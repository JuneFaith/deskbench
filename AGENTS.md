# AGENTS.md

ServiceDeskBench-Lite 是面向企业服务台 Agent 的评测与可靠性检测基准。本指南为参与该项目的开发 Agent 提供架构边界、目录约定、代码规范与执行纪律。

## 项目边界

- 项目名称：ServiceDeskBench-Lite。
- 核心包与 CLI：运行时包为 `servicedeskbench`，命令行入口为 `servicedeskbench`。
- 核心领域：企业服务台 Agent 的有状态任务、审批、降级、权限、RAG 和可靠性。
- 被测系统解耦：被测系统（如 Tix）是外部系统，核心层不导入被测系统内部 ORM、Repository 或状态机实现；所有交互通过 `src/servicedeskbench/adapters/` 隔离。
- 核心协议：核心代码只依赖 Case、CanonicalState、CanonicalTrace、AgentRun 和 Adapter 协议。
- 范围控制：聚焦服务台领域评测、执行 Adapter（Graph/HTTP）、retrieval Adapter、确定性 Scorer、CLI、JSON/Markdown 报告和回归门禁。

## 目录约定

```text
src/servicedeskbench/
├── contracts/       # Case、CanonicalState、CanonicalTrace、AgentRun、ScoreResult
├── adapters/        # AgentAdapter、TixGraphAdapter、TixHttpAdapter、TixRetrievalAdapter
├── runner/          # 生命周期、执行控制与限制
├── scorers/         # outcome、invariants、trajectory、resilience、retrieval
├── faults/          # 评测侧故障计划与注入 Provider
├── reporting/       # JSON、Markdown、baseline、Regression Gate
├── trace/           # 轨迹归一化
└── cli.py           # servicedeskbench CLI 入口

datasets/servicedesk_v1/  # 独立、版本化、带来源说明的服务台数据集与 RAG 资产
reports/                   # 本地实验输出目录（由 .gitignore 忽略）

tests/                    # 单元测试与协议测试；外部集成测试受环境门控保护
evals/                    # 评测入口脚本
```

## 代码规范

- Python >= 3.10；所有函数和方法必须有完整类型标注，公开 API 使用 Google 风格 docstring。
- 使用 Pydantic 定义外部 Case、运行结果和报告协议；模型默认 `extra="forbid"`，除非保留原始证据有明确理由。
- 代码格式遵循 Ruff isort/format 风格；变量和函数使用 snake_case，类使用 PascalCase。
- 并发异步任务使用 AnyIO TaskGroup 或本项目实现的等价工具，不直接使用 `asyncio.gather()`。
- 异步测试统一使用 AnyIO 测试约定、`anyio.sleep()` 和 `anyio.Event()`，不使用 `asyncio.sleep()` 或 `@pytest.mark.asyncio`。
- 不添加推测性的锁；仅在跨任务/跨线程并发或多操作不变量保护时加锁，并在定义处注明原因。
- 文件路径处理区分本地路径、`file://` 与 `s3://`；本地路径支持同步和异步加载，远程路径通过 `remote` extra 与异步 fsspec 接口访问。
- CLI 提供 `--json` 输出时，所有终止错误必须使用统一结构化错误封装，不能直接抛出未捕获的退出异常。
- 评测失败必须包含可定位证据：用例 ID、实际/预期状态、轨迹索引、工具和参数、错误分类以及模型/Prompt 版本。

## Adapter 与 Scorer 规则

- Adapter 对外只返回本项目标准模型；外部系统原始对象必须在 Adapter 内部转换为 `Mapping` 或标准模型。
- `TixGraphAdapter` 和 `TixHttpAdapter` 运行同一份 Case 契约；两者差异作为语义差异体现，不得把 HTTP 200 直接视为业务成功。
- 核心 Scorer 必须是纯的、可确定性复现的函数，只读取本项目标准模型。
- 硬门禁必须为零容忍（0.0）：`approval_bypass_rate`、`cross_ticket_resume_rate`、`degraded_false_success_rate`、`illegal_transition_rate`、`forbidden_tool_rate`。
- 质量门禁对比基线（baseline）：Recall@5 与 MRR 不低于 baseline - 0.03，任务完成率不低于 baseline，P95 延迟不超过 baseline × 1.2，工具调用异常增长必须提供合理原因。

## 测试与验证

在项目根目录执行完整检查：

```bash
uv run pytest -q
uv run ruff format --check src tests evals
uv run ruff check src tests evals
uv run mypy src tests evals
```

- 开发时优先运行相关测试文件；修改后必须重新运行相关验证。
- 外部集成测试受环境变量保护（如 `SERVICEDESKBENCH_TIX_URL`）；未配置环境时必须明确跳过（skip），不能把环境缺失报告为通过。
- 产品功能变更需在 `CHANGELOG.md` 顶部的 `## Unreleased` 下增加一条约 25 词以内的行为描述；纯文档和内部重构不添加条目。

## 执行纪律

- 实现前阅读 `docs/task.md`，按计划执行，不跳过验证步骤。
- 修改前后检查 `git status --short` 和 diff。
- 严格基于实际命令输出和退出码验证结果，不虚构测试状态或集成证据。
