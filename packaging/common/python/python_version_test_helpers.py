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

CHECK_SCRIPT_PATH = str(
    Path(__file__).with_name("check-supported-python-versions.py"))

PRINT_SCRIPT_PATH = str(
    Path(__file__).with_name("print-minimum-supported-python-version.py"))

PRUNE_SCRIPT_PATH = str(
    Path(__file__).with_name("prune-supported-python-versions.py"))

SHIPPED_SUPPORTED_PYTHON_VERSIONS_FILE = (
    Path(__file__).parents[2] / "builder"
    / "supported_python_versions.json")

FOUR_SUPPORTED_PYTHON_VERSIONS_JSON = '["3.10", "3.11", "3.12", "3.13"]\n'


def write_dist_info_with_requires_python(
        payload_directory, name, version, requires_python):
    """Create a <name>-<version>.dist-info/METADATA under payload_directory.

    This is the minimum importlib.metadata needs to enumerate a distribution
    and report its Requires-Python, so a payload can be assembled offline
    without installing anything.
    """
    dist_info_directory = payload_directory / "{}-{}.dist-info".format(
        name, version)
    dist_info_directory.mkdir(parents=True)
    (dist_info_directory / "METADATA").write_text(
        "Metadata-Version: 2.1\n"
        "Name: {}\n"
        "Version: {}\n"
        "Requires-Python: {}\n".format(name, version, requires_python),
        encoding="utf-8")


def write_supported_python_versions_file(
        supported_python_versions_path, versions):
    """Write a versions file listing the given "major.minor" strings."""
    supported_python_versions_path.write_text(
        dumps(list(versions)) + "\n", encoding="utf-8")


def run_payload_script(
        script_path, payload_directory, vendor_directory,
        supported_python_versions_path):
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
