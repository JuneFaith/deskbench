# ServiceDeskBench-Lite

ServiceDeskBench-Lite is an evaluation and reliability benchmark for enterprise service-desk agents. It evaluates more than the final answer: each case checks business outcome, execution trace, workflow invariants, failure recovery, retrieval quality, and cost/performance evidence.

> **Status:** Local protocol evaluation, deterministic scorers, reports, and regression gates are available. Real HTTP and retrieval integration test against external Tix endpoints with environment gating; protocol tests run completely offline.

## Documentation

- [Documentation index](docs/index.md)
- [Project context](CONTEXT.md)
- [Dataset guide](docs/datasets.md) · [Dataset manifest](datasets/servicedesk_v1/manifest.yaml)
- [Architecture](docs/architecture.md) · [Adapter protocol](docs/adapters.md)
- [Reporting and gates](docs/reporting.md) · [Verification](docs/verification.md)
- [Architecture decisions](docs/decisions.md) · [Implementation task record](docs/task.md)

## Scope

The first version targets one stateful domain and integrates with the tix system under test through two boundaries:

- `TixGraphAdapter` for local graph execution and interrupt/resume behavior.
- `TixHttpAdapter` for public API, authentication, approval, permission, and transition behavior.

Core contracts and deterministic scorers do not import tix types, ORM models, repositories, or database objects. Tix-specific conversion is isolated inside the adapters.

## Development setup

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff format --check src tests evals
uv run ruff check src tests evals
uv run mypy src tests evals
```

The package exposes the `servicedeskbench` command:

```bash
uv run servicedeskbench --help
```

## Dataset and reports

Versioned cases live under `datasets/servicedesk_v1/`. The manifest records the
version, provenance, label semantics, and case files. The core case fixtures
and RAG assets are available in `datasets/servicedesk_v1/`. Each case records its expected
state, interactions, policy, and optional fault plan.

A case file, manifest, or dataset directory may be supplied as a plain local
path or `file://` URL. For remote datasets, install the optional dependencies
and use the asynchronous loader:

```bash
uv sync --extra remote
```

`s3://bucket/path/cases.yaml` addresses one YAML case file. A bucket prefix
such as `s3://bucket/path` addresses a manifest and its listed files. Remote
reads use the asynchronous fsspec interface and currently require the asyncio
AnyIO backend.

Experimental output is written to a new directory under `reports/` containing
`summary.json`, `cases.jsonl`, and `markdown.md`; previous runs are never
normally overwritten. Reports persist dataset, adapter, model, prompt,
embedding, retrieval, scorer, timing, and per-case trace metadata. The runner
also bounds wall time, steps, tool calls, and cleanup. The `score` command reads
an existing report summary; it does not rerun scorers.

## CLI and Tix integration

The CLI has three commands:

```bash
SERVICEDESKBENCH_TIX_URL=https://tix.example \
SERVICEDESKBENCH_TIX_USERNAME=... \
SERVICEDESKBENCH_TIX_PASSWORD=... \
uv run servicedeskbench run \
  --dataset datasets/servicedesk_v1/happy_path.yaml \
  --adapter http --output reports
uv run servicedeskbench score --report reports/<timestamp>/summary.json
uv run servicedeskbench gate --report reports/<timestamp>/summary.json \
  --baseline reports/<baseline>/summary.json
```

Add `--json` to `run`, `score`, or `gate` for machine-readable success and
error envelopes. The real-HTTP MVP reads `SERVICEDESKBENCH_TIX_URL` and either
`SERVICEDESKBENCH_TIX_TOKEN` or `SERVICEDESKBENCH_TIX_USERNAME` plus
`SERVICEDESKBENCH_TIX_PASSWORD`. Tix's LLM and embedding model settings are
configured in the Tix deployment's `tix.yaml`; ServiceDeskBench does not own
or override those model settings. It uses Tix's public `/api/tickets` and
`/api/tickets/{ticket_id}/resume` endpoints; `ticket_id` is the business
handle and `thread_id` is the approval handle. Ticket cleanup is not exposed
by the public API: a dedicated deployment/database can own cleanup, while a
shared development deployment leaves the created test ticket in that shared
store. The Graph adapter reads
`SERVICEDESKBENCH_GRAPH_FACTORY` in `module:attribute` form; the selected
factory is the only application-specific graph integration seam.

Protocol tests run without tix. Real integration tests are opt-in and require
a reachable Tix service plus an account with approval permission:

```bash
SERVICEDESKBENCH_TIX_URL=https://tix.example \
SERVICEDESKBENCH_TIX_USERNAME=... \
SERVICEDESKBENCH_TIX_PASSWORD=... \
  uv run pytest -m integration
```

When no connection is configured, integration tests are skipped and must not be
reported as passing. A shared development deployment is valid for this HTTP
MVP, but its created ticket remains in the shared store and the result does not
prove deployment isolation or automatic cleanup. HTTP result identity is
checked against the requested ticket before the result enters the canonical
models. Protocol tests use MockTransport and do not prove deployment behavior;
without all connection credentials the integration case explicitly skips.

## Reliability gates

The hard regression gates require zero occurrences of approval bypass,
cross-ticket resume, degraded false success, illegal transition, and forbidden
tool usage. Quality gates compare Recall@5, MRR, completion rate, P95 latency,
and unexplained tool-call growth against a recorded baseline. Gate failures
retain named failure codes; per-case reports retain trace indexes, tool names,
arguments, actual state, and expected state where available.

The local test suite includes protocol coverage plus environment-gated tix
integration coverage. Always report integration skips separately from passing
tests when no deployment is configured.

## Project boundary

ServiceDeskBench-Lite is a standalone evaluation and reliability benchmark for enterprise service-desk agents. The package and CLI identity is `servicedeskbench`. Core contracts, runners, scorers, faults, and reporting are decoupled from any specific service-desk implementation; external systems under test integrate through dedicated adapters.
