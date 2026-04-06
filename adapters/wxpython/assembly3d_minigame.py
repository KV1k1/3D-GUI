"""
assembly3d_minigame.py  –  wxPython, OpenGL 3.3 core profile.

_AsmGLCanvas is a full rewrite using VAOs/VBOs + GLSL shaders (same approach as
kivy_assembly3d.py).  All legacy fixed-function calls (glBegin/glEnd,
glMatrixMode, glFrustum, gluLookAt, glColor4f …) are gone.

The rest of the file – _StyledButton, _StyledFeedback, Assembly3DMinigame – is
unchanged from the previous wxPython version.
"""

import ctypes
import math
import time
from typing import Any, List, Optional, Tuple

import OpenGL.GL as GL
import wx
from wx import glcanvas


# ─────────────────────────────────────────────────────────────────────────────
# Styled button / feedback widgets  (unchanged from original)
# ─────────────────────────────────────────────────────────────────────────────

class _StyledButton(wx.Control):
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
        self._checked_bg = tuple(int(x) for x in checked_bg)
        self._checked_fg = tuple(int(x) for x in checked_fg)
        self._checked_border = tuple(int(x) for x in checked_border)
        self._hover_bg = tuple(int(x) for x in hover_bg)
        self._hover_border = tuple(int(x) for x in hover_border)
        self._pressed_bg = tuple(int(x) for x in (pressed_bg or self._bg))
        self._pressed_fg = tuple(int(x) for x in (pressed_fg or self._fg))
        self._pressed_border = tuple(int(x)
                                     for x in (pressed_border or self._border))
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
        self.Bind(wx.EVT_PAINT,         self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _e: None)
        self.Bind(wx.EVT_ENTER_WINDOW,  self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW,  self._on_leave)
        self.Bind(wx.EVT_LEFT_DOWN,     self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP,       self._on_left_up)

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
            if 0 <= x < w and 0 <= y < h:
                if self._toggle:
                    self._value = not bool(self._value)
                et = wx.EVT_TOGGLEBUTTON.typeId if self._toggle else wx.EVT_BUTTON.typeId
                ce = wx.CommandEvent(et, self.GetId())
                ce.SetEventObject(self)
                try:
                    ce.SetInt(1 if self._value else 0)
                except Exception:
                    pass
                wx.PostEvent(self.GetEventHandler(), ce)
        self.Refresh(False)
        evt.Skip()

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

        path = gc.CreatePath()
        r = float(max(0, self._radius))
        path.AddRoundedRectangle(0.5, 0.5, float(w) - 1.0, float(h) - 1.0, r)
        gc.SetBrush(wx.Brush(wx.Colour(*bg)))
        gc.SetPen(wx.Pen(wx.Colour(*border), width=2))
        gc.DrawPath(path)

        gc.SetFont(self.GetFont(), wx.Colour(*fg))
        tw, th = gc.GetTextExtent(self._label)
        gc.DrawText(self._label, float((w - tw) / 2.0), float((h - th) / 2.0))


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
        f.SetPointSize(13)
        f.SetWeight(wx.FONTWEIGHT_NORMAL)
        self.SetFont(f)

    def set_text(self, text: str, *, mode: str = 'normal') -> None:
        self._text = str(text)
        self._mode = str(mode or 'normal')
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

        if self._mode == 'success':
            bg = (45, 90, 45)
            border = (74, 222, 128)
            weight = wx.FONTWEIGHT_BOLD
            border_w = 2
        elif self._mode == 'error':
            bg = (90, 45, 45)
            border = (239, 68, 68)
            weight = wx.FONTWEIGHT_BOLD
            border_w = 1
        else:
            bg = (90, 90, 96)
            border = (122, 122, 128)
            weight = wx.FONTWEIGHT_NORMAL
            border_w = 1

        f = self.GetFont()
        f.SetWeight(int(weight))
        self.SetFont(f)

        path = gc.CreatePath()
        path.AddRoundedRectangle(0.5, 0.5, float(w) - 1.0, float(h) - 1.0, 6.0)
        gc.SetBrush(wx.Brush(wx.Colour(*bg)))
        gc.SetPen(wx.Pen(wx.Colour(*border), width=int(border_w)))
        gc.DrawPath(path)

        text = str(self._text or '')
        pad = 6
        max_w = max(0, w - pad * 2)
        if max_w > 0:
            try:
                text = wx.Control.Ellipsize(text, dc, wx.ELLIPSIZE_END, max_w)
            except Exception:
                pass
        gc.SetFont(self.GetFont(), wx.Colour(255, 255, 255))
        tw, th = gc.GetTextExtent(text)
        gc.DrawText(text, max(float(pad), float((w - tw) / 2.0)),
                    max(float(pad), float((h - th) / 2.0)))


# ─────────────────────────────────────────────────────────────────────────────
# GLSL shader (shared, lazily compiled once per GL context)
# ─────────────────────────────────────────────────────────────────────────────

_VERT = b"""
#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec4 aColor;
out vec4 vColor;
uniform mat4 uMVP;
void main(){ vColor=aColor; gl_Position=uMVP*vec4(aPos,1.0); }
"""
_FRAG = b"""
#version 330 core
in vec4 vColor; out vec4 FragColor;
void main(){ FragColor=vColor; }
"""

# Per-canvas program handle (keyed by GLContext id so multi-window apps work)
_prog_cache: dict[int, int] = {}


