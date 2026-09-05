# Task Records

## T-001: deskbench 服务台 Agent 评测与可靠性检测系统基础架构搭建

**Kind:** feature
**Status:** verified
**Goal:** 搭建 deskbench 基础架构，通过统一的 Case、CanonicalState、CanonicalTrace、Tix Graph/HTTP Adapter、确定性 Scorer、故障计划、报告和回归门禁验证服务台 Agent。

### Architecture

本任务搭建 deskbench 基础架构。`src/deskbench/` 是唯一运行时包；核心 contracts、runner、scorers、faults 和 reporting 不导入 tix，只有 Adapter 模块处理 tix 边界。tix 源码和部署不在当前 checkout 中，因此协议测试使用注入的协议客户端，真实 Graph/HTTP 测试使用环境门控并在缺少部署时明确跳过。依据 D-003，deskbench 负责 Tix 之外的系统级验收、可靠性与回归评测；Tix 内部实现测试和启动/健康检查冒烟不放入本仓库。

### Out of Scope

- 不把 Ragas、DeepEval、AgentEvals、Phoenix、Langfuse 或 Opik 设为核心运行时依赖：第一版按领域协议构建运行时。
- 不把 Tix 的实现级测试和启动冒烟机械搬运到 deskbench；两者按 D-003 分层维护。
- 不在 tix 生产代码中增加 `evaluation_mode`、测试捷径、测试专用接口或评测分支：故障注入放在评测侧，HTTP 故障场景通过外部代理实现。
- 不实现完整观测平台、Web Dashboard、在线监控、自动修复、自动生成海量数据集或多行业 Benchmark：Lite 版本只覆盖服务台领域、两个执行 Adapter、一个 retrieval Adapter、四类核心 Scorer、一个 CLI、JSON/Markdown 报告和回归门禁。

### Requirement Coverage

- 服务台任务和版本化数据集：Task 2
- CanonicalState、CanonicalTrace、AgentRun：Task 2–3
- TixGraphAdapter：Task 4
- TixHttpAdapter：Task 5
- Runner、限制和故障计划：Task 6
- Outcome、WorkflowInvariant、Trajectory、Resilience Scorer：Task 7
- Retrieval Scorer 和 tix RAG 数据抽取：Task 8
- JSON/Markdown 报告、baseline 和 regression gate：Task 9
- CLI、eval 入口、契约测试、集成测试和文档：Task 10

### Task 1: 初始化项目元数据与包结构

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `src/deskbench/__init__.py`
- Create: `src/deskbench/py.typed`
- Create: `tests/test_package_boundary.py`
- Create: `AGENTS.md`
- Create: `.gitignore`

**Interfaces:**
- Produces package import `deskbench` and console entry point `deskbench`.
- Core dependency set is limited to `pydantic>=2`, `PyYAML`, `httpx`, and `anyio`; `fsspec` and `s3fs` are optional under the `remote` extra, and no core module imports tix at import time.
- Initialize repository with clean structure and baseline commit.

- [x] **Step 1: Initialize project structure and baseline files**

Verify that repository initializes cleanly without remote configuration.

- [x] **Step 2: Write the failing package-boundary test**

```python
# tests/test_package_boundary.py
import importlib


def test_core_package_imports_without_tix() -> None:
    module = importlib.import_module("deskbench.contracts")
    assert module is not None


def test_tix_adapter_is_not_imported_by_core() -> None:
    importlib.import_module("deskbench.contracts")
    assert "deskbench.adapters.tix_graph" not in __import__("sys").modules
```

- [x] **Step 3: Run `pytest tests/test_package_boundary.py -q` and verify it fails because the package does not exist**

- [x] **Step 4: Create the package metadata and empty import surface**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[project]
name = "deskbench"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["anyio>=4", "httpx>=0.27", "pydantic>=2", "pyyaml>=6"]

[project.optional-dependencies]
remote = ["fsspec>=2024.6", "s3fs>=2024.6"]

[project.scripts]
deskbench = "deskbench.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

```python
# src/deskbench/__init__.py
"""deskbench service-desk agent evaluation toolkit."""

__all__ = ["__version__"]
__version__ = "0.1.0"
```

- [x] **Step 5: Define initial project layout and core module boundaries**

- [x] **Step 6: Configure project metadata, README, package discovery, console command, and tests under deskbench namespace**

- [x] **Step 7: Clean build assets and ensure project structure is minimal and self-contained**

- [x] **Step 8: Add README boundary documentation and run `pytest tests/test_package_boundary.py -q` to verify it passes**

README now documents local/file/S3 dataset loading, CLI JSON behavior, Graph factory configuration, report metadata, and the tix integration skip contract.

- [x] **Step 9: Run `ruff check src tests && mypy src tests`; Ruff and mypy pass for the current `src tests evals` tree.**

### Task 2: 定义 Case、CanonicalState、AgentRun 和版本化数据集

**Files:**
- Create: `src/deskbench/contracts/cases.py`
- Create: `src/deskbench/contracts/state.py`
- Create: `src/deskbench/contracts/results.py`
- Create: `src/deskbench/contracts/__init__.py`
- Create: `datasets/servicedesk_v1/manifest.yaml`
- Create: `datasets/servicedesk_v1/happy_path.yaml`
- Create: `datasets/servicedesk_v1/approval.yaml`
- Create: `datasets/servicedesk_v1/degradation.yaml`
- Create: `datasets/servicedesk_v1/security.yaml`
- Create: `tests/test_contracts.py`

