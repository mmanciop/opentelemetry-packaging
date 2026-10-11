# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Drop the supported Python versions below the minimum required one.

The supported Python versions and the minimum required Python version are
defined in the module docstring of common.py, next to this script, which is
the only place either term is defined. That docstring also documents the two
phases this script runs in and the environment variables
MINIMUM_SUPPORTED_PYTHON_INTERPRETER and BUILD_DIR.

This script only ever removes entries from
packaging/builder/supported_python_versions.json. Adding an interpreter to
that file is a hand edit. Run check-supported-python-versions.py to see what
this script would drop without writing anything.
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
    prune_supported_python_versions,
    read_supported_python_versions,
)


def main():
    argument_parser = build_argument_parser(__doc__)
    add_payload_arguments(argument_parser)
    arguments = argument_parser.parse_args()

    supported_python_versions_text = Path(
        arguments.supported_python_versions_file).read_text(encoding="utf-8")
    supported_python_versions = read_supported_python_versions(
        supported_python_versions_text)

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
    if not below_minimum_required_python_version:
        print("no supported Python version is below the minimum required "
              "Python version; nothing to prune")
        return 0

    pruned_text = prune_supported_python_versions(
        supported_python_versions_text, minimum_required_python_version)
    Path(arguments.supported_python_versions_file).write_text(
        pruned_text, encoding="utf-8")
    print("dropped {} from {}".format(
        format_python_versions(below_minimum_required_python_version),
        SUPPORTED_PYTHON_VERSIONS_FILE_NAME))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
