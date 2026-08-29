# ♟️ 5D Chess with Multiverse Time Travel

一个使用 Python 实现的 **5D Chess / 多时间线国际象棋项目**。核心引擎使用 canonical 4D 坐标描述空间、时间与时间线移动，并通过不可变历史棋盘、Action / The Present、RoyalRules、Action 级终局搜索以及多棋盘 Web 界面实现完整的 5D 对局基础。

> **当前状态：核心规则、Web 5D Interaction 与 Replay / Storage v2 已完成。**
>
> 当前主线不再包含 EXE 打包计划；本地模型训练继续保留在独立的 `feat/local-ai-training` 分支中。

---

## ✅ 核心规则

### Canonical 坐标

规则层统一使用：

```text
Square5D
├── x
├── y
└── BoardCoord
    ├── timeline   # L 轴
    ├── turn       # T 轴
    └── side       # white / black 半回合阶段
```

棋子移动向量为：

```text
Vector4D(dx, dy, dt, dl)
```

`side` 用于描述棋盘阶段，不作为额外移动维度。旧 half-move `time_point` 只保留在兼容 / 存储边界，规则几何使用 canonical `BoardCoord`。

### PieceMovementRules / PawnRules

| 棋子 | 5D 几何规则 |
|---|---|
| Rook | 恰好沿 1 个维度移动任意距离 |
| Bishop | 恰好沿 2 个维度等距离移动 |
| Queen | 沿 1–4 个维度等距离移动 |
| King | Queen 方向的 4D 一步 |
| Knight | 任意两维组成 `1 + 2` 跳跃 |
| Pawn | 颜色相关的 Y / L 前进与 X-Y / T-L 捕获 |

Pawn 另外支持首次双步、Timeline 双步中间 Board 检查、Queen promotion 与同 Board en passant。

### PathRules / MultiverseBoardView

- Rook / Bishop / Queen 使用真实 4D 路径检查。
- 缺失的中间 Board 会阻断滑动路径。
- 中间格被占用会阻断路径。
- `MultiverseBoardView` 负责 `BoardCoord → Position`、Historical / Playable Board 分类与 canonical 遍历。

### Signed Timeline L

主时间线固定为 `L0`：

```text
White 创建分支：L+1, L+2, ...
Black 创建分支：L-1, L-2, ...
```

active / inactive timeline 由 `TimelineRules` 推导；`active_timeline_id` 仅保留为 legacy UI 选择指针。

### 4D MoveGenerator / MoveValidator

已支持：

- 同 Board 空间移动
- 同 Timeline 时间移动
- Historical Board branching move
- 不同 playable timeline 之间的 cross-timeline move
- Pawn 的 Y / L 前进与 T-L 捕获

`MoveValidator` 负责单 Move 的几何、路径、目标占用和 board-local 合法性；全局王安全由 `RoyalRules` 负责。

### Canonical Engine Execution

Engine 执行层统一使用 `Move.source / Move.destination`：

- 普通 Move 创建 successor Board
- branching move 从历史目标创建新 Timeline
- 原历史 Board 不会被原地修改
- cross-timeline move 分别创建 source / destination successor
- Pawn 首次移动状态、promotion、castling、en passant 随 successor 保存

### Action / The Present

一个玩家回合是一个 `Action`，可以包含多个 `Move`：

```text
Action
├── Move
├── Move
└── ...
      ↓
The Present 推进到对手
      ↓
Submit Action
      ↓
全局换方
```

已经实现：

- `Action` / `ActionRules`
- `TimelineRules`
- active / inactive timeline
- The Present
- required boards
- movable / optional boards
- `execute_action_move()`
- 显式 `submit_action()`

Board-local successor 每个 Move 都推进自己的 side，但 `current_turn_color` 只有在 Action Submit 后切换。

### RoyalRules / Check / Checkmate / Stalemate

`RoyalRules` 检查整个 multiverse 的 4D 攻击，包括历史 King 实例与跨时间 / 跨 Timeline 攻击。

终局采用 Action 级搜索：

