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

## D-004: 适配器故障注入能力边界与黑盒评测跳过语义

**Status:** adopted

- **Decision:** 在评测适配器协议中引入显式的故障注入能力感知方法（`supports_fault(fault: FaultPlan) -> bool`）。黑盒适配器（`TixHttpAdapter`）明确声明仅支持客户端层面的交互故障（如 `duplicate_resume`），拒绝服务端在体内部组件故障（如 `llm:timeout`、`embedding:unavailable`）；沙箱/白盒适配器（`TixGraphAdapter`）则声明支持全量组件故障。当用例指定的故障超出当前适配器执行能力时，Runner 不发起无效执行，而是将该用例记录为结构化跳过（`skipped=True`，状态为 `skipped`，记录 `LIFECYCLE` 跳过原因事件）；评测层（Evaluation）跳过 Scorer 评分，报告与 CLI 显式呈现跳过计数，回归门禁（Gate）在计算完成率时排除被跳过的用例。
- **Reason:** 遵循 D-001 与 D-003 原则，Tix 作为生产被测系统绝不在生产代码中植入故障注入后门端点；在真实 HTTP 黑盒评测环境下，底层健康的服务端不会发生模拟的组件超时或服务不可用，如果不做能力协商直接执行，会导致真实系统按正常高危审批流转却被 Scorer 误判为降级失败，产生假阴性（False Negative）；显式协商与跳过语义既保留了评测集完整性与可追溯性，又保证了不同适配器评测结果的严谨性。
- **Rejected:** 
  - 在 Tix 生产 API 中引入调试/故障注入端点以满足 HTTP 降级评测（严重破坏生产洁净与真实性边界）。
  - 将不支持的故障用例强行执行并报告为失败（指标失真，混淆黑盒验收与组件容错）。
  - 静默丢弃不支持的用例且不在报告中保留跳过审计踪迹（丧失评测审计证据可追溯性）。
- **Consequence:** 评测报告明确区分“成功通过”、“真实失败”与“适配器能力受限跳过”；HTTP 适配器评测聚焦于黑盒协议与流转不变量，Graph 适配器聚焦于在体组件依赖降级；门禁指标计算严密且无假阴性干扰。

## D-005: RAG 混合检索端到端评测体系与多源基准

**Status:** adopted

- **Decision:** 确立 Deskbench 的 RAG 混合检索端到端评测体系与多源（Knowledge Base 知识库文章 `kb` 与 Historical Tickets 历史工单 `ticket`）切分基准架构。评测层通过统一的 `RetrievalClient` 抽象对接 HTTP 真实公开端点（`/api/kb/search`、`/api/tickets/search`）与本地检索沙箱；采用确定性相关性模型与多维排名指标（Recall@1/3/5、Precision@5、MRR、NDCG@5、主题分面 Topic breakdown 以及反向干扰样本 Negative confounder 泄漏率）；并将检索评测提升为 CLI 一等公民命令（`deskbench retrieval` 与独立入口 `evals.retrieval_eval`），持久化结构化报告（`retrieval_summary.json` 与 `retrieval_markdown.md`）用于基线对比与防劣化门禁。
- **Reason:** 混合检索是工单智能决策与分类排障的关键前置输入，检索召回与抗干扰质量直接决定下游 Agent 的流转质量；KB 文章与历史工单在文档形态、时效性与语义粒度上差异显著，混杂打分会掩盖单源检索缺陷，必须支持多源独立度量；遵循 D-001 与 D-003 原则，通过真实公开检索接口与黑盒凭据评测，不入侵被测系统内部实现。
- **Rejected:** 
  - 将检索评测降级为端到端流转测试的隐式副作用（无法准确定位检索质量与流转质量的故障归因）。
  - 依赖黑盒 LLM Judge 进行检索主观打分（缺乏确定性、审计可复现性且开销高昂）。
  - 将知识库文章与历史工单粗粒度混合为单一池打分（掩盖不同数据源的召回短板与长尾分布偏差）。
- **Consequence:** 检索评测与状态机评测形成互补闭环；对检索模型漂移、分词参数变动、混合检索权重配置具备可量化、可比较的自动化门禁防御能力。

## D-006: 工单全生命周期场景扩充、分层治理与 RAG 复合检索提精

**Status:** adopted

