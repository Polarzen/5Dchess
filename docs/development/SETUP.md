# 开发与测试

[文档导航](../README.md)

普通玩家使用根目录启动文件即可。以下命令均在项目根目录执行。

## 环境

推荐：

- Python 3.11
- MySQL 8.0（数据库存储 / CI integration）

安装依赖：

```bash
pip install -r requirements.txt
```

运行测试：

```bash
python -m pytest -q
```

CLI：

```bash
python src/main.py --cli
```

Web：

```bash
python src/main.py --web
```

## 持续集成

面向 `main` 或整合分支 `feat/local-ai-training-v2` 的 Pull Request，以及这两个分支的更新，会运行 Python 3.11 + MySQL 8.0 CI，验证：

```text
MySQL 8.0 service
        ↓
pip install -r requirements.txt
        ↓
python -m compileall -q src
        ↓
Browser / tutorial regressions
├── JavaScript syntax checks
├── node tests/test_browser_reliability.js
├── node tests/test_p2p_invite.js
└── node tests/test_tutorial_browser.js
        ↓
Action loop regression
└── timeout 60s python -m pytest -q tests/test_action_loop_guards.py tests/test_action_warning_web.py
        ↓
Canonical Action AI regression
├── node --check src/web/static/js/game.js
└── timeout 90s python -m pytest -q tests/test_ai.py tests/test_ai_action_planning.py
        ↓
P2P launcher / client / invite checks
├── python -m py_compile scripts/run_p2p_server.py
├── node --check src/web/static/js/p2p.js
├── node --check src/web/static/js/p2p_invite.js
├── node tests/test_p2p_invite.js
├── PowerShell launcher parser validation
└── timeout 60s python -m pytest -q tests/test_p2p_web.py tests/test_p2p_invite_web.py tests/test_hotseat_online_modes.py
        ↓
full pytest
└── python -m pytest -q
```

P2P 回归覆盖房间创建 / 加入、8 秒 player lease、10 分钟 reconnect grace、隧道中断后棋局和双方身份恢复、长对局活动续期、无效 token 不续期、waiting 与 temporarily offline / reconnecting 状态、stale host cleanup、对手离线时暂停 Move / Submit Action、room-code-only 邀请 URL、非法 query 降级以及 Hotseat / Online 模式隔离。

同样的分支和 PR 还会运行 **Local AI Training v2 CI**（CPU 训练 smoke）与 **Planner Regression**。
Planner 使用仓库内的故障局面和 canonical 回放测试，不依赖会过期的模型 Artifact；它验证规划正确性、预算和终局证明，不代表完整对局棋力。
训练 smoke 始终运行，确保引擎与 AI 改动也覆盖训练兼容性。长时间训练和模型 Arena 仍需手动触发。

开发流程：

```text
feature branch
    ↓
Pull Request
    ↓
GitHub Actions
    ↓
squash merge
```

## 代码目录

```text
src/
├── engine/
│   ├── coordinates.py
│   ├── board.py
│   ├── piece.py
│   ├── piece_movement.py
│   ├── pawn_rules.py
│   ├── path_rules.py
│   ├── multiverse.py
│   ├── move_generator.py
│   ├── move_validator.py
│   ├── timeline.py
│   ├── timeline_rules.py
│   ├── action.py
│   ├── action_search.py
│   ├── royal_rules.py
│   ├── outcome_rules.py
│   └── engine.py
├── web/
│   ├── app.py
│   ├── templates/
│   └── static/
├── modes/
│   └── replay.py
├── data/
│   ├── archive.py
│   ├── pgn_parser.py
│   ├── models.py
│   ├── async_writer.py
│   └── db.py
├── gui/                  # legacy Pygame prototype
├── training/             # optional local / cloud training tools
├── ai/
└── main.py

sql/
└── schema.sql
```

脚本说明见 [scripts/README.md](../../scripts/README.md)，发布打包见 [RELEASING.md](RELEASING.md)。
