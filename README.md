# ♟️ 5D Chess with Multiverse Time Travel

一个使用 Python 实现的 **5D Chess / 多时间线国际象棋实验项目**。

项目以传统 8×8 国际象棋为基础，引入 **时间（T）** 与 **时间线（L）** 两个额外的可移动维度，并围绕不可变历史棋盘、时间旅行、时间线分支、跨时间线移动和 4D 棋子几何规则持续完善核心引擎。

> 🚧 **当前状态：核心规则重构中。**
>
> 目前已经完成 canonical 4D 坐标、时间/时间线模型、4D 路径检查、六类标准棋子的 5D 走子生成，以及跨棋盘走子的双棋盘验证。接下来重点是 Canonical Engine Execution、Action / The Present、完整跨棋盘王安全规则以及界面层的 5D 交互。

---

## 🧭 当前规则模型

引擎把一个棋子位置表示为：

```text
Square5D
├── x          空间 X 轴
├── y          空间 Y 轴
└── BoardCoord
    ├── timeline   L 轴
    ├── turn       T 轴
    └── side       当前半回合阶段
```

棋子的几何移动使用四维向量：

```text
Vector4D(dx, dy, dt, dl)
```

其中：

| 轴 | 含义 |
|---|---|
| `x` | 棋盘列方向 |
| `y` | 棋盘行方向 |
| `T` | 同一时间线上的时间方向 |
| `L` | 不同时间线之间的方向 |

`side` 不作为第五个移动轴，而是用于标识同一个完整回合中的白/黑半回合棋盘。

---

## ✅ 已实现的核心能力

### Canonical 4D 坐标

已经建立独立于旧 `Position.time_point` 的规则坐标层：

- `BoardCoord(timeline, turn, side)`
- `Square5D(board, x, y)`
- `Vector4D(dx, dy, dt, dl)`
- legacy half-move 时间与 canonical `(T, side)` 之间的兼容转换

旧存储仍可以继续使用 half-move `time_point`，但 4D 几何计算统一使用 canonical 坐标。

### 有方向的 Timeline 轴

主时间线固定为：

```text
L0
```

当前时间线坐标采用有符号整数：

```text
White 创建的分支：L+1, L+2, ...
Black 创建的分支：L-1, L-2, ...
```

这样 `Vector4D.dl` 表示真正的时间线方向和距离，而不是简单的“分支创建序号”。

### 不可变历史棋盘

跨时间和跨时间线走子不会直接修改已经存在的历史 `Position`。

规则层通过 successor board / 新时间线产生新的状态，已有历史棋盘保持不变。

### MultiverseBoardView

`MultiverseBoardView` 为旧 Timeline 存储提供 canonical 只读视图：

- `BoardCoord → Position` 解析
- Historical / Playable Board 分类
- Timeline active 状态读取
- canonical 顺序遍历
- Timeline / time / side 元数据一致性校验

规则代码因此不需要到处直接操作 legacy `time_point`。

### PieceMovementRules / PawnRules

标准棋子的 5D 走子几何已经按两层规则组织：

| 棋子 | 当前几何规则 |
|---|---|
| Rook | 恰好沿 1 个维度移动任意距离 |
| Bishop | 恰好沿 2 个维度等距离移动 |
| Queen | 沿 1–4 个维度等距离移动 |
| King | Queen 方向的 4D 一步移动 |
| Knight | 任意两个维度组成 `1 + 2` 的 L 型跳跃 |
| Pawn | 颜色相关前进；沿 Y 或 L 前进；只在 X/Y 或 T/L 平面捕获 |

Rook / Bishop / Queen / King / Knight 使用对称的 `PieceMovementRules`；Pawn 使用独立的 `PawnRules`，因为它的规则依赖颜色、捕获状态和首次移动状态。

当前 Pawn 规则包括：

