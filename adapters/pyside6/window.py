import math

import json

import os

import time

from typing import Optional, Set


from PySide6.QtCore import Qt, Signal, QPointF, QTimer, QUrl

from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QColor, QFont, QImage, QPen, QPolygonF, QRadialGradient, QLinearGradient

from PySide6.QtOpenGLWidgets import QOpenGLWidget

from PySide6.QtMultimedia import QSoundEffect

from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QDialog, QVBoxLayout, QLabel, QPushButton


from core.game_core import GameCore

from .renderer_opengl import OpenGLRenderer

from .silhouette_minigame import SilhouetteMatchDialog

from core.performance_monitor import PerformanceMonitor

from .assembly3d_minigame import Assembly3DMinigame


class GameGLWidget(QOpenGLWidget):

    mouse_moved = Signal(float, float)

    def __init__(self, core: GameCore):

        super().__init__()

        self.core = core

        self.renderer = OpenGLRenderer(core)

        self.performance_monitor = PerformanceMonitor(framework='PySide6')

        self._pause_btn_rects: dict[str, tuple[int, int, int, int]] = {}

        self._hud_font = QFont('Segoe UI', 10)

        self._hud_font_bold = QFont('Segoe UI', 11)

        self._hud_font_bold.setBold(True)

        self._cam_icon = QImage('assets/cam.jpg')

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

        self._show_the_end: bool = False

        self.setMouseTracking(True)

        self.setFocusPolicy(Qt.StrongFocus)

        self._mouse_captured = False

        self._center_global = None

        self._render_timer = QTimer(self)

        self._render_timer.timeout.connect(self.update)

        self._render_timer.start(16)

    def initializeGL(self) -> None:

        self.renderer.initialize()

    def resizeGL(self, w: int, h: int) -> None:

        self.renderer.resize(w, h)

    def _safe_update(self) -> None:

        try:

            self.update()

        except Exception:

            pass

    def paintGL(self) -> None:

        self.performance_monitor.start_frame()

        self.renderer.render()

        self._update_scene_performance_data()

        self.performance_monitor.end_frame()

        if self.core.screen_closing or self.core.game_completed:

            self._draw_screen_close_animation()

    def _update_scene_performance_data(self):
        """Update performance monitoring with current scene data"""

        self.performance_monitor.update_scene_data(

            walls_rendered=len(self.core.walls),

            coins=len(self.core.coins),

            ghosts=len(self.core.ghosts),

            spike_traps=len(self.core.spikes),

            moving_platforms=len(self.core.platforms)

        )

        if self.performance_monitor.resolution == (0, 0):

            self.performance_monitor.set_resolution(
                self.width(), self.height())

        if self.core.game_completed:

            self.performance_monitor.end_gameplay()

            self.performance_monitor.freeze_stats()

    def _draw_screen_close_animation(self) -> None:
        """Draw black bars closing from top and bottom, then congratulations screen"""

        from PySide6.QtGui import QPainter, QColor, QFont

        from PySide6.QtCore import Qt

        painter = QPainter(self)

        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()

        height = self.height()

        progress = self.core.screen_close_progress

        if progress < 1.0:

            bar_height = int(height * progress * 0.5)

            painter.fillRect(0, 0, width, bar_height, QColor(0, 0, 0))

            painter.fillRect(0, height - bar_height, width,
                             bar_height, QColor(0, 0, 0))

        else:

            painter.fillRect(0, 0, width, height, QColor(0, 0, 0))

            if getattr(self, '_show_the_end', False):

                painter.setPen(QColor(255, 255, 255))

                font = QFont('Arial', 68, QFont.Bold)

                painter.setFont(font)

                painter.drawText(0, 0, width, height,
                                 Qt.AlignCenter, 'THE END')

                if self._modal_visible:

                    self._draw_modal(painter)

                painter.end()

                return

            painter.setPen(QColor(255, 255, 255))

            font = QFont("Arial", 36, QFont.Bold)

            painter.setFont(font)

            congrats_text = "CONGRATULATIONS!"

            congrats_rect = painter.boundingRect(
                0, 0, width, height, Qt.AlignCenter, congrats_text)

            painter.drawText(0, 40, width, 80, Qt.AlignCenter, congrats_text)

            font.setPointSize(18)

            painter.setFont(font)

            painter.drawText(0, 100, width, 40, Qt.AlignCenter,
                             f"Time: {self.core.elapsed_s:.1f} seconds")

            font.setPointSize(16)

            painter.setFont(font)

            coins_text = f"Coins Collected: {self.core.coins_collected}/{self.core.coins_required}"

            keys_text = f"Keys Collected: {self.core.keys_collected}/{self.core.keys_required}"

            painter.drawText(0, 140, width, 35, Qt.AlignCenter, coins_text)

            painter.drawText(0, 165, width, 35, Qt.AlignCenter, keys_text)

            font.setPointSize(11)

            font.setFamily('Courier New')

            painter.setFont(font)

            gameplay_metrics = {

                'Coins Collected': f"{self.core.coins_collected}/{self.core.coins_required}",

                'Keys Collected': f"{self.core.keys_collected}/{self.core.keys_required}",

                'Jail Entries': str(self.core.jail_entries),

                'Avg Coin Collection Time': f"{self.core.avg_coin_time:.1f}s"

            }

            summary_text = self.performance_monitor.format_summary_text(
                gameplay_metrics)

            stats_y = 200

            line_height = 15

            lines = summary_text.split('\n')

            for i, line in enumerate(lines):

                if stats_y + i * line_height < height - 15:

                    painter.drawText(30, stats_y + i * line_height,
                                     width - 60, line_height, Qt.AlignLeft, line)

        if self._modal_visible:

            self._draw_modal(painter)

        painter.end()

    def enqueue_lore_lines(self, lines: list[str]) -> None:

        for ln in (lines or []):

            s = str(ln or '').strip()

            if not s:

                continue

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

        if self._lore_current:

            return True

        return bool(self._lore_queue)

    def _draw_lore_fade(self, painter: QPainter) -> None:

        if not self._lore_current:

            if self._lore_queue:

                self._advance_lore_line()

            else:

                return

        now = time.perf_counter()

        if now >= self._lore_current_end:

            if not self._lore_current:

                return

            self._lore_current = ''
            self._lore_current_start = 0.0
            self._lore_current_end = 0.0
            self._safe_update()
            return

        duration = max(0.01, self._lore_current_end - self._lore_current_start)

        t = max(0.0, min(1.0, (now - self._lore_current_start) / duration))

        fade = 0.18

        if t < fade:

            a = t / fade

        elif t > 1.0 - fade:

            a = (1.0 - t) / fade

        else:

            a = 1.0

        alpha = int(230 * max(0.0, min(1.0, a)))

        if alpha <= 0:

            return

        w = self.width()

        h = self.height()

        painter.setFont(QFont('Segoe UI', 18))

        text = self._lore_current

        fm = painter.fontMetrics()

        tw = min(w - 80, fm.horizontalAdvance(text))

        th = fm.height()

        bx = (w - tw) // 2

        by = int(h * 0.56)

        # Draw outlined text (no background box)

        outline = QPen(QColor(0, 0, 0, alpha))

        outline.setWidth(3)

        painter.setPen(outline)

        for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):

            painter.drawText(bx + ox, by + oy, tw, th +
                             4, Qt.AlignCenter, text)

        painter.setPen(QColor(255, 255, 255, alpha))

        painter.drawText(bx, by, tw, th + 4, Qt.AlignCenter, text)

    def hide_mouse_capture(self) -> None:

        try:

            self._mouse_captured = False

            self._center_global = None

            self.setCursor(Qt.ArrowCursor)

        except Exception:

            pass

    def show_level_select_modal(self, *, unlocked: set[str], allow_close: bool, return_to_pause: bool) -> None:

        self._level_select_unlocked = set(unlocked or {'level1'})

        if 'level1' not in self._level_select_unlocked:

            self._level_select_unlocked.add('level1')

        self._modal_visible = True

        self._modal_kind = 'level_select'

        self._modal_title = 'Select Level'

        self._modal_body = 'Level 2 is locked until you complete Level 1.\nEntering a level always starts fresh.'

        self._modal_allow_close = bool(allow_close)

        self._modal_return_to_pause = bool(return_to_pause)

        self._modal_btn_rects.clear()

        self._safe_update()

    def show_tutorial_modal(self, *, title: str, body: str) -> None:

        self._modal_visible = True

        self._modal_kind = 'tutorial'

        self._modal_title = str(title or 'Tutorial')

        self._modal_body = str(body or '')

        self._modal_allow_close = True

        self._modal_return_to_pause = False

        self._modal_btn_rects.clear()

        self._safe_update()

    def hide_modal(self) -> None:

        self._modal_visible = False

        self._modal_kind = ''

        self._modal_title = ''

        self._modal_body = ''

        self._modal_btn_rects.clear()

        self._modal_allow_close = True

        self._modal_return_to_pause = False

        self._safe_update()

    def _draw_modal(self, painter: QPainter) -> None:

        w = self.width()

        h = self.height()

        if self._modal_kind == 'level_select':

            painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 255))

        else:

            painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 160))

        if self._modal_kind == 'level_select':

            self._draw_level_select_overlay(painter)

            return

        panel_w = min(840, int(w * 0.74))

        panel_h = min(440, int(h * 0.56))

        x0 = (w - panel_w) // 2

        y0 = (h - panel_h) // 2

        painter.fillRect(x0, y0, panel_w, panel_h, QColor(18, 18, 22, 245))

        painter.setPen(QColor(235, 235, 235))

        painter.drawRect(x0, y0, panel_w, panel_h)

        # Title

        painter.setFont(QFont('Segoe UI', 18, QFont.Bold))

        painter.drawText(x0 + 24, y0 + 44, panel_w - 48, 28,
                         Qt.AlignLeft, self._modal_title)

        # Close button

        close_size = 32

        close_x = x0 + panel_w - 24 - close_size

        close_y = y0 + 22

        self._modal_btn_rects['close'] = (
            close_x, close_y, close_size, close_size)

        if self._modal_allow_close:

            painter.setPen(QColor(220, 220, 220))

        else:

            painter.setPen(QColor(120, 120, 120))

        painter.drawRect(close_x, close_y, close_size, close_size)

        painter.drawLine(close_x + 7, close_y + 7, close_x +
                         close_size - 7, close_y + close_size - 7)

        painter.drawLine(close_x + close_size - 7, close_y + 7,
                         close_x + 7, close_y + close_size - 7)

        # Body

        painter.setFont(QFont('Segoe UI', 14))

        painter.setPen(QColor(220, 220, 220))

        body_rect_x = x0 + 24

        body_rect_y = y0 + 84

        body_rect_w = panel_w - 48

        body_rect_h = panel_h - 150

        painter.drawText(body_rect_x, body_rect_y, body_rect_w,
                         body_rect_h, Qt.AlignLeft | Qt.TextWordWrap, self._modal_body)

    def _draw_level_select_overlay(self, painter: QPainter) -> None:

        w = self.width()

        h = self.height()

        self._modal_btn_rects.clear()

        painter.setPen(QColor(240, 240, 240))

        painter.setFont(QFont('Segoe UI', 28, QFont.Bold))

        painter.drawText(0, int(h * 0.14), w, 48, Qt.AlignCenter,
                         self._modal_title or 'Select Level')

        painter.setFont(QFont('Segoe UI', 13))

        painter.setPen(QColor(200, 200, 200))

        painter.drawText(0, int(h * 0.14) + 54, w, 40,
                         Qt.AlignCenter, self._modal_body or '')

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

            painter.setFont(QFont('Segoe UI', 18, QFont.Bold))

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

        if self._modal_allow_close:

            painter.setPen(QColor(220, 220, 220))

        else:

            painter.setPen(QColor(120, 120, 120))

        painter.drawRect(close_x, close_y, close_size, close_size)

        painter.drawLine(close_x + 9, close_y + 9, close_x +
                         close_size - 9, close_y + close_size - 9)

        painter.drawLine(close_x + close_size - 9, close_y + 9,
                         close_x + 9, close_y + close_size - 9)

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

        title_font = QFont('Segoe UI', 22)

        title_font.setBold(True)

        painter.setFont(title_font)

        painter.setPen(QColor(255, 220, 110))

        painter.drawText(x0, y0 + 48, panel_w, 32, Qt.AlignCenter, 'PAUSED')

        painter.setFont(self._hud_font)

        painter.setPen(QColor(235, 235, 235))

        fps = self.performance_monitor.stable_fps(update_interval_s=2.5)

        lat = self.performance_monitor.avg_input_latency_ms()

        ram = self.performance_monitor.current_ram_mb()

        stats_x = x0 + 36

        stats_y = y0 + 96

        line_h = 24

        painter.drawText(stats_x, stats_y + line_h * 0, f'FPS: {int(fps)}')

        painter.drawText(stats_x, stats_y + line_h * 1,
                         f'Avg input latency: {lat:.1f} ms')

        painter.drawText(stats_x, stats_y + line_h *
                         2, f'RAM usage: {ram:.1f} MB')

        btn_w = 280

        btn_h = 48

        gap = 16

        center_x = x0 + (panel_w - btn_w) // 2

        top_btn_y = y0 + 200

        buttons = [

            ('resume', 'Resume', center_x, top_btn_y + (btn_h + gap) * 0),

            ('levels', 'Levels', center_x, top_btn_y + (btn_h + gap) * 1),

            ('save', 'Save Game', center_x, top_btn_y + (btn_h + gap) * 2),

            ('save_exit', 'Save + Exit', center_x, top_btn_y + (btn_h + gap) * 3),

            ('restart', 'Restart', center_x, top_btn_y + (btn_h + gap) * 4),

            ('exit', 'Exit (No Save)', center_x, top_btn_y + (btn_h + gap) * 5),

        ]

        self._pause_btn_rects.clear()

        for key, label, bx, by in buttons:

            self._pause_btn_rects[key] = (bx, by, btn_w, btn_h)

            painter.fillRect(bx, by, btn_w, btn_h, QColor(32, 32, 40, 235))

            painter.setPen(QColor(220, 220, 220))

            painter.drawRect(bx, by, btn_w, btn_h)

            painter.setPen(QColor(255, 255, 255))

            painter.drawText(bx, by, btn_w, btn_h, Qt.AlignCenter, label)

    def paintEvent(self, event):

        super().paintEvent(event)

        # Atmosphere overlays (on top of 3D scene, under HUD)

        if not (self.core.screen_closing or self.core.game_completed):

            try:

                painter = QPainter(self)

                painter.setRenderHint(QPainter.Antialiasing, True)

                w = self.width()

                h = self.height()

                # Circular vignette: clear in the center, fades to dark edges.

                cx = w * 0.5

                cy = h * 0.52

                r_inner = 0.32 * min(w, h)

                r_outer = 0.74 * min(w, h)

                vign = QRadialGradient(
                    QPointF(cx, cy), r_outer, QPointF(cx, cy))

                vign.setColorAt(0.0, QColor(0, 0, 0, 0))

                vign.setColorAt(
                    max(0.01, min(0.95, r_inner / r_outer)), QColor(0, 0, 0, 0))

                vign.setColorAt(1.0, QColor(0, 0, 0, 190))

                painter.fillRect(0, 0, w, h, vign)

                # Subtle animated fog/noise in the vignette (very light).

                t = time.perf_counter()

                fog = QRadialGradient(QPointF(cx + 18.0 * math.sin(t * 0.35),
                                      cy + 14.0 * math.cos(t * 0.31)), r_outer * 1.02, QPointF(cx, cy))

                fog.setColorAt(0.0, QColor(0, 0, 0, 0))

                fog.setColorAt(0.55, QColor(0, 0, 0, 0))

                fog.setColorAt(1.0, QColor(0, 0, 0, 32))

                painter.fillRect(0, 0, w, h, fog)

                painter.end()

            except Exception:

                pass

        self._draw_hud()

    def _draw_hud(self) -> None:

        if self.core.screen_closing or self.core.game_completed:

            # End screen is rendered in paintGL() via _draw_screen_close_animation().

            # We only draw modals on top if one is visible.

            if self._modal_visible:

                painter = QPainter(self)

                painter.setRenderHint(QPainter.Antialiasing, True)

                self._draw_modal(painter)

                painter.end()

            return

        painter = QPainter(self)

        painter.setRenderHint(QPainter.Antialiasing, True)

        painter.setFont(self._hud_font)

        # objective HUD

        w = self.width()

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

        mm = t // 60

        ss = t % 60

        painter.drawText(x + 12, y + 22, f'Time: {mm:02d}:{ss:02d}')

        # Time penalty popup (e.g. +30 from timer ghost)

        nowp = time.perf_counter()

        if self._time_bonus_text and nowp < self._time_bonus_until:

            painter.setFont(QFont('Segoe UI', 22, QFont.Bold))

            painter.setPen(QColor(255, 220, 60))

            painter.drawText(x + 210, y + 8, 120, 36, Qt.AlignLeft |
                             Qt.AlignVCenter, self._time_bonus_text)

        elif self._time_bonus_text and nowp >= self._time_bonus_until:

            self._time_bonus_text = ''

        painter.setFont(self._hud_font)

        painter.setPen(QColor(240, 240, 240))

        painter.drawText(
            x + 12, y + 44, f'Coins: {self.core.coins_collected}/{self.core.coins_required}   Keys: {self.core.keys_collected}/{self.core.keys_required}')

        # minimap icon

        icon_size = 54

        ix = self.width() - icon_size - 16

        iy = self.height() - icon_size - 16

        self._cam_icon_rect = (ix, iy, icon_size, icon_size)

        now = time.perf_counter()

        on_cd = now < self._minimap_cooldown_until

        painter.fillRect(ix - 6, iy - 6, icon_size + 12,
                         icon_size + 12, QColor(0, 0, 0, 130))

        painter.setPen(QColor(220, 220, 220))

        painter.drawRect(ix - 6, iy - 6, icon_size + 12, icon_size + 12)

        if not self._cam_icon.isNull():

            painter.drawImage(ix, iy, self._cam_icon.scaled(
                icon_size, icon_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))

        else:

            painter.fillRect(ix, iy, icon_size, icon_size,
                             QColor(120, 120, 120))

        if on_cd:

            remaining = max(0.0, self._minimap_cooldown_until - now)

            painter.fillRect(ix, iy, icon_size, icon_size,
                             QColor(0, 0, 0, 160))

            painter.setPen(QColor(255, 210, 90))

            painter.drawText(ix + 10, iy + 32, f'{int(math.ceil(remaining))}s')

        # minimap - 10s

        if now < self._minimap_until:

            self._draw_minimap_overlay(painter)

        # Sector popup (bottom-center)

        popup_t = float(getattr(self.core, '_sector_popup_timer', 0.0) or 0.0)

        popup_id = str(getattr(self.core, '_sector_popup_id', '') or '')

        if popup_t > 0.0 and popup_id:

            fade_in = 0.25

            fade_out = 0.5

            total = 2.0

            alpha = 1.0

            if popup_t > (total - fade_in):

                alpha = max(
                    0.0, min(1.0, (total - popup_t) / max(0.001, fade_in)))

            elif popup_t < fade_out:

                alpha = max(0.0, min(1.0, popup_t / max(0.001, fade_out)))

            text = f'SECTOR {popup_id}'

            painter.setFont(self._hud_font_bold)

            tw = painter.fontMetrics().horizontalAdvance(text)

            th = painter.fontMetrics().height()

            bx = (self.width() - tw) // 2

            by = self.height() - 25

            pad = 10

            painter.fillRect(bx - pad, by - th, tw + pad * 2,
                             th + 10, QColor(0, 0, 0, int(150 * alpha)))

            painter.setPen(QColor(255, 220, 110, int(255 * alpha)))

            painter.drawText(bx, by, text)

        if self._modal_visible:

            self._draw_modal(painter)

        self._draw_lore_fade(painter)

        # Pause panel must render last (overlay)

        if (not self._modal_visible) and getattr(self.core, 'paused', False):

            self._draw_pause_panel(painter)

        painter.end()

    def _draw_minimap_overlay(self, painter: QPainter) -> None:

        # calculate actual maze content area

        maze_rows = len(self.core.layout)

        maze_cols = len(self.core.layout[0]) if maze_rows > 0 else 0

        # calculate cell size to fit entire maze

        max_cell_width = int(self.width() * 0.85 / maze_cols)

        max_cell_height = int((self.height() - 40) / maze_rows)

        cell_px = min(max_cell_width, max_cell_height)

        # calculate actual maze content dimensions

        maze_content_width = maze_cols * cell_px

        maze_content_height = maze_rows * cell_px

        # center the maze content area

        x0 = (self.width() - maze_content_width) // 2

        y0 = 20 + ((self.height() - 40) - maze_content_height) // 2

        painter.fillRect(x0, y0, maze_content_width,
                         maze_content_height, QColor(10, 10, 12, 210))

        painter.setPen(QColor(230, 230, 230))

        painter.drawRect(x0, y0, maze_content_width, maze_content_height)

        def to_screen(r: float, c: float) -> tuple[float, float]:

            sx = x0 + c * cell_px

            sy = y0 + r * cell_px

            return sx, sy

        # draw maze (walls/floors)

        for r in range(maze_rows):

            for c in range(maze_cols):

                rx, ry = to_screen(r, c)

                w = int(cell_px + 1)

                h = int(cell_px + 1)

                if (r, c) in self.core.walls:

                    painter.fillRect(int(rx), int(ry), w,
                                     h, QColor(45, 45, 55))

                elif (r, c) in self.core.floors:

                    painter.fillRect(int(rx), int(ry), w, h,
                                     QColor(125, 125, 135))

                else:

                    painter.fillRect(int(rx), int(ry), w,
                                     h, QColor(15, 15, 18))

        # player on minimap

        pr, pc = int(self.core.player.z), int(self.core.player.x)

        px, py = to_screen(pr + 0.5, pc + 0.5)

        player_size = max(12, int(cell_px * 0.7))

        painter.setPen(QPen(QColor(0, 255, 0), 2))  # outline

        painter.setBrush(QColor(50, 255, 50))  # fill

        half_size = player_size / 2

        diamond_points = [

            QPointF(px, py - half_size),        # Top

            QPointF(px + half_size, py),        # Right

            QPointF(px, py + half_size),        # Bottom

            QPointF(px - half_size, py),        # Left

        ]

        painter.drawPolygon(QPolygonF(diamond_points))

        center_size = player_size * 0.4

        painter.setPen(QPen(QColor(255, 255, 255), 1))  # White outline

        painter.setBrush(QColor(255, 255, 255))  # White fill

        painter.drawEllipse(int(px - center_size / 2), int(py - center_size / 2),

                            int(center_size), int(center_size))

        # Coins

        coin_size = max(6, int(cell_px * 0.35))

        painter.setPen(QPen(QColor(255, 200, 0), 1))

        painter.setBrush(QColor(255, 215, 0))

        for coin in self.core.coins.values():

            if coin.taken:

                continue

            r, c = coin.cell

            cx, cy = to_screen(r + 0.5, c + 0.5)

            painter.drawEllipse(int(cx - coin_size / 2),
                                int(cy - coin_size / 2), coin_size, coin_size)

        # ghosts

        ghost_colors = {

            1: QColor(255, 80, 60),   # Red

            2: QColor(80, 255, 140),   # Green

            3: QColor(110, 170, 255),  # Blue

            4: QColor(255, 220, 80),  # Yellow

            5: QColor(255, 90, 255),  # Magenta

        }

        ghost_size = max(10, int(cell_px * 0.6))

        for ghost in self.core.ghosts.values():

            r = ghost.z

            c = ghost.x

            ghost_color = ghost_colors.get(ghost.id, QColor(255, 120, 30))

            s = float(getattr(ghost, 'size_scale', 1.0) or 1.0)

            gsz = int(max(8, ghost_size * s))

            # Draw ghost body

            painter.setPen(QPen(ghost_color.darker(150), 1))

            painter.setBrush(ghost_color)

            sx, sy = to_screen(r + 0.5, c + 0.5)

            painter.drawEllipse(int(sx - gsz / 2), int(sy - gsz / 2), gsz, gsz)

            # Draw eyes

            eye_size = max(2, int(gsz * 0.15))

            eye_offset_x = gsz * 0.25

            eye_offset_y = gsz * 0.1

            # left eye

            painter.setPen(QPen(QColor(0, 0, 0), 1))

            painter.setBrush(QColor(255, 255, 255))

            left_eye_x = sx - eye_offset_x

            left_eye_y = sy - eye_offset_y

            painter.drawEllipse(int(left_eye_x - eye_size / 2),
                                int(left_eye_y - eye_size / 2), eye_size, eye_size)

            # right eye

            right_eye_x = sx + eye_offset_x

            right_eye_y = sy - eye_offset_y

            painter.drawEllipse(int(right_eye_x - eye_size / 2),
                                int(right_eye_y - eye_size / 2), eye_size, eye_size)

            # Eyes

            painter.setPen(Qt.NoPen)

            painter.setBrush(QColor(0, 0, 0))

            pupil_size = max(1, int(eye_size * 0.5))

            painter.drawEllipse(int(left_eye_x - pupil_size / 2),
                                int(left_eye_y - pupil_size / 2), pupil_size, pupil_size)

            painter.drawEllipse(int(right_eye_x - pupil_size / 2),
                                int(right_eye_y - pupil_size / 2), pupil_size, pupil_size)

        # Minimap countdown

        current_time = time.perf_counter()

        if current_time < self._minimap_until:

            remaining = max(0.0, self._minimap_until - current_time)

            # countdown

            painter.setFont(self._hud_font_bold)

            countdown_text = f"MAP: {int(remaining + 0.5)}s"

            text_width = painter.fontMetrics().horizontalAdvance(countdown_text)

            text_height = painter.fontMetrics().height()

            countdown_x = x0 + maze_content_width - text_width - 10

            countdown_y = y0 + text_height + 5

            painter.fillRect(countdown_x - 3, countdown_y - text_height + 3,
                             text_width + 6, text_height + 3, QColor(0, 0, 0, 180))

            painter.setPen(QColor(255, 255, 255))

            painter.drawText(countdown_x, countdown_y, countdown_text)

    def _try_open_minimap(self) -> None:

        now = time.perf_counter()

        if now < self._minimap_cooldown_until:

            return

        self._minimap_until = now + 10.0

        self._minimap_cooldown_until = now + 30.0

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

            # if click is on the minimap icon, trigger minimap and do NOT capture mouse

            ix, iy, iw, ih = getattr(self, '_cam_icon_rect', (0, 0, 0, 0))

            if ix <= event.position().x() <= ix + iw and iy <= event.position().y() <= iy + ih:

                self._try_open_minimap()

                return

            self._mouse_captured = True

            self._center_global = self.mapToGlobal(self.rect().center())

            self.setCursor(Qt.BlankCursor)

            self.cursor().setPos(self._center_global)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:

        if event.button() == Qt.LeftButton:

            # if click was on minimap icon, keep mouse capture asis and just trigger minimap

            ix, iy, iw, ih = getattr(self, '_cam_icon_rect', (0, 0, 0, 0))

            if ix <= event.position().x() <= ix + iw and iy <= event.position().y() <= iy + ih:

                self._try_open_minimap()

                return

            self._mouse_captured = False

            self.setCursor(Qt.ArrowCursor)

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


