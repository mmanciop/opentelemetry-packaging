#!/bin/bash
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

# Starts the Collector in the background, waits for its OTLP/gRPC receiver to
# accept connections, then runs the workload app in the foreground. This
# stands in for what two systemd services would do on a real host: the
# Collector as a perpetually running service, the workload as the
# userspace-visible process the container's lifecycle follows.
set -e

otelcol --config=/etc/otelcol/config.yaml &

until exec 3<>/dev/tcp/127.0.0.1/4317; do
  sleep 0.1
done
exec 3<&-
exec 3>&-

"$PYTHON_BIN" /app/app.py 2>&1 | tee /tmp/app-output.log
