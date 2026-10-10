# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for sync_minimum_python_version.py."""

from pathlib import Path
from subprocess import run
from sys import executable
from tempfile import TemporaryDirectory
from unittest import TestCase

from sync_minimum_python_version import (
    lowest_supported_major_minor_across_requires_python,
    prune_supported_versions,
    read_supported_versions,
)

_TOOL_PATH = str(Path(__file__).with_name("sync_minimum_python_version.py"))

_SUPPORTED_VERSIONS_DECLARATION = (
    'var supportedPythonVersions = []string{"3.10", "3.11", "3.12", "3.13"}')

_MINIMAL_DOWNLOAD_GO = (
    "package builder\n"
    "\n"
    + _SUPPORTED_VERSIONS_DECLARATION + "\n"
    "\n"
    "func pythonABITag(pythonVersion string) string {\n"
    '\treturn "cp" + strings.ReplaceAll(pythonVersion, ".", "")\n'
    "}\n"
)


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


def write_download_go_with_versions(download_go_path, versions):
    """Write a minimal download.go listing the given "major.minor" strings."""
    declaration = "var supportedPythonVersions = []string{{{}}}".format(
        ", ".join('"{}"'.format(version) for version in versions))
    download_go_path.write_text(
        _MINIMAL_DOWNLOAD_GO.replace(
            _SUPPORTED_VERSIONS_DECLARATION, declaration),
        encoding="utf-8")


def run_sync_minimum_python_version(
        mode, payload_directory, vendor_directory, download_go_path):
    """Run the tool in --check or --write mode and return the completed run."""
    return run(
        [
            executable, _TOOL_PATH, mode,
            "--payload-dir", str(payload_directory),
            "--vendor-dir", str(vendor_directory),
            "--download-go", str(download_go_path),
        ],
        capture_output=True, text=True)


class TestDeriveFloorFromRequiresPython(TestCase):

    def test_strictest_lower_bound_wins(self):
        self.assertEqual(
            lowest_supported_major_minor_across_requires_python(
                [">=3.8", ">=3.11", ">=3.9"]),
            (3, 11))

    def test_compatible_release_specifier_resolves_to_its_minor(self):
        self.assertEqual(
            lowest_supported_major_minor_across_requires_python(["~=3.11"]),
            (3, 11))

    def test_empty_and_none_specifiers_are_ignored(self):
        self.assertEqual(
            lowest_supported_major_minor_across_requires_python(
                ["", None, ">=3.10"]),
            (3, 10))

    def test_no_specifiers_yields_none(self):
        self.assertIsNone(
            lowest_supported_major_minor_across_requires_python(["", None]))


class TestPayloadScopedEnumeration(TestCase):

    def test_floor_comes_only_from_the_payload_directory(self):
        # The payload declares a single distribution at >=3.7, so the floor is
        # 3.7. The interpreter running this test has packaging installed
        # (>=3.9), plus pip and setuptools from the throwaway venv the
        # python-unit-tests target builds. An enumeration that walked sys.path
        # instead of --payload-dir would derive at least 3.9 from those, so
        # seeing 3.7 reported is what proves the enumeration is scoped to the
        # payload.
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            write_dist_info_with_requires_python(
                payload_directory, "shipped_thing", "1.0", ">=3.7")
            vendor_directory = temporary_path / "vendor"
            vendor_directory.mkdir()
            download_go_path = temporary_path / "download.go"
            write_download_go_with_versions(download_go_path, ["3.7", "3.8"])

            completed = run_sync_minimum_python_version(
                "--check", payload_directory, vendor_directory,
                download_go_path)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("derived minimum Python: 3.7", completed.stdout)

    def test_strictest_payload_distribution_decides_the_floor(self):
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            write_dist_info_with_requires_python(
                payload_directory, "lenient_thing", "1.0", ">=3.9")
            write_dist_info_with_requires_python(
                payload_directory, "strict_thing", "2.0", ">=3.11")
            vendor_directory = temporary_path / "vendor"
            vendor_directory.mkdir()
            download_go_path = temporary_path / "download.go"
            write_download_go_with_versions(download_go_path, ["3.11", "3.12"])

            completed = run_sync_minimum_python_version(
                "--check", payload_directory, vendor_directory,
                download_go_path)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("derived minimum Python: 3.11", completed.stdout)

    def test_missing_payload_directory_fails(self):
        # A mistyped or unbuilt payload path must be an error rather than a
        # derivation from the vendored pyproject files alone, which would
        # silently report a floor lower than the one the package ships.
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            vendor_directory = temporary_path / "vendor" / "some-package"
            vendor_directory.mkdir(parents=True)
            (vendor_directory / "pyproject.toml").write_text(
                "[project]\n"
                'name = "some-package"\n'
                'requires-python = ">=3.10"\n',
                encoding="utf-8")
            download_go_path = temporary_path / "download.go"
            write_download_go_with_versions(download_go_path, ["3.10"])

            completed = run_sync_minimum_python_version(
                "--check", temporary_path / "no-such-payload",
                temporary_path / "vendor", download_go_path)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("no distributions found", completed.stderr)

    def test_empty_payload_directory_fails(self):
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            payload_directory.mkdir()
            vendor_directory = temporary_path / "vendor"
            vendor_directory.mkdir()
            download_go_path = temporary_path / "download.go"
            write_download_go_with_versions(download_go_path, ["3.10"])

            completed = run_sync_minimum_python_version(
                "--check", payload_directory, vendor_directory,
                download_go_path)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("no distributions found", completed.stderr)


