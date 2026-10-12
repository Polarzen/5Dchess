# P2P 真人对弈（Cloudflare Quick Tunnel）

本项目的在线 P2P 模式把房主的 Web 服务通过 Cloudflare Quick Tunnel 临时发布到公网。房主服务端运行完整的 5D 引擎并权威维护对局状态；Cloudflare 只负责转发 HTTPS 流量，不承载棋局规则。

## 为什么使用 Cloudflare Quick Tunnel

Quick Tunnel 可以把房主的本地 Web 地址临时发布为 `https://*.trycloudflare.com`，不需要公网 IP 或预先配置域名，适合开发、试玩和临时联机。需要长期固定地址时，应改用 Cloudflare Named Tunnel，并按照部署环境补充访问控制。

本项目默认监听 `0.0.0.0`（所有 IPv4 网卡），默认关闭 Flask 调试模式，首选端口为 `5050`。普通 Web 启动会在
`5050-5099` 中逐个进行 TCP bind 探测并选择第一个可用端口；`--port N` 表示
首选起点，仍会从 `N` 向上最多搜索 50 个候选（范围在 `65535` 处截断），不是
严格绑定要求。实际选中的 URL 会在 Flask 启动前记录；如果 50 个候选都不可用，
启动会报告包含完整搜索范围的错误。

同一局域网的玩家可以直接访问 `http://<房主的局域网IP>:<实际端口>`，
在页面创建或加入在线房间，无需启动 Cloudflare。房主本机和 Cloudflare 转发目标仍使用
`http://127.0.0.1:<实际端口>`；`0.0.0.0` 只用于监听。

## Windows 安装与启动

只有房主需要项目、Python 和 `cloudflared`；加入者使用浏览器即可，无需下载软件。同一局域网联机不需要 Cloudflare。

### 首次安装（房主）

在项目根目录打开 PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_p2p.ps1
```

安装位置：

| 内容 | 位置 |
| --- | --- |
| Cloudflare 软件 | `D:\p2p\cloudflared\cloudflared.exe` |
| 项目 Python 依赖 | 项目内 `.venv311` |
| 安装、启动、检查脚本 | 项目内 `scripts/` |
| 官方版本及 SHA-256 清单 | `scripts/p2p/cloudflared-release.json` |
| 运行日志 | 项目内 `logs/p2p/`（Git 忽略） |

安装脚本下载清单中固定版本的官方 Windows amd64 程序，校验 SHA-256 后才安装；相同版本重复执行会复用。替换已有不同版本时会先保存备份。它不修改系统 PATH、不注册开机服务。Python 3.11 已安装时直接复用；尚未安装时，可先将 Python 3.11 安装到 `D:\p2p\Python311`，再运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_p2p.ps1 -PythonPath 'D:\p2p\Python311\python.exe'
```

可用 `-SoftwareDirectory` 指定其他软件目录；后续启动需要用 `-CloudflaredPath` 指向其中的程序。常规启动优先使用项目 `.venv311`，然后 `.venv`；Cloudflare 优先查找 `D:\p2p\cloudflared`，再查项目根目录和 PATH。显式指定的路径不存在时直接报错，不会偷偷换用别的程序。

### 异地联机

```powershell
# 只检查环境，不启动服务或隧道
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_p2p.ps1 -Check
# 启动网站和公网隧道
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_p2p.ps1
```

1. 等待终端显示 `公网地址：https://*.trycloudflare.com`。启动器确认 Cloudflare 已建立连接后才显示该地址。
2. **房主也从这个 HTTPS 地址打开游戏**，点击“创建在线房间”。
3. 点击顶部“复制邀请链接”，发送给对手，例如 `https://example.trycloudflare.com/?room=ABC123`。
4. 对手打开链接，点击“加入在线房间 ABC123”。房主固定执白，对手执黑。
5. 联机期间保持房主电脑、启动终端和双方页面运行。结束时在启动终端按 **Ctrl+C**；网站与隧道都会关闭，临时网址失效。不要靠强制结束 PowerShell 或直接关闭终端来代替正常停止。

