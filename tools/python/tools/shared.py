# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Definitions and shared code for the supported Python version scripts.

This docstring is the single definition of the three terms below. Everywhere
else in the repository that needs them refers here instead of restating them,
so that there is exactly one place to correct if any of them changes.

Supported Python versions
    The Python versions the package is built for, listed in
    packaging/builder/supported_python_versions.json as a JSON array of
    "major.minor" strings. Read that file for the current list. It is not
    repeated here, nor in any test, so that editing it cannot leave a second
    copy naming interpreters the package no longer ships.

    A person maintains that list by hand. packaging/builder/download.go
    embeds it, the builder resolves the bundled distributions once per
    supported Python version, and it writes the same list into the
    sitecustomize.py version gate, so the file is the single
    hand-maintained statement of which interpreters the package supports.
    The gate is generated from it and must not be edited directly.

Minimum supported Python version
    The lowest of the supported Python versions.
    print_minimum_supported_python_version.py prints it.

Minimum required Python version
    The maximum, over every distribution the package bundles, of the lowest
    Python version that distribution's Requires-Python admits. "Every
    distribution the package bundles" means both those found in the
    bundled distributions directory named by --bundled-distributions-dir
    and those whose pyproject.toml is found under --vendor-dir. No person
    writes this value down; it is computed.

    It is the maximum of the per-distribution minimums rather than the
    minimum, because a Python version works for the package only if it works
    for every bundled distribution at once, and the lowest version that
    satisfies all of them is the strictest of their individual lower bounds.

    Raised, when the work phase is given --lowest-resolvable-python-version,
    to at least the lowest supported Python version pip could resolve the
    pins for. Reading Requires-Python is the weaker test: it would miss a
    specifier carrying an exclusion, such as ">=3.9,!=3.10.*", which
    contributes a minimum of 3.9 while 3.10 is excluded, and it would miss a
    version for which no wheel is published at all. Whether pip can resolve
    the pins for a version is the property that actually decides whether the
    package can be built for it, so where the two disagree the resolution
    wins.

The three scripts that import this module
    print_minimum_supported_python_version.py prints the minimum supported
    Python version and exits. It is the way to read that value out of the
    data file without a JSON parser at the call site.

    check_supported_python_versions.py exits 1 when a supported Python
    version is below the minimum required Python version.

    prune_supported_python_versions.py drops the supported Python versions
    that are below the minimum required Python version. It owns the pruning
    itself, since no other script needs it; this module holds only what more
    than one script in this directory uses.

check_supported_python_versions.py and prune_supported_python_versions.py
each run in two phases.

The preparation phase runs under whatever python3 invoked the script. It
builds a virtualenv with that same interpreter, installs the scripts' own
dependencies into it, resolves the PyPI pins from requirements.txt into a
bundled distributions directory with "pip install --target", and then
re-invokes the same script with --bundled-distributions-dir. BUILD_DIR
overrides where the virtualenv and the bundled distributions are written
(default: build/ at the repository root, which "make clean" removes).

The work phase is the re-invocation. It runs inside that virtualenv, where
packaging and tomli are importable, and it does the derivation and then the
check or the prune. Passing --bundled-distributions-dir directly selects
this phase without any preparation, which is what the unit tests do.

The bundled distributions are resolved with "--python-version <target>
--only-binary=:all:" rather than by running the target interpreter, which
is how packaging/builder/download.go resolves it too. pip treats
--python-version as a resolution target, so transitive dependencies resolve
the way they would on that version without that interpreter being installed
anywhere. A newer release of a transitive dependency that raised its own
Requires-Python therefore does not inflate the minimum required Python
version above what actually runs there.

The preparation phase resolves for each supported Python version in ascending
order and stops at the first one that resolves, which is one resolution in the
ordinary case. A version pip cannot resolve the pins for is one the package
can no longer be built for, whatever the metadata says, so the lowest
supported Python version that resolves is a floor on the minimum required
Python version and is passed to the work phase as
--lowest-resolvable-python-version. Without that floor, a bump that raises a
pin's Requires-Python above the minimum supported Python version would stop
the preparation phase on a pip error before the derivation ever ran, which is
also what stopped prune_supported_python_versions.py from being able to fix
it.

The vendored requires-python values are read straight from each vendor
pyproject.toml under --vendor-dir, so the vendored source never has to be
built for the check.

