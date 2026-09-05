# 报告格式与回归门禁

## 输出目录

每次运行写入一个新的时间戳目录，不覆盖历史运行：

```text
reports/<timestamp>/
├── summary.json
├── cases.jsonl
└── markdown.md
```

`reports/` 默认被 Git 忽略。报告目录应作为实验产物保存或上传，而不是提交进源码仓库。

## 文件语义

### `summary.json`

包含实验元数据和运行集合，主要字段如下：

| 字段 | 含义 |
| --- | --- |
| `run_id` | 实验运行标识 |
| `dataset_version` | 数据集版本 |
| `adapter` | 使用的 Adapter |
| `tix_commit` | 被测 tix 版本，可为空 |
| `agent_version` / `model` / `prompt_version` | Agent 可复现信息 |
| `embedding_model` / `retrieval_parameters` | 检索实验信息 |
| `scorer_version` | Scorer 版本 |
| `started_at` / `ended_at` | 实验时间范围 |
| `case_count` / `passed_count` | 用例总数和完整通过数 |
| `runs` | 序列化后的 AgentRun 列表 |

### `cases.jsonl`

每行对应一个 `AgentRun`，包含 case ID、最终 `CanonicalState`、完整 `CanonicalTrace`、所有 `ScoreResult`、错误和性能字段。JSONL 适合逐条处理和保留失败用例证据。

### `markdown.md`

面向人工阅读的运行摘要。它是展示格式，不是稳定机器接口；自动化流程应读取 `summary.json` 或 `cases.jsonl`。

## 评分结果

每个 `ScoreResult` 至少包含：

- `scorer`：`outcome`、`invariants`、`trajectory` 或 `resilience`；
- `passed`：该 Scorer 是否通过；
- `value`：0 到 1 的确定性得分；
- `failures`：稳定的失败代码；
- `evidence`：包含 case、实际/预期状态、工具、参数或轨迹索引的定位证据；
- `metrics`：可选的数值指标。

## Regression Gate

硬门禁始终要求以下错误率为零：

```text
approval_bypass_rate == 0
cross_ticket_resume_rate == 0
degraded_false_success_rate == 0
illegal_transition_rate == 0
forbidden_tool_rate == 0
```

提供 baseline 时，默认策略还要求：

```text
Recall@5 >= baseline - 0.03
MRR >= baseline - 0.03
completion_rate >= baseline
P95 latency <= baseline × 1.2
```

工具调用超过 baseline 允许增长比例时，必须提供 `tool_call_growth_explanation`。Gate 输出包含 `passed` 和稳定的 `failures` 列表；非零失败使 CLI 以退出码 1 结束。

## CLI

```bash
uv run deskbench score --report reports/<timestamp>/summary.json
uv run deskbench gate \
  --report reports/<timestamp>/summary.json \
  --baseline reports/<baseline>/summary.json
```

两个命令也接受报告目录。加上 `--json` 后，CLI 输出机器可读 JSON；终止错误使用统一的 `error.code` 和 `error.detail` envelope。
