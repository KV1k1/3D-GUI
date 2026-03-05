import ctypes
import math
import os
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
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

        self._fog_enabled = True
        self._fog_start = 22.0
        self._fog_end = 40.0

        self._fast_mode = True

        self.wall_color = (0.45, 0.45, 0.5, 1.0)
        self.floor_color = (0.25, 0.23, 0.22, 1.0)
        self.sky_color = (0.05, 0.05, 0.08, 1.0)

        self._tex_wall: Optional[int] = None
        self._tex_floor: Optional[int] = None

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

    def initialize(self) -> None:
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
            glFogfv(GL_FOG_COLOR, [float(self.sky_color[0]), float(
                self.sky_color[1]), float(self.sky_color[2]), 1.0])
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
            glBindTexture(GL_TEXTURE_2D, int(self._tex_coin))
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            glBindTexture(GL_TEXTURE_2D, 0)

        self._build_static_geometry()
        self._build_world_vbos()
        self._build_ghost_vbo()

    def _delete_world_vbos(self) -> None:
        try:
            if self._world_vbo_floor is not None:
                glDeleteBuffers(1, [int(self._world_vbo_floor)])
        except Exception:
            pass
        try:
            if self._world_vbo_wall is not None:
                glDeleteBuffers(1, [int(self._world_vbo_wall)])
        except Exception:
            pass
        self._world_vbo_floor = None
        self._world_vbo_wall = None
        self._world_floor_vertex_count = 0
        self._world_wall_vertex_count = 0

        for vbo in (self._ghost_body_vbo, self._ghost_eye_vbo):
            try:
                if vbo is not None:
                    glDeleteBuffers(1, [int(vbo)])
            except Exception:
                pass
        if self._ghost_tail_vbos:
            for vbo in self._ghost_tail_vbos:
                try:
                    if vbo is not None:
                        glDeleteBuffers(1, [int(vbo)])
                except Exception:
                    pass
        self._ghost_body_vbo = None
        self._ghost_body_vertex_count = 0
        self._ghost_eye_vbo = None
        self._ghost_eye_vertex_count = 0
        self._ghost_tail_vbos = []
        self._ghost_tail_vertex_counts = []
        self._ghost_tail_pose_count = 0

        if self._chunk_vbos:
            for floor_vbo, _, wall_vbo, _ in self._chunk_vbos.values():
                try:
                    if floor_vbo is not None:
                        glDeleteBuffers(1, [int(floor_vbo)])
                except Exception:
                    pass
                try:
                    if wall_vbo is not None:
                        glDeleteBuffers(1, [int(wall_vbo)])
                except Exception:
                    pass
            self._chunk_vbos.clear()

    def _build_world_vbos(self) -> None:
        # Build separate VBOs for floors and walls (static geometry). If VBO creation fails,
        # we gracefully fall back to immediate mode in _draw_world().
        from array import array

        self._delete_world_vbos()

        floor_data = array('f')
        wall_data = array('f')
        chunk_floor: dict[tuple[int, int], array] = {}
        chunk_wall: dict[tuple[int, int], array] = {}

        # Vertex layout: [x, y, z, u, v] per vertex.
        for cr, cc, tex_id, quad in self._static_quads:
            target = floor_data if tex_id == self._tex_floor else wall_data
            if tex_id not in (self._tex_floor, self._tex_wall):
                continue

            ch_r = int(float(cr) // float(self._chunk_size))
            ch_c = int(float(cc) // float(self._chunk_size))
            ch_key = (ch_r, ch_c)
            if tex_id == self._tex_floor:
                ch_target = chunk_floor.get(ch_key)
                if ch_target is None:
                    ch_target = array('f')
                    chunk_floor[ch_key] = ch_target
            else:
                ch_target = chunk_wall.get(ch_key)
                if ch_target is None:
                    ch_target = array('f')
                    chunk_wall[ch_key] = ch_target

            for (u, v, x, y, z) in quad:
                target.extend(
                    [float(x), float(y), float(z), float(u), float(v)])
                ch_target.extend(
                    [float(x), float(y), float(z), float(u), float(v)])

        self._world_floor_vertex_count = int(len(floor_data) // 5)
        self._world_wall_vertex_count = int(len(wall_data) // 5)

        self._chunk_vbos.clear()

        try:
            if self._world_floor_vertex_count > 0:
                vbo = glGenBuffers(1)
                self._world_vbo_floor = int(vbo) if vbo else None
                if self._world_vbo_floor:
                    glBindBuffer(GL_ARRAY_BUFFER, int(self._world_vbo_floor))
                    glBufferData(GL_ARRAY_BUFFER,
                                 floor_data.tobytes(), GL_STATIC_DRAW)

            if self._world_wall_vertex_count > 0:
                vbo = glGenBuffers(1)
                self._world_vbo_wall = int(vbo) if vbo else None
                if self._world_vbo_wall:
                    glBindBuffer(GL_ARRAY_BUFFER, int(self._world_vbo_wall))
                    glBufferData(GL_ARRAY_BUFFER,
                                 wall_data.tobytes(), GL_STATIC_DRAW)

            glBindBuffer(GL_ARRAY_BUFFER, 0)

            # Build per-chunk VBOs so we can cull distant static geometry.
            for ch_key in sorted(set(chunk_floor.keys()) | set(chunk_wall.keys())):
                fd = chunk_floor.get(ch_key)
                wd = chunk_wall.get(ch_key)

                floor_vbo: Optional[int] = None
                wall_vbo: Optional[int] = None
                floor_count = int(len(fd) // 5) if fd else 0
                wall_count = int(len(wd) // 5) if wd else 0

                if floor_count > 0:
                    vbo = glGenBuffers(1)
                    floor_vbo = int(vbo) if vbo else None
                    if floor_vbo:
                        glBindBuffer(GL_ARRAY_BUFFER, int(floor_vbo))
                        glBufferData(GL_ARRAY_BUFFER,
                                     fd.tobytes(), GL_STATIC_DRAW)

                if wall_count > 0:
                    vbo = glGenBuffers(1)
                    wall_vbo = int(vbo) if vbo else None
                    if wall_vbo:
                        glBindBuffer(GL_ARRAY_BUFFER, int(wall_vbo))
                        glBufferData(GL_ARRAY_BUFFER,
                                     wd.tobytes(), GL_STATIC_DRAW)

                glBindBuffer(GL_ARRAY_BUFFER, 0)
                self._chunk_vbos[ch_key] = (
                    floor_vbo, floor_count, wall_vbo, wall_count)
        except Exception:
            self._delete_world_vbos()

    def _build_ghost_vbo(self) -> None:
        from array import array

        # Delete old VBOs first (if any)
        for vbo in (self._ghost_body_vbo, self._ghost_eye_vbo):
            try:
                if vbo is not None:
                    glDeleteBuffers(1, [int(vbo)])
            except Exception:
                pass
        if self._ghost_tail_vbos:
            for vbo in self._ghost_tail_vbos:
                try:
                    if vbo is not None:
                        glDeleteBuffers(1, [int(vbo)])
                except Exception:
                    pass

        self._ghost_body_vbo = None
        self._ghost_body_vertex_count = 0
        self._ghost_eye_vbo = None
        self._ghost_eye_vertex_count = 0
        self._ghost_tail_vbos = []
        self._ghost_tail_vertex_counts = []
        self._ghost_tail_pose_count = 0

        segments = 18 if self._fast_mode else 28
        body_layers = 11
        tail_layers = 8
        radius = 0.20

        def y_and_r(t: float) -> tuple[float, float]:
            if t < 0.5:
                yv = radius * 0.62 * math.cos(t * math.pi)
                rv = radius * 0.95 * math.sin(t * math.pi)
            else:
                yv = -radius * 0.25 * (t - 0.5) * 2.0
                rv = radius * 0.95
            return yv, rv

        def add_strip(data: array, y0: float, r0: float, y1: float, r1: float) -> None:
            for i in range(segments + 1):
                a = (i / segments) * (2.0 * math.pi)
                ca = math.cos(a)
                sa = math.sin(a)

                x = ca * r0
                z = sa * r0
                data.extend([x, y0, z, ca, 0.0, sa])

                x = ca * r1
                z = sa * r1
                data.extend([x, y1, z, ca, 0.0, sa])

        # Body VBO (static)
        body = array('f')
        for layer in range(1, body_layers):
            layer_ratio = layer / (body_layers - 1)
            prev_ratio = (layer - 1) / (body_layers - 1)
            y_prev, r_prev = y_and_r(prev_ratio)
            y_curr, r_curr = y_and_r(layer_ratio)
            add_strip(body, y_prev, r_prev, y_curr, r_curr)

        self._ghost_body_vertex_count = int(len(body) // 6)

        # Eyes VBO (static, 2 quads)
        eye = array('f')
        eye_y = radius * 0.22
        eye_z = radius * 1.05
        eye_x = radius * 0.34
        ew = radius * 0.22
        eh = radius * 0.28

        def add_eye_quad(cx: float) -> None:
            # Normal points forward (+Z)
            nx, ny, nz = 0.0, 0.0, 1.0
            x0 = cx - ew
            x1 = cx + ew
            y0 = eye_y - eh
            y1 = eye_y + eh
            z0 = eye_z
            # Two triangles
            eye.extend([x0, y0, z0, nx, ny, nz])
            eye.extend([x1, y0, z0, nx, ny, nz])
            eye.extend([x1, y1, z0, nx, ny, nz])
            eye.extend([x0, y0, z0, nx, ny, nz])
            eye.extend([x1, y1, z0, nx, ny, nz])
            eye.extend([x0, y1, z0, nx, ny, nz])

        add_eye_quad(-eye_x)
        add_eye_quad(eye_x)
        self._ghost_eye_vertex_count = int(len(eye) // 6)

        # Tail poses VBOs (animated via pose switching)
        pose_count = 12
        self._ghost_tail_pose_count = int(pose_count)
        tail_vbos: list[Optional[int]] = []
        tail_counts: list[int] = []

        # Precompute pose data without relying on runtime _anim_t.
        for pose in range(pose_count):
            phase = (pose / max(1, pose_count)) * (2.0 * math.pi)
            tail = array('f')

            for layer in range(tail_layers):
                layer_ratio = layer / tail_layers
                prev_ratio = (layer - 1) / tail_layers

                base_r = radius * 0.95 * (1.0 - layer_ratio * 0.35)
                wave_amp = radius * (0.08 + 0.14 * layer_ratio)
                y_curr = -radius * 0.52 - layer_ratio * radius * 0.48

                def skirt_val(a: float, layer_idx: int, amp: float, ph: float) -> float:
                    return (
                        math.sin(a * 3.0 + ph + layer_idx * 0.55) * amp
                        + math.sin(a * 7.0 - ph * 0.7 +
                                   layer_idx * 0.35) * (amp * 0.55)
                    )

                if layer == 0:
                    for i in range(segments + 1):
                        a = (i / segments) * (2.0 * math.pi)
                        ca = math.cos(a)
                        sa = math.sin(a)
                        skirt = skirt_val(a, layer, wave_amp, phase)
                        r_curr = max(radius * 0.02, base_r + skirt)

                        # body connection ring
                        tail.extend([ca * radius * 0.95, -radius *
                                    0.25, sa * radius * 0.95, ca, 0.0, sa])
                        tail.extend(
                            [ca * r_curr, y_curr, sa * r_curr, ca, 0.0, sa])
                else:
                    prev_base_r = radius * 0.95 * (1.0 - prev_ratio * 0.35)
                    prev_amp = radius * (0.08 + 0.14 * prev_ratio)
                    y_prev = -radius * 0.52 - prev_ratio * radius * 0.48

                    for i in range(segments + 1):
                        a = (i / segments) * (2.0 * math.pi)
                        ca = math.cos(a)
                        sa = math.sin(a)
                        skirt_prev = skirt_val(a, layer - 1, prev_amp, phase)
                        skirt_curr = skirt_val(a, layer, wave_amp, phase)
                        r_prev = max(radius * 0.02, prev_base_r + skirt_prev)
                        r_curr = max(radius * 0.02, base_r + skirt_curr)
                        tail.extend(
                            [ca * r_prev, y_prev, sa * r_prev, ca, 0.0, sa])
                        tail.extend(
                            [ca * r_curr, y_curr, sa * r_curr, ca, 0.0, sa])

            tail_counts.append(int(len(tail) // 6))
            try:
                vbo = glGenBuffers(1)
                tv = int(vbo) if vbo else None
                if tv and tail_counts[-1] > 0:
                    glBindBuffer(GL_ARRAY_BUFFER, int(tv))
                    glBufferData(GL_ARRAY_BUFFER,
                                 tail.tobytes(), GL_STATIC_DRAW)
                    glBindBuffer(GL_ARRAY_BUFFER, 0)
                else:
                    tv = None
                tail_vbos.append(tv)
            except Exception:
                tail_vbos.append(None)

        try:
            if self._ghost_body_vertex_count > 0:
                vbo = glGenBuffers(1)
                self._ghost_body_vbo = int(vbo) if vbo else None
                if self._ghost_body_vbo:
                    glBindBuffer(GL_ARRAY_BUFFER, int(self._ghost_body_vbo))
                    glBufferData(GL_ARRAY_BUFFER,
                                 body.tobytes(), GL_STATIC_DRAW)
                    glBindBuffer(GL_ARRAY_BUFFER, 0)

            if self._ghost_eye_vertex_count > 0:
                vbo = glGenBuffers(1)
                self._ghost_eye_vbo = int(vbo) if vbo else None
                if self._ghost_eye_vbo:
                    glBindBuffer(GL_ARRAY_BUFFER, int(self._ghost_eye_vbo))
                    glBufferData(GL_ARRAY_BUFFER,
                                 eye.tobytes(), GL_STATIC_DRAW)
                    glBindBuffer(GL_ARRAY_BUFFER, 0)
        except Exception:
            self._ghost_body_vbo = None
            self._ghost_body_vertex_count = 0
            self._ghost_eye_vbo = None
            self._ghost_eye_vertex_count = 0

        self._ghost_tail_vbos = tail_vbos
        self._ghost_tail_vertex_counts = tail_counts

    def _draw_ghost_vbo(self, color: Tuple[float, float, float, float]) -> None:
        if self._ghost_body_vbo is None or self._ghost_body_vertex_count <= 0:
            self._draw_ghost_3d(color)
            return

        stride = 6 * 4

        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_NORMAL_ARRAY)

        # Body
        glColor4f(*color)
        glBindBuffer(GL_ARRAY_BUFFER, int(self._ghost_body_vbo))
        glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
        glNormalPointer(GL_FLOAT, stride, ctypes.c_void_p(12))
        glDrawArrays(GL_TRIANGLE_STRIP, 0, int(self._ghost_body_vertex_count))

        # Tail pose
        if self._ghost_tail_pose_count > 0 and self._ghost_tail_vbos:
            pose_fps = 6.0
            pose_idx = int(
                self._anim_t * pose_fps) % int(self._ghost_tail_pose_count)
            if 0 <= pose_idx < len(self._ghost_tail_vbos):
                vbo = self._ghost_tail_vbos[pose_idx]
                cnt = self._ghost_tail_vertex_counts[pose_idx] if pose_idx < len(
                    self._ghost_tail_vertex_counts) else 0
                if vbo is not None and cnt > 0:
                    glBindBuffer(GL_ARRAY_BUFFER, int(vbo))
                    glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
                    glNormalPointer(GL_FLOAT, stride, ctypes.c_void_p(12))
                    glDrawArrays(GL_TRIANGLE_STRIP, 0, int(cnt))

        # Eyes (draw after tail; same transform)
        if self._ghost_eye_vbo is not None and self._ghost_eye_vertex_count > 0:
            glColor4f(0.06, 0.06, 0.08, 0.96)
            glBindBuffer(GL_ARRAY_BUFFER, int(self._ghost_eye_vbo))
            glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
            glNormalPointer(GL_FLOAT, stride, ctypes.c_void_p(12))
            glDrawArrays(GL_TRIANGLES, 0, int(self._ghost_eye_vertex_count))

        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glDisableClientState(GL_NORMAL_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)

    def _draw_world_immediate(self) -> None:
        """Fallback immediate-mode draw for world geometry"""
        pr = int(round(float(self.core.player.z)))
        pc = int(round(float(self.core.player.x)))

        pr = self.core.player.z
        pc = self.core.player.x
        radius = 28.0
        r2 = radius * radius

        view_radius = 25.0
        view_r2 = view_radius * view_radius

        bound_tex: Optional[int] = None
        texture_enabled = False
        for cr, cc, tex_id, quad in self._static_quads:
            dx = cc - pc
            dz = cr - pr
            if dx * dx + dz * dz > view_r2:
                continue
            if dx * dx + dz * dz > r2:
                continue

            if tex_id != bound_tex:
                if tex_id is None:
                    if texture_enabled:
                        glDisable(GL_TEXTURE_2D)
                        texture_enabled = False
                    self._bind_texture(None)
                    glColor4f(0.75, 0.75, 0.80, 1.0)
                else:
                    if not texture_enabled:
                        glEnable(GL_TEXTURE_2D)
                        texture_enabled = True
                    self._bind_texture(tex_id)
                    glColor4f(1.0, 1.0, 1.0, 1.0)
                bound_tex = tex_id

            glBegin(GL_QUADS)
            for (u, v, x, y, z) in quad:
                if texture_enabled:
                    glTexCoord2f(u, v)
                glVertex3f(x, y, z)
            glEnd()

        self._bind_texture(None)
        if texture_enabled:
            glDisable(GL_TEXTURE_2D)
        glEnable(GL_LIGHTING)

    def _draw_world(self) -> None:
        """Draw world geometry"""
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

            # Draw nearby chunks only (conservative radius based on fog end)
            px = float(self.core.player.x)
            pz = float(self.core.player.z)
            ch_r0 = int(pz // float(self._chunk_size))
            ch_c0 = int(px // float(self._chunk_size))

            chunk_radius = max(
                2, int(math.ceil(float(self._fog_end) / float(self._chunk_size))) + 1)

            for dr in range(-chunk_radius, chunk_radius + 1):
                for dc in range(-chunk_radius, chunk_radius + 1):
                    key = (ch_r0 + dr, ch_c0 + dc)
                    entry = self._chunk_vbos.get(key)
                    if not entry:
                        continue

                    floor_vbo, floor_count, wall_vbo, wall_count = entry

                    if floor_vbo is not None and floor_count > 0:
                        self._bind_texture(self._tex_floor)
                        glBindBuffer(GL_ARRAY_BUFFER, int(floor_vbo))
                        glVertexPointer(3, GL_FLOAT, stride,
                                        ctypes.c_void_p(0))
                        glTexCoordPointer(2, GL_FLOAT, stride,
                                          ctypes.c_void_p(12))
                        glDrawArrays(GL_QUADS, 0, int(floor_count))

                    if wall_vbo is not None and wall_count > 0:
                        self._bind_texture(self._tex_wall)
                        glBindBuffer(GL_ARRAY_BUFFER, int(wall_vbo))
                        glVertexPointer(3, GL_FLOAT, stride,
                                        ctypes.c_void_p(0))
                        glTexCoordPointer(2, GL_FLOAT, stride,
                                          ctypes.c_void_p(12))
                        glDrawArrays(GL_QUADS, 0, int(wall_count))

            glBindBuffer(GL_ARRAY_BUFFER, 0)
            self._bind_texture(None)
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
            glFogfv(GL_FOG_COLOR, [float(self.sky_color[0]), float(
                self.sky_color[1]), float(self.sky_color[2]), 1.0])

    def render(self) -> None:
        glEnable(GL_DEPTH_TEST)
        self._anim_t = float(self.core.elapsed_s)
        glClearColor(*self.sky_color)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

        px = self.core.player.x
        py = self.core.player.y + self.camera_height
        pz = self.core.player.z

        yaw = self.core.player.yaw
        pitch = self.core.player.pitch

        lx = px + math.sin(yaw) * math.cos(pitch)
        ly = py + math.sin(pitch)
        lz = pz + math.cos(yaw) * math.cos(pitch)

        # When looking near straight up/down, the view direction becomes almost collinear
        # with the fixed up-vector (0,1,0). Some GLU implementations can produce an
        # unstable matrix in this case. Use a dynamic up-vector to keep the basis valid.
        fx = float(lx - px)
        fy = float(ly - py)
        fz = float(lz - pz)
        f_len = math.sqrt(fx * fx + fy * fy + fz * fz)
        if f_len > 0.0:
            fx /= f_len
            fy /= f_len
            fz /= f_len

        if abs(fy) > 0.97:
            upx, upy, upz = 1.0, 0.0, 0.0
        else:
            upx, upy, upz = 0.0, 1.0, 0.0

        gluLookAt(px, py, pz, lx, ly, lz, upx, upy, upz)

        glDisable(GL_BLEND)
        glDepthMask(True)
        self._draw_world()
        glEnable(GL_BLEND)
        self._draw_entities()

    def _build_static_geometry(self) -> None:
        self._static_quads.clear()
        wall_h = float(self.core.wall_height)
        ceil_h = float(self.core.ceiling_height)

        def add_quad(center_r: float, center_c: float, tex: Optional[int], vtx: Tuple[Tuple[float, float, float, float, float], ...]):
            self._static_quads.append((center_r, center_c, tex, vtx))

        floors = self.core.floors
        walls = self.core.walls

        # Use layout bounds for boundary sealing.
        h = int(getattr(self.core, 'height', 0))
        w = int(getattr(self.core, 'width', 0))

        def is_solid(rr: int, cc: int) -> bool:
            # Walls are solid; outside map is treated as empty so we generate boundary faces.
            if rr < 0 or cc < 0 or rr >= h or cc >= w:
                return False
            return (rr, cc) in walls

        def is_inside(rr: int, cc: int) -> bool:
            return 0 <= rr < h and 0 <= cc < w

        for (r, c) in floors:
            cx = c + 0.5
            cz = r + 0.5
            add_quad(
                cz,
                cx,
                self._tex_floor,
                (
                    (0.0, 0.0, cx - 0.5, 0.0, cz - 0.5),
                    (1.0, 0.0, cx + 0.5, 0.0, cz - 0.5),
                    (1.0, 1.0, cx + 0.5, 0.0, cz + 0.5),
                    (0.0, 1.0, cx - 0.5, 0.0, cz + 0.5),
                ),
            )
            add_quad(
                cz,
                cx,
                self._tex_floor,
                (
                    (0.0, 0.0, cx - 0.5, ceil_h, cz + 0.5),
                    (1.0, 0.0, cx + 0.5, ceil_h, cz + 0.5),
                    (1.0, 1.0, cx + 0.5, ceil_h, cz - 0.5),
                    (0.0, 1.0, cx - 0.5, ceil_h, cz - 0.5),
                ),
            )

            # Boundary sealing: if this floor touches the outer map boundary, add a wall face.
            # This keeps start/exit tunnels from opening into the void without changing map data.
            if not is_inside(r - 1, c):
                add_quad(
                    cz, cx, self._tex_wall,
                    (
                        (0.0, 0.0, cx - 0.5, 0.0, cz - 0.5),
                        (1.0, 0.0, cx + 0.5, 0.0, cz - 0.5),
                        (1.0, 1.0, cx + 0.5, wall_h, cz - 0.5),
                        (0.0, 1.0, cx - 0.5, wall_h, cz - 0.5),
                    ),
                )
            if not is_inside(r + 1, c):
                add_quad(
                    cz, cx, self._tex_wall,
                    (
                        (0.0, 0.0, cx + 0.5, 0.0, cz + 0.5),
                        (1.0, 0.0, cx - 0.5, 0.0, cz + 0.5),
                        (1.0, 1.0, cx - 0.5, wall_h, cz + 0.5),
                        (0.0, 1.0, cx + 0.5, wall_h, cz + 0.5),
                    ),
                )
            if not is_inside(r, c - 1):
                add_quad(
                    cz, cx, self._tex_wall,
                    (
                        (0.0, 0.0, cx - 0.5, 0.0, cz + 0.5),
                        (1.0, 0.0, cx - 0.5, 0.0, cz - 0.5),
                        (1.0, 1.0, cx - 0.5, wall_h, cz - 0.5),
                        (0.0, 1.0, cx - 0.5, wall_h, cz + 0.5),
                    ),
                )
            if not is_inside(r, c + 1):
                add_quad(
                    cz, cx, self._tex_wall,
                    (
                        (0.0, 0.0, cx + 0.5, 0.0, cz - 0.5),
                        (1.0, 0.0, cx + 0.5, 0.0, cz + 0.5),
                        (1.0, 1.0, cx + 0.5, wall_h, cz + 0.5),
                        (0.0, 1.0, cx + 0.5, wall_h, cz - 0.5),
                    ),
                )

        # Walls: generate only faces that are exposed to non-wall space.
        # This reduces draw calls and prevents "double walls" artifacts at map boundaries.
        for (r, c) in walls:
            cx = c + 0.5
            cz = r + 0.5
            y0 = 0.0
            y1 = wall_h

            # North face (towards r-1)
            if not is_solid(r - 1, c):
                add_quad(
                    cz, cx, self._tex_wall,
                    (
                        (0.0, 0.0, cx - 0.5, y0, cz - 0.5),
                        (1.0, 0.0, cx + 0.5, y0, cz - 0.5),
                        (1.0, 1.0, cx + 0.5, y1, cz - 0.5),
                        (0.0, 1.0, cx - 0.5, y1, cz - 0.5),
                    ),
                )

            # South face (towards r+1)
            if not is_solid(r + 1, c):
                add_quad(
                    cz, cx, self._tex_wall,
                    (
                        (0.0, 0.0, cx + 0.5, y0, cz + 0.5),
                        (1.0, 0.0, cx - 0.5, y0, cz + 0.5),
                        (1.0, 1.0, cx - 0.5, y1, cz + 0.5),
                        (0.0, 1.0, cx + 0.5, y1, cz + 0.5),
                    ),
                )

            # West face (towards c-1)
            if not is_solid(r, c - 1):
                add_quad(
                    cz, cx, self._tex_wall,
                    (
                        (0.0, 0.0, cx - 0.5, y0, cz + 0.5),
                        (1.0, 0.0, cx - 0.5, y0, cz - 0.5),
                        (1.0, 1.0, cx - 0.5, y1, cz - 0.5),
                        (0.0, 1.0, cx - 0.5, y1, cz + 0.5),
                    ),
                )

            # East face (towards c+1)
            if not is_solid(r, c + 1):
                add_quad(
                    cz, cx, self._tex_wall,
                    (
                        (0.0, 0.0, cx + 0.5, y0, cz - 0.5),
                        (1.0, 0.0, cx + 0.5, y0, cz + 0.5),
                        (1.0, 1.0, cx + 0.5, y1, cz + 0.5),
                        (0.0, 1.0, cx + 0.5, y1, cz - 0.5),
                    ),
                )

            # Top face (only if there is no wall above it; keeps ceiling from looking open if wall_h < ceil_h)
            if y1 < ceil_h and (not is_solid(r - 1, c) or not is_solid(r + 1, c) or not is_solid(r, c - 1) or not is_solid(r, c + 1)):
                add_quad(
                    cz, cx, self._tex_wall,
                    (
                        (0.0, 0.0, cx - 0.5, y1, cz + 0.5),
                        (1.0, 0.0, cx + 0.5, y1, cz + 0.5),
                        (1.0, 1.0, cx + 0.5, y1, cz - 0.5),
                        (0.0, 1.0, cx - 0.5, y1, cz - 0.5),
                    ),
                )

    def _draw_entities(self) -> None:
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)

        cam_yaw = self.core.player.yaw
        right_x = math.cos(cam_yaw)
        right_z = -math.sin(cam_yaw)
        up_y = 1.0

        def billboard_quad(cx: float, cy: float, cz: float, w: float, h: float, color: Tuple[float, float, float, float]) -> None:
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

        def soft_aura(cx: float, cy: float, cz: float, base_size: float, color: Tuple[float, float, float], alpha: float) -> None:
            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
            glDepthMask(False)
            sizes = (base_size * 0.9, base_size * 1.25, base_size * 1.65)
            alphas = (alpha * 0.55, alpha * 0.28, alpha * 0.14)
            for s, a in zip(sizes, alphas):
                billboard_quad(cx, cy, cz, s, s,
                               (color[0], color[1], color[2], a))
            glDepthMask(True)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        def radial_sprite_glow(cx: float, cy: float, cz: float, radius: float, color: Tuple[float, float, float], alpha: float) -> None:
            # Seamless circular glow oriented towards the camera (no rectangular billboard edges).
            from OpenGL.GL import GL_TRIANGLE_FAN

            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
            glDepthMask(False)
            glBegin(GL_TRIANGLE_FAN)
            glColor4f(color[0], color[1], color[2], alpha)
            glVertex3f(cx, cy, cz)
            steps = 28
            glColor4f(color[0], color[1], color[2], 0.0)
            for i in range(steps + 1):
                a = (i / steps) * (2.0 * math.pi)
                x = math.cos(a) * radius
                y = math.sin(a) * radius
                glVertex3f(cx + x * right_x, cy + y, cz + x * right_z)
            glEnd()
            glDepthMask(True)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        def floor_glow(cx: float, cz: float, y: float, radius: float, color: Tuple[float, float, float], alpha: float) -> None:
            # Camera-independent circular glow projected onto the floor.
            from OpenGL.GL import GL_TRIANGLE_FAN

            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
            glDepthMask(False)
            glBegin(GL_TRIANGLE_FAN)
            glColor4f(color[0], color[1], color[2], alpha)
            glVertex3f(cx, y, cz)
            steps = 22
            glColor4f(color[0], color[1], color[2], 0.0)
            for i in range(steps + 1):
                a = (i / steps) * (2.0 * math.pi)
                glVertex3f(cx + math.cos(a) * radius,
                           y, cz + math.sin(a) * radius)
            glEnd()
            glDepthMask(True)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        def _draw_coin_3d_mario(radius: float = 0.13, thickness: float = 0.045, segments: int = 18, textured: bool = False) -> None:
            from OpenGL.GL import GL_TRIANGLE_FAN, GL_POINTS, GL_QUADS

            y0 = -thickness / 2.0
            y1 = thickness / 2.0

            stripe_segments = segments // 24
            glBegin(GL_QUADS)
            for i in range(segments):
                a0 = (i / segments) * (2.0 * math.pi)
                a1 = ((i + 1) / segments) * (2.0 * math.pi)
                x0 = math.cos(a0) * radius
                z0 = math.sin(a0) * radius
                x1 = math.cos(a1) * radius
                z1 = math.sin(a1) * radius

                stripe_index = i // stripe_segments
                if stripe_index % 2 == 0:
                    glColor4f(1.0, 0.84, 0.18, 0.98)
                else:
                    glColor4f(240/255, 168/255, 48/255, 0.98)

                glVertex3f(x0, y0, z0)
                glVertex3f(x1, y0, z1)
                glVertex3f(x1, y1, z1)
                glVertex3f(x0, y1, z0)
            glEnd()

            if textured and self._tex_coin:
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, self._tex_coin)
                glColor4f(1.0, 1.0, 1.0, 0.98)

                glDisable(GL_TEXTURE_2D)
                glColor4f(1.0, 0.84, 0.18, 0.98)
                glBegin(GL_TRIANGLE_FAN)
                glVertex3f(0.0, y1, 0.0)
                for i in range(segments + 1):
                    a = (i / segments) * (2.0 * math.pi)
                    glVertex3f(math.cos(a) * radius, y1, math.sin(a) * radius)
                glEnd()

                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, self._tex_coin)
                glColor4f(1.0, 1.0, 1.0, 0.98)
                inner_radius = radius * 0.92
                glBegin(GL_TRIANGLE_FAN)
                glTexCoord2f(0.5, 0.5)
                glVertex3f(0.0, y1 + 0.001, 0.0)
                for i in range(segments + 1):
                    a = (i / segments) * (2.0 * math.pi)
                    u = 0.5 + 0.48 * math.cos(a)
                    v = 0.5 + 0.48 * math.sin(a)
                    glTexCoord2f(u, v)
                    glVertex3f(math.cos(a) * inner_radius, y1 +
                               0.001, math.sin(a) * inner_radius)
                glEnd()

                glDisable(GL_TEXTURE_2D)
                glColor4f(1.0, 0.84, 0.18, 0.98)
                glBegin(GL_TRIANGLE_FAN)
                glVertex3f(0.0, y0, 0.0)
                for i in range(segments + 1):
                    a = (i / segments) * (2.0 * math.pi)
                    glVertex3f(math.cos(a) * radius, y0, math.sin(a) * radius)
                glEnd()

                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, self._tex_coin)
                glColor4f(1.0, 1.0, 1.0, 0.98)
                glBegin(GL_TRIANGLE_FAN)
                glTexCoord2f(0.5, 0.5)
                glVertex3f(0.0, y0 - 0.001, 0.0)
                for i in range(segments + 1):
                    a = (i / segments) * (2.0 * math.pi)
                    u = 0.5 + 0.48 * math.cos(a)
                    v = 0.5 + 0.48 * math.sin(a)
                    glTexCoord2f(u, v)
                    glVertex3f(math.cos(a) * inner_radius, y0 -
                               0.001, math.sin(a) * inner_radius)
                glEnd()

                glBindTexture(GL_TEXTURE_2D, 0)
                glDisable(GL_TEXTURE_2D)
            else:
                glBegin(GL_TRIANGLE_FAN)
                glVertex3f(0.0, y1, 0.0)
                for i in range(segments + 1):
                    a = (i / segments) * (2.0 * math.pi)
                    glVertex3f(math.cos(a) * radius, y1, math.sin(a) * radius)
                glEnd()

                glBegin(GL_TRIANGLE_FAN)
                glVertex3f(0.0, y0, 0.0)
                for i in range(segments + 1):
                    a = (i / segments) * (2.0 * math.pi)
                    glVertex3f(math.cos(a) * radius, y0, math.sin(a) * radius)
                glEnd()

            glPointSize(1.5)
            glBegin(GL_POINTS)
            glVertex3f(0.0, y1, 0.0)  # Front center
            glVertex3f(0.0, y0, 0.0)  # Back center
            glEnd()

        def _draw_ghost_3d(color: Tuple[float, float, float, float]) -> None:
            from OpenGL.GL import GL_TRIANGLE_STRIP
            radius = 0.20
            segments = 26 if self._fast_mode else 40
            body_layers = 11
            tail_layers = 8

            glColor4f(*color)

            for layer in range(1, body_layers):
                layer_ratio = layer / (body_layers - 1)
                prev_ratio = (layer - 1) / (body_layers - 1)

                def y_and_r(t: float) -> Tuple[float, float]:
                    if t < 0.5:
                        yv = radius * 0.62 * math.cos(t * math.pi)
                        rv = radius * 0.95 * math.sin(t * math.pi)
                    else:
                        yv = -radius * 0.25 * (t - 0.5) * 2.0
                        rv = radius * 0.95
                    return yv, rv

                y_prev, r_prev = y_and_r(prev_ratio)
                y_curr, r_curr = y_and_r(layer_ratio)

                glBegin(GL_TRIANGLE_STRIP)
                for i in range(segments + 1):
                    a = (i / segments) * (2.0 * math.pi)
                    ca = math.cos(a)
                    sa = math.sin(a)
                    glVertex3f(ca * r_prev, y_prev, sa * r_prev)
                    glVertex3f(ca * r_curr, y_curr, sa * r_curr)
                glEnd()

            # Wavy tail
            for layer in range(tail_layers):
                layer_ratio = layer / tail_layers
                prev_ratio = (layer - 1) / tail_layers

                base_r = radius * 0.95 * (1.0 - layer_ratio * 0.35)
                wave_amp = radius * (0.08 + 0.14 * layer_ratio)
                y_curr = -radius * 0.52 - layer_ratio * radius * 0.48

                if layer == 0:
                    # Connect tail to body
                    glBegin(GL_TRIANGLE_STRIP)
                    for i in range(segments + 1):
                        a = (i / segments) * (2.0 * math.pi)
                        ca = math.cos(a)
                        sa = math.sin(a)
                        skirt = (
                            math.sin(a * 3.0 + self._anim_t *
                                     2.4 + layer * 0.55) * wave_amp
                            + math.sin(a * 7.0 - self._anim_t * 1.7 +
                                       layer * 0.35) * (wave_amp * 0.55)
                        )
                        r_curr = max(radius * 0.02, base_r + skirt)
                        glVertex3f(ca * radius * 0.95, -radius *
                                   0.25, sa * radius * 0.95)
                        glVertex3f(ca * r_curr, y_curr, sa * r_curr)
                    glEnd()
                else:
                    prev_base_r = radius * 0.95 * (1.0 - prev_ratio * 0.35)
                    prev_amp = radius * (0.08 + 0.14 * prev_ratio)
                    y_prev = -radius * 0.52 - prev_ratio * radius * 0.48

                    glBegin(GL_TRIANGLE_STRIP)
                    for i in range(segments + 1):
                        a = (i / segments) * (2.0 * math.pi)
                        ca = math.cos(a)
                        sa = math.sin(a)
                        skirt_prev = (
                            math.sin(a * 3.0 + self._anim_t * 2.4 +
                                     (layer - 1) * 0.55) * prev_amp
                            + math.sin(a * 7.0 - self._anim_t * 1.7 +
                                       (layer - 1) * 0.35) * (prev_amp * 0.55)
                        )
                        skirt_curr = (
                            math.sin(a * 3.0 + self._anim_t *
                                     2.4 + layer * 0.55) * wave_amp
                            + math.sin(a * 7.0 - self._anim_t * 1.7 +
                                       layer * 0.35) * (wave_amp * 0.55)
                        )
                        r_prev = max(radius * 0.02, prev_base_r + skirt_prev)
                        r_curr = max(radius * 0.02, base_r + skirt_curr)
                        glVertex3f(ca * r_prev, y_prev, sa * r_prev)
                        glVertex3f(ca * r_curr, y_curr, sa * r_curr)
                    glEnd()

            # Eyes on the "front" (local +Z)
            glColor4f(0.06, 0.06, 0.08, 0.96)
            eye_y = radius * 0.22
            eye_z = radius * 1.05
            eye_x = radius * 0.34
            ew = radius * 0.22
            eh = radius * 0.28
            glBegin(GL_QUADS)
            glVertex3f(-eye_x - ew, eye_y - eh, eye_z)
            glVertex3f(-eye_x + ew, eye_y - eh, eye_z)
            glVertex3f(-eye_x + ew, eye_y + eh, eye_z)
            glVertex3f(-eye_x - ew, eye_y + eh, eye_z)
            glVertex3f(eye_x - ew, eye_y - eh, eye_z)
            glVertex3f(eye_x + ew, eye_y - eh, eye_z)
            glVertex3f(eye_x + ew, eye_y + eh, eye_z)
            glVertex3f(eye_x - ew, eye_y + eh, eye_z)
            glEnd()

        # Animation constants
        TWO_PI = 6.283185307179586
        RAD_TO_DEG = 57.29577951308232

        px = float(self.core.player.x)
        pz = float(self.core.player.z)

        entity_draw_radius = max(18.0, float(self._fog_end) - 2.0)
        entity_r2 = entity_draw_radius * entity_draw_radius

        # Coins: 3D spinning coins (Mario-style) - clean and optimal
        for coin in self.core.coins.values():
            if coin.taken:
                continue

            # Simple direct animation
            r, c = coin.cell
            cx = c + 0.5
            cz = r + 0.5

            dx = float(cx) - px
            dz = float(cz) - pz
            if dx * dx + dz * dz > entity_r2:
                continue

            # Direct animation calculation
            anim_time = self._anim_t
            spin = (anim_time * 3.0) % TWO_PI
            spin_degrees = spin * RAD_TO_DEG

            # Bob animation
            bob = 0.06 * math.sin(anim_time * 1.6 + (r * 0.37 + c * 0.51))

            glPushMatrix()
            glTranslatef(cx, 1.22 + bob, cz)

            # Simple rotation
            glRotatef(spin_degrees, 0.0, 1.0, 0.0)
            glRotatef(90.0, 1.0, 0.0, 0.0)

            # Draw coin with texture on front/back faces
            glDisable(GL_LIGHTING)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glColor4f(1.0, 0.84, 0.18, 0.98)
            _draw_coin_3d_mario(radius=0.14, thickness=0.04,
                                segments=24, textured=True)

            glColor4f(1.0, 1.0, 1.0, 1.0)

            glPopMatrix()

            # Glow around the coin only (seamless circle, no floor spill)
            pulse = 0.16 + 0.06 * \
                math.sin(anim_time * 2.2 + (r * 0.17 + c * 0.23))
            radial_sprite_glow(cx, 1.22 + bob, cz, 0.34,
                               (1.0, 0.90, 0.35), pulse)

        def _draw_letter(letter: str) -> None:
            glBegin(GL_LINES)
            if letter == 'A':
                glVertex3f(-0.10, -0.08, 0.0)
                glVertex3f(0.0, 0.10, 0.0)
                glVertex3f(0.0, 0.10, 0.0)
                glVertex3f(0.10, -0.08, 0.0)
                glVertex3f(-0.06, 0.00, 0.0)
                glVertex3f(0.06, 0.00, 0.0)
            elif letter == 'B':
                glVertex3f(-0.10, -0.10, 0.0)
                glVertex3f(-0.10, 0.10, 0.0)
                glVertex3f(-0.10, 0.10, 0.0)
                glVertex3f(0.06, 0.06, 0.0)
                glVertex3f(0.06, 0.06, 0.0)
                glVertex3f(-0.10, 0.00, 0.0)
                glVertex3f(-0.10, 0.00, 0.0)
                glVertex3f(0.06, -0.04, 0.0)
                glVertex3f(0.06, -0.04, 0.0)
                glVertex3f(-0.10, -0.10, 0.0)
            elif letter == 'C':
                glVertex3f(0.08, 0.08, 0.0)
                glVertex3f(-0.08, 0.08, 0.0)
                glVertex3f(-0.08, 0.08, 0.0)
                glVertex3f(-0.10, 0.00, 0.0)
                glVertex3f(-0.10, 0.00, 0.0)
                glVertex3f(-0.08, -0.08, 0.0)
                glVertex3f(-0.08, -0.08, 0.0)
                glVertex3f(0.08, -0.08, 0.0)
            elif letter == 'D':
                glVertex3f(-0.10, -0.10, 0.0)
                glVertex3f(-0.10, 0.10, 0.0)
                glVertex3f(-0.10, 0.10, 0.0)
                glVertex3f(0.06, 0.06, 0.0)
                glVertex3f(0.06, 0.06, 0.0)
                glVertex3f(0.06, -0.06, 0.0)
                glVertex3f(0.06, -0.06, 0.0)
                glVertex3f(-0.10, -0.10, 0.0)
            elif letter == 'E':
                glVertex3f(0.08, 0.10, 0.0)
                glVertex3f(-0.10, 0.10, 0.0)
                glVertex3f(-0.10, 0.10, 0.0)
                glVertex3f(-0.10, -0.10, 0.0)
                glVertex3f(-0.10, 0.00, 0.0)
                glVertex3f(0.04, 0.00, 0.0)
                glVertex3f(-0.10, -0.10, 0.0)
                glVertex3f(0.08, -0.10, 0.0)
            elif letter == 'F':
                glVertex3f(0.08, 0.10, 0.0)
                glVertex3f(-0.10, 0.10, 0.0)
                glVertex3f(-0.10, 0.10, 0.0)
                glVertex3f(-0.10, -0.10, 0.0)
                glVertex3f(-0.10, 0.00, 0.0)
                glVertex3f(0.04, 0.00, 0.0)
            elif letter == 'G':
                glVertex3f(0.08, 0.08, 0.0)
                glVertex3f(-0.08, 0.08, 0.0)
                glVertex3f(-0.08, 0.08, 0.0)
                glVertex3f(-0.10, 0.00, 0.0)
                glVertex3f(-0.10, 0.00, 0.0)
                glVertex3f(-0.08, -0.08, 0.0)
                glVertex3f(-0.08, -0.08, 0.0)
                glVertex3f(0.08, -0.08, 0.0)
                glVertex3f(0.08, -0.08, 0.0)
                glVertex3f(0.08, 0.00, 0.0)
                glVertex3f(0.08, 0.00, 0.0)
                glVertex3f(0.00, 0.00, 0.0)
            elif letter == 'H':
                glVertex3f(-0.10, -0.10, 0.0)
                glVertex3f(-0.10, 0.10, 0.0)
                glVertex3f(0.10, -0.10, 0.0)
                glVertex3f(0.10, 0.10, 0.0)
                glVertex3f(-0.10, 0.00, 0.0)
                glVertex3f(0.10, 0.00, 0.0)
            elif letter == 'J':
                glVertex3f(-0.04, 0.10, 0.0)
                glVertex3f(0.10, 0.10, 0.0)
                glVertex3f(0.06, 0.10, 0.0)
                glVertex3f(0.06, -0.04, 0.0)
                glVertex3f(0.06, -0.04, 0.0)
                glVertex3f(0.00, -0.10, 0.0)
                glVertex3f(0.00, -0.10, 0.0)
                glVertex3f(-0.06, -0.04, 0.0)
            elif letter == 'X':
                glVertex3f(-0.10, -0.10, 0.0)
                glVertex3f(0.10, 0.10, 0.0)
                glVertex3f(-0.10, 0.10, 0.0)
                glVertex3f(0.10, -0.10, 0.0)
            glEnd()

        # Wall-mounted sector signs + jail painting
        def _wall_quad(cx: float, cy: float, cz: float, w: float, h: float, facing: str) -> None:
            if facing == 'N':
                z = cz - 0.49
                glVertex3f(cx - w, cy + h, z)
                glVertex3f(cx + w, cy + h, z)
                glVertex3f(cx + w, cy - h, z)
                glVertex3f(cx - w, cy - h, z)
                return
            if facing == 'S':
                z = cz + 0.49
                glVertex3f(cx + w, cy + h, z)
                glVertex3f(cx - w, cy + h, z)
                glVertex3f(cx - w, cy - h, z)
                glVertex3f(cx + w, cy - h, z)
                return
            if facing == 'W':
                x = cx - 0.49
                glVertex3f(x, cy + h, cz + w)
                glVertex3f(x, cy + h, cz - w)
                glVertex3f(x, cy - h, cz - w)
                glVertex3f(x, cy - h, cz + w)
                return
            x = cx + 0.49
            glVertex3f(x, cy + h, cz - w)
            glVertex3f(x, cy + h, cz + w)
            glVertex3f(x, cy - h, cz + w)
            glVertex3f(x, cy - h, cz - w)

        sector_signs = getattr(self.core, 'sector_signs', None) or {}
        if sector_signs:
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            for sid, (cell, facing) in sector_signs.items():
                r, c = cell
                cx = c + 0.5
                cz = r + 0.5
                cy = 1.65
                glColor4f(0.10, 0.10, 0.12, 0.92)
                glBegin(GL_QUADS)
                _wall_quad(cx, cy, cz, 0.48, 0.18, facing)
                glEnd()

                label = f"SECTOR {str(sid)[:1]}"
                tex = self._get_text_texture(label)
                if tex:
                    glEnable(GL_TEXTURE_2D)
                    glBindTexture(GL_TEXTURE_2D, int(tex))
                    glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
                    glColor4f(1.0, 1.0, 1.0, 0.98)
                    tw = 0.42
                    th = 0.11
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
                        # Match _wall_quad('S') corner ordering so text is not mirrored.
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
                        # Match _wall_quad('W') corner ordering so text is not mirrored.
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
                        # Match _wall_quad('E') corner ordering so text is not mirrored.
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

        painting = getattr(self.core, 'jail_painting', None)
        if painting:
            (pr, pc), facing = painting
            cx = pc + 0.5
            cz = pr + 0.5
            cy = 1.55

            # Shift the painting along the wall away from corners to avoid being clipped.
            dr, dc = (0, 0)
            if facing == 'N':
                dr, dc = (-1, 0)
            elif facing == 'S':
                dr, dc = (1, 0)
            elif facing == 'W':
                dr, dc = (0, -1)
            else:
                dr, dc = (0, 1)
            wr, wc = pr + dr, pc + dc
            if (wr, wc) in getattr(self.core, 'walls', set()):
                neg = 0
                pos = 0
                if facing in ('N', 'S'):
                    cc2 = wc - 1
                    while (wr, cc2) in self.core.walls:
                        neg += 1
                        cc2 -= 1
                    cc2 = wc + 1
                    while (wr, cc2) in self.core.walls:
                        pos += 1
                        cc2 += 1
                    shift = max(-0.28, min(0.28, (pos - neg) * 0.12))
                    cx += shift
                else:
                    rr2 = wr - 1
                    while (rr2, wc) in self.core.walls:
                        neg += 1
                        rr2 -= 1
                    rr2 = wr + 1
                    while (rr2, wc) in self.core.walls:
                        pos += 1
                        rr2 += 1
                    shift = max(-0.28, min(0.28, (pos - neg) * 0.12))
                    cz += shift

            # Frame
            glColor4f(0.30, 0.20, 0.10, 1.0)
            glBegin(GL_QUADS)
            _wall_quad(cx, cy, cz, 0.78, 0.50, facing)
            glEnd()

            # Canvas background
            glColor4f(0.08, 0.08, 0.10, 0.98)
            glBegin(GL_QUADS)
            _wall_quad(cx, cy, cz, 0.72, 0.44, facing)
            glEnd()

            tex = self._get_jail_map_texture()
            if tex:
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, int(tex))
                glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
                glColor4f(1.0, 1.0, 1.0, 0.98)
                tw = 0.70
                th = 0.41
                glBegin(GL_QUADS)
                if facing == 'N':
                    z = cz - 0.473
                    # Using vertically mirrored upload; top should use v=1.
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

        # Key fragments: 3D keys with bob + spin (coin-like)
        def _draw_key_3d() -> None:
            # Model space: centered around origin. Y is up.
            # Ring (handle): simple flat loop built from quads (no GLU dependency).
            glPushMatrix()
            glTranslatef(0.23, 0.06, 0.0)
            outer_r = 0.16
            inner_r = 0.11
            thickness = 0.035
            seg = 24
            TWO_PI = 6.283185307179586
            glBegin(GL_QUADS)
            for i in range(seg):
                a0 = TWO_PI * (i / seg)
                a1 = TWO_PI * ((i + 1) / seg)
                c0 = math.cos(a0)
                s0 = math.sin(a0)
                c1 = math.cos(a1)
                s1 = math.sin(a1)

                # Outer wall
                glVertex3f(outer_r * c0, -thickness, outer_r * s0)
                glVertex3f(outer_r * c1, -thickness, outer_r * s1)
                glVertex3f(outer_r * c1, +thickness, outer_r * s1)
                glVertex3f(outer_r * c0, +thickness, outer_r * s0)

                # Inner wall
                glVertex3f(inner_r * c1, -thickness, inner_r * s1)
                glVertex3f(inner_r * c0, -thickness, inner_r * s0)
                glVertex3f(inner_r * c0, +thickness, inner_r * s0)
                glVertex3f(inner_r * c1, +thickness, inner_r * s1)

                # Front face
                glVertex3f(inner_r * c0, +thickness, inner_r * s0)
                glVertex3f(inner_r * c1, +thickness, inner_r * s1)
                glVertex3f(outer_r * c1, +thickness, outer_r * s1)
                glVertex3f(outer_r * c0, +thickness, outer_r * s0)

                # Back face
                glVertex3f(outer_r * c0, -thickness, outer_r * s0)
                glVertex3f(outer_r * c1, -thickness, outer_r * s1)
                glVertex3f(inner_r * c1, -thickness, inner_r * s1)
                glVertex3f(inner_r * c0, -thickness, inner_r * s0)
            glEnd()
            glPopMatrix()

            # Shaft (thin box)
            glPushMatrix()
            glTranslatef(-0.12, 0.06, 0.0)
            glScalef(0.52, 0.06, 0.08)
            self._draw_untextured_cube()
            glPopMatrix()

            # Teeth (2-3 small boxes)
            for tx, th in ((-0.34, 0.12), (-0.25, 0.09), (-0.18, 0.07)):
                glPushMatrix()
                glTranslatef(tx, 0.02, 0.0)
                glScalef(0.06, th, 0.08)
                self._draw_untextured_cube()
                glPopMatrix()

        for frag in self.core.key_fragments.values():
            if frag.taken:
                continue

            r, c = frag.cell
            cx = c + 0.5
            cz = r + 0.5

            dx = float(cx) - px
            dz = float(cz) - pz
            if dx * dx + dz * dz > entity_r2:
                continue

            if frag.kind == 'KH':
                base = (0.55, 0.95, 1.0, 0.95)
                glow_rgb = (0.65, 1.0, 1.0)
            elif frag.kind == 'KP':
                base = (0.9, 0.65, 1.0, 0.95)
                glow_rgb = (0.95, 0.75, 1.0)
            else:
                base = (0.75, 1.0, 0.65, 0.95)
                glow_rgb = (0.85, 1.0, 0.75)

            # KP stays near ceiling; others float at normal height.
            if frag.kind == 'KP':
                base_y = float(self.core.ceiling_height) - 0.85
            else:
                base_y = 1.18

            # frag.id is a string (e.g. "frag_kh"); derive a stable numeric seed for animation.
            seed = float(sum((i + 1) * ord(ch)
                         for i, ch in enumerate(str(getattr(frag, 'id', '')))) % 997)
            bob = 0.08 * math.sin(self._anim_t * 2.4 + seed)
            spin_degrees = (self._anim_t * 140.0 + seed * 37.0) % 360.0

            glPushMatrix()
            glTranslatef(cx, base_y + bob, cz)
            glRotatef(spin_degrees, 0.0, 1.0, 0.0)
            glRotatef(90.0, 0.0, 0.0, 1.0)
            glScalef(1.05, 1.05, 1.05)

            glDisable(GL_LIGHTING)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glColor4f(base[0], base[1], base[2], base[3])
            _draw_key_3d()

            # Soft glow aura
            soft_aura(cx, base_y + bob + 0.05, cz, 0.55, glow_rgb, 0.12)

            glPopMatrix()

        # Checkpoint arrow: green arrow pointing down, visible through walls
        if self.core.checkpoint_arrow and self.core.checkpoint_arrow.visible:
            r, c = self.core.checkpoint_arrow.cell
            cx = c + 0.5
            cz = r + 0.5
            bob_offset = self.core.checkpoint_arrow.bob_offset

            # Arrow height - floats lower above ground with bobbing
            arrow_y = 1.8 + bob_offset  # Lowered from 2.5 for better visibility

            # Draw arrow as a green downward-pointing triangle
            glDisable(GL_DEPTH_TEST)  # Make visible through walls
            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
            glDepthMask(False)

            # Arrow glow effect - follow arrow shape (triangle pointing down)
            # Large glow triangle
            billboard_quad(cx, arrow_y + 0.1, cz, 1.0,
                           0.8, (0.2, 1.0, 0.2, 0.2))
            # Medium glow triangle
            billboard_quad(cx, arrow_y, cz, 0.8, 0.6, (0.3, 1.0, 0.3, 0.3))

            # Main arrow body - bright green triangle pointing down
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

            # Draw arrow as triangle shape using multiple quads to form a downward arrow
            # Arrow shaft (longer vertical rectangle)
            billboard_quad(cx, arrow_y, cz, 0.3, 0.8, (0.2, 1.0, 0.2, 0.9))

            # Arrow head (wider at bottom, triangular shape)
            billboard_quad(cx, arrow_y - 0.3, cz, 0.6,
                           0.3, (0.2, 1.0, 0.2, 0.9))

            # Arrow tip (point at bottom)
            billboard_quad(cx, arrow_y - 0.5, cz, 0.2,
                           0.2, (0.1, 0.8, 0.1, 1.0))

            glDepthMask(True)
            glEnable(GL_DEPTH_TEST)

        # Spikes
        if getattr(self.core, 'spikes', None):
            h = 0.0
            if hasattr(self.core, 'spike_height_factor'):
                h = float(self.core.spike_height_factor())
            for s in self.core.spikes:
                r, c = s.cell
                glPushMatrix()
                glTranslatef(c + 0.5, 0.0, r + 0.5)
                if s.active:
                    glColor4f(0.85, 0.15, 0.15, 1.0)
                else:
                    glColor4f(0.45, 0.12, 0.12, 1.0)
                self._draw_spike(height=0.85 * h)
                glPopMatrix()

        # Gates
        for gate in self.core.gates.values():
            self._draw_gate(gate)

        # Platforms
        for platform in getattr(self.core, 'platforms', []):
            self._draw_platform(platform)

        # Jail table + book (visual cue for interactable)
        if getattr(self.core, 'jail_book_cell', None):
            jr, jc = self.core.jail_book_cell
            glPushMatrix()
            glTranslatef(jc + 0.5, 0.0, jr + 0.5)
            # Table
            glColor4f(0.35, 0.22, 0.10, 1.0)
            glPushMatrix()
            glTranslatef(0.0, 0.40, 0.0)
            glScalef(0.85, 0.08, 0.60)
            self._draw_untextured_cube()
            glPopMatrix()
            # Legs
            for lx in (-0.35, 0.35):
                for lz in (-0.22, 0.22):
                    glPushMatrix()
                    glTranslatef(lx, 0.20, lz)
                    glScalef(0.08, 0.40, 0.08)
                    self._draw_untextured_cube()
                    glPopMatrix()

            # Book
            glColor4f(0.12, 0.12, 0.14, 1.0)
            glPushMatrix()
            glTranslatef(0.0, 0.48, 0.0)
            glScalef(0.28, 0.04, 0.20)
            self._draw_untextured_cube()
            glPopMatrix()
            # Book glow marker
            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
            glDepthMask(False)
            radial_sprite_glow(0.0, 0.70, 0.0, 0.55, (0.95, 0.85, 0.35), 0.16)
            radial_sprite_glow(0.0, 0.70, 0.0, 0.95, (0.95, 0.85, 0.35), 0.06)
            glDepthMask(True)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glPopMatrix()

        # Ghosts
        ghost_colors = {
            1: (1.0, 0.35, 0.20, 0.82),
            2: (0.30, 1.0, 0.55, 0.82),
            3: (0.45, 0.65, 1.0, 0.82),
            4: (1.0, 0.85, 0.25, 0.82),
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
            # In our coordinate convention yaw=0 means +Z. glRotatef expects degrees.
            glRotatef(math.degrees(g.yaw), 0.0, 1.0, 0.0)
            # Wider + taller silhouette
            glScalef(2.10 * s, 2.75 * s, 2.10 * s)

            glDepthMask(False)
            _draw_ghost_3d(ghost_colors.get(g.id, (1.0, 0.55, 0.15, 0.92)))
            glDepthMask(True)

            glPopMatrix()

            col = ghost_colors.get(g.id, (1.0, 0.55, 0.15, 0.92))
            radial_sprite_glow(g.x, 1.15 + y_raise + bob + 0.08,
                               g.z, 0.55 * s, (col[0], col[1], col[2]), 0.12)
            radial_sprite_glow(g.x, 1.15 + y_raise + bob + 0.08,
                               g.z, 0.95 * s, (col[0], col[1], col[2]), 0.05)

        ceil_h = float(self.core.ceiling_height)

        def is_floor(rr: int, cc: int) -> bool:
            return (rr, cc) in self.core.floors and (rr, cc) not in self.core.walls

        # Corridor-center lamps (for 3-wide corridors, place on the middle tile).
        # We sample candidates and then thin them out by spacing.
        lamp_candidates: list[Tuple[int, int]] = []
        for (r, c) in self.core.floors:
            if (r, c) in self.core.walls:
                continue

            # East-west 3-wide corridor: floor strip across width, walls beyond.
            if is_floor(r, c - 1) and is_floor(r, c + 1) and (not is_floor(r, c - 2)) and (not is_floor(r, c + 2)):
                lamp_candidates.append((r, c))
                continue

            # North-south 3-wide corridor.
            if is_floor(r - 1, c) and is_floor(r + 1, c) and (not is_floor(r - 2, c)) and (not is_floor(r + 2, c)):
                lamp_candidates.append((r, c))

        lamp_candidates.sort()
        lamps: list[Tuple[int, int]] = []
        min_sep2 = 8.0 * 8.0
        for rc in lamp_candidates:
            if all(((rc[0] - lr) ** 2 + (rc[1] - lc) ** 2) >= min_sep2 for (lr, lc) in lamps):
                lamps.append(rc)
            if len(lamps) >= 140:
                break

        for r, c in lamps:
            cx = c + 0.5
            cz = r + 0.5

            # Hanging lamp: small stem + shade + bulb
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

            # Circular pool of light on the floor (like screenshot)
            floor_glow(cx, cz, 0.015, 1.75, (0.98, 0.95, 0.82), 0.20)
            floor_glow(cx, cz, 0.016, 0.85, (0.98, 0.95, 0.82), 0.22)
            soft_aura(cx, ceil_h - 0.45, cz, 1.10, (0.98, 0.95, 0.82), 0.08)

        glEnable(GL_TEXTURE_2D)
        glEnable(GL_LIGHTING)

    def _draw_gate(self, gate) -> None:
        wall_h = float(self.core.wall_height)
        for (r, c) in gate.cells:
            glPushMatrix()
            glTranslatef(c + 0.5, wall_h / 2.0 + gate.y_offset, r + 0.5)
            glScalef(1.0, wall_h, 1.0)
            # Metallic bars
            glColor4f(0.7, 0.7, 0.75, 1.0)  # Metallic silver-gray
            self._draw_gate_bars(gate.id)
            glPopMatrix()

    def _draw_gate_bars(self, gate_id: str) -> None:
        if gate_id == 'jail':
            for i in range(-2, 3):
                x = i * 0.18
                glPushMatrix()
                glTranslatef(x, 0.0, 0.0)
                glScalef(0.07, 1.0, 0.12)
                self._draw_untextured_cube()
                glPopMatrix()
        else:
            for i in range(-2, 3):
                z = i * 0.18
                glPushMatrix()
                glTranslatef(0.0, 0.0, z)
                glRotatef(90, 0.0, 1.0, 0.0)
                glScalef(0.07, 1.0, 0.12)
                self._draw_untextured_cube()
                glPopMatrix()

        # top for gate
        glPushMatrix()
        glTranslatef(0.0, 0.42, 0.0)
        glColor4f(0.65, 0.65, 0.7, 1.0)
        if gate_id == 'jail':
            glScalef(0.95, 0.12, 0.16)
        else:
            glRotatef(90, 0.0, 1.0, 0.0)
            glScalef(0.95, 0.12, 0.16)
        self._draw_untextured_cube()
        glPopMatrix()

    def _draw_ghost_blob(self) -> None:
        glPushMatrix()
        glScalef(0.55, 0.9, 0.35)
        self._draw_untextured_cube()
        glPopMatrix()
        for i in (-1, 0, 1):
            glPushMatrix()
            glTranslatef(i * 0.18, -0.52, 0.0)
            glScalef(0.16, 0.22, 0.22)
            self._draw_untextured_cube()
            glPopMatrix()

    def _draw_platform(self, platform) -> None:
        r, c = platform.cell
        glPushMatrix()
        glTranslatef(c + 0.5, platform.y_offset + 0.05, r + 0.5)

        # platform surface
        glColor4f(0.6, 0.4, 0.2, 1.0)
        glPushMatrix()
        glScalef(0.8, 0.1, 0.8)
        self._draw_untextured_cube()
        glPopMatrix()

        # úlatform edges/ rails
        glColor4f(0.4, 0.3, 0.15, 1.0)
        # Front edge
        glPushMatrix()
        glTranslatef(0.0, 0.15, 0.35)
        glScalef(0.82, 0.2, 0.05)
        self._draw_untextured_cube()
        glPopMatrix()
        # Back edge
        glPushMatrix()
        glTranslatef(0.0, 0.15, -0.35)
        glScalef(0.82, 0.2, 0.05)
        self._draw_untextured_cube()
        glPopMatrix()
        # left edge
        glPushMatrix()
        glTranslatef(-0.35, 0.15, 0.0)
        glScalef(0.05, 0.2, 0.82)
        self._draw_untextured_cube()
        glPopMatrix()
        # right edge
        glPushMatrix()
        glTranslatef(0.35, 0.15, 0.0)
        glScalef(0.05, 0.2, 0.82)
        self._draw_untextured_cube()
        glPopMatrix()

        glPopMatrix()

    def _draw_spike(self, height: float) -> None:
        if height <= 0.02:
            return
        base = 0.18
        glBegin(GL_QUADS)
        # base plate
        glVertex3f(-base, 0.01, -base)
        glVertex3f(base, 0.01, -base)
        glVertex3f(base, 0.01, base)
        glVertex3f(-base, 0.01, base)
        glEnd()
        # four sides
        from OpenGL.GL import GL_TRIANGLES
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

    def _draw_billboard_disc(self, radius: float) -> None:
        glDisable(GL_TEXTURE_2D)
        glBegin(GL_QUADS)
        glVertex3f(-radius, -radius, 0.0)
        glVertex3f(radius, -radius, 0.0)
        glVertex3f(radius, radius, 0.0)
        glVertex3f(-radius, radius, 0.0)
        glEnd()
        glBegin(GL_QUADS)
        glVertex3f(0.0, -radius, -radius)
        glVertex3f(0.0, -radius, radius)
        glVertex3f(0.0, radius, radius)
        glVertex3f(0.0, radius, -radius)
        glEnd()
        glEnable(GL_TEXTURE_2D)

    def _draw_floor_tile(self, tex_scale: float) -> None:
        glBegin(GL_QUADS)
        glTexCoord2f(0.0, 0.0)
        glVertex3f(-0.5, 0.0, -0.5)
        glTexCoord2f(tex_scale, 0.0)
        glVertex3f(0.5, 0.0, -0.5)
        glTexCoord2f(tex_scale, tex_scale)
        glVertex3f(0.5, 0.0, 0.5)
        glTexCoord2f(0.0, tex_scale)
        glVertex3f(-0.5, 0.0, 0.5)
        glEnd()

    def _draw_ceiling_tile(self, tex_scale: float) -> None:
        glBegin(GL_QUADS)
        glTexCoord2f(0.0, 0.0)
        glVertex3f(-0.5, 0.0, 0.5)
        glTexCoord2f(tex_scale, 0.0)
        glVertex3f(0.5, 0.0, 0.5)
        glTexCoord2f(tex_scale, tex_scale)
        glVertex3f(0.5, 0.0, -0.5)
        glTexCoord2f(0.0, tex_scale)
        glVertex3f(-0.5, 0.0, -0.5)
        glEnd()

    def _draw_textured_cube(self) -> None:
        # Texture wraps per face
        glBegin(GL_QUADS)
        # Front
        glTexCoord2f(0.0, 0.0)
        glVertex3f(-0.5, -0.5, 0.5)
        glTexCoord2f(1.0, 0.0)
        glVertex3f(0.5, -0.5, 0.5)
        glTexCoord2f(1.0, 1.0)
        glVertex3f(0.5, 0.5, 0.5)
        glTexCoord2f(0.0, 1.0)
        glVertex3f(-0.5, 0.5, 0.5)
        # Back
        glTexCoord2f(0.0, 0.0)
        glVertex3f(-0.5, -0.5, -0.5)
        glTexCoord2f(1.0, 0.0)
        glVertex3f(-0.5, 0.5, -0.5)
        glTexCoord2f(1.0, 1.0)
        glVertex3f(0.5, 0.5, -0.5)
        glTexCoord2f(0.0, 1.0)
        glVertex3f(0.5, -0.5, -0.5)
        # Right
        glTexCoord2f(0.0, 0.0)
        glVertex3f(0.5, -0.5, -0.5)
        glTexCoord2f(1.0, 0.0)
        glVertex3f(0.5, 0.5, -0.5)
        glTexCoord2f(1.0, 1.0)
        glVertex3f(0.5, 0.5, 0.5)
        glTexCoord2f(0.0, 1.0)
        glVertex3f(0.5, -0.5, 0.5)
        # Left
        glTexCoord2f(0.0, 0.0)
        glVertex3f(-0.5, -0.5, -0.5)
        glTexCoord2f(1.0, 0.0)
        glVertex3f(-0.5, -0.5, 0.5)
        glTexCoord2f(1.0, 1.0)
        glVertex3f(-0.5, 0.5, 0.5)
        glTexCoord2f(0.0, 1.0)
        glVertex3f(-0.5, 0.5, -0.5)
        # Top
        glTexCoord2f(0.0, 0.0)
        glVertex3f(-0.5, 0.5, -0.5)
        glTexCoord2f(1.0, 0.0)
        glVertex3f(-0.5, 0.5, 0.5)
        glTexCoord2f(1.0, 1.0)
        glVertex3f(0.5, 0.5, 0.5)
        glTexCoord2f(0.0, 1.0)
        glVertex3f(0.5, 0.5, -0.5)
        # Bottom
        glTexCoord2f(0.0, 0.0)
        glVertex3f(-0.5, -0.5, -0.5)
        glTexCoord2f(1.0, 0.0)
        glVertex3f(0.5, -0.5, -0.5)
        glTexCoord2f(1.0, 1.0)
        glVertex3f(0.5, -0.5, 0.5)
        glTexCoord2f(0.0, 1.0)
        glVertex3f(-0.5, -0.5, 0.5)
        glEnd()

    def _draw_untextured_cube(self) -> None:
        glDisable(GL_TEXTURE_2D)
        glBegin(GL_QUADS)
        # Front
        glVertex3f(-0.5, -0.5, 0.5)
        glVertex3f(0.5, -0.5, 0.5)
        glVertex3f(0.5, 0.5, 0.5)
        glVertex3f(-0.5, 0.5, 0.5)
        # Back
        glVertex3f(-0.5, -0.5, -0.5)
        glVertex3f(-0.5, 0.5, -0.5)
        glVertex3f(0.5, 0.5, -0.5)
        glVertex3f(0.5, -0.5, -0.5)
        # Top
        glVertex3f(-0.5, 0.5, -0.5)
        glVertex3f(-0.5, 0.5, 0.5)
        glVertex3f(0.5, 0.5, 0.5)
        glVertex3f(0.5, 0.5, -0.5)
        # Bottom
        glVertex3f(-0.5, -0.5, -0.5)
        glVertex3f(0.5, -0.5, -0.5)
        glVertex3f(0.5, -0.5, 0.5)
        glVertex3f(-0.5, -0.5, 0.5)
        # Right
        glVertex3f(0.5, -0.5, -0.5)
        glVertex3f(0.5, 0.5, -0.5)
        glVertex3f(0.5, 0.5, 0.5)
        glVertex3f(0.5, -0.5, 0.5)
        # Left
        glVertex3f(-0.5, -0.5, -0.5)
        glVertex3f(-0.5, -0.5, 0.5)
        glVertex3f(-0.5, 0.5, 0.5)
        glVertex3f(-0.5, 0.5, -0.5)
        glEnd()
        glEnable(GL_TEXTURE_2D)

    def _load_texture(self, path: str) -> Optional[int]:
        if not os.path.exists(path):
            return None
        img = QImage(path)
        if img.isNull():
            return None
        img = img.convertToFormat(QImage.Format_RGBA8888)
        w = img.width()
        h = img.height()
        ptr = img.bits()
        data = bytes(ptr[: w * h * 4])

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
        cached = self._text_texture_cache.get(text)
        if cached:
            return cached

        w, h = 256, 64
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        font = QFont('Arial', 28)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(255, 235, 120, 255))
        p.drawText(img.rect(), int(Qt.AlignmentFlag.AlignCenter), text)
        p.end()

        img = img.mirrored(False, True)

        ptr = img.constBits()
        size = int(img.sizeInBytes())
        if hasattr(ptr, 'tobytes'):
            data = ptr.tobytes()[:size]
        else:
            data = bytes(ptr)[:size]
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
            return int(self._jail_map_texture)

        grid_h = int(getattr(self.core, 'height', 0) or 0)
        grid_w = int(getattr(self.core, 'width', 0) or 0)
        if grid_h <= 0 or grid_w <= 0:
            return 0

        palette = {
            'A': QColor(80, 120, 200, 255),
            'B': QColor(180, 130, 80, 255),
            'C': QColor(80, 180, 100, 255),
            'D': QColor(110, 180, 180, 255),
            'E': QColor(180, 100, 140, 255),
            'F': QColor(180, 180, 90, 255),
            'G': QColor(160, 100, 190, 255),
            'H': QColor(150, 150, 150, 255),
        }

        w, h = 640, 420
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(QColor(50, 42, 36, 255))

        margin = 28
        cell_w = (w - margin * 2) / float(grid_w)
        cell_h = (h - margin * 2) / float(grid_h)
        cell = min(cell_w, cell_h)
        map_w = cell * grid_w
        map_h = cell * grid_h
        ox = (w - map_w) * 0.5
        oy = (h - map_h) * 0.5

        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        for rr in range(grid_h):
            for cc in range(grid_w):
                if (rr, cc) in self.core.walls:
                    continue
                sid = ''
                if hasattr(self.core, 'sector_id_for_cell'):
                    sid = self.core.sector_id_for_cell((rr, cc))
                color = palette.get(sid)
                if not color:
                    continue
                x0 = ox + cc * cell
                y0 = oy + rr * cell
                p.fillRect(int(x0), int(y0), int(
                    cell + 1), int(cell + 1), color)

        # Big sector letters at centroids.
        acc: dict[str, tuple[float, float, int]] = {}
        for rr in range(grid_h):
            for cc in range(grid_w):
                if (rr, cc) in self.core.walls:
                    continue
                sid = ''
                if hasattr(self.core, 'sector_id_for_cell'):
                    sid = self.core.sector_id_for_cell((rr, cc))
                if not sid:
                    continue
                if sid not in acc:
                    acc[sid] = (0.0, 0.0, 0)
                sx, sy, n = acc[sid]
                acc[sid] = (sx + float(rr), sy + float(cc), n + 1)

        p.setPen(QColor(10, 10, 12, 255))
        font_big = QFont('Arial', 52)
        font_big.setBold(True)
        p.setFont(font_big)
        for sid, (sx, sy, n) in acc.items():
            if n <= 0:
                continue
            cr = sx / n
            cc = sy / n
            px = ox + (cc + 0.5) * cell
            py = oy + (cr + 0.5) * cell
            p.drawText(int(px - 22), int(py + 22), sid[:1])

        # exit labels
        font_small = QFont('Arial', 22)
        font_small.setBold(True)
        p.setFont(font_small)
        if getattr(self.core, 'exit_cells', None):
            er, ec = self.core.exit_cells[0]
            px = ox + (ec + 0.5) * cell + 5
            py = oy + (er + 0.5) * cell
            box_w = 64
            box_h = 26
            p.fillRect(int(px - box_w / 2), int(py - box_h / 2),
                       box_w, box_h, QColor(210, 190, 175, 200))
            p.setPen(QColor(15, 15, 16, 255))
            p.drawText(int(px - box_w / 2) + 10, int(py + 9), 'exit')
            p.setPen(QColor(10, 10, 12, 255))

        p.end()

        img = img.mirrored(False, True)

        ptr = img.constBits()
        size = int(img.sizeInBytes())
        if hasattr(ptr, 'tobytes'):
            data = ptr.tobytes()[:size]
        else:
            data = bytes(ptr)[:size]

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

        self._jail_map_texture = int(tex_id)
        return int(tex_id)

    def _bind_texture(self, tex_id: Optional[int]) -> None:
        if tex_id is None:
            glBindTexture(GL_TEXTURE_2D, 0)
            return
        glBindTexture(GL_TEXTURE_2D, tex_id)
