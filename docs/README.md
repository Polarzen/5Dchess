# 文档目录

[返回项目首页](../README.md) · [下载最新版](https://github.com/Polarzen/5Dchess/releases/latest)

## 使用指南

- [解压后的使用说明](../使用说明.txt)：下载、两个启动入口、停止与常见问题。
- [游玩指南](guides/PLAY.md)：模式选择、教程与行动提交。
- [联机和 Cloudflare](guides/P2P_CLOUDFLARE.md)：局域网、异地邀请、重连和网络排查。

## 开发与维护

- [环境和测试](development/SETUP.md)：Python、命令行、测试与代码目录。
- [本地与云端训练](development/LOCAL_AI_TRAINING.md)：可选 AI 训练工具。
- [发布流程](development/RELEASING.md)：可复现打包、校验和、GitHub Release。
- [脚本索引](../scripts/README.md)：各启动、验证与训练脚本的用途。

## 规则与实现参考

- [规则与引擎](reference/ENGINE.md)：坐标、走子、时间线、行动与终局。
- [棋谱与存储](reference/REPLAY.md)：`saves` 续局、回放和 `.5dpgn`。
- [AI 行为](reference/AI.md)：搜索预算、难度和训练边界。

## 验证与历史

- [验证索引](validation/README.md)：实际验收范围、故障回放与机器可读证据。
- [历史项目大纲](archive/PROJECT_OUTLINE.md)：早期设计草案，部分设想已变化，以当前规则参考和代码为准。
