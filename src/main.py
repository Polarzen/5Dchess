"""
5D Chess - 主入口
使用方式:
    python src/main.py                  # 启动GUI
    python src/main.py --cli            # 命令行模式
    python src/main.py --replay <file>  # 直接加载棋谱回放
    python src/main.py --test           # 运行测试
"""
import sys
import os
from pathlib import Path

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from src.utils.logger import logger


def main():
    parser = argparse.ArgumentParser(description="5D Chess - 五维国际象棋")
    parser.add_argument("--cli", action="store_true", help="命令行模式")
    parser.add_argument("--web", action="store_true", help="Web模式 (Flask)")
    parser.add_argument("--replay", type=str, help="加载棋谱文件回放")
    parser.add_argument("--pvp", action="store_true", help="直接启动PvP模式")
    parser.add_argument("--pve", type=str, choices=["easy", "medium", "hard"],
                       help="直接启动PvE模式")
    parser.add_argument("--test", action="store_true", help="运行单元测试")
    args = parser.parse_args()

    if args.test:
        run_tests()
    elif args.cli:
        run_cli(args)
    elif args.web:
        run_web()
    elif args.replay:
        run_replay_from_file(args.replay)
    elif args.pvp:
        run_gui("pvp")
    elif args.pve:
        run_gui("pve", difficulty=args.pve)
    else:
        run_web()


def run_gui(mode: str = None, difficulty: str = "medium"):
    """启动GUI模式"""
    from src.gui import ChessApp
    app = ChessApp()
    logger.info("5D Chess GUI 启动")
    app.run()


def run_web(host: str = "127.0.0.1", port: int = 5000):
    """启动Web模式"""
    from src.web import run_server
    run_server(host=host, port=port)


def run_cli(args):
    """命令行模式（用于测试）"""
    from src.engine import FiveDEngine
    from src.utils.constants import ChessColor

    engine = FiveDEngine()
    print("=" * 50)
    print("5D Chess - 命令行模式")
    print("=" * 50)

    while engine.game_state.value == "playing":
        pos = engine.get_current_position()
        print(f"\n回合: {engine.move_counter + 1} | {pos.turn.value}方走棋")
        print(f"时间线: T{pos.timeline_id} | 时间点: t={pos.time_point}")
        print_board(pos.board)

        moves = engine.get_legal_moves()
        if not moves:
            print("无合法走子！")
            break

        print(f"\n合法走子 ({len(moves)}):")
        for i, move in enumerate(moves[:20]):
            print(f"  [{i}] {move.to_notation()}")

        if len(moves) > 20:
            print(f"  ... 还有 {len(moves) - 20} 个走子")

        try:
            choice = input("\n选择走子编号 (q=退出): ").strip()
            if choice.lower() == "q":
                break
            idx = int(choice)
            if 0 <= idx < len(moves):
                engine.execute_move(moves[idx])
            else:
                print("无效选择")
        except (ValueError, IndexError):
            print("无效输入")

    print(f"\n游戏结束: {engine.game_state.name}")
    print(engine.get_game_summary())


def run_replay_from_file(filepath: str):
    """从文件加载棋谱并回放（GUI模式）"""
    from src.gui import ChessApp
    from src.data.pgn_parser import FiveDPGN
    from src.engine import FiveDEngine
    from src.modes import ReplayMode

    moves, tl_mgr = FiveDPGN.load(filepath)
    if moves is None:
        logger.error(f"无法加载棋谱: {filepath}")
        return

    app = ChessApp()
    app.current_mode = "replay"
    app.mode_instance = ReplayMode()
    app.mode_instance.load_from_moves(moves, tl_mgr)
    app.mode_instance.start()
    app._update_board_state()
    app._setup_replay_controls()
    app.run()


def run_tests():
    """运行单元测试"""
    import pytest
    import os
    test_dir = os.path.join(os.path.dirname(__file__), "..", "tests")
    sys.exit(pytest.main([test_dir, "-v"]))


def print_board(board: list[list[str]]):
    """打印棋盘（命令行）"""
    print("  ┌───┬───┬───┬───┬───┬───┬───┬───┐")
    for y, row in enumerate(board):
        print(f"{8 - y} │", end="")
        for ch in row:
            from src.engine.piece import piece_from_char
            piece = piece_from_char(ch)
            symbol = piece.symbol if piece else " "
            print(f" {symbol} │", end="")
        print(f" {8 - y}")
        if y < 7:
            print("  ├───┼───┼───┼───┼───┼───┼───┼───┤")
    print("  └───┴───┴───┴───┴───┴───┴───┴───┘")
    print("    a   b   c   d   e   f   g   h")


if __name__ == "__main__":
    main()