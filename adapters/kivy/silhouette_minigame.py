import random
from typing import List

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.widget import Widget
from kivy.uix.modalview import ModalView
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
        # fixed cell size
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
            Color(0.176, 0.176, 0.176, 1)
            Rectangle(pos=(ox, oy), size=(
                total_size * scale, total_size * scale))
            for r, row in enumerate(self._pattern):
                for c, val in enumerate(row):
                    px = ox + pad_scaled + c * cell
                    py = oy + pad_scaled + (n - 1 - r) * cell
                    if val:
                        Color(1.0, 0.84, 0.0, 1)  # Gold like PySide
                    else:
                        Color(0.376, 0.376, 0.376, 1)
                    Rectangle(pos=(px, py), size=(cell - 2, cell - 2))
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
        self.size = (46, 46)
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
            self.background_color = (1.0, 0.84, 0.0, 1.0)
        else:
            self.background_color = (0.25, 0.25, 0.26, 1.0)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if self._on:
                self.background_color = (0.9, 0.76, 0.0, 1.0)
            else:
                self.background_color = (0.21, 0.21, 0.21, 1.0)
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        self._update_style()
        return super().on_touch_up(touch)


class KivySilhouetteMinigame(ModalView):

    def __init__(self, hard_mode: bool = False, **kwargs):
        kwargs.setdefault('size_hint', (None, None))
        kwargs.setdefault('size', (720, 550))
        kwargs.setdefault('auto_dismiss', False)
        super().__init__(**kwargs)

        self._hard_mode = hard_mode
        self._callback = None
        self._size = 6
        self._target = []  # Will be set in on_open to avoid showing wrong puzzle briefly
        self._cells = []
        self._panel_bg = None
        self._title_label = None
        self._inst_label = None
        self._build_ui()

    def bind_result(self, callback):
        self._callback = callback

    def on_open(self):
        self._reset()
        if self._hard_mode:
            self._target = [
                [0, 1, 0, 0, 0, 1],
                [1, 0, 1, 0, 1, 0],
                [0, 1, 0, 1, 0, 1],
                [0, 0, 1, 0, 1, 0],
                [0, 1, 0, 1, 0, 1],
                [1, 0, 1, 0, 1, 0],
            ]
            self._title_label.text = 'GHOST 4 CHALLENGE'
            self._inst_label.text = 'Match this harder silhouette!'
        else:
            patterns = _build_patterns(self._size)
            self._target = random.choice(patterns)
            self._title_label.text = 'Silhouette Matching'
            self._inst_label.text = 'Match the silhouette to unlock the jail gate'
        self._target_display.set_pattern(self._target)

    def _build_ui(self):
        root = BoxLayout(
            orientation='vertical', padding=0, spacing=0,
            size_hint=(1, 1),  # Fill the ModalView
        )

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

        header = BoxLayout(orientation='horizontal',
                           size_hint_y=None, height=35, spacing=8, padding=8)
        header.background_color = (0.25, 0.25, 0.26, 1.0)

        # Title in header
        title_text = 'Silhouette Matching'
        if self._hard_mode:
            title_text = 'GHOST 4 CHALLENGE'
        self._title_label = Label(
            text=title_text,
            font_size=16,
            halign='left', valign='middle',
            color=(1.0, 0.84, 0.0, 1.0), bold=True,
            size_hint_x=1,
        )

        close_btn = Button(
            text='X', font_size=14,
            size_hint=(None, 1), width=30,
            background_normal='', background_color=(0.60, 0.15, 0.15, 1.0),
            color=(1.0, 1.0, 1.0, 1.0),
        )
        close_btn.bind(on_press=lambda *_: self._finish(False))

        header.add_widget(self._title_label)
        header.add_widget(close_btn)
        root.add_widget(header)

        # Main content area
        content = BoxLayout(orientation='vertical', padding=8, spacing=8)

        instructions = BoxLayout(
            orientation='horizontal', size_hint_y=None, height=50, padding=8)
        instructions.background_color = (0.25, 0.25, 0.26, 1.0)

        inst_text = 'Match the silhouette to unlock the jail gate'
        if self._hard_mode:
            inst_text = 'Match this harder silhouette!'
        self._inst_label = Label(
            text=inst_text,
            font_size=18,
            halign='center', valign='middle',
            color=(1.0, 0.84, 0.0, 1.0),
            size_hint_x=1,
        )
        instructions.add_widget(self._inst_label)
        content.add_widget(instructions)

        # Grid area
        body = BoxLayout(orientation='horizontal', spacing=8)

        left = BoxLayout(orientation='vertical', size_hint_x=1, spacing=6)
        target_container = BoxLayout(orientation='vertical', padding=12)
        target_container.background_color = (0.25, 0.25, 0.26, 1.0)

        self._target_display = PatternDisplay(self._target)
        target_container.add_widget(self._target_display)
        left.add_widget(target_container)
        body.add_widget(left)

        right = BoxLayout(orientation='vertical', size_hint_x=2, spacing=6)
        grid_container = BoxLayout(orientation='vertical', padding=12)
        grid_container.background_color = (0.25, 0.25, 0.26, 1.0)

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

        self._status = Label(
            text='Click the squares to draw the silhouette',
            font_size=14,
            halign='center', valign='middle',
            color=(1.0, 0.84, 0.0, 1.0),
            size_hint_y=None, height=30,
        )
        status_container = BoxLayout(
            orientation='horizontal', size_hint_y=None, height=40, padding=6)
        status_container.background_color = (0.25, 0.25, 0.26, 1.0)
        status_container.add_widget(self._status)
        content.add_widget(status_container)

        # Buttons
        btn_row = BoxLayout(orientation='horizontal',
                            size_hint_y=None, height=55, spacing=10, padding=10)
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
        return super().on_touch_down(touch)

    def _reset(self, *_):
        for r in range(self._size):
            for c in range(self._size):
                if self._cells[r][c].is_on:
                    self._cells[r][c].set_off()
        self._status.text = 'Click the squares to draw the silhouette'
        self._status.color = (1.0, 0.84, 0.0, 1.0)

    def _check(self, *_):
        current = [[1 if self._cells[r][c].is_on else 0
                    for c in range(self._size)]
                   for r in range(self._size)]
        if current == self._target:
            self._status.text = 'Correct!'
            self._status.color = (1.0, 0.84, 0.0, 1.0)
            from kivy.clock import Clock
            Clock.schedule_once(lambda *_: self._finish(True), 0.6)
        else:
            self._status.text = 'X Incorrect. Keep trying!'
            self._status.color = (1.0, 1.0, 1.0, 1.0)

    def _finish(self, success: bool):
        self.dismiss()
        if self._callback:
            self._callback(success)
