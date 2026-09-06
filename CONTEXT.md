# deskbench 项目上下文

## 当前状态

deskbench 是面向企业服务台 Agent 的评测与可靠性检测基准。当前已完成 T-001 至 T-013 阶段任务，提供本地协议级评测、5 类确定性 Scorer（Outcome、Workflow Invariants、Trajectory、Resilience、Retrieval）、报告和回归门禁。已支持 Tix HTTP、Graph 与 Retrieval Adapter，并在真实 Tix 部署上完成全生命周期（咨询、审批、方案审查放行/打回、自愈重分派、重大网络故障、分级自主解决与安全护轨一票否决）评测集与提精后 RAG 混合检索（含跨领域复合难例与显式硬负样本）的端到端闭环验证与基线固化。评测资产采用三层治理模型（`core_lifecycle`、`fault_injection`、`rag_benchmarks`）并由 manifest 结构化管理；核心契约与评分器支持针对 AI 分级自主解决（`auto_resolved`）的确定性度量；提供环境就绪与坐席防饱和感知（`deskbench env status`）及非侵入式测试生命周期自动清理能力（`deskbench env clean` / `deskbench run --pre-clean`）。

## 术语表

- **Case**：一个版本化的服务台评测用例，包含输入、交互、预期结果、策略限制和可选故障计划。
- **CanonicalState**：Adapter 将被测系统状态映射后的业务事实模型；核心 Scorer 只读取此模型。
- **CanonicalTrace**：Adapter 将执行事件归一化后的有序证据；包含工具、状态变更、中断、恢复、错误和降级事件。
- **AgentRun**：一次 Case 执行的标准化结果，包括状态、轨迹、评分、错误和性能证据。
- **Adapter**：连接 deskbench 与被测系统的边界。当前有 tix Graph、tix HTTP 和 tix retrieval 三类 Adapter；HTTP 黑盒使用 `ticket_id` 业务句柄和 `thread_id` 审批句柄。
- **硬门禁**：必须为零的安全和流程错误率：审批绕过、跨工单恢复、降级误成功、非法状态迁移、禁止工具调用。
- **测试职责分层**：Tix 保留实现级测试与部署冒烟；deskbench 负责独立的系统级验收、可靠性与回归评测，不机械搬运 Tix 内部测试。

## 架构事实

```text
Case Dataset
    ↓
Evaluation Runner
    ↓
Agent Adapter
    ↓
CanonicalState / CanonicalTrace
    ↓
Deterministic Scorers
    ↓
JSON / Markdown Report
    ↓
Regression Gate
```

核心运行时包是 `src/deskbench/`。contracts、runner、scorers、faults 和 reporting 不依赖 tix 内部类型；只有 `adapters/` 处理 tix Graph、公开 HTTP 或检索协议。HTTP Adapter 只调用公开 `/auth/login`、`/tickets`、详情、`transition` 和 `resume`，不调用虚构的 `/runs` 资源；部署或数据库生命周期负责清理。HTTP 评测可以复用共享开发部署，但这不提供隔离和自动清理证据。CLI 入口是 `deskbench`。

数据集位于 `datasets/servicedesk_v1/`。核心 Case fixture 与 RAG 资产（`rag_queries.yaml`、`rag_tickets.yaml`、`rag_kb_articles.yaml`）均已就绪并由 `manifest.yaml` 记录元数据与来源路径。

## 生效决策

- [D-001](docs/decisions.md#d-001-tix-is-an-external-system-under-test)：tix 是外部被测系统，核心层不导入 tix。
- [D-002](docs/decisions.md#d-002-lite-version-uses-deterministic-core-gates)：Lite 版本优先使用确定性核心门禁。
- [D-003](docs/decisions.md#d-003-test-responsibility-split-and-externalized-advanced-acceptance-evaluation)：测试职责分层与高级验收评测外置。
- [D-004](docs/decisions.md#d-004-适配器故障注入能力边界与黑盒评测跳过语义)：适配器故障注入能力边界与黑盒评测跳过语义。
- [D-005](docs/decisions.md#d-005-rag-混合检索端到端评测体系与多源基准)：RAG 混合检索端到端评测体系与多源基准。
- [D-006](docs/decisions.md#d-006-工单全生命周期场景扩充分层治理与-rag-复合检索提精)：工单全生命周期场景扩充、分层治理与 RAG 复合检索提精。
- [D-007](docs/decisions.md#d-007-评测环境健康探查防饱和感知与测试生命周期清理)：评测环境健康探查、防饱和感知与测试生命周期清理。
- [D-008](docs/decisions.md#d-008-ai-分级自主解决断言契约护轨一票否决与评测闭环)：AI 分级自主解决断言契约、护轨一票否决与评测闭环。

## 当前任务

详细实施状态见 [`docs/task.md`](docs/task.md)（已完成基础架构搭建 T-001、文档整理 T-002、HTTP 黑盒验收 T-003、审批生命周期修复 T-004、首批报告与基线固化 T-005、对接缺陷修复与真实闭环验证 T-006、真实混合检索集成与执行加固 T-007、远端仓库配置与推送 T-008、故障感知与跳过语义加固 T-009、RAG 混合检索基线建立与 CLI 集成 T-010、数据演进与 Manifest 分层治理 T-011、评测环境探查与测试生命周期清理 T-012、分级自主解决评测与安全护轨断言 T-013）。后续关注点：

1. 自动化评测沙箱与 CI/CD 容器化流水线端到端编排；
2. 持续扩充真实故障注入与多场景评测用例。

## 负空间

当前版本不实现通用 LLM Judge、完整观测平台、Web Dashboard、在线监控、自动修复、多行业 Benchmark 或 tix 生产代码中的评测专用分支。社区评测和观测工具只能作为后续可选集成。