def _get_prog(ctx_id: int) -> int:
    if ctx_id in _prog_cache:
        return _prog_cache[ctx_id]

    def _sh(src: bytes, kind: int) -> int:
        s = GL.glCreateShader(kind)
        GL.glShaderSource(s, src)
        GL.glCompileShader(s)
        if not GL.glGetShaderiv(s, GL.GL_COMPILE_STATUS):
            raise RuntimeError(GL.glGetShaderInfoLog(s).decode())
        return s

    p = GL.glCreateProgram()
    GL.glAttachShader(p, _sh(_VERT, GL.GL_VERTEX_SHADER))
    GL.glAttachShader(p, _sh(_FRAG, GL.GL_FRAGMENT_SHADER))
    GL.glLinkProgram(p)
    if not GL.glGetProgramiv(p, GL.GL_LINK_STATUS):
        raise RuntimeError(GL.glGetProgramInfoLog(p).decode())
    _prog_cache[ctx_id] = p
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Math helpers  (column-major, identical to kivy_assembly3d.py)
# ─────────────────────────────────────────────────────────────────────────────

def _mul(a: List[float], b: List[float]) -> List[float]:
    o = [0.0] * 16
    for c in range(4):
        for r in range(4):
            o[r + c * 4] = sum(a[r + k * 4] * b[k + c * 4] for k in range(4))
    return o


def _persp(fov: float, asp: float, n: float, f: float) -> List[float]:
    t = 1.0 / math.tan(math.radians(fov) / 2.0)
    nf = 1.0 / (n - f)
    return [t / asp, 0, 0, 0,  0, t, 0, 0,  0, 0, (f + n) * nf, -1,  0, 0, 2 * f * n * nf, 0]


def _lookat(ex: float, ey: float, ez: float,
            cx: float, cy: float, cz: float,
            ux: float, uy: float, uz: float) -> List[float]:
    fx, fy, fz = cx - ex, cy - ey, cz - ez
    fl = math.sqrt(fx*fx + fy*fy + fz*fz) or 1e-9
    fx /= fl
    fy /= fl
    fz /= fl
    rx = fy*uz - fz*uy
    ry = fz*ux - fx*uz
    rz = fx*uy - fy*ux
    rl = math.sqrt(rx*rx + ry*ry + rz*rz) or 1e-9
    rx /= rl
    ry /= rl
    rz /= rl
    upx = ry*fz - rz*fy
    upy = rz*fx - rx*fz
    upz = rx*fy - ry*fx
    return [rx, upx, -fx, 0,
            ry, upy, -fy, 0,
            rz, upz, -fz, 0,
            -(rx*ex + ry*ey + rz*ez),
            -(upx*ex + upy*ey + upz*ez),
            (fx*ex + fy*ey + fz*ez), 1]


def _tmat(tx: float, ty: float, tz: float) -> List[float]:
    m = [1, 0, 0, 0,  0, 1, 0, 0,  0, 0, 1, 0,  0, 0, 0, 1]
    m[12] = tx
    m[13] = ty
    m[14] = tz
    return m


def _camera_vp(w: int, h: int,
               dist: float = 8.0,
               elev_deg: float = 20.0,
               azim_deg: float = 30.0,
               fov: float = 60.0) -> List[float]:
    """Build VP matrix.  Z is up, camera orbits in azimuth around Z-up world."""
    elev = math.radians(elev_deg)
    azim = math.radians(azim_deg)
    ex = dist * math.cos(elev) * math.cos(azim)
    ey = dist * math.cos(elev) * math.sin(azim)
    ez = dist * math.sin(elev)
    proj = _persp(fov, float(w) / float(max(1, h)), 0.1, 80.0)
    view = _lookat(ex, ey, ez,  0, 0, 0,  0, 0, 1)   # Z is up
    return _mul(proj, view)


# ─────────────────────────────────────────────────────────────────────────────
# Geometry helpers  (identical to kivy_assembly3d.py)
# ─────────────────────────────────────────────────────────────────────────────

