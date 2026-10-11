# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for check-supported-python-versions.py."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from python_version_test_helpers import (
    CHECK_SCRIPT_PATH,
    run_payload_script,
    write_dist_info_with_requires_python,
    write_supported_python_versions_file,
)


class TestPayloadScopedEnumeration(TestCase):

    def test_minimum_required_python_version_comes_only_from_the_payload_directory(
            self):
        # The payload declares a single distribution at >=3.7, so the
        # minimum required Python version is 3.7. The interpreter running
        # this test has packaging installed (>=3.9), plus pip and
        # setuptools from the throwaway venv the python-unit-tests target
        # builds. An enumeration that walked sys.path instead of
        # --payload-dir would derive at least 3.9 from those, so seeing
        # 3.7 reported is what proves the enumeration is scoped to the
        # payload.
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            write_dist_info_with_requires_python(
                payload_directory, "shipped_thing", "1.0", ">=3.7")
            vendor_directory = temporary_path / "vendor"
            vendor_directory.mkdir()
            supported_python_versions_path = (
                temporary_path / "supported_python_versions.json")
            write_supported_python_versions_file(
                supported_python_versions_path, ["3.7", "3.8"])

            completed = run_payload_script(
                CHECK_SCRIPT_PATH, payload_directory, vendor_directory,
                supported_python_versions_path)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("minimum required Python version: 3.7", completed.stdout)

    def test_strictest_payload_distribution_decides_the_minimum_required_python_version(
            self):
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            write_dist_info_with_requires_python(
                payload_directory, "lenient_thing", "1.0", ">=3.9")
            write_dist_info_with_requires_python(
                payload_directory, "strict_thing", "2.0", ">=3.11")
            vendor_directory = temporary_path / "vendor"
            vendor_directory.mkdir()
            supported_python_versions_path = (
                temporary_path / "supported_python_versions.json")
            write_supported_python_versions_file(
                supported_python_versions_path, ["3.11", "3.12"])

            completed = run_payload_script(
                CHECK_SCRIPT_PATH, payload_directory, vendor_directory,
                supported_python_versions_path)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "minimum required Python version: 3.11", completed.stdout)

    def test_missing_payload_directory_fails(self):
        # A mistyped or unbuilt payload path must be an error rather than a
        # derivation from the vendored pyproject files alone, which would
        # silently report a minimum lower than the one the package ships.
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            vendor_directory = temporary_path / "vendor" / "some-package"
            vendor_directory.mkdir(parents=True)
            (vendor_directory / "pyproject.toml").write_text(
                "[project]\n"
                'name = "some-package"\n'
                'requires-python = ">=3.10"\n',
                encoding="utf-8")
            supported_python_versions_path = (
                temporary_path / "supported_python_versions.json")
            write_supported_python_versions_file(
                supported_python_versions_path, ["3.10"])

            completed = run_payload_script(
                CHECK_SCRIPT_PATH, temporary_path / "no-such-payload",
                temporary_path / "vendor", supported_python_versions_path)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("no distributions found", completed.stderr)

    def test_empty_payload_directory_fails(self):
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            payload_directory.mkdir()
            vendor_directory = temporary_path / "vendor"
            vendor_directory.mkdir()
            supported_python_versions_path = (
                temporary_path / "supported_python_versions.json")
            write_supported_python_versions_file(
                supported_python_versions_path, ["3.10"])

            completed = run_payload_script(
                CHECK_SCRIPT_PATH, payload_directory, vendor_directory,
                supported_python_versions_path)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("no distributions found", completed.stderr)


