# 数据集说明

## 版本目录

当前数据集位于：

```text
datasets/servicedesk_v1/
├── manifest.yaml
├── happy_path.yaml
├── approval.yaml
├── degradation.yaml
└── security.yaml
```

每个 YAML case 文件是 Case 列表。Case 包含输入、交互步骤、预期结果、策略限制和可选故障计划。manifest 提供 `dataset_version`、来源、数据状态、标注语义和文件清单；加载目录或 manifest 时，manifest 元数据会补入没有显式填写这些字段的 Case。当前 `status.core_cases` 为 `available`，`status.rag_assets` 为 `pending_external_source`。

## 当前数据状态

核心 Case fixture 当前可用。RAG 源资产尚未提供，manifest 记录了预期来源路径和标签语义，但不包含伪造的 `rag_queries.yaml`、`rag_tickets.yaml` 或 `rag_kb_articles.yaml`。因此当前版本不能生成有意义的 tix RAG fixture 报告。

## 路径形式

| 路径 | API | 说明 |
| --- | --- | --- |
| plain local path | `load_cases(path)` | 同步读取本地 YAML、manifest 或目录 |
| `file://` | `load_cases(url)` | 同步读取本地 file URL；异步流程使用 `load_cases_async` |
| `s3://` 文件 | `await load_cases_async(url)` | 使用 remote extra 和异步 fsspec 读取 |
| `s3://` 前缀 | `await load_cases_async(prefix)` | 查找前缀下的 `manifest.yaml`，再读取 manifest 文件 |

S3 路径不能通过同步 API 或线程包装同步 I/O 读取；当前实现要求 asyncio AnyIO backend。

## 新增数据的要求

1. 增加新的版本目录或明确更新 `dataset_version`。
2. 在 manifest 中记录真实来源、标签语义和文件清单。
3. 保留正样本、负样本和混淆样本的语义，不用运行时导入 tix 测试代替数据。
4. 数据缺失时记录 `pending_external_source`，不要生成占位样本。
5. 更新 README、manifest 和对应测试。
