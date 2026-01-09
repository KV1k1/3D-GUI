import math
import time
from typing import Optional, Set

from PySide6.QtCore import Qt, Signal, QPointF, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QColor, QFont, QImage, QPen, QPolygonF
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from core.game_core import GameCore
from .renderer_opengl import OpenGLRenderer
from .silhouette_minigame import SilhouetteMatchDialog
from .performance_monitor import PerformanceMonitor
from .assembly3d_minigame import Assembly3DMinigame


class GameGLWidget(QOpenGLWidget):
    mouse_moved = Signal(float, float)

    def __init__(self, core: GameCore):
        super().__init__()
        self.core = core
        self.renderer = OpenGLRenderer(core)
        self.performance_monitor = PerformanceMonitor()

        self._hud_font = QFont('Segoe UI', 10)
        self._hud_font_bold = QFont('Segoe UI', 11)
        self._hud_font_bold.setBold(True)

        self._cam_icon = QImage('assets/cam.jpg')
        self._minimap_until = 0.0
        self._minimap_cooldown_until = 0.0

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
            self.performance_monitor.set_resolution(self.width(), self.height())
        
        if self.core.elapsed_s > 0 and self.performance_monitor.gameplay_start_time is None:
            self.performance_monitor.start_gameplay()
        
        if self.core.game_completed and self.performance_monitor.gameplay_end_time is None:
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
            
            painter.fillRect(0, height - bar_height, width, bar_height, QColor(0, 0, 0))
        else:
            painter.fillRect(0, 0, width, height, QColor(0, 0, 0))
            
            painter.setPen(QColor(255, 255, 255))
            font = QFont("Arial", 36, QFont.Bold)
            painter.setFont(font)
            
            congrats_text = "CONGRATULATIONS!"
            congrats_rect = painter.boundingRect(0, 0, width, height, Qt.AlignCenter, congrats_text)
            painter.drawText(0, 40, width, 80, Qt.AlignCenter, congrats_text)
            
            font.setPointSize(18)
            painter.setFont(font)
            time_text = f"Time: {self.core.elapsed_s:.1f} seconds"
            painter.drawText(0, 100, width, 40, Qt.AlignCenter, time_text)
            
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
            summary_text = self.performance_monitor.format_summary_text(gameplay_metrics)
            
            stats_y = 200
            line_height = 15
            lines = summary_text.split('\n')
            
            for i, line in enumerate(lines):
                if stats_y + i * line_height < height - 15:
                    painter.drawText(30, stats_y + i * line_height, width - 60, line_height, Qt.AlignLeft, line)
        
        painter.end()

    def paintEvent(self, event):
        super().paintEvent(event)
        self._draw_hud()

    def _draw_hud(self) -> None:
        # dont draw HUD during ending screen
        if self.core.screen_closing or self.core.game_completed:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
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
        painter.setFont(self._hud_font)
        painter.drawText(x + 12, y + 44, f'Coins: {self.core.coins_collected}/{self.core.coins_required}   Keys: {self.core.keys_collected}/{self.core.keys_required}')

        # minimap icon
        icon_size = 54
        ix = self.width() - icon_size - 16
        iy = self.height() - icon_size - 16
        self._cam_icon_rect = (ix, iy, icon_size, icon_size)

        now = time.perf_counter()
        on_cd = now < self._minimap_cooldown_until
        painter.fillRect(ix - 6, iy - 6, icon_size + 12, icon_size + 12, QColor(0, 0, 0, 130))
        painter.setPen(QColor(220, 220, 220))
        painter.drawRect(ix - 6, iy - 6, icon_size + 12, icon_size + 12)

        if not self._cam_icon.isNull():
            painter.drawImage(ix, iy, self._cam_icon.scaled(icon_size, icon_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        else:
            painter.fillRect(ix, iy, icon_size, icon_size, QColor(120, 120, 120))

        if on_cd:
            remaining = max(0.0, self._minimap_cooldown_until - now)
            painter.fillRect(ix, iy, icon_size, icon_size, QColor(0, 0, 0, 160))
            painter.setPen(QColor(255, 210, 90))
            painter.drawText(ix + 10, iy + 32, f'{int(math.ceil(remaining))}s')

        # minimap - 10s
        if now < self._minimap_until:
            self._draw_minimap_overlay(painter)
        else:
            # clear movement keys - bug
            if hasattr(self, 'keys_pressed'):
                self.keys_pressed.clear()

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

        painter.fillRect(x0, y0, maze_content_width, maze_content_height, QColor(10, 10, 12, 210))
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
                    painter.fillRect(int(rx), int(ry), w, h, QColor(45, 45, 55))
                elif (r, c) in self.core.floors:
                    painter.fillRect(int(rx), int(ry), w, h, QColor(125, 125, 135))
                else:
                    painter.fillRect(int(rx), int(ry), w, h, QColor(15, 15, 18))

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
            painter.drawEllipse(int(cx - coin_size / 2), int(cy - coin_size / 2), coin_size, coin_size)

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
            
            # Draw ghost body
            painter.setPen(QPen(ghost_color.darker(150), 1))
            painter.setBrush(ghost_color)
            sx, sy = to_screen(r + 0.5, c + 0.5)
            painter.drawEllipse(int(sx - ghost_size / 2), int(sy - ghost_size / 2), ghost_size, ghost_size)
            
            # Draw eyes
            eye_size = max(2, int(ghost_size * 0.15))
            eye_offset_x = ghost_size * 0.25
            eye_offset_y = ghost_size * 0.1
            
            # left eye
            painter.setPen(QPen(QColor(0, 0, 0), 1))
            painter.setBrush(QColor(255, 255, 255))
            left_eye_x = sx - eye_offset_x
            left_eye_y = sy - eye_offset_y
            painter.drawEllipse(int(left_eye_x - eye_size / 2), int(left_eye_y - eye_size / 2), eye_size, eye_size)
            
            # right eye
            right_eye_x = sx + eye_offset_x
            right_eye_y = sy - eye_offset_y
            painter.drawEllipse(int(right_eye_x - eye_size / 2), int(right_eye_y - eye_size / 2), eye_size, eye_size)
            
            # Eyes
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0))
            pupil_size = max(1, int(eye_size * 0.5))
            painter.drawEllipse(int(left_eye_x - pupil_size / 2), int(left_eye_y - pupil_size / 2), pupil_size, pupil_size)
            painter.drawEllipse(int(right_eye_x - pupil_size / 2), int(right_eye_y - pupil_size / 2), pupil_size, pupil_size)

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
            painter.fillRect(countdown_x - 3, countdown_y - text_height + 3, text_width + 6, text_height + 3, QColor(0, 0, 0, 180))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(countdown_x, countdown_y, countdown_text)

    def _try_open_minimap(self) -> None:
        now = time.perf_counter()
        if now < self._minimap_cooldown_until:
            return
        self._minimap_until = now + 10.0
        self._minimap_cooldown_until = now + 30.0

    def mousePressEvent(self, event: QMouseEvent) -> None:
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
        self.core = GameCore()

        self._key_minigame_open = False
        self.core.register_event_callback('key_fragment_encountered', self._on_key_fragment_encountered)

        self.setWindowTitle('Within the Walls (PySide6)')
        self.resize(1280, 800)

        self.keys_pressed: set[int] = set()

        self.gl = GameGLWidget(self.core)
        self.setCentralWidget(self.gl)

        self.gl.mouse_moved.connect(self._on_mouse_look)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._update_game)
        self._tick.start(16)

        self.setFocusPolicy(Qt.StrongFocus)

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
        if event.key() == Qt.Key_M:
            self.gl._try_open_minimap()
        if event.key() == Qt.Key_Escape:
            self.close()

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
        
        self.core.update(dt)

        move_speed = 0.25
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
            self.core.move_player(dx, dz)

    def _handle_interact(self) -> None:
        action = self.core.interact()
        if action == 'jail_book':
            dlg = SilhouetteMatchDialog(self)
            if dlg.exec():
                self.core.mark_jail_puzzle_success()
        elif action == 'exit_locked':
            pass
        elif action == 'jail_locked':
            pass
        elif action == 'gate_jail':
            self.core.try_leave_jail()

    def _on_key_fragment_encountered(self, data: dict) -> None:
        if self._key_minigame_open:
            return
        frag_id = str((data or {}).get('id', ''))
        if not frag_id:
            return
        self._key_minigame_open = True
        dlg = Assembly3DMinigame(self)
        if dlg.exec():
            self.core.mark_key_fragment_taken(frag_id)
        else:
            self.core.clear_pending_key_fragment(frag_id)
        self._key_minigame_open = False


def run() -> int:
    app = QApplication.instance() or QApplication([])
    win = PySide6GameWindow()
    win.show()
    return app.exec()
