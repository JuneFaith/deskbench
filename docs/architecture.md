# 架构说明

## 目标

ServiceDeskBench-Lite 评估服务台 Agent 的业务结果、执行路径、流程合规性、故障恢复、检索质量和性能证据，而不是只检查最终文本。

## 执行流水线

```text
Dataset (Case)
    │
    ▼
Runner: load → prepare → submit → resume → result → cleanup
    │
    ▼
Adapter boundary
    ├── TixGraphAdapter  (local graph)
    ├── TixHttpAdapter   (public HTTP)
    └── TixRetrievalAdapter (retrieval experiment)
    │
    ▼
Canonical models
    ├── CanonicalState
    ├── CanonicalTrace
    └── AgentRun
    │
    ▼
Deterministic scorers
    ├── outcome
    ├── invariants
    ├── trajectory
    ├── resilience
    └── retrieval (independent retrieval inputs)
    │
    ▼
EvaluationReport → summary.json / cases.jsonl / markdown.md
    │
    ▼
Regression Gate
```

## 模块边界

| 模块 | 职责 | 不负责 |
| --- | --- | --- |
| `contracts/` | 定义 Case、状态、轨迹、运行和评分协议 | 访问 tix 或执行网络请求 |
| `adapters/` | 连接 tix Graph、HTTP 和 retrieval 边界，转换为标准模型 | 把 tix 对象泄漏给核心层 |
| `runner/` | 控制生命周期、交互、超时、步骤和工具调用限制 | 定义业务评分规则 |
| `scorers/` | 对 canonical 模型执行纯的确定性检查 | 读取 tix ORM、数据库或内部状态 |
| `faults/` | 提供评测侧故障计划和注入 Provider | 修改 tix 生产逻辑 |
| `reporting/` | 持久化证据、计算摘要和执行门禁 | 覆盖已有实验目录 |
| `cli.py` | 解析命令和配置，在边界处选择 Adapter | 在核心层隐式发现 tix |

## 证据流

Adapter 必须在边界内把外部响应转换为 `Mapping` 或标准 Pydantic 模型。轨迹归一化保留未知字段到 `raw`，使 Scorer 能通过事件索引、工具名、参数、实际/预期状态和错误分类定位失败。

Runner 发生错误时仍返回带 `error` 和 `CanonicalTrace` 错误事件的 `AgentRun`，并在 finally 路径执行有界清理。HTTP 状态码仅表示传输层结果；HTTP 200 不等于业务成功。

## 版本与依赖边界

运行时包为 `servicedeskbench`。核心依赖 Pydantic、PyYAML、httpx 和 AnyIO；S3 支持通过 `remote` extra 提供。tix 源码和部署不属于本仓库，真实集成依赖环境变量和外部服务。