**Interfaces:**
- `Case.model_validate(data: object) -> Case` validates `id`, input, interaction, expected outcome, policy step/rejection limits, provenance, and optional `FaultPlan`.
- `CanonicalState` contains `status`, `category`, `priority`, `urgency`, `severity`, `impact`, `assigned`, `resolution`, `needs_review`, `degraded`, `human_takeover`, and `audit_summary`.
- `CanonicalTrace` is a list of typed events: `agent_step`, `model_call`, `tool_call`, `tool_result`, `state_change`, `interrupt`, `resume`, `error`, and `degradation`.
- `AgentRun` contains adapter/run identity, dataset and timing metadata, final state, trace, scorer results, error, and cost/performance fields.

- [x] **Step 1: Write tests for valid YAML, rejected transitions, and named result fields**

```python
from pathlib import Path
import yaml
import pytest
from pydantic import ValidationError
from deskbench.contracts import Case, CanonicalState


def test_case_loads_versioned_approval_fixture() -> None:
    raw = yaml.safe_load(
        Path("datasets/servicedesk_v1/approval.yaml").read_text()
    )[0]
    case = Case.model_validate(raw)
    assert case.id == "security-approval-001"
    assert case.expected.final_status == "closed"
    assert case.policy.forbidden_transitions == ["pending_approval -> closed"]


def test_case_rejects_empty_id() -> None:
    with pytest.raises(ValidationError):
        Case.model_validate({"id": "", "input": {}})


def test_canonical_state_exposes_business_facts() -> None:
    state = CanonicalState(status="pending_approval", assigned=False)
    assert state.status == "pending_approval"
    assert state.assigned is False
```

- [x] **Step 2: Run `pytest tests/test_contracts.py -q` and verify the tests fail**

- [x] **Step 3: Implement Pydantic models with strict enums for action, fault mode, and event kind; use `Field(default_factory=list)` for collection fields and `model_config = ConfigDict(extra="forbid")`****

- [x] **Step 4: Add initial development cases split among normal, approval, degradation, and security paths; `manifest.yaml` records dataset provenance****

- [x] **Step 5: Run `pytest tests/test_contracts.py -q && ruff check src tests` and verify the contract tests pass**

### Task 3: 实现 Trace 归一化和执行证据模型

**Files:**
- Create: `src/deskbench/contracts/trace.py`
- Create: `src/deskbench/trace/normalize.py`
- Create: `src/deskbench/trace/__init__.py`
- Create: `tests/test_trace_normalization.py`

**Interfaces:**
- `normalize_trace(events: Sequence[Mapping[str, object]]) -> CanonicalTrace` preserves timestamps, tool names, arguments, results, state changes, interrupt/resume IDs, exceptions, degradation reasons, tokens, latency, and retries.
- `CanonicalTrace.find(kind: TraceEventKind) -> list[TraceEvent]` and `CanonicalTrace.tool_calls() -> list[TraceEvent]` provide scorer-only access without tix types.

- [x] **Step 1: Write tests for tix-like event dictionaries, missing optional fields, invalid kinds, and preservation of raw evidence**

```python
from deskbench.trace.normalize import normalize_trace


def test_normalize_trace_preserves_tool_and_state_evidence() -> None:
    trace = normalize_trace([
        {"kind": "tool_call", "name": "assign_ticket", "arguments": {"ticket_id": "T1"}},
        {"kind": "state_change", "from": "classified", "to": "assigned"},
    ])
    assert trace.tool_calls()[0].name == "assign_ticket"
    assert trace.find("state_change")[0].to_status == "assigned"
```

- [x] **Step 2: Run `pytest tests/test_trace_normalization.py -q` and verify it fails**

- [x] **Step 3: Implement typed trace events and a normalization function that maps known keys, records unknown payload keys under `raw`, and raises `TraceNormalizationError` with event index and kind for invalid required fields**

- [x] **Step 4: Run `pytest tests/test_trace_normalization.py -q && mypy src tests` and verify it passes**

### Task 4: 定义 Adapter 协议并实现 TixGraphAdapter

**Files:**
- Create: `src/deskbench/adapters/base.py`
- Create: `src/deskbench/adapters/tix_graph.py`
- Create: `src/deskbench/adapters/__init__.py`
- Create: `tests/test_adapter_contract.py`
- Create: `tests/test_tix_graph_adapter.py`

**Interfaces:**
- `AgentAdapter.prepare(case: Case) -> PreparedRun`.
- `AgentAdapter.submit(prepared: PreparedRun) -> RunHandle`.
- `AgentAdapter.resume(handle: RunHandle, action: str) -> RunHandle` receives the serialized `CaseAction` value.
- `AgentAdapter.result(handle: RunHandle) -> AgentRun`.
- `AgentAdapter.cleanup(handle: RunHandle) -> None`.
- `TixGraphAdapter` receives an injected graph factory, event reader, and cleanup callback; it maps tix objects to plain mappings at the Adapter boundary and never exports tix objects.

- [x] **Step 1: Write protocol tests using a local protocol implementation inside the test file, covering submit, interrupt, resume, result, and cleanup**

```python
async def test_adapter_contract_requires_cleanup(adapter: AgentAdapter, case: Case) -> None:
    prepared = await adapter.prepare(case)
    handle = await adapter.submit(prepared)
    await adapter.cleanup(handle)
    assert handle.run_id
```

