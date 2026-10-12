# 棋谱与存储

[文档导航](../README.md)

Replay / Storage 已迁移到 canonical v2 格式。

## `.5dpgn` v2

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

## Replay Origin

v2 不再假设所有棋谱都从标准初始棋盘开始。

对于标准新游戏，系统会使用标准起点；如果调用方先构造自定义 multiverse / 测试局面，应在第一步 Move 前调用：

```python
GameArchive.set_replay_origin(engine)
```

这样 Replay 可以从真实起始 multiverse 严格重建整局。

## Action-aware Replay

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

## v1 文件兼容

旧 `.5dpgn` v1 仍可读取。

v1 没有显式 Action / Submit 信息，因此读取时会通过旧 auto-submit 行为推断 Action 边界。新文件统一写 v2，不再继续生成 v1。

## MySQL canonical schema

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
