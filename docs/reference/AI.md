# AI 行为与训练边界

[文档导航](../README.md)

PvE 现在使用 canonical Action 级 AI。AI 在引擎快照上规划一个可以完整推进 The Present、通过 RoyalRules 并可 Submit 的 Action，再由真实引擎逐 Move 重新校验并只 Submit 一次：

- Easy：从完整合法 Action 候选中随机选择（支持固定 seed 的可重复测试）
- Medium：在完整 Action boundary 上进行 bounded 候选评估
- Hard：按 Action / turn 深度执行 bounded alpha-beta / negamax，至少考虑对手的下一 Action 响应
- Evaluation：评估当前可玩的 multiverse frontier，不重复累计历史 Board

搜索由状态数、候选 Action 数、单 Action Move 深度和单调时钟共同设限。预算耗尽不会被误判为将杀、逼和或“无合法 Action”：已有完整候选时从中安全选择；尚无完整候选时返回明确的 bounded-search failure 并停止本次 AI 执行。早期 `choose_move()` 和单 Move Opening Book 仅作为兼容接口保留，不进入 canonical PvE 主路径。

主线的 `src/training/` 提供可选的本地训练、自对弈数据生成、模型结构与 checkpoint 管理。
训练依赖通过 `requirements-training.txt` 单独安装；普通游戏不会加载 PyTorch，模型权重和训练数据不随源码分发。

手动触发的 **Local AI Cloud Training** 可让 GitHub-hosted CPU runner 独立完成
canonical self-play、训练、Arena 与可续训 Artifact；启动后本地浏览器和电脑均可关闭。它不表示
模型已达到可发布棋力，也不会自动部署权重或替换 Web 默认 AI。详见训练文档。

训练方法见 [本地与云端训练](../development/LOCAL_AI_TRAINING.md)，历史测评见 [验证记录](../validation/README.md)。
