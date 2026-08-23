"""
5D Chess - 时间线树可视化（Canvas自绘）
"""
import pygame
from src.config import COLOR_BG, COLOR_PANEL, COLOR_TEXT


class TimelineTreeView:
    """时间线树可视化组件"""

    def __init__(self, x: int, y: int, width: int, height: int):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.font = pygame.font.SysFont("arial", 14)
        self.title_font = pygame.font.SysFont("arial", 16, bold=True)
        self.tree_data: dict | None = None
        self.selected_id: int = 0
        self._node_positions: dict[int, tuple[int, int]] = {}
        self._node_rects: dict[int, pygame.Rect] = {}

    def set_tree(self, tree_data: dict):
        """设置树数据"""
        self.tree_data = tree_data
        self._calculate_layout()

    def set_selected(self, timeline_id: int):
        self.selected_id = timeline_id

    def _calculate_layout(self):
        """计算节点布局"""
        self._node_positions.clear()
        self._node_rects.clear()
        if not self.tree_data:
            return

        def layout(node: dict, x: int, y: int, depth: int) -> int:
            """递归布局，返回子树宽度"""
            node_id = node["id"]
            node_width = 80
            node_height = 30
            spacing_x = 20
            spacing_y = 50

            if not node.get("children"):
                nx = x
                ny = y
                self._node_positions[node_id] = (nx, ny)
                self._node_rects[node_id] = pygame.Rect(
                    self.x + nx, self.y + ny, node_width, node_height
                )
                return node_width

            # 先布局子节点
            child_widths = []
            total_children_width = 0
            for child in node["children"]:
                cw = layout(child, 0, y + spacing_y, depth + 1)
                child_widths.append(cw)
                total_children_width += cw + spacing_x

            total_children_width -= spacing_x if child_widths else 0

            # 父节点居中
            nx = x + (total_children_width - node_width) // 2 if total_children_width > node_width else x
            self._node_positions[node_id] = (nx, y)
            self._node_rects[node_id] = pygame.Rect(
                self.x + nx, self.y + y, node_width, node_height
            )

            return max(total_children_width, node_width)

        layout(self.tree_data, 10, 10, 0)

    def draw(self, screen: pygame.Surface):
        """绘制时间线树"""
        # 背景面板
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        pygame.draw.rect(screen, COLOR_PANEL, panel_rect)
        pygame.draw.rect(screen, (80, 80, 80), panel_rect, 1)

        # 标题
        title = self.title_font.render("时间线树", True, COLOR_TEXT)
        screen.blit(title, (self.x + 10, self.y + 5))

        if not self.tree_data:
            text = self.font.render("(无分支)", True, (150, 150, 150))
            screen.blit(text, (self.x + 10, self.y + 30))
            return

        # 绘制连线
        self._draw_edges(screen)

        # 绘制节点
        self._draw_nodes(screen)

    def _draw_edges(self, screen: pygame.Surface):
        """绘制分支连线"""
        if not self.tree_data:
            return

        def draw_edges_rec(node: dict):
            node_id = node["id"]
            if node_id not in self._node_rects:
                return
            parent_rect = self._node_rects[node_id]

            for child in node.get("children", []):
                child_id = child["id"]
                if child_id not in self._node_rects:
                    continue
                child_rect = self._node_rects[child_id]

                start = (parent_rect.centerx, parent_rect.bottom)
                end = (child_rect.centerx, child_rect.top)

                color = (100, 200, 100) if child.get("is_active") else (150, 150, 150)
                pygame.draw.line(screen, color, start, end, 2)

                draw_edges_rec(child)

        draw_edges_rec(self.tree_data)

    def _draw_nodes(self, screen: pygame.Surface):
        """绘制节点"""
        if not self.tree_data:
            return

        def draw_nodes_rec(node: dict):
            node_id = node["id"]
            if node_id not in self._node_rects:
                return
            rect = self._node_rects[node_id]

            # 节点颜色
            if node_id == self.selected_id:
                node_color = (80, 180, 80)
            elif node.get("is_active"):
                node_color = (100, 140, 100)
            else:
                node_color = (100, 100, 100)

            pygame.draw.rect(screen, node_color, rect, border_radius=5)
            pygame.draw.rect(screen, (200, 200, 200), rect, 1, border_radius=5)

            # 节点名称
            text = self.font.render(node.get("name", f"T{node_id}"), True, COLOR_TEXT)
            text_rect = text.get_rect(center=rect.center)
            screen.blit(text, text_rect)

            for child in node.get("children", []):
                draw_nodes_rec(child)

        draw_nodes_rec(self.tree_data)

    def handle_click(self, mouse_x: int, mouse_y: int) -> int | None:
        """处理点击，返回点击的时间线ID"""
        for tid, rect in self._node_rects.items():
            if rect.collidepoint(mouse_x, mouse_y):
                return tid
        return None