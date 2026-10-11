# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for prune-supported-python-versions.py."""

from json import loads
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from common import read_supported_python_versions
from python_version_test_helpers import (
    PRUNE_SCRIPT_PATH,
    SHIPPED_SUPPORTED_PYTHON_VERSIONS_FILE,
    run_payload_script,
    write_dist_info_with_requires_python,
    write_supported_python_versions_file,
)


class TestPruneSupportedPythonVersions(TestCase):

    def test_prune_drops_the_supported_python_versions_below_the_minimum_required_python_version(
            self):
        # The versions the package ships go in, and a vendored pyproject
        # demanding the second-lowest of them puts the minimum required
        # Python version there, so the prune must drop the lowest one and
        # keep every other. They are read from the shipped file rather than
        # restated here, so that editing that file cannot leave this test
        # asserting against a list the package no longer ships.
        shipped_text = SHIPPED_SUPPORTED_PYTHON_VERSIONS_FILE.read_text(
            encoding="utf-8")
        shipped_versions = sorted(
            read_supported_python_versions(shipped_text))
        self.assertGreater(
            len(shipped_versions), 1,
            "this test needs at least two supported Python versions")

        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            write_dist_info_with_requires_python(
                payload_directory, "shipped_thing", "1.0",
                ">={}.{}".format(*shipped_versions[0]))
            vendor_directory = temporary_path / "vendor" / "high-requirement"
            vendor_directory.mkdir(parents=True)
            (vendor_directory / "pyproject.toml").write_text(
                "[project]\n"
                'name = "high-requirement"\n'
                'requires-python = ">={}.{}"\n'.format(*shipped_versions[1]),
                encoding="utf-8")
            supported_python_versions_path = (
                temporary_path / "supported_python_versions.json")
            supported_python_versions_path.write_text(
                shipped_text, encoding="utf-8")

            completed = run_payload_script(
                PRUNE_SCRIPT_PATH, payload_directory,
                temporary_path / "vendor", supported_python_versions_path)
            self.assertEqual(completed.returncode, 0, completed.stderr)

            rewritten = supported_python_versions_path.read_text(
                encoding="utf-8")

        self.assertEqual(
            loads(rewritten),
            ["{}.{}".format(*version) for version in shipped_versions[1:]])

    def test_prune_writes_nothing_when_no_version_is_below(self):
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            write_dist_info_with_requires_python(
                payload_directory, "shipped_thing", "1.0", ">=3.10")
            vendor_directory = temporary_path / "vendor"
            vendor_directory.mkdir()
            supported_python_versions_path = (
                temporary_path / "supported_python_versions.json")
            write_supported_python_versions_file(
                supported_python_versions_path, ["3.11", "3.12"])
            before = supported_python_versions_path.read_text(
                encoding="utf-8")

            completed = run_payload_script(
                PRUNE_SCRIPT_PATH, payload_directory, vendor_directory,
                supported_python_versions_path)

            after = supported_python_versions_path.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("nothing to prune", completed.stdout)
        self.assertEqual(before, after)
