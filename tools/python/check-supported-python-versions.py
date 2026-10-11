# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Fail when a supported Python version is below the minimum required one.

The supported Python versions and the minimum required Python version are
defined in the module docstring of common.py, next to this script, which is
the only place either term is defined. That docstring also documents the two
phases this script runs in, why a supported Python version below the minimum
required Python version is an error while the converse is not, and the
environment variables MINIMUM_SUPPORTED_PYTHON_INTERPRETER and BUILD_DIR.

This script never writes a file. Run prune-supported-python-versions.py to
drop the versions it reports.
"""

from pathlib import Path
from sys import stderr

from common import (
    SUPPORTED_PYTHON_VERSIONS_FILE_NAME,
    MinimumRequiredPythonVersionError,
    add_payload_arguments,
    build_argument_parser,
    derive_minimum_required_python_version_from_bundled_distributions,
    format_python_versions,
    prepare_payload_and_rerun_in_the_virtualenv,
    read_supported_python_versions,
)


def main():
    argument_parser = build_argument_parser(__doc__)
    add_payload_arguments(argument_parser)
    arguments = argument_parser.parse_args()

    supported_python_versions = read_supported_python_versions(
        Path(arguments.supported_python_versions_file).read_text(
            encoding="utf-8"))

    if arguments.payload_dir is None:
        return prepare_payload_and_rerun_in_the_virtualenv(
            __file__, min(supported_python_versions), arguments)

    try:
        minimum_required_python_version = (
            derive_minimum_required_python_version_from_bundled_distributions(
                arguments.payload_dir, arguments.vendor_dir))
    except MinimumRequiredPythonVersionError as error:
        print(error, file=stderr)
        return 1

    print("minimum required Python version: {}.{}".format(
        *minimum_required_python_version))
    print("supported Python versions: {}".format(
        format_python_versions(supported_python_versions)))

    below_minimum_required_python_version = [
        version for version in supported_python_versions
        if version < minimum_required_python_version]
    if below_minimum_required_python_version:
        print(
            "{} lists {} below the minimum required Python version {}.{}; "
            "pip cannot resolve the payload for those interpreters. Run "
            "prune-supported-python-versions.py to drop them.".format(
                SUPPORTED_PYTHON_VERSIONS_FILE_NAME,
                format_python_versions(
                    below_minimum_required_python_version),
                *minimum_required_python_version),
            file=stderr)
        return 1

    if min(supported_python_versions) > minimum_required_python_version:
        print(
            "note: the bundled distributions would also permit {}.{}, "
            "which the package does not ship".format(
                *minimum_required_python_version))
    print("supported Python versions are in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
