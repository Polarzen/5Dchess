"""
5D Chess - GUI 棋盘视图
"""
import pygame
from src.config import (
    BOARD_SIZE, CELL_SIZE, COLOR_WHITE, COLOR_BLACK,
    COLOR_SELECTED, COLOR_VALID_MOVE, COLOR_CHECK, COLOR_BG,
    WINDOW_WIDTH, WINDOW_HEIGHT, FPS
)
from src.utils.constants import ChessColor, PieceType, PIECE_SYMBOLS
from src.engine.board import Position
from src.engine.move_generator import Move


class BoardView:
    """棋盘视图组件"""

    def __init__(self, x: int = 0, y: int = 0, size: int = 640):
        self.x = x
        self.y = y
        self.size = size
        self.cell_size = size // BOARD_SIZE
        self.font = pygame.font.SysFont("segoeuisymbol", self.cell_size - 4)
        self.small_font = pygame.font.SysFont("arial", 14)
        self.selected_square: tuple[int, int] | None = None
        self.valid_moves: list[tuple[int, int]] = []
        self.check_square: tuple[int, int] | None = None
        self.timeline_id: int = 0
        self.time_point: int = 0

    def draw(self, screen: pygame.Surface, board: list[list[str]], turn: str = "white"):
        """绘制棋盘"""
        self._draw_board(screen)
        self._draw_pieces(screen, board)
        self._draw_highlights(screen)
        self._draw_info(screen, turn)

    def _draw_board(self, screen: pygame.Surface):
        """绘制棋盘格子"""
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                rect = pygame.Rect(
                    self.x + col * self.cell_size,
                    self.y + row * self.cell_size,
                    self.cell_size,
                    self.cell_size,
                )
                color = COLOR_WHITE if (row + col) % 2 == 0 else COLOR_BLACK
                pygame.draw.rect(screen, color, rect)

    def _draw_pieces(self, screen: pygame.Surface, board: list[list[str]]):
        """绘制棋子"""
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                ch = board[row][col]
                if not ch:
                    continue
                from src.engine.piece import piece_from_char
                piece = piece_from_char(ch)
                if piece is None:
                    continue

                symbol = piece.symbol
                text = self.font.render(symbol, True, (0, 0, 0))
                text_rect = text.get_rect(center=(
                    self.x + col * self.cell_size + self.cell_size // 2,
                    self.y + row * self.cell_size + self.cell_size // 2,
                ))
                screen.blit(text, text_rect)

    def _draw_highlights(self, screen: pygame.Surface):
        """绘制高亮"""
        # 选中格子
        if self.selected_square:
            sx, sy = self.selected_square
            rect = pygame.Rect(
                self.x + sx * self.cell_size,
                self.y + sy * self.cell_size,
                self.cell_size, self.cell_size,
            )
            pygame.draw.rect(screen, COLOR_SELECTED, rect, 3)

        # 合法走子目标
        for tx, ty in self.valid_moves:
            cx = self.x + tx * self.cell_size + self.cell_size // 2
            cy = self.y + ty * self.cell_size + self.cell_size // 2
            radius = self.cell_size // 6
            pygame.draw.circle(screen, COLOR_VALID_MOVE, (cx, cy), radius)

        # 将军高亮
        if self.check_square:
            kx, ky = self.check_square
            rect = pygame.Rect(
                self.x + kx * self.cell_size,
                self.y + ky * self.cell_size,
                self.cell_size, self.cell_size,
            )
            pygame.draw.rect(screen, COLOR_CHECK, rect, 4)

    def _draw_info(self, screen: pygame.Surface, turn: str):
        """绘制信息栏"""
        info_y = self.y + self.size + 10
        turn_text = self.small_font.render(
            f"Turn: {turn} | Timeline: T{self.timeline_id} | t={self.time_point}",
            True, (220, 220, 220)
        )
        screen.blit(turn_text, (self.x, info_y))

    def handle_click(self, mouse_x: int, mouse_y: int) -> tuple[int, int] | None:
        """处理鼠标点击，返回棋盘坐标"""
        col = (mouse_x - self.x) // self.cell_size
        row = (mouse_y - self.y) // self.cell_size
        if 0 <= col < BOARD_SIZE and 0 <= row < BOARD_SIZE:
            return (col, row)
        return None

    def set_selection(self, square: tuple[int, int] | None, valid_moves: list[tuple[int, int]]):
        self.selected_square = square
        self.valid_moves = valid_moves

    def set_check(self, square: tuple[int, int] | None):
        self.check_square = square