```text
是否存在至少一个完整合法 Action？
        │
        ├─ 是 → 继续游戏
        │
        └─ 否
            ├─ 当前处于 5D Check → CHECKMATE
            └─ 当前不在 Check     → STALEMATE
```

因此“某一张棋盘没有合法 Move”不会被错误当成整个 multiverse 的终局。

---

## 🖥️ Web 5D Interaction

Web 是项目的**主 5D GUI**；Pygame GUI 只保留为 legacy 原型。

界面使用多棋盘时间线画布：

```text
纵向：Timeline L
横向：Time T

L+1   [Board] → [Board] → [Board]
          ↗ branch / 5D move
L0    [Board] → [Board] → [Board] → ...
          ↘
L-1        [Board] → [Board]
```

当前支持：

- 同屏显示所有 stored BoardCoord
- Timeline / Time 排列的小棋盘
- 时间轨道和分支曲线
- Present / required / movable / inactive / historical 状态高亮
- BoardCoord 信息查看
- 从任意合法 movable Board 选择棋子
- 跨多个 Board 同时显示合法 5D 目标
- branching / cross-board 候选曲线
- canonical BoardCoord Web API
- PvP `execute_action_move()` + 显式 `Submit Action`
- 棋盘缩放与 Present 定位

启动：

```bash
python src/main.py --web
```

或者：

```bash
python src/main.py
```

默认地址：

```text
http://127.0.0.1:5000
```

---

## 🌐 Online P2P / Cloudflare Tunnel

在线 P2P 通过 Cloudflare Quick Tunnel 发布房主的 Web 服务；5D 引擎和对局状态始终由房主服务端权威维护。一个服务进程只开放一个房间和一个房间码：`White = host`（房主），`Black = joiner`（加入者）。

Windows 下从项目根目录启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_p2p.ps1
```

脚本会启动 `debug=False` 的本地 Flask 服务，并创建临时的 `https://*.trycloudflare.com` Quick Tunnel。把终端显示的 HTTPS 地址发给对手，双方打开同一地址后，房主点击“创建真人房间”，对手输入房间码点击“加入真人房间”。需要手动分开启动时，可分别运行：

```powershell
python scripts/run_p2p_server.py
cloudflared tunnel --url http://127.0.0.1:5000
```

浏览器将每位玩家的 bearer `player_token` 与房间码保存在本地；刷新或短暂断线后，使用同一房间码和令牌可以恢复原来的颜色。客户端每 1.2 秒轮询房间状态，这个轮询同时作为连接 heartbeat。服务端在 8 秒 lease 超时后把座位视为暂时离线，并保留 30 秒 reconnect grace；观察到连接状态变化时递增 `state_version`。超过 lease+grace 后，黑方座位释放，失联的房主房间也过期，不再阻塞新房间创建。

对局规则与生命周期：

- 对手离线时不能走子、提交 Action 或进行其他局面 mutation。
- 白方显式返回菜单会关闭整个房间；黑方显式返回菜单会立即释放黑方座位。
- 常见认证、房间和状态错误以 JSON 4xx 响应返回；`player_token` 不写入日志。

---

## 💾 Replay / Storage v2

Replay / Storage 已迁移到 canonical v2 格式。

### `.5dpgn` v2

新文件写入：

```text
schema_version = 2
format version = 2.0
```

每个 Move 以 canonical 坐标保存：

```text
Move
├── piece
├── source
│   ├── BoardCoord(timeline, turn, side)
│   ├── x
│   └── y
└── destination
    ├── BoardCoord(timeline, turn, side)
    ├── x
    └── y
```

文件同时保存：

- 完整 `move_history`
- 完整 `action_history`
- 每个 Action 的 starting Present
- Action 内 Move 顺序
- `submitted` 边界
- 当前尚未提交的 Action
- branching / cross-timeline 元数据
- `created_timeline`
- promotion / castling / en passant / capture 信息
- 最终 TimelineManager 状态
- `Replay Origin`

### Replay Origin

v2 不再假设所有棋谱都从标准初始棋盘开始。

