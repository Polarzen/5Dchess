"""
5D Chess - GUI 主程序
三模式集成：PvP / PvE / Replay
"""
import sys
import pygame
from src.config import (
    WINDOW_TITLE, WINDOW_WIDTH, WINDOW_HEIGHT, FPS,
    COLOR_BG, COLOR_TEXT, COLOR_PANEL, BOARD_SIZE, BOARD_VIEW_SIZE,
    TIMELINE_TREE_WIDTH, CELL_SIZE,
)
from src.utils.constants import ChessColor, GameState, PieceType
from src.utils.logger import logger
from src.engine.piece import piece_from_char
from src.engine.engine import FiveDEngine
from src.modes import PvPMode, PvEMode, ReplayMode
from src.gui.board_view import BoardView
from src.gui.timeline_tree import TimelineTreeView
from src.gui.control_panel import ControlPanel


class ChessApp:
    """5D Chess GUI 主应用"""

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        pygame.display.set_caption(WINDOW_TITLE)
        self.clock = pygame.time.Clock()
        self.running = False

        # 模式
        self.current_mode = None  # "pvp" | "pve" | "replay"
        self.mode_instance = None

        # 组件
        board_x = 20
        board_y = 20
        self.board_view = BoardView(board_x, board_y, BOARD_VIEW_SIZE)

        tree_x = board_x + BOARD_VIEW_SIZE + 20
        tree_y = board_y
        tree_height = WINDOW_HEIGHT - 140
        self.tree_view = TimelineTreeView(tree_x, tree_y, TIMELINE_TREE_WIDTH, tree_height)

        panel_x = board_x
        panel_y = board_y + BOARD_VIEW_SIZE + 50
        panel_width = BOARD_VIEW_SIZE + TIMELINE_TREE_WIDTH + 20
        panel_height = 120
        self.control_panel = ControlPanel(panel_x, panel_y, panel_width, panel_height)

        # 字体
        self.font = pygame.font.SysFont("arial", 18)
        self.big_font = pygame.font.SysFont("arial", 24, bold=True)

        # 状态
        self._init_mode_buttons()

    def _init_mode_buttons(self):
        """初始化模式选择按钮"""
        self.mode_buttons = {
            "pvp": pygame.Rect(300, 400, 200, 50),
            "pve_easy": pygame.Rect(300, 470, 200, 50),
            "pve_medium": pygame.Rect(300, 540, 200, 50),
            "pve_hard": pygame.Rect(300, 610, 200, 50),
            "replay": pygame.Rect(300, 680, 200, 50),
        }

    def run(self):
        """主循环"""
        self.running = True
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                self._handle_event(event)

            # Replay 自动播放
            if self.current_mode == "replay" and self.mode_instance:
                self.mode_instance.update(dt)

            self._draw()
            pygame.display.flip()

        pygame.quit()
        sys.exit()

    def _handle_event(self, event: pygame.event.Event):
        """处理事件"""
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.current_mode is None:
                self._handle_mode_selection(event.pos)
            elif self.current_mode == "pvp":
                self._handle_pvp_click(event.pos)
            else:
                self._handle_tree_click(event.pos)
                self._handle_panel_event(event)

        elif event.type == pygame.KEYDOWN:
            self._handle_key(event.key)

        self.control_panel.handle_event(event)

    def _handle_mode_selection(self, pos):
        """处理模式选择"""
        for mode, rect in self.mode_buttons.items():
            if rect.collidepoint(pos):
                if mode == "pvp":
                    self._start_pvp()
                elif mode.startswith("pve"):
                    difficulty = mode.split("_")[1]
                    self._start_pve(difficulty)
                elif mode == "replay":
                    self._start_replay()

    def _handle_pvp_click(self, pos):
        """处理PvP棋盘点击"""
        sq = self.board_view.handle_click(*pos)
        if sq is None:
            return
        result = self.mode_instance.select_square(*sq)
        self._update_board_state()

    def _handle_tree_click(self, pos):
        """处理时间线树点击"""
        tid = self.tree_view.handle_click(*pos)
        if tid is not None and self.mode_instance:
            if hasattr(self.mode_instance, "select_timeline"):
                self.mode_instance.select_timeline(tid)
                self._update_board_state()

    def _handle_panel_event(self, event):
        """处理面板事件"""
        self.control_panel.handle_event(event)

    def _handle_key(self, key):
        """处理键盘"""
        if self.current_mode == "replay":
            if key == pygame.K_LEFT:
                self.mode_instance.step_backward()
            elif key == pygame.K_RIGHT:
                self.mode_instance.step_forward()
            elif key == pygame.K_SPACE:
                self.mode_instance.toggle_play()
            elif key == pygame.K_HOME:
                self.mode_instance.jump_to_start()
            elif key == pygame.K_END:
                self.mode_instance.jump_to_end()
            self._update_board_state()
        elif key == pygame.K_ESCAPE:
            self._back_to_menu()

    def _start_pvp(self):
        """启动PvP模式"""
        logger.info("启动PvP模式")
        engine = FiveDEngine()
        self.mode_instance = PvPMode(engine)
        self.mode_instance.start()
        self.current_mode = "pvp"
        self._setup_pvp_controls()
        self._update_board_state()

    def _start_pve(self, difficulty: str):
        """启动PvE模式"""
        logger.info(f"启动PvE模式 (AI: {difficulty})")
        engine = FiveDEngine()
        self.mode_instance = PvEMode(engine, player_color=ChessColor.WHITE, ai_difficulty=difficulty)
        self.mode_instance.on("ai_thinking", lambda thinking: self._update_board_state())
        self.mode_instance.on("ai_move_ready", lambda move, apply: (
            apply(),
            self._update_board_state()
        ))
        self.mode_instance.start()
        self.current_mode = "pve"
        self._setup_pve_controls()
        self._update_board_state()

    def _start_replay(self):
        """启动Replay模式"""
        logger.info("启动Replay模式")
        engine = FiveDEngine()
        self.mode_instance = ReplayMode(engine)
        self.mode_instance.start()
        self.current_mode = "replay"
        self._setup_replay_controls()
        self._update_board_state()

    def _setup_pvp_controls(self):
        """设置PvP控制面板"""
        self.control_panel.clear_buttons()
        self.control_panel.add_button("返回菜单", self._back_to_menu, y_offset=0)

    def _setup_pve_controls(self):
        """设置PvE控制面板"""
        self.control_panel.clear_buttons()
        self.control_panel.add_button("返回菜单", self._back_to_menu, y_offset=0)

    def _setup_replay_controls(self):
        """设置Replay控制面板"""
        self.control_panel.clear_buttons()
        self.control_panel.add_button("⏮", lambda: self._replay_action("start"), y_offset=0, width=50)
        self.control_panel.add_button("◀", lambda: self._replay_action("back"), x_offset=55, y_offset=0, width=50)
        self.control_panel.add_button("▶/⏸", lambda: self._replay_action("toggle"), x_offset=110, y_offset=0, width=60)
        self.control_panel.add_button("▶", lambda: self._replay_action("forward"), x_offset=175, y_offset=0, width=50)
        self.control_panel.add_button("⏭", lambda: self._replay_action("end"), x_offset=230, y_offset=0, width=50)
        self.control_panel.add_button("返回菜单", self._back_to_menu, x_offset=290, y_offset=0)

    def _replay_action(self, action: str):
        """Replay控制动作"""
        if not self.mode_instance:
            return
        actions = {
            "start": self.mode_instance.jump_to_start,
            "back": self.mode_instance.step_backward,
            "forward": self.mode_instance.step_forward,
            "end": self.mode_instance.jump_to_end,
            "toggle": self.mode_instance.toggle_play,
        }
        if action in actions:
            actions[action]()
        self._update_board_state()

    def _update_board_state(self):
        """更新棋盘显示"""
        if not self.mode_instance:
            return

        if self.current_mode == "pvp":
            state = self.mode_instance.get_board_state()
            board = state["board"]
            self.board_view.timeline_id = state["timeline_id"]
            self.board_view.time_point = state["time_point"]

            # 检查将军
            pos = self.mode_instance.engine.get_current_position()
            king_pos = pos.find_king(pos.turn)
            from src.engine.move_validator import MoveValidator
            validator = MoveValidator()
            if validator.is_king_in_check(pos, pos.turn):
                self.board_view.set_check(king_pos)
            else:
                self.board_view.set_check(None)

            # 更新选中
            sel = self.mode_instance.selected_piece
            valid = [(m["x"], m["y"]) for m in state.get("valid_moves", [])] if sel else []
            self.board_view.set_selection(sel, valid)

            self.control_panel.set_info([
                f"模式: PvP | 回合: {state['total_moves']}",
                f"当前: {state['turn']} | 时间线: {state['total_timelines']}",
                f"状态: {state['game_state']}",
            ])

        elif self.current_mode == "pve":
            state = self.mode_instance.get_board_state()
            board = state["board"]
            self.board_view.timeline_id = state["timeline_id"]
            self.board_view.time_point = state["time_point"]

            self.control_panel.set_info([
                f"模式: PvE ({state['ai_difficulty']}) | 回合: {state['total_moves']}",
                f"AI思考中..." if state.get("ai_thinking") else f"轮到你了: {state['turn']}",
                f"状态: {state['game_state']}",
            ])

        elif self.current_mode == "replay":
            stats = self.mode_instance.get_statistics()
            board = self.mode_instance.get_current_board()
            self.board_view.timeline_id = self.mode_instance.selected_timeline_id

            self.control_panel.set_info([
                f"回放: {stats['current_index']}/{stats['total_moves']} | "
                f"{'▶ 播放中' if self.mode_instance.is_playing else '⏸ 暂停'}",
                f"时间线: {stats['total_timelines']} | 分支: {stats['branching_moves']} | "
                f"跨线: {stats['cross_timeline_moves']}",
                f"状态: {stats['result']}",
            ])

        # 更新时间线树
        tree = self.mode_instance.engine.timeline_manager.build_tree()
        self.tree_view.set_tree(tree)
        if self.current_mode == "replay":
            self.tree_view.set_selected(self.mode_instance.selected_timeline_id)

        # 绘制棋盘
        self.board_view.draw(self.screen, board, self._get_current_turn())

    def _get_current_turn(self) -> str:
        """获取当前走子方"""
        if self.mode_instance and hasattr(self.mode_instance, "engine"):
            return self.mode_instance.engine.current_turn_color.value
        return "white"

    def _back_to_menu(self):
        """返回主菜单"""
        self.current_mode = None
        self.mode_instance = None
        self.board_view.set_selection(None, [])
        self.board_view.set_check(None)
        self.control_panel.clear_buttons()
        self.tree_view.set_tree({})

    def _draw(self):
        """绘制所有内容"""
        self.screen.fill(COLOR_BG)

        if self.current_mode is None:
            self._draw_menu()
        else:
            self.board_view.draw(self.screen, self._get_board(), self._get_current_turn())
            self.tree_view.draw(self.screen)
            self.control_panel.draw(self.screen)

    def _draw_menu(self):
        """绘制主菜单"""
        # 标题
        title = self.big_font.render("5D Chess - 五维国际象棋", True, COLOR_TEXT)
        title_rect = title.get_rect(center=(WINDOW_WIDTH // 2, 150))
        self.screen.blit(title, title_rect)

        subtitle = self.font.render("Multiverse Time Travel", True, (180, 180, 180))
        sub_rect = subtitle.get_rect(center=(WINDOW_WIDTH // 2, 190))
        self.screen.blit(subtitle, sub_rect)

        # 模式按钮
        button_texts = [
            ("pvp", "真人对弈 (PvP)", (100, 200, 100)),
            ("pve_easy", "人机对弈 - 简单", (100, 150, 200)),
            ("pve_medium", "人机对弈 - 中等", (100, 150, 200)),
            ("pve_hard", "人机对弈 - 困难", (100, 150, 200)),
            ("replay", "棋谱回放 (Replay)", (200, 150, 100)),
        ]

        for mode, text, color in button_texts:
            rect = self.mode_buttons[mode]
            pygame.draw.rect(self.screen, color, rect, border_radius=8)
            pygame.draw.rect(self.screen, (255, 255, 255), rect, 2, border_radius=8)
            text_surf = self.font.render(text, True, (255, 255, 255))
            text_rect = text_surf.get_rect(center=rect.center)
            self.screen.blit(text_surf, text_rect)

        # 提示
        hint = self.font.render("点击选择模式开始游戏 | ESC 返回菜单", True, (150, 150, 150))
        hint_rect = hint.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT - 50))
        self.screen.blit(hint, hint_rect)

    def _get_board(self) -> list[list[str]]:
        """获取当前棋盘数据"""
        if not self.mode_instance:
            return [[]]
        try:
            if self.current_mode == "replay":
                return self.mode_instance.get_current_board()
            else:
                state = self.mode_instance.get_board_state()
                return state.get("board", [[]])
        except Exception:
            return [[]]