- [x] **Step 2: Run the contract tests and verify failure because the protocol and graph adapter do not exist**

- [x] **Step 3: Implement the protocol and `TixGraphAdapter` with run IDs, interrupt IDs, and conversion through `normalize_trace` plus `CanonicalState.model_validate`**

- [x] **Step 4: Add graph-path tests for approval interrupt/resume, result normalization, and cleanup; inject all tix dependencies rather than importing tix in the test process**

- [x] **Step 5: Run `pytest tests/test_adapter_contract.py tests/test_tix_graph_adapter.py -q && ruff check src tests`**

### Task 5: 实现 TixHttpAdapter 和最小只读 API 契约

**Files:**
- Create: `src/deskbench/adapters/tix_http.py`
- Create: `tests/test_tix_http_adapter.py`
- Modify: `README.md` to document `DESKBENCH_TIX_URL`, authentication, Graph factory configuration, and integration-test command

**Interfaces:**
- `TixHttpAdapter(base_url: str, token: str | None, client: httpx.AsyncClient | None = None)` implements `AgentAdapter`.
- The HTTP mapping uses only stable endpoints for create, read, approval queue, approval decision, event/audit read, and run cleanup; each response must include `run_id` or a structured error.
- `TixHttpAdapter` raises `HttpAdapterError(status_code, endpoint, detail)` for transport, authentication, schema, and server errors.

- [x] **Step 1: Write MockTransport tests for request methods, auth headers, structured errors, and result retrieval**

- [x] **Step 2: Run `pytest tests/test_tix_http_adapter.py -q` and verify failure**

- [x] **Step 3: Implement the adapter with `httpx.AsyncClient`, response validation, timeout configuration, and no business-logic retries; preserve the server's error code**

- [x] **Step 4: Add an opt-in integration test marker that requires `DESKBENCH_TIX_URL`; do not run it when the variable is absent**

- [x] **Step 5: Run `pytest tests/test_tix_http_adapter.py -q && ruff check src tests && mypy src tests`**

### Task 6: 实现 Runner、执行限制和评测侧故障计划

**Files:**
- Create: `src/deskbench/runner/lifecycle.py`
- Create: `src/deskbench/runner/execution.py`
- Create: `src/deskbench/runner/limits.py`
- Create: `src/deskbench/faults/plans.py`
- Create: `src/deskbench/faults/providers.py`
- Create: `tests/test_runner.py`
- Create: `tests/test_faults.py`

**Interfaces:**
- `run_case(case: Case, adapter: AgentAdapter, limits: ExecutionLimits) -> AgentRun` controls timeout, max steps, max tool calls, interaction actions, cleanup, and error capture.
- `FaultPlan(component: FaultComponent, mode: FaultMode, once: bool = True)` is applied by adapter/provider injection and never changes tix production behavior.
- Supported modes are `timeout`, `invalid_json`, `unavailable`, `error`, `write_failure`, `read_failure`, `duplicate_resume`, and `cross_ticket_thread`.

- [x] **Step 1: Write tests proving timeout, approval action dispatch, cleanup after exception, and explicit error outcome**

- [x] **Step 2: Run `pytest tests/test_runner.py tests/test_faults.py -q` and verify failure**

- [x] **Step 3: Implement `ExecutionLimits` and an anyio-based runner with `anyio.fail_after` and sequential interaction handling**

The runner also enforces configured step and tool-call limits and preserves adapter identity plus elapsed failure evidence.

- [x] **Step 4: Implement a generic evaluation-side one-shot fault provider for injected dependencies**

- [x] **Step 5: Run focused runner and fault tests under AnyIO backends****

### Task 7: 实现四类确定性 Scorer

**Files:**
- Create: `src/deskbench/scorers/outcome.py`
- Create: `src/deskbench/scorers/invariants.py`
- Create: `src/deskbench/scorers/trajectory.py`
- Create: `src/deskbench/scorers/resilience.py`
- Create: `src/deskbench/scorers/__init__.py`
- Create: `tests/test_scorers.py`

**Interfaces:**
- `score_outcome(case: Case, run: AgentRun) -> ScoreResult` checks category, priority, assignment, review, resolution, and final status.
- `score_invariants(case: Case, run: AgentRun) -> ScoreResult` checks approval bypass, degraded auto-assignment, empty resolution close, approval-period mutation, unauthorized approval, thread ownership, duplicate resume, rejection limit, and infrastructure false success.
- `score_trajectory(case: Case, run: AgentRun) -> ScoreResult` checks allowed/forbidden tools, arguments, ordering, duplicates, excess steps, recovery, and answer/evidence consistency.
- `score_resilience(case: Case, run: AgentRun) -> ScoreResult` checks fault detection, structured failure, degraded/human takeover state, state pollution, audit evidence, resumability, and false success.
- `ScoreResult` contains `scorer`, `passed`, `value`, `failures`, and `evidence` with actual/expected state and trace indexes.

- [x] **Step 1: Write scorer tests for outcome, approval bypass, forbidden tools, and degraded false success**

- [x] **Step 2: Run `pytest tests/test_scorers.py -q` and verify failure**

- [x] **Step 3: Implement pure outcome, invariant, trajectory, and resilience scorers over only canonical models**

