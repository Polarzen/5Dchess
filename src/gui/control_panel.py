"""
5D Chess - 控制面板 GUI
"""
import pygame
from src.config import COLOR_PANEL, COLOR_TEXT, COLOR_BG


class Button:
    """按钮组件"""

    def __init__(self, x: int, y: int, width: int, height: int,
                 text: str, callback=None, color: tuple = (80, 80, 80)):
        self.rect = pygame.Rect(x, y, width, height)
        self.text = text
        self.callback = callback
        self.color = color
        self.hover_color = tuple(min(c + 40, 255) for c in color)
        self.hovered = False
        self.font = pygame.font.SysFont("arial", 14)

    def draw(self, screen: pygame.Surface):
        color = self.hover_color if self.hovered else self.color
        pygame.draw.rect(screen, color, self.rect, border_radius=4)
        pygame.draw.rect(screen, (120, 120, 120), self.rect, 1, border_radius=4)
        text_surf = self.font.render(self.text, True, COLOR_TEXT)
        text_rect = text_surf.get_rect(center=self.rect.center)
        screen.blit(text_surf, text_rect)

    def handle_event(self, event: pygame.event.Event):
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and self.hovered:
            if self.callback:
                self.callback()


class ControlPanel:
    """控制面板"""

    def __init__(self, x: int, y: int, width: int, height: int):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.buttons: list[Button] = []
        self.font = pygame.font.SysFont("arial", 14)
        self.title_font = pygame.font.SysFont("arial", 16, bold=True)
        self.info_lines: list[str] = []

    def add_button(self, text: str, callback, x_offset: int = 0, y_offset: int = 0,
                   width: int = 100, height: int = 30):
        """添加按钮"""
        btn = Button(
            self.x + 10 + x_offset,
            self.y + 40 + y_offset,
            width, height,
            text, callback,
        )
        self.buttons.append(btn)
        return btn

    def set_info(self, lines: list[str]):
        self.info_lines = lines

    def draw(self, screen: pygame.Surface):
        """绘制控制面板"""
        # 背景
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        pygame.draw.rect(screen, COLOR_PANEL, panel_rect)
        pygame.draw.rect(screen, (80, 80, 80), panel_rect, 1)

        # 标题
        title = self.title_font.render("控制面板", True, COLOR_TEXT)
        screen.blit(title, (self.x + 10, self.y + 5))

        # 按钮
        for btn in self.buttons:
            btn.draw(screen)

        # 信息
        y_offset = self.y + 80
        for line in self.info_lines:
            text = self.font.render(line, True, COLOR_TEXT)
            screen.blit(text, (self.x + 10, y_offset))
            y_offset += 20

    def handle_event(self, event: pygame.event.Event):
        for btn in self.buttons:
            btn.handle_event(event)

    def clear_buttons(self):
        self.buttons.clear()