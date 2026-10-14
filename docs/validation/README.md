# 验证记录索引

[文档目录](../README.md)

这里保存按日期记录的验证证据。历史记录描述当时的源码和环境，不能据此推断每个后续版本已经通过相同测试；新版本状态请同时查看 [GitHub Actions](https://github.com/Polarzen/5Dchess/actions) 和 [发布说明](https://github.com/Polarzen/5Dchess/releases)。

| 记录 | 内容 |
| --- | --- |
| [在线 AI 对弈](LLM_AI.md) | 网页配置与防误操作、密钥本机保存、合法候选选招、费用与网络上限、超时回退及模拟接口验收 |
| [历史支线与远程启动](BRANCH_REMOTE_STARTUP.md) | 匿名局面复现、支线操作提示、连接方式选择、隧道失败保留网站及 Windows 端口占用 |
| [跨棋盘速读](CROSS_BOARD_GUIDE.md) | 车象马图例与引擎对照、课程直达、对局隔离及手机布局 |
| [远端仓库隐私与路径](REPOSITORY_PRIVACY_AUDIT.md) | 全引用历史、四个发布 ZIP、邮箱元数据、路径可移植性与仓库保护状态 |
| [浅粉色界面与交互性能](WEB_REDESIGN.md) | 大厅、棋盘、教程、手机布局、增量渲染及轻量联机轮询 |
| [AI 搜索效率](ai-search-efficiency-20261013.json) | 169 / 200 步局面、防守排序、存档复制优化与既有预算回归 |
| [文件存档与回放](FILE_REPLAY.md) | 统一存档入口、逐手回放、续局、无数据库运行 |
| [AI 超时与长局回放](ai-replay-validation-20261012.json) | 全量测试差异、长局校验修复、169 步回放耗时与仍存在的 AI 预算边界 |
| [P2P 验收](P2P_ACCEPTANCE.md) | 安装、公网、局域网、端口冲突与已验证范围 |
| [在线存档与恢复](P2P_RECOVERY.md) | 自动存档、进程重启、断线提示，以及待完成的异地双机步骤 |
| [Web 可靠性](WEB_RELIABILITY.md) | 请求、轮询、教程、超时与规则修复记录 |
| [13 课新手教程](TUTORIAL.md) | 规则对照、独立练习、进度保存和浏览器验收 |
| [AI / Arena 汇总](arena-acceptance-status.md) | 历次规则、规划和长对局测评，包含历史失败边界 |
| [规则与循环](rules-loop-validation-20261012.json) | 规则修正和长局检查 |
| [规划超时](planner-timeout-fix-20261012.json) | 超时故障和修复验证 |
| [规划历史](planner-validation-20261011.json) | 历史回归局面 |
| [AI 重复偏好](ai-repetition-validation-20261012.json) | 重复局面和策略对照 |
| [终局评分](ai-terminal-scoring-validation-20261012.json) | 战术与终局评分对照 |
| [终局评估](outcome-evaluation-validation-20261012.json) | 终局检查性能与正确性 |
| [CI 性能](ci-performance-validation-20261012.json) | 回归耗时和预算 |

2026-10-13 对历史记录中的本机路径作了脱敏：JSON 中的项目绝对目录前缀替换为 `<PROJECT_ROOT>`，P2P 安装验收中的外部工具目录替换为 `<TOOLS_ROOT>`。占位符仅用于说明历史环境，不是可直接执行的路径。提交号、哈希、测试结果、耗时与其他测量数据均保持不变；这些报告不能当作当前版本重新运行过的证据。