- White：空间前进 `-Y`，Timeline 前进 `-L`
- Black：空间前进 `+Y`，Timeline 前进 `+L`
- 非捕获时可沿 Y 或 L 前进一步
- 首次移动可沿 Y 或 L 前进两步
- 空间捕获仅允许 `X/Y` 对角
- 时间捕获仅允许 `T/L` 对角
- 不允许空间轴与时间轴混合捕获
- Timeline 双步要求中间 Board 存在且目标格为空
- Promotion 只允许升变为 Queen
- En passant 只保留传统同一 Board 语义，不扩展到时间或 Timeline

`Position` 会随不可变历史保存 Pawn 的首次移动状态，因此沿 Timeline 移动过的 Pawn 不会再次错误获得双步权利。

### PathRules

Rook / Bishop / Queen 的滑动路径已经支持四维检查。

系统会枚举 source 与 destination 之间的所有中间 `Square5D`，并区分：

- `missing_board`：中间所需棋盘不存在
- `occupied`：中间格存在棋子阻挡

Knight / King 不使用滑动路径检查。

### 真实 4D MoveGenerator

旧的“同一格直接传送到过去”的简化时间旅行生成逻辑已经被替换。

非 Pawn 棋子的生成流程：

```text
Playable source Board
        ↓
MultiverseBoardView
        ↓
选择同 side 的真实目标 Board
        ↓
计算 dt / dl
        ↓
推导少量 dx / dy 候选
        ↓
PieceMovementRules
        ↓
PathRules（滑动棋子）
        ↓
目标占用检查
        ↓
生成 Move
```

Pawn 则使用颜色相关的 `PawnRules`，在空间 Board 内生成 Y 前进 / X-Y 捕获，在 multiverse 中生成 L 前进 / T-L 捕获。

Historical Board 目标会生成 branching Move；另一条时间线上的 Playable Board 可以生成 cross-timeline Move。

### 跨棋盘 MoveValidator

跨时间 / 跨 Timeline 走子不再被错误地模拟成“在 source Board 内从起点直接移动到终点”。

当前验证器会分别构造：

```text
source_after
    └── 移除移动棋子

destination_after
    └── 放入移动棋子 / 完成 capture
```

并检查：

- source 是否是当前 Playable Board
- destination 是否真实存在
- Historical 目标是否正确标记 branching
- 目标位置是否存在己方棋子
- capture 元数据是否与目标棋盘一致
- 4D movement geometry
- slider 4D path
- Pawn 的颜色方向、首次双步、中间 Board、捕获平面、Promotion / en passant 约束
- source / destination 两张结果棋盘上的局部王安全

这一层仍然是 **single-move + board-local safety**。完整跨棋盘 attack / check / checkmate 会在后续 `ActionRules / RoyalRules` 中实现。

---

## 🌲 时间旅行与分支

当前 Engine 已经支持基础的分支和跨时间线状态变更，并重点保证历史棋盘不会被原地修改。

向 Historical Board 移动时会产生新的 Timeline；跨 Timeline 移动时 source 与 destination 分别产生新的 successor 状态。

目前仍在继续把 Engine 执行层从 legacy：

```text
from_time / to_time
from_timeline_id / to_timeline_id
```

逐步迁移到直接使用：

```text
Move.source
Move.destination
```

---

## 🚧 尚未完成的规则

以下内容目前 **不应视为已经完整实现**：

- 一个玩家回合包含多个 Move 的 `Action` 模型
- `The Present` 推进与 Submit Turn
- active / inactive Timeline 的完整官方规则
- 跨 Board / 跨时间 / 跨 Timeline 的 King attack 检测
- 完整 5D check / checkmate / stalemate
- Action 级合法走子搜索

因此当前项目已经具备标准棋子的真实 4D **走子几何与跨棋盘状态基础**，但还不能把现阶段的 `RulesEngine` 等同于完整的最终 5D Chess 规则实现。

---

## 🤖 AI 状态

仓库当前保留已有的传统搜索型 AI：

- Random AI
- Alpha-Beta AI
- 基于评估函数的较深搜索
- Opening Book

这些 AI 主要基于当前 legacy / 单步搜索结构，还没有完成面向最终 Action-level 5D 规则的整体迁移。

