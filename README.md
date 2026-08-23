# ♟️ 5D Chess with Multiverse Time Travel

> 🎓 计算机科学与技术本科毕业论文 | Python + MySQL | 三模式系统

复刻 Steam 游戏 *"5D Chess with Multiverse Time Travel"*，在传统二维国际象棋基础上引入**时间**和**平行时间线**维度。棋子可以向过去移动，产生分支时间线，跨时间线跳跃——带来全新的策略深度。

> ⚠️ **开发中** — 核心引擎已完成，GUI 和 Web 界面持续完善中。

---

## 🧠 五维定义

| 维度 | 说明 |
|------|------|
| X轴 | 棋盘列 (a-h, 8列) |
| Y轴 | 棋盘行 (1-8, 8行) |
| 时间 | 同一时间线内前后移动 |
| 平行时间线 | 向过去走子 → 产生新分支 |
| 跨时间线移动 | 棋子在不同时间线之间跳跃 |

**胜负条件：** 任意王在任意时间线的任意时间点被将死，即判负。

---

## ✨ 功能

- 🆚 **PvP 真人对弈** — 同屏热座，落子后交换
- 🤖 **PvE 人机对弈** — 三档AI：简单(随机) / 中等(Alpha-Beta) / 困难(深搜索+开局库)
- 🔁 **Replay 棋谱回放** — 逐步回放、时间线树可视化、快进/快退、统计分析
- 🖥️ **双界面** — Pygame 桌面GUI + Flask Web 界面
- 💾 **数据持久化** — MySQL 异步写入 + `.5dpgn` 棋谱文件
- 🌲 **时间线树** — 可视化所有分支时间线，点击切换查看

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- MySQL 8.0（可选，数据持久化需要）

### 安装

```bash
# 克隆仓库
git clone git@github.com:Polarzen/5Dchess.git
cd 5Dchess

# 安装依赖
pip install -r requirements.txt

# 初始化数据库（可选）
mysql -u root -p < sql/schema.sql
```

### 运行

```bash
# Web 模式（默认，推荐）
python src/main.py

# 命令行模式（测试用）
python src/main.py --cli

# 直接启动PvP（Pygame桌面GUI）
python src/main.py --pvp

# 人机对弈（三档难度）
python src/main.py --pve easy
python src/main.py --pve medium
python src/main.py --pve hard

# 加载棋谱回放
python src/main.py --replay data/replays/example.5dpgn

# 运行测试
python src/main.py --test
```

---

## 📋 依赖

| 库 | 用途 |
|----|------|
| `numpy` | 棋盘状态矩阵运算 |
| `pygame` | 桌面GUI |
| `flask` | Web 服务器 |
| `mysql-connector-python` / `SQLAlchemy` | 数据库 |
| `pytest` | 单元测试 |

---

## 🗂️ 项目结构

```
5Dchess/
├── src/
│   ├── main.py                 # 入口
│   ├── config.py               # 配置
│   ├── engine/                 # 5D核心引擎
│   │   ├── engine.py           # FiveDEngine 主引擎
│   │   ├── board.py            # 棋盘表示
│   │   ├── piece.py            # 棋子定义
│   │   ├── move_generator.py   # 走子生成
│   │   ├── move_validator.py   # 合法性校验
│   │   ├── timeline.py         # 时间线管理
│   │   └── rules.py            # 将军/将杀/和棋判定
│   ├── modes/                  # 游戏模式
│   │   ├── pvp.py              # PvP 真人对弈
│   │   ├── pve.py              # PvE 人机对弈
│   │   └── replay.py           # Replay 棋谱回放
│   ├── ai/                     # AI引擎
│   │   ├── random_ai.py        # 简单AI（随机）
│   │   ├── alpha_beta.py       # 中等AI（Alpha-Beta搜索）
│   │   ├── hard_ai.py          # 困难AI（深搜索+开局库）
│   │   ├── evaluator.py        # 评估函数
│   │   └── opening_book.py     # 开局库
│   ├── gui/                    # Pygame GUI
│   │   ├── app.py              # 主应用
│   │   ├── board_view.py       # 棋盘视图
│   │   ├── timeline_tree.py    # 时间线树可视化
│   │   └── control_panel.py    # 控制面板
│   ├── web/                    # Web 界面 (Flask)
│   │   ├── app.py              # Flask API 服务器
│   │   ├── templates/          # HTML 模板
│   │   └── static/             # CSS/JS 静态资源
│   ├── data/                   # 数据持久化
│   │   ├── db.py               # MySQL 连接
│   │   ├── models.py           # ORM 模型
│   │   ├── async_writer.py     # 异步写入
│   │   └── pgn_parser.py       # .5dpgn 棋谱解析
│   └── utils/                  # 工具
│       ├── constants.py
│       └── logger.py
├── tests/                      # 单元测试
│   ├── test_engine.py
│   ├── test_move_generator.py
│   ├── test_timeline.py
│   ├── test_ai.py
│   └── test_db.py
├── sql/
│   └── schema.sql              # 数据库建表脚本
├── data/
│   └── openings.json           # 开局库数据
├── requirements.txt
└── 项目大纲.md                  # 毕业论文详细设计文档
```

---

## 🎮 操作说明

### PvP / PvE
- 点击棋子选中，再点击目标位置走子
- 绿色高亮 = 可走位置
- 时间旅行/分支走子会用特殊颜色标记
- ESC 返回主菜单

### Replay
- `◀` `▶` 逐步前进/后退
- `⏮` `⏭` 跳到开头/结尾
- `▶/⏸` 自动播放/暂停
- 点击时间线树节点切换查看分支

---

## 📊 开发进度

| 模块 | 状态 | 说明 |
|------|------|------|
| 5D核心引擎 | ✅ 完成 | 走子生成、校验、分支、跨线移动、将军/将杀 |
| PvP 模式 | ✅ 完成 | 同屏热座，完整走子流程 |
| PvE 模式 | ✅ 完成 | 三档AI，异步计算 |
| Replay 模式 | ✅ 完成 | 逐步回放、时间线切换、统计分析 |
| Pygame GUI | ✅ 完成 | 棋盘、时间线树、控制面板 |
| Web API | ✅ 完成 | Flask REST API |
| Web 前端 | 🚧 开发中 | 基础模板已完成，交互待完善 |
| MySQL 持久化 | ✅ 完成 | 异步写入，ORM模型 |
| .5dpgn 棋谱 | ✅ 完成 | 解析/导出 |
| 单元测试 | ✅ 完成 | 5个测试文件 |
| 论文文档 | 🚧 开发中 | 详见 `项目大纲.md` |

---

## 📄 许可

MIT License — 随意使用、修改、分发。

---

*🎓 本科毕业论文项目，欢迎 Star ⭐ 和 Issue 反馈。*
