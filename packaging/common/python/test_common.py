# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the functions common.py shares between the scripts."""

from unittest import TestCase

from common import (
    derive_minimum_required_python_version,
    prune_supported_python_versions,
    read_supported_python_versions,
)
from python_version_test_helpers import (
    SHIPPED_SUPPORTED_PYTHON_VERSIONS_FILE,
)


class TestDeriveMinimumRequiredPythonVersion(TestCase):

    def test_strictest_lower_bound_wins(self):
        self.assertEqual(
            derive_minimum_required_python_version(
                [">=3.8", ">=3.11", ">=3.9"]),
            (3, 11))

    def test_compatible_release_specifier_resolves_to_its_minor(self):
        self.assertEqual(
            derive_minimum_required_python_version(["~=3.11"]),
            (3, 11))

    def test_empty_and_none_specifiers_are_ignored(self):
        self.assertEqual(
            derive_minimum_required_python_version(
                ["", None, ">=3.10"]),
            (3, 10))

    def test_no_specifiers_yields_none(self):
        self.assertIsNone(
            derive_minimum_required_python_version(["", None]))


class TestReadSupportedPythonVersions(TestCase):

    def test_read_supported_python_versions_from_the_json_array(self):
        # Deliberately not the versions the package ships: this exercises the
        # parser, so the input has to be fixed rather than whatever
        # supported_python_versions.json happens to list today.
        self.assertEqual(
            read_supported_python_versions('["3.4", "3.5", "4.0"]\n'),
            [(3, 4), (3, 5), (4, 0)])

    def test_read_malformed_json_raises(self):
        with self.assertRaises(ValueError):
            read_supported_python_versions('["3.10",\n')

    def test_read_a_non_array_document_raises(self):
        with self.assertRaises(ValueError):
            read_supported_python_versions('{"versions": ["3.10"]}')

    def test_read_an_empty_array_raises(self):
        with self.assertRaises(ValueError):
            read_supported_python_versions("[]")

    def test_read_a_non_python_version_entry_raises(self):
        for entry in ('"three.ten"', '"3"', "310", "null"):
            with self.subTest(entry=entry):
                with self.assertRaises(ValueError):
                    read_supported_python_versions("[{}]".format(entry))


class TestPruneSupportedPythonVersions(TestCase):
    """Pruning, exercised against the versions the package actually ships.

    The input is read from packaging/builder/supported_python_versions.json
    rather than restated here, so that editing that file cannot leave these
    tests asserting against a list the package no longer ships.
    """

    def setUp(self):
        self.shipped_text = SHIPPED_SUPPORTED_PYTHON_VERSIONS_FILE.read_text(
            encoding="utf-8")
        self.shipped_versions = read_supported_python_versions(
            self.shipped_text)
        self.assertGreater(
            len(self.shipped_versions), 1,
            "these tests need at least two supported Python versions")

    def test_prune_drops_only_the_supported_python_versions_below_the_minimum_required_python_version(
            self):
        second_lowest_version = sorted(self.shipped_versions)[1]

        pruned = read_supported_python_versions(
            prune_supported_python_versions(
                self.shipped_text, second_lowest_version))

        self.assertNotIn(min(self.shipped_versions), pruned)
        self.assertEqual(len(pruned), len(self.shipped_versions) - 1)
        self.assertEqual(min(pruned), second_lowest_version)

    def test_prune_output_matches_the_shipped_file_formatting(self):
        # The pruned text is written back over the file the Go builder
        # embeds, so a prune run must not reformat it into something a
        # reviewer sees as an unrelated change. Pruning at the lowest shipped
        # version drops nothing, so the output has to be the input verbatim.
        self.assertEqual(
            prune_supported_python_versions(
                self.shipped_text, min(self.shipped_versions)),
            self.shipped_text)

    def test_prune_below_every_supported_python_version_changes_nothing(self):
        self.assertEqual(
            read_supported_python_versions(
                prune_supported_python_versions(self.shipped_text, (3, 0))),
            self.shipped_versions)

    def test_prune_that_would_empty_the_list_raises(self):
        with self.assertRaises(ValueError):
            prune_supported_python_versions(self.shipped_text, (9, 99))
