// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

// Package collector_test validates "Option 2" from the top-level README's
// "Configuring where telemetry goes" section: the Python auto-instrumentation
// package left at its default (unset) OTLP exporter settings, plus a
// separately installed OpenTelemetry Collector that relays telemetry off the
// host. The workload container never sets OTEL_EXPORTER_OTLP_ENDPOINT or
// OTEL_EXPORTER_OTLP_PROTOCOL, so it can only reach the Collector's receiver
// on localhost — reaching the sink at all proves the Collector relayed it.
package collector_test

import (
	"context"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/open-telemetry/opentelemetry-packaging/testutil"
	"github.com/open-telemetry/opentelemetry-packaging/testutil/otelsink"
	"github.com/stretchr/testify/assert"

	tracepb "go.opentelemetry.io/proto/otlp/trace/v1"
)

// exportTimeout bounds how long we wait for each signal to reach the sink via
// the Collector. The workload flushes on ~1s schedules (see the Dockerfiles);
// the Collector's own batch processor adds negligible latency on top.
const exportTimeout = 90 * time.Second

// target is one (package format, base image) combination in the test matrix.
type target struct {
	format    string // "deb" or "rpm" — selects Dockerfile.<format>
	baseImage string
}

var matrix = []target{
	{format: "deb", baseImage: "debian:12"},
	{format: "rpm", baseImage: "fedora:41"},
}

// TestCollectorRelay builds a container with the injector, the Python
// auto-instrumentation package, and the upstream OpenTelemetry Collector all
// installed side by side, drives traffic against the workload, and asserts
// that traces, metrics, and logs arrive at the sink — having necessarily
// passed through the Collector, since the workload has no other route there.
func TestCollectorRelay(t *testing.T) {
	ctx := context.Background()
	for _, tg := range matrix {
		t.Run(tg.format, func(t *testing.T) {
			t.Run(imageSlug(tg.baseImage), func(t *testing.T) {
				t.Parallel()
				runCollectorCase(t, ctx, tg)
			})
		})
	}
}

func imageSlug(image string) string {
	return strings.NewReplacer(":", "-", "/", "-").Replace(image)
}

func runCollectorCase(t *testing.T, ctx context.Context, tg target) {
	arch := testutil.TargetArch()
	buildArgs := map[string]*string{
		"BASE_IMAGE": &tg.baseImage,
		"ARCH":       &arch,
	}

	sink := otelsink.Start(t)

	// Deliberately not sink.Env(): the workload must keep its OTLP exporter
	// at the SDK default (grpc to localhost:4317, the Collector's receiver),
	// so only the resource attribute scoping telemetry to this test is set.
	// OTLP_FORWARD_ENDPOINT is consumed by the Collector's config, not by the
	// workload's own OTLP environment.
	env := map[string]string{
		"OTEL_RESOURCE_ATTRIBUTES": fmt.Sprintf("%s=%s", otelsink.TestIDAttribute, sink.TestID()),
		"OTLP_FORWARD_ENDPOINT":    sink.ExternalHTTPEndpoint(),
	}

	container := testutil.StartServiceContainerOpts(t, ctx, testutil.ServiceContainerOptions{
		DockerfilePath:  fmt.Sprintf("packaging/tests/collector/Dockerfile.%s", tg.format),
		BuildArgs:       buildArgs,
		ExposedPorts:    []string{"8080/tcp"},
		WaitPort:        "8080/tcp",
		WaitPath:        "/",
		Env:             env,
		HostAccessPorts: sink.HostAccessPorts(),
	})

	// Drive traffic; each request runs a sqlite3 query and emits a log record.
	for range 3 {
		status := testutil.ContainerHTTPGet(t, ctx, container, "8080/tcp", "/")
		assert.Equal(t, 200, status)
	}

	// Traces: reaching the sink at all proves the Collector relayed them — the
	// workload's own OTLP exporter cannot reach anything but localhost.
	traces := sink.WaitForTraces(t, exportTimeout, func(tr *otelsink.Traces) bool {
		return tr.WithKind(tracepb.Span_SPAN_KIND_CLIENT).Len() > 0
	})
	assert.NotEmpty(t, traces.WithSpanAttributeValue("db.system", "sqlite").Spans(),
		"expected a sqlite db.system client span")
	assert.NotEmpty(t, traces.WithResourceAttribute("service.name", "python-testapp").Spans(),
		"spans should carry the configured service.name resource, unchanged by the Collector relay")

	metrics := sink.WaitForMetrics(t, exportTimeout, otelsink.NonEmpty)
	assert.NotEmpty(t, metrics.Names(), "expected at least one exported metric")

	logs := sink.WaitForLogs(t, exportTimeout, func(l *otelsink.Logs) bool {
		return l.WithBodyContaining("request handled").Len() > 0
	})
	assert.Greater(t, logs.Len(), 0, "expected the stdlib logging record bridged to OTLP logs")
}
