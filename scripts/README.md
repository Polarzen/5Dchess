# 脚本索引

[项目首页](../README.md) · [开发文档](../docs/development/SETUP.md)

玩家直接双击根目录的 `本地.bat` 或 `远程.bat`。以下脚本用于启动实现和开发维护，命令从项目根目录执行。

| 路径 | 用途 |
| --- | --- |
| `launch_windows.ps1` | Windows 一键入口：准备独立环境、阻止重复启动、记录错误 |
| `windows_bootstrap.ps1` | 下载校验、运行环境和依赖准备函数 |
| `start_p2p.ps1` | 管理网站和隧道进程、就绪检查、端口选择与退出清理 |
| `p2p_common.ps1` | Python / Cloudflare 查找、隧道重试及共享函数 |
| `run_p2p_server.py` | Web 服务入口与机器可读端口选择 |
| `setup_p2p.ps1` | 已安装 Python 的开发者使用的手动环境准备 |
| `p2p/` | Python 与 Cloudflare 固定版本、下载地址和 SHA-256 |
| `check_p2p.py` | 联机验收；`--exercise-room` 仅用于无真实玩家的测试服务 |
| `validate_rule_loops.py` / `validate_ai_tactics.py` | 规则循环与 AI 战术验证 |
| `validate_long_replay.py` | 困难 AI 续走、长局文件回放、逐步/跳转与 HTTP 续局一致性 |
| `training/` | 可选训练、自对弈、Arena、设备检查与续训 |
| `release/build_windows.py` | 从指定 Git 提交构建 ZIP 和校验和，不打包工作区临时数据 |

已有命令路径保持稳定。发布步骤见 [发布流程](../docs/development/RELEASING.md)，训练步骤见 [训练指南](../docs/development/LOCAL_AI_TRAINING.md)。

长局验证示例（建议单独运行，避免其他性能测试争用 CPU）：

```powershell
python scripts/validate_long_replay.py --source tests/fixtures/hard20_eight_required_rewind_state.json.gz --actions 12 --profile hybrid --output-dir .planner-work/long-replay
```

`hybrid` 使用既有 5 秒规划配置；`web` 使用界面困难 AI 的默认配置。不传 `--source` 则从标准初始局面开始。报告和存档仅写入指定输出目录，不启动网站或修改玩家的 `saves`。报告分别记录新增 AI 行动和已有棋谱，逐步重建参考局面并比对前进、后退、随机跳转、文件校验及 HTTP 续局；HTTP 时间通过本机 Flask 测试客户端测量，不代表异地网络延迟。
