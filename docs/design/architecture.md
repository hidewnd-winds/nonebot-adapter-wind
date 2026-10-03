# 架构与生命周期

```text
NoneBot Driver
  ├─ Wind QQ Adapter ─ 官方 QQ Adapter 传输/认证
  └─ Wind OneBot Adapter ─ 官方 OneBot V11 传输/认证
             │
             ├─ 平台事件 → UnifiedMessage / GroupMessage / PrivateMessage
             ├─ Document / RichContent → 平台原生发送与 MessageReceipt
             └─ 群资料、成员、审批及平台专有 QQ 交互 API
```

官方 Adapter 仍拥有协议连接和原生 Bot 能力；Wind Adapter 扩展事件识别、实例生命周期和统一 API。统一消息只覆盖源码中支持的平台消息事件，不表示原生 Adapter 的每类事件都能转换。

导入模型、Document 或 API 不应连接网络、访问数据库或创建全局预处理器。由适配器注册阶段建立配置相关行为；实例持有限流、图片发布和任务状态，并在关闭时释放自己创建的资源。关闭期间完成的 Webhook 预初始化不得重新注册 Bot，关闭后的新回调须明确拒绝。QQ 自定义交互模型只在 Wind QQ 的解析路径处理，不能修改上游 SDK 全局事件注册表。

命令视图的预处理配置需同时影响事件预处理和消息模型构造。禁用后不能在 `create_message` 阶段再次处理原始事件。QQ Webhook Bot 提前初始化默认开启；必须在认证成功后注册 Bot，失败可继续正常 Webhook 建连。

统一 API 不决定宿主业务是否允许某人管理群。写操作不自动重试；平台未知权限不被填成肯定值。消息归档、统计、固定面板内容属于宿主集成。
