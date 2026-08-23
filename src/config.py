"""
5D Chess - 全局配置
"""
import os
from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).resolve().parent.parent

# 数据库配置
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "chess_5d"),
    "charset": "utf8mb4",
    "autocommit": False,
}

# 异步写入配置
ASYNC_WRITE_INTERVAL = 0.5          # 批量写入间隔(秒)
ASYNC_QUEUE_MAXSIZE = 10000         # 队列最大容量

# 游戏配置
DEFAULT_MAX_TIMELINES = 32          # 最大活跃时间线数
DEFAULT_MAX_TURNS = 500             # 最大回合数
BOARD_SIZE = 8                      # 棋盘大小

# AI 配置
AI_CONFIG = {
    "easy": {"search_depth": 0},    # 随机
    "medium": {"search_depth": 2},  # Alpha-Beta 浅搜索
    "hard": {"search_depth": 4},    # Alpha-Beta 深搜索
}

AI_TIMEOUT = 5.0                    # AI 思考超时(秒)

# GUI 配置
WINDOW_TITLE = "5D Chess - 五维国际象棋"
WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900
BOARD_VIEW_SIZE = 640               # 棋盘视图边长
CELL_SIZE = BOARD_VIEW_SIZE // BOARD_SIZE
TIMELINE_TREE_WIDTH = 350
FPS = 60

# 颜色
COLOR_WHITE = (240, 217, 181)
COLOR_BLACK = (181, 136, 99)
COLOR_SELECTED = (255, 255, 100)
COLOR_VALID_MOVE = (100, 200, 100)
COLOR_CHECK = (255, 80, 80)
COLOR_BG = (40, 40, 40)
COLOR_TEXT = (220, 220, 220)
COLOR_PANEL = (50, 50, 50)

# 日志
LOG_DIR = ROOT_DIR / "logs"
LOG_LEVEL = "INFO"