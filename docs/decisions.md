# Decisions

## D-001: Tix is an external system under test

**Status:** adopted

- **Decision:** Core deskbench contracts, runner, scorers, faults, reports, and CLI remain independent of tix; tix-specific knowledge is isolated to Adapter modules.
- **Reason:** Tix source and deployment are not present in this checkout, and the benchmark must not be coupled to tix ORM or internal database objects.
- **Rejected:** Importing tix tests or internals into core code, or adding test-only production paths to tix.
- **Consequence:** Protocol-level tests run locally; real Graph/HTTP integration tests require an externally configured tix deployment.

## D-002: Lite version uses deterministic core gates

**Status:** adopted

- **Decision:** The first usable version prioritizes deterministic outcome, workflow-invariant, trajectory, resilience, retrieval, reporting, and regression-gate behavior; optional community metric integrations remain outside the core.
- **Reason:** Service-desk state-machine, approval, permission, degradation, and recovery rules must be mechanically auditable.
- **Rejected:** Making a general-purpose LLM judge or observability platform the core runtime.
- **Consequence:** Open-ended quality integrations can be added only after the canonical models and evidence-bearing gates are stable.

## D-003: Test responsibility split and externalized advanced acceptance evaluation

**Status:** adopted

- **Decision:** Tix retains implementation-correctness tests and deployment smoke checks: unit tests, state-machine/Guard/Action tests, Repository/UoW and database tests, API parameter and basic permission tests, Graph-node tests, database schema tests, EventBus/Outbox contract tests, and startup/health checks. deskbench owns advanced system-behavior evaluation: complete service-desk lifecycles, black-box acceptance, approval bypass, permission violations, illegal workflows, degradation and recovery, duplicate resume, cross-ticket thread use, RAG regression, and cross-model/Prompt/Embedding/version reports and gates.
- **Reason:** Tix implementation tests and smoke checks have a different lifecycle and purpose from externally verifiable product behavior and cross-version evaluation. The external layer avoids making the product repository the sole source of evidence while allowing Tix to run without the evaluation project.
- **Boundary:** deskbench uses versioned Cases, canonical evidence, and deterministic Scorers at the external boundary. Tix must not add `evaluation_mode`, evaluation shortcuts, evaluation-only business endpoints, or production branches. Existing Tix tests are not mechanically moved into the benchmark.
- **Implementation status:** This decision establishes ownership only. The real Tix adapter, run/isolation unit, evidence contract, fault-injection boundary, dataset ownership, and reporting/deployment workflow remain separate implementation decisions (see T-003 for the adopted HTTP black-box MVP). Mock or protocol tests must not be described as real Tix integration evidence.
- **Consequence:** New tests about external service-desk behavior should be added to deskbench; tests about Tix implementation defects remain in Tix, with both layers used when appropriate.
- **Out of scope:** Immediate relocation or deletion of existing Tix tests; selecting full Graph versus HTTP for all future scenarios (T-003 adopted the HTTP black-box MVP for the public acceptance seam); a general fault platform, S3 dataset support, Dashboard, or multi-domain Benchmark.