- [x] **Step 4: Add tests asserting scorer output includes trace evidence rather than only a boolean**

- [x] **Step 5: Run `pytest tests/test_scorers.py -q && mypy src tests && ruff check src tests`**

### Task 8: 抽取并评估 RAG 数据

**Files:**
- Create: `src/deskbench/adapters/tix_retrieval.py`
- Create: `src/deskbench/scorers/retrieval.py`
- Create: `datasets/servicedesk_v1/rag_queries.yaml`
- Create: `datasets/servicedesk_v1/rag_tickets.yaml`
- Create: `datasets/servicedesk_v1/rag_kb_articles.yaml`
- Create: `tests/test_retrieval.py`

**Interfaces:**
- `RetrievalExample` stores query, relevance labels, source type, topic, and negative-confounder metadata.
- `score_retrieval(examples: Sequence[RetrievalExample], results: Sequence[RetrievalResult], k: int = 5) -> RetrievalScore` computes Recall@1/3/5, Precision@5, MRR, NDCG@5, leakage, and topic breakdown.
- `TixRetrievalAdapter` exposes retrieval results as plain `RetrievalResult` objects and supports `min_score`, RRF weights, BM25 parameters, and candidate length as explicit experiment metadata.

- [ ] **Step 1: Copy the four tix RAG source assets into new versioned YAML files after recording source paths and label semantics in `manifest.yaml`; do not import tix test modules at runtime**

The manifest records the expected source paths and label semantics, but those source assets are absent from this checkout and have not been fabricated.

- [x] **Step 2: Write failing metric tests for rank positions, mixed sources, negative leakage, and per-topic aggregation**

- [x] **Step 3: Run `pytest tests/test_retrieval.py -q` and verify failure**

- [x] **Step 4: Implement rank metrics, negative leakage detection, and per-topic aggregation**

- [ ] **Step 5: Run `pytest tests/test_retrieval.py -q` and save a deterministic fixture report for the eventual tix query set**

The metric tests pass locally, but the requested fixture report cannot be generated until the source query set is supplied.

### Task 9: 实现实验持久化、报告和 Regression Gate

**Files:**
- Create: `src/deskbench/reporting/json_report.py`
- Create: `src/deskbench/reporting/markdown_report.py`
- Create: `src/deskbench/reporting/gate.py`
- Create: `src/deskbench/reporting/__init__.py`
- Create: `tests/test_reporting.py`
- Create: `tests/test_gate.py`

**Interfaces:**
- `ExperimentMetadata` records `run_id`, dataset version, tix commit, adapter, agent/model/prompt/embedding versions, retrieval parameters, scorer version, and start/end timestamps.
- `write_report(report: EvaluationReport | list[AgentRun], output_root: str | Path) -> ReportPaths` writes `reports/<timestamp>/summary.json`, `cases.jsonl`, and `markdown.md` without overwriting a prior run; the list form remains a compatibility convenience for programmatic callers.
- `evaluate_gate(summary: Summary, baseline: Summary | None, policy: GatePolicy) -> GateResult` enforces hard zero-rate safety gates and baseline-relative quality/performance gates.

- [x] **Step 1: Write tests for stable JSON serialization and one-case-per-line output**

- [x] **Step 2: Write gate tests for hard gates and baseline quality/latency checks**

- [x] **Step 3: Run `pytest tests/test_reporting.py tests/test_gate.py -q` and verify failure**

- [x] **Step 4: Implement timestamped JSON/JSONL/Markdown reports and hard/baseline gate evaluation**

Reports use `EvaluationReport` and `ExperimentMetadata`; summaries derive retrieval metrics and safety rates from persisted score evidence.

- [x] **Step 5: Run focused tests and validate a generated report through JSON parsing**

### Task 10: 接入 CLI、评测入口、契约矩阵和项目文档

**Files:**
- Create: `src/deskbench/cli.py`
- Create: `evals/servicedesk_eval.py`
- Create: `tests/test_cli.py`
- Create: `tests/test_end_to_end.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md` only when the implementation adds user-facing product functionality and the entry is placed under `## Unreleased`

**Interfaces:**
- CLI commands: `deskbench run --dataset PATH --adapter graph|http --output PATH`, `deskbench score --report PATH`, and `deskbench gate --report PATH --baseline PATH`.
- `servicedesk_eval.py` re-exports the async `run_dataset(dataset_path: str | Path, adapter: AgentAdapter, output_path: str | Path, *, limits: ExecutionLimits | None = None) -> ReportPaths` workflow; the CLI constructs the selected Adapter only after configuration is resolved.
- Contract matrix runs the same cases against Graph and HTTP adapters and reports semantic differences instead of treating HTTP 200 as success.

- [x] **Step 1: Write CLI tests for help and command parsing**

- [x] **Step 2: Write an end-to-end test using a deterministic protocol adapter that exercises case loading → runner → scorers → report**

- [x] **Step 3: Run `pytest tests/test_cli.py tests/test_end_to_end.py -q` and verify failure**

- [x] **Step 4: Implement CLI argument parsing, manifest-aware dataset loading, report writing, stable JSON/error output, and configured Graph/HTTP Adapter selection.**

- [x] **Step 5: Document setup, dataset provenance, Graph/HTTP configuration, report layout, gate policy, and test layers in `README.md`****

- [x] **Step 6: Run the complete verification sequence from the repository root:**

