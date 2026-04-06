import math
import json
import os
import time
from typing import Optional, Set

from PySide6.QtCore import Qt, Signal, QPointF, QTimer, QUrl
from PySide6.QtGui import (
    QKeyEvent, QMouseEvent, QPainter, QColor, QFont, QImage,
    QPen, QPolygonF, QRadialGradient, QSurfaceFormat,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QApplication, QMainWindow

from core.game_core import GameCore
from core.performance_monitor import PerformanceMonitor
from .renderer_opengl import OpenGLRenderer
from .silhouette_minigame import SilhouetteMatchDialog
from .assembly3d_minigame import Assembly3DMinigame

FPS_CAMERA_SENSITIVITY = 0.002


class GameGLWidget(QOpenGLWidget):

    mouse_moved = Signal(float, float)

    def __init__(self, core: GameCore, performance_monitor: PerformanceMonitor):
        fmt = QSurfaceFormat()
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setVersion(3, 3)
        fmt.setRenderableType(QSurfaceFormat.OpenGL)
        fmt.setSamples(4)

        super().__init__()
        self.setFormat(fmt)

        self.core = core
        self.renderer = OpenGLRenderer(core)

        self.performance_monitor = performance_monitor

        self._pause_btn_rects: dict[str, tuple[int, int, int, int]] = {}

        self._hud_font = QFont('Arial', 10)
        self._hud_font_bold = QFont('Arial', 11)
        self._hud_font_bold.setBold(True)

        self._cam_icon = QImage('assets/cam.jpg')
        self._cam_icon_rect = (0, 0, 0, 0)
        self._minimap_until = 0.0
        self._minimap_cooldown_until = 0.0

        self._modal_visible = False
        self._modal_kind: str = ''
        self._modal_title: str = ''
        self._modal_body: str = ''
        self._modal_btn_rects: dict[str, tuple[int, int, int, int]] = {}
        self._modal_allow_close = True
        self._modal_return_to_pause = False

        self._level_select_unlocked: set[str] = {'level1'}

        self._lore_queue: list[str] = []
        self._lore_current: str = ''
        self._lore_current_start = 0.0
        self._lore_current_end = 0.0

        self._time_bonus_text: str = ''
        self._time_bonus_until: float = 0.0

        self._flash_until: float = 0.0
        self._flash_color: QColor = QColor(20, 20, 25, 180)

        self._show_the_end: bool = False
        self._stats_text: str = ''
        self._stats_visible: bool = False
        self._end_screen_visible: bool = False

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._mouse_captured = False
        self._center_global = None

        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self.update)
        self._render_timer.start(16)

    def initializeGL(self) -> None:
        if self.performance_monitor.startup_time_ms is None:
            startup_ms = (time.perf_counter() -
                          self.performance_monitor._startup_begin) * 1000
            self.performance_monitor.record_startup_time(startup_ms)
        self.renderer.initialize()

    def resizeGL(self, w: int, h: int) -> None:
        self.renderer.resize(w, h)

    def _safe_update(self) -> None:
        try:
            self.update()
        except Exception:
            pass

    def paintGL(self) -> None:
        self.renderer.render()
        self._update_scene_performance_data()
        if self.core.screen_closing or self.core.game_completed:
            self._draw_screen_close_animation()

        if not (self.core.paused or self._stats_visible or self._show_the_end):
            self.performance_monitor.record_frame()
        else:
            self.performance_monitor.record_frame(is_pause_frame=True)

    def _update_scene_performance_data(self) -> None:
        self.performance_monitor.update_scene_data(
            walls_rendered=len(self.core.walls),
            coins=len(self.core.coins),
            ghosts=len(self.core.ghosts),
            spike_traps=len(self.core.spikes),
            moving_platforms=len(self.core.platforms),
        )
        if self.performance_monitor.resolution == (0, 0):
            self.performance_monitor.set_resolution(
                self.width(), self.height())

    def _draw_screen_close_animation(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        progress = self.core.screen_close_progress

        if progress < 1.0:
            bar_h = int(h * progress * 0.5)
            painter.fillRect(0, 0, w, bar_h, QColor(0, 0, 0))
            painter.fillRect(0, h - bar_h, w, bar_h, QColor(0, 0, 0))
        else:
            painter.fillRect(0, 0, w, h, QColor(0, 0, 0))

            if self._show_the_end:
                painter.setPen(QColor(255, 255, 255))
                painter.setFont(QFont('Arial', 68, QFont.Bold))
                painter.drawText(0, 0, w, h, Qt.AlignCenter, 'THE END')
                painter.setPen(QColor(150, 150, 150))
                painter.setFont(QFont('Arial', 13))
                painter.drawText(0, h - 46, w, 30,
                                 Qt.AlignCenter, 'Press ESC to continue')
            else:
                stats = self._stats_text
                if stats:
                    lines = [ln.rstrip() for ln in stats.split('\n')]
                    while lines and not lines[0]:
                        lines.pop(0)
                    while lines and not lines[-1]:
                        lines.pop()

                    usable_h = h - 80
                    ideal_line_h = 26
                    line_h = min(ideal_line_h, max(
                        14, usable_h // max(1, len(lines))))
                    start_y = max(36, (h - len(lines) * line_h - 50) // 2)
                    fs_body = max(10, min(14, line_h - 4))
                    fs_header = fs_body + 1

                    font = QFont('Arial', fs_body)
                    for i, ln in enumerate(lines):
                        y = start_y + i * line_h
                        is_sep = ln.startswith('─')
                        is_header = (ln.isupper() and len(ln) > 2
                                     and not ln.startswith('•') and not is_sep)
                        if is_sep:
                            color = QColor(100, 100, 100, 200)
                            fs = fs_body
                        elif is_header:
                            color = QColor(255, 220, 80, 255)
                            fs = fs_header
                        else:
                            color = QColor(230, 230, 230, 255)
                            fs = fs_body
                        font.setPointSize(fs)
                        font.setBold(is_header)
                        painter.setFont(font)
                        painter.setPen(color)
                        painter.drawText(0, y, w, line_h, Qt.AlignCenter, ln)
                else:
                    painter.setPen(QColor(255, 255, 255))
                    painter.setFont(QFont('Arial', 48, QFont.Bold))
                    painter.drawText(
                        0, 0, w, h, Qt.AlignCenter, 'LEVEL COMPLETE')

                painter.setPen(QColor(160, 160, 160))
                painter.setFont(QFont('Arial', 13))
                painter.drawText(0, h - 46, w, 30,
                                 Qt.AlignCenter, 'Press ESC to continue')

        if self._modal_visible:
            self._draw_modal(painter)

        painter.end()

    def paintEvent(self, event):
        super().paintEvent(event)

        if not (self.core.screen_closing or self.core.game_completed):
            try:
                painter = QPainter(self)
                painter.setRenderHint(QPainter.Antialiasing, True)
                w = self.width()
                h = self.height()
                painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 13))
                painter.end()
            except Exception:
                pass

        self._draw_hud()

    def _draw_hud(self) -> None:
        if self.core.screen_closing or self.core.game_completed:
            if self._modal_visible:
                painter = QPainter(self)
                painter.setRenderHint(QPainter.Antialiasing, True)
                self._draw_modal(painter)
                painter.end()
            return

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setFont(self._hud_font)

            w = self.width()
            h = self.height()

            pad = 10
            box_w = 320
            box_h = 56
            x = (w - box_w) // 2
            y = pad

            painter.fillRect(x, y, box_w, box_h, QColor(0, 0, 0, 160))
            painter.setPen(QColor(240, 240, 240))
            painter.drawRect(x, y, box_w, box_h)

            painter.setFont(self._hud_font_bold)
            t = int(self.core.elapsed_s)
            painter.drawText(
                x + 12, y + 22, f'Time: {t // 60:02d}:{t % 60:02d}')

            nowp = time.perf_counter()
            if self._time_bonus_text and nowp < self._time_bonus_until:
                painter.setFont(QFont('Arial', 22, QFont.Bold))
                painter.setPen(QColor(255, 220, 60))
                painter.drawText(x + 210, y + 8, 120, 36, Qt.AlignLeft | Qt.AlignVCenter,
                                 self._time_bonus_text)
            elif self._time_bonus_text and nowp >= self._time_bonus_until:
                self._time_bonus_text = ''

            painter.setFont(self._hud_font)
            painter.setPen(QColor(240, 240, 240))
            painter.drawText(x + 12, y + 44,
                             f'Coins: {self.core.coins_collected}/{self.core.coins_required}'
                             f'   Keys: {self.core.keys_collected}/{self.core.keys_required}')

            icon_size = 54
            ix = w - icon_size - 16
            iy = h - icon_size - 16
            self._cam_icon_rect = (ix, iy, icon_size, icon_size)

            now = time.perf_counter()
            on_cd = now < self._minimap_cooldown_until
            painter.fillRect(ix - 6, iy - 6, icon_size + 12,
                             icon_size + 12, QColor(0, 0, 0, 130))
            painter.setPen(QColor(220, 220, 220))
            painter.drawRect(ix - 6, iy - 6, icon_size + 12, icon_size + 12)

            if not self._cam_icon.isNull():
                painter.drawImage(
                    ix, iy,
                    self._cam_icon.scaled(icon_size, icon_size,
                                          Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation),
                )
            else:
                painter.fillRect(ix, iy, icon_size, icon_size,
                                 QColor(120, 120, 120))

            if on_cd:
                remaining = max(0.0, self._minimap_cooldown_until - now)
                painter.fillRect(ix, iy, icon_size, icon_size,
                                 QColor(0, 0, 0, 160))
                painter.setPen(QColor(255, 210, 90))
                painter.drawText(ix + 10, iy + 32,
                                 f'{int(math.ceil(remaining))}s')

            if now < self._minimap_until:
                self._draw_minimap_overlay(painter)

            popup_t = float(
                getattr(self.core, '_sector_popup_timer', 0.0) or 0.0)
            popup_id = str(getattr(self.core, '_sector_popup_id', '') or '')
            if popup_t > 0.0 and popup_id:
                fade_in = 0.25
                fade_out = 0.5
                total = 2.0
                if popup_t > (total - fade_in):
                    alpha = max(
                        0.0, min(1.0, (total - popup_t) / max(0.001, fade_in)))
                elif popup_t < fade_out:
                    alpha = max(0.0, min(1.0, popup_t / max(0.001, fade_out)))
                else:
                    alpha = 1.0

                text = f'SECTOR {popup_id}'
                painter.setFont(self._hud_font_bold)
                tw = painter.fontMetrics().horizontalAdvance(text)
                th = painter.fontMetrics().height()
                bx = (w - tw) // 2
                by = h - 25
                painter.fillRect(bx - 10, by - th, tw + 20, th + 10,
                                 QColor(0, 0, 0, int(150 * alpha)))
                painter.setPen(QColor(255, 220, 110, int(255 * alpha)))
                painter.drawText(bx, by, text)

            if self._modal_visible:
                self._draw_modal(painter)

            self._draw_lore_fade(painter)

            if (not self._modal_visible) and getattr(self.core, 'paused', False):
                self._draw_pause_panel(painter)
        finally:
            painter.end()

    def trigger_flash(self, duration_ms: float = 300, color: Optional[QColor] = None) -> None:
        self._flash_until = time.perf_counter() + (duration_ms / 1000.0)
        if color:
            self._flash_color = color
        self._safe_update()

    def enqueue_lore_lines(self, lines: list[str]) -> None:
        for ln in (lines or []):
            s = str(ln or '').strip()
            if s:
                self._lore_queue.append(s)
        if not self._lore_current and self._lore_queue:
            self._advance_lore_line()
        self._safe_update()

    def _advance_lore_line(self) -> None:
        if not self._lore_queue:
            self._lore_current = ''
            self._lore_current_start = 0.0
            self._lore_current_end = 0.0
            return
        now = time.perf_counter()
        self._lore_current = self._lore_queue.pop(0)
        self._lore_current_start = now
        self._lore_current_end = now + 2.5

    def is_lore_playing(self) -> bool:
        return bool(self._lore_current or self._lore_queue)

    def _draw_lore_fade(self, painter: QPainter) -> None:
        if not self._lore_current:
            if self._lore_queue:
                self._advance_lore_line()
            else:
                return

        now = time.perf_counter()
        if now >= self._lore_current_end:
            self._lore_current = ''
            self._lore_current_start = 0.0
            self._lore_current_end = 0.0
            self._safe_update()
            return

        duration = max(0.01, self._lore_current_end - self._lore_current_start)
        t = max(0.0, min(1.0, (now - self._lore_current_start) / duration))
        fade = 0.18
        a = t / fade if t < fade else (1.0 - t) / \
            fade if t > 1.0 - fade else 1.0
        alpha = int(230 * max(0.0, min(1.0, a)))
        if alpha <= 0:
            return

        w = self.width()
        h = self.height()
        painter.setFont(QFont('Arial', 18))
        text = self._lore_current
        fm = painter.fontMetrics()
        tw = min(w - 80, fm.horizontalAdvance(text))
        th = fm.height()
        bx = (w - tw) // 2
        by = int(h * 0.56)

        outline = QPen(QColor(0, 0, 0, alpha))
        outline.setWidth(3)
        painter.setPen(outline)
        for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            painter.drawText(bx + ox, by + oy, tw, th +
                             4, Qt.AlignCenter, text)
        painter.setPen(QColor(255, 255, 255, alpha))
        painter.drawText(bx, by, tw, th + 4, Qt.AlignCenter, text)

    def _draw_minimap_overlay(self, painter: QPainter) -> None:
        maze_rows = len(self.core.layout)
        maze_cols = len(self.core.layout[0]) if maze_rows > 0 else 0
        if maze_rows == 0 or maze_cols == 0:
            return

        max_cell_w = int(self.width() * 0.85 / maze_cols)
        max_cell_h = int((self.height() - 40) / maze_rows)
        cell_px = min(max_cell_w, max_cell_h)
        if cell_px <= 0:
            return

        mw = maze_cols * cell_px
        mh = maze_rows * cell_px
        x0 = (self.width() - mw) // 2
        y0 = 20 + ((self.height() - 40) - mh) // 2

        painter.fillRect(x0, y0, mw, mh, QColor(10, 10, 12, 210))
        painter.setPen(QColor(230, 230, 230))
        painter.drawRect(x0, y0, mw, mh)

        def to_screen(r: float, c: float) -> tuple[float, float]:
            return x0 + c * cell_px, y0 + r * cell_px

        for r in range(maze_rows):
            for c in range(maze_cols):
                rx, ry = to_screen(r, c)
                sz = int(cell_px + 1)
                if (r, c) in self.core.walls:
                    painter.fillRect(int(rx), int(ry), sz,
                                     sz, QColor(45, 45, 55))
                elif (r, c) in self.core.floors:
                    painter.fillRect(int(rx), int(ry), sz, sz,
                                     QColor(125, 125, 135))
                else:
                    painter.fillRect(int(rx), int(ry), sz,
                                     sz, QColor(15, 15, 18))

        pr, pc = int(self.core.player.z), int(self.core.player.x)
        px, py = to_screen(pr + 0.5, pc + 0.5)
        player_size = max(12, int(cell_px * 0.7))
        half = player_size / 2

        painter.setPen(QPen(QColor(0, 255, 0), 2))
        painter.setBrush(QColor(50, 255, 50))
        painter.drawPolygon(QPolygonF([
            QPointF(px, py - half),
            QPointF(px + half, py),
            QPointF(px, py + half),
            QPointF(px - half, py),
        ]))

        center_size = player_size * 0.4
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(int(px - center_size / 2), int(py - center_size / 2),
                            int(center_size), int(center_size))

        yaw = float(getattr(self.core.player, 'yaw', 0.0))
        fx = math.sin(yaw)
        fz = math.cos(yaw)
        line_len = max(6, int(cell_px * 0.75))
        painter.setPen(QPen(QColor(255, 220, 110), 2))
        painter.drawLine(int(px), int(py), int(
            px + int(fx * line_len)), int(py + int(fz * line_len)))

        for coin in self.core.coins.values():
            if coin.taken:
                continue
            r, c = coin.cell
            cx, cy = to_screen(r + 0.5, c + 0.5)
            coin_size = max(6, int(cell_px * 0.35))
            painter.setPen(QPen(QColor(255, 215, 0), 1))
            painter.setBrush(QColor(255, 215, 0))
            painter.drawEllipse(int(cx - coin_size / 2),
                                int(cy - coin_size / 2), coin_size, coin_size)

        ghost_colors = {
            1: QColor(255, 80, 60),
            2: QColor(80, 255, 140),
            3: QColor(110, 170, 255),
            4: QColor(255, 220, 80),
            5: QColor(255, 90, 255),
        }
        ghost_size = max(10, int(cell_px * 0.6))
        for ghost in self.core.ghosts.values():
            col = ghost_colors.get(ghost.id, QColor(255, 120, 30))
            s = float(getattr(ghost, 'size_scale', 1.0) or 1.0)
            gsz = int(max(8, ghost_size * s))
            sx, sy = to_screen(ghost.z + 0.5, ghost.x + 0.5)

            painter.setPen(QPen(col.darker(150), 1))
            painter.setBrush(col)
            painter.drawEllipse(int(sx - gsz / 2), int(sy - gsz / 2), gsz, gsz)

            eye_size = max(2, int(gsz * 0.15))
            eye_ox = gsz * 0.25
            eye_oy = gsz * 0.1
            for ex in (sx - eye_ox, sx + eye_ox):
                ey = sy - eye_oy
                painter.setPen(QPen(QColor(0, 0, 0), 1))
                painter.setBrush(QColor(255, 255, 255))
                painter.drawEllipse(int(ex - eye_size / 2),
                                    int(ey - eye_size / 2), eye_size, eye_size)
                pupil = max(1, int(eye_size * 0.5))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(0, 0, 0))
                painter.drawEllipse(int(ex - pupil / 2),
                                    int(ey - pupil / 2), pupil, pupil)

        now = time.perf_counter()
        if now < self._minimap_until:
            remaining = max(0.0, self._minimap_until - now)
            painter.setFont(self._hud_font_bold)
            ctext = f'MAP: {int(remaining + 0.5)}s'
            tw = painter.fontMetrics().horizontalAdvance(ctext)
            th = painter.fontMetrics().height()
            cx2 = x0 + mw - tw - 10
            cy2 = y0 + th + 5
            painter.fillRect(cx2 - 3, cy2 - th + 3, tw + 6,
                             th + 3, QColor(0, 0, 0, 180))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(cx2, cy2, ctext)

    def _try_open_minimap(self) -> None:
        now = time.perf_counter()
        if now < self._minimap_cooldown_until:
            return
        self._minimap_until = now + 10.0
        self._minimap_cooldown_until = now + 30.0

    def _close_minimap(self) -> None:
        self._minimap_until = 0.0

    def _toggle_minimap(self) -> None:
        now = time.perf_counter()
        if now < self._minimap_until:
            self._close_minimap()
            return
        self._try_open_minimap()

    def _draw_modal(self, painter: QPainter) -> None:
        w = self.width()
        h = self.height()

        if self._modal_kind == 'level_select':
            painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 255))
            self._draw_level_select_overlay(painter)
            return

        painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 160))

        panel_w = min(840, int(w * 0.74))
        panel_h = min(440, int(h * 0.56))
        x0 = (w - panel_w) // 2
        y0 = (h - panel_h) // 2

        painter.fillRect(x0, y0, panel_w, panel_h, QColor(18, 18, 22, 245))
        painter.setPen(QColor(235, 235, 235))
        painter.drawRect(x0, y0, panel_w, panel_h)

        painter.setFont(QFont('Arial', 18, QFont.Bold))
        painter.drawText(x0 + 24, y0 + 44, panel_w - 48, 28,
                         Qt.AlignLeft, self._modal_title)

        close_size = 32
        close_x = x0 + panel_w - 24 - close_size
        close_y = y0 + 22
        self._modal_btn_rects['close'] = (
            close_x, close_y, close_size, close_size)
        painter.setPen(QColor(220, 220, 220)
                       if self._modal_allow_close else QColor(120, 120, 120))
        painter.drawRect(close_x, close_y, close_size, close_size)
        painter.drawLine(close_x + 7, close_y + 7,
                         close_x + close_size - 7, close_y + close_size - 7)
        painter.drawLine(close_x + close_size - 7, close_y + 7,
                         close_x + 7, close_y + close_size - 7)

        painter.setFont(QFont('Arial', 14))
        painter.setPen(QColor(220, 220, 220))
        painter.drawText(x0 + 24, y0 + 84, panel_w - 48, panel_h - 150,
                         Qt.AlignLeft | Qt.TextWordWrap, self._modal_body)

    def _draw_level_select_overlay(self, painter: QPainter) -> None:
        w = self.width()
        h = self.height()
        self._modal_btn_rects.clear()

        painter.setPen(QColor(240, 240, 240))
        painter.setFont(QFont('Arial', 28, QFont.Bold))
        painter.drawText(0, int(h * 0.14), w, 48, Qt.AlignCenter,
                         self._modal_title or 'Select Level')

        painter.setFont(QFont('Arial', 13))
        painter.setPen(QColor(200, 200, 200))
        painter.drawText(0, int(h * 0.14) + 54, w, 40, Qt.AlignCenter,
                         self._modal_body or '')

        btn_w = min(620, int(w * 0.62))
        btn_h = 82
        gap = 22
        bx = (w - btn_w) // 2
        by1 = int(h * 0.34)
        by2 = by1 + btn_h + gap

        def draw_btn(key: str, y: int, label: str, enabled: bool) -> None:
            if enabled:
                painter.fillRect(bx, y, btn_w, btn_h, QColor(22, 22, 26, 255))
                painter.setPen(QColor(240, 240, 240))
            else:
                painter.fillRect(bx, y, btn_w, btn_h, QColor(22, 22, 26, 190))
                painter.setPen(QColor(140, 140, 140))
            painter.drawRect(bx, y, btn_w, btn_h)
            painter.setFont(QFont('Arial', 18, QFont.Bold))
            painter.drawText(bx, y, btn_w, btn_h, Qt.AlignCenter, label)
            self._modal_btn_rects[key] = (bx, y, btn_w, btn_h)

        draw_btn('level1', by1, 'Level 1', True)
        lvl2_enabled = 'level2' in self._level_select_unlocked
        draw_btn(
            'level2', by2, 'Level 2' if lvl2_enabled else 'Level 2 (Locked)', lvl2_enabled)

        close_size = 38
        close_x = w - close_size - 20
        close_y = 18
        self._modal_btn_rects['close'] = (
            close_x, close_y, close_size, close_size)
        painter.setPen(QColor(220, 220, 220)
                       if self._modal_allow_close else QColor(120, 120, 120))
        painter.drawRect(close_x, close_y, close_size, close_size)
        painter.drawLine(close_x + 8, close_y + 8,
                         close_x + close_size - 8, close_y + close_size - 8)
        painter.drawLine(close_x + close_size - 8, close_y + 8,
                         close_x + 8, close_y + close_size - 8)

    def _draw_pause_panel(self, painter: QPainter) -> None:
        w = self.width()
        h = self.height()
        painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 160))

        panel_w = 560
        panel_h = 610
        x0 = (w - panel_w) // 2
        y0 = (h - panel_h) // 2

        painter.fillRect(x0, y0, panel_w, panel_h, QColor(18, 18, 22, 235))
        painter.setPen(QColor(220, 220, 220))
        painter.drawRect(x0, y0, panel_w, panel_h)

        title_font = QFont('Arial', 22)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(255, 220, 110))
        painter.drawText(x0, y0 + 48, panel_w, 32, Qt.AlignCenter, 'PAUSED')

        painter.setFont(self._hud_font)
        painter.setPen(QColor(235, 235, 235))

        fps = self.performance_monitor.stable_display_fps(
            update_interval_s=2.5)
        ram = self.performance_monitor.current_ram_mb()

        stats_x = x0 + 36
        stats_y = y0 + 96
        line_h = 24
        painter.drawText(stats_x, stats_y + line_h * 0, f'FPS: {int(fps)}')
        painter.drawText(stats_x, stats_y + line_h *
                         1, f'RAM usage: {ram:.1f} MB')

        btn_w = 280
        btn_h = 48
        gap = 16
        center_x = x0 + (panel_w - btn_w) // 2
        top_btn_y = y0 + 200

        buttons = [
            ('resume',    'Resume',         center_x, top_btn_y + (btn_h + gap) * 0),
            ('levels',    'Levels',         center_x, top_btn_y + (btn_h + gap) * 1),
            ('save',      'Save Game',      center_x, top_btn_y + (btn_h + gap) * 2),
            ('save_exit', 'Save + Exit',    center_x, top_btn_y + (btn_h + gap) * 3),
            ('restart',   'Restart',        center_x, top_btn_y + (btn_h + gap) * 4),
            ('exit',      'Exit (No Save)', center_x, top_btn_y + (btn_h + gap) * 5),
        ]

        self._pause_btn_rects.clear()
        for key, label, bx, by in buttons:
            self._pause_btn_rects[key] = (bx, by, btn_w, btn_h)
            painter.fillRect(bx, by, btn_w, btn_h, QColor(32, 32, 40, 235))
            painter.setPen(QColor(220, 220, 220))
            painter.drawRect(bx, by, btn_w, btn_h)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(bx, by, btn_w, btn_h, Qt.AlignCenter, label)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._modal_visible:
            if event.button() == Qt.LeftButton:
                x = int(event.position().x())
                y = int(event.position().y())
                for key, (bx, by, bw, bh) in self._modal_btn_rects.items():
                    if bx <= x <= bx + bw and by <= y <= by + bh:
                        if key == 'close':
                            win = self.window()
                            if hasattr(win, '_on_modal_close_clicked'):
                                win._on_modal_close_clicked()
                            return
                        if self._modal_kind == 'level_select':
                            if key == 'level2' and key not in self._level_select_unlocked:
                                return
                            win = self.window()
                            if hasattr(win, '_on_level_selected'):
                                win._on_level_selected(key)
                            return
            return

        if getattr(self.core, 'paused', False):
            if event.button() == Qt.LeftButton:
                x = int(event.position().x())
                y = int(event.position().y())
                for key, (bx, by, bw, bh) in self._pause_btn_rects.items():
                    if bx <= x <= bx + bw and by <= y <= by + bh:
                        win = self.window()
                        if hasattr(win, '_on_pause_action'):
                            win._on_pause_action(key)
                        return
            return

        if event.button() == Qt.LeftButton:
            ix, iy, iw, ih = self._cam_icon_rect
            if ix <= event.position().x() <= ix + iw and iy <= event.position().y() <= iy + ih:
                self._toggle_minimap()
                return
            center_global = self.mapToGlobal(self.rect().center())
            self._fps_camera_start(center_global)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._fps_camera_stop()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if getattr(self.core, 'paused', False):
            return
        if not self._mouse_captured or not self._center_global:
            return
        current_global = self.mapToGlobal(event.pos())
        dx = current_global.x() - self._center_global.x()
        dy = current_global.y() - self._center_global.y()
        if abs(dx) > 1 or abs(dy) > 1:
            self.mouse_moved.emit(float(dx), float(dy))
            self.cursor().setPos(self._center_global)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        event.ignore()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        event.ignore()

    def hide_mouse_capture(self) -> None:
        self._fps_camera_stop()

    def show_level_select_modal(self, *, unlocked: set[str], allow_close: bool,
                                return_to_pause: bool) -> None:
        self._modal_visible = True
        self._modal_kind = 'level_select'
        self._modal_title = 'Select Level'
        self._modal_body = 'Level 2 is locked until you complete Level 1.\nEntering a level always starts fresh.'
        self._level_select_unlocked = set(unlocked)
        self._modal_allow_close = bool(allow_close)
        self._modal_return_to_pause = bool(return_to_pause)
        self._modal_btn_rects.clear()
        self.hide_mouse_capture()
        self._safe_update()

    def show_tutorial_modal(self, *, title: str, body: str) -> None:
        self._modal_visible = True
        self._modal_kind = 'tutorial'
        self._modal_title = str(title)
        self._modal_body = str(body)
        self._modal_allow_close = True
        self._modal_return_to_pause = False
        self._modal_btn_rects.clear()
        self.hide_mouse_capture()
        self._safe_update()

    def hide_modal(self) -> None:
        self._modal_visible = False
        self._modal_kind = ''
        self._modal_title = ''
        self._modal_body = ''
        self._modal_btn_rects.clear()
        self._safe_update()

    def _fps_camera_start(self, center_global) -> None:
        self._mouse_captured = True
        self._center_global = center_global
        self.setCursor(Qt.BlankCursor)
        self.cursor().setPos(center_global)

    def _fps_camera_stop(self) -> None:
        self._mouse_captured = False
        self._center_global = None
        self.setCursor(Qt.ArrowCursor)

    def _fps_camera_update(self, dx: float, dy: float) -> None:
        self.core.rotate_player(-dx * FPS_CAMERA_SENSITIVITY)
        self.core.tilt_camera(-dy * FPS_CAMERA_SENSITIVITY)


