# deskbench 文档

## 从哪里开始

- [README](../README.md)：安装、CLI、数据集、报告和 tix 配置。
- [项目上下文](../CONTEXT.md)：当前架构、术语、生效决策和未完成事项。

## 设计与协议

- [架构说明](architecture.md)：执行流水线、边界和评分层。
- [Adapter 协议](adapters.md)：Graph、HTTP 和 retrieval Adapter 的生命周期与语义。
- [报告格式与门禁](reporting.md)：报告文件、评分证据和 Regression Gate。

## 数据与验证

- [数据集说明](datasets.md)：版本化 Case、来源、路径类型和 RAG 状态。
- [验证指南](verification.md)：本地测试、静态检查和 tix 集成测试。
- [数据集 manifest](../datasets/servicedesk_v1/manifest.yaml)：机器可读的数据集来源和文件清单。

## 项目记录

- [实施任务记录](task.md)：已完成任务记录（T-001 至 T-013）。
- [架构决策记录](decisions.md)：已采用的长期决策。