def _cube(col: Tuple[float, float, float, float]) -> List[float]:
    r, g, b, a = col
    v: List[float] = []
    for q in [
        [(-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5)],
        [(0.5, -0.5, -0.5), (-0.5, -0.5, -0.5),
         (-0.5, 0.5, -0.5), (0.5, 0.5, -0.5)],
        [(-0.5, -0.5, -0.5), (-0.5, -0.5, 0.5),
         (-0.5, 0.5, 0.5), (-0.5, 0.5, -0.5)],
        [(0.5, -0.5, 0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (0.5, 0.5, 0.5)],
        [(-0.5, 0.5, 0.5), (0.5, 0.5, 0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5)],
        [(-0.5, -0.5, -0.5), (0.5, -0.5, -0.5),
         (0.5, -0.5, 0.5), (-0.5, -0.5, 0.5)],
    ]:
        p0, p1, p2, p3 = q
        for p in [p0, p1, p2, p0, p2, p3]:
            v.extend([*p, r, g, b, a])
    return v


def _pyramid(col: Tuple[float, float, float, float]) -> List[float]:
    r, g, b, a = col
    verts = [(0.0, 0.5, 0.0), (0.5, -0.5, 0.5), (0.5, -0.5, -0.5),
             (-0.5, -0.5, -0.5), (-0.5, -0.5, 0.5)]
    faces = [(0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1), (1, 2, 3), (1, 3, 4)]
    v: List[float] = []
    for a0, b0, c0 in faces:
        for p in (verts[a0], verts[b0], verts[c0]):
            v.extend([p[0], p[1], p[2], r, g, b, a])
    return v


def _grid_verts() -> List[float]:
    """
    X-Y plane grid at Z=0 with half-integer offsets.
    Grid lines at half-integers so pieces at integer positions sit IN cells.
    """
    v: List[float] = []
    GREY = (0.30, 0.30, 0.30, 0.22)
    GOLD = (1.0,  0.84, 0.0,  0.32)
    for x in range(-4, 5):
        c = GOLD if x == 0 else GREY
        xf = float(x) - 0.5  # Half-integer offset for centered grid cells
        v.extend([xf, -1.5, 0, *c,  xf, 2.5, 0, *c])
    for y in range(-1, 4):
        c = GOLD if y == 0 else GREY
        yf = float(y) - 0.5  # Half-integer offset for centered grid cells
        v.extend([-4, yf, 0, *c,  4, yf, 0, *c])
    return v


def _upload(raw: List[float]) -> Tuple[int, int]:
    """Upload vertex data (x,y,z,r,g,b,a per vertex) into a new VAO/VBO."""
    if not raw:
        return 0, 0
    n = len(raw) // 7
    data = (ctypes.c_float * len(raw))(*raw)
    stride = 7 * 4
    vao = GL.glGenVertexArrays(1)
    GL.glBindVertexArray(vao)
    vbo = GL.glGenBuffers(1)
    GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
    GL.glBufferData(GL.GL_ARRAY_BUFFER, ctypes.sizeof(
        data), data, GL.GL_STATIC_DRAW)
    GL.glVertexAttribPointer(
        0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(0))
    GL.glEnableVertexAttribArray(0)
    GL.glVertexAttribPointer(
        1, 4, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(12))
    GL.glEnableVertexAttribArray(1)
    GL.glBindVertexArray(0)
    return int(vao), n


# ─────────────────────────────────────────────────────────────────────────────
# Piece / target data  (plain lists, no numpy – matches kivy_assembly3d.py)
# ─────────────────────────────────────────────────────────────────────────────

_Y_COL = (1.0, 0.875, 0.0, 1.0)   # yellow
_B_COL = (0.0, 0.584, 1.0, 1.0)   # blue
_R_COL = (1.0, 0.271, 0.0, 1.0)   # red


def _make_pieces(kind: str) -> List[dict]:
    """Initial piece positions. Pieces at z=0.5 sit on grid (matching Kivy/PySide6)."""
    k = (kind or 'KP').upper()
    if k == 'KP':
        return [
            {'type': 'cube',    'color': _Y_COL, 'pos': [2., 0., 0.5]},
            {'type': 'cube',    'color': _B_COL, 'pos': [-2., 0., 0.5]},
            {'type': 'pyramid', 'color': _R_COL, 'pos': [0., 0., 0.5]},
        ]
    if k == 'K':
        cs = [_B_COL, _Y_COL, _R_COL, _R_COL, _B_COL]
        return [{'type': 'cube', 'color': c, 'pos': [-3. + i, 0., 0.5]} for i, c in enumerate(cs)]
    return [
        {'type': 'cube',    'color': _Y_COL, 'pos': [-2., 0., 0.5]},
        {'type': 'cube',    'color': _R_COL, 'pos': [-1., 0., 0.5]},
        {'type': 'pyramid', 'color': _B_COL, 'pos': [0., 0., 0.5]},
        {'type': 'pyramid', 'color': _Y_COL, 'pos': [1., 0., 0.5]},
    ]


def _make_target(kind: str) -> List[dict]:
    k = (kind or 'KP').upper()
    if k == 'KP':
        return [
            {'type': 'cube',    'pos': [0, 0, 0]},
            {'type': 'cube',    'pos': [0, 1, 0]},
            {'type': 'pyramid', 'pos': [0, 2, 0]},
        ]
    if k == 'K':
        return [
            {'type': 'cube', 'pos': [0, 0, 0]}, {
                'type': 'cube', 'pos': [1, 0, 0]},
            {'type': 'cube', 'pos': [2, 0, 0]}, {
                'type': 'cube', 'pos': [0, 1, 0]},
            {'type': 'cube', 'pos': [1, 1, 0]},
        ]
    return [
        {'type': 'cube',    'pos': [0, 0, 0]}, {
            'type': 'cube',    'pos': [1, 0, 0]},
        {'type': 'pyramid', 'pos': [0, 1, 0]}, {
            'type': 'pyramid', 'pos': [1, 1, 0]},
    ]

# ─────────────────────────────────────────────────────────────────────────────
# _AsmGLCanvas  –  core-profile GL canvas
# ─────────────────────────────────────────────────────────────────────────────


# GL context attributes for core profile (matching main renderer)
_GL_ATTRS = [
    wx.glcanvas.WX_GL_RGBA,
    wx.glcanvas.WX_GL_DOUBLEBUFFER,
    wx.glcanvas.WX_GL_CORE_PROFILE,
    wx.glcanvas.WX_GL_MAJOR_VERSION, 3,
    wx.glcanvas.WX_GL_MINOR_VERSION, 3,
    wx.glcanvas.WX_GL_DEPTH_SIZE, 24,
]


class _AsmGLCanvas(wx.glcanvas.GLCanvas):
    """
    Core-profile OpenGL canvas for one 3-D view panel (reference or assembly).

    Scene data is stored as (vao, vtx_count) pairs plus translation matrices so
    that the same VAOs can be reused with different positions without re-uploading.

    public API (called by Assembly3DMinigame):
      set_scene(vaos, mats, gvao=0, gvtx=0)   – set piece VAOs + grid VAO
      set_camera(dist, elev, azim, azim_extra, fov)
      request_redraw()
    """

    def __init__(self, parent: wx.Window, *,
                 bg_dark: bool = True,
                 orbit: bool = False):
        attribs = [
            glcanvas.WX_GL_RGBA,
            glcanvas.WX_GL_DOUBLEBUFFER,
            glcanvas.WX_GL_DEPTH_SIZE, 24,
            0,
        ]
        super().__init__(parent, attribList=attribs)

        # Try to obtain a core-profile 3.3 context
        try:
            ca = glcanvas.GLContextAttrs()
            ca = ca.PlatformDefaults().CoreProfile().OGLVersion(3, 3).EndList()
            self._ctx = glcanvas.GLContext(self, ctxAttribs=ca)
        except Exception:
            self._ctx = glcanvas.GLContext(self)

        self._bg_dark = bool(bg_dark)
        self._orbit = bool(orbit)
        self._initialized = False

        # Camera params
        self._cam_dist = 8.0
        self._cam_elev = 20.0   # degrees
        self._cam_azim = 30.0   # degrees
        self._cam_azim_extra = 0.0   # added by orbit drag
        self._cam_elev_extra = 0.0   # added by orbit drag
        self._fov = 60.0

        # Scene
        self._vaos: List[Tuple[int, int]] = []   # (vao, vtx_count) per piece
        self._mats: List[List[float]] = []   # translation matrix per piece
        self._gvao: int = 0                       # grid VAO
        self._gvtx: int = 0                       # grid vertex count

        # Orbit drag
        self._dragging = False
        self._last_mouse: Optional[Tuple[int, int]] = None

        self.Bind(wx.EVT_PAINT,  self._on_paint)
        self.Bind(wx.EVT_SIZE, lambda _e: self.Refresh(False))
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _e: None)

        if self._orbit:
            self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
            self.Bind(wx.EVT_LEFT_UP,   self._on_left_up)
            self.Bind(wx.EVT_MOTION,    self._on_motion)

        # Refresh timer so animation / flash stays smooth even without user input
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda _e: self.Refresh(False), self._timer)
        self._timer.Start(33)   # ~30 fps

    # ── orbit drag ────────────────────────────────────────────────────────────

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
        if not self._dragging or not evt.Dragging() or not evt.LeftIsDown():
            return
        if self._last_mouse is None:
            self._last_mouse = (evt.GetX(), evt.GetY())
            return
        lx, ly = self._last_mouse
        dx, dy = float(evt.GetX() - lx), float(evt.GetY() - ly)
        self._last_mouse = (evt.GetX(), evt.GetY())
        self._cam_azim_extra -= dx * 0.4
        self._cam_elev_extra += dy * 0.4
        self._cam_elev_extra = max(-89.0, min(89.0, self._cam_elev_extra))
        self.Refresh(False)

    # ── public API ────────────────────────────────────────────────────────────

    def set_scene(self, vaos: List[Tuple[int, int]], mats: List[List[float]],
                  gvao: int = 0, gvtx: int = 0) -> None:
        self._vaos = vaos
        self._mats = mats
        self._gvao = gvao
        self._gvtx = gvtx
        self.Refresh(False)

    def set_camera(self, dist: float = 8.0, elev: float = 20.0,
                   azim: float = 30.0, fov: float = 60.0) -> None:
        self._cam_dist = float(dist)
        self._cam_elev = float(elev)
        self._cam_azim = float(azim)
        self._fov = float(fov)
        self.Refresh(False)

    def request_redraw(self) -> None:
        self.Refresh(False)

    # ── GL lifecycle ──────────────────────────────────────────────────────────

    def _ensure(self) -> None:
        if self._initialized:
            return
        self.SetCurrent(self._ctx)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthFunc(GL.GL_LEQUAL)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glDisable(GL.GL_CULL_FACE)
        # Compile shader for this context
        try:
            _get_prog(id(self._ctx))
        except Exception as e:
            print(f'[_AsmGLCanvas] shader compile failed: {e}')
        self._initialized = True

    # ── paint ─────────────────────────────────────────────────────────────────

    def _on_paint(self, _evt: wx.PaintEvent) -> None:
        _ = wx.PaintDC(self)
        self._ensure()
        self.SetCurrent(self._ctx)

        w, h = self.GetClientSize()
        if w < 2 or h < 2:
            return

        # Clear with background colour
        if self._bg_dark:
            GL.glClearColor(0.314, 0.314, 0.333, 1.0)   # #505055
        else:
            GL.glClearColor(0.941, 0.941, 0.961, 1.0)   # #f0f0f5
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        GL.glViewport(0, 0, int(w), int(h))

        if not self._vaos and not self._gvao:
            self.SwapBuffers()
            return

        prog = _get_prog(id(self._ctx))
        GL.glUseProgram(prog)
        loc = GL.glGetUniformLocation(prog, b'uMVP')

        # Build camera VP
        elev = self._cam_elev + self._cam_elev_extra
        azim = self._cam_azim + self._cam_azim_extra
        vp = _camera_vp(w, h, self._cam_dist, elev, azim, self._fov)

        # Draw grid
        if self._gvao and self._gvtx:
            GL.glUniformMatrix4fv(loc, 1, GL.GL_FALSE,
                                  (ctypes.c_float * 16)(*vp))
            GL.glBindVertexArray(self._gvao)
            GL.glDrawArrays(GL.GL_LINES, 0, self._gvtx)
            GL.glBindVertexArray(0)

        # Draw pieces
        for i, (vao, vtx) in enumerate(self._vaos):
            if not vao or not vtx:
                continue
            m = self._mats[i] if i < len(self._mats) else _tmat(0, 0, 0)
            mvp = _mul(vp, m)
            GL.glUniformMatrix4fv(loc, 1, GL.GL_FALSE,
                                  (ctypes.c_float * 16)(*mvp))
            GL.glBindVertexArray(vao)
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, vtx)
            GL.glBindVertexArray(0)

        GL.glUseProgram(0)
        self.SwapBuffers()

    def Destroy(self) -> bool:
        try:
            self._timer.Stop()
        except Exception:
            pass
        return super().Destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Assembly3DMinigame  –  wx.Dialog wrapping the two GL canvases
