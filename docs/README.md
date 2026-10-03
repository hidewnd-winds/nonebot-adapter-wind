# 文档导航

按以下顺序接入：先阅读[安装与接入](integration.md)，再选择[配置](configuration.md)和所需能力指南。首次使用统一格式消息时，建议完整阅读[Document](document.md)与[消息 API](messaging.md)。

| 文档 | 内容 |
|---|---|
| [安装与接入](integration.md) | 安装、Driver、适配器注册、插件注入和生命周期 |
| [配置](configuration.md) | Wind 配置开关、QQ 初始化和可选 COS |
| [统一 Document](document.md) | 所有节点、按钮、渲染、限制和示例 |
| [消息 API](messaging.md) | 入站上下文、发送、回执、引用、主动消息 |
| [群管理](group-management.md) | 群资料、权限、禁言、审批、黑名单 |
| [QQ 交互与面板](qq-interactions.md) | 交互回调、确认、回复、撤回和面板 API |
| [媒体与存储](media-storage.md) | 图片内容、图片发布器、COS |
| [协议能力矩阵](capabilities.md) | 统一 API 与平台支持边界 |
| [示例](examples.md) | 示例索引、运行方法和预期行为 |
| [故障排查](troubleshooting.md) | 注册冲突、配置和平台限制 |

设计与来源记录：[`design/architecture.md`](design/architecture.md)、[`design/compatibility.md`](design/compatibility.md)、[`design/extraction-plan.md`](design/extraction-plan.md)。

所有平台操作由调用方明确触发。导入包或示例不会自动连接、发送消息、修改群成员或创建面板。