- **Decision:** 将 Deskbench 评测数据集从初期原型推进至“数据演进（Data Evolution）”架构。核心流转场景扩展为涵盖标准咨询、高危分派审批、方案审查放行/打回（`review.yaml`）、单次驳回自愈重分派（`recovery.yaml`）以及重大网络基础设施故障（`network.yaml`）的工单全生命周期闭环；评测清单规范化升级为三层治理模型（`core_lifecycle` 核心生命周期流转、`fault_injection` 在体与客户端故障注入、`rag_benchmarks` 检索评测资产），通过 `manifest.yaml` 的 `layers` 字段建立结构化映射与分类状态标记；在 RAG 混合检索评测集上，修复已知真值标注遗漏（如 `rag-q-ac-001` 补入 Rank 1 召回的 BOLA 规范文档 `rag-kb-ac-005`），扩充 12 条涵盖网络超时、连接池耗尽、前端缓存污染、CORS 跨域、OOM、数据备份等跨领域复合难例（`rag-q-comp-001` ~ `rag-q-comp-012`），并显式定义混淆干扰项（`negative_kb_articles` 与 `negative_tickets`）确立 0.00% 负向泄露刚性门禁。
- **Reason:** 服务台系统的真实业务复杂度主要集中在方案审查打回、专家重分派容错、重大基础设施故障调度等高阶场景；早期仅有 4 个用例无法充分覆盖状态机的所有关键分支和自愈回路；RAG 混合检索在面对跨领域复合故障时极易发生语义混淆与负向泄露，必须通过复合难例与显式负样本约束保证召回抗干扰性；分层治理使评测集具备面向不同评测目的（回归门禁、黑盒验收、沙箱容错）的模块化调度能力。
- **Rejected:**
  - 将所有场景堆叠在单个庞大的测试文件中（丧失职责边界与细粒度追踪能力）。
  - 在检索评测集中仅做单主题简单查询而忽视跨领域复合长尾故障（导致真实生产中检索抗混淆能力不足）。
  - 允许负向干扰文档渗入 Top-5 召回（破坏检索评测的高置信度与严格度）。
- **Consequence:** Deskbench 用例规模从 7 个扩充至 12 个（核心流转 10 个，降级跳过 2 个），覆盖工单流转全生命周期；RAG 评测集扩充至 76 条，综合 Recall@5 达 100.0%，MRR 提升至 0.9413，负向泄露率维持 0.00%；数据层结构清晰且完全向后兼容。

## D-007: 评测环境健康探查、防饱和感知与测试生命周期清理

**Status:** adopted

- **Decision:** 在 Deskbench 评测层中引入独立的环境探查与生命周期治理模块（`deskbench.environment` 与 `deskbench env` CLI 子命令）。支持对被测系统服务就绪状态（`/health`）与坐席承接能力（`GET /api/handlers`）进行自动化探查，感知坐席过载与饱和状态（`current_load >= max_load`）；提供幂等环境清理能力（`clean_environment`），优先通过容器运行时（Podman/Docker）在数据库底层精准级联清除 API 渠道评测工单并归零坐席负载，或回退至被测系统运维调和命令（`reconcile --purge-api-tickets`）；并在 `deskbench run` 中提供 `--pre-clean` 选项，在基准测试执行前自动净化共享环境。
- **Reason:** 黑盒 HTTP 评测复用共享部署时，历史测试工单持续堆积，未正常终态关闭的测试工单会导致坐席负载无法释放直至饱和，进而导致后续分派测试因坐席满载而误转人工（产生假阴性）；遵循 D-001 原则，Tix 生产 API 严格禁止暴露无鉴权的删除/重置后门，因此通过外部环境探针感知坐席饱和，结合容器/运维生命周期钩子进行非侵入式复位，既保持被测系统生产代码的纯净性，又彻底解决了共享环境数据污染与负载饱和问题。
- **Rejected:** 
  - 在 Tix 生产 API 中引入评测专用的清库端点（违反 D-001 与生产安全性要求）。
  - 忽视坐席负载累积，任由并发与长尾测试跑至坐席耗尽后随机失败（严重破坏基准评测结果的稳定性与可复现性）。
- **Consequence:** Deskbench 具备了端到端自包含环境健康检查（`deskbench env status`）与一键清理（`deskbench env clean`）能力；`run --pre-clean` 保证评测始终在干净的专家零负载状态下启动；全量 12 个场景与 76 条检索用例在多次反复执行下保持 100% 稳定通过。


