# 验证记录索引

[文档目录](../README.md)

这里保存按日期记录的验证证据。历史记录描述当时的源码和环境，不能据此推断每个后续版本已经通过相同测试；新版本状态请同时查看 [GitHub Actions](https://github.com/Polarzen/5Dchess/actions) 和 [发布说明](https://github.com/Polarzen/5Dchess/releases)。

| 记录 | 内容 |
| --- | --- |
| [P2P 验收](P2P_ACCEPTANCE.md) | 安装、公网、局域网、端口冲突与已验证范围 |
| [在线存档与恢复](P2P_RECOVERY.md) | 自动存档、进程重启、断线提示，以及待完成的异地双机步骤 |
| [Web 可靠性](WEB_RELIABILITY.md) | 请求、轮询、教程、超时与规则修复记录 |
| [AI / Arena 汇总](arena-acceptance-status.md) | 历次规则、规划和长对局测评，包含历史失败边界 |
| [规则与循环](rules-loop-validation-20261012.json) | 规则修正和长局检查 |
| [规划超时](planner-timeout-fix-20261012.json) | 超时故障和修复验证 |
| [规划历史](planner-validation-20261011.json) | 历史回归局面 |
| [AI 重复偏好](ai-repetition-validation-20261012.json) | 重复局面和策略对照 |
| [终局评分](ai-terminal-scoring-validation-20261012.json) | 战术与终局评分对照 |
| [终局评估](outcome-evaluation-validation-20261012.json) | 终局检查性能与正确性 |
| [CI 性能](ci-performance-validation-20261012.json) | 回归耗时和预算 |

JSON 中原始运行路径、提交和哈希保留原貌；移动文档不会重新解释或修改历史测量结果。