对于标准新游戏，系统会使用标准起点；如果调用方先构造自定义 multiverse / 测试局面，应在第一步 Move 前调用：

```python
GameArchive.set_replay_origin(engine)
```

这样 Replay 可以从真实起始 multiverse 严格重建整局。

### Action-aware Replay

Replay UI 仍然一次前进一个可见 Move，但会保留原始 Submit 边界。

例如：

```text
White Action
├── Move A   ← 此时其实已经可以 Submit
├── Move B   ← 玩家当时选择继续走 optional future Board
└── SUBMIT
```

Replay 时：

```text
step 1 → Move A，仍然是 White
step 2 → Move B + 原记录的 SUBMIT，切换 Black
```

不会因为 Replay 调用旧 `execute_move()` 而提前换方。

Replay 会从 Replay Origin 重建每一步精确快照，并在 v2 文件加载时验证最终重建状态与存档状态一致。

### v1 文件兼容

旧 `.5dpgn` v1 仍可读取。

v1 没有显式 Action / Submit 信息，因此读取时会通过旧 auto-submit 行为推断 Action 边界。新文件统一写 v2，不再继续生成 v1。

### MySQL canonical schema

数据库 baseline schema 已同步到 v2：

```text
games
├── total_actions
└── archive_version

timelines
├── timeline_row_id      # DB 内部主键
├── lane_id              # canonical signed L，可为负数
├── parent_lane_id
└── owner

actions
├── game_id
├── action_index
├── color
├── starting_present_json
├── submitted
└── move_count

moves
├── action_index / move_index
├── source_timeline / source_turn / source_side / x / y
├── destination_timeline / destination_turn / destination_side / x / y
├── branching / cross-timeline flags
└── created_timeline / capture / promotion / notation
```

数据库中的 `timeline_row_id` 与规则里的 `lane_id` 已分离，因此 `L-1`、`L-2` 等 Black-created timeline 可以正常持久化。

`from_time / to_time` 暂时只作为兼容 / debug hint 保留，不再是新存储格式的主语义。

> **数据库兼容说明：** `.5dpgn` v1 有读取兼容层；旧版 MySQL v1 schema 没有足够的 Action / signed-L 信息进行无损自动迁移，因此当前不伪造自动迁移。已有旧数据库需要根据实际数据选择重建 v2 schema 或单独编写迁移流程。

---

## 🤖 AI 状态

仓库仍保留 legacy 搜索型 AI：

- Random AI
- Alpha-Beta AI
- Evaluation
- Opening Book

这些实现仍主要基于早期单 Move 搜索接口，仅作为兼容功能保留。

本地模型训练、自对弈数据、模型结构与 checkpoint 管理继续放在独立分支：

```text
feat/local-ai-training
```

规则、Web 与 Replay / Storage 主线不会直接混入本地训练实现。

---

## 🗂️ 核心结构

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
├── ai/
└── main.py

sql/
└── schema.sql
```

---

## 🚀 开发环境

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

---

## 🧪 GitHub Actions

Pull Request / `main` 更新会运行 Python 3.11 + MySQL 8.0 CI，验证：

```text
MySQL 8.0 service
        ↓
pip install -r requirements.txt
        ↓
python -m compileall -q src
        ↓
pytest
├── 核心规则回归
├── Web 5D Interaction
├── Replay / Storage v2
└── MySQL v2 schema + signed L / Action / canonical Move integration
```

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

---

## 🛣️ 当前开发路线

```text
Canonical Coordinates          ✅
Piece / Pawn Movement Rules    ✅
PathRules                      ✅
MultiverseBoardView            ✅
Signed Timeline L              ✅
4D MoveGenerator               ✅
4D MoveValidator               ✅
Canonical Engine Execution     ✅
Action / The Present           ✅
RoyalRules / 5D Check          ✅
Checkmate / Stalemate          ✅
Web 5D Interaction             ✅
Replay / Storage v2            ✅
Online P2P / Cloudflare Tunnel ✅

AI Local Training              独立分支 / 下一大阶段
EXE                            已移出项目范围
```

---

## 📄 License

MIT License
