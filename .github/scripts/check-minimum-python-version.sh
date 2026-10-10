#!/usr/bin/env bash

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

# Keep supportedPythonVersions in packaging/builder/download.go in sync with
# the strictest Requires-Python across the distributions that actually ship.
#
# Usage: check-minimum-python-version.sh [--check|--write]
#
#   --check (the default) fails when a listed version is below the derived
#   floor.
#   --write drops the listed versions below the derived floor.
#
# Environment:
#
#   MINIMUM_PYTHON  Interpreter that derives the floor (default: the lowest
#                   version in supportedPythonVersions, as pythonX.Y).
#   BUILD_DIR       Scratch directory for the venv and the payload
#                   (default: build/ at the repository root, removed by
#                   "make clean").
#
# The PyPI pins (excluding the vendored source lines) are installed with
# pip install --target into a throwaway payload directory, the same way
# packaging/builder/download.go assembles the payload for the DEB and the RPM,
# and sync_minimum_python_version.py enumerates only that directory. A
# virtualenv would additionally contain pip and setuptools from "python -m venv"
# plus the tool's own tomli, none of which ship; since the floor is a maximum, a
# non-shipped distribution can only raise it, which would mask a floor that
# should drop while the check still reported "in sync".
#
# The vendored floor is read straight from each vendor pyproject.toml via
# --vendor-dir, so the vendored source does not need to be built for the check.
#
# The venv that runs the tool is built with the lowest interpreter in
# supportedPythonVersions on purpose: its pip must resolve the payload's
# transitive dependencies the way it would on that version, so a newer release
# of a transitive dependency that raised its own Requires-Python does not
# inflate the derived floor above what actually runs on the lowest supported
# interpreter. tomli is the tomllib backport the tool falls back to under
# Python 3.10 (tomllib is standard library from 3.11).

set -euo pipefail

MODE="${1:---check}"
case "${MODE}" in
    --check | --write) ;;
    *)
        echo "usage: $(basename "$0") [--check|--write]" >&2
        exit 2
        ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_DIR="${REPO_ROOT}/packaging/common/python"
DOWNLOAD_GO="${REPO_ROOT}/packaging/builder/download.go"

MINIMUM_PYTHON_VERSION="$(
    grep '^var supportedPythonVersions' "${DOWNLOAD_GO}" \
        | grep -o '"[0-9]\{1,\}\.[0-9]\{1,\}"' | tr -d '"' | sort -V | head -1
)"
if [ -z "${MINIMUM_PYTHON_VERSION}" ]; then
    echo "error: could not read supportedPythonVersions from ${DOWNLOAD_GO}" >&2
    exit 1
fi
MINIMUM_PYTHON="${MINIMUM_PYTHON:-python${MINIMUM_PYTHON_VERSION}}"
BUILD_DIR="${BUILD_DIR:-${REPO_ROOT}/build}"
VENV_DIR="${BUILD_DIR}/minimum-python-version-venv"
PAYLOAD_DIR="${BUILD_DIR}/minimum-python-version-payload"

if ! command -v "${MINIMUM_PYTHON}" > /dev/null 2>&1; then
    echo "error: ${MINIMUM_PYTHON} is not installed. The floor must be derived" \
        "with the minimum supported interpreter so that pip resolves" \
        "transitive dependencies the way it does on that floor. Install it, or" \
        "set MINIMUM_PYTHON to the interpreter for the current floor." >&2
    exit 1
fi

"${MINIMUM_PYTHON}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --quiet packaging tomli

rm -rf "${PAYLOAD_DIR}"
grep -v '^\./vendor/' "${PYTHON_DIR}/requirements.txt" \
    | "${VENV_DIR}/bin/pip" install --quiet \
        --target "${PAYLOAD_DIR}" -r /dev/stdin

"${VENV_DIR}/bin/python" "${PYTHON_DIR}/sync_minimum_python_version.py" \
    "${MODE}" \
    --payload-dir "${PAYLOAD_DIR}" \
    --vendor-dir "${PYTHON_DIR}/vendor" \
    --download-go "${DOWNLOAD_GO}"
