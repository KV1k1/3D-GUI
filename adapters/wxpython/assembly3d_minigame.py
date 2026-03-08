import math
import time
from typing import Any, Optional

import numpy as np
import wx
from wx import glcanvas

from OpenGL.GL import (
    GL_BLEND,
    GL_COLOR_BUFFER_BIT,
    GL_CULL_FACE,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_TEST,
    GL_MODELVIEW,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_PROJECTION,
    GL_QUADS,
    GL_SRC_ALPHA,
    glBegin,
    glBlendFunc,
    glClear,
    glClearColor,
    glDisable,
    glEnable,
    glEnd,
    glLoadIdentity,
    glMatrixMode,
    glPopMatrix,
    glPushMatrix,
    glRotatef,
    glScalef,
    glTranslatef,
    glVertex3f,
)


class _QtLikeButton(wx.Control):
    def __init__(
        self,
        parent: wx.Window,
        *,
        label: str,
        toggle: bool = False,
        size: Optional[tuple[int, int]] = None,
        bg: tuple[int, int, int] = (90, 90, 96),
        fg: tuple[int, int, int] = (255, 255, 255),
        border: tuple[int, int, int] = (122, 122, 128),
        radius: int = 8,
        checked_bg: tuple[int, int, int] = (255, 215, 0),
        checked_fg: tuple[int, int, int] = (45, 45, 48),
        checked_border: tuple[int, int, int] = (255, 237, 78),
        hover_bg: tuple[int, int, int] = (106, 106, 112),
        hover_border: tuple[int, int, int] = (255, 215, 0),
        pressed_bg: Optional[tuple[int, int, int]] = None,
        pressed_fg: Optional[tuple[int, int, int]] = None,
        pressed_border: Optional[tuple[int, int, int]] = None,
        enabled: bool = True,
        font_point: int = 13,
        font_weight: int = wx.FONTWEIGHT_BOLD,
        padding_x: int = 16,
        padding_y: int = 8,
    ):
        style = wx.BORDER_NONE
        super().__init__(parent, style=style)
        self._label = str(label)
        self._toggle = bool(toggle)
        self._value = False
        self._hover = False
        self._pressed = False

        self._bg = tuple(int(x) for x in bg)
        self._fg = tuple(int(x) for x in fg)
        self._border = tuple(int(x) for x in border)
        self._radius = int(radius)
        self._checked_bg = tuple(int(x) for x in checked_bg)
        self._checked_fg = tuple(int(x) for x in checked_fg)
        self._checked_border = tuple(int(x) for x in checked_border)
        self._hover_bg = tuple(int(x) for x in hover_bg)
        self._hover_border = tuple(int(x) for x in hover_border)
        self._pressed_bg = tuple(int(x) for x in (pressed_bg or self._bg))
        self._pressed_fg = tuple(int(x) for x in (pressed_fg or self._fg))
        self._pressed_border = tuple(int(x) for x in (pressed_border or self._border))
        self._padding_x = int(padding_x)
        self._padding_y = int(padding_y)

        f = self.GetFont()
        f.SetPointSize(int(font_point))
        f.SetWeight(int(font_weight))
        self.SetFont(f)
        self.Enable(bool(enabled))

        if size is not None:
            self.SetMinSize((int(size[0]), int(size[1])))

        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _e: None)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)

    def SetLabel(self, label: str) -> None:  # type: ignore[override]
        self._label = str(label)
        self.Refresh(False)

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

    def _on_left_down(self, evt: wx.MouseEvent) -> None:
        if not self.IsEnabled():
            return
        self._pressed = True
        self.CaptureMouse()
        self.Refresh(False)
        evt.Skip()

    def _on_left_up(self, evt: wx.MouseEvent) -> None:
        if self.HasCapture():
            try:
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
                evt_btn = wx.CommandEvent(evt_type, self.GetId())
                evt_btn.SetEventObject(self)
                try:
                    evt_btn.SetInt(1 if self._value else 0)
                except Exception:
                    pass
                wx.PostEvent(self.GetEventHandler(), evt_btn)
        self.Refresh(False)
        evt.Skip()

    def _on_paint(self, _evt: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.Clear()

        w, h = self.GetClientSize()
        if w <= 0 or h <= 0:
            return

        if not self.IsEnabled():
            bg = (58, 58, 64)
            fg = (128, 128, 128)
            border = (90, 90, 96)
        elif self._toggle and self._value:
            bg = self._checked_bg
            fg = self._checked_fg
            border = self._checked_border
        elif self._pressed:
            bg = self._pressed_bg
            fg = self._pressed_fg
            border = self._pressed_border
        elif self._hover:
            bg = self._hover_bg
            fg = self._fg
            border = self._hover_border
        else:
            bg = self._bg
            fg = self._fg
            border = self._border

        rect = wx.Rect(0, 0, int(w), int(h))
        dc.SetBrush(wx.Brush(wx.Colour(*bg)))
        dc.SetPen(wx.Pen(wx.Colour(*border), width=2))
        dc.DrawRoundedRectangle(rect, self._radius)

        dc.SetTextForeground(wx.Colour(*fg))
        dc.SetFont(self.GetFont())
        tw, th = dc.GetTextExtent(self._label)
        x = int((w - tw) // 2)
        y = int((h - th) // 2)
        dc.DrawText(self._label, x, y)


class _StyledFeedback(wx.Panel):
    def __init__(self, parent: wx.Window, *, size: tuple[int, int]):
        super().__init__(parent)
        self._text = ''
        self._mode = 'normal'
        self.SetMinSize((int(size[0]), int(size[1])))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _e: None)

        f = self.GetFont()
        f.SetPointSize(14)
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        self.SetFont(f)

    def set_text(self, text: str, *, mode: str = 'normal') -> None:
        self._text = str(text)
        self._mode = str(mode or 'normal')
        self.Refresh(False)

    def _on_paint(self, _evt: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.Clear()

        w, h = self.GetClientSize()
        if w <= 0 or h <= 0:
            return

        if self._mode == 'success':
            bg = (45, 90, 45)
            border = (74, 222, 128)
            weight = wx.FONTWEIGHT_BOLD
            pad = 8
            border_w = 2
        elif self._mode == 'error':
            bg = (90, 45, 45)
            border = (239, 68, 68)
            weight = wx.FONTWEIGHT_BOLD
            pad = 6
            border_w = 1
        else:
            bg = (90, 90, 96)
            border = (122, 122, 128)
            weight = wx.FONTWEIGHT_BOLD
            pad = 6
            border_w = 1

        f = self.GetFont()
        f.SetWeight(int(weight))
        self.SetFont(f)

        rect = wx.Rect(0, 0, int(w), int(h))
        dc.SetBrush(wx.Brush(wx.Colour(*bg)))
        dc.SetPen(wx.Pen(wx.Colour(*border), width=int(border_w)))
        dc.DrawRoundedRectangle(rect, 6)

        dc.SetTextForeground(wx.Colour(255, 255, 255))
        dc.SetFont(self.GetFont())
        text = self._text
        tw, th = dc.GetTextExtent(text)
        x = int((w - tw) // 2)
        y = int((h - th) // 2)
        y = max(int(pad), y)
        dc.DrawText(text, x, y)


class _AsmGLCanvas(glcanvas.GLCanvas):
    def __init__(self, parent: wx.Window, *, bg: tuple[int, int, int, int], orbit: bool = False):
        super().__init__(parent, attribList=[glcanvas.WX_GL_RGBA, glcanvas.WX_GL_DOUBLEBUFFER, glcanvas.WX_GL_DEPTH_SIZE, 24, 0])
        self._ctx = glcanvas.GLContext(self)
        self._bg = tuple(int(x) for x in bg)
        self._initialized = False

        # Camera params (approximate pyqtgraph GLViewWidget defaults used in PySide).
        self._cam_distance = 8.0
        self._cam_elev_deg = 20.0
        self._cam_azim_deg = 30.0
        self._cam_target = (0.0, 0.0, 0.0)
        self._fov = 60.0

        self._pieces: list[dict[str, Any]] = []
        self._target: list[dict[str, Any]] = []
        self._draw_mode = 'assembly'

        self._selected_idx: Optional[int] = None
        self._flash_green: bool = False

        self._orbit_enabled = bool(orbit)
        self._dragging = False
        self._last_mouse: Optional[tuple[int, int]] = None

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        if self._orbit_enabled:
            self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
            self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
            self.Bind(wx.EVT_MOTION, self._on_motion)

    def _on_left_down(self, evt: wx.MouseEvent) -> None:
        self._dragging = True
        self._last_mouse = (evt.GetX(), evt.GetY())
        try:
            self.CaptureMouse()
        except Exception:
            pass

    def _on_left_up(self, _evt: wx.MouseEvent) -> None:
        self._dragging = False
        self._last_mouse = None
        try:
            if self.HasCapture():
                self.ReleaseMouse()
        except Exception:
            pass

    def _on_motion(self, evt: wx.MouseEvent) -> None:
        if not self._dragging:
            return
        if not evt.Dragging() or not evt.LeftIsDown():
            return
        if self._last_mouse is None:
            self._last_mouse = (evt.GetX(), evt.GetY())
            return
        x, y = evt.GetX(), evt.GetY()
        lx, ly = self._last_mouse
        dx = float(x - lx)
        dy = float(y - ly)
        self._last_mouse = (x, y)

        self._cam_azim_deg = float(self._cam_azim_deg) + dx * 0.4
        self._cam_elev_deg = float(self._cam_elev_deg) + dy * 0.4
        self._cam_elev_deg = max(-89.0, min(89.0, float(self._cam_elev_deg)))
        self.Refresh(False)

    def set_scene(self, *, pieces: list[dict[str, Any]], target: list[dict[str, Any]], mode: str) -> None:
        self._pieces = list(pieces)
        self._target = list(target)
        self._draw_mode = str(mode or 'assembly')
        self.Refresh(False)

    def set_selection(self, idx: Optional[int], *, flash_green: bool) -> None:
        self._selected_idx = None if idx is None else int(idx)
        self._flash_green = bool(flash_green)
        self.Refresh(False)

    def set_camera(
        self,
        *,
        distance: float = 8.0,
        elevation_deg: float = 20.0,
        azimuth_deg: float = 30.0,
        target: Optional[tuple[float, float, float]] = None,
        fov: Optional[float] = None,
    ) -> None:
        self._cam_distance = float(distance)
        self._cam_elev_deg = float(elevation_deg)
        self._cam_azim_deg = float(azimuth_deg)
        if target is not None:
            self._cam_target = (float(target[0]), float(target[1]), float(target[2]))
        if fov is not None:
            self._fov = float(fov)
        self.Refresh(False)

    def _ensure(self) -> None:
        if self._initialized:
            return
        self.SetCurrent(self._ctx)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDisable(GL_CULL_FACE)
        self._initialized = True

    def _on_size(self, _evt: wx.SizeEvent) -> None:
        self.Refresh(False)

    def _setup_3d(self, w: int, h: int) -> None:
        aspect = float(w) / float(max(1, h))
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        fov = float(self._fov)
        near = 0.1
        far = 100.0
        top = math.tan(math.radians(fov) / 2.0) * near
        right = top * aspect
        # glFrustum replacement (manual)
        from OpenGL.GL import glFrustum

        glFrustum(-right, right, -top, top, near, far)

        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

        # Z-up orbit camera similar to pyqtgraph GLViewWidget.
        from OpenGL.GLU import gluLookAt

        elev = math.radians(float(self._cam_elev_deg))
        azim = math.radians(float(self._cam_azim_deg))
        dist = float(self._cam_distance)
        tx, ty, tz = (float(self._cam_target[0]), float(self._cam_target[1]), float(self._cam_target[2]))

        cx = tx + dist * math.cos(elev) * math.cos(azim)
        cy = ty + dist * math.cos(elev) * math.sin(azim)
        cz = tz + dist * math.sin(elev)

        gluLookAt(cx, cy, cz, tx, ty, tz, 0.0, 0.0, 1.0)

    def _draw_grid(self) -> None:
        # Match PySide grid feel: light grey plane grid + subtle yellow axis highlight.
        from OpenGL.GL import GL_LINES, glColor4f, glLineWidth

        glLineWidth(1.25)
        glBegin(GL_LINES)

        # Grid lines (floor plane: XY at Z=0)
        # Draw lines at half-integers so integer piece positions land centered on a grid cell
        # (like the PySide version where moving +/-1 hops between squares).
        for x in range(-4, 5):
            glColor4f(0.65, 0.65, 0.68, 0.55)
            xf = float(x) - 0.5
            glVertex3f(xf, -4.5, 0.0)
            glVertex3f(xf, 4.5, 0.0)
        for y in range(-4, 5):
            glColor4f(0.65, 0.65, 0.68, 0.55)
            yf = float(y) - 0.5
            glVertex3f(-4.5, yf, 0.0)
            glVertex3f(4.5, yf, 0.0)

        # Highlight axes (subtle yellow)
        glColor4f(1.0, 0.84, 0.0, 0.35)
        glVertex3f(-4.5, -0.5, 0.0)
        glVertex3f(4.5, -0.5, 0.0)
        glVertex3f(-0.5, -4.5, 0.0)
        glVertex3f(-0.5, 4.5, 0.0)

        glEnd()

    def _draw_cube(self, color: tuple[float, float, float, float]) -> None:
        r, g, b, a = color
        from OpenGL.GL import glColor4f

        glColor4f(r, g, b, a)
        # unit cube with base on Z=0 (so it sits on the floor grid)
        faces = [
            # z0
            [(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0)],
            # z1
            [(-0.5, -0.5, 1.0), (0.5, -0.5, 1.0), (0.5, 0.5, 1.0), (-0.5, 0.5, 1.0)],
            # x-
            [(-0.5, -0.5, 0.0), (-0.5, 0.5, 0.0), (-0.5, 0.5, 1.0), (-0.5, -0.5, 1.0)],
            # x+
            [(0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (0.5, 0.5, 1.0), (0.5, -0.5, 1.0)],
            # y-
            [(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, -0.5, 1.0), (-0.5, -0.5, 1.0)],
            # y+
            [(-0.5, 0.5, 0.0), (0.5, 0.5, 0.0), (0.5, 0.5, 1.0), (-0.5, 0.5, 1.0)],
        ]
        glBegin(GL_QUADS)
        for face in faces:
            for vx, vy, vz in face:
                glVertex3f(float(vx), float(vy), float(vz))
        glEnd()

    def _draw_pyramid(self, color: tuple[float, float, float, float]) -> None:
        r, g, b, a = color
        from OpenGL.GL import GL_TRIANGLES, glColor4f

        glColor4f(r, g, b, a)
        apex = (0.0, 0.0, 1.0)
        base = [(0.5, 0.5, 0.0), (0.5, -0.5, 0.0), (-0.5, -0.5, 0.0), (-0.5, 0.5, 0.0)]

        glBegin(GL_TRIANGLES)
        for i in range(4):
            v1 = base[i]
            v2 = base[(i + 1) % 4]
            glVertex3f(*apex)
            glVertex3f(*v1)
            glVertex3f(*v2)
        glEnd()

        glBegin(GL_QUADS)
        for vx, vy, vz in base:
            glVertex3f(float(vx), float(vy), float(vz))
        glEnd()

    def _draw_part(self, part: dict[str, Any]) -> None:
        t = str(part.get('type', 'cube'))
        pos = part.get('pos')
        rot = part.get('rot') or [0, 0, 0]
        col = part.get('color')
        if pos is None:
            return
        if col is None:
            col = (255, 255, 255, 255)

        rgba = (float(col[0]) / 255.0, float(col[1]) / 255.0, float(col[2]) / 255.0, float(col[3]) / 255.0)

        if self._draw_mode == 'assembly' and self._selected_idx is not None:
            try:
                idx = int(part.get('_idx', -1))
            except Exception:
                idx = -1
            if idx == int(self._selected_idx) and bool(self._flash_green):
                rgba = (0.15, 0.95, 0.25, rgba[3])

        glPushMatrix()
        glTranslatef(float(pos[0]), float(pos[1]), float(pos[2]))
        try:
            glRotatef(float(rot[0]), 1.0, 0.0, 0.0)
            glRotatef(float(rot[1]), 0.0, 1.0, 0.0)
            glRotatef(float(rot[2]), 0.0, 0.0, 1.0)
        except Exception:
            pass

        if t == 'pyramid':
            self._draw_pyramid(rgba)
        else:
            self._draw_cube(rgba)
        glPopMatrix()

    def _on_paint(self, _evt: wx.PaintEvent) -> None:
        dc = wx.PaintDC(self)
        del dc
        self._ensure()
        self.SetCurrent(self._ctx)

        w, h = self.GetClientSize()
        bg = self._bg
        glClearColor(bg[0] / 255.0, bg[1] / 255.0, bg[2] / 255.0, bg[3] / 255.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        self._setup_3d(int(w), int(h))

        from OpenGL.GL import glEnable, glDisable

        if self._draw_mode == 'assembly':
            glEnable(GL_BLEND)
            self._draw_grid()
            glDisable(GL_BLEND)
            for p in self._pieces:
                self._draw_part(p)
        else:
            glDisable(GL_BLEND)
            for p in self._target:
                self._draw_part(p)

        self.SwapBuffers()


class Assembly3DMinigame(wx.Dialog):
    def __init__(self, parent=None, *, kind: str = 'KP'):
        super().__init__(parent, title='3D Assembly Minigame', style=wx.DEFAULT_DIALOG_STYLE)
        self.kind = str(kind or 'KP').upper()

        self.SetSize((900, 600))
        self.SetMinSize((900, 600))

        self._selection_flash_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_flash_timer, self._selection_flash_timer)
        self._selection_flash_timer.Start(33)

        self._game_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_game_timer, self._game_timer)
        self._game_timer.Start(16)
        self._last_game_update = time.perf_counter()

        self.selected_piece: Optional[int] = None

        self._build_ui()
        self._build_scene_for_kind()
        self._update_feedback()

    def reset(self, *, kind: str) -> None:
        self.kind = str(kind or 'KP').upper()
        self._build_scene_for_kind()
        self._ensure_piece_controls_match_scene()
        self._update_feedback()

    def _build_ui(self) -> None:
        self.SetBackgroundColour(wx.Colour(74, 74, 80))

        root = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(root)

        # Left: large empty grey + small reference view at bottom (like PySide screenshot).
        left_panel = wx.Panel(self)
        left_panel.SetBackgroundColour(wx.Colour(74, 74, 80))
        left = wx.BoxSizer(wx.VERTICAL)
        left_panel.SetSizer(left)
        root.Add(left_panel, 2, wx.EXPAND | wx.ALL, 10)

        ref_header = wx.Panel(left_panel)
        ref_header.SetBackgroundColour(wx.Colour(90, 90, 96))
        ref_header_s = wx.BoxSizer(wx.VERTICAL)
        ref_header.SetSizer(ref_header_s)
        ref_label = wx.StaticText(ref_header, label='Reference', style=wx.ALIGN_CENTER)
        f = ref_label.GetFont()
        f.SetPointSize(16)
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        ref_label.SetFont(f)
        ref_label.SetForegroundColour(wx.Colour(255, 255, 255))
        ref_header_s.Add(ref_label, 1, wx.EXPAND | wx.ALL, 8)
        left.Add(ref_header, 0, wx.EXPAND | wx.BOTTOM, 8)

        self.ref_view = _AsmGLCanvas(left_panel, bg=(80, 80, 85, 255), orbit=True)
        self.ref_view.set_camera(distance=8.0, elevation_deg=20.0, azimuth_deg=30.0, fov=60.0)
        left.Add(self.ref_view, 1, wx.EXPAND)

        # Right: assembly view + controls.
        right_panel = wx.Panel(self)
        right_panel.SetBackgroundColour(wx.Colour(74, 74, 80))
        right = wx.BoxSizer(wx.VERTICAL)
        right_panel.SetSizer(right)
        root.Add(right_panel, 1, wx.EXPAND | wx.ALL, 10)

        asm_header = wx.Panel(right_panel)
        asm_header.SetBackgroundColour(wx.Colour(90, 90, 96))
        asm_header_s = wx.BoxSizer(wx.VERTICAL)
        asm_header.SetSizer(asm_header_s)
        asm_label = wx.StaticText(asm_header, label='Assembly Area', style=wx.ALIGN_CENTER)
        f2 = asm_label.GetFont()
        f2.SetPointSize(16)
        f2.SetWeight(wx.FONTWEIGHT_BOLD)
        asm_label.SetFont(f2)
        asm_label.SetForegroundColour(wx.Colour(255, 255, 255))
        asm_header_s.Add(asm_label, 1, wx.EXPAND | wx.ALL, 8)
        right.Add(asm_header, 0, wx.EXPAND | wx.BOTTOM, 8)

        self.asm_view = _AsmGLCanvas(right_panel, bg=(240, 240, 245, 255))
        self.asm_view.set_camera(distance=4.8, elevation_deg=20.0, azimuth_deg=30.0, target=(0.0, 0.0, 0.0), fov=40.0)
        right.Add(self.asm_view, 1, wx.EXPAND)

        # Feedback + action buttons in a single row.
        ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        right.Add(ctrl_row, 0, wx.EXPAND | wx.TOP, 8)

        self.feedback_label = _StyledFeedback(right_panel, size=(420, 38))
        ctrl_row.Add(self.feedback_label, 0, wx.EXPAND | wx.RIGHT, 8)

        btn_reset = _QtLikeButton(right_panel, label='Reset')
        btn_reset.SetMinSize((90, 38))
        btn_reset.Bind(wx.EVT_BUTTON, lambda _evt: self._reset_pieces())
        ctrl_row.Add(btn_reset, 0, wx.RIGHT, 6)

        btn_check = _QtLikeButton(
            right_panel,
            label='Check',
            bg=(74, 222, 128),
            fg=(45, 45, 48),
            border=(34, 197, 94),
            hover_bg=(34, 197, 94),
            hover_border=(22, 163, 74),
        )
        btn_check.SetMinSize((90, 38))
        btn_check.Bind(wx.EVT_BUTTON, lambda _evt: self._check_assembly())
        ctrl_row.Add(btn_check, 0, wx.RIGHT, 6)

        btn_quit = _QtLikeButton(
            right_panel,
            label='Quit',
            bg=(239, 68, 68),
            fg=(255, 255, 255),
            border=(220, 38, 38),
            hover_bg=(220, 38, 38),
            hover_border=(185, 28, 28),
        )
        btn_quit.SetMinSize((90, 38))
        btn_quit.Bind(wx.EVT_BUTTON, lambda _evt: self.EndModal(wx.ID_CANCEL))
        ctrl_row.Add(btn_quit, 0)

        # Piece buttons row.
        self._piece_btn_panel = wx.Panel(right_panel)
        self._piece_btn_panel.SetBackgroundColour(wx.Colour(74, 74, 80))
        self._piece_btn_host = wx.BoxSizer(wx.HORIZONTAL)
        self._piece_btn_panel.SetSizer(self._piece_btn_host)
        right.Add(self._piece_btn_panel, 0, wx.EXPAND | wx.TOP, 8)

        # Arrow pad inside a container panel (like PySide arrow_widget).
        arrow_host = wx.Panel(right_panel)
        arrow_host.SetBackgroundColour(wx.Colour(90, 90, 96))
        arrow_s = wx.BoxSizer(wx.VERTICAL)
        arrow_host.SetSizer(arrow_s)
        right.Add(arrow_host, 0, wx.EXPAND | wx.TOP, 8)

        arrow_inner = wx.Panel(arrow_host)
        arrow_inner.SetBackgroundColour(wx.Colour(90, 90, 96))
        arrow_inner_s = wx.BoxSizer(wx.VERTICAL)
        arrow_inner.SetSizer(arrow_inner_s)
        arrow_s.Add(arrow_inner, 1, wx.EXPAND | wx.ALL, 8)

        arrow_grid = wx.GridSizer(3, 4, 4, 4)
        arrow_inner_s.Add(arrow_grid, 1, wx.EXPAND)

        def add_btn(lbl: str, fn) -> None:
            if lbl.strip() == '':
                p = wx.Panel(arrow_inner)
                p.SetBackgroundColour(wx.Colour(90, 90, 96))
                arrow_grid.Add(p, 0, wx.EXPAND)
                return
            if lbl in ('Z+', 'Z-'):
                b = _QtLikeButton(
                    arrow_inner,
                    label=lbl,
                    size=(40, 40),
                    bg=(255, 248, 220),
                    fg=(45, 45, 48),
                    border=(255, 215, 0),
                    hover_bg=(255, 237, 78),
                    hover_border=(255, 215, 0),
                    font_point=11,
                    padding_x=0,
                    padding_y=0,
                )
            else:
                b = _QtLikeButton(
                    arrow_inner,
                    label=lbl,
                    size=(40, 40),
                    pressed_bg=(255, 215, 0),
                    pressed_fg=(45, 45, 48),
                    pressed_border=(255, 237, 78),
                    padding_x=0,
                    padding_y=0,
                )
            b.Bind(wx.EVT_BUTTON, lambda _evt: fn())
            arrow_grid.Add(b, 0, wx.EXPAND)

        add_btn(' ', lambda: None)
        add_btn('↑', lambda: self._move_selected_piece(0, 1, 0))
        add_btn(' ', lambda: None)
        add_btn('Z+', lambda: self._move_selected_piece(0, 0, 1))

        add_btn('←', lambda: self._move_selected_piece(-1, 0, 0))
        add_btn(' ', lambda: None)
        add_btn('→', lambda: self._move_selected_piece(1, 0, 0))
        add_btn(' ', lambda: None)

        add_btn(' ', lambda: None)
        add_btn('↓', lambda: self._move_selected_piece(0, -1, 0))
        add_btn(' ', lambda: None)
        add_btn('Z-', lambda: self._move_selected_piece(0, 0, -1))

        self.piece_btns: list[wx.ToggleButton] = []

    def _ensure_piece_controls_match_scene(self) -> None:
        for b in list(self.piece_btns):
            try:
                b.Destroy()
            except Exception:
                pass
        self.piece_btns = []

        parent = getattr(self, '_piece_btn_panel', None) or self
        for i, piece in enumerate(getattr(self, 'pieces', []) or []):
            b = _QtLikeButton(parent, label=f"{str(piece.get('type', 'cube')).capitalize()} {i + 1}", toggle=True)
            b.SetMinSize((140, 40))
            b.Bind(wx.EVT_TOGGLEBUTTON, lambda _evt, idx=i: self._select_piece(idx))
            self._piece_btn_host.Add(b, 0, wx.RIGHT, 6)
            self.piece_btns.append(b)
        try:
            if getattr(self, '_piece_btn_panel', None) is not None:
                self._piece_btn_panel.Layout()
        except Exception:
            pass
        self.Layout()

    def _on_game_timer(self, _evt: wx.TimerEvent) -> None:
        parent = self.GetParent()
        if parent is not None and hasattr(parent, 'core'):
            try:
                current_time = time.perf_counter()
                dt = current_time - float(getattr(self, '_last_game_update', current_time))
                dt = min(dt, 0.1)
                parent.core.elapsed_s += dt
                self._last_game_update = current_time
            except Exception:
                pass

    def _on_flash_timer(self, _evt: wx.TimerEvent) -> None:
        if self.selected_piece is None:
            try:
                self.asm_view.set_selection(None, flash_green=False)
            except Exception:
                pass
            return
        idx = int(self.selected_piece)
        if idx < 0 or idx >= len(getattr(self, 'pieces', []) or []):
            return
        if idx < 0 or idx >= len(getattr(self, 'placed', []) or []):
            return
        if self.placed[idx]:
            try:
                self.asm_view.set_selection(None, flash_green=False)
            except Exception:
                pass
            return

        # 2.5Hz-ish blink like the PySide "selected" flash.
        flash_green = (int(time.perf_counter() * 5.0) % 2) == 0
        try:
            self.asm_view.set_selection(idx, flash_green=flash_green)
        except Exception:
            pass

    def _build_scene_for_kind(self) -> None:
        self.pieces = self._generate_pieces_3d(self.kind)
        self.target_structure = self._generate_target_structure_3d(self.kind)
        self.placed = [False] * len(self.pieces)
        self.selected_piece = None

        # Tag each piece with a stable index so the GL renderer can highlight it.
        for i, p in enumerate(self.pieces):
            try:
                p['_idx'] = int(i)
            except Exception:
                pass

        self._ensure_piece_controls_match_scene()

        self.ref_view.set_scene(pieces=self.pieces, target=self.target_structure, mode='reference')
        self.asm_view.set_scene(pieces=self.pieces, target=self.target_structure, mode='assembly')

        # Auto-center assembly camera target so the grid + pieces fill the canvas instead of sitting with wide margins.
        try:
            pts = []
            for p in self.pieces:
                pos = p.get('pos')
                if pos is None:
                    continue
                pts.append((float(pos[0]), float(pos[1]), float(pos[2])))
            if pts:
                cx = float(sum(x for x, _, _ in pts) / len(pts))
                cy = float(sum(y for _, y, _ in pts) / len(pts))
                cz = float(sum(z for _, _, z in pts) / len(pts))
                self.asm_view.set_camera(distance=4.8, elevation_deg=20.0, azimuth_deg=30.0, target=(cx, cy, cz), fov=40.0)
        except Exception:
            pass

    def _generate_pieces_3d(self, kind: str):
        yellow = (255, 223, 0, 255)
        blue = (0, 149, 255, 255)
        red = (255, 69, 0, 255)

        kind = str(kind or 'KP').upper()

        if kind == 'KP':
            return [
                {'type': 'cube', 'color': yellow, 'pos': np.array([2, 0, 0], dtype=float), 'rot': [0, 0, 0]},
                {'type': 'cube', 'color': blue, 'pos': np.array([-2, 0, 0], dtype=float), 'rot': [0, 0, 0]},
                {'type': 'pyramid', 'color': red, 'pos': np.array([0, 0, 0], dtype=float), 'rot': [0, 0, 0]},
            ]

        if kind == 'K':
            colors = [blue, yellow, red, red, blue]
            pieces = []
            for i, col in enumerate(colors):
                pieces.append({'type': 'cube', 'color': col, 'pos': np.array([-2 + i, 0, 0], dtype=float), 'rot': [0, 0, 0]})
            return pieces

        colors = [yellow, red, blue, yellow]
        types = ['cube', 'cube', 'pyramid', 'pyramid']
        pieces = []
        for i, (t, col) in enumerate(zip(types, colors)):
            pieces.append({'type': t, 'color': col, 'pos': np.array([-2 + i, 0, 0], dtype=float), 'rot': [0, 0, 0]})
        return pieces

    def _generate_target_structure_3d(self, kind: str):
        kind = str(kind or 'KP').upper()

        if kind == 'KP':
            return [
                {'type': 'cube', 'pos': np.array([0, 0, 0], dtype=float), 'rot': [0, 0, 0], 'color': self.pieces[0]['color']},
                {'type': 'cube', 'pos': np.array([0, 0, 1], dtype=float), 'rot': [0, 0, 0], 'color': self.pieces[1]['color']},
                {'type': 'pyramid', 'pos': np.array([0, 0, 2], dtype=float), 'rot': [0, 0, 0], 'color': self.pieces[2]['color']},
            ]

        if kind == 'K':
            return [
                {'type': 'cube', 'pos': np.array([0, 0, 0], dtype=float), 'rot': [0, 0, 0], 'color': self.pieces[0]['color']},
                {'type': 'cube', 'pos': np.array([1, 0, 0], dtype=float), 'rot': [0, 0, 0], 'color': self.pieces[1]['color']},
                {'type': 'cube', 'pos': np.array([2, 0, 0], dtype=float), 'rot': [0, 0, 0], 'color': self.pieces[2]['color']},
                {'type': 'cube', 'pos': np.array([0, 1, 0], dtype=float), 'rot': [0, 0, 0], 'color': self.pieces[3]['color']},
                {'type': 'cube', 'pos': np.array([1, 1, 0], dtype=float), 'rot': [0, 0, 0], 'color': self.pieces[4]['color']},
            ]

        return [
            {'type': 'cube', 'pos': np.array([0, 0, 0], dtype=float), 'rot': [0, 0, 0], 'color': self.pieces[0]['color']},
            {'type': 'cube', 'pos': np.array([1, 0, 0], dtype=float), 'rot': [0, 0, 0], 'color': self.pieces[1]['color']},
            {'type': 'pyramid', 'pos': np.array([0, 1, 0], dtype=float), 'rot': [0, 0, 0], 'color': self.pieces[2]['color']},
            {'type': 'pyramid', 'pos': np.array([1, 1, 0], dtype=float), 'rot': [0, 0, 0], 'color': self.pieces[3]['color']},
        ]

    GRID_MIN = -2
    GRID_MAX = 2
    Z_MIN = 0
    Z_MAX = 2

    def _select_piece(self, idx: int) -> None:
        self.selected_piece = int(idx)
        for i, b in enumerate(self.piece_btns):
            try:
                b.SetValue(i == self.selected_piece)
            except Exception:
                pass
        self._update_feedback()

    def _move_selected_piece(self, dx: int, dy: int, dz: int) -> None:
        if self.selected_piece is None:
            return
        idx = int(self.selected_piece)
        if idx < 0 or idx >= len(self.pieces):
            return
        if self.placed[idx]:
            return

        pos = self.pieces[idx]['pos']
        new_pos = pos.copy()
        new_pos[0] = max(self.GRID_MIN, min(self.GRID_MAX, new_pos[0] + dx))
        new_pos[1] = max(self.GRID_MIN, min(self.GRID_MAX, new_pos[1] + dy))
        new_pos[2] = max(self.Z_MIN, min(self.Z_MAX, new_pos[2] + dz))
        self.pieces[idx]['pos'] = new_pos
        self.asm_view.Refresh(False)
        self._update_feedback()

    def _reset_pieces(self) -> None:
        for i, piece in enumerate(self.pieces):
            if self.kind == 'KP':
                piece['pos'] = np.array([2 if i == 0 else -2 if i == 1 else 0, 0, 0], dtype=float)
            else:
                piece['pos'] = np.array([-2 + i, 0, 0], dtype=float)
        self.placed = [False] * len(self.pieces)
        self.selected_piece = None
        self.asm_view.Refresh(False)
        self._update_feedback()

    def _update_feedback(self) -> None:
        for i, b in enumerate(self.piece_btns):
            try:
                b.SetValue(self.selected_piece == i)
            except Exception:
                pass

        if all(self.placed) and self.pieces:
            self.feedback_label.set_text('🎉 Perfect Assembly! 🎉', mode='success')
        else:
            self.feedback_label.set_text('Select piece → Use arrows to move → Z+/- for height', mode='normal')

    def _check_assembly(self) -> None:
        def neighbors_from_positions(positions: list[np.ndarray]) -> dict[int, set[int]]:
            adj: dict[int, set[int]] = {i: set() for i in range(len(positions))}
            ipos = [np.round(p).astype(int) for p in positions]
            for i in range(len(ipos)):
                for j in range(i + 1, len(ipos)):
                    diff = np.abs(ipos[i] - ipos[j])
                    touching = (np.sum(diff == 1) == 1) and (np.sum(diff == 0) == 2)
                    if touching:
                        adj[i].add(j)
                        adj[j].add(i)
            return adj

        color_type_ok = True
        for i, target in enumerate(self.target_structure):
            if i >= len(self.pieces):
                color_type_ok = False
                break
            if self.pieces[i]['type'] != target['type']:
                color_type_ok = False
                break

        target_adj = neighbors_from_positions([t['pos'] for t in self.target_structure])
        placed_adj = neighbors_from_positions([p['pos'] for p in self.pieces])

        adjacency_ok = True
        for i in range(len(self.target_structure)):
            if placed_adj.get(i, set()) != target_adj.get(i, set()):
                adjacency_ok = False
                break

        if color_type_ok and adjacency_ok:
            self.feedback_label.set_text('Perfect Assembly!', mode='success')
            self._show_congratulations()
            self.EndModal(wx.ID_OK)
            return

        self.feedback_label.set_text('❌ Incorrect - Keep Trying!', mode='error')

    def _show_congratulations(self) -> None:
        dlg = wx.Dialog(self, title='Success!', style=wx.DEFAULT_DIALOG_STYLE)
        dlg.SetBackgroundColour(wx.Colour(74, 74, 80))
        s = wx.BoxSizer(wx.VERTICAL)
        dlg.SetSizer(s)

        t1 = wx.StaticText(dlg, label='Congratulations!')
        f1 = t1.GetFont()
        f1.SetPointSize(24)
        f1.SetWeight(wx.FONTWEIGHT_BOLD)
        t1.SetFont(f1)
        t1.SetForegroundColour(wx.Colour(74, 222, 128))
        s.Add(t1, 0, wx.ALIGN_CENTER | wx.TOP | wx.LEFT | wx.RIGHT, 18)

        t2 = wx.StaticText(dlg, label='You have successfully assembled the structure!')
        f2 = t2.GetFont()
        f2.SetPointSize(16)
        f2.SetWeight(wx.FONTWEIGHT_NORMAL)
        t2.SetFont(f2)
        t2.SetForegroundColour(wx.Colour(255, 255, 255))
        s.Add(t2, 0, wx.ALIGN_CENTER | wx.TOP | wx.LEFT | wx.RIGHT, 12)

        t3 = wx.StaticText(dlg, label='You collected a key fragment!')
        f3 = t3.GetFont()
        f3.SetPointSize(14)
        f3.SetWeight(wx.FONTWEIGHT_BOLD)
        t3.SetFont(f3)
        t3.SetForegroundColour(wx.Colour(255, 215, 0))
        s.Add(t3, 0, wx.ALIGN_CENTER | wx.TOP | wx.LEFT | wx.RIGHT, 8)

        ok = _QtLikeButton(dlg, label='OK')
        ok.Bind(wx.EVT_BUTTON, lambda _evt: dlg.EndModal(wx.ID_OK))
        s.Add(ok, 0, wx.ALIGN_CENTER | wx.ALL, 16)

        dlg.Fit()
        dlg.CentreOnParent()
        dlg.ShowModal()
        dlg.Destroy()

    def Destroy(self) -> bool:
        try:
            self._selection_flash_timer.Stop()
        except Exception:
            pass
        try:
            self._game_timer.Stop()
        except Exception:
            pass
        return super().Destroy()
