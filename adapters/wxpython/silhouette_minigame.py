from __future__ import annotations

import random

from typing import Optional

import wx


class _RoundedPanel(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        *,
        bg: tuple[int, int, int],
        border: tuple[int, int, int],
        radius: int,
        border_w: int,
    ):
        super().__init__(parent)
        self._bg = tuple(int(x) for x in bg)
        self._border = tuple(int(x) for x in border)
        self._radius = int(radius)
        self._border_w = int(border_w)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _e: None)

    def _on_paint(self, _evt: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        if w <= 0 or h <= 0:
            return
        try:
            parent_bg = self.GetParent().GetBackgroundColour()
        except Exception:
            parent_bg = wx.Colour(45, 45, 48)
        dc.SetBackground(wx.Brush(parent_bg))
        dc.Clear()

        gc = wx.GraphicsContext.Create(dc)
        if gc is None:
            return
        try:
            gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)
        except Exception:
            pass

        rect = wx.Rect(0, 0, int(w), int(h))
        path = gc.CreatePath()
        path.AddRoundedRectangle(float(rect.x) + 0.5, float(rect.y) + 0.5, float(rect.width) - 1.0, float(rect.height) - 1.0, float(self._radius))
        gc.SetBrush(wx.Brush(wx.Colour(*self._bg)))
        gc.SetPen(wx.Pen(wx.Colour(*self._border), width=int(self._border_w)))
        gc.DrawPath(path)


class _StyledButton(wx.Control):
    def __init__(
        self,
        parent: wx.Window,
        *,
        label: str,
        toggle: bool = False,
        size: tuple[int, int],
        bg: tuple[int, int, int],
        fg: tuple[int, int, int],
        border: tuple[int, int, int],
        radius: int,
        hover_bg: tuple[int, int, int],
        hover_border: tuple[int, int, int],
        pressed_bg: tuple[int, int, int],
        checked_bg: Optional[tuple[int, int, int]] = None,
        checked_fg: Optional[tuple[int, int, int]] = None,
        checked_border: Optional[tuple[int, int, int]] = None,
        font_point: int = 13,
        font_weight: int = wx.FONTWEIGHT_BOLD,
    ):
        super().__init__(parent, style=wx.BORDER_NONE)
        self._label = str(label)
        self._toggle = bool(toggle)
        self._value = False
        self._hover = False
        self._pressed = False

        self._bg = tuple(int(x) for x in bg)
        self._fg = tuple(int(x) for x in fg)
        self._border = tuple(int(x) for x in border)
        self._radius = int(radius)
        self._hover_bg = tuple(int(x) for x in hover_bg)
        self._hover_border = tuple(int(x) for x in hover_border)
        self._pressed_bg = tuple(int(x) for x in pressed_bg)
        self._checked_bg = tuple(int(x) for x in (checked_bg or bg))
        self._checked_fg = tuple(int(x) for x in (checked_fg or fg))
        self._checked_border = tuple(int(x) for x in (checked_border or border))

        f = self.GetFont()
        f.SetPointSize(int(font_point))
        f.SetWeight(int(font_weight))
        self.SetFont(f)

        self.SetMinSize((int(size[0]), int(size[1])))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _e: None)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)

    def GetValue(self) -> bool:
        return bool(self._value)

    def SetValue(self, v: bool) -> None:
        if not self._toggle:
            self._value = False
        else:
            self._value = bool(v)
        self.Refresh(False)

    def _on_enter(self, _evt: wx.MouseEvent) -> None:
        self._hover = True
        self.Refresh(False)

    def _on_leave(self, _evt: wx.MouseEvent) -> None:
        self._hover = False
        self._pressed = False
        self.Refresh(False)

    def _on_left_down(self, _evt: wx.MouseEvent) -> None:
        if not self.IsEnabled():
            return
        self._pressed = True
        try:
            self.CaptureMouse()
        except Exception:
            pass
        self.Refresh(False)

    def _on_left_up(self, evt: wx.MouseEvent) -> None:
        try:
            if self.HasCapture():
                self.ReleaseMouse()
        except Exception:
            pass

        was_pressed = bool(self._pressed)
        self._pressed = False
        if not self.IsEnabled():
            self.Refresh(False)
            return

        if was_pressed:
            x, y = evt.GetX(), evt.GetY()
            w, h = self.GetClientSize()
            inside = 0 <= x < w and 0 <= y < h
            if inside:
                if self._toggle:
                    self._value = not bool(self._value)
                evt_type = wx.EVT_TOGGLEBUTTON.typeId if self._toggle else wx.EVT_BUTTON.typeId
                ce = wx.CommandEvent(evt_type, self.GetId())
                ce.SetEventObject(self)
                try:
                    ce.SetInt(1 if self._value else 0)
                except Exception:
                    pass
                wx.PostEvent(self.GetEventHandler(), ce)
        self.Refresh(False)

    def _on_paint(self, _evt: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        if w <= 0 or h <= 0:
            return
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()

        gc = wx.GraphicsContext.Create(dc)
        if gc is None:
            return
        try:
            gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)
        except Exception:
            pass

        if not self.IsEnabled():
            bg = (53, 53, 53)
            fg = (128, 128, 128)
            border = (64, 64, 64)
        elif self._toggle and self._value:
            bg = self._checked_bg
            fg = self._checked_fg
            border = self._checked_border
        elif self._pressed:
            bg = self._pressed_bg
            fg = self._fg
            border = self._border
        elif self._hover:
            bg = self._hover_bg
            fg = self._fg
            border = self._hover_border
        else:
            bg = self._bg
            fg = self._fg
            border = self._border

        rect = wx.Rect(0, 0, int(w), int(h))
        path = gc.CreatePath()
        path.AddRoundedRectangle(float(rect.x) + 0.5, float(rect.y) + 0.5, float(rect.width) - 1.0, float(rect.height) - 1.0, float(self._radius))
        gc.SetBrush(wx.Brush(wx.Colour(*bg)))
        gc.SetPen(wx.Pen(wx.Colour(*border), width=2))
        gc.DrawPath(path)

        gc.SetFont(self.GetFont(), wx.Colour(*fg))
        tw, th = gc.GetTextExtent(self._label)
        gc.DrawText(self._label, float((w - tw) / 2.0), float((h - th) / 2.0))


