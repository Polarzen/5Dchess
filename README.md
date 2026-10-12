# ♟️ 时线棋局

在多个时间与平行时间线之间走棋的国际象棋游戏。浏览器界面支持人机对弈、同屏双人、局域网及异地联机，并提供互动教程和棋谱回放。

**[下载 Windows 一键启动 ZIP](https://github.com/Polarzen/5Dchess/releases/latest/download/5DChess-Windows.zip)** · [所有版本](https://github.com/Polarzen/5Dchess/releases) · [使用说明](使用说明.txt) · [文档目录](docs/README.md)

## 下载与启动

1. 下载上面的 **5DChess-Windows.zip**，右键选择“全部解压”。
2. 打开解压后的 `5DChess` 文件夹，双击 **本地.bat** 或 **远程.bat**。
3. 首次等待组件和依赖自动准备完成，浏览器会自动打开。

| 启动入口 | 适用场景 | 对方需要什么 |
| --- | --- | --- |
| **本地.bat** | 自己游玩、同屏双人、同一局域网 | 局域网联机时用浏览器打开房主的局域网网址 |
| **远程.bat** | 不同网络之间联机 | 浏览器打开房主发来的邀请链接 |

支持 **Windows 10/11 x64**，首次启动需要联网，无需预装 Python、Git 或数据库。只有房主需要运行项目。结束时在启动窗口按 **Ctrl+C**，等待服务停止后再关窗口。

启动器会检查文件、校验下载、拦截重复启动，并在端口占用时选择空闲端口。不要在 ZIP 内直接运行，也不要单独移动两个启动文件。完整步骤及故障处理见 [使用说明.txt](使用说明.txt)。其他平台可按 [开发环境](docs/development/SETUP.md) 手动运行源码。

## 第一次玩

进入主页后选择“第一次玩？从这里开始”。教程会演示普通走子、跨时间线移动、返回历史生成分支，以及“提交行动”如何结束回合。

- **自己练习**：选择人机对弈；同一台电脑两人轮流玩时选择同屏双人。
- **联机**：房主创建在线房间并复制邀请链接，对方打开后加入。
- **存档**：在本机网址打开“存档与回放”，选择继续在线对局或逐手回放；数据保存在项目的 `saves` 文件夹。
- **走棋**：先推进必须行动的棋盘，保护所有王，再点击“提交行动”。

详细说明见 [游玩指南](docs/guides/PLAY.md) 与 [联机及网络排查](docs/guides/P2P_CLOUDFLARE.md)。正常联网的对局会持续续期；断线后有重连保留期，重启服务会丢失内存中的房间。Cloudflare 临时入口的可达性和延迟取决于网络。

## 仓库导航

```text
本地.bat / 远程.bat   双击启动
使用说明.txt         解压后的操作说明
src/                 游戏引擎、AI、模式与界面
scripts/             启动、环境准备、训练及发布工具
tests/               自动化测试与回归局面
docs/                使用指南、开发文档、规则参考与验证记录
data/                开局数据
saves/               本地自动存档（运行时生成）
```

运行时生成的 `.runtime/`、`logs/`、`dist/` 等目录不提交到仓库。安装依赖位于项目内，不修改系统 PATH。

| 想了解 | 入口 |
| --- | --- |
| 使用、联机与排错 | [游玩指南](docs/guides/PLAY.md) · [联机指南](docs/guides/P2P_CLOUDFLARE.md) |
| 开发、测试与发布 | [开发环境](docs/development/SETUP.md) · [脚本说明](scripts/README.md) · [发布流程](docs/development/RELEASING.md) |
| 棋子规则、回合与存档 | [规则与引擎](docs/reference/ENGINE.md) · [棋谱与存储](docs/reference/REPLAY.md) |
| AI 与可选训练 | [AI 行为](docs/reference/AI.md) · [训练指南](docs/development/LOCAL_AI_TRAINING.md) |
| 已验证范围与历史记录 | [验证索引](docs/validation/README.md) |

普通游戏不需要 PyTorch，模型权重不随源码分发。AI 训练是可选开发功能，其测评结果不等同于通用棋力保证。

## 项目与许可

玩法灵感来自 [《5D Chess With Multiverse Time Travel》](https://store.steampowered.com/app/1349230/5D_Chess_With_Multiverse_Time_Travel/)。代码与项目自制素材独立制作，与原游戏开发者和发行商没有隶属、合作或授权关系。

本项目有权许可的代码、文档和自制素材采用 [MIT License](LICENSE)。第三方依赖、名称、标识与外部引用内容保留各自权利，许可证不涵盖原游戏的代码、素材或品牌标识。
