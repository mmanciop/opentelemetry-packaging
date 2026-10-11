# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the functions common.py shares between the scripts."""

from json import loads
from unittest import TestCase

from common import (
    derive_minimum_required_python_version,
    prune_supported_python_versions,
    read_supported_python_versions,
)
from python_version_test_helpers import (
    FOUR_SUPPORTED_PYTHON_VERSIONS_JSON,
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


class TestReadAndPruneSupportedPythonVersions(TestCase):

    def test_read_supported_python_versions_from_the_json_array(self):
        self.assertEqual(
            read_supported_python_versions(
                FOUR_SUPPORTED_PYTHON_VERSIONS_JSON),
            [(3, 10), (3, 11), (3, 12), (3, 13)])

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

    def test_prune_drops_only_the_supported_python_versions_below_the_minimum_required_python_version(
            self):
        pruned = prune_supported_python_versions(
            FOUR_SUPPORTED_PYTHON_VERSIONS_JSON, (3, 12))
        self.assertEqual(loads(pruned), ["3.12", "3.13"])
        self.assertEqual(
            read_supported_python_versions(pruned), [(3, 12), (3, 13)])

    def test_prune_output_matches_the_shipped_file_formatting(self):
        # The pruned text is written back over the file the Go builder embeds,
        # so a prune run must not reformat it into something a reviewer sees
        # as an unrelated change.
        self.assertEqual(
            prune_supported_python_versions(
                FOUR_SUPPORTED_PYTHON_VERSIONS_JSON, (3, 9)),
            SHIPPED_SUPPORTED_PYTHON_VERSIONS_FILE.read_text(
                encoding="utf-8"))

    def test_prune_below_every_supported_python_version_changes_nothing(self):
        self.assertEqual(
            read_supported_python_versions(
                prune_supported_python_versions(
                    FOUR_SUPPORTED_PYTHON_VERSIONS_JSON, (3, 9))),
            [(3, 10), (3, 11), (3, 12), (3, 13)])

    def test_prune_that_would_empty_the_list_raises(self):
        with self.assertRaises(ValueError):
            prune_supported_python_versions(
                FOUR_SUPPORTED_PYTHON_VERSIONS_JSON, (3, 99))