class PySide6GameWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        # This mirrors Kivy's approach: _startup_begin is stamped here,
        # so startup_time_ms reflects the full cost from app launch to first frame.
        self._perf = PerformanceMonitor(framework='PySide6')

        self._progress_path = os.path.abspath('progression.json')
        self._progress = self._load_progression()

        unlocked = set(self._progress.get('unlocked_levels') or [])
        last_level = str(self._progress.get('last_level') or 'level1')
        if last_level not in unlocked:
            last_level = 'level1'

        self._save_path = os.path.abspath('savegame.json')
        self._current_level_id = last_level

        self._autoload_level1_save = (
            last_level == 'level1' and os.path.exists(self._save_path))

        self.core = GameCore(level_id=last_level)

        # ── Audio (loaded after monitor, so audio I/O is included in startup) ─
        self._asset_dir = os.path.abspath('assets')
        _LOOPS = 999999999
        self._sfx_footsteps = QSoundEffect(self)
        self._sfx_footsteps.setSource(
            QUrl.fromLocalFile(os.path.join(self._asset_dir, 'running-on-concrete-268478.wav')))
        self._sfx_footsteps.setVolume(0.22)
        self._sfx_footsteps.setLoopCount(_LOOPS)

        self._sfx_coin = QSoundEffect(self)
        self._sfx_coin.setSource(
            QUrl.fromLocalFile(os.path.join(self._asset_dir, 'drop-coin-384921.wav')))
        self._sfx_coin.setVolume(0.55)

        self._sfx_gate = QSoundEffect(self)
        self._sfx_gate.setSource(
            QUrl.fromLocalFile(os.path.join(self._asset_dir, 'closing-metal-door-44280.wav')))
        self._sfx_gate.setVolume(0.55)

        self._sfx_ghost = QSoundEffect(self)
        self._sfx_ghost.setSource(
            QUrl.fromLocalFile(os.path.join(self._asset_dir, 'ghost-horror-sound-382709.wav')))
        self._sfx_ghost.setVolume(0.40)

        self._footsteps_playing = False

        self._ghost_sound_timer = QTimer(self)
        self._ghost_sound_timer.timeout.connect(self._play_ghost_sound)
        self._ghost_sound_timer.start(2500)

        self._key_minigame_open = False
        self._assembly_minigame: Optional[Assembly3DMinigame] = None
        self._solved_fragments: set[str] = set()
        self._last_ghost_id: int = 0

        self._register_core_callbacks()

        self.setWindowTitle('Within the Walls (PySide6)')
        self.showMaximized()

        self.keys_pressed: set[int] = set()

        # ── GL widget receives the already-created monitor ──────────────────
        # Connect monitor to core BEFORE creating GL widget so texture loading
        # time can be recorded during renderer initialization
        self.core._performance_monitor = self._perf
        self.gl = GameGLWidget(self.core, self._perf)
        self.setCentralWidget(self.gl)

        self._lore_seen: set[str] = set()
        self._lore_flags: dict[str, bool] = {}
        self._persist_seen: dict[str, bool] = {}
        self._pending_gameplay_tutorial = False

        self._level_end_triggered: bool = False
        self._level_complete: bool = False
        self._stats_text: str = ''
        self._perf_pdf_exported: bool = False
        self._last_update_time: float = time.perf_counter()

        self.gl.mouse_moved.connect(self._on_mouse_look)

        self.setFocusPolicy(Qt.StrongFocus)
        self.startTimer(16)

        # ── Deferred level start (same pattern as Kivy) ──────────────────────
        # No eager GL init here — initializeGL() fires automatically when the
        # widget is first shown, which happens before _deferred_start runs.
        QTimer.singleShot(100, self._deferred_start)

    def _deferred_start(self) -> None:
        if self._current_level_id == 'level2':
            self._set_paused(False)
            self._start_level(
                'level2', load_save=os.path.exists(self._save_path))
        elif self._autoload_level1_save:
            self._set_paused(False)
            self._start_level('level1', load_save=True)
        else:
            self._open_level_select_modal(startup=True)

    def _start_level(self, level_id: str, *, load_save: bool) -> None:
        level_id = str(level_id or 'level1')
        paused_was = bool(getattr(self.core, 'paused', False))

        try:
            self.core.simulation_frozen = False
        except Exception:
            pass

        self.core = GameCore(level_id=level_id)
        self._current_level_id = level_id
        self.gl.core = self.core

        self._level_end_triggered = False
        self._level_complete = False
        self._stats_text = ''
        self._perf_pdf_exported = False
        self.gl._show_the_end = False
        self.gl._stats_text = ''
        self.gl._stats_visible = False

        # Fresh monitor for every level — preserve startup time across restarts
        # (same logic as Kivy's _start_level)
        old_startup_time = self._perf.startup_time_ms
        old_texture_load_time = self._perf.texture_load_time_ms
        self._perf = PerformanceMonitor(framework='PySide6')
        if old_startup_time is not None:
            self._perf.startup_time_ms = old_startup_time
        if old_texture_load_time is not None:
            self._perf.texture_load_time_ms = old_texture_load_time
        self._perf.frozen_stats = None
        self._perf.fps_history.clear()
        self._perf.memory_samples.clear()
        self.gl.performance_monitor = self._perf

        for k in ('coins_half', 'ghost_close', 'l2_frags_done', 'l2_sector_f_done'):
            self._lore_flags.pop(k, None)
        self.__dict__.pop('_player_has_moved', None)

        try:
            self.gl.makeCurrent()
            self.gl.renderer = OpenGLRenderer(self.core)
            self.gl.renderer.resize(self.gl.width(), self.gl.height())
            self.gl.renderer.initialize()
            self.gl.doneCurrent()
        except Exception:
            try:
                self.gl.renderer.core = self.core
            except Exception:
                pass

        self.keys_pressed.clear()
        self._register_core_callbacks()
        self.core._performance_monitor = self._perf

        if bool(load_save):
            self._load_save_if_present()

        if paused_was:
            self._set_paused(True)
        self._last_update_time = time.perf_counter()

        if (not load_save) and float(getattr(self.core, 'elapsed_s', 0.0) or 0.0) <= 0.0001:
            self._play_sfx(self._sfx_gate)

        if float(getattr(self.core, 'elapsed_s', 0.0) or 0.0) <= 0.0001:
            if level_id == 'level1' and not self._persist_seen.get('l1_intro'):
                self._persist_seen['l1_intro'] = True
                self._show_lore_line('A basement? This feels like a test.')
                self._pending_gameplay_tutorial = True
            elif level_id == 'level2' and not self._persist_seen.get('l2_intro'):
                self._persist_seen['l2_intro'] = True
                self._show_lore_line('This place feels inhabited.')

        self._safe_gl_update()

    # ── progression / save ───────────────────────────────────────────────────

    def _load_progression(self) -> dict:
        if not os.path.exists(self._progress_path):
            return {'unlocked_levels': ['level1']}
        try:
            with open(self._progress_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {'unlocked_levels': ['level1']}
            unlocked = data.get('unlocked_levels')
            if not isinstance(unlocked, list) or 'level1' not in unlocked:
                return {'unlocked_levels': ['level1']}
            return data
        except Exception:
            return {'unlocked_levels': ['level1']}

    def _save_progression(self) -> None:
        try:
            with open(self._progress_path, 'w', encoding='utf-8') as f:
                json.dump(self._progress, f, indent=2)
        except Exception:
            pass

    def _save_game(self) -> None:
        try:
            self._progress['last_level'] = str(self._current_level_id)
            self._save_progression()
        except Exception as e:
            print(f'[save] progression failed: {e}')
        try:
            state = self.core.get_save_state()
            state['ui_seen'] = dict(self._persist_seen)
            with open(self._save_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f'[save] savegame failed: {e}')

    def _load_save_if_present(self) -> None:
        if not os.path.exists(self._save_path):
            return
        try:
            with open(self._save_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
            if isinstance(state, dict):
                saved_level = str(state.get('level_id') or '')
                if saved_level and saved_level != self._current_level_id:
                    return
                seen = state.get('ui_seen')
                if isinstance(seen, dict):
                    self._persist_seen.update(
                        {str(k): bool(v) for k, v in seen.items()})
            self.core.load_save_state(state)
        except Exception as e:
            print(f'[load] failed: {e}')

    # ── core registration ─────────────────────────────────────────────────────

    def _register_core_callbacks(self) -> None:
        ev = self.core.register_event_callback
        ev('coin_picked',              self._on_coin_picked)
        ev('gate_opened',              self._on_gate_moved)
        ev('gate_closed',              self._on_gate_moved)
        ev('key_fragment_encountered', self._on_key_fragment_encountered)
        ev('game_won',                 self._on_game_won)
        ev('checkpoint_reached',       self._on_checkpoint_reached)
        ev('time_penalty',             self._on_time_penalty)
        ev('exit_unlocked',            self._on_exit_unlocked)
        ev('sector_entered',           self._on_sector_entered)
        ev('sent_to_jail',             self._on_sent_to_jail)
        ev('sent_to_spawn',           self._on_sent_to_spawn)
        ev('left_jail',                self._on_left_jail)
        ev('key_picked',               self._on_key_picked)
        ev('player_move', lambda d: None)

    # ── level-end flow ────────────────────────────────────────────────────────

    def _handle_level_end(self) -> None:
        self._level_end_triggered = True
        self._level_complete = True
        self.core.simulation_frozen = True
        self._set_footsteps_playing(False)

        if self._current_level_id == 'level1':
            unlocked = set(self._progress.get('unlocked_levels') or ['level1'])
            unlocked.add('level2')
            self._progress['unlocked_levels'] = sorted(unlocked)
            self._save_progression()

        try:
            self._perf.update_scene_data(
                walls_rendered=len(getattr(self.core, 'walls', set())),
                coins=len(getattr(self.core, 'coins', [])),
                ghosts=len(getattr(self.core, 'ghosts', {})),
                spike_traps=len(getattr(self.core, 'spikes', [])),
                moving_platforms=len(getattr(self.core, 'platforms', [])),
            )
            self._perf._game_core_elapsed_s = self.core.elapsed_s
            self._perf.freeze_stats()
            summary_text = self._perf.format_summary_text()
        except Exception as exc:
            summary_text = f'Level complete!\n\nPress ESC to continue.\n\n({exc})'

        try:
            perf_data = self._perf.get_performance_summary()
            from core.pdf_export import export_performance_pdf
            export_performance_pdf(
                framework='pyside6',
                level_id=self._current_level_id,
                performance_data=perf_data,
                out_dir=os.path.abspath('performance_reports'),
            )
            self._perf_pdf_exported = True
            print('[PySide6] PDF report exported to performance_reports/')
        except ImportError:
            pass
        except Exception as e:
            print(f'[PySide6] PDF export failed: {e}')

        self.show_stats_screen(summary_text)
        self._safe_gl_update()

    def show_stats_screen(self, text: str) -> None:
        self._stats_text = str(text or '')
        self._level_complete = True
        self.gl._stats_text = self._stats_text
        self.gl._show_the_end = False

    def show_end_screen(self, text: str) -> None:
        self._stats_text = str(text or '')
        self._level_complete = True
        self.gl._stats_text = self._stats_text
        self.gl._show_the_end = True
        try:
            if os.path.exists(self._save_path):
                os.remove(self._save_path)
        except Exception:
            pass

    def _on_stats_screen_esc(self) -> None:
        if not self._level_complete:
            return
        try:
            if os.path.exists(self._save_path):
                os.remove(self._save_path)
        except Exception:
            pass
        if self._current_level_id == 'level2':
            self._show_the_end_from_stats()
        else:
            self._level_complete = False
            self._open_level_select_modal(startup=False)

    def _show_the_end_from_stats(self) -> None:
        self.gl._stats_text = ''
        self._level_complete = False
        self.show_end_screen(self._stats_text)

    def _set_paused(self, paused: bool) -> None:
        self.core.paused = bool(paused)
        if paused:
            self.keys_pressed.clear()
            self._set_footsteps_playing(False)
            try:
                self.gl._mouse_captured = False
                self.gl.setCursor(Qt.ArrowCursor)
            except Exception:
                pass
            try:
                self._sfx_footsteps.stop()
            except Exception:
                pass
            try:
                self._ghost_sound_timer.stop()
            except Exception:
                pass
            return
        try:
            self._ghost_sound_timer.start(2500)
        except Exception:
            pass
        self._last_update_time = time.perf_counter()

    def _toggle_pause(self) -> None:
        if self.core.screen_closing or self.core.game_completed or self.core.game_won:
            return
        self._set_paused(not bool(getattr(self.core, 'paused', False)))

    # ── main update loop ──────────────────────────────────────────────────────

    def _update_game(self) -> None:
        now = time.perf_counter()
        dt = min(now - self._last_update_time, 0.05)
        self._last_update_time = now

        paused = bool(getattr(self.core, 'paused', False))

        if self.core.screen_closing and not self.core.game_won:
            self.core._update_screen_close(dt)
        elif not paused:
            self.core.update(dt)

        if bool(getattr(self.core, 'game_won', False)) and not self._level_end_triggered:
            self._level_end_triggered = True
            self._handle_level_end()
            return

        if not paused and not getattr(self.gl, '_modal_visible', False):
            self._poll_lore_triggers()

        if self._pending_gameplay_tutorial and not getattr(self.gl, '_modal_visible', False):
            if not self.gl.is_lore_playing():
                self._pending_gameplay_tutorial = False
                if (self._current_level_id == 'level1'
                        and not self._persist_seen.get('tutorial_gameplay')):
                    self._persist_seen['tutorial_gameplay'] = True
                    self._show_tutorial_modal(
                        'Gameplay',
                        'Press WASD to move.\n'
                        'Hold Left Mouse Button to look around.\n'
                        'Press ESC to pause. You can also save and exit from the pause menu.\n\n'
                        'Press M or click the camera icon to open the minimap.\n'
                        'The minimap stays open for 10 seconds, then goes on a 20 second cooldown.\n\n'
                        'Collect all coins and key fragments to unlock the exit.\n'
                        'Avoid hazards. If you get caught, you will be sent to jail.'
                    )

        if paused:
            self._set_footsteps_playing(False)
            return

        if getattr(self.gl, '_modal_visible', False):
            return

        move_speed = 0.12 if self._current_level_id == 'level1' else 0.18
        dx = dz = 0.0
        if Qt.Key_W in self.keys_pressed:
            dz += move_speed
        if Qt.Key_S in self.keys_pressed:
            dz -= move_speed
        if Qt.Key_A in self.keys_pressed:
            dx -= move_speed
        if Qt.Key_D in self.keys_pressed:
            dx += move_speed

        if dx != 0.0 or dz != 0.0:
            moved = self.core.move_player(dx, dz)
            if moved:
                self._perf.record_input_processed()
            self._set_footsteps_playing(moved)
        else:
            self._set_footsteps_playing(False)

    # ── keyboard ──────────────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        self._perf.record_input_event()
        self.keys_pressed.add(event.key())

        if event.key() == Qt.Key_E:
            self._handle_interact()
            return

        if event.key() == Qt.Key_Escape:
            if self._level_complete and (self.core.screen_closing or self.core.game_completed):
                self._on_stats_screen_esc()
                return
            if getattr(self.gl, '_modal_visible', False):
                self._on_modal_close_clicked()
                return
            self._toggle_pause()
            return

        if getattr(self.gl, '_modal_visible', False):
            return

        if event.key() == Qt.Key_M:
            self.gl._toggle_minimap()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        self.keys_pressed.discard(event.key())

    # ── mouse look ────────────────────────────────────────────────────────────

    def _on_mouse_look(self, dx: float, dy: float) -> None:
        sensitivity = 0.002
        self.core.rotate_player(-dx * sensitivity)
        self.core.tilt_camera(-dy * sensitivity)

    # ── audio helpers ─────────────────────────────────────────────────────────

    def _play_sfx(self, sfx: QSoundEffect) -> None:
        sfx.stop()
        sfx.play()

    def _set_footsteps_playing(self, playing: bool) -> None:
        if playing == self._footsteps_playing:
            return
        self._footsteps_playing = playing
        if playing:
            self._sfx_footsteps.play()
        else:
            self._sfx_footsteps.stop()

    def _play_ghost_sound(self) -> None:
        if getattr(self.core, 'paused', False):
            return
        if self.core.game_won or self.core.game_completed:
            return
        if not getattr(self.core, 'ghosts', None):
            return
        px = float(self.core.player.x)
        pz = float(self.core.player.z)
        nearest = min(
            (math.hypot(g.x - px, g.z - pz)
             for g in self.core.ghosts.values()),
            default=None,
        )
        if nearest is None or nearest > 10.0:
            return
        t = 1.0 if nearest <= 2.5 else max(0.0, (10.0 - nearest) / 7.5)
        self._sfx_ghost.setVolume(0.06 + 0.55 * t)
        self._play_sfx(self._sfx_ghost)

    # ── interact ──────────────────────────────────────────────────────────────

    def _handle_interact(self) -> None:
        if getattr(self.core, 'paused', False):
            return
        action = self.core.interact()
        if action == 'jail_book':
            self.keys_pressed.clear()
            if (self._current_level_id == 'level1'
                    and not self._lore_flags.get('l1_jail_puzzle_success')):
                self._lore_flags['l1_jail_puzzle_success'] = True
                self._show_lore_line('The maze resets what it cannot control.')
            self._release_mouse()
            self.keys_pressed.clear()
            prev = self.core.simulation_frozen
            self.core.simulation_frozen = True
            ok = False
            try:
                # Use hard mode if ghost 4 caught us
                hard_mode = (self._last_ghost_id == 4)
                ok = bool(SilhouetteMatchDialog(
                    self, hard_mode=hard_mode).exec())
            finally:
                self.core.simulation_frozen = prev
                self._last_update_time = time.perf_counter()
            if ok:
                self.core.mark_jail_puzzle_success()
                if (self._current_level_id == 'level1'
                        and not self._lore_flags.get('l1_jail_puzzle_success')):
                    self._lore_flags['l1_jail_puzzle_success'] = True
                    self._show_lore_line(
                        'The maze resets what it cannot control.')
            self._release_mouse()
            self.keys_pressed.clear()
        elif action == 'gate_jail':
            self.core.try_leave_jail()

    def _release_mouse(self) -> None:
        try:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.mouseButtons()
            if hasattr(self.gl, '_mouse_captured'):
                self.gl._mouse_captured = False
                self.gl.setCursor(Qt.ArrowCursor)
        except Exception:
            pass

    # ── modal close ───────────────────────────────────────────────────────────

    def _on_modal_close_clicked(self) -> None:
        if not getattr(self.gl, '_modal_visible', False):
            return
        if not bool(getattr(self.gl, '_modal_allow_close', True)):
            return
        if (str(getattr(self.gl, '_modal_kind', '')) == 'level_select'
                and bool(getattr(self.gl, '_modal_return_to_pause', False))):
            self.gl.hide_modal()
            self._set_paused(True)
            self._safe_gl_update()
            return
        self.gl.hide_modal()
        self._set_paused(False)

    # ── pause actions ─────────────────────────────────────────────────────────

    def _on_pause_action(self, action: str) -> None:
        if action == 'resume':
            self._toggle_pause()
        elif action == 'levels':
            self._toggle_pause()
            self._open_level_select_modal(startup=False)
        elif action == 'save':
            self._save_game()
        elif action == 'save_exit':
            self._save_game()
            self.close()
        elif action == 'exit':
            self.close()
        elif action == 'restart':
            self._restart_game()

    def _restart_game(self) -> None:
        paused_was = bool(getattr(self.core, 'paused', False))
        self.core = GameCore(level_id=self._current_level_id)
        self.gl.core = self.core

        self._level_end_triggered = False
        self._level_complete = False
        self._stats_text = ''
        self._perf_pdf_exported = False
        self.gl._show_the_end = False
        self.gl._stats_text = ''

        old_startup_time = self._perf.startup_time_ms
        old_texture_load_time = self._perf.texture_load_time_ms
        self._perf = PerformanceMonitor(framework='PySide6')
        if old_startup_time is not None:
            self._perf.startup_time_ms = old_startup_time
        if old_texture_load_time is not None:
            self._perf.texture_load_time_ms = old_texture_load_time
        self._perf.frozen_stats = None
        self._perf.fps_history.clear()
        self._perf.memory_samples.clear()
        self.gl.performance_monitor = self._perf

        try:
            self.gl.makeCurrent()
            self.gl.renderer = OpenGLRenderer(self.core)
            self.gl.renderer.resize(self.gl.width(), self.gl.height())
            self.gl.renderer.initialize()
            self.gl.doneCurrent()
        except Exception:
            try:
                self.gl.renderer.core = self.core
            except Exception:
                pass

        self.keys_pressed.clear()
        self._register_core_callbacks()
        self.core._performance_monitor = self._perf
        if paused_was:
            self._set_paused(True)
        self._last_update_time = time.perf_counter()
        self._play_sfx(self._sfx_gate)
        self._safe_gl_update()

    # ── lore / tutorial ───────────────────────────────────────────────────────

    def _show_lore_line(self, text: str) -> None:
        s = str(text or '').strip()
        if s:
            self.gl.enqueue_lore_lines([s])

    def _show_tutorial_modal(self, title: str, body: str) -> None:
        self._set_paused(True)
        self.gl.show_tutorial_modal(title=title, body=body)

    def _trigger_lore(self, key: str) -> None:
        key = str(key or '').strip()
        if not key or key in self._lore_seen:
            return
        txt: Optional[str] = None
        if key == 'ON_GHOST_CLOSE':
            txt = 'Why are you here?' if self._current_level_id == 'level1' else 'Wake me up.'
        if not txt:
            return
        self._lore_seen.add(key)
        self._show_lore_line(txt)

    def _poll_lore_triggers(self) -> None:
        if getattr(self.core, 'paused', False) or getattr(self.gl, '_modal_visible', False):
            return
        try:
            nearest = min(
                (math.hypot(g.x - self.core.player.x, g.z - self.core.player.z)
                 for g in self.core.ghosts.values()),
                default=None,
            )
            if nearest is not None and nearest <= 2.0:
                if not self._lore_flags.get('ghost_close'):
                    self._lore_flags['ghost_close'] = True
                    k = f'ghost_close_{self._current_level_id}'
                    if not self._persist_seen.get(k):
                        self._persist_seen[k] = True
                        self._trigger_lore('ON_GHOST_CLOSE')
        except Exception:
            pass

    # ── core event callbacks ──────────────────────────────────────────────────

    def _on_coin_picked(self, data: dict) -> None:
        self._play_sfx(self._sfx_coin)
        try:
            if float(self.core.coins_collected) >= float(self.core.coins_required) * 0.5:
                k = f'coins_half_{self._current_level_id}'
                if not self._lore_flags.get('coins_half') and not self._persist_seen.get(k):
                    self._lore_flags['coins_half'] = True
                    self._persist_seen[k] = True
                    self._show_lore_line(
                        'Halfway.' if self._current_level_id == 'level1'
                        else 'The maze likes it when I collect.'
                    )
        except Exception:
            pass

    def _on_gate_moved(self, data: dict) -> None:
        self._play_sfx(self._sfx_gate)

    def _on_exit_unlocked(self, data: dict) -> None:
        pass

    def _on_sector_entered(self, data: dict) -> None:
        sid = str((data or {}).get('id', '') or '')
        if self._current_level_id == 'level2' and sid == 'F':
            try:
                req = (int(self.core.coins_collected) >= int(self.core.coins_required)
                       and int(self.core.keys_collected) >= int(self.core.keys_required))
            except Exception:
                req = False
            if req and not self._lore_flags.get('l2_sector_f_done'):
                self._lore_flags['l2_sector_f_done'] = True
                self._show_lore_line('A dream... Far too lucid.')

    def _on_sent_to_jail(self, data: dict) -> None:
        # Track which ghost sent us to jail (ghost 4 triggers hard minigame)
        reason = str(data.get('reason', ''))
        if reason == 'ghost_4':
            self._last_ghost_id = 4
        elif reason.startswith('ghost'):
            self._last_ghost_id = 1  # Normal ghost
        else:
            self._last_ghost_id = 0  # Spikes or other
        if self._current_level_id != 'level1':
            return
        if not self._persist_seen.get('tutorial_jail'):
            self._persist_seen['tutorial_jail'] = True
            self._show_tutorial_modal(
                'Jail',
                'You were caught and sent to jail.\n\n'
                'A sector map is displayed here. Use it to orient yourself before returning to the maze.',
            )

    def _on_sent_to_spawn(self, data: dict) -> None:
        """Ghost 3 sends player to spawn instead of jail - show lore and flash screen."""
        self._show_lore_line('Be safe.')
        self.gl.trigger_flash(300, QColor(20, 20, 25, 180))

    def _on_left_jail(self, data: dict) -> None:
        pass

    def _on_key_picked(self, data: dict) -> None:
        try:
            cnt = int((data or {}).get('count', 0) or 0)
            if (self._current_level_id == 'level2' and cnt >= 3
                    and not self._lore_flags.get('l2_frags_done')):
                self._lore_flags['l2_frags_done'] = True
                self._show_lore_line('The key is done... I am watched.')
        except Exception:
            pass

    def _on_game_won(self, data: dict) -> None:
        if self._current_level_id != 'level1':
            return
        unlocked = set(self._progress.get('unlocked_levels') or [])
        if 'level2' not in unlocked:
            unlocked.add('level2')
            self._progress['unlocked_levels'] = sorted(unlocked)
            self._save_progression()

    def _on_checkpoint_reached(self, data: dict) -> None:
        self._set_paused(True)
        self._last_update_time = time.perf_counter()
        self._safe_gl_update()

    def _on_time_penalty(self, data: dict) -> None:
        try:
            amount = int((data or {}).get('seconds', 0) or 0)
            if amount > 0:
                self.gl._time_bonus_text = f'+{amount}'
                self.gl._time_bonus_until = time.perf_counter() + 2.5
                self._safe_gl_update()
        except Exception:
            pass

    def _on_key_fragment_encountered(self, data: dict) -> None:
        if getattr(self.core, 'paused', False) or self._key_minigame_open:
            return
        frag_id = str((data or {}).get('id', ''))
        if not frag_id:
            return
        if frag_id in self._solved_fragments:
            return
        try:
            frag = getattr(self.core, 'key_fragments', {}).get(frag_id)
            frag_kind = str(getattr(frag, 'kind', '') or '')
        except Exception:
            frag_kind = ''

        self._key_minigame_open = True
        self.keys_pressed.clear()
        self._set_footsteps_playing(False)
        self._release_mouse()
        prev = self.core.simulation_frozen
        self.core.simulation_frozen = True

        if self._assembly_minigame is None:
            self._assembly_minigame = Assembly3DMinigame(
                self, kind=frag_kind or 'KP')
        else:
            self._assembly_minigame.reset(kind=frag_kind or 'KP')

        ok = False
        try:
            ok = bool(self._assembly_minigame.exec())
        finally:
            self.core.simulation_frozen = prev
            self._last_update_time = time.perf_counter()

        if ok:
            self.core.mark_key_fragment_taken(frag_id)
            self.core.defer_key_fragment(frag_id)
            self._solved_fragments.add(frag_id)
        else:
            self.core.clear_pending_key_fragment(frag_id)
            self.core.defer_key_fragment(frag_id)

        self._release_mouse()
        self._key_minigame_open = False
        self.keys_pressed.clear()

    # ── timer (keeps ticking through modal dialogs) ───────────────────────────

    def timerEvent(self, event) -> None:
        self._update_game()

    def _safe_gl_update(self) -> None:
        try:
            self.gl.update()
        except Exception:
            pass

    # ── level selection ───────────────────────────────────────────────────────

    def _open_level_select_modal(self, *, startup: bool) -> None:
        unlocked = set(self._progress.get('unlocked_levels') or [])
        self._set_paused(True)
        try:
            self.gl.hide_mouse_capture()
        except Exception:
            pass
        self.gl.show_level_select_modal(
            unlocked=unlocked,
            allow_close=(not startup),
            return_to_pause=(not startup),
        )

    def _on_level_selected(self, level_id: str) -> None:
        self.gl.hide_modal()
        self._set_paused(False)
        try:
            self._progress['last_level'] = str(level_id)
            unlocked = set(self._progress.get('unlocked_levels', []))
            if level_id == 'level1' and 'level2' not in unlocked:
                unlocked.add('level2')
                self._progress['unlocked_levels'] = sorted(unlocked)
            self._save_progression()
        except Exception as e:
            print(f'Error saving progression: {e}')
        self._start_level(level_id, load_save=False)


# ---------------------------------------------------------------------------

def run() -> int:
    app = QApplication.instance() or QApplication([])
    win = PySide6GameWindow()
    win.show()
    return app.exec()