The latest verification completed the full local test suite, with environment-gated tix tests skipped because no deployment was configured; Ruff format, Ruff check, mypy, and CLI help also passed.

```bash
uv run pytest -q
uv run ruff format --check src tests evals
uv run ruff check src tests evals
uv run mypy src tests evals
uv run python -m deskbench.cli --help
```

- [x] **Step 7: Run the opt-in tix integration suite against the available shared Tix development deployment:**

The suite was also checked without deployment configuration and correctly reported 2 skips; the shared-development run is recorded in T-003 below and is not confused with isolated-deployment evidence.

```bash
DESKBENCH_TIX_URL=... \
DESKBENCH_TIX_USERNAME=... \
DESKBENCH_TIX_PASSWORD=... \
  uv run pytest -m integration
```

- [x] **Step 8: Review the final diff for clean package paths, git submodules, reports excluded from source control, and complete requirement coverage**

The final audit verified:
1. **Clean package paths**: Searched `src/`, `tests/`, `evals/`, and configuration files. `deskbench` is the sole runtime package and CLI.
2. **Submodules**: `git submodule status` is empty.
3. **Artifacts & Reports**: `.gitignore` properly excludes `reports/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`.
4. **Clean Git history**: Git history starts cleanly with `chore: initialize deskbench` without stale history or remote.
5. **Requirement coverage**: Full Lite scope implemented: contracts, trace normalization, runner lifecycle, 5 deterministic scorers, fault injection plans, reporting (JSON/JSONL/Markdown), regression gate, and CLI.
6. **External blockers**: RAG source assets remain explicitly documented in manifest; automated deployment isolation and cleanup remain an external orchestration boundary.

### Architecture Review: relationship with tix (2026-09-02)

The review confirmed that externalizing non-basic service-desk acceptance tests is a valid boundary: tix retains implementation tests and smoke checks, while deskbench may own versioned cases, end-to-end business behavior, deterministic workflow scorers, RAG regression, and baseline reports. This is not itself over-design.

The current implementation now has a ticket-oriented HTTP MVP boundary. The HTTP Adapter maps Tix public Ticket endpoints, while `TixGraphAdapter` remains a generic protocol adapter rather than a claimed mapping of tix's internal `run_graph`/`resume_graph` entry points. Fault plans are not connected to a live adapter, RAG source assets are unavailable, and there is no deployment-backed report or baseline. Treat protocol tests as contract evidence, not real integration evidence.

The next scope decision is explicit: (A) keep advanced evaluation inside tix, (B) retain deskbench but first reduce it to a real tix HTTP black-box adapter plus a small deterministic scorer/report path, or (C) continue platform expansion only after defining the real tix run/cleanup/trace contract, isolation unit, fault-injection boundary, dataset ownership, and maintenance responsibility. Until the developer selects a path, defer Graph/Fault/S3/multi-adapter expansion and do not add evaluation-specific production branches to tix.

### Code Audit and Security Review

- Fresh audit checks found no embedded credentials or private keys in the new package, datasets, tests, or metadata.
- HTTP authentication remains confined to the adapter boundary; core contracts and scorers do not handle tix objects.
- User-selected graph factory imports are explicit through `DESKBENCH_GRAPH_FACTORY=module:attribute`; no shell execution is performed by the CLI.
- Local/file dataset paths are supported synchronously and asynchronously; S3 loading uses the optional `remote` extra and asynchronous fsspec access. The current implementation reports an explicit backend error under Trio, and a real S3 contract test remains blocked without a configured object store.
- No unresolved high-confidence security finding was identified in this pass.

### Risks and Decisions

1. **Repository boundary:** the repository contains the deskbench runtime and no tix implementation. The product identity is standalone rather than a sibling package or compatibility layer.
2. **Git history:** implementation starts with a fresh repository initialization. The initial commit is `chore: initialize deskbench`.
3. **tix API availability:** Graph and HTTP integration tests cannot be made fully executable from this checkout without a tix checkout/deployment. The plan therefore separates protocol-level tests from environment-gated integration tests.
4. **Fault injection:** the first implementation uses injected provider wrappers and HTTP proxies, not production branches in tix.
5. **Component design:** components are designed specifically to satisfy deskbench contracts; domain model and CLI semantics target enterprise service desk evaluation.

### Verification and Handoff

Before implementation is declared complete, run the focused test after every task, then the full `pytest`, Ruff format/check, mypy, report JSON validation, and any available tix integration tests. The final Git verification must show a fresh single-line history beginning with `chore: initialize deskbench`, no restored `origin` remote unless explicitly requested, and clean product paths. Record actual command results in the final change summary; do not claim tix integration passed when it was skipped because no deployment was configured.

## T-002: deskbench 文档体系整理

**Kind:** maintenance
**Status:** verified
**Goal:** 建立可导航的项目文档入口，集中当前上下文，并说明架构、Adapter、数据集、报告和验证契约。

### Scope

- 增加 `CONTEXT.md` 和 `docs/index.md`。
- 增加架构、Adapter、数据集、报告和验证说明。
- 在 README 增加文档导航，并使 manifest 的数据状态与 `DatasetManifest` schema 一致。
- 不改变业务执行语义，不补造缺失的 tix RAG 数据或集成结果。

### Verification

- `uv run pytest tests/test_contracts.py tests/test_cli.py -q`：22 passed。
- manifest 状态解析测试已补充并通过。
- `git diff --check`：通过。
- 文档相对链接目标和任务/决策编号空槽检查：通过。