class TestVendorPyprojectParsing(TestCase):

    def test_check_reads_requires_python_from_vendor_pyproject(self):
        # The payload floor (3.8) is below the only vendored pyproject floor
        # (3.12), which must therefore drive --check to reject a list that
        # still starts at 3.10. This proves the tool reads
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
            download_go_path = temporary_path / "download.go"
            write_download_go_with_versions(
                download_go_path, ["3.10", "3.11", "3.12"])

            completed = run_sync_minimum_python_version(
                "--check", payload_directory, temporary_path / "vendor",
                download_go_path)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("3.12", completed.stdout)


class TestSupportedVersionsReadAndPrune(TestCase):

    def test_read_versions_from_the_declaration(self):
        self.assertEqual(
            read_supported_versions(_MINIMAL_DOWNLOAD_GO),
            [(3, 10), (3, 11), (3, 12), (3, 13)])

    def test_read_without_the_declaration_raises(self):
        with self.assertRaises(ValueError):
            read_supported_versions("package builder\n")

    def test_read_with_two_declarations_raises(self):
        with self.assertRaises(ValueError):
            read_supported_versions(
                _MINIMAL_DOWNLOAD_GO + _MINIMAL_DOWNLOAD_GO)

    def test_read_with_an_empty_list_raises(self):
        with self.assertRaises(ValueError):
            read_supported_versions(
                "var supportedPythonVersions = []string{}\n")

    def test_prune_drops_only_the_versions_below_the_floor(self):
        pruned = prune_supported_versions(_MINIMAL_DOWNLOAD_GO, (3, 12))
        self.assertIn(
            'var supportedPythonVersions = []string{"3.12", "3.13"}', pruned)
        self.assertEqual(read_supported_versions(pruned), [(3, 12), (3, 13)])

    def test_prune_leaves_the_rest_of_the_file_untouched(self):
        pruned = prune_supported_versions(_MINIMAL_DOWNLOAD_GO, (3, 12))
        self.assertTrue(pruned.startswith("package builder\n"))
        self.assertIn(
            "func pythonABITag(pythonVersion string) string {", pruned)

    def test_prune_below_every_version_changes_nothing(self):
        self.assertEqual(
            read_supported_versions(
                prune_supported_versions(_MINIMAL_DOWNLOAD_GO, (3, 9))),
            [(3, 10), (3, 11), (3, 12), (3, 13)])

    def test_prune_that_would_empty_the_list_raises(self):
        with self.assertRaises(ValueError):
            prune_supported_versions(_MINIMAL_DOWNLOAD_GO, (3, 99))


class TestCheckAndWriteEndToEnd(TestCase):

    def test_check_passes_when_every_version_meets_the_floor(self):
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            write_dist_info_with_requires_python(
                payload_directory, "shipped_thing", "1.0", ">=3.11")
            vendor_directory = temporary_path / "vendor"
            vendor_directory.mkdir()
            download_go_path = temporary_path / "download.go"
            write_download_go_with_versions(download_go_path, ["3.11", "3.12"])

            completed = run_sync_minimum_python_version(
                "--check", payload_directory, vendor_directory,
                download_go_path)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("is in sync", completed.stdout)

    def test_check_fails_when_a_version_is_below_the_floor(self):
        # This is the regression the check exists for: a dependency bump
        # raises the floor to 3.11 while the builder still tries to resolve
        # the payload for 3.10, which pip cannot do.
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            write_dist_info_with_requires_python(
                payload_directory, "shipped_thing", "1.0", ">=3.11")
            vendor_directory = temporary_path / "vendor"
            vendor_directory.mkdir()
            download_go_path = temporary_path / "download.go"
            write_download_go_with_versions(
                download_go_path, ["3.10", "3.11", "3.12"])

            completed = run_sync_minimum_python_version(
                "--check", payload_directory, vendor_directory,
                download_go_path)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("3.10", completed.stderr)

    def test_check_passes_with_a_note_when_the_floor_is_below_every_version(
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
            download_go_path = temporary_path / "download.go"
            write_download_go_with_versions(download_go_path, ["3.10", "3.11"])

            completed = run_sync_minimum_python_version(
                "--check", payload_directory, vendor_directory,
                download_go_path)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("would also permit 3.8", completed.stdout)

    def test_write_drops_the_versions_below_the_derived_floor(self):
        # A vendored pyproject with a 3.12 floor above the payload's 3.10 puts
        # the derived floor at 3.12, so --write must drop 3.10 and 3.11 and
        # keep the rest.
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            payload_directory = temporary_path / "payload"
            write_dist_info_with_requires_python(
                payload_directory, "shipped_thing", "1.0", ">=3.10")
            vendor_directory = temporary_path / "vendor" / "high-floor"
            vendor_directory.mkdir(parents=True)
            (vendor_directory / "pyproject.toml").write_text(
                "[project]\n"
                'name = "high-floor"\n'
                'requires-python = ">=3.12"\n',
                encoding="utf-8")
            download_go_path = temporary_path / "download.go"
            download_go_path.write_text(
                _MINIMAL_DOWNLOAD_GO, encoding="utf-8")

            completed = run_sync_minimum_python_version(
                "--write", payload_directory, temporary_path / "vendor",
                download_go_path)
            self.assertEqual(completed.returncode, 0, completed.stderr)

            rewritten = download_go_path.read_text(encoding="utf-8")

        self.assertIn(
            'var supportedPythonVersions = []string{"3.12", "3.13"}',
            rewritten)