本地模型训练将作为独立工作进行，目前已经预留专用分支：

```text
feat/local-ai-training
```

计划中的本地训练、自对弈、训练数据、模型结构和 checkpoint 管理不会与当前规则引擎重构混在同一个开发分支中。

---

## 🖥️ 界面与其他模块

仓库中目前包含：

- Pygame 桌面 GUI
- Flask Web 模块
- PvP / PvE / Replay 模式
- Timeline tree 可视化代码
- MySQL / SQLAlchemy 数据持久化
- `.5dpgn` 棋谱解析

这些模块已经具备原型实现，但部分接口仍基于早期二维 / 简化时间旅行模型，后续需要继续适配 canonical `Square5D`、Timeline + Turn 目标选择以及 Action-level 规则。

特别是 GUI / Web 层目前还不能视为完整的 5D 交互界面。

---

## 🗂️ 核心项目结构

```text
5Dchess/
├── src/
│   ├── main.py
│   ├── engine/
│   │   ├── coordinates.py       # BoardCoord / Square5D / Vector4D
│   │   ├── board.py             # Position + Pawn 首次移动状态
│   │   ├── piece.py             # 棋子定义
│   │   ├── piece_movement.py    # R/B/Q/K/N 4D 几何规则
│   │   ├── pawn_rules.py        # 标准 Pawn 5D 规则
│   │   ├── path_rules.py        # 4D 滑动路径与阻挡检查
│   │   ├── multiverse.py        # canonical Board resolver / board role
│   │   ├── move_generator.py    # 标准棋子真实 4D 走子生成
│   │   ├── move_validator.py    # 空间与跨棋盘走子验证
│   │   ├── timeline.py          # 有符号 L 轴 / Timeline 管理
│   │   ├── engine.py            # 状态变更与走子执行
│   │   └── rules.py             # 当前 legacy 王安全 / 结果规则
│   ├── ai/
│   ├── modes/
│   ├── gui/
│   ├── web/
│   ├── data/
│   └── utils/
├── tests/
├── sql/
├── data/
├── .github/
│   └── workflows/
│       └── ci.yml
├── requirements.txt
└── README.md
```

---

## 🚀 开发环境

### 基础要求

- Python 3.11 推荐
- MySQL 8.0：数据库相关功能和 CI 数据库测试使用

安装当前声明的依赖：

```bash
pip install -r requirements.txt
```

### 运行测试

```bash
python -m pytest -q
```

也可以通过入口运行：

```bash
python src/main.py --test
```

### CLI

```bash
python src/main.py --cli
```

### GUI

```bash
python src/main.py --pvp
python src/main.py --pve easy
python src/main.py --pve medium
python src/main.py --pve hard
```

当前 `--pvp / --pve` 参数已经存在，但 GUI 入口仍需要继续完成模式参数与 5D 交互层的整合。

### Web

入口支持：

```bash
python src/main.py --web
```

当前默认无参数启动也会进入 Web 模式。

> 注意：仓库当前 `requirements.txt` 尚未声明 Flask，因此 Web 运行依赖仍需要进一步整理；现阶段不要把 Web 启动视为完全开箱即用。

---

## 🧪 GitHub Actions

仓库已经配置 CI workflow。

对 `main` 的 Push / Pull Request 会自动执行：

```text
MySQL 8.0 service
        ↓
安装 requirements.txt
        ↓
python -m compileall -q src
        ↓
python -m pytest -q
```

规则重构目前采用“功能分支 → PR → Actions 验证 → squash merge”的方式推进，以避免未经验证的规则改动直接进入 `main`。

---

## 🛣️ 当前开发路线

近期规则层优先级：

```text
1. Canonical Engine Execution
        ↓
2. Action / The Present
        ↓
3. RoyalRules
        ↓
4. 完整 check / checkmate / stalemate
        ↓
5. GUI / Web 5D 交互适配
```

AI 本地训练作为独立开发方向，在核心规则接口稳定后从 `feat/local-ai-training` 继续推进。

---

## 📄 License

MIT License