### Notes

P1 文档整理已完成。tix RAG 源资产和真实 tix 部署仍由 T-001 的未完成项跟踪。

## T-003: 真实 Tix HTTP 黑盒验收 MVP

**Kind:** feature
**Status:** verified
**Goal:** 以 Tix 当前公开 HTTP API 为边界，验证可重复的审批锁定、合法恢复和最终业务事实闭环。

### Architecture

deskbench 将 Tix 视为外部系统，仅通过 `/auth/login`、`/tickets`、Ticket 详情、`transition` 与 `resume` 公开接口交互。业务句柄使用 `ticket_id`，审批恢复句柄使用详情中的 `thread_id`；部署或数据库生命周期负责清理，Adapter 不调用不存在的 run 删除接口。HTTP MVP 可使用共享开发部署，但该模式会在共享数据库中留下测试工单，不能证明部署隔离或自动清理。

### Out of Scope

不扩展 Tix 生产代码，不实现评测专用接口、Graph/Fault/RAG/S3 或通用平台能力；没有真实部署时只运行协议测试，并将 integration 明确标记为 skip，不把 Mock 结果当作真实集成证据。共享开发部署可用于本 MVP，但不提供独立部署隔离或自动清理证据。

### Requirements

- Adapter 支持 token 或 username/password 登录，创建工单接受 `202` 并校验 `ticket_id`。
- 详情读取保留 Ticket 业务字段和事件证据，未知字段进入 `raw`；错误保留 HTTP 状态、端点、服务端 code/detail 和 transport/schema 分类。
- 支持 bounded 状态轮询、审批 `/resume`、普通 transition/PATCH 拒绝探针；HTTP 200 不单独代表业务成功。
- Case 覆盖高风险工单审批态、审批期间普通修改被拒绝、合法 resume 后读取状态和事件。

### Delivery

- [x] 将 HTTP Adapter 从虚构 `/runs` 协议改为真实 Ticket API。
- [x] 增加 MockTransport 契约和无部署明确跳过的 integration 测试。
- [x] 同步 CanonicalState/Trace、README、Adapter 与验证文档。
- [x] 运行局部及完整 pytest、Ruff format/check、mypy，并记录真实部署不可用状态。

### Verification

共享开发部署的真实 HTTP 集成已执行；测试覆盖两次审批窗口（分派审批与解决复审）、审批期间普通 transition 拒绝、两次合法 `/resume` 以及最终业务事实读取。测试工单留存在共享开发数据库中；未验证独立部署隔离与自动清理。

- 受控本地环境注入测试账号且清除不可用代理后，`uv run pytest tests/test_tix_integration.py -q` → `2 passed in 25.77s`（asyncio + trio）；Secret 值未写入记录。
- `curl --max-time 75 -sS http://127.0.0.1:8000/health` → HTTP 200，overall `healthy`
- `uv run pytest tests/test_tix_http_adapter.py -q` → `14 passed`
- `uv run pytest -q` → `88 passed, 2 skipped`
- `uv run ruff format --check src tests evals` → `52 files already formatted`
- `uv run ruff check src tests evals` → `All checks passed!`
- `uv run mypy src tests evals` → `Success: no issues found in 52 source files`
- `tests/test_tix_integration.py` 在未注入部署参数时仍会明确显示 `2 skipped`；本次真实运行通过上面的受控进程注入完成。

真实 Tix HTTP 集成已验证；部署隔离、自动清理和 RAG 源资产仍未验证。协议测试通过不等价于部署验证通过。

## T-004: Tix HTTP Adapter 审批生命周期修复

**Kind:** maintenance
**Status:** verified
**Goal:** 使公开 Tix HTTP Adapter 与通用 Runner 正确处理异步建单、两阶段审批、HTTP 200 结构化失败和严格的真实集成门禁。

### Architecture

Adapter 仍只调用 Tix 公开 Ticket API；建单后通过有界详情轮询发现首个审批窗口，resume 解析完整 `GraphRunResponse` 并将后续 interrupt 传回 Runner。探针保留业务响应证据，真实集成测试只在缺少部署时 skip，连接成功但状态/锁定/终态不符时失败。

### Out of Scope

不新增 Tix 评测专用接口、删除接口、Graph/Fault/RAG 扩展或生产分支；跨工单 thread 纵深校验作为后续安全增强，不在本次最小修复内。

### Requirements

- [x] submit 后发现并返回初始审批中断，使通用 Runner 能驱动交互。
- [x] resume 校验完整响应，暴露 HTTP 200 的 `result.error`，并保留下一阶段 interrupt。
- [x] probe 不把“返回 ticket”单独等同于业务成功，保留状态/响应证据。
- [x] 真实集成测试覆盖每个审批窗口的 transition/PATCH 锁定、审批事件和严格 `closed` 终态。
- [x] 真实集成测试使用版本化 approval fixture 或等价完整契约。

### Verification

