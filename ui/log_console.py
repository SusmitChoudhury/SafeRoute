"""
ui/log_console.py – Scrolling colored algorithm log panel.

Renders the SimLogger's ring buffer with exact level coloring:
  INFO   (blue)
  CALC   (yellow)
  ROUTE  (green)
  WARN   (orange)
  ALERT  (red)
  ERROR  (magenta)

Supports mouse wheel scrolling and auto-scroll to latest lines.
"""

from typing import Optional
import pygame

from sim.logger import LOG_COLORS, SimLogger

COLOR_CONSOLE_BG = (15, 23, 42)      # Deep modern navy slate (#0f172a)
COLOR_BORDER = (51, 65, 85)          # Slate border (#334155)
COLOR_SCROLLBAR = (30, 41, 59)
COLOR_SCROLL_THUMB = (100, 116, 139)


class LogConsole:
    """Scrollable, syntax-colored algorithm console view."""

    def __init__(self, rect: pygame.Rect, logger: SimLogger, line_height: int = 25):
        self.rect = rect
        self.logger = logger
        self.line_height = line_height

        self.font: Optional[pygame.font.Font] = None
        self.scroll_offset = 0  # Number of lines scrolled up from bottom
        self.auto_scroll = True
        self._init_font()

    def _init_font(self) -> None:
        if not pygame.font.get_init():
            pygame.font.init()
        # High-visibility 16px bold monospace for crisp recording and screenshots
        self.font = pygame.font.SysFont("Consolas, 'Cascadia Code', 'Fira Code', monospace", 16, bold=True)

    def handle_scroll(self, dy: int) -> None:
        """Handle mouse wheel scroll events (dy > 0: scroll up, dy < 0: scroll down)."""
        self.scroll_offset = max(0, self.scroll_offset + dy * 3)
        if dy < 0 and self.scroll_offset == 0:
            self.auto_scroll = True
        else:
            self.auto_scroll = False

    def draw(self, surface: pygame.Surface) -> None:
        """Render the console and colored log lines onto the surface."""
        # Background and frame
        pygame.draw.rect(surface, COLOR_CONSOLE_BG, self.rect)
        pygame.draw.rect(surface, COLOR_BORDER, self.rect, 1)

        lines = self.logger.lines()
        if not lines or self.font is None:
            return

        visible_line_count = (self.rect.height - 12) // self.line_height
        total_lines = len(lines)

        if self.auto_scroll:
            start_idx = max(0, total_lines - visible_line_count)
            end_idx = total_lines
        else:
            end_idx = max(visible_line_count, total_lines - self.scroll_offset)
            end_idx = min(total_lines, end_idx)
            start_idx = max(0, end_idx - visible_line_count)

        # Clip drawing to console boundary
        surface.set_clip(self.rect)

        y = self.rect.y + 6
        for i in range(start_idx, end_idx):
            level, text = lines[i]
            color = LOG_COLORS.get(level, (220, 220, 220))
            rendered_line = self.font.render(text, True, color)
            surface.blit(rendered_line, (self.rect.x + 8, y))
            y += self.line_height

        # Draw scrollbar if content exceeds visible area
        if total_lines > visible_line_count:
            sb_x = self.rect.right - 8
            sb_y = self.rect.y + 4
            sb_h = self.rect.height - 8
            pygame.draw.rect(surface, COLOR_SCROLLBAR, (sb_x, sb_y, 4, sb_h), border_radius=2)

            thumb_h = max(20, int(sb_h * (visible_line_count / total_lines)))
            thumb_ratio = (start_idx / (total_lines - visible_line_count)) if total_lines > visible_line_count else 0
            thumb_y = sb_y + int(thumb_ratio * (sb_h - thumb_h))
            pygame.draw.rect(surface, COLOR_SCROLL_THUMB, (sb_x, thumb_y, 4, thumb_h), border_radius=2)

        surface.set_clip(None)