A supported Python version below the minimum required Python version is an
error: pip cannot resolve the pins for an interpreter the bundled
distributions reject, so the build either fails or ships something that
cannot run. A minimum required Python version below every supported Python
version is not an error. The top of the list is governed by whether wheels
exist rather than by Requires-Python, and declining to ship an interpreter
the dependencies would permit is a deliberate choice.

Keeping the supported Python versions in a data file rather than in the Go
source is what lets these scripts read and rewrite them with a JSON parser.
Extracting a Go slice literal with a regular expression cannot tell a live
entry from one inside a // comment.

The bundled distributions directory holds what a "pip install --target" of
requirements.txt produces, which is what packaging/builder/download.go
writes into the DEB and the RPM. Scoping the enumeration to that directory
keeps distributions that never ship out of the derivation: pip and
setuptools, which "python -m venv" creates in the virtualenv, and tomli,
which only these scripts import. Since the minimum required Python version
is a maximum, a distribution that does not ship can only raise it and never
lower it, so including one would mask a value that should drop while the
check still reported the list as in sync. That is why the bundled
distributions are installed with --target rather than into the virtualenv.

These scripts only handle 3.x interpreters. If the minimum required Python
version has a major version other than 3, they exit with an error asking for a
refactor.
"""

from argparse import (
    ArgumentParser,
    Namespace,
    RawDescriptionHelpFormatter,
)
from collections.abc import Iterable
from importlib.metadata import distributions
from json import JSONDecodeError, loads
from os import environ
from pathlib import Path
from shutil import rmtree
from subprocess import CalledProcessError, run
from sys import executable, stderr

# packaging and tomli are imported where they are used rather than here,
# because the preparation phase runs under whatever python3 invoked the script
# and neither is installed there. Only the work phase, which runs inside the
# virtualenv the preparation phase builds, can import them.

# The lowest major.minor pairs we scan when probing a specifier for the lowest
# version it admits. Python 3 minors are the realistic range for this project;
# major 4 is included so that a future 4.x-only minimum is detected and
# reported as needing a refactor rather than silently mis-derived.
_CANDIDATE_PYTHON_VERSIONS: list[tuple[int, int]] = [
    (3, minor) for minor in range(0, 31)
] + [
    (4, minor) for minor in range(0, 31)
]

SUPPORTED_PYTHON_VERSIONS_FILE_NAME: str = (
    "supported_python_versions.json")

# These scripts live outside packaging/, so every path they need is
# derived from the repository root rather than from the directory they
# sit in.
_REPOSITORY_ROOT: Path = Path(__file__).resolve().parents[3]

_PYTHON_PACKAGING_DIRECTORY: Path = (
    _REPOSITORY_ROOT / "packaging" / "common" / "python")


class MinimumRequiredPythonVersionError(Exception):
    """The minimum required Python version could not be derived or is 4.x."""


def build_argument_parser(description: str) -> ArgumentParser:
    """Return a parser carrying the option every script in this set takes."""
    argument_parser = ArgumentParser(
        description=description,
        formatter_class=RawDescriptionHelpFormatter)
    argument_parser.add_argument(
        "--supported-python-versions-file",
        default=str(
            _REPOSITORY_ROOT / "packaging" / "builder"
            / SUPPORTED_PYTHON_VERSIONS_FILE_NAME),
        help="path to the JSON array of supported Python versions that "
             "packaging/builder/download.go embeds "
             "(default: the one in this repository)")
    return argument_parser


def add_bundled_distributions_arguments(
    argument_parser: ArgumentParser
) -> None:
    """Add the options naming where the bundled distributions are found."""
    argument_parser.add_argument(
        "--bundled-distributions-dir",
        default=None,
        help="directory holding the bundled distributions, as produced by "
             "pip install --target; only the bundled distributions found "
             "there contribute to the minimum required Python version. "
             "Omit it to run the preparation phase, which builds the "
             "bundled distributions and then re-invokes this script with "
             "the directory it built")
    argument_parser.add_argument(
        "--vendor-dir",
        default=str(_PYTHON_PACKAGING_DIRECTORY / "vendor"),
        help="directory tree searched for vendored pyproject.toml files "
             "(default: packaging/common/python/vendor)")
    argument_parser.add_argument(
        "--lowest-resolvable-python-version",
        default=None,
        type=python_version_pair,
        help="the lowest supported Python version pip could resolve the "
             "pinned requirements for, as a \"major.minor\" string. The "
             "preparation phase passes what it found; it raises the minimum "
             "required Python version to at least this, so that a version no "
             "longer resolvable is reported even when the metadata alone "
             "would not show it")


def python_version_pair(version_text: str) -> tuple[int, int]:
    """Return the (major, minor) pair for a "major.minor" string.

    Raises ValueError when version_text is not two dot-separated numbers.
    """
    major, _, minor = version_text.partition(".")
    if not major.isdigit() or not minor.isdigit():
        raise ValueError(
            'expected a version like "3.10", found {!r}'.format(version_text))
    return (int(major), int(minor))


def read_supported_python_versions(
    supported_python_versions_text: str
) -> list[tuple[int, int]]:
    """Return the (major, minor) pairs of the supported Python versions.

    Takes the text of packaging/builder/supported_python_versions.json, which
    holds a JSON array of "major.minor" strings. Raises ValueError if the
    document is not such an array or lists no version.
    """
    try:
        parsed = loads(supported_python_versions_text)
    except JSONDecodeError as error:
        raise ValueError(
            "{} is not valid JSON: {}".format(
                SUPPORTED_PYTHON_VERSIONS_FILE_NAME, error)) from error
    if not isinstance(parsed, list):
        raise ValueError(
            "{} must hold a JSON array, found {}".format(
                SUPPORTED_PYTHON_VERSIONS_FILE_NAME, type(parsed).__name__))
    if not parsed:
        raise ValueError(
            "{} lists no version".format(
                SUPPORTED_PYTHON_VERSIONS_FILE_NAME))
    versions: list[tuple[int, int]] = []
    for entry in parsed:
        try:
            versions.append(python_version_pair(entry))
        except (AttributeError, ValueError) as error:
            raise ValueError(
                '{} entries must be strings like "3.10", found {!r}'.format(
                    SUPPORTED_PYTHON_VERSIONS_FILE_NAME, entry)) from error
    return versions


def format_python_versions(versions: Iterable[tuple[int, int]]) -> str:
    """Return a comma-separated "major.minor" rendering of the given pairs."""
    return ", ".join("{}.{}".format(*version) for version in versions)


def derive_minimum_required_python_version_from_bundled_distributions(
    bundled_distributions_directory: str, vendor_directory: str
) -> tuple[int, int]:
    """Return the minimum required Python version of what the package ships.

    Reads Requires-Python from every distribution installed in
    bundled_distributions_directory and requires-python from every
    pyproject.toml under vendor_directory, then derives the value as the
    module docstring describes. Raises MinimumRequiredPythonVersionError
    when the bundled distributions directory is missing or empty, when
    nothing declared a constraint, or when the derived major version is
    not 3.
    """
    # The enumeration is scoped to the bundled distributions directory with
    # path=; called with no arguments, distributions() would walk the
    # running interpreter's sys.path and pick up pip, setuptools and tomli,
    # which the DEB and the RPM never ship.
    shipped_distributions = list(
        distributions(path=[bundled_distributions_directory]))
    if not shipped_distributions:
        raise MinimumRequiredPythonVersionError(
            "no bundled distributions found in {}: it is missing "
            "or empty, and must be populated with pip install --target "
            "before running this script".format(
                bundled_distributions_directory))
    # .get rather than subscripting: a distribution that declares no
    # Requires-Python has no such field, and subscripting a missing field is
    # deprecated and slated to raise KeyError.
    requires_python_strings = [
        distribution.metadata.get("Requires-Python")
        for distribution in shipped_distributions]

    try:
        from tomllib import load
    except ModuleNotFoundError:
        from tomli import load
    for pyproject_path in Path(vendor_directory).rglob("pyproject.toml"):
        with open(pyproject_path, "rb") as pyproject_file:
            pyproject_data = load(pyproject_file)
        requires_python_strings.append(
            pyproject_data.get("project", {}).get("requires-python"))

    # Each Requires-Python is reduced to the lowest candidate version it
    # admits, and the answer is the maximum of those. A string that is empty
    # or None is skipped, because a distribution declaring no Requires-Python
    # constrains nothing.
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    per_distribution_minimums: list[tuple[int, int]] = []
    for requires_python in requires_python_strings:
        if not requires_python:
            continue
        specifier_set = SpecifierSet(requires_python)
        for candidate_version in _CANDIDATE_PYTHON_VERSIONS:
            if specifier_set.contains(
                    Version("{}.{}".format(*candidate_version))):
                per_distribution_minimums.append(candidate_version)
                break

    if not per_distribution_minimums:
        raise MinimumRequiredPythonVersionError(
            "could not derive the minimum required Python version: no "
            "distribution or vendored pyproject declared Requires-Python")
    minimum_required_python_version = max(per_distribution_minimums)
    if minimum_required_python_version[0] != 3:
        raise MinimumRequiredPythonVersionError(
            "the minimum required Python version has major version {}, not "
            "3; {} and the sitecustomize.py gate only support 3.x and must "
            "be updated for major-version bumps".format(
                minimum_required_python_version[0],
                SUPPORTED_PYTHON_VERSIONS_FILE_NAME))
    return minimum_required_python_version


def prepare_bundled_distributions_and_rerun_in_the_virtualenv(
    script_path: str,
    supported_python_versions: list[tuple[int, int]],
    arguments: Namespace,
) -> int:
    """Build the virtualenv and bundled distributions, rerun script_path.

    This is the preparation phase the module docstring describes. Resolves the
    pins for each supported Python version in ascending order, stopping at the
    first that resolves, and passes that version to the work phase as
    --lowest-resolvable-python-version. Returns the exit status the caller
    should exit with: the rerun script's own status, or a non-zero one if a
    preparation step failed.
    """
    build_directory = Path(
        environ.get("BUILD_DIR", str(_REPOSITORY_ROOT / "build")))
    venv_directory = (
        build_directory / "minimum-supported-python-version-venv")
    bundled_distributions_directory = build_directory / (
        "minimum-supported-python-version-bundled-distributions")
    pinned_requirements_path = (
        build_directory / "minimum-supported-python-version-requirements.txt")

    pinned_requirements = [
        line for line
        in (_PYTHON_PACKAGING_DIRECTORY / "requirements.txt").read_text(
            encoding="utf-8").splitlines()
        if not line.startswith("./vendor/")]
    build_directory.mkdir(parents=True, exist_ok=True)
    pinned_requirements_path.write_text(
        "\n".join(pinned_requirements) + "\n", encoding="utf-8")
    venv_python = str(venv_directory / "bin" / "python")
    for command in (
            [executable, "-m", "venv", "--clear", str(venv_directory)],
            [venv_python, "-m", "pip", "install", "--quiet",
             "packaging", "tomli"]):
        try:
            run(command, check=True)
        except CalledProcessError as error:
            print(
                "error: preparation step failed with exit status {}: "
                "{}".format(error.returncode, " ".join(command)),
                file=stderr)
            return error.returncode

    lowest_resolvable_python_version: tuple[int, int] | None = None
    for python_version in sorted(supported_python_versions):
        rmtree(bundled_distributions_directory, ignore_errors=True)
        resolution = run([
            venv_python, "-m", "pip", "install", "--quiet",
            "--target", str(bundled_distributions_directory),
            "--python-version", "{}.{}".format(*python_version),
            "--only-binary=:all:",
            "-r", str(pinned_requirements_path)])
        if resolution.returncode == 0:
            lowest_resolvable_python_version = python_version
            break
        print(
            "note: pip cannot resolve {} for Python {}.{}, so the package "
            "can no longer be built for it".format(
                pinned_requirements_path.name, *python_version),
            file=stderr)

    if lowest_resolvable_python_version is None:
        print(
            "error: pip cannot resolve {} for any supported Python version "
            "({}). Every supported Python version would have to be dropped, "
            "which would leave {} empty, so this needs a pin reverted or a "
            "newer interpreter added by hand.".format(
                pinned_requirements_path.name,
                format_python_versions(sorted(supported_python_versions)),
                SUPPORTED_PYTHON_VERSIONS_FILE_NAME),
            file=stderr)
        return 1

    return run([
        venv_python, script_path,
        "--bundled-distributions-dir", str(bundled_distributions_directory),
        "--vendor-dir", arguments.vendor_dir,
        "--lowest-resolvable-python-version",
        "{}.{}".format(*lowest_resolvable_python_version),
        "--supported-python-versions-file",
        arguments.supported_python_versions_file]).returncode
