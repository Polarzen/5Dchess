# 5D Chess with Multiverse Time Travel
# 五维国际象棋 - 复刻版

> 计算机科学与技术本科毕业论文 | Python + MySQL | 三模式系统

## 项目简介

复刻 Steam 游戏 "5D Chess with Multiverse Time Travel"，在传统二维国际象棋基础上引入**时间**和**平行时间线**维度，形成五维棋类系统。

- **X轴**：棋盘列 (a-h)
- **Y轴**：棋盘行 (1-8)
- **时间**：同一时间线内前后移动
- **平行时间线**：向过去走子产生分支
- **跨时间线移动**：棋子在不同时间线间跳跃

## 三模式系统

| 模式 | 说明 |
|------|------|
| PvP | 同屏热座真人对弈 |
| PvE | 人机对弈（三档AI难度） |
| Replay | 棋谱回放与分析（答辩核心） |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 初始化数据库
mysql -u root -p < sql/schema.sql

# 运行
python src/main.py
```

## 项目结构

```
5D_Chess/
├── src/
│   ├── engine/    # 5D核心引擎
│   ├── modes/     # 游戏模式(PvP/PvE/Replay)
│   ├── ai/        # AI引擎
│   ├── gui/       # 图形界面
│   ├── data/      # 数据持久化
│   └── utils/     # 工具
├── tests/         # 单元测试
├── sql/           # 数据库脚本
└── data/          # 开局库/示例棋谱
```