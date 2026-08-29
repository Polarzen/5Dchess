# P2P 真人对弈（Cloudflare Tunnel）

当前 Web 版真人对弈采用“房主本机作为权威游戏服务器 + 双方浏览器作为客户端”的方式。
这不是把规则引擎搬到第三方服务器：完整 5D 规则、Action、The Present 和终局判断仍由房主机器上的 Flask/Engine 执行。

## 为什么选 Cloudflare Tunnel，而不是 GitHub Pages

项目的 Web UI 依赖 Python/Flask 后端保存棋局和执行 5D 规则。GitHub Pages 只能部署静态站点，不能直接运行 Python 服务端代码，因此不能单独承载当前游戏服务器。

Cloudflare Quick Tunnel 可以直接把房主的 `http://127.0.0.1:5000` 临时发布成 `https://*.trycloudflare.com`，不需要公网 IP，也不需要先配置域名，最适合目前的两人联机方式。

> Quick Tunnel 适合开发、试玩和临时联机。需要长期固定地址时，应改用 Cloudflare Named Tunnel。

## Windows 最简启动

1. 安装项目依赖：

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. 安装 `cloudflared`，并确保命令 `cloudflared --version` 可运行；也可以把 `cloudflared.exe` 直接放在项目根目录。

3. 在项目根目录运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\start_p2p.ps1
   ```

4. 等终端打印类似：

   ```text
   https://random-words.trycloudflare.com
   ```

5. 房主和对手都打开这个 HTTPS 地址。

6. 房主点击 **创建真人房间**，页面会显示 6 位 `Room` 房间码。点击顶部的 `Room XXXXXXX` 可以复制房间码。

7. 对手点击 **加入真人房间**，输入房间码。房主固定执白，对手固定执黑。

8. 关闭 PowerShell 中的 `cloudflared` 后，临时公网地址失效，本地 Flask 服务也会由脚本一起停止。

## 手工启动

如果不使用脚本，可以开两个 PowerShell 窗口：

```powershell
python src/main.py --web
```

以及：

```powershell
cloudflared tunnel --url http://127.0.0.1:5000
```

## 联机协议与安全边界

- 当前主机一次只开放一个在线房间，符合项目现有 single-session Flask 架构。
- 房间码用于找到棋局；真正的走子权限由每位玩家独立的随机 `player_token` 控制。
- 白方只能在白方 Action 行动，黑方只能在黑方 Action 行动。
- 第二位玩家加入后房间即满，第三位玩家无法占用棋手席位。
- 在线房间存在时，旧的未鉴权 `/api/game/*` 与 `/api/replay/*` 接口会被拒绝，避免绕过 P2P 权限修改局面。
- 浏览器会在本地保存当前房间的玩家令牌；刷新后再次输入同一房间码会恢复原白/黑身份。
- 房主返回菜单会关闭房间；黑方返回菜单只会离开席位，房主可以等待另一位黑方重新加入。

## 同步方式

双方共享房主机器上的同一个 `FiveDEngine`。客户端约每 1.2 秒轮询一次房间状态。所有 Move 和 Submit Action 都先在服务器验证当前玩家身份、回合和合法性，再写入引擎，因此客户端不能自行伪造棋局状态。