# ─────────────────────────────────────────────────────────────────────────────

class Assembly3DMinigame(wx.Dialog):
    """
    3-D Assembly Minigame dialog.

    Usage (same as before):
        dlg = Assembly3DMinigame(parent, kind='KP')
        if dlg.ShowModal() == wx.ID_OK:
            ...
        # or call reset(kind=...) to reuse the same instance.
    """

    GRID_MIN = -4
    GRID_MAX = 4
    Z_MIN = 0
    Z_MAX = 2

    def __init__(self, parent=None, *, kind: str = 'KP'):
        super().__init__(parent, title='3D Assembly Minigame',
                         style=wx.DEFAULT_DIALOG_STYLE)
        self.kind = str(kind or 'KP').upper()

        self.SetSize((900, 600))
        self.SetMinSize((900, 600))

        self.selected_piece: Optional[int] = None

        # VAO lists - separate for each canvas since VAOs cannot be shared between contexts
        # (vao, vtx) per piece for asm_view
        self._piece_vaos: List[Tuple[int, int]] = []
        # (vao, vtx) per piece for ref_view
        self._ref_vaos: List[Tuple[int, int]] = []
        # duplicate for ref_view context
        self._piece_vaos_ref: List[Tuple[int, int]] = []
        # duplicate for ref_view context
        self._ref_vaos_ref: List[Tuple[int, int]] = []
        self._gvao: int = 0
        self._gvtx: int = 0
        # grid for ref_view (not used but kept for consistency)
        self._gvao_ref: int = 0
        self._gl_built = False

        # Flash state
        self._flash_vaos: List[Tuple[int, int]] = []  # green flash VAOs
        self._flash_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_flash_timer, self._flash_timer)
        self._flash_timer.Start(33)

        self._build_ui()
        self._build_scene_for_kind()
        self._update_feedback()

        # Center on parent like PySide6
        try:
            self.CentreOnParent()
        except Exception:
            pass

        # Build GL after the window is shown so context is ready
        self.Bind(wx.EVT_SHOW, self._on_show)

    # ── show / close ──────────────────────────────────────────────────────────

    def _on_show(self, evt: wx.ShowEvent) -> None:
        if evt.IsShown():
            wx.CallAfter(self._build_gl)
        evt.Skip()

    def reset(self, *, kind: str) -> None:
        self.kind = str(kind or 'KP').upper()
        self._build_scene_for_kind()
        self._ensure_piece_controls_match_scene()
        self._update_views()
        self._update_feedback()

    def Destroy(self) -> bool:
        try:
            self._flash_timer.Stop()
        except Exception:
            pass
        return super().Destroy()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.SetBackgroundColour(wx.Colour(74, 74, 80))

        root = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(root)

        # ── Left: Reference panel ─────────────────────────────────────────────
        left_panel = wx.Panel(self)
        left_panel.SetBackgroundColour(wx.Colour(74, 74, 80))
        left = wx.BoxSizer(wx.VERTICAL)
        left_panel.SetSizer(left)
        root.Add(left_panel, 1, wx.EXPAND | wx.ALL, 10)

        ref_hdr = wx.Panel(left_panel)
        ref_hdr.SetBackgroundColour(wx.Colour(90, 90, 96))
        ref_hdr_s = wx.BoxSizer(wx.VERTICAL)
        ref_hdr.SetSizer(ref_hdr_s)
        lbl = wx.StaticText(ref_hdr, label='Reference', style=wx.ALIGN_CENTER)
        f = lbl.GetFont()
        f.SetPointSize(16)
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        lbl.SetFont(f)
        lbl.SetForegroundColour(wx.Colour(255, 255, 255))
        ref_hdr_s.Add(lbl, 1, wx.EXPAND | wx.ALL, 8)
        left.Add(ref_hdr, 0, wx.EXPAND | wx.BOTTOM, 8)

        self.ref_view = _AsmGLCanvas(left_panel, bg_dark=True, orbit=True)
        self.ref_view.set_camera(dist=8.0, elev=20.0, azim=30.0, fov=60.0)
        left.Add(self.ref_view, 1, wx.EXPAND)

        # ── Right: Assembly panel ─────────────────────────────────────────────
        right_panel = wx.Panel(self)
        right_panel.SetBackgroundColour(wx.Colour(74, 74, 80))
        right = wx.BoxSizer(wx.VERTICAL)
        right_panel.SetSizer(right)
        root.Add(right_panel, 2, wx.EXPAND | wx.ALL, 10)

        asm_hdr = wx.Panel(right_panel)
        asm_hdr.SetBackgroundColour(wx.Colour(90, 90, 96))
        asm_hdr_s = wx.BoxSizer(wx.VERTICAL)
        asm_hdr.SetSizer(asm_hdr_s)
        lbl2 = wx.StaticText(
            asm_hdr, label='Assembly Area', style=wx.ALIGN_CENTER)
        f2 = lbl2.GetFont()
        f2.SetPointSize(16)
        f2.SetWeight(wx.FONTWEIGHT_BOLD)
        lbl2.SetFont(f2)
        lbl2.SetForegroundColour(wx.Colour(255, 255, 255))
        asm_hdr_s.Add(lbl2, 1, wx.EXPAND | wx.ALL, 8)
        right.Add(asm_hdr, 0, wx.EXPAND | wx.BOTTOM, 8)

        self.asm_view = _AsmGLCanvas(right_panel, bg_dark=False, orbit=False)
        self.asm_view.set_camera(dist=5.0, elev=20.0, azim=30.0, fov=50.0)
        right.Add(self.asm_view, 1, wx.EXPAND)

        # Feedback + action buttons
        ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        right.Add(ctrl_row, 0, wx.EXPAND | wx.TOP, 8)

        self.feedback_label = _StyledFeedback(right_panel, size=(420, 38))
        ctrl_row.Add(self.feedback_label, 0, wx.EXPAND | wx.RIGHT, 8)

        btn_reset = _StyledButton(right_panel, label='Reset')
        btn_reset.SetMinSize((80, 38))
        btn_reset.Bind(wx.EVT_BUTTON, lambda _e: self._reset_pieces())
        ctrl_row.Add(btn_reset, 0, wx.RIGHT, 6)

        btn_check = _StyledButton(right_panel, label='Check',
                                  bg=(74, 222, 128), fg=(45, 45, 48),
                                  border=(34, 197, 94),
                                  hover_bg=(34, 197, 94), hover_border=(22, 163, 74))
        btn_check.SetMinSize((80, 38))
        btn_check.Bind(wx.EVT_BUTTON, lambda _e: self._check_assembly())
        ctrl_row.Add(btn_check, 0, wx.RIGHT, 6)

        btn_quit = _StyledButton(right_panel, label='Quit',
                                 bg=(239, 68, 68), fg=(255, 255, 255),
                                 border=(220, 38, 38),
                                 hover_bg=(220, 38, 38), hover_border=(185, 28, 28))
        btn_quit.SetMinSize((80, 38))
        btn_quit.Bind(wx.EVT_BUTTON, lambda _e: self.EndModal(wx.ID_CANCEL))
        ctrl_row.Add(btn_quit, 0)

        # Piece buttons row
        self._piece_btn_panel = wx.Panel(right_panel)
        self._piece_btn_panel.SetBackgroundColour(wx.Colour(74, 74, 80))
        self._piece_btn_host = wx.BoxSizer(wx.HORIZONTAL)
        self._piece_btn_panel.SetSizer(self._piece_btn_host)
        right.Add(self._piece_btn_panel, 0, wx.EXPAND | wx.TOP, 8)
        self.piece_btns: List[_StyledButton] = []

        # Arrow pad
        arrow_host = wx.Panel(right_panel)
        arrow_host.SetBackgroundColour(wx.Colour(90, 90, 96))
        arrow_s = wx.BoxSizer(wx.HORIZONTAL)
        arrow_host.SetSizer(arrow_s)
        right.Add(arrow_host, 0, wx.EXPAND | wx.TOP, 8)

        arrow_inner = wx.Panel(arrow_host)
        arrow_inner.SetBackgroundColour(wx.Colour(90, 90, 96))
        arrow_inner_s = wx.BoxSizer(wx.VERTICAL)
        arrow_inner.SetSizer(arrow_inner_s)
        arrow_s.Add(arrow_inner, 1, wx.EXPAND | wx.ALL, 8)

        z_col = wx.Panel(arrow_host)
        z_col.SetBackgroundColour(wx.Colour(90, 90, 96))
        z_col_s = wx.BoxSizer(wx.VERTICAL)
        z_col.SetSizer(z_col_s)
        arrow_s.Add(z_col, 0, wx.EXPAND | wx.TOP | wx.BOTTOM | wx.RIGHT, 8)

        arrow_grid = wx.GridSizer(3, 3, 4, 4)
        arrow_inner_s.Add(arrow_grid, 1, wx.EXPAND)

        def _abtn(lbl: str, fn) -> None:
            if lbl.strip() == '':
                p = wx.Panel(arrow_inner)
                p.SetBackgroundColour(wx.Colour(90, 90, 96))
                arrow_grid.Add(p, 0, wx.EXPAND)
                return
            b = _StyledButton(arrow_inner, label=lbl, size=(40, 40),
                              pressed_bg=(255, 215, 0), pressed_fg=(45, 45, 48),
                              pressed_border=(255, 237, 78),
                              padding_x=0, padding_y=0)
            b.Bind(wx.EVT_BUTTON, lambda _e: fn())
            arrow_grid.Add(b, 0, wx.EXPAND)

        _abtn(' ', lambda: None)
        _abtn('↑', lambda: self._move_selected_piece(0, 1, 0))
        _abtn(' ', lambda: None)
        _abtn('←', lambda: self._move_selected_piece(-1, 0, 0))
        _abtn(' ', lambda: None)
        _abtn('→', lambda: self._move_selected_piece(1, 0, 0))
        _abtn(' ', lambda: None)
        _abtn('↓', lambda: self._move_selected_piece(0, -1, 0))
        _abtn(' ', lambda: None)

        _zbtn_kw = dict(size=(40, 40), bg=(255, 248, 220), fg=(45, 45, 48),
                        border=(255, 215, 0), hover_bg=(255, 237, 78),
                        hover_border=(255, 215, 0), font_point=11,
                        padding_x=0, padding_y=0)
        btn_zp = _StyledButton(z_col, label='Z+', **_zbtn_kw)
        btn_zp.Bind(wx.EVT_BUTTON,
                    lambda _e: self._move_selected_piece(0, 0, 1))
        z_col_s.Add(btn_zp, 0, wx.ALIGN_CENTER | wx.BOTTOM, 8)

        btn_zm = _StyledButton(z_col, label='Z-', **_zbtn_kw)
        btn_zm.Bind(wx.EVT_BUTTON,
                    lambda _e: self._move_selected_piece(0, 0, -1))
        z_col_s.Add(btn_zm, 0, wx.ALIGN_CENTER)

    # ── scene / GL ────────────────────────────────────────────────────────────

    def _build_scene_for_kind(self) -> None:
        self.pieces = _make_pieces(self.kind)
        self.target_structure = _make_target(self.kind)
        self.placed = [False] * len(self.pieces)
        self.selected_piece = None
        self._gl_built = False

        for i, p in enumerate(self.pieces):
            p['_idx'] = i

        self._ensure_piece_controls_match_scene()

    def _ensure_piece_controls_match_scene(self) -> None:
        for b in list(self.piece_btns):
            try:
                b.Destroy()
            except Exception:
                pass
        self.piece_btns = []

        parent = self._piece_btn_panel
        for i, piece in enumerate(self.pieces):
            lbl = f"{str(piece.get('type', 'cube')).capitalize()} {i + 1}"
            b = _StyledButton(parent, label=lbl, toggle=True)
            b.SetMinSize((130, 38))
            b.Bind(wx.EVT_TOGGLEBUTTON, lambda _e,
                   idx=i: self._select_piece(idx))
            self._piece_btn_host.Add(b, 0, wx.RIGHT, 6)
            self.piece_btns.append(b)
        try:
            self._piece_btn_panel.Layout()
        except Exception:
            pass
        self.Layout()

    def _build_gl(self) -> None:
        """Upload VAOs for current pieces + target + grid.  Called once after show."""
        if self._gl_built:
            return

        # Ensure both canvases have initialized their GL contexts
        self.ref_view._ensure()
        self.asm_view._ensure()

        # Upload piece VAOs for asm_view context
        self.asm_view.SetCurrent(self.asm_view._ctx)
        self._piece_vaos = []
        for p in self.pieces:
            col = p['color']
            raw = _cube(col) if p['type'] == 'cube' else _pyramid(col)
            self._piece_vaos.append(_upload(raw))

        # Upload target VAOs for asm_view context (not used but kept)
        self._ref_vaos = []
        for i, t in enumerate(self.target_structure):
            col = self.pieces[i]['color'] if i < len(
                self.pieces) else (0.7, 0.7, 0.7, 1.0)
            raw = _cube(col) if t['type'] == 'cube' else _pyramid(col)
            self._ref_vaos.append(_upload(raw))

        # Grid VAO for asm_view
        self._gvao, self._gvtx = _upload(_grid_verts())

        # Upload separate VAOs for ref_view context (VAOs cannot be shared!)
        self.ref_view.SetCurrent(self.ref_view._ctx)
        self._piece_vaos_ref = []
        for p in self.pieces:
            col = p['color']
            raw = _cube(col) if p['type'] == 'cube' else _pyramid(col)
            self._piece_vaos_ref.append(_upload(raw))

        self._ref_vaos_ref = []
        for i, t in enumerate(self.target_structure):
            col = self.pieces[i]['color'] if i < len(
                self.pieces) else (0.7, 0.7, 0.7, 1.0)
            raw = _cube(col) if t['type'] == 'cube' else _pyramid(col)
            self._ref_vaos_ref.append(_upload(raw))

        self._flash_vaos = []  # allocated on demand in _on_flash_timer

        self._gl_built = True
        self._update_views()

    def _asm_mats_from_pieces(self) -> List[List[float]]:
        return [_tmat(float(p['pos'][0]), float(p['pos'][1]), float(p['pos'][2]))
                for p in self.pieces]

    def _ref_mats_from_target(self) -> List[List[float]]:
        return [_tmat(float(t['pos'][0]), float(t['pos'][1]), float(t['pos'][2]))
                for t in self.target_structure]

    def _update_views(self) -> None:
        if not self._gl_built:
            return

        # Use separate VAOs for each canvas since VAOs cannot be shared between contexts
        self.ref_view.set_scene(
            self._ref_vaos_ref, self._ref_mats_from_target())
        self.asm_view.set_scene(self._piece_vaos, self._asm_mats_from_pieces(),
                                self._gvao, self._gvtx)

    # ── flash timer ──────────────────────────────────────────────────────────

    def _on_flash_timer(self, _evt: wx.TimerEvent) -> None:
        """Rebuild the selected piece's VAO with a flashing green colour."""
        if not self._gl_built:
            return
        idx = self.selected_piece
        if idx is None or idx < 0 or idx >= len(self.pieces):
            return
        if self.placed[idx]:
            return

        flash = (int(time.perf_counter() * 5.0) % 2) == 0
        p = self.pieces[idx]
        orig_col = p['color']
        col = (0.15, 0.95, 0.25, float(orig_col[3])) if flash else orig_col

        # Re-upload just this piece's VAO
        self.asm_view.SetCurrent(self.asm_view._ctx)
        raw = _cube(col) if p['type'] == 'cube' else _pyramid(col)
        old_vao, _ = self._piece_vaos[idx]
        # Delete old VAO to avoid leaking (best-effort)
        try:
            GL.glDeleteVertexArrays(1, [old_vao])
        except Exception:
            pass
        self._piece_vaos[idx] = _upload(raw)

        self.asm_view.set_scene(self._piece_vaos, self._asm_mats_from_pieces(),
                                self._gvao, self._gvtx)

    # ── piece interaction ─────────────────────────────────────────────────────

    def _select_piece(self, idx: int) -> None:
        # Restore original color for previously selected piece before changing selection
        if self.selected_piece is not None and self.selected_piece != idx and self._gl_built:
            prev_idx = self.selected_piece
            if 0 <= prev_idx < len(self.pieces) and not self.placed[prev_idx]:
                # Restore original color for previously selected piece
                self.asm_view.SetCurrent(self.asm_view._ctx)
                old_vao, _ = self._piece_vaos[prev_idx]
                try:
                    GL.glDeleteVertexArrays(1, [old_vao])
                except Exception:
                    pass
                p = self.pieces[prev_idx]
                raw = _cube(p['color']) if p['type'] == 'cube' else _pyramid(
                    p['color'])
                self._piece_vaos[prev_idx] = _upload(raw)

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
        if idx < 0 or idx >= len(self.pieces) or self.placed[idx]:
            return
        pos = self.pieces[idx]['pos']
        pos[0] = max(self.GRID_MIN, min(self.GRID_MAX, pos[0] + dx))
        pos[1] = max(self.GRID_MIN, min(self.GRID_MAX, pos[1] + dy))
        pos[2] = max(self.Z_MIN,    min(self.Z_MAX,    pos[2] + dz))
        self._update_views()
        self._update_feedback()

    def _reset_pieces(self) -> None:
        fresh = _make_pieces(self.kind)
        for i, p in enumerate(self.pieces):
            p['pos'] = list(fresh[i]['pos'])
        self.placed = [False] * len(self.pieces)
        self.selected_piece = None
        # Restore original colours (remove any flash tint)
        if self._gl_built:
            self.asm_view.SetCurrent(self.asm_view._ctx)
            for i, p in enumerate(self.pieces):
                old_vao, _ = self._piece_vaos[i]
                try:
                    GL.glDeleteVertexArrays(1, [old_vao])
                except Exception:
                    pass
                raw = _cube(p['color']) if p['type'] == 'cube' else _pyramid(
                    p['color'])
                self._piece_vaos[i] = _upload(raw)
        self._update_views()
        self._update_feedback()

    def _update_feedback(self) -> None:
        for i, b in enumerate(self.piece_btns):
            try:
                b.SetValue(self.selected_piece == i)
            except Exception:
                pass
        if all(self.placed) and self.pieces:
            self.feedback_label.set_text('Perfect Assembly!', mode='success')
        else:
            self.feedback_label.set_text(
                'Select piece → Use arrows to move → Z+/- for height', mode='normal')

    # ── check / congratulations ───────────────────────────────────────────────

    def _check_assembly(self) -> None:
        def adj(positions):
            a = {i: set() for i in range(len(positions))}
            ip = [[round(v) for v in pos] for pos in positions]
            for i in range(len(ip)):
                for j in range(i + 1, len(ip)):
                    diff = [abs(ip[i][k] - ip[j][k]) for k in range(3)]
                    if sum(1 for d in diff if d == 1) == 1 and sum(1 for d in diff if d == 0) == 2:
                        a[i].add(j)
                        a[j].add(i)
            return a

        type_ok = all(
            i < len(self.pieces) and self.pieces[i]['type'] == t['type']
            for i, t in enumerate(self.target_structure)
        )
        ta = adj([t['pos'] for t in self.target_structure])
        pa = adj([p['pos'] for p in self.pieces])
        adj_ok = all(pa.get(i, set()) == ta.get(i, set())
                     for i in range(len(self.target_structure)))

        if type_ok and adj_ok:
            self.feedback_label.set_text('Perfect Assembly!', mode='success')
            self._show_congratulations()
            self.EndModal(wx.ID_OK)
        else:
            self.feedback_label.set_text(
                '❌ Incorrect - Keep Trying!', mode='error')

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

        t2 = wx.StaticText(
            dlg, label='You have successfully assembled the structure!')
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

        ok = _StyledButton(dlg, label='OK')
        ok.Bind(wx.EVT_BUTTON, lambda _e: dlg.EndModal(wx.ID_OK))
        s.Add(ok, 0, wx.ALIGN_CENTER | wx.ALL, 16)

        dlg.Fit()
        dlg.CentreOnParent()
        dlg.ShowModal()
        dlg.Destroy()