房间码是自动生成的 6 位字母或数字，只在该房主的网站服务中有效。手动加入时仍需先打开相同网址；房间码不能让另一个独立启动的网站自动找到房主。房间关闭、过期或服务重启后，应创建新房间并重新分享邀请。邀请链接只含房间码，不含玩家身份令牌。

### 同一局域网

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_p2p.ps1 -LanOnly
```

脚本显示本机地址和局域网候选地址。双方使用房主实际连接网络的 IPv4 地址，例如 `http://192.168.1.20:5050`。房主也从这个地址创建房间，复制的邀请链接才能供同网设备访问。`127.0.0.1` 仅供房主本机使用；不要在浏览器中填写监听地址 `0.0.0.0`。如果同网设备连不上，检查两台设备是否处于允许互访的同一网络，以及 Windows 防火墙是否允许该 Python 在专用网络接收入站连接。

### 端口、就绪和停止

```powershell
# 从 5099 向上搜索最多 50 个空闲候选，隧道跟随实际选中的端口
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_p2p.ps1 -Port 5099
# 网络不支持 UDP/QUIC 时使用 HTTP/2 隧道
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_p2p.ps1 -TunnelProtocol http2
```

启动器先通过 `run_p2p_server.py --select-port` 取得具体端口，再严格传给网站和 Tunnel，避免二者指向不同端口。启动前的端口探测不构成预留；最终绑定发生竞争会报错，需要重新启动。

网站使用 `debug=False`，不会启动开发调试器或重载进程。启动器用一次性的 launch identity 和实际服务 PID 确认就绪，兼容 Windows 虚拟环境解释器的子进程；identity 只经环境传递，不写入 URL。网站就绪最多等 30 秒，每次隧道启动最多等 90 秒。

申请临时网址遇到超时、网络中断或接口 429/5xx，且尚未取得网址时，启动器默认最多尝试 3 次（首次失败后等 2 秒，再次失败后等 4 秒），期间本地网站继续运行。可通过 `-TunnelAttempts 1` 关闭重试，或设置为 1–5 次。每次尝试分别写入 `logs/p2p/*-tunnel-attempt-N-error.log`，保留之前的错误。配置、证书等错误不自动重试；已经取得网址或成功连接后的退出也不自动重建，以免更换邀请链接。达到重试上限、服务退出、启动超时或按 Ctrl+C 时会清理本次启动的进程。

### 手动启动

在两个终端分别运行，并分别按 Ctrl+C 停止：

```powershell
.\.venv311\Scripts\python.exe scripts/run_p2p_server.py
# 把网站日志中的实际端口填入下一条命令
& 'D:\p2p\cloudflared\cloudflared.exe' tunnel --url http://127.0.0.1:<actual-port>
```

直接运行 `run_p2p_server.py` 会自动寻找端口；给它传入 `--port N` 则严格绑定 N。该 Python 参数与 PowerShell 启动器的 `-Port N`（搜索起点）含义不同。

### 联机验收

在刚启动、没有玩家对局的测试网站上执行：

```powershell
.\.venv311\Scripts\python.exe -X utf8 scripts/check_p2p.py --url https://example.trycloudflare.com --exercise-room
```

该命令明确创建临时房间，模拟两个独立玩家，验证房间满员、非法身份、回合权限、双方走子和提交、同色重连及棋盘同步，最后关闭测试房间。令牌只在内存中使用，不打印或保存。已有房间时创建会失败，不会接管玩家的对局。可将 `--url` 换为本机或局域网地址验证相应路径。

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

### 启动提示 Cloudflare Tunnel 已退出

先看终端给出的原因与日志。若出现以下错误，表示向 Cloudflare **申请网址** 的 HTTPS 请求超时，此时本地 Flask 通常已正常启动：

```text
failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel": context deadline exceeded
failed to read quick-tunnel response: context deadline exceeded (Client.Timeout or context cancellation while reading body)
```

