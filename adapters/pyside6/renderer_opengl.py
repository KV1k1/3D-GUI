import ctypes
import math
import os
import time
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter
from OpenGL.GL import *
from OpenGL.GLU import gluLookAt, gluPerspective

from core.game_core import GameCore


class OpenGLRenderer:
    def __init__(self, core: GameCore):
        self.core = core
        self.width = 800
        self.height = 600
        self.camera_height = 1.6
        self.fov = 60.0
        self.near_plane = 0.15
        self.far_plane = 42.0

        self._anim_clock_s = 0.0
        self._last_anim_elapsed_s: Optional[float] = None

        self._fog_enabled = True
        self._fog_start = 22.0
        self._fog_end = 40.0

        self._fast_mode = True

        self.sky_color = (0.05, 0.05, 0.08, 1.0)

        self._tex_wall: Optional[int] = None
        self._tex_floor: Optional[int] = None
        self._tex_coin: Optional[int] = None

        self._static_quads: List[Tuple[float, float, Optional[int],
                                       Tuple[Tuple[float, float, float, float, float], ...]]] = []

        self._world_vbo_floor: Optional[int] = None
        self._world_vbo_wall: Optional[int] = None
        self._world_floor_vertex_count: int = 0
        self._world_wall_vertex_count: int = 0

        self._chunk_size = 12
        self._chunk_vbos: dict[tuple[int, int],
                               tuple[Optional[int], int, Optional[int], int]] = {}

        self._ghost_body_vbo: Optional[int] = None
        self._ghost_body_vertex_count: int = 0
        self._ghost_eye_vbo: Optional[int] = None
        self._ghost_eye_vertex_count: int = 0
        self._ghost_tail_vbos: list[Optional[int]] = []
        self._ghost_tail_vertex_counts: list[int] = []
        self._ghost_tail_pose_count: int = 0

        self._anim_t = 0.0

        self._text_texture_cache: dict[str, int] = {}
        self._jail_map_texture: Optional[int] = None

    # ------------------------------------------------------------------ setup

    def initialize(self) -> None:
        """Initialize OpenGL resources and load textures."""
        start_time = time.perf_counter()

        # Always reset animation state so a reused renderer doesn't carry over
        # elapsed time from a previous level, which would cause entities to
        # snap to the wrong animation phase on the first frame.
        self._anim_clock_s = 0.0
        self._last_anim_elapsed_s = None
        self._anim_t = 0.0

        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glClearDepth(1.0)
        glDisable(GL_CULL_FACE)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glLightfv(GL_LIGHT0, 0x1203, [10.0, 12.0, 10.0, 1.0])

        if self._fog_enabled:
            glEnable(GL_FOG)
            glFogi(GL_FOG_MODE, GL_LINEAR)
            glFogf(GL_FOG_START, float(self._fog_start))
            glFogf(GL_FOG_END, float(self._fog_end))
            glFogfv(GL_FOG_COLOR, [*self.sky_color[:3], 1.0])
        else:
            glDisable(GL_FOG)

        glEnable(GL_TEXTURE_2D)
        self._tex_wall = self._load_texture(
            os.path.join('assets', 'image.png'))
        self._tex_floor = self._load_texture(
            os.path.join('assets', 'path.png'))
        self._tex_coin = self._load_texture(
            os.path.join('assets', 'JEMA GER 1640-11.png'))

        if self._tex_coin is not None:
            glBindTexture(GL_TEXTURE_2D, self._tex_coin)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            glBindTexture(GL_TEXTURE_2D, 0)

        self._build_static_geometry()
        self._build_world_vbos()
        self._build_ghost_vbo()

        # Capture texture load time for PDF report
        load_time = time.perf_counter() - start_time
        try:
            from core.pdf_export import get_system_collector
            collector = get_system_collector()
            collector.record_texture_load_time(load_time)
            try:
                vendor = glGetString(GL_VENDOR).decode('utf-8')
                renderer = glGetString(GL_RENDERER).decode('utf-8')
                version = glGetString(GL_VERSION).decode('utf-8')
                collector.record_opengl_info(
                    vendor=vendor, renderer=renderer, version=version)
            except Exception:
                pass
        except ImportError:
            pass

    def resize(self, width: int, height: int) -> None:
        self.width = max(1, width)
        self.height = max(1, height)
        glViewport(0, 0, self.width, self.height)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(self.fov, self.width / self.height,
                       self.near_plane, self.far_plane)

        if self._fog_enabled:
            glFogf(GL_FOG_START, float(self._fog_start))
            glFogf(GL_FOG_END, float(self._fog_end))
            glFogfv(GL_FOG_COLOR, [*self.sky_color[:3], 1.0])

    # ------------------------------------------------------------------ VBO management

    def _safe_delete_buffer(self, vbo: Optional[int]) -> None:
        if vbo is not None:
            try:
                glDeleteBuffers(1, [int(vbo)])
            except Exception:
                pass

    def _delete_world_vbos(self) -> None:
        self._safe_delete_buffer(self._world_vbo_floor)
        self._safe_delete_buffer(self._world_vbo_wall)
        self._world_vbo_floor = None
        self._world_vbo_wall = None
        self._world_floor_vertex_count = 0
        self._world_wall_vertex_count = 0

        self._safe_delete_buffer(self._ghost_body_vbo)
        self._safe_delete_buffer(self._ghost_eye_vbo)
        for vbo in self._ghost_tail_vbos:
            self._safe_delete_buffer(vbo)

        self._ghost_body_vbo = None
        self._ghost_body_vertex_count = 0
        self._ghost_eye_vbo = None
        self._ghost_eye_vertex_count = 0
        self._ghost_tail_vbos = []
        self._ghost_tail_vertex_counts = []
        self._ghost_tail_pose_count = 0

        for floor_vbo, _, wall_vbo, _ in self._chunk_vbos.values():
            self._safe_delete_buffer(floor_vbo)
            self._safe_delete_buffer(wall_vbo)
        self._chunk_vbos.clear()

    def _upload_vbo(self, data_bytes: bytes) -> Optional[int]:
        """Create and upload a GL buffer. Returns the VBO id, or None on failure."""
        try:
            vbo = glGenBuffers(1)
            vid = int(vbo) if vbo else None
            if vid:
                glBindBuffer(GL_ARRAY_BUFFER, vid)
                glBufferData(GL_ARRAY_BUFFER, data_bytes, GL_STATIC_DRAW)
                glBindBuffer(GL_ARRAY_BUFFER, 0)
            return vid
        except Exception:
            return None

    def _build_world_vbos(self) -> None:
        from array import array

        self._delete_world_vbos()

        floor_data: array = array('f')
        wall_data: array = array('f')
        chunk_floor: dict[tuple[int, int], array] = {}
        chunk_wall: dict[tuple[int, int], array] = {}

        # Vertex layout per vertex: x, y, z, u, v
        for cr, cc, tex_id, quad in self._static_quads:
            if tex_id not in (self._tex_floor, self._tex_wall):
                continue

            is_floor_tex = tex_id == self._tex_floor
            target = floor_data if is_floor_tex else wall_data

            ch_key = (int(cr) // self._chunk_size, int(cc) // self._chunk_size)
            chunk_dict = chunk_floor if is_floor_tex else chunk_wall
            ch_target = chunk_dict.setdefault(ch_key, array('f'))

            for (u, v, x, y, z) in quad:
                vals = [float(x), float(y), float(z), float(u), float(v)]
                target.extend(vals)
                ch_target.extend(vals)

        self._world_floor_vertex_count = len(floor_data) // 5
        self._world_wall_vertex_count = len(wall_data) // 5

        try:
            if self._world_floor_vertex_count > 0:
                self._world_vbo_floor = self._upload_vbo(floor_data.tobytes())
            if self._world_wall_vertex_count > 0:
                self._world_vbo_wall = self._upload_vbo(wall_data.tobytes())

            for ch_key in sorted(set(chunk_floor) | set(chunk_wall)):
                fd = chunk_floor.get(ch_key)
                wd = chunk_wall.get(ch_key)
                floor_count = len(fd) // 5 if fd else 0
                wall_count = len(wd) // 5 if wd else 0
                floor_vbo = self._upload_vbo(
                    fd.tobytes()) if floor_count > 0 else None
                wall_vbo = self._upload_vbo(
                    wd.tobytes()) if wall_count > 0 else None
                self._chunk_vbos[ch_key] = (
                    floor_vbo, floor_count, wall_vbo, wall_count)
        except Exception:
            self._delete_world_vbos()

    def _build_ghost_vbo(self) -> None:
        from array import array

        # Clean up any existing ghost VBOs before rebuilding
        self._safe_delete_buffer(self._ghost_body_vbo)
        self._safe_delete_buffer(self._ghost_eye_vbo)
        for vbo in self._ghost_tail_vbos:
            self._safe_delete_buffer(vbo)

        self._ghost_body_vbo = None
        self._ghost_body_vertex_count = 0
        self._ghost_eye_vbo = None
        self._ghost_eye_vertex_count = 0
        self._ghost_tail_vbos = []
        self._ghost_tail_vertex_counts = []
        self._ghost_tail_pose_count = 0

        segments = 26 if self._fast_mode else 40
        body_layers = 11
        radius = 0.20

        def y_and_r(t: float) -> tuple[float, float]:
            if t < 0.5:
                return radius * 0.62 * math.cos(t * math.pi), radius * 0.95 * math.sin(t * math.pi)
            return -radius * 0.25 * (t - 0.5) * 2.0, radius * 0.95

        def add_strip(data: array, y0: float, r0: float, y1: float, r1: float) -> None:
            for i in range(segments + 1):
                a = (i / segments) * (2.0 * math.pi)
                ca, sa = math.cos(a), math.sin(a)
                data.extend([ca * r0, y0, sa * r0, ca, 0.0, sa])
                data.extend([ca * r1, y1, sa * r1, ca, 0.0, sa])

        # Body
        body: array = array('f')
        for layer in range(1, body_layers):
            y_prev, r_prev = y_and_r((layer - 1) / (body_layers - 1))
            y_curr, r_curr = y_and_r(layer / (body_layers - 1))
            add_strip(body, y_prev, r_prev, y_curr, r_curr)
        self._ghost_body_vertex_count = len(body) // 6

        # Eyes (two quads as triangles)
        eye: array = array('f')
        eye_y = radius * 0.22
        eye_z = radius * 1.05
        eye_x = radius * 0.34
        ew = radius * 0.22
        eh = radius * 0.28

        def add_eye_quad(cx: float) -> None:
            x0, x1 = cx - ew, cx + ew
            y0, y1 = eye_y - eh, eye_y + eh
            for verts in [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]:
                eye.extend([verts[0], verts[1], eye_z, 0.0, 0.0, 1.0])

        add_eye_quad(-eye_x)
        add_eye_quad(eye_x)
        self._ghost_eye_vertex_count = len(eye) // 6

        # Tail rendered in immediate mode for smooth animation
        self._ghost_tail_vbos = []
        self._ghost_tail_vertex_counts = []
        self._ghost_tail_pose_count = 0

        # Upload body + eye VBOs
        if self._ghost_body_vertex_count > 0:
            self._ghost_body_vbo = self._upload_vbo(body.tobytes())
        if self._ghost_eye_vertex_count > 0:
            self._ghost_eye_vbo = self._upload_vbo(eye.tobytes())

    # ------------------------------------------------------------------ render

    def render(self) -> None:
        glEnable(GL_DEPTH_TEST)

        frozen = bool(getattr(self.core, 'simulation_frozen', False))

        # Drive animations from wall-clock time
        now = time.perf_counter()
        if self._last_anim_elapsed_s is None:
            self._last_anim_elapsed_s = now
        else:
            dt_anim = max(0.0, min(0.1, now - self._last_anim_elapsed_s))
            self._last_anim_elapsed_s = now
            if not frozen:
                self._anim_clock_s += dt_anim

        self._anim_t = self._anim_clock_s

        glClearColor(*self.sky_color)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

        px, py, pz = self.core.player.x, self.core.player.y + \
            self.camera_height, self.core.player.z
        yaw, pitch = self.core.player.yaw, self.core.player.pitch

        lx = px + math.sin(yaw) * math.cos(pitch)
        ly = py + math.sin(pitch)
        lz = pz + math.cos(yaw) * math.cos(pitch)

        # Dynamic up-vector for camera stability
        fx = lx - px
        fy = ly - py
        fz = lz - pz
        f_len = math.sqrt(fx * fx + fy * fy + fz * fz)
        if f_len > 0.0:
            fy /= f_len

        upx, upy, upz = (1.0, 0.0, 0.0) if abs(fy) > 0.97 else (0.0, 1.0, 0.0)
        gluLookAt(px, py, pz, lx, ly, lz, upx, upy, upz)

        glDisable(GL_BLEND)
        glDepthMask(True)
        self._draw_world()
        glEnable(GL_BLEND)
        self._draw_entities()

    # ------------------------------------------------------------------ world geometry

    def _build_static_geometry(self) -> None:
        self._static_quads.clear()
        wall_h = float(self.core.wall_height)
        ceil_h = float(self.core.ceiling_height)
        h = int(getattr(self.core, 'height', 0))
        w = int(getattr(self.core, 'width', 0))
        walls = self.core.walls

        def add_quad(cr, cc, tex, vtx):
            self._static_quads.append((cr, cc, tex, vtx))

        def is_solid(rr: int, cc: int) -> bool:
            if rr < 0 or cc < 0 or rr >= h or cc >= w:
                return False
            return (rr, cc) in walls

        def is_inside(rr: int, cc: int) -> bool:
            return 0 <= rr < h and 0 <= cc < w

        for (r, c) in self.core.floors:
            cx, cz = c + 0.5, r + 0.5
            add_quad(cz, cx, self._tex_floor, (
                (0.0, 0.0, cx - 0.5, 0.0, cz - 0.5), (1.0,
                                                      0.0, cx + 0.5, 0.0, cz - 0.5),
                (1.0, 1.0, cx + 0.5, 0.0, cz + 0.5), (0.0,
                                                      1.0, cx - 0.5, 0.0, cz + 0.5),
            ))
            add_quad(cz, cx, self._tex_floor, (
                (0.0, 0.0, cx - 0.5, ceil_h, cz + 0.5), (1.0,
                                                         0.0, cx + 0.5, ceil_h, cz + 0.5),
                (1.0, 1.0, cx + 0.5, ceil_h, cz - 0.5), (0.0,
                                                         1.0, cx - 0.5, ceil_h, cz - 0.5),
            ))
            if not is_inside(r - 1, c):
                add_quad(cz, cx, self._tex_wall, (
                    (0.0, 0.0, cx - 0.5, 0.0, cz - 0.5), (1.0,
                                                          0.0, cx + 0.5, 0.0, cz - 0.5),
                    (1.0, 1.0, cx + 0.5, wall_h, cz - 0.5), (0.0,
                                                             1.0, cx - 0.5, wall_h, cz - 0.5),
                ))
            if not is_inside(r + 1, c):
                add_quad(cz, cx, self._tex_wall, (
                    (0.0, 0.0, cx + 0.5, 0.0, cz + 0.5), (1.0,
                                                          0.0, cx - 0.5, 0.0, cz + 0.5),
                    (1.0, 1.0, cx - 0.5, wall_h, cz + 0.5), (0.0,
                                                             1.0, cx + 0.5, wall_h, cz + 0.5),
                ))
            if not is_inside(r, c - 1):
                add_quad(cz, cx, self._tex_wall, (
                    (0.0, 0.0, cx - 0.5, 0.0, cz + 0.5), (1.0,
                                                          0.0, cx - 0.5, 0.0, cz - 0.5),
                    (1.0, 1.0, cx - 0.5, wall_h, cz - 0.5), (0.0,
                                                             1.0, cx - 0.5, wall_h, cz + 0.5),
                ))
            if not is_inside(r, c + 1):
                add_quad(cz, cx, self._tex_wall, (
                    (0.0, 0.0, cx + 0.5, 0.0, cz - 0.5), (1.0,
                                                          0.0, cx + 0.5, 0.0, cz + 0.5),
                    (1.0, 1.0, cx + 0.5, wall_h, cz + 0.5), (0.0,
                                                             1.0, cx + 0.5, wall_h, cz - 0.5),
                ))

        for (r, c) in walls:
            cx, cz = c + 0.5, r + 0.5
            y0, y1 = 0.0, wall_h
            if not is_solid(r - 1, c):
                add_quad(cz, cx, self._tex_wall, (
                    (0.0, 0.0, cx - 0.5, y0, cz - 0.5), (1.0,
                                                         0.0, cx + 0.5, y0, cz - 0.5),
                    (1.0, 1.0, cx + 0.5, y1, cz - 0.5), (0.0,
                                                         1.0, cx - 0.5, y1, cz - 0.5),
                ))
            if not is_solid(r + 1, c):
                add_quad(cz, cx, self._tex_wall, (
                    (0.0, 0.0, cx + 0.5, y0, cz + 0.5), (1.0,
                                                         0.0, cx - 0.5, y0, cz + 0.5),
                    (1.0, 1.0, cx - 0.5, y1, cz + 0.5), (0.0,
                                                         1.0, cx + 0.5, y1, cz + 0.5),
                ))
            if not is_solid(r, c - 1):
                add_quad(cz, cx, self._tex_wall, (
                    (0.0, 0.0, cx - 0.5, y0, cz + 0.5), (1.0,
                                                         0.0, cx - 0.5, y0, cz - 0.5),
                    (1.0, 1.0, cx - 0.5, y1, cz - 0.5), (0.0,
                                                         1.0, cx - 0.5, y1, cz + 0.5),
                ))
            if not is_solid(r, c + 1):
                add_quad(cz, cx, self._tex_wall, (
                    (0.0, 0.0, cx + 0.5, y0, cz - 0.5), (1.0,
                                                         0.0, cx + 0.5, y0, cz + 0.5),
                    (1.0, 1.0, cx + 0.5, y1, cz + 0.5), (0.0,
                                                         1.0, cx + 0.5, y1, cz - 0.5),
                ))
            if y1 < ceil_h and (not is_solid(r - 1, c) or not is_solid(r + 1, c)
                                or not is_solid(r, c - 1) or not is_solid(r, c + 1)):
                add_quad(cz, cx, self._tex_wall, (
                    (0.0, 0.0, cx - 0.5, y1, cz + 0.5), (1.0,
                                                         0.0, cx + 0.5, y1, cz + 0.5),
                    (1.0, 1.0, cx + 0.5, y1, cz - 0.5), (0.0,
                                                         1.0, cx - 0.5, y1, cz - 0.5),
                ))

    def _draw_world_immediate(self) -> None:
        """Fallback immediate-mode draw when VBOs are unavailable."""
        pr = self.core.player.z
        pc = self.core.player.x
        view_r2 = 25.0 ** 2

        bound_tex: Optional[int] = None
        texture_enabled = False

        for cr, cc, tex_id, quad in self._static_quads:
            dx, dz = cc - pc, cr - pr
            if dx * dx + dz * dz > view_r2:
                continue

            if tex_id != bound_tex:
                if tex_id is None:
                    if texture_enabled:
                        glDisable(GL_TEXTURE_2D)
                        texture_enabled = False
                    glBindTexture(GL_TEXTURE_2D, 0)
                    glColor4f(0.75, 0.75, 0.80, 1.0)
                else:
                    if not texture_enabled:
                        glEnable(GL_TEXTURE_2D)
                        texture_enabled = True
                    glBindTexture(GL_TEXTURE_2D, tex_id)
                    glColor4f(1.0, 1.0, 1.0, 1.0)
                bound_tex = tex_id

            glBegin(GL_QUADS)
            for (u, v, x, y, z) in quad:
                if texture_enabled:
                    glTexCoord2f(u, v)
                glVertex3f(x, y, z)
            glEnd()

        glBindTexture(GL_TEXTURE_2D, 0)
        if texture_enabled:
            glDisable(GL_TEXTURE_2D)
        glEnable(GL_LIGHTING)

    def _draw_world(self) -> None:
        if self._world_vbo_floor is None or self._world_vbo_wall is None:
            self._draw_world_immediate()
            return

        glDisable(GL_LIGHTING)
        glColor4f(1.0, 1.0, 1.0, 1.0)

        try:
            glEnableClientState(GL_VERTEX_ARRAY)
            glEnableClientState(GL_TEXTURE_COORD_ARRAY)
            stride = 5 * 4
            glEnable(GL_TEXTURE_2D)

            px, pz = float(self.core.player.x), float(self.core.player.z)
            ch_r0 = int(pz // self._chunk_size)
            ch_c0 = int(px // self._chunk_size)
            chunk_radius = max(
                2, int(math.ceil(self._fog_end / self._chunk_size)) + 1)

            for dr in range(-chunk_radius, chunk_radius + 1):
                for dc in range(-chunk_radius, chunk_radius + 1):
                    entry = self._chunk_vbos.get((ch_r0 + dr, ch_c0 + dc))
                    if not entry:
                        continue

                    floor_vbo, floor_count, wall_vbo, wall_count = entry

                    if floor_vbo is not None and floor_count > 0:
                        glBindTexture(GL_TEXTURE_2D, self._tex_floor or 0)
                        glBindBuffer(GL_ARRAY_BUFFER, floor_vbo)
                        glVertexPointer(3, GL_FLOAT, stride,
                                        ctypes.c_void_p(0))
                        glTexCoordPointer(2, GL_FLOAT, stride,
                                          ctypes.c_void_p(12))
                        glDrawArrays(GL_QUADS, 0, floor_count)

                    if wall_vbo is not None and wall_count > 0:
                        glBindTexture(GL_TEXTURE_2D, self._tex_wall or 0)
                        glBindBuffer(GL_ARRAY_BUFFER, wall_vbo)
                        glVertexPointer(3, GL_FLOAT, stride,
                                        ctypes.c_void_p(0))
                        glTexCoordPointer(2, GL_FLOAT, stride,
                                          ctypes.c_void_p(12))
                        glDrawArrays(GL_QUADS, 0, wall_count)

            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glBindTexture(GL_TEXTURE_2D, 0)
            glDisable(GL_TEXTURE_2D)
        except Exception:
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            try:
                glDisableClientState(GL_TEXTURE_COORD_ARRAY)
                glDisableClientState(GL_VERTEX_ARRAY)
            except Exception:
                pass
            glEnable(GL_LIGHTING)
            self._draw_world_immediate()
            return

        glDisableClientState(GL_TEXTURE_COORD_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)
        glEnable(GL_LIGHTING)

    # ------------------------------------------------------------------ entity rendering

    def _draw_ghost_vbo(self, color: Tuple[float, float, float, float]) -> None:
        """Draw ghost: body+eyes via VBO (static), tail via immediate mode (smooth continuous animation)."""
        if self._ghost_body_vbo is None or self._ghost_body_vertex_count <= 0:
            return

        stride = 6 * 4

        # --- Body (static VBO) ---
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_NORMAL_ARRAY)
        glColor4f(*color)
        glBindBuffer(GL_ARRAY_BUFFER, self._ghost_body_vbo)
        glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
        glNormalPointer(GL_FLOAT, stride, ctypes.c_void_p(12))
        glDrawArrays(GL_TRIANGLE_STRIP, 0, self._ghost_body_vertex_count)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glDisableClientState(GL_NORMAL_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)

        # --- Tail (immediate mode — continuous sin() for smooth animation, no pose snapping) ---
        radius = 0.20
        segments = 26 if self._fast_mode else 40
        tail_layers = 8
        TWO_PI = math.pi * 2.0
        t = self._anim_t
        glColor4f(*color)
        for layer in range(tail_layers):
            layer_ratio = layer / tail_layers
            prev_ratio = (layer - 1) / tail_layers
            base_r = radius * 0.95 * (1.0 - layer_ratio * 0.35)
            wave_amp = radius * (0.08 + 0.14 * layer_ratio)
            y_curr = -radius * 0.52 - layer_ratio * radius * 0.48
            glBegin(GL_TRIANGLE_STRIP)
            if layer == 0:
                for i in range(segments + 1):
                    a = (i / segments) * TWO_PI
                    ca, sa = math.cos(a), math.sin(a)
                    skirt = (math.sin(a * 3.0 + t * 2.4 + layer * 0.55) * wave_amp
                             + math.sin(a * 7.0 - t * 1.7 + layer * 0.35) * (wave_amp * 0.55))
                    r_curr = max(radius * 0.02, base_r + skirt)
                    glVertex3f(ca * radius * 0.95, -radius *
                               0.25, sa * radius * 0.95)
                    glVertex3f(ca * r_curr, y_curr, sa * r_curr)
            else:
                prev_base_r = radius * 0.95 * (1.0 - prev_ratio * 0.35)
                prev_amp = radius * (0.08 + 0.14 * prev_ratio)
                y_prev = -radius * 0.52 - prev_ratio * radius * 0.48
                for i in range(segments + 1):
                    a = (i / segments) * TWO_PI
                    ca, sa = math.cos(a), math.sin(a)
                    skirt_p = (math.sin(a * 3.0 + t * 2.4 + (layer - 1) * 0.55) * prev_amp
                               + math.sin(a * 7.0 - t * 1.7 + (layer - 1) * 0.35) * (prev_amp * 0.55))
                    skirt_c = (math.sin(a * 3.0 + t * 2.4 + layer * 0.55) * wave_amp
                               + math.sin(a * 7.0 - t * 1.7 + layer * 0.35) * (wave_amp * 0.55))
                    r_prev = max(radius * 0.02, prev_base_r + skirt_p)
                    r_curr = max(radius * 0.02, base_r + skirt_c)
                    glVertex3f(ca * r_prev, y_prev, sa * r_prev)
                    glVertex3f(ca * r_curr, y_curr, sa * r_curr)
            glEnd()

        # --- Eyes (static VBO) ---
        if self._ghost_eye_vbo is not None and self._ghost_eye_vertex_count > 0:
            glEnableClientState(GL_VERTEX_ARRAY)
            glEnableClientState(GL_NORMAL_ARRAY)
            glColor4f(0.06, 0.06, 0.08, 0.96)
            glBindBuffer(GL_ARRAY_BUFFER, self._ghost_eye_vbo)
            glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
            glNormalPointer(GL_FLOAT, stride, ctypes.c_void_p(12))
            glDrawArrays(GL_TRIANGLES, 0, self._ghost_eye_vertex_count)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glDisableClientState(GL_NORMAL_ARRAY)
            glDisableClientState(GL_VERTEX_ARRAY)

    def _draw_entities(self) -> None:
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)

        cam_yaw = self.core.player.yaw
        right_x = math.cos(cam_yaw)
        right_z = -math.sin(cam_yaw)

        TWO_PI = math.pi * 2.0

        def billboard_quad(cx, cy, cz, w, h, color):
            glColor4f(*color)
            hx = (w / 2.0) * right_x
            hz = (w / 2.0) * right_z
            hy = h / 2.0
            glBegin(GL_QUADS)
            glVertex3f(cx - hx, cy - hy, cz - hz)
            glVertex3f(cx + hx, cy - hy, cz + hz)
            glVertex3f(cx + hx, cy + hy, cz + hz)
            glVertex3f(cx - hx, cy + hy, cz - hz)
            glEnd()

        def soft_aura(cx, cy, cz, base_size, color, alpha):
            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
            glDepthMask(False)
            for s, a in zip(
                (base_size * 0.9, base_size * 1.25, base_size * 1.65),
                (alpha * 0.55, alpha * 0.28, alpha * 0.14),
            ):
                billboard_quad(cx, cy, cz, s, s,
                               (color[0], color[1], color[2], a))
            glDepthMask(True)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        def radial_sprite_glow(cx, cy, cz, radius, color, alpha):
            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
            glDepthMask(False)
            glBegin(GL_TRIANGLE_FAN)
            glColor4f(*color, alpha)
            glVertex3f(cx, cy, cz)
            glColor4f(*color, 0.0)
            for i in range(29):
                a = (i / 28) * TWO_PI
                x = math.cos(a) * radius
                y = math.sin(a) * radius
                glVertex3f(cx + x * right_x, cy + y, cz + x * right_z)
            glEnd()
            glDepthMask(True)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        def floor_glow(cx, cz, y, radius, color, alpha):
            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
            glDepthMask(False)
            glBegin(GL_TRIANGLE_FAN)
            glColor4f(*color, alpha)
            glVertex3f(cx, y, cz)
            glColor4f(*color, 0.0)
            for i in range(23):
                a = (i / 22) * TWO_PI
                glVertex3f(cx + math.cos(a) * radius,
                           y, cz + math.sin(a) * radius)
            glEnd()
            glDepthMask(True)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        def draw_coin_3d(radius=0.13, thickness=0.045, segments=18, textured=False):
            y0, y1 = -thickness / 2.0, thickness / 2.0

            glBegin(GL_QUADS)
            for i in range(segments):
                a0 = (i / segments) * TWO_PI
                a1 = ((i + 1) / segments) * TWO_PI
                x0, z0 = math.cos(a0) * radius, math.sin(a0) * radius
                x1, z1 = math.cos(a1) * radius, math.sin(a1) * radius
                glColor4f(1.0, 0.84, 0.18, 0.98) if i % 2 == 0 else glColor4f(
                    240/255, 168/255, 48/255, 0.98)
                glVertex3f(x0, y0, z0)
                glVertex3f(x1, y0, z1)
                glVertex3f(x1, y1, z1)
                glVertex3f(x0, y1, z0)
            glEnd()

            def disc_fan(y_offset):
                glBegin(GL_TRIANGLE_FAN)
                glVertex3f(0.0, y_offset, 0.0)
                for i in range(segments + 1):
                    a = (i / segments) * TWO_PI
                    glVertex3f(math.cos(a) * radius,
                               y_offset, math.sin(a) * radius)
                glEnd()

            def tex_fan(y_offset, inner_r):
                glBegin(GL_TRIANGLE_FAN)
                glTexCoord2f(0.5, 0.5)
                glVertex3f(0.0, y_offset, 0.0)
                for i in range(segments + 1):
                    a = (i / segments) * TWO_PI
                    glTexCoord2f(0.5 + 0.48 * math.cos(a),
                                 0.5 + 0.48 * math.sin(a))
                    glVertex3f(math.cos(a) * inner_r,
                               y_offset, math.sin(a) * inner_r)
                glEnd()

            if textured and self._tex_coin:
                inner_r = radius * 0.92
                glColor4f(1.0, 0.84, 0.18, 0.98)
                disc_fan(y1)
                disc_fan(y0)
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, self._tex_coin)
                glColor4f(1.0, 1.0, 1.0, 0.98)
                tex_fan(y1 + 0.001, inner_r)
                tex_fan(y0 - 0.001, inner_r)
                glBindTexture(GL_TEXTURE_2D, 0)
                glDisable(GL_TEXTURE_2D)
            else:
                glColor4f(1.0, 0.84, 0.18, 0.98)
                disc_fan(y1)
                disc_fan(y0)

        def draw_ghost_3d(color):
            radius = 0.20
            segments = 26 if self._fast_mode else 40
            body_layers = 11
            tail_layers = 8

            glColor4f(*color)

            def y_and_r(t):
                if t < 0.5:
                    return radius * 0.62 * math.cos(t * math.pi), radius * 0.95 * math.sin(t * math.pi)
                return -radius * 0.25 * (t - 0.5) * 2.0, radius * 0.95

            for layer in range(1, body_layers):
                y_prev, r_prev = y_and_r((layer - 1) / (body_layers - 1))
                y_curr, r_curr = y_and_r(layer / (body_layers - 1))
                glBegin(GL_TRIANGLE_STRIP)
                for i in range(segments + 1):
                    a = (i / segments) * TWO_PI
                    ca, sa = math.cos(a), math.sin(a)
                    glVertex3f(ca * r_prev, y_prev, sa * r_prev)
                    glVertex3f(ca * r_curr, y_curr, sa * r_curr)
                glEnd()

            for layer in range(tail_layers):
                layer_ratio = layer / tail_layers
                prev_ratio = (layer - 1) / tail_layers
                base_r = radius * 0.95 * (1.0 - layer_ratio * 0.35)
                wave_amp = radius * (0.08 + 0.14 * layer_ratio)
                y_curr = -radius * 0.52 - layer_ratio * radius * 0.48

                glBegin(GL_TRIANGLE_STRIP)
                if layer == 0:
                    for i in range(segments + 1):
                        a = (i / segments) * TWO_PI
                        ca, sa = math.cos(a), math.sin(a)
                        skirt = (math.sin(a * 3.0 + self._anim_t * 2.4 + layer * 0.55) * wave_amp
                                 + math.sin(a * 7.0 - self._anim_t * 1.7 + layer * 0.35) * (wave_amp * 0.55))
                        r_curr = max(radius * 0.02, base_r + skirt)
                        glVertex3f(ca * radius * 0.95, -radius *
                                   0.25, sa * radius * 0.95)
                        glVertex3f(ca * r_curr, y_curr, sa * r_curr)
                else:
                    prev_base_r = radius * 0.95 * (1.0 - prev_ratio * 0.35)
                    prev_amp = radius * (0.08 + 0.14 * prev_ratio)
                    y_prev = -radius * 0.52 - prev_ratio * radius * 0.48
                    for i in range(segments + 1):
                        a = (i / segments) * TWO_PI
                        ca, sa = math.cos(a), math.sin(a)
                        skirt_prev = (math.sin(a * 3.0 + self._anim_t * 2.4 + (layer - 1) * 0.55) * prev_amp
                                      + math.sin(a * 7.0 - self._anim_t * 1.7 + (layer - 1) * 0.35) * (prev_amp * 0.55))
                        skirt_curr = (math.sin(a * 3.0 + self._anim_t * 2.4 + layer * 0.55) * wave_amp
                                      + math.sin(a * 7.0 - self._anim_t * 1.7 + layer * 0.35) * (wave_amp * 0.55))
                        r_prev2 = max(radius * 0.02, prev_base_r + skirt_prev)
                        r_curr2 = max(radius * 0.02, base_r + skirt_curr)
                        glVertex3f(ca * r_prev2, y_prev, sa * r_prev2)
                        glVertex3f(ca * r_curr2, y_curr, sa * r_curr2)
                glEnd()

            glColor4f(0.06, 0.06, 0.08, 0.96)
            eye_y, eye_z = radius * 0.22, radius * 1.05
            eye_x, ew, eh = radius * 0.34, radius * 0.22, radius * 0.28
            glBegin(GL_QUADS)
            for ex in (-eye_x, eye_x):
                glVertex3f(ex - ew, eye_y - eh, eye_z)
                glVertex3f(ex + ew, eye_y - eh, eye_z)
                glVertex3f(ex + ew, eye_y + eh, eye_z)
                glVertex3f(ex - ew, eye_y + eh, eye_z)
            glEnd()

        def draw_key_3d():
            glPushMatrix()
            glTranslatef(0.23, 0.06, 0.0)
            outer_r, inner_r, thickness, seg = 0.16, 0.11, 0.035, 24
            glBegin(GL_QUADS)
            for i in range(seg):
                a0, a1 = TWO_PI * (i / seg), TWO_PI * ((i + 1) / seg)
                c0, s0, c1, s1 = math.cos(a0), math.sin(
                    a0), math.cos(a1), math.sin(a1)
                glVertex3f(outer_r*c0, -thickness, outer_r*s0)
                glVertex3f(outer_r*c1, -thickness, outer_r*s1)
                glVertex3f(outer_r*c1, +thickness, outer_r*s1)
                glVertex3f(outer_r*c0, +thickness, outer_r*s0)
                glVertex3f(inner_r*c1, -thickness, inner_r*s1)
                glVertex3f(inner_r*c0, -thickness, inner_r*s0)
                glVertex3f(inner_r*c0, +thickness, inner_r*s0)
                glVertex3f(inner_r*c1, +thickness, inner_r*s1)
                glVertex3f(inner_r*c0, +thickness, inner_r*s0)
                glVertex3f(inner_r*c1, +thickness, inner_r*s1)
                glVertex3f(outer_r*c1, +thickness, outer_r*s1)
                glVertex3f(outer_r*c0, +thickness, outer_r*s0)
                glVertex3f(outer_r*c0, -thickness, outer_r*s0)
                glVertex3f(outer_r*c1, -thickness, outer_r*s1)
                glVertex3f(inner_r*c1, -thickness, inner_r*s1)
                glVertex3f(inner_r*c0, -thickness, inner_r*s0)
            glEnd()
            glPopMatrix()
            glPushMatrix()
            glTranslatef(-0.12, 0.06, 0.0)
            glScalef(0.52, 0.06, 0.08)
            self._draw_untextured_cube()
            glPopMatrix()
            for tx, th in ((-0.34, 0.12), (-0.25, 0.09), (-0.18, 0.07)):
                glPushMatrix()
                glTranslatef(tx, 0.02, 0.0)
                glScalef(0.06, th, 0.08)
                self._draw_untextured_cube()
                glPopMatrix()

        def wall_quad(cx, cy, cz, w, h, facing):
            if facing == 'N':
                z = cz - 0.49
                glVertex3f(cx - w, cy + h, z)
                glVertex3f(cx + w, cy + h, z)
                glVertex3f(cx + w, cy - h, z)
                glVertex3f(cx - w, cy - h, z)
            elif facing == 'S':
                z = cz + 0.49
                glVertex3f(cx + w, cy + h, z)
                glVertex3f(cx - w, cy + h, z)
                glVertex3f(cx - w, cy - h, z)
                glVertex3f(cx + w, cy - h, z)
            elif facing == 'W':
                x = cx - 0.49
                glVertex3f(x, cy + h, cz + w)
                glVertex3f(x, cy + h, cz - w)
                glVertex3f(x, cy - h, cz - w)
                glVertex3f(x, cy - h, cz + w)
            else:
                x = cx + 0.49
                glVertex3f(x, cy + h, cz - w)
                glVertex3f(x, cy + h, cz + w)
                glVertex3f(x, cy - h, cz + w)
                glVertex3f(x, cy - h, cz - w)

        px = float(self.core.player.x)
        pz = float(self.core.player.z)
        entity_r2 = max(18.0, self._fog_end - 2.0) ** 2
        glow_r2 = max(12.0, (self._fog_end - 2.0) * 0.70) ** 2

        # Coins
        for coin in self.core.coins.values():
            if coin.taken:
                continue
            r, c = coin.cell
            cx, cz = c + 0.5, r + 0.5
            dx, dz = float(cx) - px, float(cz) - pz
            d2 = dx * dx + dz * dz
            if d2 > entity_r2:
                continue
            spin_deg = ((self._anim_t * 3.0) % TWO_PI) * (180.0 / math.pi)
            bob = 0.06 * math.sin(self._anim_t * 1.6 + r * 0.37 + c * 0.51)
            glPushMatrix()
            glTranslatef(cx, 1.22 + bob, cz)
            glRotatef(spin_deg, 0.0, 1.0, 0.0)
            glRotatef(90.0, 1.0, 0.0, 0.0)
            glDisable(GL_LIGHTING)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glColor4f(1.0, 0.84, 0.18, 0.98)
            draw_coin_3d(radius=0.14, thickness=0.04, segments=(
                24 if d2 <= glow_r2 else 16), textured=True)
            glPopMatrix()
            if d2 <= glow_r2:
                pulse = 0.16 + 0.06 * \
                    math.sin(self._anim_t * 2.2 + r * 0.17 + c * 0.23)
                radial_sprite_glow(cx, 1.22 + bob, cz, 0.34,
                                   (1.0, 0.90, 0.35), pulse)

        # Sector signs
        sector_signs = getattr(self.core, 'sector_signs', None) or {}
        if sector_signs:
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            for sid, (cell, facing) in sector_signs.items():
                r, c = cell
                cx, cz, cy = c + 0.5, r + 0.5, 1.65
                glColor4f(0.10, 0.10, 0.12, 0.92)
                glBegin(GL_QUADS)
                wall_quad(cx, cy, cz, 0.48, 0.18, facing)
                glEnd()

                label = f"SECTOR {str(sid)[:1]}"
                tex = self._get_text_texture(label)
                if tex:
                    glEnable(GL_TEXTURE_2D)
                    glBindTexture(GL_TEXTURE_2D, tex)
                    glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
                    glColor4f(1.0, 1.0, 1.0, 0.98)
                    tw, th = 0.42, 0.11
                    glBegin(GL_QUADS)
                    if facing == 'N':
                        z = cz - 0.481
                        glTexCoord2f(0.0, 1.0)
                        glVertex3f(cx - tw, cy + th, z)
                        glTexCoord2f(1.0, 1.0)
                        glVertex3f(cx + tw, cy + th, z)
                        glTexCoord2f(1.0, 0.0)
                        glVertex3f(cx + tw, cy - th, z)
                        glTexCoord2f(0.0, 0.0)
                        glVertex3f(cx - tw, cy - th, z)
                    elif facing == 'S':
                        z = cz + 0.481
                        glTexCoord2f(0.0, 1.0)
                        glVertex3f(cx + tw, cy + th, z)
                        glTexCoord2f(1.0, 1.0)
                        glVertex3f(cx - tw, cy + th, z)
                        glTexCoord2f(1.0, 0.0)
                        glVertex3f(cx - tw, cy - th, z)
                        glTexCoord2f(0.0, 0.0)
                        glVertex3f(cx + tw, cy - th, z)
                    elif facing == 'W':
                        x = cx - 0.481
                        glTexCoord2f(0.0, 1.0)
                        glVertex3f(x, cy + th, cz + tw)
                        glTexCoord2f(1.0, 1.0)
                        glVertex3f(x, cy + th, cz - tw)
                        glTexCoord2f(1.0, 0.0)
                        glVertex3f(x, cy - th, cz - tw)
                        glTexCoord2f(0.0, 0.0)
                        glVertex3f(x, cy - th, cz + tw)
                    else:
                        x = cx + 0.481
                        glTexCoord2f(0.0, 1.0)
                        glVertex3f(x, cy + th, cz - tw)
                        glTexCoord2f(1.0, 1.0)
                        glVertex3f(x, cy + th, cz + tw)
                        glTexCoord2f(1.0, 0.0)
                        glVertex3f(x, cy - th, cz + tw)
                        glTexCoord2f(0.0, 0.0)
                        glVertex3f(x, cy - th, cz - tw)
                    glEnd()
                    glBindTexture(GL_TEXTURE_2D, 0)

        # Jail painting
        painting = getattr(self.core, 'jail_painting', None)
        if painting:
            (pr_cell, pc_cell), facing = painting
            cx, cz, cy = pc_cell + 0.5, pr_cell + 0.5, 1.55

            dr, dc = {'N': (-1, 0), 'S': (1, 0), 'W': (0, -1)
                      }.get(facing, (0, 1))
            wr, wc = pr_cell + dr, pc_cell + dc
            if (wr, wc) in getattr(self.core, 'walls', set()):
                neg, pos = 0, 0
                if facing in ('N', 'S'):
                    cc2 = wc - 1
                    while (wr, cc2) in self.core.walls:
                        neg += 1
                        cc2 -= 1
                    cc2 = wc + 1
                    while (wr, cc2) in self.core.walls:
                        pos += 1
                        cc2 += 1
                    cx += max(-0.28, min(0.28, (pos - neg) * 0.12))
                else:
                    rr2 = wr - 1
                    while (rr2, wc) in self.core.walls:
                        neg += 1
                        rr2 -= 1
                    rr2 = wr + 1
                    while (rr2, wc) in self.core.walls:
                        pos += 1
                        rr2 += 1
                    cz += max(-0.28, min(0.28, (pos - neg) * 0.12))

            glColor4f(0.30, 0.20, 0.10, 1.0)
            glBegin(GL_QUADS)
            wall_quad(cx, cy, cz, 0.78, 0.50, facing)
            glEnd()
            glColor4f(0.08, 0.08, 0.10, 0.98)
            glBegin(GL_QUADS)
            wall_quad(cx, cy, cz, 0.72, 0.44, facing)
            glEnd()

            tex = self._get_jail_map_texture()
            if tex:
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, tex)
                glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
                glColor4f(1.0, 1.0, 1.0, 0.98)
                tw, th = 0.70, 0.41
                glBegin(GL_QUADS)
                if facing == 'N':
                    z = cz - 0.473
                    glTexCoord2f(0.0, 1.0)
                    glVertex3f(cx - tw, cy + th, z)
                    glTexCoord2f(1.0, 1.0)
                    glVertex3f(cx + tw, cy + th, z)
                    glTexCoord2f(1.0, 0.0)
                    glVertex3f(cx + tw, cy - th, z)
                    glTexCoord2f(0.0, 0.0)
                    glVertex3f(cx - tw, cy - th, z)
                elif facing == 'S':
                    z = cz + 0.473
                    glTexCoord2f(0.0, 1.0)
                    glVertex3f(cx + tw, cy + th, z)
                    glTexCoord2f(1.0, 1.0)
                    glVertex3f(cx - tw, cy + th, z)
                    glTexCoord2f(1.0, 0.0)
                    glVertex3f(cx - tw, cy - th, z)
                    glTexCoord2f(0.0, 0.0)
                    glVertex3f(cx + tw, cy - th, z)
                elif facing == 'W':
                    x = cx - 0.473
                    glTexCoord2f(0.0, 1.0)
                    glVertex3f(x, cy + th, cz + tw)
                    glTexCoord2f(1.0, 1.0)
                    glVertex3f(x, cy + th, cz - tw)
                    glTexCoord2f(1.0, 0.0)
                    glVertex3f(x, cy - th, cz - tw)
                    glTexCoord2f(0.0, 0.0)
                    glVertex3f(x, cy - th, cz + tw)
                else:
                    x = cx + 0.473
                    glTexCoord2f(0.0, 1.0)
                    glVertex3f(x, cy + th, cz - tw)
                    glTexCoord2f(1.0, 1.0)
                    glVertex3f(x, cy + th, cz + tw)
                    glTexCoord2f(1.0, 0.0)
                    glVertex3f(x, cy - th, cz + tw)
                    glTexCoord2f(0.0, 0.0)
                    glVertex3f(x, cy - th, cz - tw)
                glEnd()
                glBindTexture(GL_TEXTURE_2D, 0)

        # Key fragments
        for frag in self.core.key_fragments.values():
            if frag.taken:
                continue
            r, c = frag.cell
            cx, cz = c + 0.5, r + 0.5
            dx, dz = float(cx) - px, float(cz) - pz
            d2 = dx * dx + dz * dz
            if d2 > entity_r2:
                continue
            kind = getattr(frag, 'kind', '')
            if kind == 'KH':
                base, glow_rgb = (0.55, 0.95, 1.0, 0.95), (0.65, 1.0, 1.0)
            elif kind == 'KP':
                base, glow_rgb = (0.9, 0.65, 1.0, 0.95), (0.95, 0.75, 1.0)
            else:
                base, glow_rgb = (0.75, 1.0, 0.65, 0.95), (0.85, 1.0, 0.75)
            base_y = (float(self.core.ceiling_height) -
                      0.85) if kind == 'KP' else 1.18
            seed = float(sum((i + 1) * ord(ch)
                         for i, ch in enumerate(str(getattr(frag, 'id', '')))) % 997)
            bob = 0.08 * math.sin(self._anim_t * 2.4 + seed)
            spin = (self._anim_t * 140.0 + seed * 37.0) % 360.0
            glPushMatrix()
            glTranslatef(cx, base_y + bob, cz)
            glRotatef(spin, 0.0, 1.0, 0.0)
            glRotatef(90.0, 0.0, 0.0, 1.0)
            glScalef(1.05, 1.05, 1.05)
            glDisable(GL_LIGHTING)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glColor4f(*base)
            draw_key_3d()
            if d2 <= glow_r2:
                soft_aura(cx, base_y + bob + 0.05, cz, 0.55, glow_rgb, 0.12)
            glPopMatrix()

        # Checkpoint arrow
        arrow = getattr(self.core, 'checkpoint_arrow', None)
        if arrow and arrow.visible:
            ar, ac = arrow.cell
            cx = float(ac) + 0.5
            cz = float(ar) + 0.5

            bounce = 0.08 * math.sin(self._anim_t * 2.5)
            cy = float(getattr(self.core, 'wall_height', 3.0)) * 0.45 + bounce

            glDisable(GL_TEXTURE_2D)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

            pulse = 0.75 + 0.25 * math.sin(self._anim_t * 3.0)

            glDisable(GL_DEPTH_TEST)
            glDisable(GL_LIGHTING)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
            glDepthMask(False)

            yaw = float(getattr(self.core.player, 'yaw', 0.0) or 0.0)
            rx = math.cos(yaw)
            rz = -math.sin(yaw)

            glow_radius = 1.5
            glow_alpha = 0.25 * pulse
            glColor4f(0.15, 1.0, 0.4, glow_alpha)
            glBegin(GL_TRIANGLE_FAN)
            glVertex3f(cx, cy, cz)
            glColor4f(0.15, 1.0, 0.4, 0.0)
            steps = 48
            for i in range(steps + 1):
                a = (i / steps) * 2.0 * math.pi
                x = math.cos(a) * glow_radius
                y = math.sin(a) * glow_radius
                glVertex3f(cx + x * rx, cy + y, cz + x * rz)
            glEnd()

            glDepthMask(True)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

            # Solid 3D arrow — use glPushAttrib to save/restore ALL lighting+material state.
            # This prevents green emission from leaking into ceiling lamps drawn below.
            glDisable(GL_DEPTH_TEST)
            glPushAttrib(GL_LIGHTING_BIT | GL_COLOR_BUFFER_BIT)

            glEnable(GL_LIGHTING)
            glEnable(GL_LIGHT0)
            glMaterialfv(GL_FRONT_AND_BACK, GL_AMBIENT,
                         [0.0, 0.65, 0.20, 1.0])
            glMaterialfv(GL_FRONT_AND_BACK, GL_DIFFUSE,
                         [0.0, 0.98, 0.35, 1.0])
            glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR,
                         [0.6, 1.0,  0.7,  1.0])
            glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION,
                         [0.0, 0.45, 0.15, 1.0])
            glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 64.0)

            glPushMatrix()
            glTranslatef(cx, cy, cz)

            shaft_r = 0.12
            shaft_h = 0.60
            head_r = 0.30
            head_h = 0.42
            seg = 32
            shaft_top = shaft_h * 0.5
            shaft_bot = -shaft_h * 0.5
            tip_y = shaft_bot - head_h

            glBegin(GL_TRIANGLE_STRIP)
            for i in range(seg + 1):
                a = (i / seg) * 2.0 * math.pi
                ca, sa = math.cos(a), math.sin(a)
                glNormal3f(ca, 0.0, sa)
                glVertex3f(ca * shaft_r, shaft_top, sa * shaft_r)
                glVertex3f(ca * shaft_r, shaft_bot, sa * shaft_r)
            glEnd()

            glBegin(GL_TRIANGLE_FAN)
            glNormal3f(0.0, 1.0, 0.0)
            glVertex3f(0.0, shaft_top, 0.0)
            for i in range(seg + 1):
                a = (i / seg) * 2.0 * math.pi
                glVertex3f(math.cos(a) * shaft_r,
                           shaft_top, math.sin(a) * shaft_r)
            glEnd()

            glBegin(GL_TRIANGLE_FAN)
            glNormal3f(0.0, 1.0, 0.0)
            glVertex3f(0.0, shaft_bot, 0.0)
            for i in range(seg + 1):
                a = (i / seg) * 2.0 * math.pi
                glVertex3f(math.cos(a) * head_r,
                           shaft_bot, math.sin(a) * head_r)
            glEnd()

            slant = math.atan2(head_r, head_h)
            ny = math.sin(slant)
            nr = math.cos(slant)
            glBegin(GL_TRIANGLE_FAN)
            glNormal3f(0.0, -1.0, 0.0)
            glVertex3f(0.0, tip_y, 0.0)
            for i in range(seg + 1):
                a = (i / seg) * 2.0 * math.pi
                ca, sa = math.cos(a), math.sin(a)
                glNormal3f(ca * nr, ny, sa * nr)
                glVertex3f(ca * head_r, shaft_bot, sa * head_r)
            glEnd()

            glPopMatrix()

            # Restore ALL lighting+material state saved by glPushAttrib — no manual resets needed.
            glPopAttrib()

            glEnable(GL_DEPTH_TEST)
            glEnable(GL_TEXTURE_2D)
            # Ensure we're back to the expected state for subsequent draws
            glDisable(GL_LIGHTING)

        # Spikes
        spikes = getattr(self.core, 'spikes', None)
        if spikes:
            h_factor = float(self.core.spike_height_factor()) if hasattr(
                self.core, 'spike_height_factor') else 0.0
            for s in spikes:
                r, c = s.cell
                glPushMatrix()
                glTranslatef(c + 0.5, 0.0, r + 0.5)
                glColor4f(0.85, 0.15, 0.15, 1.0) if s.active else glColor4f(
                    0.45, 0.12, 0.12, 1.0)
                self._draw_spike(height=0.85 * h_factor)
                glPopMatrix()

        # Gates
        for gate in self.core.gates.values():
            self._draw_gate(gate)

        # Moving platforms
        for platform in getattr(self.core, 'platforms', []):
            self._draw_platform(platform)

        # Jail table + book
        if getattr(self.core, 'jail_book_cell', None):
            jr, jc = self.core.jail_book_cell
            glPushMatrix()
            glTranslatef(jc + 0.5, 0.0, jr + 0.5)
            glColor4f(0.35, 0.22, 0.10, 1.0)
            glPushMatrix()
            glTranslatef(0.0, 0.40, 0.0)
            glScalef(0.85, 0.08, 0.60)
            self._draw_untextured_cube()
            glPopMatrix()
            for lx in (-0.35, 0.35):
                for lz in (-0.22, 0.22):
                    glPushMatrix()
                    glTranslatef(lx, 0.20, lz)
                    glScalef(0.08, 0.40, 0.08)
                    self._draw_untextured_cube()
                    glPopMatrix()
            glColor4f(0.12, 0.12, 0.14, 1.0)
            glPushMatrix()
            glTranslatef(0.0, 0.48, 0.0)
            glScalef(0.28, 0.04, 0.20)
            self._draw_untextured_cube()
            glPopMatrix()
            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
            glDepthMask(False)
            radial_sprite_glow(0.0, 0.70, 0.0, 0.55, (0.95, 0.85, 0.35), 0.16)
            radial_sprite_glow(0.0, 0.70, 0.0, 0.95, (0.95, 0.85, 0.35), 0.06)
            glDepthMask(True)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glPopMatrix()

        # Ghosts
        ghost_colors = {
            1: (1.0, 0.35, 0.20, 0.82), 2: (0.30, 1.0, 0.55, 0.82),
            3: (0.45, 0.65, 1.0, 0.82), 4: (1.0, 0.85, 0.25, 0.82),
            5: (0.95, 0.35, 1.0, 0.82),
        }
        for g in self.core.ghosts.values():
            dx = float(getattr(g, 'x', 0.0) or 0.0) - px
            dz = float(getattr(g, 'z', 0.0) or 0.0) - pz
            if dx * dx + dz * dz > entity_r2:
                continue
            bob = 0.05 * math.sin(self._anim_t * 2.0 + g.id)
            wobble = 0.06 * math.sin(self._anim_t * 4.6 + g.id * 0.7)
            s = float(getattr(g, 'size_scale', 1.0) or 1.0)
            y_raise = 0.18 + 0.22 * max(0.0, s - 1.0)
            glPushMatrix()
            glTranslatef(g.x, 1.15 + y_raise + bob + wobble, g.z)
            glRotatef(math.degrees(g.yaw), 0.0, 1.0, 0.0)
            glScalef(2.10 * s, 2.75 * s, 2.10 * s)
            glDepthMask(False)
            col = ghost_colors.get(g.id, (1.0, 0.55, 0.15, 0.92))
            if self._ghost_body_vbo is not None:
                self._draw_ghost_vbo(col)
            else:
                draw_ghost_3d(col)
            glDepthMask(True)
            glPopMatrix()
            col = ghost_colors.get(g.id, (1.0, 0.55, 0.15, 0.92))
            radial_sprite_glow(g.x, 1.15 + y_raise + bob +
                               0.08, g.z, 0.55 * s, col[:3], 0.12)
            radial_sprite_glow(g.x, 1.15 + y_raise + bob +
                               0.08, g.z, 0.95 * s, col[:3], 0.05)

        # Ceiling lamps
        ceil_h = float(self.core.ceiling_height)

        def is_floor_tile(rr, cc):
            return (rr, cc) in self.core.floors and (rr, cc) not in self.core.walls

        lamp_candidates = []
        for (r, c) in self.core.floors:
            if (r, c) in self.core.walls:
                continue
            if is_floor_tile(r, c - 1) and is_floor_tile(r, c + 1) and not is_floor_tile(r, c - 2) and not is_floor_tile(r, c + 2):
                lamp_candidates.append((r, c))
                continue
            if is_floor_tile(r - 1, c) and is_floor_tile(r + 1, c) and not is_floor_tile(r - 2, c) and not is_floor_tile(r + 2, c):
                lamp_candidates.append((r, c))

        lamp_candidates.sort()
        lamps = []
        min_sep2 = 8.0 ** 2
        for rc in lamp_candidates:
            if all(((rc[0] - lr) ** 2 + (rc[1] - lc) ** 2) >= min_sep2 for lr, lc in lamps):
                lamps.append(rc)
            if len(lamps) >= 140:
                break

        for r, c in lamps:
            cx, cz = c + 0.5, r + 0.5
            glPushMatrix()
            glTranslatef(cx, ceil_h - 0.15, cz)
            glColor4f(0.10, 0.10, 0.12, 1.0)
            glPushMatrix()
            glTranslatef(0.0, 0.18, 0.0)
            glScalef(0.03, 0.36, 0.03)
            self._draw_untextured_cube()
            glPopMatrix()
            glColor4f(0.18, 0.18, 0.22, 1.0)
            glPushMatrix()
            glTranslatef(0.0, 0.02, 0.0)
            glScalef(0.26, 0.10, 0.26)
            self._draw_untextured_cube()
            glPopMatrix()
            glColor4f(0.98, 0.95, 0.82, 1.0)
            glPushMatrix()
            glTranslatef(0.0, -0.02, 0.0)
            glScalef(0.10, 0.07, 0.10)
            self._draw_untextured_cube()
            glPopMatrix()
            glPopMatrix()
            floor_glow(cx, cz, 0.015, 1.75, (0.98, 0.95, 0.82), 0.20)
            floor_glow(cx, cz, 0.016, 0.85, (0.98, 0.95, 0.82), 0.22)
            soft_aura(cx, ceil_h - 0.45, cz, 1.10, (0.98, 0.95, 0.82), 0.08)

        glEnable(GL_TEXTURE_2D)
        glEnable(GL_LIGHTING)

    # ------------------------------------------------------------------ prop drawing

    def _draw_gate(self, gate) -> None:
        wall_h = float(self.core.wall_height)
        for (r, c) in gate.cells:
            glPushMatrix()
            glTranslatef(c + 0.5, wall_h / 2.0 + gate.y_offset, r + 0.5)
            glScalef(1.0, wall_h, 1.0)
            glColor4f(0.7, 0.7, 0.75, 1.0)
            self._draw_gate_bars(gate.id)
            glPopMatrix()

    def _draw_gate_bars(self, gate_id: str) -> None:
        is_jail = gate_id == 'jail'
        for i in range(-2, 3):
            glPushMatrix()
            if is_jail:
                glTranslatef(i * 0.18, 0.0, 0.0)
            else:
                glTranslatef(0.0, 0.0, i * 0.18)
                glRotatef(90, 0.0, 1.0, 0.0)
            glScalef(0.07, 1.0, 0.12)
            self._draw_untextured_cube()
            glPopMatrix()
        glPushMatrix()
        glTranslatef(0.0, 0.42, 0.0)
        glColor4f(0.65, 0.65, 0.7, 1.0)
        if not is_jail:
            glRotatef(90, 0.0, 1.0, 0.0)
        glScalef(0.95, 0.12, 0.16)
        self._draw_untextured_cube()
        glPopMatrix()

    def _draw_platform(self, platform) -> None:
        r, c = platform.cell
        glPushMatrix()
        glTranslatef(c + 0.5, platform.y_offset + 0.05, r + 0.5)
        glColor4f(0.6, 0.4, 0.2, 1.0)
        glPushMatrix()
        glScalef(0.8, 0.1, 0.8)
        self._draw_untextured_cube()
        glPopMatrix()
        glColor4f(0.4, 0.3, 0.15, 1.0)
        for tx, ty, tz, sx, sy, sz in [
            (0.0, 0.15,  0.35, 0.82, 0.2, 0.05),
            (0.0, 0.15, -0.35, 0.82, 0.2, 0.05),
            (-0.35, 0.15, 0.0, 0.05, 0.2, 0.82),
            (0.35, 0.15, 0.0, 0.05, 0.2, 0.82),
        ]:
            glPushMatrix()
            glTranslatef(tx, ty, tz)
            glScalef(sx, sy, sz)
            self._draw_untextured_cube()
            glPopMatrix()
        glPopMatrix()

    def _draw_spike(self, height: float) -> None:
        if height <= 0.02:
            return
        base = 0.18
        glBegin(GL_QUADS)
        glVertex3f(-base, 0.01, -base)
        glVertex3f(base, 0.01, -base)
        glVertex3f(base, 0.01, base)
        glVertex3f(-base, 0.01, base)
        glEnd()
        glBegin(GL_TRIANGLES)
        glVertex3f(-base, 0.01, -base)
        glVertex3f(base, 0.01, -base)
        glVertex3f(0.0, height, 0.0)
        glVertex3f(base, 0.01, -base)
        glVertex3f(base, 0.01, base)
        glVertex3f(0.0, height, 0.0)
        glVertex3f(base, 0.01, base)
        glVertex3f(-base, 0.01, base)
        glVertex3f(0.0, height, 0.0)
        glVertex3f(-base, 0.01, base)
        glVertex3f(-base, 0.01, -base)
        glVertex3f(0.0, height, 0.0)
        glEnd()

    def _draw_untextured_cube(self) -> None:
        glDisable(GL_TEXTURE_2D)
        glBegin(GL_QUADS)
        glVertex3f(-0.5, -0.5, 0.5)
        glVertex3f(0.5, -0.5, 0.5)
        glVertex3f(0.5, 0.5, 0.5)
        glVertex3f(-0.5, 0.5, 0.5)
        glVertex3f(-0.5, -0.5, -0.5)
        glVertex3f(-0.5, 0.5, -0.5)
        glVertex3f(0.5, 0.5, -0.5)
        glVertex3f(0.5, -0.5, -0.5)
        glVertex3f(-0.5, 0.5, -0.5)
        glVertex3f(-0.5, 0.5, 0.5)
        glVertex3f(0.5, 0.5, 0.5)
        glVertex3f(0.5, 0.5, -0.5)
        glVertex3f(-0.5, -0.5, -0.5)
        glVertex3f(0.5, -0.5, -0.5)
        glVertex3f(0.5, -0.5, 0.5)
        glVertex3f(-0.5, -0.5, 0.5)
        glVertex3f(0.5, -0.5, -0.5)
        glVertex3f(0.5, 0.5, -0.5)
        glVertex3f(0.5, 0.5, 0.5)
        glVertex3f(0.5, -0.5, 0.5)
        glVertex3f(-0.5, -0.5, -0.5)
        glVertex3f(-0.5, -0.5, 0.5)
        glVertex3f(-0.5, 0.5, 0.5)
        glVertex3f(-0.5, 0.5, -0.5)
        glEnd()
        glEnable(GL_TEXTURE_2D)

    # ------------------------------------------------------------------ textures

    def _load_texture(self, path: str) -> Optional[int]:
        if not os.path.exists(path):
            return None
        img = QImage(path)
        if img.isNull():
            return None
        img = img.convertToFormat(QImage.Format_RGBA8888)
        w, h = img.width(), img.height()
        ptr = img.bits()
        data = bytes(ptr[:w * h * 4])

        tex_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h,
                     0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        glBindTexture(GL_TEXTURE_2D, 0)
        return int(tex_id)

    def _get_text_texture(self, text: str) -> int:
        # Limit cache size to prevent memory bloat
        if len(self._text_texture_cache) >= 200:
            # Remove oldest 50 entries
            keys_to_remove = list(self._text_texture_cache.keys())[:50]
            for key in keys_to_remove:
                tex_id = self._text_texture_cache.pop(key)
                try:
                    if tex_id > 0:
                        glDeleteTextures([tex_id])
                except Exception:
                    pass

        cached = self._text_texture_cache.get(text)
        if cached:
            return cached

        text = str(text)
        if not text:
            return 0

        # Measure actual text extent
        font = QFont('Arial', 28)
        font.setBold(True)
        fm = QFontMetrics(font)
        text_width = fm.horizontalAdvance(text)
        text_height = fm.height()

        # Add padding
        pad = 10
        w = text_width + pad * 2
        h = text_height + pad * 2

        # Use minimum size to avoid tiny textures
        w, h = max(w, 64), max(h, 32)

        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setFont(font)
        p.setPen(QColor(255, 235, 120, 255))
        p.drawText(pad, pad, text_width, text_height,
                   Qt.AlignLeft | Qt.AlignTop, text)
        p.end()
        img = img.mirrored(False, True)

        ptr = img.constBits()
        size = int(img.sizeInBytes())
        data = ptr.tobytes()[:size] if hasattr(
            ptr, 'tobytes') else bytes(ptr)[:size]

        tex_id = glGenTextures(1)
        if tex_id == 0:
            return 0
        glBindTexture(GL_TEXTURE_2D, int(tex_id))
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h,
                     0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        glBindTexture(GL_TEXTURE_2D, 0)

        self._text_texture_cache[text] = int(tex_id)
        return int(tex_id)

    def _get_jail_map_texture(self) -> int:
        if self._jail_map_texture is not None:
            return self._jail_map_texture

        grid_h = int(getattr(self.core, 'height', 0) or 0)
        grid_w = int(getattr(self.core, 'width', 0) or 0)
        if grid_h <= 0 or grid_w <= 0:
            return 0

        palette = {
            'A': QColor(80, 120, 200), 'B': QColor(180, 130, 80),
            'C': QColor(80, 180, 100), 'D': QColor(110, 180, 180),
            'E': QColor(180, 100, 140), 'F': QColor(180, 180, 90),
            'G': QColor(160, 100, 190), 'H': QColor(150, 150, 150),
        }

        iw, ih = 640, 420
        img = QImage(iw, ih, QImage.Format.Format_RGBA8888)
        img.fill(QColor(50, 42, 36, 255))

        margin = 28
        cell = min((iw - margin * 2) / grid_w, (ih - margin * 2) / grid_h)
        ox = (iw - cell * grid_w) * 0.5
        oy = (ih - cell * grid_h) * 0.5

        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        sid_for = getattr(self.core, 'sector_id_for_cell', None)

        for rr in range(grid_h):
            for cc in range(grid_w):
                if (rr, cc) in self.core.walls:
                    continue
                sid = sid_for((rr, cc)) if callable(sid_for) else ''
                col = palette.get(sid)
                if col:
                    p.fillRect(int(ox + cc * cell), int(oy + rr * cell),
                               int(cell + 1), int(cell + 1), col)

        acc: dict[str, list] = {}
        if callable(sid_for):
            for rr in range(grid_h):
                for cc in range(grid_w):
                    if (rr, cc) in self.core.walls:
                        continue
                    sid = sid_for((rr, cc))
                    if sid:
                        acc.setdefault(sid, [0.0, 0.0, 0])
                        acc[sid][0] += rr
                        acc[sid][1] += cc
                        acc[sid][2] += 1

        font_big = QFont('Arial', 52)
        font_big.setBold(True)
        p.setFont(font_big)
        p.setPen(QColor(10, 10, 12, 255))
        for sid, (sx, sy, n) in acc.items():
            if n > 0:
                p.drawText(int(ox + (sy / n + 0.5) * cell - 22),
                           int(oy + (sx / n + 0.5) * cell + 22), sid[:1])

        if getattr(self.core, 'exit_cells', None):
            er, ec = self.core.exit_cells[0]
            ex = ox + (ec + 0.5) * cell + 5
            ey = oy + (er + 0.5) * cell
            font_small = QFont('Arial', 22)
            font_small.setBold(True)
            p.setFont(font_small)
            p.fillRect(int(ex - 32), int(ey - 13), 64,
                       26, QColor(210, 190, 175, 200))
            p.setPen(QColor(15, 15, 16, 255))
            p.drawText(int(ex - 22), int(ey + 9), 'exit')

        p.end()
        img = img.mirrored(False, True)

        ptr = img.constBits()
        size = int(img.sizeInBytes())
        data = ptr.tobytes()[:size] if hasattr(
            ptr, 'tobytes') else bytes(ptr)[:size]

        tex_id = glGenTextures(1)
        if tex_id == 0:
            return 0
        glBindTexture(GL_TEXTURE_2D, int(tex_id))
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, iw, ih,
                     0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        glBindTexture(GL_TEXTURE_2D, 0)

        self._jail_map_texture = int(tex_id)
        return self._jail_map_texture
