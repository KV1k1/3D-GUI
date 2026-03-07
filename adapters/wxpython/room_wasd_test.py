import math
import time
from dataclasses import dataclass

import wx
from wx import glcanvas

from OpenGL.GL import (
    GL_AMBIENT,
    GL_BLEND,
    GL_COLOR_BUFFER_BIT,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_TEST,
    GL_DIFFUSE,
    GL_LEQUAL,
    GL_LIGHT0,
    GL_LIGHTING,
    GL_MODELVIEW,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_POSITION,
    GL_PROJECTION,
    GL_QUADS,
    GL_SRC_ALPHA,
    glBegin,
    glBlendFunc,
    glClear,
    glClearColor,
    glDepthFunc,
    glDisable,
    glEnable,
    glEnd,
    glLightfv,
    glLoadIdentity,
    glMatrixMode,
    glPopMatrix,
    glPushMatrix,
    glRotatef,
    glScalef,
    glTranslatef,
    glVertex3f,
    glViewport,
    glColor4f,
)
from OpenGL.GLU import gluLookAt, gluPerspective


@dataclass
class Camera:
    x: float = 0.0
    y: float = 1.6
    z: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0


class RoomCanvas(glcanvas.GLCanvas):
    def __init__(self, parent: wx.Window):
        attribs = [
            glcanvas.WX_GL_RGBA,
            glcanvas.WX_GL_DOUBLEBUFFER,
            glcanvas.WX_GL_DEPTH_SIZE,
            24,
            0,
        ]
        super().__init__(parent, attribList=attribs)

        self._gl_context = glcanvas.GLContext(self)
        self._gl_initialized = False

        self._last_update_t = time.perf_counter()

        self.camera = Camera(x=0.0, y=1.6, z=2.0, yaw=math.pi, pitch=0.0)
        self._keys_down: set[int] = set()

        self._mouse_captured = False
        self._mouse_center: tuple[int, int] | None = None

        self._move_speed = 2.6
        self._mouse_sensitivity = 0.002

        self._timer = wx.Timer(self)

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)

        self.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.Bind(wx.EVT_KEY_UP, self._on_key_up)

        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOTION, self._on_mouse_move)

        self.SetFocus()
        self._timer.Start(16)

    def _ensure_gl(self) -> None:
        if self._gl_initialized:
            return

        self.SetCurrent(self._gl_context)

        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)

        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, [10.0, 12.0, 10.0, 1.0])
        glLightfv(GL_LIGHT0, GL_AMBIENT, [0.25, 0.25, 0.25, 1.0])
        glLightfv(GL_LIGHT0, GL_DIFFUSE, [0.85, 0.85, 0.85, 1.0])

        glClearColor(0.05, 0.05, 0.08, 1.0)

        self._gl_initialized = True

    def _on_size(self, _evt: wx.SizeEvent) -> None:
        self.Refresh(False)

    def _on_key_down(self, evt: wx.KeyEvent) -> None:
        self._keys_down.add(int(evt.GetKeyCode()))
        evt.Skip()

    def _on_key_up(self, evt: wx.KeyEvent) -> None:
        self._keys_down.discard(int(evt.GetKeyCode()))
        evt.Skip()

    def _on_left_down(self, evt: wx.MouseEvent) -> None:
        self.SetFocus()
        if not self.HasCapture():
            self.CaptureMouse()

        self._mouse_captured = True
        self.SetCursor(wx.Cursor(wx.CURSOR_BLANK))

        w, h = self.GetClientSize()
        cx, cy = int(w // 2), int(h // 2)
        self._mouse_center = (cx, cy)
        self.WarpPointer(cx, cy)
        evt.Skip()

    def _on_left_up(self, evt: wx.MouseEvent) -> None:
        if self.HasCapture():
            self.ReleaseMouse()
        self._mouse_captured = False
        self._mouse_center = None
        self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))
        evt.Skip()

    def _on_mouse_move(self, evt: wx.MouseEvent) -> None:
        if not self._mouse_captured:
            evt.Skip()
            return

        if not self._mouse_center:
            evt.Skip()
            return

        mx, my = evt.GetPosition()
        cx, cy = self._mouse_center
        dx = mx - cx
        dy = my - cy

        if abs(dx) > 1 or abs(dy) > 1:
            self._apply_mouse_look(float(dx), float(dy))
            self.WarpPointer(cx, cy)

        evt.Skip()

    def _apply_mouse_look(self, dx: float, dy: float) -> None:
        self.camera.yaw = (self.camera.yaw - dx * self._mouse_sensitivity) % (2 * math.pi)

        limit = (math.pi / 2) - 0.05
        self.camera.pitch = max(-limit, min(limit, self.camera.pitch - dy * self._mouse_sensitivity))

    def _on_timer(self, _evt: wx.TimerEvent) -> None:
        now = time.perf_counter()
        dt = now - self._last_update_t
        self._last_update_t = now
        dt = min(dt, 0.1)

        self._update_movement(dt)
        self.Refresh(False)

    def _update_movement(self, dt: float) -> None:
        dx = 0.0
        dz = 0.0

        if ord('W') in self._keys_down:
            dz += 1.0
        if ord('S') in self._keys_down:
            dz -= 1.0
        if ord('A') in self._keys_down:
            dx -= 1.0
        if ord('D') in self._keys_down:
            dx += 1.0

        if dx == 0.0 and dz == 0.0:
            return

        length = math.sqrt(dx * dx + dz * dz)
        if length > 0:
            dx /= length
            dz /= length

        speed = self._move_speed * dt

        forward_x = math.sin(self.camera.yaw)
        forward_z = math.cos(self.camera.yaw)
        right_x = -math.cos(self.camera.yaw)
        right_z = math.sin(self.camera.yaw)

        world_dx = dx * right_x + dz * forward_x
        world_dz = dx * right_z + dz * forward_z

        nx = self.camera.x + world_dx * speed
        nz = self.camera.z + world_dz * speed

        room_half = 4.5
        margin = 0.25
        nx = max(-room_half + margin, min(room_half - margin, nx))
        nz = max(-room_half + margin, min(room_half - margin, nz))

        self.camera.x = nx
        self.camera.z = nz

    def _on_paint(self, _evt: wx.PaintEvent) -> None:
        dc = wx.PaintDC(self)
        _ = dc

        self._ensure_gl()
        self.SetCurrent(self._gl_context)

        w, h = self.GetClientSize()
        w = max(1, int(w))
        h = max(1, int(h))

        glViewport(0, 0, w, h)

        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(60.0, float(w) / float(h), 0.1, 80.0)

        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

        fx = math.sin(self.camera.yaw) * math.cos(self.camera.pitch)
        fy = math.sin(self.camera.pitch)
        fz = math.cos(self.camera.yaw) * math.cos(self.camera.pitch)

        gluLookAt(
            self.camera.x,
            self.camera.y,
            self.camera.z,
            self.camera.x + fx,
            self.camera.y + fy,
            self.camera.z + fz,
            0.0,
            1.0,
            0.0,
        )

        self._draw_room()

        self.SwapBuffers()

    def _draw_room(self) -> None:
        size = 5.0
        height = 3.0

        wall = (0.45, 0.45, 0.50, 1.0)
        floor = (0.25, 0.23, 0.22, 1.0)
        ceil = (0.18, 0.18, 0.20, 1.0)

        glDisable(GL_LIGHTING)
        glColor4f(*floor)
        glBegin(GL_QUADS)
        glVertex3f(-size, 0.0, -size)
        glVertex3f(size, 0.0, -size)
        glVertex3f(size, 0.0, size)
        glVertex3f(-size, 0.0, size)
        glEnd()

        glColor4f(*ceil)
        glBegin(GL_QUADS)
        glVertex3f(-size, height, size)
        glVertex3f(size, height, size)
        glVertex3f(size, height, -size)
        glVertex3f(-size, height, -size)
        glEnd()

        glColor4f(*wall)

        glBegin(GL_QUADS)
        glVertex3f(-size, 0.0, -size)
        glVertex3f(size, 0.0, -size)
        glVertex3f(size, height, -size)
        glVertex3f(-size, height, -size)
        glEnd()

        glBegin(GL_QUADS)
        glVertex3f(size, 0.0, -size)
        glVertex3f(size, 0.0, size)
        glVertex3f(size, height, size)
        glVertex3f(size, height, -size)
        glEnd()

        glBegin(GL_QUADS)
        glVertex3f(size, 0.0, size)
        glVertex3f(-size, 0.0, size)
        glVertex3f(-size, height, size)
        glVertex3f(size, height, size)
        glEnd()

        glBegin(GL_QUADS)
        glVertex3f(-size, 0.0, size)
        glVertex3f(-size, 0.0, -size)
        glVertex3f(-size, height, -size)
        glVertex3f(-size, height, size)
        glEnd()

        glEnable(GL_LIGHTING)

        glPushMatrix()
        glTranslatef(0.0, 1.0, 0.0)
        glScalef(0.35, 0.35, 0.35)
        glRotatef(30.0, 1.0, 0.0, 0.0)
        glRotatef(45.0, 0.0, 1.0, 0.0)
        glDisable(GL_LIGHTING)
        self._draw_unit_cube((0.8, 0.75, 0.2, 1.0))
        glEnable(GL_LIGHTING)
        glPopMatrix()

    def _draw_unit_cube(self, color: tuple[float, float, float, float]) -> None:
        glColor4f(*color)
        glBegin(GL_QUADS)

        glVertex3f(-1.0, -1.0, 1.0)
        glVertex3f(1.0, -1.0, 1.0)
        glVertex3f(1.0, 1.0, 1.0)
        glVertex3f(-1.0, 1.0, 1.0)

        glVertex3f(1.0, -1.0, -1.0)
        glVertex3f(-1.0, -1.0, -1.0)
        glVertex3f(-1.0, 1.0, -1.0)
        glVertex3f(1.0, 1.0, -1.0)

        glVertex3f(-1.0, -1.0, -1.0)
        glVertex3f(-1.0, -1.0, 1.0)
        glVertex3f(-1.0, 1.0, 1.0)
        glVertex3f(-1.0, 1.0, -1.0)

        glVertex3f(1.0, -1.0, 1.0)
        glVertex3f(1.0, -1.0, -1.0)
        glVertex3f(1.0, 1.0, -1.0)
        glVertex3f(1.0, 1.0, 1.0)

        glVertex3f(-1.0, 1.0, 1.0)
        glVertex3f(1.0, 1.0, 1.0)
        glVertex3f(1.0, 1.0, -1.0)
        glVertex3f(-1.0, 1.0, -1.0)

        glVertex3f(-1.0, -1.0, -1.0)
        glVertex3f(1.0, -1.0, -1.0)
        glVertex3f(1.0, -1.0, 1.0)
        glVertex3f(-1.0, -1.0, 1.0)

        glEnd()


class RoomTestFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title='WxPython OpenGL Room Test', size=(1100, 700))

        self.canvas = RoomCanvas(self)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.canvas, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _on_close(self, evt: wx.CloseEvent) -> None:
        try:
            if self.canvas.HasCapture():
                self.canvas.ReleaseMouse()
        except Exception:
            pass
        evt.Skip()


def run() -> int:
    app = wx.App(False)
    frame = RoomTestFrame()
    frame.Show(True)
    return int(app.MainLoop() or 0)
