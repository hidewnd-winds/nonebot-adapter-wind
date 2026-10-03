# 群资料与管理

群 API 提供平台能力的统一入口，但**不替调用方做业务授权**。调用前应按自身权限模型检查操作者、群范围和业务策略。平台返回的未知权限保持未知；不能将其推断成允许或拒绝。

## 查询

```python
from nonebot.adapters.wind import (
    GroupMessage, get_group_bot_state, get_group_info, get_group_member,
    get_group_members,
)

async def inspect(message: GroupMessage) -> None:
    info = await get_group_info(message)
    member = await get_group_member(message)  # 当前群、当前发送者
    members = await get_group_members(message)
    bot_state = await get_group_bot_state(message._bot, message.group.id)
```

`get_group_info(message, group_id=None)`、`get_group_members(message, group_id=None)` 默认使用当前群。`get_group_member(message, user_id=None, group_id=None, fresh=False)` 默认查询当前发送者；传 `Bot` 时必须明确传入 `group_id` 和 `user_id`。`fresh=True` 请求避开缓存（具体平台实现可能没有缓存）。`get_groups(message)` 查询当前 Bot 所在群列表。

`get_group_bot_state(bot, group_id)` 查询平台实际提供的 Bot 角色和权限。`get_group_mute_settings(bot, group_id)` 查询禁言设置；平台没有能力时会抛 `UnsupportedProtocolCapabilityError`。

## 写操作

| API | 关键行为 |
|---|---|
| `set_group_members_mute(bot, group_id, members)` | 每批 1–20 个不重复成员；禁言到期时间须在未来 30 天内。删除禁言使用对应的删除操作字段 |
| `remove_group_members(bot, group_id, user_ids, add_to_blacklist=False)` | 每批 1–20 个不重复成员；OneBot 的附带选项按平台语义拒绝再次入群 |
| `approve_group_join_request(bot, group_id, request, approve=..., reason=None, add_to_blacklist=False)` | 必须使用真实申请标识；同意时不能同时给拒绝理由或拉黑 |
| `set_group_blacklist(bot, group_id, user_ids, add=...)` | 每批操作平台群黑名单，返回平台明确报告失败的标识 |

写操作不自动重试，以免不确定结果造成重复变更。OneBot 批量操作部分成功时以 `GroupBatchOperationError` 携带已完成成员信息；不要整体重放。黑名单与应用自己的业务黑名单无关。

## 分页和申请处理

`get_group_join_requests(bot, group_id, cursor=None, limit=None)` 返回一页 `GroupJoinRequestPage`，`limit` 范围为 1–50；游标由调用方原样传回。`get_group_blacklist` 同样按游标分页。API 不建立数据库待审批队列。

入群辅助通过 `get_group_join_application(bot, event)` 提取事件中平台真实的 `flag` / `join_request_id`、群及用户标识；无关事件返回 `None`。`get_group_join_approver(bot)` 取得该 Bot 所属审批配额对象，`request_slot(bot)` 用于按平台配额串行化拒绝/审批动作。`reject(bot, application, reason=...)` 需要调用方明确传入拒绝理由（可为空）；业务黑名单判断和权限检查仍属于宿主。

QQ 群状态客户端通过 `get_qq_group_state_client(bot)` 获取实例拥有的限流客户端。不得在多个入口各建客户端来绕过同 Bot 的请求配额。若使用旧 `register_qq_extensions()`，该函数当前仅为迁移兼容保留，已弃用且无副作用。

QQ 群状态 API 对平台响应错误进行分类并做受限重试；它不会将一般写操作自动重试。错误分类和权限项参见[故障排查](troubleshooting.md)。

入群辅助器保留原实现的范围：OneBot 仅提取 `sub_type="add"` 的主动入群申请，`invite` 返回 `None`。若业务要处理邀请事件，应直接构造 `GroupJoinRequest(request_id=event.flag, user_id=str(event.user_id), sub_type=event.sub_type)` 并调用统一审批 API；不得丢掉真实子类型。该 API 支持 `add`/`invite`，辅助器不会假装把两者都转换成主动申请。
