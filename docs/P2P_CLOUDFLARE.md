# P2P 真人对弈（Cloudflare Quick Tunnel）

本项目的在线 P2P 模式把房主的 Web 服务通过 Cloudflare Quick Tunnel 临时发布到公网。房主服务端运行完整的 5D 引擎并权威维护对局状态；Cloudflare 只负责转发 HTTPS 流量，不承载棋局规则。

## 为什么使用 Cloudflare Quick Tunnel

Quick Tunnel 可以把房主的 `http://127.0.0.1:5000` 临时发布为 `https://*.trycloudflare.com`，不需要公网 IP 或预先配置域名，适合开发、试玩和临时联机。需要长期固定地址时，应改用 Cloudflare Named Tunnel，并按照部署环境补充访问控制。

## Windows 启动

1. 安装项目依赖：

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. 安装 `cloudflared`，并确认 `cloudflared --version` 可以运行。也可以把 Cloudflare 官方 Windows 64-bit `cloudflared.exe` 放在项目根目录；启动脚本会优先使用 PATH 中的命令，否则查找根目录中的该文件。

3. 在项目根目录运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\start_p2p.ps1
   ```

   脚本会以 `debug=False` 启动 `scripts/run_p2p_server.py`，再创建 Quick Tunnel。终端出现 `https://*.trycloudflare.com` 地址后，房主先打开该地址并创建在线房间。

4. 房主点击“创建在线房间”后，顶部会出现“复制邀请链接”。点击后得到类似：

   ```text
   https://example.trycloudflare.com/?room=ABC123
   ```

   把这一条邀请链接发给对手即可，不再需要另外发送 6 位房间码。邀请 URL **只包含 room code**，绝不包含 `player_token`。

5. 加入者打开邀请链接后，主页会识别合法的 `room` 参数并显示“加入在线房间 ABC123”。只有加入者明确点击该按钮后才会请求 Black 席位；页面加载本身不会为没有已保存 token 的浏览器自动占用席位。没有邀请参数时，原来的手动输入 6 位房间码流程仍然可用。`White = host`（房主），`Black = joiner`（加入者）。

6. 结束联机时，先由玩家在页面返回菜单；关闭运行 Quick Tunnel 的 PowerShell 后，临时地址失效，启动脚本也会停止本地 Flask 服务。

### 手动启动

不使用启动脚本时，在两个 PowerShell 窗口中分别运行：

```powershell
python scripts/run_p2p_server.py
```

```powershell
cloudflared tunnel --url http://127.0.0.1:5000
```

手动启动时也应保持 Flask 的非调试模式，不要把开发调试器发布到公网。

## 邀请链接与认证边界

安全邀请格式固定为：

```text
<当前 origin>/?room=<6 位房间码>
```

例如：

```text
https://example.trycloudflare.com/?room=ABC123
```

- `room` 参数会去除首尾空白并统一为大写，只接受 6 位 ASCII 字母或数字；空值、长度错误、特殊字符和 HTML/script payload 都会被忽略并降级为普通手动加入流程。
- 页面只使用 `textContent` 显示从 URL 得到的房间码，不把不可信参数拼接进 HTML。
- 房间码只负责定位房间，**不是认证凭据**。它不能绕过房间已满、颜色、回合或 token 校验。
- `player_token` 从不进入 query string、hash、pathname、邀请链接、页面文本、toast 或剪贴板邀请 URL；它继续只保存在现有 P2P `localStorage` 会话中并作为 bearer 身份凭证发送给 `/api/p2p/*`。
- 如果浏览器已经保存了与邀请房间相同的 token，刷新页面时仍可按现有 reconnect 逻辑恢复原颜色；没有 token 的新浏览器打开邀请链接时，必须显式点击加入。
- 从带 `?room=...` 的邀请页返回菜单时，该 query 可以继续保留，方便再次点击加入；它不会影响 Local Hotseat PvP，因为 Hotseat 不读取 room 参数，也不使用 P2P token、polling 或 `opponent_connected` 权限。

## 房间与连接生命周期

- 一个服务进程只允许一个在线房间和一个房间码。
- 房间码用于定位房间；每位玩家另有随机 bearer `player_token`。令牌保存在该玩家浏览器的 `localStorage`，因此刷新或短暂断线后，客户端会自动提交同一房间码和令牌，在 reconnect grace 内恢复原来的颜色。
- 房主创建房间后固定为 White；第一位加入者固定为 Black。没有第二位玩家时不能开始走子。
- 客户端每 1.2 秒轮询 `/api/p2p/state`；该轮询同时作为连接 heartbeat。轮询请求不会并发重叠，瞬时失败会沿用后续轮询周期重试；终态的认证 / 房间错误会停止轮询并清理本地会话。
- player lease 超时为 8 秒。状态接口和界面区分 `not_connected`（等待第二位玩家）与 `offline`（已有席位但暂时离线 / reconnecting）；座位暂时离线后，仍保留 30 秒 reconnect grace。观察到连接状态变化时，房间 `state_version` 会递增。
- lease 加 grace 都耗尽后，Black 座位释放，可以由新的加入者占用；stale host cleanup 会使失联房主的旧房间过期，不再阻塞创建新房间。
- White 显式返回菜单会关闭整个房间；Black 显式返回菜单会立即释放 Black 座位。
- 对手离线时，不能走子、提交 Action 或进行其他局面 mutation；重新连接并恢复在线状态后才能继续。

## 安全边界与错误处理

- `/api/p2p/create` 创建请求和不带令牌的初次 `/api/p2p/join` 加入请求是认证例外：前者不需要房间码 / token，后者只需要房间码；带 token 的 `/api/p2p/join` 则是恢复已有席位。认证后的 `/api/p2p/state`、游戏请求（`/api/p2p/legal_moves`、`/api/p2p/move`、`/api/p2p/submit`）和 `/api/p2p/leave` 都必须同时携带正确的房间码与玩家令牌。房间码不是玩家身份凭据；不要把 bearer 令牌分享给他人。
- 服务端验证玩家颜色、当前回合和完整 5D 合法性；在线房间存在时，旧的未鉴权 `/api/game/*` 与 `/api/replay/*` mutation 接口会被拒绝。
- 常见的房间、认证、回合和状态错误以 JSON 4xx 响应返回，便于页面显示可读错误。
- `player_token` 不写入服务端日志，也不会被邀请链接生成逻辑读取或复制。Quick Tunnel 地址和房间码仍应只发给预期对手；临时联机结束后关闭 Tunnel。
- Quick Tunnel 是临时公网入口，不等同于完整账号系统或长期生产部署。需要长期运行时，请使用 Named Tunnel、访问策略和适合部署环境的日志/密钥管理。

## 常见检查

- 找不到 `python`：安装 Python 3.11+ 并确保它在 PATH 中。
- 找不到 `cloudflared`：将其加入 PATH，或把 `cloudflared.exe` 放到项目根目录后重新执行启动命令。
- 创建房间提示已有在线房间：由原房主显式返回菜单关闭旧房间，或等待失联房间的 lease+grace 生命周期结束。
- 邀请链接没有显示目标房间：确认 `?room=` 后是恰好 6 位 ASCII 字母或数字；非法参数会被安全忽略并回到手动输入流程。
- 页面提示连接中断：确认房主进程和 Quick Tunnel 仍在运行，并重新打开同一 HTTPS 地址；浏览器中的房间码和令牌会用于同色恢复。
