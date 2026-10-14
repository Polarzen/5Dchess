# AI 行为与训练边界

[文档导航](../README.md)

PvE 现在使用 canonical Action 级 AI。AI 在引擎快照上规划一个可以完整推进 The Present、通过 RoyalRules 并可 Submit 的 Action，再由真实引擎逐 Move 重新校验并只 Submit 一次：

- Easy：从完整合法 Action 候选中随机选择（支持固定 seed 的可重复测试）
- Medium：在完整 Action boundary 上进行 bounded 候选评估
- Hard：按 Action / turn 深度执行 bounded alpha-beta / negamax，至少考虑对手的下一 Action 响应
- LLM：由 DeepSeek 或兼容接口选择本地引擎已验证的完整 Action 编号，超时使用本地合法候选；配置和限制见 [在线 AI 对弈](../guides/LLM_AI.md)
- Evaluation：评估当前可玩的 multiverse frontier，不重复累计历史 Board

搜索由状态数、候选 Action 数、单 Action Move 深度和单调时钟共同设限。预算耗尽不会被误判为将杀、逼和或“无合法 Action”：已有完整候选时从中安全选择；尚无完整候选时返回明确的 bounded-search failure 并停止本次 AI 执行。早期 `choose_move()` 和单 Move Opening Book 仅作为兼容接口保留，不进入 canonical PvE 主路径。

网页默认困难 AI 的搜索预算为 2 秒、1536 个状态、12 个候选行动、单行动最多 32 步；历史 hybrid 验证配置为 5 秒、1024 个状态、24 个候选行动、最多 32 步。“预算耗尽”指单次搜索触及其中一个上限，不是项目运行超过 10 分钟。走法重新校验、终局判断和状态序列化仍有额外耗时，搜索秒数不是整个 HTTP 请求的硬超时。

困难 AI 需要推进三个以上棋盘时使用防守优先的混合搜索。浅层探测和深层搜索共用原有截止时间与状态计数；若时间线活动规则已证明单步不可能提交，就跳过浅层探测。深层搜索保留防守、来子和必走棋盘的排序，每个完整候选仍必须通过引擎的王安全提交检查。

主线的 `src/training/` 提供可选的本地训练、自对弈数据生成、模型结构与 checkpoint 管理。
训练依赖通过 `requirements-training.txt` 单独安装；普通游戏不会加载 PyTorch，模型权重和训练数据不随源码分发。

手动触发的 **Local AI Cloud Training** 可让 GitHub-hosted CPU runner 独立完成
canonical self-play、训练、Arena 与可续训 Artifact；启动后本地浏览器和电脑均可关闭。它不表示
模型已达到可发布棋力，也不会自动部署权重或替换 Web 默认 AI。详见训练文档。

训练方法见 [本地与云端训练](../development/LOCAL_AI_TRAINING.md)，历史测评见 [验证记录](../validation/README.md)。
