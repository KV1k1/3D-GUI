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
        self.near_plane = 0.25
        self.far_plane = 80.0

        self.wall_color = (0.45, 0.45, 0.5, 1.0)
        self.floor_color = (0.25, 0.23, 0.22, 1.0)
        self.sky_color = (0.05, 0.05, 0.08, 1.0)

        self._tex_wall: Optional[int] = None
        self._tex_floor: Optional[int] = None

        self._static_quads: List[Tuple[float, float, Optional[int],
                                       Tuple[Tuple[float, float, float, float, float], ...]]] = []

        self._world_list_floor: Optional[int] = None
        self._world_list_wall: Optional[int] = None

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
        self._build_world_display_lists()

    def _delete_world_display_lists(self) -> None:
        if self._world_list_floor is not None:
            glDeleteLists(int(self._world_list_floor), 1)
            self._world_list_floor = None
        if self._world_list_wall is not None:
            glDeleteLists(int(self._world_list_wall), 1)
            self._world_list_wall = None

    def _build_world_display_lists(self) -> None:
        self._delete_world_display_lists()

        floor_id = glGenLists(1)
        wall_id = glGenLists(1)
        if floor_id == 0 or wall_id == 0:
            self._world_list_floor = None
            self._world_list_wall = None
            return

        self._world_list_floor = int(floor_id)
        self._world_list_wall = int(wall_id)

        glNewList(self._world_list_floor, GL_COMPILE)
        glEnable(GL_TEXTURE_2D)
        self._bind_texture(self._tex_floor)
        glColor4f(1.0, 1.0, 1.0, 1.0)
        glBegin(GL_QUADS)
        for _, _, tex_id, quad in self._static_quads:
            if tex_id != self._tex_floor:
                continue
            for (u, v, x, y, z) in quad:
                glTexCoord2f(u, v)
                glVertex3f(x, y, z)
        glEnd()
        glEndList()

        glNewList(self._world_list_wall, GL_COMPILE)
        glEnable(GL_TEXTURE_2D)
        self._bind_texture(self._tex_wall)
        glColor4f(1.0, 1.0, 1.0, 1.0)
        glBegin(GL_QUADS)
        for _, _, tex_id, quad in self._static_quads:
            if tex_id != self._tex_wall:
                continue
            for (u, v, x, y, z) in quad:
                glTexCoord2f(u, v)
                glVertex3f(x, y, z)
        glEnd()
        glEndList()

    def _draw_world_immediate(self) -> None:
        """Draw world geometry using immediate mode"""
        glDisable(GL_LIGHTING)
        glColor4f(1.0, 1.0, 1.0, 1.0)

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
        if self._world_list_floor is None or self._world_list_wall is None:
            self._draw_world_immediate()
            return

        glDisable(GL_LIGHTING)
        glColor4f(1.0, 1.0, 1.0, 1.0)
        glEnable(GL_TEXTURE_2D)
        glCallList(int(self._world_list_floor))
        glCallList(int(self._world_list_wall))
        self._bind_texture(None)
        glDisable(GL_TEXTURE_2D)
        glEnable(GL_LIGHTING)

    def resize(self, width: int, height: int) -> None:
        self.width = max(1, width)
        self.height = max(1, height)
        glViewport(0, 0, self.width, self.height)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(self.fov, self.width / self.height,
                       self.near_plane, self.far_plane)

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

        gluLookAt(px, py, pz, lx, ly, lz, 0.0, 1.0, 0.0)

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
            segments = 40
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

        # Coins: 3D spinning coins (Mario-style) - clean and optimal
        for coin in self.core.coins.values():
            if coin.taken:
                continue

            # Simple direct animation
            r, c = coin.cell
            cx = c + 0.5
            cz = r + 0.5

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

            # Glow effects - clean ground lighting only
            floor_glow(cx, cz, 0.015, 1.05, (1.0, 0.90, 0.35), 0.12)
            floor_glow(cx, cz, 0.016, 0.55, (1.0, 0.90, 0.35), 0.14)

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

        # Key fragments: glowing shards
        for frag in self.core.key_fragments.values():
            if frag.taken:
                continue
            r, c = frag.cell
            cx = c + 0.5
            cz = r + 0.5
            if frag.kind == 'KH':
                base = (0.55, 0.95, 1.0, 0.95)
                glow = (0.65, 1.0, 1.0, 0.22)
            elif frag.kind == 'KP':
                base = (0.9, 0.65, 1.0, 0.95)
                glow = (0.95, 0.75, 1.0, 0.22)
            else:
                base = (0.75, 1.0, 0.65, 0.95)
                glow = (0.85, 1.0, 0.75, 0.22)

            # Place KP fragment relative to the moving platform, others at normal height.
            if frag.kind == 'KP':
                fragment_y = float(self.core.ceiling_height) - 0.85
            else:
                fragment_y = 1.18  # Normal height

            billboard_quad(cx, fragment_y, cz, 0.34, 0.46, base)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
            glDepthMask(False)
            billboard_quad(cx, fragment_y, cz, 0.55, 0.70, glow)
            glDepthMask(True)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

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
            billboard_quad(0.0, 0.70, 0.0, 0.60, 0.60,
                           (0.95, 0.85, 0.35, 0.22))
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
            bob = 0.22 * math.sin(self._anim_t * 3.8 + g.id)
            wobble = 0.06 * math.sin(self._anim_t * 4.6 + g.id * 0.7)
            glPushMatrix()
            glTranslatef(g.x, 1.15 + bob + wobble, g.z)
            # In our coordinate convention yaw=0 means +Z. glRotatef expects degrees.
            glRotatef(math.degrees(g.yaw), 0.0, 1.0, 0.0)
            # Wider + taller silhouette
            glScalef(2.10, 2.75, 2.10)

            glDepthMask(False)
            _draw_ghost_3d(ghost_colors.get(g.id, (1.0, 0.55, 0.15, 0.92)))
            glDepthMask(True)

            glPopMatrix()

            col = ghost_colors.get(g.id, (1.0, 0.55, 0.15, 0.92))
            soft_aura(g.x, 1.15 + bob + 0.05, g.z, 0.70,
                      (col[0], col[1], col[2]), 0.14)

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
            'A': QColor(40, 70, 180, 255),
            'B': QColor(150, 95, 40, 255),
            'C': QColor(40, 150, 65, 255),
            'D': QColor(60, 150, 150, 255),
            'E': QColor(150, 60, 110, 255),
            'F': QColor(150, 150, 55, 255),
            'G': QColor(130, 60, 170, 255),
            'H': QColor(120, 120, 120, 255),
        }

        w, h = 640, 420
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(QColor(30, 22, 16, 255))

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

        # jail / exit labels
        font_small = QFont('Arial', 22)
        font_small.setBold(True)
        p.setFont(font_small)
        if getattr(self.core, 'jail_spawn_cell', None):
            jr, jc = self.core.jail_spawn_cell
            px = ox + (jc + 0.5) * cell
            py = oy + (jr + 0.5) * cell
            box_w = 70
            box_h = 26
            p.fillRect(int(px - box_w / 2), int(py - box_h / 2),
                       box_w, box_h, QColor(210, 190, 175, 200))
            p.setPen(QColor(15, 15, 16, 255))
            p.drawText(int(px - box_w / 2) + 10, int(py + 9), 'jail')
            p.setPen(QColor(10, 10, 12, 255))
        if getattr(self.core, 'exit_cells', None):
            er, ec = self.core.exit_cells[0]
            px = ox + (ec + 0.5) * cell
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