新版启动器会自动做上述有限次数重试，命令不变，无需重新安装。若每次都失败，可稍后重试或换一个可访问该接口的网络（例如手机热点）。自动重试能处理短暂波动，不能保证修复持续不可达的外部服务。

第一种是等待申请请求响应超时，第二种是读取响应内容超时；两者都发生在申请网址阶段，都会重试。若已经出现临时网址，但随后反复出现 `Failed to dial a quic connection`，则是隧道连接阶段的问题。自检中的 `UDP Connectivity FAIL`、`TCP Connectivity FAIL` 表示对应检测未连通，并不能单独确定是本机防火墙、网络出口还是上游链路造成。可先换手机热点对照；只有 UDP 不通时可以尝试 HTTP/2，但 TCP 也不通时仍可能失败。Cloudflare 隧道使用出站 7844 端口，QUIC 使用 UDP，HTTP/2 使用 TCP，详见[官方网络要求](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/)。

在 PowerShell 7 窗口里执行 `powershell ...` 仍会启动 Windows PowerShell 5.1；要使用当前 PowerShell 7，可直接执行 `& .\scripts\start_p2p.ps1`（受当前执行策略约束），或将命令开头换成 `pwsh`。启动器支持两者；切换 PowerShell 版本不会修复网络连接问题。

`-TunnelProtocol http2` 用于已取得网址后连接 Cloudflare 隧道的阶段，不能延长或改变申请网址这一步。所固定的 cloudflared 2026.10.0 在[官方实现](https://github.com/cloudflare/cloudflared/blob/2026.10.0/cmd/cloudflared/tunnel/quick_tunnel.go)中把申请请求超时设为 15 秒；启动器的 90 秒等待上限不会覆盖它。

局域网玩家仍可使用 `-LanOnly`；异地玩家需要公网入口恢复后才能加入，局域网模式不能替代异地连接。

### 点棋子后落点显示很慢

选子会请求房主计算合法走法，公网链路慢时会直接影响落点出现的时间；这不是每 1.2 秒状态轮询的等待时间。客户端会在轮到自己时，后台预取一张可行动棋盘的合法走法；该请求完成后，同一棋盘上的选子复用缓存，无需再次等待公网往返。其他棋盘按所点棋子请求，重复点选也可复用结果。走子、回合、在线状态版本或房间会话改变后，旧缓存失效；实际落子始终经房主服务端校验。若预取尚未完成，第一次点选仍可能等待。

状态版本相同的心跳不会重绘所有棋盘。服务端的单棋子查询只生成该棋子的走法，不再先生成其他棋子的走法。前端资源更新后双方可强制刷新页面；后端更新应等当前对局结束再重启，避免丢失内存中的房间。

如果连主页或创建房间也很慢，先检查实际公网路径。可在本局结束后用 `-TunnelProtocol http2` 与默认 `auto` 对照，但切换协议不保证更快，也不会自动选择更近的节点。重启会产生新公网链接，需要重新邀请。排查时不要在正在玩的服务上运行 `check_p2p.py --exercise-room`。

- 找不到项目 Python 或缺少依赖：执行 `scripts/setup_p2p.ps1`；新安装的 Python 可通过 `-PythonPath` 指定。
- 找不到 `cloudflared`：执行 `scripts/setup_p2p.ps1`，默认安装到 `D:\p2p\cloudflared`；自定义位置使用 `-CloudflaredPath`。
- 创建房间提示已有在线房间：由原房主显式返回菜单关闭旧房间，或等待失联房间的 lease+grace 生命周期结束。
- 邀请链接没有显示目标房间：确认 `?room=` 后是恰好 6 位 ASCII 字母或数字；非法参数会被安全忽略并回到手动输入流程。
- 页面提示连接中断：确认房主进程和 Quick Tunnel 仍在运行，并重新打开同一 HTTPS 地址；浏览器中的房间码和令牌会用于同色恢复。

官方参考：[Quick Tunnel 使用说明](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)、[cloudflared 下载](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/)。

本次实际运行结果及验证范围见 [P2P 验收记录](P2P_ACCEPTANCE.md)。