class SilhouetteMatchDialog(wx.Dialog):
    def __init__(self, parent=None):
        super().__init__(parent, title='Silhouette Matching', style=wx.DEFAULT_DIALOG_STYLE)
        self.SetSize((900, 620))
        self.SetMinSize((900, 620))

        self._size = 6
        self._patterns = self._build_patterns(self._size)
        self._target = random.choice(self._patterns)

        root = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(root)

        self.SetBackgroundColour(wx.Colour(45, 45, 48))

        title_host = _RoundedPanel(self, bg=(64, 64, 64), border=(85, 85, 85), radius=6, border_w=1)
        title_s = wx.BoxSizer(wx.VERTICAL)
        title_host.SetSizer(title_s)
        title = wx.StaticText(title_host, label='Match the silhouette to unlock the jail gate', style=wx.ALIGN_CENTER)
        title.SetForegroundColour(wx.Colour(255, 215, 0))
        title_font = title.GetFont()
        title_font.SetPointSize(18)
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)
        title_s.Add(title, 1, wx.EXPAND | wx.ALL, 8)
        root.Add(title_host, 0, wx.EXPAND | wx.ALL, 8)

        mid = wx.BoxSizer(wx.HORIZONTAL)
        root.Add(mid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        left = wx.BoxSizer(wx.VERTICAL)
        mid.Add(left, 1, wx.EXPAND | wx.RIGHT, 12)

        self._target_panel = _PatternPanel(self, self._target, cell_px=26, pad=10)
        left.Add(self._target_panel, 1, wx.EXPAND)

        right = wx.BoxSizer(wx.VERTICAL)
        mid.Add(right, 2, wx.EXPAND)

        grid_outer = _RoundedPanel(self, bg=(64, 64, 64), border=(85, 85, 85), radius=10, border_w=2)
        grid_outer_s = wx.BoxSizer(wx.VERTICAL)
        grid_outer.SetSizer(grid_outer_s)
        right.Add(grid_outer, 1, wx.EXPAND | wx.ALL, 0)

        grid_host = wx.Panel(grid_outer)
        grid_host.SetBackgroundColour(wx.Colour(64, 64, 64))
        grid_host_s = wx.BoxSizer(wx.VERTICAL)
        grid_host.SetSizer(grid_host_s)
        grid_outer_s.Add(grid_host, 1, wx.EXPAND | wx.ALL, 16)

        grid_s = wx.GridSizer(self._size, self._size, 8, 8)
        grid_host_s.AddStretchSpacer(1)
        grid_host_s.Add(grid_s, 0, wx.ALIGN_CENTER)
        grid_host_s.AddStretchSpacer(1)

        self._cells: list[list[wx.ToggleButton]] = []
        for r in range(self._size):
            row: list[wx.ToggleButton] = []
            for c in range(self._size):
                b = _StyledButton(
                    grid_host,
                    label='',
                    toggle=True,
                    size=(46, 46),
                    bg=(64, 64, 64),
                    fg=(255, 255, 255),
                    border=(85, 85, 85),
                    radius=8,
                    hover_bg=(74, 74, 74),
                    hover_border=(255, 215, 0),
                    pressed_bg=(53, 53, 53),
                    checked_bg=(255, 215, 0),
                    checked_fg=(45, 45, 48),
                    checked_border=(255, 237, 78),
                )
                b.Bind(wx.EVT_TOGGLEBUTTON, lambda evt, rr=r, cc=c: self._on_toggle(rr, cc))
                grid_s.Add(b, 0, wx.ALIGN_CENTER)
                row.append(b)
            self._cells.append(row)

        status_host = _RoundedPanel(self, bg=(64, 64, 64), border=(85, 85, 85), radius=6, border_w=1)
        status_s = wx.BoxSizer(wx.VERTICAL)
        status_host.SetSizer(status_s)
        self._status = wx.StaticText(status_host, label='', style=wx.ALIGN_CENTER)
        st_font = self._status.GetFont()
        st_font.SetPointSize(14)
        st_font.SetWeight(wx.FONTWEIGHT_BOLD)
        self._status.SetFont(st_font)
        self._status.SetForegroundColour(wx.Colour(255, 215, 0))
        status_s.Add(self._status, 1, wx.EXPAND | wx.ALL, 6)
        root.Add(status_host, 0, wx.EXPAND | wx.ALL, 8)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        root.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)

        btn_reset = _StyledButton(
            self,
            label='Reset',
            size=(110, 38),
            bg=(64, 64, 64),
            fg=(255, 255, 255),
            border=(85, 85, 85),
            radius=8,
            hover_bg=(74, 74, 74),
            hover_border=(255, 215, 0),
            pressed_bg=(53, 53, 53),
        )
        btn_reset.Bind(wx.EVT_BUTTON, lambda _evt: self._reset())
        buttons.Add(btn_reset, 0, wx.RIGHT, 8)

        buttons.AddStretchSpacer(1)

        btn_unlock = _StyledButton(
            self,
            label='Unlock',
            size=(120, 38),
            bg=(74, 222, 128),
            fg=(45, 45, 48),
            border=(34, 197, 94),
            radius=8,
            hover_bg=(34, 197, 94),
            hover_border=(22, 163, 74),
            pressed_bg=(74, 74, 80),
            font_weight=wx.FONTWEIGHT_BOLD,
        )
        try:
            btn_unlock.SetDefault()
        except Exception:
            pass
        btn_unlock.Bind(wx.EVT_BUTTON, lambda _evt: self._check())
        buttons.Add(btn_unlock, 0, wx.RIGHT, 8)

        btn_quit = _StyledButton(
            self,
            label='Quit',
            size=(110, 38),
            bg=(239, 68, 68),
            fg=(255, 255, 255),
            border=(220, 38, 38),
            radius=8,
            hover_bg=(220, 38, 38),
            hover_border=(185, 28, 28),
            pressed_bg=(74, 74, 80),
        )
        btn_quit.Bind(wx.EVT_BUTTON, lambda _evt: self.EndModal(wx.ID_CANCEL))
        buttons.Add(btn_quit, 0)

        self._reset()
        try:
            self.CentreOnParent()
        except Exception:
            pass

    def _apply_base_theme(self) -> None:
        return

    def _set_cell_theme(self, r: int, c: int) -> None:
        try:
            self._cells[r][c].Refresh(False)
        except Exception:
            pass

    def _on_toggle(self, r: int, c: int) -> None:
        self._set_cell_theme(r, c)

    def _read_grid(self) -> list[list[int]]:
        out: list[list[int]] = []
        for r in range(self._size):
            row: list[int] = []
            for c in range(self._size):
                row.append(1 if self._cells[r][c].GetValue() else 0)
            out.append(row)
        return out

    def _reset(self) -> None:
        for r in range(self._size):
            for c in range(self._size):
                try:
                    self._cells[r][c].SetValue(False)
                except Exception:
                    pass
                self._set_cell_theme(r, c)
        self._status.SetLabel('Click the squares to draw the silhouette')
        self._status.SetForegroundColour(wx.Colour(255, 215, 0))

    def _check(self) -> None:
        current = self._read_grid()
        if current == self._target:
            self.EndModal(wx.ID_OK)
            return
        self._status.SetLabel('❌ Incorrect. Keep trying!')
        self._status.SetForegroundColour(wx.Colour(255, 255, 255))

    def _build_patterns(self, n: int) -> list[list[list[int]]]:
        def empty() -> list[list[int]]:
            return [[0 for _ in range(n)] for _ in range(n)]

        def add_rect(p: list[list[int]], r0: int, c0: int, r1: int, c1: int) -> None:
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    if 0 <= r < n and 0 <= c < n:
                        p[r][c] = 1

        patterns: list[list[list[int]]] = []

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


