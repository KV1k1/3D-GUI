"""
kivy_silhouette.py
==================
Kivy port of SilhouetteMatchDialog.

The puzzle: a target 6x6 binary pattern is shown on the LEFT.
The player clicks cells in the 6x6 editable grid on the RIGHT to toggle
them gold/dark, trying to replicate the target pattern exactly.
Reset clears the grid. Unlock checks if the player-drawn grid matches the target.
"""

from __future__ import annotations
import random
from typing import List

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle, Line
from kivy.metrics import dp
from kivy.core.window import Window


def _build_patterns(n: int = 6):
    def empty():
        return [[0]*n for _ in range(n)]

    def add_rect(p, r0, c0, r1, c1):
        for r in range(r0, r1+1):
            for c in range(c0, c1+1):
                if 0 <= r < n and 0 <= c < n:
                    p[r][c] = 1
    patterns = []
    p = empty()
    add_rect(p, 1, 1, 1, 4)
    add_rect(p, 2, 3, 4, 3)
    add_rect(p, 4, 1, 4, 2)
    patterns.append(p)
    p = empty()
    add_rect(p, 1, 2, 4, 3)
    add_rect(p, 1, 1, 1, 4)
    patterns.append(p)
    p = empty()
    add_rect(p, 1, 2, 4, 3)
    add_rect(p, 0, 2, 1, 3)
    add_rect(p, 4, 1, 4, 4)
    patterns.append(p)
    p = empty()
    add_rect(p, 2, 1, 3, 4)
    add_rect(p, 1, 2, 4, 3)
    patterns.append(p)
    p = empty()
    add_rect(p, 1, 1, 1, 4)
    add_rect(p, 1, 1, 4, 1)
    add_rect(p, 4, 1, 4, 4)
    add_rect(p, 2, 4, 4, 4)
    add_rect(p, 2, 2, 2, 3)
    patterns.append(p)
    return patterns


class PatternDisplay(Widget):
    def __init__(self, pattern, **kwargs):
        super().__init__(**kwargs)
        self._pattern = pattern
        self.bind(pos=self._redraw, size=self._redraw)

    def set_pattern(self, p):
        self._pattern = p
        self._redraw()

    def _redraw(self, *_):
        self.canvas.clear()
        n = len(self._pattern)
        if n == 0:
            return
        # Use fixed cell size like PySide (26px) with 10px padding
        cell_px = 26
        pad = 10
        total_size = pad * 2 + cell_px * n
        # Center the pattern in available space
        scale_x = min(1.0, self.width / total_size)
        scale_y = min(1.0, self.height / total_size)
        scale = min(scale_x, scale_y)
        cell = cell_px * scale
        pad_scaled = pad * scale
        ox = self.x + (self.width - total_size * scale) / 2
        oy = self.y + (self.height - total_size * scale) / 2

        with self.canvas:
            # Background like PySide (#2d2d30)
            Color(0.176, 0.176, 0.176, 1)
            Rectangle(pos=(ox, oy), size=(
                total_size * scale, total_size * scale))
            for r, row in enumerate(self._pattern):
                for c, val in enumerate(row):
                    px = ox + pad_scaled + c * cell
                    py = oy + pad_scaled + \
                        (n - 1 - r) * cell  # Flip Y coordinate
                    if val:
                        Color(1.0, 0.84, 0.0, 1)  # Gold like PySide
                    else:
                        Color(0.376, 0.376, 0.376, 1)  # Dark gray like PySide
                    Rectangle(pos=(px, py), size=(cell - 2, cell - 2))
            # Border like PySide
            Color(1.0, 0.84, 0.0, 0.5)
            Line(rectangle=(ox, oy, total_size *
                 scale, total_size * scale), width=1.5)


class _CellButton(Button):
    def __init__(self, row, col, **kwargs):
        super().__init__(**kwargs)
        self.row = row
        self.col = col
        self._on = False
        self.size_hint = (None, None)
        self.size = (46, 46)  # Fixed size like PySide
        self.background_normal = ''
        self.background_down = ''
        self.text = ''
        self._update_style()

    @property
    def is_on(self):
        return self._on

    def toggle(self):
        self._on = not self._on
        self._update_style()

    def set_off(self):
        self._on = False
        self._update_style()

    def _update_style(self):
        if self._on:
            # Gold style like PySide
            self.background_color = (1.0, 0.84, 0.0, 1.0)
        else:
            # Dark gray style like PySide
            self.background_color = (0.25, 0.25, 0.26, 1.0)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            # Visual feedback on press
            if self._on:
                self.background_color = (0.9, 0.76, 0.0, 1.0)  # Darker gold
            else:
                self.background_color = (0.21, 0.21, 0.21, 1.0)  # Darker gray
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        self._update_style()
        return super().on_touch_up(touch)