- `uv run pytest tests/test_tix_http_adapter.py tests/test_runner.py -q` → `40 passed`
- `uv run pytest tests/test_tix_http_adapter.py -q` → `31 passed`
- `uv run ruff format --check src tests evals` → `52 files already formatted`
- `uv run ruff check src tests evals` → `All checks passed!`
- `uv run mypy src tests evals` → `Success: no issues found in 52 source files`
- `uv run pytest -q`（未注入部署配置）→ `110 passed, 2 skipped in 2.22s`
- 修复 P1 安全与一致性检查：`_discover_interrupt` 与 `resume` 校验 `ticket.id`/`result.ticket_id`/`interrupted.ticket_id` 与请求工单一致，强制校验 `interrupted` 对象非空字段，校验 `completed`/`interrupted` 状态一致性，校验 `poll_interval > 0`，保留 probe 真实 `status_code`。
- 共享开发部署真实 HTTP 集成验证：受控注入环境配置后，`uv run pytest tests/test_tix_integration.py -q` → `2 passed in 28.55s`（asyncio + trio 通过）。两阶段审批（dispatch approval 与 resolution review）、审批窗口锁定探针（transition/PATCH 409/422 拒绝）、双次合法 resume 推进及严格 `closed` 终态均获真实证据验证。

剩余限制：真实集成验证使用共享开发部署，测试工单留存于共享数据库中；独立部署隔离与自动清理未由 Adapter 实现，属于部署编排职责。Tix HTTP Adapter 的 thread ownership 纵深校验不在本任务范围。

## T-005: 首批端到端报告生成、基线固化与回归门禁验证

**Kind:** feature
**Status:** verified
**Goal:** 在共享开发部署上运行真实 Tix 端到端评测生成报告，固化回归基线，并验证 Gate CLI 的通过与多维熔断逻辑。

### Architecture

使用 CLI `deskbench run --adapter http` 运行版本化数据集，生成包含状态、轨迹和 4 类 Scorer 评分的 `summary.json`、`cases.jsonl`、`markdown.md`；将完整通过的审批用例运行结果固化为 `reports/baseline/`；使用 `deskbench gate --baseline ...` 验证一致性通过，并注入劣化模拟数据验证完成率回退、P95 延迟恶化、工具调用无解释增长与硬安全门禁熔断。

### Out of Scope

不在此任务中修改 Tix 生产代码或挂载外部故障代理；不将 `reports/` 签入源码控制（由 `.gitignore` 管理）。

### Requirements

- [x] CLI `run` 成功在真实 Tix 服务上执行 `approval.yaml`，生成端到端运行报告，4 类 Scorer 全通通过（1.000）。
- [x] 固化首份标准 Baseline 至 `reports/baseline/`，派生硬门禁率全为 0.0、完成率 1.0、P95 延迟与平均工具调用数。
- [x] CLI `gate` 针对 baseline 进行回归比较，相同指标下验证通过（`passed: true`，退出码 0）。
- [x] 验证 Gate 的多维熔断：完成率回退、P95 延迟超过 1.2 倍、工具调用无解释增长及审批绕过硬安全门禁，均输出对应 failure 代码且退出码为 1。
- [x] 在 `tests/test_cli.py` 中补充针对带 baseline 的 gate CLI 自动化测试。

### Verification

- 受控环境注入 Tix 测试账号运行 CLI 生成报告：
  - `uv run deskbench run --adapter http --dataset datasets/servicedesk_v1/approval.yaml --output reports` → `evaluated 1 cases; report: reports/2026-09-05T081622.342540Z`（退出码 0）。
  - 该次运行各 Scorer 得分：outcome 1.000、workflow_invariants 1.000、trajectory 1.000、resilience 1.000；最终工单状态为 `closed`，带完整 12 条 trace 事件。
  - `uv run deskbench score --report reports/2026-09-05T081622.342540Z` → `scored 1/1 cases`（退出码 0）。
  - `uv run deskbench score --report reports/2026-09-05T081622.342540Z --json` → `{"case_count": 1, "passed_count": 1}`。
- 基线固化与 Gate 一致性验证：
  - 复制为基线至 `reports/baseline/`，派生指标：硬安全门禁率均为 0.0，completion_rate=1.0，P95 延迟=12.8s。
  - `uv run deskbench gate --report reports/2026-09-05T081622.342540Z --baseline reports/baseline` → `{"failures": [], "passed": true}`（退出码 0）。
- Gate 多维熔断验证：
  - 完成率回退（completion_regression）：`{"failures": ["completion_regression"], "passed": false}`（退出码 1）。
  - P95 延迟恶化（p95_latency_regression）：`{"failures": ["p95_latency_regression"], "passed": false}`（退出码 1）。
  - 工具调用无解释超量增长（unexplained_tool_call_growth）：`{"failures": ["unexplained_tool_call_growth"], "passed": false}`（退出码 1）。
  - 审批绕过硬门禁（approval_bypass_rate）：`{"failures": ["approval_bypass_rate", "completion_regression"], "passed": false}`（退出码 1）。
- 自动化测试与质量检查：
  - `uv run pytest -q` → `112 passed, 2 skipped in 3.12s`。
  - `uv run ruff format --check src tests evals` → `52 files already formatted`。
  - `uv run ruff check src tests evals` → `All checks passed!`。
  - `uv run mypy src tests evals` → `Success: no issues found in 52 source files`。

## T-006: Tix 与 deskbench 对接缺陷修复与多数据集真实闭环验证

**Kind:** bugfix/feature
**Status:** verified
**Goal:** 解决 Tix 与 deskbench 在 HTTP 接口、错误契约、状态流转、轮询竞态与评测用例规范上的对接问题，并在真实 Tix 服务上实现全量数据集端到端闭环验证。

