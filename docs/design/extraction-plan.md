# 独立工程提取计划与实施状态

基线：wind-bot `fdc0180cecd662160f010903e15964a4c9d0eb5d` 的 `src/adapter/protocol/`；目标目录 `/Users/hidewnd/workspaces/projects/nonebot-adapter-wind`；首版 `0.1.0`。本文件记录已实施内容和剩余发布验收，不能将本地离线通过等同于平台联调或已发布。

## 目标与原则

建立可独立安装的 QQ / OneBot V11 扩展包，保留源模块职责及公共接口，不迁移 wind-bot 应用，也不修改其接入。使用 `nonebot.adapters.wind` 命名空间，保留两个真实 Adapter；官方 SDK 继续拥有传输、鉴权、原生事件和 Bot API，不新建虚拟统一 Adapter。

按“复制实现 → 最小解耦 → 对照验证 → 发布准备”实施。原十个模块全部保留；新增 `config.py`、`log.py`、`media.py`、`storage/cos.py` 和 `py.typed` 只处理独立运行所需能力。没有提供旧 `src.adapter.protocol` 兼容包。

## 功能保留基线

| 能力 | 实施结果与证据 |
|---|---|
| 公共接口 | 103 个根导出保留并自动逐项检查；子模块接口见[兼容记录](compatibility.md) |
| 模型和 Document | 原字段、节点、默认值、异常、按钮结构和 Markdown/纯文本渲染保留 |
| 入站上下文 | 群/私聊、原始文本、真实 at/all、图片顺序、引用索引、内联引用、克隆身份均保留 |
| 发送 | 字符串/Document/ImageContent/RichContent/OrderedContent、尾注、单消息检查、回执、finish、响应上下文保留 |
| OneBot | 群多项内容合并转发、私聊逐条、主动合并、引用段和旧连接所有权检查保留 |
| QQ | Markdown/键盘/媒体、回复过期降级、msg_seq、交互确认/回复、两类撤回语义保留 |
| 群能力 | 资料/成员/状态、禁言、分页申请、审批、成员移除、黑名单和部分失败结果保留 |
| 入群辅助 | 真实申请身份、审批配额、协议匹配保留；业务拒绝理由显式参数化 |
| 面板 | 模型、查询/创建/更新保留；不自动创建业务菜单 |
| 图片 | 公网 URL、图片尺寸/下载限制、自定义发布器、可选 COS 内容去重和成功缓存；失败继续暴露 |

`__init__.py`、`base.py`、`document.py`、`models.py`、`qq_panel.py` 已和源文件逐字节比对一致。其他模块只做宿主解耦、实例生命周期和配置接入；删除宿主统计预处理器、替换进程单例等差异均在兼容文档中列明。

## 实施阶段

1. **基线盘点完成**：记录源版本、十个模块、根导出清单和子模块接口；`tests/expected_exports.json` 可机器核对。
2. **复制及解耦完成**：日志进入 NoneBot；不导入数据库、归档、统计和业务名单。通过发送返回值、回执观察及显式 Matcher 钩子提供接入示例。
3. **初始化整理完成**：模型/API 导入无联网或预处理器注册；Wind Adapter 初始化幂等注册专属预处理；相同配置同时约束事件处理和统一转换。QQ 局部扩展交互解析，未修改官方全局事件表。
4. **生命周期完成**：QQ Webhook 预初始化默认开启，认证成功后注册，失败保留正常回调恢复路径；并发初始化/首次回调使用相同锁。关闭后不接受迟到注册，清理实例状态。OneBot 旧连接退出不清理替换后的新连接。
5. **文档和示例完成**：`docs/` 覆盖接入、配置、Document、消息、群管理、QQ 交互、图片、能力矩阵、排错和设计；`examples/` 包含单/双协议入口、真实图片渲染、群管理、面板、发布器、COS、回执和统计。
6. **本地分发准备完成**：固定 QQ 1.7.3 / OneBot 2.4.6，NoneBot 2.5.x；使用 uv/uv_build、MIT、py.typed、wheel/sdist、离线测试与 CI 矩阵。

## 验证记录（2026-10-04）

- [x] 197 项隔离测试通过。真实 SDK 事件/返回模型配合网络边界替身；没有访问真实平台、数据库或 COS。
- [x] Ruff 正确性规则通过；Pyright 对运行时包及示例检查为 0 errors / 0 warnings。
- [x] 文档相对链接、QQ 配置 JSON 对固定 SDK 的校验、示例语法和宿主依赖检查通过。
- [x] 13 个示例模块可导入；Document 本地渲染可运行；三种启动入口在替换 `nonebot.run` 后完成注册/插件装配检查，没有启动服务器。
- [x] 回执 JSONL 保存与显式 Matcher 钩子注册完成离线检查。
- [x] wheel/sdist 构建成功，`twine check --strict` 通过。
- [x] 源码目录之外的基础虚拟环境安装 wheel，103 导出和两个上游 SDK 共存，未安装 COS 仍可使用；导入不初始化 Driver/预处理器。
- [x] 保留原 wind-bot 工作区，无原项目接入改动。
- [ ] Python 3.10 / 3.14 实际执行：已配置 CI 矩阵，本次本地为 macOS arm64 / Python 3.12.14。
- [ ] 真实 QQ Webhook、QQ WebSocket、OneBot 连接和 COS 上传联调。
- [ ] TestPyPI 测试发布、正式 PyPI 发布和 NoneBot 商店提交。

已知的 3 个测试告警来自固定 QQ SDK 的 Pydantic `.dict()` 弃用调用；不影响本次通过结果，未修改 SDK。测试总数不是每一种平台组合均完成实测的声明。

## 明确边界与发布前事项

- Wind `register(driver)` 在同名协议已注册时抛错；直接调用 NoneBot 的注册方法仍可能被上游静默忽略。不修改框架全局行为。
- OneBot 入群辅助器延续只提取 `add` 的行为；需要 `invite` 时调用方直接通过 `GroupJoinRequest.sub_type` 使用统一审批接口，不能伪装成 `add`。
- `single_message` 约束单个 RichContent，不对整个内容序列提供事务。QQ 字节图文要求严格单消息时需要可用的图片发布路径。
- 安装采用 wheel 或 `uv sync --no-editable`；editable 模式无法可靠合并到已安装的 NoneBot 命名空间，已在接入文档说明。
- 最终发布前仍需确认仓库 URL、作者/维护者信息及发布账号。本轮未将占位仓库或个人身份写入发行元数据。
- PyPI 包名查询不保留名称，也不代表发布权限；执行发布时重新核对。Git 提交需按用户规则单独确认，本轮不提交。

推荐的最终发布流程：目标平台联调并记录 → 在 CI 执行 3.10/3.12/3.14 → 确认作者/仓库信息 → 更新发行元数据并重新构建/检查 → 经明确发布授权完成 TestPyPI 安装验证 → 正式 PyPI 与 NoneBot 商店提交。
