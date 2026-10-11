# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Fixtures shared by the supported Python version test modules.

The file name deliberately does not match the test_*.py pattern that
"unittest discover" uses, so this module is imported by the test modules
rather than collected as one.
"""

from json import dumps
from pathlib import Path
from subprocess import run
from sys import executable

_TOOLS_DIRECTORY = Path(__file__).resolve().parents[1] / "tools"

CHECK_SCRIPT_PATH = str(
    _TOOLS_DIRECTORY / "check_supported_python_versions.py")

PRINT_SCRIPT_PATH = str(
    _TOOLS_DIRECTORY / "print_minimum_supported_python_version.py")

PRUNE_SCRIPT_PATH = str(
    _TOOLS_DIRECTORY / "prune_supported_python_versions.py")

SHIPPED_SUPPORTED_PYTHON_VERSIONS_FILE = (
    Path(__file__).resolve().parents[3] / "packaging" / "builder"
    / "supported_python_versions.json")


def write_dist_info_with_requires_python(
    payload_directory, name, version, requires_python
):
    """Create a <name>-<version>.dist-info/METADATA under payload_directory.

    This is the minimum importlib.metadata needs to enumerate a distribution
    and report its Requires-Python, so a payload can be assembled offline
    without installing anything. Passing None for requires_python omits the
    field, which is how a distribution that constrains nothing looks.
    """
    dist_info_directory = payload_directory / "{}-{}.dist-info".format(
        name, version)
    dist_info_directory.mkdir(parents=True)
    metadata = (
        "Metadata-Version: 2.1\n"
        "Name: {}\n"
        "Version: {}\n".format(name, version))
    if requires_python is not None:
        metadata += "Requires-Python: {}\n".format(requires_python)
    (dist_info_directory / "METADATA").write_text(
        metadata, encoding="utf-8")


def write_supported_python_versions_file(
    supported_python_versions_path, versions
):
    """Write a versions file listing the given "major.minor" strings."""
    supported_python_versions_path.write_text(
        dumps(list(versions)) + "\n", encoding="utf-8")


def run_payload_script(
    script_path, payload_directory, vendor_directory,
    supported_python_versions_path
):
    """Run a payload script's work phase and return the completed run.

    Passing --payload-dir selects the work phase directly, so no virtualenv
    is built and no distribution is downloaded.
    """
    return run(
        [
            executable, script_path,
            "--payload-dir", str(payload_directory),
            "--vendor-dir", str(vendor_directory),
            "--supported-python-versions-file",
            str(supported_python_versions_path),
        ],
        capture_output=True, text=True)
