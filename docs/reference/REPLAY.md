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

## 项目内的 `saves` 存档

在线房间在创建时和每次成功提交行动后，将完整棋局保存到项目的 `saves/<存档ID>.json`。更新版本时，停止服务后复制整个 `saves` 文件夹即可保留记录；也可通过 `FIVE_D_CHESS_SAVE_DIR` 指定目录。普通启动不连接数据库，依赖中不再包含 MySQL 驱动或 SQLAlchemy。

在房主本机网址的菜单选择 **存档与回放**，列表按保存时间显示所有可读取的存档：

- **继续对局**：恢复最终局面并生成新房间码，重新邀请对手；已结束的棋局不能续局。
- **观看回放**：严格重建原始起点、每步走子与提交边界，然后从开局观看。支持上一手、下一手、播放/暂停、跳转和直接到最后；不改变原文件，不创建房间，也不要求对手在线。
- **其他棋谱（.5dpgn）**：进入原有文件加载入口，继续兼容 v1/v2 棋谱。

存档列表、续局和读取存档回放只对本机入口开放，公网及局域网访客不能读取。正在运行的在线房间必须先退出，才能切换存档。当前仅在线对局自动保存；同屏和人机对局仍使用手动导出的棋谱。

### 文件结构与完整性

```text
<save_id>.json
├── payload
│   ├── version = 1           # 自动存档封装版本
│   ├── save_id / saved_at
│   └── game                  # 上文的 GameArchive canonical v2
│       ├── replay_origin
│       ├── move_history / action_history
│       └── 最终完整局面
└── sha256                    # payload 的完整性校验
```

存档不包含玩家身份令牌。写入使用同目录临时文件、落盘和原子替换，失败时保留上一份完整文件。存档只包含已提交的行动；中途未提交的走子需重走。无法读取的文件会保留并在列表提示数量；历史无法精确重建时拒绝进入回放，保留当前棋局。

旧版未接入主流程的数据库连接器、异步写入器及建表文件已移除；已有外部数据库不会被读取、迁移或修改。