class _PatternPanel(wx.Panel):
    def __init__(self, parent: wx.Window, pattern: list[list[int]], *, cell_px: int, pad: int):
        super().__init__(parent)
        self._pattern = pattern
        self._cell_px = int(cell_px)
        self._pad = int(pad)
        self.SetBackgroundColour(wx.Colour(45, 45, 48))
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def _on_paint(self, _evt: wx.PaintEvent) -> None:
        dc = wx.PaintDC(self)
        dc.SetBackground(wx.Brush(wx.Colour(45, 45, 48)))
        dc.Clear()

        w, h = self.GetClientSize()
        n = len(self._pattern)
        cell_px = self._cell_px
        pad = self._pad

        grid_w = n * cell_px
        grid_h = n * cell_px
        x0 = (w - (grid_w + pad * 2)) // 2
        y0 = (h - (grid_h + pad * 2)) // 2
        x0 = max(0, int(x0))
        y0 = max(0, int(y0))

        bg = wx.Colour(64, 64, 68)
        on = wx.Colour(255, 215, 0)
        off = wx.Colour(96, 96, 96)

        dc.SetPen(wx.Pen(wx.Colour(255, 215, 0, 128), 1))
        dc.SetBrush(wx.Brush(bg))
        dc.DrawRectangle(x0, y0, grid_w + pad * 2, grid_h + pad * 2)

        for r in range(n):
            for c in range(n):
                x = x0 + pad + c * cell_px
                y = y0 + pad + r * cell_px
                dc.SetBrush(wx.Brush(on if self._pattern[r][c] else off))
                dc.SetPen(wx.Pen(wx.Colour(0, 0, 0), 0))
                dc.DrawRectangle(int(x), int(y), int(cell_px - 2), int(cell_px - 2))

        dc.SetPen(wx.Pen(wx.Colour(255, 215, 0, 128), 1))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawRectangle(x0 + 1, y0 + 1, grid_w + pad * 2 - 2, grid_h + pad * 2 - 2)
