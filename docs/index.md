# ServiceDeskBench-Lite 文档

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

- [实施任务记录](task.md)：T-001 基础架构搭建、T-002 文档整理、T-003 HTTP 黑盒验收、T-004 审批生命周期修复、T-005 报告与基线固化、T-006 多数据集真实闭环验证、T-007 真实检索评测集成。
- [架构决策记录](decisions.md)：已采用的长期决策。
