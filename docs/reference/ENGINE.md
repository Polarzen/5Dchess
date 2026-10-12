# 规则与引擎

[文档导航](../README.md)

## Canonical 坐标

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

## PieceMovementRules / PawnRules

| 棋子 | 5D 几何规则 |
|---|---|
| Rook | 恰好沿 1 个维度移动任意距离 |
| Bishop | 恰好沿 2 个维度等距离移动 |
| Queen | 沿 1–4 个维度等距离移动 |
| King | Queen 方向的 4D 一步 |
| Knight | 任意两维组成 `1 + 2` 跳跃 |
| Pawn | 颜色相关的 Y / L 前进与 X-Y / T-L 捕获 |

Pawn 另外支持首次双步、Timeline 双步中间 Board 检查、Queen promotion 与同 Board en passant。

标准开局的王车易位检查易位权、王车位置与通路，并禁止王在本棋盘受将军时易位或经过受攻击格；最终落点和全局提交仍须满足王安全。

## PathRules / MultiverseBoardView

- Rook / Bishop / Queen 使用真实 4D 路径检查。
- 缺失的中间 Board 会阻断滑动路径。
- 中间格被占用会阻断路径。
- `MultiverseBoardView` 负责 `BoardCoord → Position`、Historical / Playable Board 分类与 canonical 遍历。

## Signed Timeline L

主时间线固定为 `L0`：

```text
White 创建分支：L+1, L+2, ...
Black 创建分支：L-1, L-2, ...
```

active / inactive timeline 由 `TimelineRules` 推导；`active_timeline_id` 仅保留为 legacy UI 选择指针。

## 4D MoveGenerator / MoveValidator

已支持：

- 同 Board 空间移动
- 同 Timeline 时间移动
- Historical Board branching move
- 不同 playable timeline 之间的 cross-timeline move
- Pawn 的 Y / L 前进与 T-L 捕获

`MoveValidator` 负责单 Move 的几何、路径、目标占用和 board-local 合法性；全局王安全由 `RoyalRules` 负责。

## Canonical Engine Execution

Engine 执行层统一使用 `Move.source / Move.destination`：

- 普通 Move 创建 successor Board
- branching move 从历史目标创建新 Timeline
- 原历史 Board 不会被原地修改
- cross-timeline move 分别创建 source / destination successor
- Pawn 首次移动状态、promotion、castling、en passant 随 successor 保存

## Action / The Present

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

## RoyalRules / Check / Checkmate / Stalemate

`RoyalRules` 检查整个 multiverse 的 4D 攻击，包括历史 King 实例与跨时间 / 跨 Timeline 攻击。

时间旅行可能让一张棋盘没有己方王，或同时存在多个己方王。王离开后，其他棋子仍可正常走子；同色王有多个时，每一个都必须满足王安全规则，提交行动时还会检查历史中的王。

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
