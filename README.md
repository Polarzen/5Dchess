# ♟️ 5D Chess with Multiverse Time Travel

一个使用 Python 实现的 **5D Chess / 多时间线国际象棋项目**。核心引擎以 canonical 4D 坐标描述空间、时间与时间线移动，并通过不可变历史棋盘、Action / The Present、RoyalRules 与 Action 级终局搜索实现完整的 5D 对局规则基础。

> **当前状态：核心规则层已基本完成，Web 5D 交互界面已进入主界面阶段。**
>
> 当前重点从规则重构转向多棋盘 Web GUI、Replay / Storage 适配，以及后续独立的本地 AI 训练工作。

---

## ✅ 当前已完成

### Canonical 坐标与棋盘模型

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

`side` 用于描述棋盘阶段，不作为额外移动轴。旧存储仍可以使用 half-move `time_point`，但规则几何统一通过 `BoardCoord` 转换。

### PieceMovementRules / PawnRules

标准棋子的 5D 几何规则已经实现：

| 棋子 | 规则 |
|---|---|
| Rook | 恰好沿 1 个维度移动任意距离 |
| Bishop | 恰好沿 2 个维度等距离移动 |
| Queen | 沿 1–4 个维度等距离移动 |
| King | Queen 方向的 4D 一步 |
| Knight | 任意两维组成 `1 + 2` 跳跃 |
| Pawn | 颜色相关的 Y / L 前进与 X-Y / T-L 捕获 |

Pawn 还包含首次双步、Timeline 双步中间 Board 检查、Queen promotion 与同 Board en passant。

### PathRules / MultiverseBoardView

- Rook / Bishop / Queen 使用真实 4D 路径检查。
- 中间 Board 缺失会阻断滑动路径。
- 中间格有棋子会阻断路径。
- `MultiverseBoardView` 负责 `BoardCoord → Position` 解析以及 Historical / Playable Board 分类。

### Signed Timeline L

主时间线为 `L0`：

```text
White 创建的分支：L+1, L+2, ...
Black 创建的分支：L-1, L-2, ...
```

active / inactive timeline 由 `TimelineRules` 推导，不再由单一 UI 选中时间线决定。

### 真实 4D MoveGenerator / MoveValidator

走子生成器已经支持：

- 同 Board 空间移动
- 同 Timeline 时间移动
- Historical Board branching move
- 不同 playable timeline 之间的 cross-timeline move
- Pawn 的 Y / L 前进与 T-L 捕获

`MoveValidator` 负责单 Move 几何、路径、目标占用与 board-local 合法性；完整 multiverse 王安全由更高层规则负责。

### Canonical Engine Execution

Engine 执行层已经统一使用 `Move.source / Move.destination`：

- 普通 Move 创建 source Board successor
- branching move 从目标历史 Board 创建新 Timeline，同时保持原历史不可变
- cross-timeline move 分别创建 source / destination successor
- Pawn 首次移动状态、promotion、castling、en passant 均随 successor 保存

### Action / The Present

一个玩家回合不再等同于单个 Move。

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

- `Action`
- `ActionRules`
- `TimelineRules`
- active / inactive timeline
- The Present
- required boards
- movable / optional boards
- 显式 `submit_action()`

Board-local successor 每次 Move 都会正常推进 side，但 `current_turn_color` 只在 Action Submit 后切换。

### RoyalRules / 5D Check

`RoyalRules` 会检查整个 multiverse 中的王实例与 4D 攻击关系，包括：

- Rook / Bishop / Queen 的 4D 滑动攻击
- Knight 4D 跳跃
- King 4D 邻接
- Pawn 5D 捕获几何
- 历史 King 实例
- inactive timeline 上仍可作为 optional move source 的 playable Board
- The Present 的虚拟 pass check 语义

Action 只有在 The Present 推进完成且所有王安全时才能 Submit。

### Checkmate / Stalemate

终局已经升级为 **Action 级搜索**，不再使用“单张棋盘无合法 Move”作为 5D 终局条件。

`ActionSearch` 会搜索当前玩家是否存在至少一个可以：

1. 从合法 movable Board 开始；
2. 完成所有 required Present Board；
3. 必要时使用 future / inactive Board、branching 或 cross-timeline move；
4. 最终推进 The Present；
5. 通过 RoyalRules；
6. 成功 Submit。

如果不存在完整合法 Action：

```text
处于 5D Check     → CHECKMATE
不处于 5D Check   → STALEMATE
```

---

## 🖥️ Web 5D GUI

Web 是当前项目的**主 5D 交互界面**。Pygame GUI 仍保留为 legacy 原型，但后续不会再维护两套完整 5D 交互逻辑。

当前 Web 界面采用多棋盘 multiverse canvas：

```text
纵向：Timeline L
横向：Time T

L+1   [Board] → [Board] → [Board]
          ↗ branch / 5D move
L0    [Board] → [Board] → [Board] → ...
          ↘
L-1        [Board] → [Board]
```

已支持：

- 同屏显示所有 stored BoardCoord
- 小棋盘按 Timeline / Time 排列
- 紫色时间轨道与分支曲线
- Present 高亮
- required Board 强高亮
- movable / inactive / historical 状态区分
- BoardCoord 信息查看
- 在任意 movable Board 选择棋子
- 跨多个 Board 同时显示合法 5D 目标
- branching / cross-board 候选曲线
- canonical BoardCoord API
- PvP 中 `execute_action_move()` + 显式 `Submit Action`
- Replay 多时间线概览基础
- 棋盘缩放与 Present 定位

启动：

```bash
python src/main.py --web
```

或直接：

```bash
python src/main.py
```

默认地址：

```text
http://127.0.0.1:5000
```

---

## 🤖 AI 状态

仓库保留已有 legacy 搜索型 AI：

- Random AI
- Alpha-Beta AI
- Evaluation
- Opening Book

这些 AI 目前仍主要基于早期单 Move 搜索接口，仅作为兼容功能保留。

本地模型训练、自对弈数据、模型结构与 checkpoint 管理将在独立分支：

```text
feat/local-ai-training
```

中继续，不与当前规则 / Web GUI 开发混合。

---

## 💾 Replay / Storage

当前仓库仍包含：

- `.5dpgn` 棋谱解析
- ReplayMode
- MySQL / SQLAlchemy 数据层
- 异步写入模块

这些模块仍有部分接口建立在早期 legacy Move / timeline 表示上。

下一阶段将重点完成：

- Action history 持久化
- canonical source / destination 保存
- branching / cross-timeline replay 一致性
- Web multiverse Replay 适配
- legacy 存档兼容边界整理

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
├── gui/                  # legacy Pygame prototype
├── modes/
├── ai/
├── data/
└── main.py
```

---

## 🚀 开发环境

推荐：

- Python 3.11
- MySQL 8.0（数据库相关测试 / 功能）

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

当前 CI 在 Pull Request / `main` 更新时执行：

```text
MySQL 8.0 service
        ↓
pip install -r requirements.txt
        ↓
python -m compileall -q src
        ↓
python -m pytest -q
```

开发流程保持：

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

Replay / Storage               ← 下一阶段
AI Local Training              独立分支
```

---

## 📄 License

MIT License