### Architecture

遵循“不让 Tix 适配 Bench，保持 Tix 业务通用自洽”原则：
1. **Tix 侧**：规范全局 `AppError` 错误契约（`detail` 为空时提供 `message`），将流转锁定与更新锁定统一为 `TicketLockedError`（409 `TICKET_LOCKED`）；在图转换节点实现凭据前置原子绑定消除审批时序竞态；在调度器实现 `run_lock` 单飞行护栏并在崩溃时通过独立事务记录系统审计事件安全升级；在 `resume_node` 闭环多阶段审批凭据持久化与终态凭据清理。
2. **Bench 侧**：修复 `TixHttpAdapter` 错误提取、状态派生与审批事件映射；解耦业务流转升级（`escalated`）与系统降级（`degraded`）；重构 `execution.py` 与 `trajectory.py` 仅统计 Agent 决策步数，排除底层数据库关系表审计日志；修复 `TixGraphAdapter` 协议凭据字段对齐；屏蔽宿主网络代理劫持。
3. **数据集规范化**：将虚构的优先级与状态对齐为 Tix 的 ITIL 规范（P0-P4、escalated）；同步导入 3 份 RAG 真实数据文件并更新 manifest 状态为 `available`。

### Out of Scope

不为 Bench 开设测试专用端点或特化分支；不改变 Tix 核心状态机与 ITIL 三维优先级体系。

### Requirements

- [x] 修复 `TixHttpAdapter._error_fields` 提取 Tix `AppError` 报错为 `"None"` 的 Bug。
- [x] 修复 `_discover_interrupt` 在审批状态但 `thread_id` 回写微秒级延迟时的竞态报错，改为有界重试。
- [x] 修复 HTTP 客户端受宿主全局 SOCKS 代理污染问题（`trust_env=False`）。
- [x] 规范化 `happy_path.yaml` 为真实低危自动流转用例，规范化 `security.yaml` 对齐 D-003 有限回边审批规则。
- [x] 从 Tix 导入 `rag_queries.yaml`、`rag_tickets.yaml`、`rag_kb_articles.yaml` 并将 manifest 状态置为 `available`。
- [x] 在真实运行的 Tix 实例上完整跑通 `test_tix_integration.py`（2 passed in 28s）、`happy_path.yaml`（2/2 passed）、`approval.yaml`（1/1 passed）、`security.yaml`（2/2 passed）。

### Verification

- `cd deskbench && uv run pytest -q` → `112 passed, 2 skipped`
- `cd deskbench && uv run ruff format --check src tests evals && uv run ruff check src tests evals && uv run mypy src tests evals` → 全部通过
- `cd tix/backend && uv run pytest tests/ --ignore=tests/e2e -q && uv run ruff check src tests scripts && uv run mypy src` → 838 passed, 全部通过
- 真实 Tix 部署环境验证：
  - `pytest tests/test_tix_integration.py` → `2 passed in 28.20s`
  - CLI `happy_path.yaml` → `{"case_count": 2, "passed_count": 2}`（Outcome/Invariants/Trajectory/Resilience 4 类 Scorer 全 1.000）
  - CLI `approval.yaml` → `{"case_count": 1, "passed_count": 1}`（4 类 Scorer 全 1.000）
  - CLI `security.yaml` → `{"case_count": 2, "passed_count": 2}`（4 类 Scorer 全 1.000）

## T-007: Tix 真实混合检索端到端评测集成与执行层健壮性加固

**Kind:** feature/maintenance
**Status:** verified
**Goal:** 补齐针对 Tix 真实混合检索（KB 与工单搜索）的端到端集成评测能力，并加固 Runner 交互执行循环与 TixHttpAdapter 对重复恢复、状态派生与错误事件的映射契约。

### Architecture

1. **检索边界**：在 `TixRetrievalAdapter` 之上增加 `TixHttpRetrievalClient`，直接对接 Tix `/api/kb/search` 与 `/api/tickets/search` 公开检索接口；集成测试提供 HTTP 远程与 Local DB 双运行路径。
2. **交互循环**：清理 Runner 中对中断状态的过早判断，使交互序列能完整驱动测试场景（如 duplicate resume 校验）。
3. **适配器容错与状态精度**：在 `TixHttpAdapter` 中宽容处理非中断状态下的重复恢复失败，并深度挖掘工单及事件中的 `review_required`、`degraded` 及编排器崩溃日志。
4. **CLI 默认行为**：默认执行适配器对齐为 `http`。

### Requirements

- [x] 实现 `TixHttpRetrievalClient`，适配 Tix HTTP 检索接口并支持认证 token。
- [x] 编写 `tests/test_tix_retrieval_integration.py`，支持基于环境变量（URL 或 Config）运行真实混合检索验收。
- [x] 优化 `execution.py` 交互循环，移除错误的中断截断条件。
- [x] 优化 `TixHttpAdapter.resume` 处理 duplicate resume 错误时的优雅降级。
- [x] 准确映射 `needs_review`、`degraded` 标记与 `orchestrator_failure` 错误事件。
- [x] 将 CLI 默认适配器修改为 `http`。

### Verification

- `uv run pytest -q` → 112 passed, 3 skipped（集成测试受环境门控保护）。
- `uv run ruff check src tests evals` → All checks passed。
- `uv run mypy src tests evals` → Success: no issues found in 53 source files。

## T-008:

