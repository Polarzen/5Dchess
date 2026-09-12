# Web 稳定性

本文记录当前 Web 稳定性实现的请求、会话与错误处理边界。

## 请求与状态保护

- 普通请求和 AI 请求都使用 `AbortController` 与 Promise deadline 限制在 10 秒内完成；deadline 覆盖响应体读取与解析。
- P2P 状态轮询按 1200 毫秒周期运行；每次请求的单次 timeout 为 4 秒，并要读取、解析响应 body，再根据协议结果更新局面或连接状态。
- 请求结束时，无论成功、失败还是超时，都在 `finally` 中释放请求中标记，避免后续请求被永久挡住。
- 每个请求带有 owner 与会话 generation 保护，P2P 状态还检查 `state_version`；过期响应不能覆盖更新的局面。
- 返回菜单会立即撤销当前会话并停止相关 UI 工作；稍后完成的 leave 请求不能影响新游戏或新会话。
- AI 超时只做状态级重新同步，不立即再次调用 `ai_move`。客户端 timeout 只终止本地等待，不取消服务器已经开始的行动；手动同步只有在权威状态仍轮到 AI、`ai_thinking === false` 且没有进行中的 AI 请求时，才显示一次明确的安全重试入口。

## P2P 重试与终态

短暂网络错误使用有界退避重试，退避上限为 10 秒，并保留本地房间码和 `player_token`，以便在连接恢复后继续同一会话。终态协议错误 `invalid_token`、`room_expired`、`room_not_found` 会停止轮询、清理本地会话并返回重新加入流程；重试不会绕过这些终态。

页面显示给玩家的错误使用简体中文；机器协议码仍单独保留给分支判断和诊断，不能用显示文案替代协议码。`player_token` 不进入玩家文案或日志。

## AI 验收边界

Planner 生产预算固定为 5 秒、1024 个状态、24 个行动、最大深度 32。固定种子 53 的 Planner Regression 仍未解决，状态为 BLOCKED；Medium、Hard 和大规模 self-play 在该问题解决前继续阻塞。PR #24 必须保持 Draft，DO NOT MERGE。
