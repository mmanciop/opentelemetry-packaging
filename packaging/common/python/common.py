# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Definitions and shared code for the supported Python version scripts.

This docstring is the single definition of the three terms below. Everywhere
else in the repository that needs them refers here instead of restating them,
so that there is exactly one place to correct if any of them changes.

Supported Python versions
    The Python versions the package is built for, listed in
    packaging/builder/supported_python_versions.json:

        ["3.10", "3.11", "3.12", "3.13"]

    A person maintains that list by hand. packaging/builder/download.go
    embeds it, the builder resolves and installs the payload once per entry,
    and it writes the same set into the sitecustomize.py version gate, so the
    file is the single hand-maintained statement of which interpreters the
    package supports. The gate is generated from it and must not be edited
    directly.

Minimum supported Python version
    The lowest of the supported Python versions. Currently 3.10.

Minimum required Python version
    The maximum, over every distribution the package bundles, of the lowest
    Python version that distribution's Requires-Python admits. "Every
    distribution the package bundles" means both those found in the payload
    directory named by --payload-dir and those whose pyproject.toml is found
    under --vendor-dir. No person writes this value down; it is computed.

    It is the maximum of the per-distribution minimums rather than the
    minimum, because a Python version works for the package only if it works
    for every bundled distribution at once, and the lowest version that
    satisfies all of them is the strictest of their individual lower bounds.

    Note that this is the algorithm and not the stronger property "the lowest
    Python version on which every bundled distribution installs". The two
    coincide only while every Requires-Python is a plain lower bound such as
    ">=3.10", which is true of all of them today. A specifier carrying an
    exclusion, such as ">=3.9,!=3.10.*", would contribute a minimum of 3.9
    and nothing here would notice that 3.10 is excluded.

The three scripts that import this module
    print-minimum-supported-python-version.py prints the minimum supported
    Python version and exits. CI runs it to decide which interpreter to
    install before running the check.

    check-supported-python-versions.py exits 1 when a supported Python
    version is below the minimum required Python version.

    prune-supported-python-versions.py drops the supported Python versions
    that are below the minimum required Python version.

check-supported-python-versions.py and prune-supported-python-versions.py
each run in two phases, in two different interpreters.

The preparation phase runs under whatever python3 invoked the script. It
builds a virtualenv with the interpreter for the minimum supported Python
version, installs the scripts' own dependencies into it, installs the PyPI
pins from requirements.txt into a payload directory with "pip install
--target", and then re-invokes the same script with that interpreter and
--payload-dir. MINIMUM_SUPPORTED_PYTHON_INTERPRETER overrides the interpreter
it looks for, and BUILD_DIR overrides where the virtualenv and the payload are
written (default: build/ at the repository root, which "make clean" removes).

The work phase is the re-invocation. It runs inside that virtualenv, where
packaging and tomli are importable, and it does the derivation and then the
check or the prune. Passing --payload-dir directly selects this phase without
any preparation, which is what the unit tests do.

The virtualenv is built with the interpreter for the minimum supported Python
version on purpose: its pip must resolve the payload's transitive dependencies
the way it would on that version, so a newer release of a transitive
dependency that raised its own Requires-Python does not inflate the minimum
required Python version above what actually runs there.

The vendored requires-python values are read straight from each vendor
pyproject.toml under --vendor-dir, so the vendored source never has to be
built for the check.

A supported Python version below the minimum required Python version is an
error: pip cannot resolve the payload for an interpreter the bundled
distributions reject, so the build either fails or ships something that cannot
run. A minimum required Python version below every supported Python version is
not an error. The top of the list is governed by whether wheels exist rather
than by Requires-Python, and declining to ship an interpreter the dependencies
would permit is a deliberate choice.

Keeping the supported Python versions in a data file rather than in the Go
source is what lets these scripts read and rewrite them with a JSON parser.
Extracting a Go slice literal with a regular expression cannot tell a live
entry from one inside a // comment.

The payload directory holds what a "pip install --target" of requirements.txt
produces, which is what packaging/builder/download.go writes into the DEB and
the RPM. Scoping the enumeration to that directory keeps distributions that
never ship out of the derivation: pip and setuptools, which "python -m venv"
creates in the virtualenv, and tomli, which only these scripts import. Since
the minimum required Python version is a maximum, a distribution that does not
ship can only raise it and never lower it, so including one would mask a value
that should drop while the check still reported the list as in sync. That is
why the payload is installed with --target rather than into the virtualenv.

