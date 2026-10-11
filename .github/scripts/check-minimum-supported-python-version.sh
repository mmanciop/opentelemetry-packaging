#!/usr/bin/env bash

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

# Prepares the inputs for sync_minimum_supported_python_version.py and runs it.
# The module docstring of packaging/common/python/
# sync_minimum_supported_python_version.py defines the minimum supported
# Python version and the minimum required Python version, and is the only
# place either term is defined.
#
# Usage: check-minimum-supported-python-version.sh [--check|--write]
#
# Both modes are the tool's; this script only passes them through.
#
# Environment:
#
#   MINIMUM_SUPPORTED_PYTHON_INTERPRETER
#                   Interpreter used to build the payload (default: the
#                   minimum supported Python version, as pythonX.Y).
#   BUILD_DIR       Scratch directory for the venv and the payload
#                   (default: build/ at the repository root, removed by
#                   "make clean").
#
# This script exists because the tool cannot assemble its own payload. The
# PyPI pins (excluding the vendored source lines) are installed with
# pip install --target into a throwaway payload directory, the same way
# packaging/builder/download.go assembles the payload for the DEB and the RPM,
# and the tool then enumerates only that directory. Installing into a
# virtualenv instead would add pip, setuptools and the tool's own tomli, none
# of which ship; the tool's docstring explains why including a non-shipped
# distribution is one-directional and silent.
#
# The vendored requires-python values are read straight from each vendor
# pyproject.toml via --vendor-dir, so the vendored source does not need to be
# built for the check.
#
# The venv is built with the interpreter for the minimum supported Python
# version on purpose: its pip must resolve the payload's transitive
# dependencies the way it would on that version, so a newer release of a
# transitive dependency that raised its own Requires-Python does not inflate
# the minimum required Python version above what actually runs there. tomli is
# the tomllib backport the tool falls back to under Python 3.10 (tomllib is
# standard library from 3.11).

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
SUPPORTED_PYTHON_VERSIONS_FILE="${REPO_ROOT}/packaging/builder/supported_python_versions.json"

MINIMUM_SUPPORTED_PYTHON_VERSION="$(
    grep -o '"[0-9]\{1,\}\.[0-9]\{1,\}"' "${SUPPORTED_PYTHON_VERSIONS_FILE}" \
        | tr -d '"' | sort -V | head -1
)"
if [ -z "${MINIMUM_SUPPORTED_PYTHON_VERSION}" ]; then
    echo "error: could not read any version from ${SUPPORTED_PYTHON_VERSIONS_FILE}" >&2
    exit 1
fi
MINIMUM_SUPPORTED_PYTHON_INTERPRETER="${MINIMUM_SUPPORTED_PYTHON_INTERPRETER:-python${MINIMUM_SUPPORTED_PYTHON_VERSION}}"
BUILD_DIR="${BUILD_DIR:-${REPO_ROOT}/build}"
VENV_DIR="${BUILD_DIR}/minimum-supported-python-version-venv"
PAYLOAD_DIR="${BUILD_DIR}/minimum-supported-python-version-payload"

if ! command -v "${MINIMUM_SUPPORTED_PYTHON_INTERPRETER}" > /dev/null 2>&1; then
    echo "error: ${MINIMUM_SUPPORTED_PYTHON_INTERPRETER} is not installed. The minimum" \
        "required Python version must be derived with the interpreter for" \
        "the minimum supported Python version, so that pip resolves" \
        "transitive dependencies the way it does there. Install it, or set" \
        "MINIMUM_SUPPORTED_PYTHON_INTERPRETER to that interpreter." >&2
    exit 1
fi

"${MINIMUM_SUPPORTED_PYTHON_INTERPRETER}" -m venv --clear "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --quiet packaging tomli

rm -rf "${PAYLOAD_DIR}"
grep -v '^\./vendor/' "${PYTHON_DIR}/requirements.txt" \
    | "${VENV_DIR}/bin/pip" install --quiet \
        --target "${PAYLOAD_DIR}" -r /dev/stdin

"${VENV_DIR}/bin/python" "${PYTHON_DIR}/sync_minimum_supported_python_version.py" \
    "${MODE}" \
    --payload-dir "${PAYLOAD_DIR}" \
    --vendor-dir "${PYTHON_DIR}/vendor" \
    --supported-python-versions-file "${SUPPORTED_PYTHON_VERSIONS_FILE}"