class KivySilhouetteMinigame(FloatLayout):
    """
    Draw-to-match silhouette puzzle.
    Open with .open(). Bind result with .bind_result(fn) where fn(success:bool).
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.size_hint = (1, 1)

        self._callback = None
        self._size = 6
        patterns = _build_patterns(self._size)
        self._target = random.choice(patterns)
        self._cells = []
        self._bg = None
        self._panel = None
        self._panel_bg = None
        self._build_ui()

    def bind_result(self, callback):
        self._callback = callback

    def open(self):
        Window.add_widget(self)

    def dismiss(self):
        try:
            Window.remove_widget(self)
        except Exception:
            pass

    def _build_ui(self):
        with self.canvas.before:
            Color(0, 0, 0, 160/255)
            self._bg = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=lambda w, v: (setattr(self._bg, 'size', v), setattr(self._bg, 'pos', w.pos)),
                  pos=lambda w, v: setattr(self._bg, 'pos', v))

        root = BoxLayout(
            orientation='vertical', padding=0, spacing=0,
            # Proper size for PySide parity
            size_hint=(None, None), size=(720, 520),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
        )
        self._panel = root

        with root.canvas.before:
            Color(0.18, 0.18, 0.22, 0.98)
            self._panel_bg = Rectangle(pos=root.pos, size=root.size)

        def _upd_panel_bg(w, v=None):
            if self._panel_bg is None:
                return
            self._panel_bg.pos = w.pos
            self._panel_bg.size = w.size
            w.canvas.after.clear()
            with w.canvas.after:
                Color(1.0, 0.84, 0.0, 0.55)
                Line(rectangle=(w.x, w.y, w.width, w.height), width=1.25)
        root.bind(pos=_upd_panel_bg, size=_upd_panel_bg)

        # Header bar that looks like a window title bar
        header = BoxLayout(orientation='horizontal',
                           size_hint_y=None, height=35, spacing=8, padding=8)
        # Dark header background like PySide
        header.background_color = (0.25, 0.25, 0.26, 1.0)

        # Title in header
        title = Label(
            text='Silhouette Matching',
            font_size=16,
            halign='left', valign='middle',
            color=(1.0, 0.84, 0.0, 1.0), bold=True,
            size_hint_x=1,
        )

        # Close button in header
        close_btn = Button(
            text='✕', font_size=14,
            size_hint=(None, 1), width=30,
            background_normal='', background_color=(0.60, 0.15, 0.15, 1.0),
            color=(1.0, 1.0, 1.0, 1.0),
        )
        close_btn.bind(on_press=lambda *_: self._finish(False))

        header.add_widget(title)
        header.add_widget(close_btn)
        root.add_widget(header)

        # Main content area with proper padding
        content = BoxLayout(orientation='vertical', padding=8, spacing=8)

        # Instructions with exact PySide styling
        instructions = BoxLayout(
            orientation='horizontal', size_hint_y=None, height=50, padding=8)  # 8px padding + margin
        instructions.background_color = (
            0.25, 0.25, 0.26, 1.0)  # #404040 like PySide

        inst_label = Label(
            text='Match the silhouette to unlock the jail gate',
            font_size=18,
            halign='center', valign='middle',
            color=(1.0, 0.84, 0.0, 1.0),  # #ffd700 like PySide
            size_hint_x=1,
        )
        instructions.add_widget(inst_label)
        content.add_widget(instructions)

        # Grid area
        body = BoxLayout(orientation='horizontal', spacing=8)

        left = BoxLayout(orientation='vertical', size_hint_x=1, spacing=6)
        # Target display with PySide-style container (no "Target" label in PySide)
        target_container = BoxLayout(orientation='vertical', padding=12)
        target_container.background_color = (
            0.25, 0.25, 0.26, 1.0)  # #404040 like PySide

        self._target_display = PatternDisplay(self._target)
        target_container.add_widget(self._target_display)
        left.add_widget(target_container)
        body.add_widget(left)

        right = BoxLayout(orientation='vertical', size_hint_x=2, spacing=6)
        # Grid container with PySide-style background (no "Your Drawing" label in PySide)
        grid_container = BoxLayout(orientation='vertical', padding=12)
        grid_container.background_color = (
            0.25, 0.25, 0.26, 1.0)  # #404040 like PySide

        # Simple grid container
        grid = GridLayout(cols=self._size, spacing=6, size_hint=(1, 1))
        self._cells = []
        for r in range(self._size):
            row_cells = []
            for c in range(self._size):
                btn = _CellButton(r, c)
                btn.bind(on_press=lambda b, *_: b.toggle())
                grid.add_widget(btn)
                row_cells.append(btn)
            self._cells.append(row_cells)
        grid_container.add_widget(grid)
        right.add_widget(grid_container)
        body.add_widget(right)
        content.add_widget(body)

        # Status with PySide-style background
        self._status = Label(
            text='Click the squares to draw the silhouette',
            font_size=14,
            halign='center', valign='middle',
            color=(1.0, 0.84, 0.0, 1.0),  # #ffd700 like PySide
            size_hint_y=None, height=30,
        )
        status_container = BoxLayout(
            orientation='horizontal', size_hint_y=None, height=40, padding=6)
        status_container.background_color = (
            0.25, 0.25, 0.26, 1.0)  # #404040 like PySide
        status_container.add_widget(self._status)
        content.add_widget(status_container)

        # Buttons
        btn_row = BoxLayout(orientation='horizontal',
                            size_hint_y=None, height=40, spacing=10, padding=10)
        reset_btn = Button(
            text='Reset', font_size=14,
            background_normal='', background_color=(0.25, 0.25, 0.26, 1.0),
            size_hint_x=None, width=80,
        )
        reset_btn.bind(on_press=self._reset)

        unlock_btn = Button(
            text='[b]Unlock[/b]', markup=True, font_size=14,
            background_normal='', background_color=(0.29, 0.71, 0.50, 1.0),
            color=(0.18, 0.18, 0.18, 1.0),
            size_hint_x=None, width=80,
        )
        unlock_btn.bind(on_press=self._check)

        quit_btn = Button(
            text='Quit', font_size=14,
            background_normal='', background_color=(0.94, 0.27, 0.27, 1.0),
            size_hint_x=None, width=80,
        )
        quit_btn.bind(on_press=lambda *_: self._finish(False))

        btn_row.add_widget(reset_btn)
        btn_row.add_widget(Widget(size_hint_x=1))  # Spacer
        btn_row.add_widget(unlock_btn)
        btn_row.add_widget(quit_btn)
        content.add_widget(btn_row)

        root.add_widget(content)

        self.add_widget(root)

    def on_touch_down(self, touch):
        if self._panel_bg is not None:
            x, y = touch.pos
            if not (self._panel_bg.pos[0] <= x <= self._panel_bg.pos[0] + self._panel_bg.size[0]
                    and self._panel_bg.pos[1] <= y <= self._panel_bg.pos[1] + self._panel_bg.size[1]):
                return True
        return super().on_touch_down(touch)

    def _reset(self, *_):
        for r in range(self._size):
            for c in range(self._size):
                if self._cells[r][c].is_on:
                    self._cells[r][c].set_off()
        self._status.text = 'Click the squares to draw the silhouette'
        self._status.color = (1.0, 0.84, 0.0, 1.0)  # #ffd700 like PySide

    def _check(self, *_):
        current = [[1 if self._cells[r][c].is_on else 0
                    for c in range(self._size)]
                   for r in range(self._size)]
        if current == self._target:
            self._status.text = 'Correct! Unlocking gate...'
            self._status.color = (1.0, 0.84, 0.0, 1.0)  # Keep gold like PySide
            from kivy.clock import Clock
            Clock.schedule_once(lambda *_: self._finish(True), 0.6)
        else:
            # Use 'X' instead of emoji for Kivy compatibility
            self._status.text = 'X Incorrect. Keep trying!'
            self._status.color = (1.0, 1.0, 1.0, 1.0)  # #ffffff like PySide

    def _finish(self, success: bool):
        self.dismiss()
        if self._callback:
            self._callback(success)