class PySide6GameWindow(QMainWindow):

    def __init__(self):

        super().__init__()

        self._progress_path = os.path.abspath('progression.json')

        self._progress = self._load_progression()

        unlocked = set(self._progress.get('unlocked_levels') or [])

        last_level = str(self._progress.get('last_level') or 'level1')

        if last_level not in unlocked:

            last_level = 'level1'

        self._save_path = os.path.abspath('savegame.json')

        # Auto-resume rule:

        # - If a Level 1 save exists AND last_level is level1, boot directly into that save (no level select).

        # - Otherwise follow progression (Level Select for Level 1, direct boot for Level 2).

        autoload_level1_save = False

        if last_level == 'level1' and os.path.exists(self._save_path):

            autoload_level1_save = True

        self.core = GameCore(level_id=last_level)

        self._current_level_id = last_level

        self._asset_dir = os.path.abspath('assets')

        _INFINITE_LOOPS = 999999999

        self._sfx_footsteps = QSoundEffect(self)
        self._sfx_footsteps.setSource(QUrl.fromLocalFile(
            os.path.join(self._asset_dir, 'running-on-concrete-268478.wav')))
        self._sfx_footsteps.setVolume(0.22)
        self._sfx_footsteps.setLoopCount(_INFINITE_LOOPS)

        self._sfx_coin = QSoundEffect(self)
        self._sfx_coin.setSource(QUrl.fromLocalFile(
            os.path.join(self._asset_dir, 'drop-coin-384921.wav')))
        self._sfx_coin.setVolume(0.55)

        self._sfx_gate = QSoundEffect(self)
        self._sfx_gate.setSource(QUrl.fromLocalFile(
            os.path.join(self._asset_dir, 'closing-metal-door-44280.wav')))
        self._sfx_gate.setVolume(0.55)

        self._sfx_ghost = QSoundEffect(self)
        self._sfx_ghost.setSource(QUrl.fromLocalFile(
            os.path.join(self._asset_dir, 'ghost-horror-sound-382709.wav')))
        self._sfx_ghost.setVolume(0.40)
        self._footsteps_playing = False
        self._door_sound_played = False

        self._ghost_sound_timer = QTimer(self)

        self._ghost_sound_timer.timeout.connect(self._play_ghost_sound)

        self._ghost_sound_timer.start(2500)

        self._key_minigame_open = False

        self._assembly_minigame: Optional[Assembly3DMinigame] = None

        self._register_core_callbacks()

        self.setWindowTitle('Within the Walls (PySide6)')

        self.resize(1280, 800)

        self.keys_pressed: set[int] = set()

        self.gl = GameGLWidget(self.core)

        self.setCentralWidget(self.gl)

        self._lore_seen: set[str] = set()

        self._lore_flags: dict[str, bool] = {}

        self._minimap_used = 0

        self._tutorial_seen: dict[str, bool] = {}

        # Persisted "seen" state (saved in savegame.json) so resume doesn't replay tutorials/lore.

        self._persist_seen: dict[str, bool] = {}

        self._pending_gameplay_tutorial = False

        # Startup behavior:

        # - First boot / Level 1: show level select first.

        # - After the player has entered Level 2 at least once, restart resumes directly into Level 2.

        if self._current_level_id == 'level2':

            self._set_paused(False)

            self._start_level(
                'level2', load_save=os.path.exists(self._save_path))

        elif autoload_level1_save:

            self._set_paused(False)

            self._start_level('level1', load_save=True)

        else:

            self._open_level_select_modal(startup=True)

        self.gl.mouse_moved.connect(self._on_mouse_look)

        self._tick = QTimer(self)

        self._tick.timeout.connect(self._update_game)

        self._tick.start(16)

        self.setFocusPolicy(Qt.StrongFocus)

        # With the new level system, entering a level always starts fresh.

        # We keep Save Game for convenience. If a save exists and the last level is Level 1,

        # we auto-load it so the player can continue progress.

    def _register_core_callbacks(self) -> None:

        self.core.register_event_callback('coin_picked', self._on_coin_picked)

        self.core.register_event_callback('gate_opened', self._on_gate_moved)

        self.core.register_event_callback('gate_closed', self._on_gate_moved)

        self.core.register_event_callback(
            'key_fragment_encountered', self._on_key_fragment_encountered)

        self.core.register_event_callback('game_won', self._on_game_won)

        self.core.register_event_callback(
            'checkpoint_reached', self._on_checkpoint_reached)

        self.core.register_event_callback(
            'time_penalty', self._on_time_penalty)

        self.core.register_event_callback(
            'exit_unlocked', self._on_exit_unlocked)

        self.core.register_event_callback(
            'sector_entered', self._on_sector_entered)

        self.core.register_event_callback(
            'sent_to_jail', self._on_sent_to_jail)

        self.core.register_event_callback('left_jail', self._on_left_jail)

        self.core.register_event_callback('key_picked', self._on_key_picked)

        self.core.register_event_callback(
            'player_move', self._on_player_move_event)

    def _safe_gl_update(self) -> None:

        try:

            self.gl.update()

        except Exception:

            pass

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

    def _open_level_select_modal(self, *, startup: bool) -> None:

        unlocked = set(self._progress.get('unlocked_levels') or [])

        self._set_paused(True)

        try:

            self.gl.hide_mouse_capture()

        except Exception:

            pass

        self.gl.show_level_select_modal(unlocked=unlocked, allow_close=(
            not startup), return_to_pause=(not startup))

    def _on_level_selected(self, level_id: str) -> None:

        self.gl.hide_modal()

        self._set_paused(False)

        # Persist "last_level" so restarting the game can resume at Level 2.

        try:

            self._progress['last_level'] = str(level_id)

            self._save_progression()

        except Exception:

            pass

        # Selecting a level always starts fresh; do NOT load a previous Level 1 save.

        self._start_level(level_id, load_save=False)

    def _start_level(self, level_id: str, *, load_save: bool) -> None:

        level_id = str(level_id or 'level1')

        paused_was = bool(getattr(self.core, 'paused', False))

        self.core = GameCore(level_id=level_id)

        self._current_level_id = level_id

        self.gl.core = self.core

        # Reset per-level lore flags.

        for k in ('coins_half', 'ghost_close', 'l2_frags_done', 'l2_sector_f_done'):

            self._lore_flags.pop(k, None)

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

        if paused_was:

            self._set_paused(True)

        self._last_update_time = time.perf_counter()

        # Door sound should only play for a fresh run (timer starts at 00:00), not on save resume.

        if (not load_save) and float(getattr(self.core, 'elapsed_s', 0.0) or 0.0) <= 0.0001:

            self._play_sfx(self._sfx_gate)

        self._safe_gl_update()

        if level_id == 'level2' and load_save:

            self._load_save_if_present()

        if level_id == 'level1' and load_save:

            # Resume from save.

            self._load_save_if_present()

        if level_id == 'level1':

            # Level 1 intro flow: one lore thought, then the single Gameplay tutorial modal.

            # Only show on a fresh start (timer at 00:00).

            if float(getattr(self.core, 'elapsed_s', 0.0) or 0.0) <= 0.0001:

                if not self._persist_seen.get('l1_intro'):

                    self._persist_seen['l1_intro'] = True

                    self._show_lore_line('A basement? This feels like a test.')

                    self._pending_gameplay_tutorial = True

        if level_id == 'level2':

            # Level 2 entry lore (no tutorials in Level 2) - only on a fresh run.

            if float(getattr(self.core, 'elapsed_s', 0.0) or 0.0) <= 0.0001:

                if not self._persist_seen.get('l2_intro'):

                    self._persist_seen['l2_intro'] = True

                    self._show_lore_line('This place feels inhabited.')

    def _on_game_won(self, data: dict) -> None:

        if str(getattr(self, '_current_level_id', '')) != 'level1':

            return

        unlocked = set(self._progress.get('unlocked_levels') or [])

        if 'level2' in unlocked:

            return

        unlocked.add('level2')

        self._progress['unlocked_levels'] = sorted(unlocked)

        self._save_progression()

    def _on_checkpoint_reached(self, data: dict) -> None:

        # Freeze player input, but allow the end-screen animation to progress.

        self._set_paused(True)

        self._last_update_time = time.perf_counter()

        self._safe_gl_update()

    def _on_mouse_look(self, dx: float, dy: float) -> None:

        sensitivity = 0.002

        self.core.rotate_player(-dx * sensitivity)

        self.core.tilt_camera(-dy * sensitivity)

    def keyPressEvent(self, event: QKeyEvent) -> None:

        # record input event for performance monitoring

        self.gl.performance_monitor.record_input_event(time.perf_counter())

        self.keys_pressed.add(event.key())

        if event.key() == Qt.Key_E:

            self._handle_interact()

        if event.key() == Qt.Key_Escape:

            # If a modal is open, Esc closes it.

            if getattr(self.gl, '_modal_visible', False):

                self._on_modal_close_clicked()

                return

            # If we're on the end/stats screen, Esc should open the level select.

            if self.core.screen_closing or self.core.game_completed:

                if str(getattr(self, '_current_level_id', '')) == 'level2':

                    self.gl._show_the_end = True

                    self._safe_gl_update()

                    return

                # Ensure Level 2 is unlocked once Level 1 is completed.

                try:

                    if str(getattr(self, '_current_level_id', '')) == 'level1':

                        unlocked = set(self._progress.get(
                            'unlocked_levels') or [])

                        if 'level2' not in unlocked:

                            unlocked.add('level2')

                            self._progress['unlocked_levels'] = sorted(
                                unlocked)

                            self._save_progression()

                except Exception:

                    pass

                self._open_level_select_modal(startup=False)

                return

            self._toggle_pause()

            return

        if getattr(self.gl, '_modal_visible', False):

            return

        if event.key() == Qt.Key_M:

            self.gl._try_open_minimap()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:

        self.keys_pressed.discard(event.key())

    def _update_game(self) -> None:

        # Record input response for performance monitoring

        self.gl.performance_monitor.record_input_response(time.perf_counter())

        if not hasattr(self, '_last_update_time'):

            self._last_update_time = time.perf_counter()

            return

        current_time = time.perf_counter()

        dt = current_time - self._last_update_time

        self._last_update_time = current_time

        dt = min(dt, 0.1)

        paused = bool(getattr(self.core, 'paused', False))

        # If we're in the end-screen close sequence, the animation must still advance,

        # even though gameplay input is frozen.

        if self.core.screen_closing and (not self.core.game_won):

            self.core._update_screen_close(dt)

        elif not paused:

            self.core.update(dt)

        if (not getattr(self.core, 'paused', False)) and (not getattr(self.gl, '_modal_visible', False)):

            self._poll_lore_triggers()

        if self._pending_gameplay_tutorial and (not getattr(self.gl, '_modal_visible', False)):

            if not self.gl.is_lore_playing():

                self._pending_gameplay_tutorial = False

                if (self._current_level_id == 'level1') and (not self._persist_seen.get('tutorial_gameplay')):

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

        if self._key_minigame_open and bool(getattr(self.core, 'simulation_frozen', False)):

            self._safe_gl_update()

        move_speed = 0.18 if str(
            getattr(self, '_current_level_id', '')) == 'level1' else 0.30

        dx = 0.0

        dz = 0.0

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

                self._set_footsteps_playing(True)

            else:

                self._set_footsteps_playing(False)

        else:

            self._set_footsteps_playing(False)

    def _set_footsteps_playing(self, playing: bool) -> None:

        if playing == self._footsteps_playing:

            return

        self._footsteps_playing = playing

        if playing:
            self._sfx_footsteps.play()
        else:
            self._sfx_footsteps.stop()

    def _play_sfx(self, sfx: QSoundEffect) -> None:
        sfx.stop()
        sfx.play()

    def _on_coin_picked(self, data: dict) -> None:
        self._play_sfx(self._sfx_coin)

        try:

            if float(self.core.coins_collected) >= float(self.core.coins_required) * 0.5:

                key = f'coins_half_{self._current_level_id}'

                if (not self._lore_flags.get('coins_half')) and (not self._persist_seen.get(key)):

                    self._lore_flags['coins_half'] = True

                    self._persist_seen[key] = True

                    if self._current_level_id == 'level1':

                        self._show_lore_line('Halfway.')

                    elif self._current_level_id == 'level2':

                        self._show_lore_line(
                            'The maze likes it when I collect.')

        except Exception:

            pass

    def _on_gate_moved(self, data: dict) -> None:
        self._play_sfx(self._sfx_gate)

    def _on_exit_unlocked(self, data: dict) -> None:

        # No messaging for this in the simplified spec.

        return

    def _on_sector_entered(self, data: dict) -> None:

        sid = str((data or {}).get('id', '') or '')

        if (self._current_level_id == 'level2') and (sid == 'F'):

            try:

                req_met = (int(self.core.coins_collected) >= int(self.core.coins_required)) and (
                    int(self.core.keys_collected) >= int(self.core.keys_required))

            except Exception:

                req_met = False

            if req_met and (not self._lore_flags.get('l2_sector_f_done')):

                self._lore_flags['l2_sector_f_done'] = True

                self._show_lore_line('A dream... Far too lucid.')

    def _on_sent_to_jail(self, data: dict) -> None:

        if self._current_level_id != 'level1':

            return

        # Level 1: jail tutorial only on first entry.

        if not self._persist_seen.get('tutorial_jail'):

            self._persist_seen['tutorial_jail'] = True

            self._show_tutorial_modal(

                'Jail',

                'This is not death.\n'

                'To escape, find the table and press E to interact with the glowing book.\n\n'

                'A sector map is displayed here. Use it to orient yourself before returning to the maze.'

            )

    def _on_left_jail(self, data: dict) -> None:

        # No messaging for this in the simplified spec.

        return

    def _on_key_picked(self, data: dict) -> None:

        try:

            cnt = int((data or {}).get('count', 0) or 0)

            if (self._current_level_id == 'level2') and (cnt >= 3) and (not self._lore_flags.get('l2_frags_done')):

                self._lore_flags['l2_frags_done'] = True

                self._show_lore_line('The key is done... I am watched.')

        except Exception:

            pass

    def _on_player_move_event(self, data: dict) -> None:

        # No messaging for this in the simplified spec.

        return

    def _play_ghost_sound(self) -> None:

        if getattr(self.core, 'paused', False):

            return

        if self.core.game_won or self.core.game_completed:

            return

        if not getattr(self.core, 'ghosts', None):

            return

        px = float(self.core.player.x)

        pz = float(self.core.player.z)

        nearest = None

        for g in self.core.ghosts.values():

            d = math.hypot(float(g.x) - px, float(g.z) - pz)

            if nearest is None or d < nearest:

                nearest = d

        if nearest is None:

            return

        hear_dist = 10.0

        near_dist = 2.5

        if nearest > hear_dist:

            return

        if nearest <= near_dist:

            t = 1.0

        else:

            t = max(0.0, min(1.0, (hear_dist - nearest) / (hear_dist - near_dist)))

        self._sfx_ghost.setVolume(0.06 + 0.55 * t)
        self._play_sfx(self._sfx_ghost)

    def _handle_interact(self) -> None:

        if getattr(self.core, 'paused', False):

            return

        action = self.core.interact()

        if action == 'jail_book':

            self.keys_pressed.clear()

            self._set_footsteps_playing(False)

            self._release_mouse_buttons()

            prev_frozen = bool(getattr(self.core, 'simulation_frozen', False))
            self.core.simulation_frozen = True

            dlg = SilhouetteMatchDialog(self)

            ok = False
            try:
                ok = bool(dlg.exec())
            finally:
                self.core.simulation_frozen = prev_frozen

            if ok:

                self.core.mark_jail_puzzle_success()

                if (self._current_level_id == 'level1') and (not self._lore_flags.get('l1_jail_puzzle_success')):

                    self._lore_flags['l1_jail_puzzle_success'] = True

                    self._show_lore_line(
                        'The maze resets what it cannot control.')

            self._release_mouse_buttons()

            self.keys_pressed.clear()

        elif action == 'exit_locked':

            return

        elif action == 'jail_locked':

            pass

        elif action == 'gate_jail':

            self.core.try_leave_jail()

    def _on_key_fragment_encountered(self, data: dict) -> None:

        if getattr(self.core, 'paused', False):

            return

        if self._key_minigame_open:

            return

        frag_id = str((data or {}).get('id', ''))

        if not frag_id:

            return

        frag_kind = ''

        try:

            frag = getattr(self.core, 'key_fragments', {}).get(frag_id)

            frag_kind = str(getattr(frag, 'kind', '') or '')

        except Exception:

            frag_kind = ''

        self._trigger_lore('ON_KEY_FRAGMENT_DISCOVERED')

        self._key_minigame_open = True

        self.keys_pressed.clear()

        self._set_footsteps_playing(False)

        self._release_mouse_buttons()

        prev_frozen = bool(getattr(self.core, 'simulation_frozen', False))
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
            self.core.simulation_frozen = prev_frozen

        if ok:

            self.core.mark_key_fragment_taken(frag_id)

            self._trigger_lore('ON_ASSEMBLY_SUCCESS')

        else:

            self.core.clear_pending_key_fragment(frag_id)

            self.core.defer_key_fragment(frag_id)

        self._release_mouse_buttons()

        self._key_minigame_open = False

        self.keys_pressed.clear()

    def _release_mouse_buttons(self) -> None:
        """Clear Qt mouse button state and capture to avoid stuck clicks after dialogs."""

        try:

            from PySide6.QtGui import QGuiApplication

            # Query current button state to help Qt reset internal state

            QGuiApplication.mouseButtons()

            # Also ensure our widget isn't stuck in captured mode

            if hasattr(self.gl, '_mouse_captured'):

                self.gl._mouse_captured = False

                self.gl.setCursor(Qt.ArrowCursor)

        except Exception:

            pass

    def _set_paused(self, paused: bool) -> None:

        paused = bool(paused)

        self.core.paused = paused

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

        now_paused = not bool(getattr(self.core, 'paused', False))

        self._set_paused(now_paused)

    def _on_pause_action(self, action: str) -> None:

        if action == 'resume':

            self._toggle_pause()

            return

        if action == 'levels':

            self._toggle_pause()

            self._open_level_select_modal(startup=False)

            return

        if action == 'save':

            self._save_game()

            return

        if action == 'save_exit':

            self._save_game()

            self.close()

            return

        if action == 'exit':

            self.close()

            return

        if action == 'restart':

            self._restart_game()

            return

    def _on_modal_close_clicked(self) -> None:

        if not getattr(self.gl, '_modal_visible', False):

            return

        if not bool(getattr(self.gl, '_modal_allow_close', True)):

            return

        if str(getattr(self.gl, '_modal_kind', '')) == 'level_select' and bool(getattr(self.gl, '_modal_return_to_pause', False)):

            self.gl.hide_modal()

            self._set_paused(True)

            self._safe_gl_update()

            return

        self.gl.hide_modal()

        self._set_paused(False)

    def _show_lore_line(self, text: str) -> None:

        s = str(text or '').strip()

        if not s:

            return

        self.gl.enqueue_lore_lines([s])

    def _show_tutorial_modal(self, title: str, body: str) -> None:

        self._set_paused(True)

        self.gl.show_tutorial_modal(title=title, body=body)

    def _trigger_lore(self, key: str) -> None:

        # Backwards-compatible no-op mapping layer.

        # Lore is now code-driven (no lore.md dependency). Only a small set of keys are supported.

        key = str(key or '').strip()

        if not key:

            return

        if key in self._lore_seen:

            return

        txt: Optional[str] = None

        if key == 'ON_GHOST_CLOSE':

            if self._current_level_id == 'level1':

                txt = 'Why are you here?'

            elif self._current_level_id == 'level2':

                txt = 'Wake me up.'

        elif key == 'COIN_HALF':

            if self._current_level_id == 'level1':

                txt = 'Halfway.'

            elif self._current_level_id == 'level2':

                txt = 'The maze likes it when I collect.'

        if not txt:

            return

        self._lore_seen.add(key)

        self._show_lore_line(txt)

    def _try_trigger_lore(self, key: str) -> None:

        self._trigger_lore(key)

    def _poll_lore_triggers(self) -> None:

        if getattr(self.core, 'paused', False):

            return

        if getattr(self.gl, '_modal_visible', False):

            return

        # Ghost close (distance threshold; once only)

        try:

            nearest = None

            for g in self.core.ghosts.values():

                d = math.hypot(g.x - self.core.player.x,
                               g.z - self.core.player.z)

                if nearest is None or d < nearest:

                    nearest = d

            if nearest is not None and nearest <= 2.0:

                if not self._lore_flags.get('ghost_close'):

                    self._lore_flags['ghost_close'] = True

                    if not self._persist_seen.get(f'ghost_close_{self._current_level_id}'):

                        self._persist_seen[f'ghost_close_{self._current_level_id}'] = True

                        self._trigger_lore('ON_GHOST_CLOSE')

        except Exception:

            pass

    def _save_game(self) -> None:

        try:

            self._progress['last_level'] = str(
                getattr(self, '_current_level_id', 'level1') or 'level1')

            self._save_progression()

        except Exception as e:

            print(f"[save] progression save failed: {e}")

        try:

            state = self.core.get_save_state()

            state['ui_seen'] = dict(self._persist_seen)

            with open(self._save_path, 'w', encoding='utf-8') as f:

                json.dump(state, f, indent=2)

        except Exception as e:

            print(f"[save] savegame write failed: {e}")

    def _load_save_if_present(self) -> None:

        if not os.path.exists(self._save_path):

            return

        try:

            with open(self._save_path, 'r', encoding='utf-8') as f:

                state = json.load(f)

            if isinstance(state, dict):

                saved_level = str(state.get('level_id') or '')

                if saved_level and saved_level != str(getattr(self, '_current_level_id', '') or ''):

                    return

            if isinstance(state, dict):

                seen = state.get('ui_seen')

                if isinstance(seen, dict):

                    self._persist_seen.update(
                        {str(k): bool(v) for k, v in seen.items()})

            self.core.load_save_state(state)

        except Exception as e:

            print(f"[load] savegame load failed: {e}")

            return

    def _restart_game(self) -> None:

        paused_was = bool(getattr(self.core, 'paused', False))

        self.core = GameCore(level_id=str(
            getattr(self, '_current_level_id', 'level1') or 'level1'))

        self.gl.core = self.core

        try:

            # Renderer caches static geometry/display lists based on the core.

            # Recreate it so Restart doesn't render the old world.

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

        if paused_was:

            self._set_paused(True)

        self._last_update_time = time.perf_counter()

        # Restart starts at 00:00 -> play door sound.

        self._play_sfx(self._sfx_gate)

        self._safe_gl_update()

    def _on_time_penalty(self, data: dict) -> None:

        try:

            amount = int((data or {}).get('seconds', 0) or 0)

        except Exception:

            amount = 0

        if amount <= 0:

            return

        # Display as +30 next to the timer for 2.5s

        try:

            self.gl._time_bonus_text = f'+{amount}'

            self.gl._time_bonus_until = time.perf_counter() + 2.5

            self._safe_gl_update()

        except Exception:

            pass


def run() -> int:

    app = QApplication.instance() or QApplication([])

    win = PySide6GameWindow()

    win.show()

    return app.exec()
