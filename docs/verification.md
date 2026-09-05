# 验证指南

## 本地验证

在项目根目录执行完整门禁：

```bash
uv run pytest -q
uv run ruff format --check src tests evals
uv run ruff check src tests evals
uv run mypy src tests evals
uv run python -m servicedeskbench.cli --help
```

开发期间可先运行相关测试：

```bash
uv run pytest tests/test_contracts.py tests/test_cli.py -q
uv run pytest tests/test_adapter_contract.py tests/test_tix_graph_adapter.py -q
uv run pytest tests/test_tix_http_adapter.py -q
uv run pytest tests/test_runner.py tests/test_faults.py -q
uv run pytest tests/test_scorers.py tests/test_retrieval.py -q
uv run pytest tests/test_reporting.py tests/test_gate.py -q
```

## 测试层

- **Unit tests**：验证 contracts、trace 归一化、Runner、Scorer、报告和门禁，不需要 tix。
- **Protocol tests**：用注入的协议客户端验证 Graph/HTTP Adapter 的请求、映射和生命周期，不需要 tix 部署。
- **Integration tests**：通过 `integration` marker 访问真实 Tix 公共 Ticket API，要求配置 `SERVICEDESKBENCH_TIX_URL`、`SERVICEDESKBENCH_TIX_USERNAME` 和 `SERVICEDESKBENCH_TIX_PASSWORD`（Adapter 协议本身亦支持 token，当前集成测试用例按完整账号密码登录执行）。

## tix 集成

```bash
SERVICEDESKBENCH_TIX_URL=https://tix.example \
SERVICEDESKBENCH_TIX_USERNAME=... \
SERVICEDESKBENCH_TIX_PASSWORD=... \
  uv run pytest -m integration
```

未配置完整 Tix 连接参数时，真实集成测试会明确跳过。跳过不是通过；报告验证结果时必须单独列出跳过数量和原因。HTTP MVP 可以使用共享开发部署，但必须将结果标注为“共享开发部署上的真实 HTTP 集成”，不能据此声称已验证部署隔离或自动清理。当前共享部署验证覆盖两次审批窗口、审批锁定、合法 `/resume` 和最终状态读取，并已在 asyncio 与 trio 后端通过。协议测试使用 MockTransport，只证明 Adapter 契约，不证明部署行为。Tix 的模型配置由被测 Tix 部署的 `tix.yaml` 管理，不由本仓库配置。

## 文档检查

文档改动完成后至少检查：

```bash
git diff --check
uv run pytest tests/test_contracts.py tests/test_cli.py -q
```

同时确认 README 中的相对链接存在、manifest 与 `DatasetManifest` schema 一致、`docs/task.md` 和 `docs/decisions.md` 保留尾部编号空槽，以及 RAG 缺失状态没有被写成可用数据。
