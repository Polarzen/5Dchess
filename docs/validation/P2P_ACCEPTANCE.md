# P2P 安装与联机验收

验证日期：2026-10-12（Asia/Hong_Kong）。环境：Windows、Python 3.11.9、Windows PowerShell 5.1 / PowerShell 7、cloudflared 2026.10.0。

## 安装和启动

- 官方 Windows amd64 程序安装在 `<TOOLS_ROOT>/cloudflared/cloudflared.exe`，SHA-256 与 `scripts/p2p/cloudflared-release.json` 一致。`<TOOLS_ROOT>` 为此次验证使用的外部工具目录；2026-10-13 已将原本机路径脱敏，安装和测试结果不变。当前版本的默认安装位置请参见 [联机指南](../guides/P2P_CLOUDFLARE.md)。
- 依赖位于项目 `.venv311`；启动器实际使用此环境，未使用系统默认 Python 3.14。
- 重复执行安装脚本复用已校验的软件，不重复下载；`-Check` 成功且不启动服务。
- 真实启动验证覆盖 Windows 虚拟环境的解释器子进程，就绪校验通过。

## 公网路径

使用 `scripts/start_p2p.ps1` 建立真实 Cloudflare Quick Tunnel（QUIC），通过生成的 HTTPS 公网地址执行：

```powershell
.\.venv311\Scripts\python.exe -X utf8 scripts/check_p2p.py --url <本次公网地址> --exercise-room
```

结果通过：主页、创建房间、加入房间、满员拒绝、无效令牌拒绝、回合权限、白黑双方各一次走子和行动提交、原身份重连、双方棋盘一致。测试房间已关闭；在启动终端按 Ctrl+C 后，网站和 cloudflared 进程均退出，监听端口释放。

这次公网验收使用同一台验证机上的两个独立玩家身份，经实际 Cloudflare 公网域名访问房主服务；尚未用两台处于不同运营商网络的实体设备对弈。

## 局域网与端口冲突

用测试监听器占用 `5050`，启动 `start_p2p.ps1 -LanOnly -Port 5050`。网站自动选择 `5051`；通过房主实际网卡 IP 的 HTTP 地址执行同一双玩家验收，结果通过。停止网站服务进程后，启动器检测退出并完成清理，`5051` 释放。此次局域网验收也从房主验证机访问其实际网卡地址，未覆盖其他设备的防火墙或无线网络隔离配置。

## 自动回归

```powershell
.\.venv311\Scripts\python.exe -X utf8 -m pytest -q tests/test_p2p_startup_scripts.py tests/test_web_port_selection.py tests/test_p2p_web.py tests/test_p2p_invite_web.py tests/test_hotseat_online_modes.py
node tests/test_browser_reliability.js
node tests/test_p2p_invite.js
node tests/test_tutorial_browser.js
```

49 项 Python 测试通过，三组 JavaScript 回归通过。Python 编译、PowerShell 脚本解析和 `git diff --check` 通过。安装软件、虚拟环境、临时公网地址、玩家令牌、运行日志均未加入 Git。