class TestVendorPyprojectParsing(TestCase):

    def test_check_reads_requires_python_from_vendor_pyproject(self):
        # The payload minimum (3.8) is below the only vendored pyproject
        # minimum (3.12), which must therefore drive the check to reject a
        # list that still starts at 3.10. This proves the script reads
        # [project].requires-python from pyproject.toml files under
        # --vendor-dir.
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            write_dist_info_with_requires_python(
                payload_directory, "shipped_thing", "1.0", ">=3.8")
            vendor_directory = temporary_path / "vendor" / "some-package"
            vendor_directory.mkdir(parents=True)
            (vendor_directory / "pyproject.toml").write_text(
                "[project]\n"
                'name = "some-package"\n'
                'requires-python = ">=3.12"\n',
                encoding="utf-8")
            supported_python_versions_path = (
                temporary_path / "supported_python_versions.json")
            write_supported_python_versions_file(
                supported_python_versions_path, ["3.10", "3.11", "3.12"])

            completed = run_payload_script(
                CHECK_SCRIPT_PATH, payload_directory,
                temporary_path / "vendor", supported_python_versions_path)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("3.12", completed.stdout)


class TestCheckOutcome(TestCase):

    def test_check_passes_when_every_supported_python_version_meets_the_minimum_required_python_version(
            self):
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            write_dist_info_with_requires_python(
                payload_directory, "shipped_thing", "1.0", ">=3.11")
            vendor_directory = temporary_path / "vendor"
            vendor_directory.mkdir()
            supported_python_versions_path = (
                temporary_path / "supported_python_versions.json")
            write_supported_python_versions_file(
                supported_python_versions_path, ["3.11", "3.12"])

            completed = run_payload_script(
                CHECK_SCRIPT_PATH, payload_directory, vendor_directory,
                supported_python_versions_path)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("are in sync", completed.stdout)

    def test_check_fails_when_a_supported_python_version_is_below_the_minimum_required_python_version(
            self):
        # This is the regression the check exists for: a dependency bump
        # raises the minimum to 3.11 while the builder still tries to resolve
        # the payload for 3.10, which pip cannot do.
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            write_dist_info_with_requires_python(
                payload_directory, "shipped_thing", "1.0", ">=3.11")
            vendor_directory = temporary_path / "vendor"
            vendor_directory.mkdir()
            supported_python_versions_path = (
                temporary_path / "supported_python_versions.json")
            write_supported_python_versions_file(
                supported_python_versions_path, ["3.10", "3.11", "3.12"])

            completed = run_payload_script(
                CHECK_SCRIPT_PATH, payload_directory, vendor_directory,
                supported_python_versions_path)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("3.10", completed.stderr)
        self.assertIn(
            "prune-supported-python-versions.py", completed.stderr)

    def test_check_leaves_the_supported_python_versions_file_untouched(self):
        # The check must never write, however stale the list is. Only
        # prune-supported-python-versions.py rewrites the file.
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            write_dist_info_with_requires_python(
                payload_directory, "shipped_thing", "1.0", ">=3.12")
            vendor_directory = temporary_path / "vendor"
            vendor_directory.mkdir()
            supported_python_versions_path = (
                temporary_path / "supported_python_versions.json")
            write_supported_python_versions_file(
                supported_python_versions_path, ["3.10", "3.11", "3.12"])
            before = supported_python_versions_path.read_text(
                encoding="utf-8")

            completed = run_payload_script(
                CHECK_SCRIPT_PATH, payload_directory, vendor_directory,
                supported_python_versions_path)

            after = supported_python_versions_path.read_text(encoding="utf-8")

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(before, after)

    def test_check_passes_with_a_note_when_the_minimum_required_python_version_is_below_every_supported_python_version(
            self):
        # Shipping fewer interpreters than the dependencies permit is a
        # deliberate choice, because wheel availability rather than
        # Requires-Python governs the top of the list, so this reports rather
        # than fails.
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            write_dist_info_with_requires_python(
                payload_directory, "shipped_thing", "1.0", ">=3.8")
            vendor_directory = temporary_path / "vendor"
            vendor_directory.mkdir()
            supported_python_versions_path = (
                temporary_path / "supported_python_versions.json")
            write_supported_python_versions_file(
                supported_python_versions_path, ["3.10", "3.11"])

            completed = run_payload_script(
                CHECK_SCRIPT_PATH, payload_directory, vendor_directory,
                supported_python_versions_path)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("would also permit 3.8", completed.stdout)