These scripts only handle 3.x interpreters. If the minimum required Python
version has a major version other than 3, they exit with an error asking for a
refactor.
"""

from argparse import ArgumentParser, RawDescriptionHelpFormatter
from importlib.metadata import distributions
from json import JSONDecodeError, dumps, loads
from os import environ
from os.path import dirname, join
from pathlib import Path
from shutil import rmtree, which
from subprocess import CalledProcessError, run
from sys import stderr

# packaging and tomli are imported where they are used rather than here,
# because the preparation phase runs under whatever python3 invoked the script
# and neither is installed there. Only the work phase, which runs inside the
# virtualenv the preparation phase builds, can import them.

# The lowest major.minor pairs we scan when probing a specifier for the lowest
# version it admits. Python 3 minors are the realistic range for this project;
# major 4 is included so that a future 4.x-only minimum is detected and
# reported as needing a refactor rather than silently mis-derived.
_CANDIDATE_PYTHON_VERSIONS = [(3, minor) for minor in range(0, 31)] + [
    (4, minor) for minor in range(0, 31)
]

SUPPORTED_PYTHON_VERSIONS_FILE_NAME = "supported_python_versions.json"

_SCRIPT_DIRECTORY = dirname(__file__)


class MinimumRequiredPythonVersionError(Exception):
    """The minimum required Python version could not be derived or is 4.x."""


def build_argument_parser(description):
    """Return a parser carrying the option every script in this set takes."""
    argument_parser = ArgumentParser(
        description=description,
        formatter_class=RawDescriptionHelpFormatter)
    argument_parser.add_argument(
        "--supported-python-versions-file",
        default=join(
            _SCRIPT_DIRECTORY, "..", "..", "builder",
            SUPPORTED_PYTHON_VERSIONS_FILE_NAME),
        help="path to the JSON array of supported Python versions that "
             "packaging/builder/download.go embeds "
             "(default: the one in this repository)")
    return argument_parser


def add_payload_arguments(argument_parser):
    """Add the options naming where the bundled distributions are found."""
    argument_parser.add_argument(
        "--payload-dir",
        default=None,
        help="directory holding the distributions that ship in the package, "
             "as produced by pip install --target; only the distributions "
             "found there contribute to the minimum required Python version. "
             "Omit it to run the preparation phase, which builds the payload "
             "and then re-invokes this script with the directory it built")
    argument_parser.add_argument(
        "--vendor-dir",
        default=join(_SCRIPT_DIRECTORY, "vendor"),
        help="directory tree searched for vendored pyproject.toml files "
             "(default: the vendor dir next to this script)")


def read_supported_python_versions(supported_python_versions_text):
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
    versions = []
    for entry in parsed:
        major, _, minor = entry.partition(".") if isinstance(
            entry, str) else ("", "", "")
        if not major.isdigit() or not minor.isdigit():
            raise ValueError(
                '{} entries must be strings like "3.10", found {!r}'.format(
                    SUPPORTED_PYTHON_VERSIONS_FILE_NAME, entry))
        versions.append((int(major), int(minor)))
    return versions


def prune_supported_python_versions(
        supported_python_versions_text, minimum_required_python_version):
    """Return the supported Python versions JSON without the ones below.

    minimum_required_python_version is a (major, minor) pair. Raises
    ValueError if pruning would empty the list, which would mean no
    interpreter the builder knows about can run the bundled distributions
    at all.
    """
    kept = [
        version
        for version in read_supported_python_versions(
            supported_python_versions_text)
        if version >= minimum_required_python_version]
    if not kept:
        raise ValueError(
            "pruning to the minimum required Python version {}.{} would "
            "empty {}".format(
                *minimum_required_python_version,
                SUPPORTED_PYTHON_VERSIONS_FILE_NAME))
    return dumps(["{}.{}".format(*version) for version in kept]) + "\n"


def format_python_versions(versions):
    """Return a comma-separated "major.minor" rendering of the given pairs."""
    return ", ".join("{}.{}".format(*version) for version in versions)


def derive_minimum_required_python_version(requires_python_strings):
    """Return the minimum required Python version as a (major, minor) pair.

    See the module docstring for what that value is and why it is a maximum
    of per-distribution minimums. Each item is a Requires-Python string, for
    example ">=3.10" or "~=3.11,!=3.12.*". Strings that are empty or None are
    ignored, because a distribution that declares no Requires-Python
    constrains nothing. Returns None when no item constrains anything.
    """
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    per_specifier_minimums = []
    for requires_python in requires_python_strings:
        if not requires_python:
            continue
        specifier_set = SpecifierSet(requires_python)
        lowest_admitted = None
        for major, minor in _CANDIDATE_PYTHON_VERSIONS:
            if specifier_set.contains(Version("{}.{}".format(major, minor))):
                lowest_admitted = (major, minor)
                break
        if lowest_admitted is not None:
            per_specifier_minimums.append(lowest_admitted)
    if not per_specifier_minimums:
        return None
    return max(per_specifier_minimums)


def derive_minimum_required_python_version_from_bundled_distributions(
        payload_directory, vendor_directory):
    """Return the minimum required Python version of what the package ships.

    Reads Requires-Python from every distribution installed in
    payload_directory and requires-python from every pyproject.toml under
    vendor_directory, then derives the value as the module docstring
    describes. Raises MinimumRequiredPythonVersionError when the payload
    directory is missing or empty, when nothing declared a constraint, or
    when the derived major version is not 3.
    """
    # The enumeration is scoped to the payload directory with path=; called
    # with no arguments, distributions() would walk the running interpreter's
    # sys.path and pick up pip, setuptools and tomli, which the DEB and the
    # RPM never ship.
    shipped_distributions = list(distributions(path=[payload_directory]))
    if not shipped_distributions:
        raise MinimumRequiredPythonVersionError(
            "no distributions found in payload directory {}: it is missing "
            "or empty, and must be populated with pip install --target "
            "before running this script".format(payload_directory))
    requires_python_strings = [
        distribution.metadata["Requires-Python"]
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

    minimum_required_python_version = derive_minimum_required_python_version(
        requires_python_strings)
    if minimum_required_python_version is None:
        raise MinimumRequiredPythonVersionError(
            "could not derive the minimum required Python version: no "
            "distribution or vendored pyproject declared Requires-Python")
    if minimum_required_python_version[0] != 3:
        raise MinimumRequiredPythonVersionError(
            "the minimum required Python version has major version {}, not "
            "3; {} and the sitecustomize.py gate only support 3.x and must "
            "be updated for major-version bumps".format(
                minimum_required_python_version[0],
                SUPPORTED_PYTHON_VERSIONS_FILE_NAME))
    return minimum_required_python_version


def prepare_payload_and_rerun_in_the_virtualenv(
        script_path, minimum_supported_python_version, arguments):
    """Build the virtualenv and the payload, then rerun script_path in it.

    This is the preparation phase the module docstring describes. Returns the
    exit status the caller should exit with: the rerun script's own status, or
    a non-zero one if a preparation step failed.
    """
    interpreter_name = environ.get(
        "MINIMUM_SUPPORTED_PYTHON_INTERPRETER",
        "python{}.{}".format(*minimum_supported_python_version))
    interpreter = which(interpreter_name)
    if interpreter is None:
        print(
            "error: {} is not installed. The minimum required Python "
            "version must be derived with the interpreter for the minimum "
            "supported Python version, so that pip resolves transitive "
            "dependencies the way it does there. Install it, or set "
            "MINIMUM_SUPPORTED_PYTHON_INTERPRETER to that "
            "interpreter.".format(interpreter_name),
            file=stderr)
        return 1

    repository_root = Path(_SCRIPT_DIRECTORY).resolve().parents[2]
    build_directory = Path(
        environ.get("BUILD_DIR", str(repository_root / "build")))
    venv_directory = (
        build_directory / "minimum-supported-python-version-venv")
    payload_directory = (
        build_directory / "minimum-supported-python-version-payload")
    pinned_requirements_path = (
        build_directory / "minimum-supported-python-version-requirements.txt")

    with open(join(_SCRIPT_DIRECTORY, "requirements.txt"),
              encoding="utf-8") as requirements_file:
        pinned_requirements = [
            line for line in requirements_file.read().splitlines()
            if not line.startswith("./vendor/")]
    build_directory.mkdir(parents=True, exist_ok=True)
    pinned_requirements_path.write_text(
        "\n".join(pinned_requirements) + "\n", encoding="utf-8")
    rmtree(payload_directory, ignore_errors=True)

    venv_python = str(venv_directory / "bin" / "python")
    for command in (
            [interpreter, "-m", "venv", "--clear", str(venv_directory)],
            [venv_python, "-m", "pip", "install", "--quiet",
             "packaging", "tomli"],
            [venv_python, "-m", "pip", "install", "--quiet",
             "--target", str(payload_directory),
             "-r", str(pinned_requirements_path)]):
        try:
            run(command, check=True)
        except CalledProcessError as error:
            print(
                "error: preparation step failed with exit status {}: "
                "{}".format(error.returncode, " ".join(command)),
                file=stderr)
            return error.returncode

    return run([
        venv_python, script_path,
        "--payload-dir", str(payload_directory),
        "--vendor-dir", arguments.vendor_dir,
        "--supported-python-versions-file",
        arguments.supported_python_versions_file]).returncode
