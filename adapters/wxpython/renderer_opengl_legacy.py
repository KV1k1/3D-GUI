import ctypes
import math
import os
import time
from array import array
from typing import List, Optional, Tuple

import numpy as np
import wx
from OpenGL.GL import *
from OpenGL.GLU import gluLookAt, gluPerspective

from core.game_core import GameCore


class OpenGLRenderer:
    def __init__(self, core: GameCore):
        self.core = core
        self.width = 800
        self.height = 600
        self._assets_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', '..', 'assets'))
        self.camera_height = 1.6
        self.fov = 60.0
        self.near_plane = 0.15
        self.far_plane = 42.0

        self._anim_clock_s = 0.0
        self._last_anim_elapsed_s: Optional[float] = None
        self._last_anim_perf_s: Optional[float] = None

        self._fog_enabled = True
        self._fog_start = 22.0
        self._fog_end = 40.0

        self._fast_mode = True

        self.wall_color = (0.45, 0.45, 0.5, 1.0)
        self.floor_color = (0.25, 0.23, 0.22, 1.0)
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

        self._lamp_vbo: Optional[int] = None
        self._lamp_vertex_count: int = 0
        self._lamp_positions: List[Tuple[int, int]] = []

        self._coin_geom_vbo: Optional[int] = None
        self._coin_geom_vertex_count: int = 0
        self._coin_tex_vbo: Optional[int] = None
        self._coin_tex_vertex_count: int = 0
        self._glow_additive_vbo: Optional[int] = None
        self._glow_additive_vertex_count: int = 0
        self._spikes_vbo: Optional[int] = None
        self._spikes_vertex_count: int = 0
        self._platforms_vbo: Optional[int] = None
        self._platforms_vertex_count: int = 0
        self._gates_vbo: Optional[int] = None
        self._gates_vertex_count: int = 0
        self._key_fragments_vbo: Optional[int] = None
        self._key_fragments_vertex_count: int = 0
        self._ghosts_vbo: Optional[int] = None
        self._ghosts_vertex_count: int = 0

        self._text_texture_cache: dict[tuple, tuple[int, int, int]] = {}
        self._jail_map_texture: Optional[int] = None

        self._textures_loaded = False
        self._geometry_built = False

    def initialize(self) -> None:
        start_time = time.perf_counter()
        try:
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(GL_LEQUAL)
            glClearDepth(1.0)
            glDisable(GL_CULL_FACE)
            glEnable(GL_LIGHTING)
            glEnable(GL_TEXTURE_2D)

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
                glTexParameteri(
                    GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
                glTexParameteri(
                    GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
                glBindTexture(GL_TEXTURE_2D, 0)

            self._textures_loaded = True

            self._build_ghost_vbo()

            self._build_lamp_vbo()

            vbo = glGenBuffers(1)
            self._coin_geom_vbo = int(vbo) if vbo else None
            vbo = glGenBuffers(1)
            self._coin_tex_vbo = int(vbo) if vbo else None
            vbo = glGenBuffers(1)
            self._glow_additive_vbo = int(vbo) if vbo else None
            vbo = glGenBuffers(1)
            self._spikes_vbo = int(vbo) if vbo else None
            vbo = glGenBuffers(1)
            self._platforms_vbo = int(vbo) if vbo else None
            vbo = glGenBuffers(1)
            self._gates_vbo = int(vbo) if vbo else None
            vbo = glGenBuffers(1)
            self._key_fragments_vbo = int(vbo) if vbo else None
            vbo = glGenBuffers(1)
            self._ghosts_vbo = int(vbo) if vbo else None

        except Exception as e:
            print(f"wxPython renderer initialization error: {e}")
            import traceback
            traceback.print_exc()

        load_time = time.perf_counter() - start_time
        try:
            perf = getattr(self.core, '_performance_monitor', None)
            if perf:
                perf.record_texture_load_time(load_time * 1000)
            from core.pdf_export import get_system_collector
            collector = get_system_collector()
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

    def _ensure_textures_loaded(self) -> None:
        if self._textures_loaded:
            return

        start_time = time.perf_counter()

        wall_path = os.path.join(self._assets_dir, 'image.png')
        floor_path = os.path.join(self._assets_dir, 'path.png')
        coin_path = os.path.join(self._assets_dir, 'JEMA GER 1640-11.png')

        if os.path.exists(wall_path):
            self._tex_wall = self._load_texture(wall_path)
        if os.path.exists(floor_path):
            self._tex_floor = self._load_texture(floor_path)
        if os.path.exists(coin_path):
            self._tex_coin = self._load_texture(coin_path)

        if self._tex_coin is not None:
            glBindTexture(GL_TEXTURE_2D, int(self._tex_coin))
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            glBindTexture(GL_TEXTURE_2D, 0)

        self._textures_loaded = True

        self._build_ghost_vbo()

        self._build_lamp_vbo()

        load_time = time.perf_counter() - start_time
        try:
            perf = getattr(self.core, '_performance_monitor', None)
            if perf:
                perf.record_texture_load_time(load_time * 1000)
        except Exception:
            pass

    def _ensure_geometry_built(self) -> None:
        if self._geometry_built:
            return

        start_time = time.perf_counter()

        self._build_static_geometry()
        self._build_world_vbos()
        self._geometry_built = True

        build_time = time.perf_counter() - start_time
        if build_time > 1.0:
            print(f"Geometry built in {build_time:.2f}s")

    def _draw_gates(self) -> None:
        gates = getattr(self.core, 'gates', None) or {}
        if not gates:
            return
        for gate in gates.values():
            self._draw_gate(gate)

    def _draw_gate(self, gate) -> None:
        wall_h = float(getattr(self.core, 'wall_height', 2.8) or 2.8)
        y_off = float(getattr(gate, 'y_offset', 0.0) or 0.0)
        cells = list(getattr(gate, 'cells', []) or [])
        gid = str(getattr(gate, 'id', '') or '')
        glDisable(GL_TEXTURE_2D)
        glDisable(GL_LIGHTING)
        for (r, c) in cells:
            glPushMatrix()
            glTranslatef(float(c) + 0.5, wall_h / 2.0 + y_off, float(r) + 0.5)
            glScalef(1.0, wall_h, 1.0)
            glColor4f(0.7, 0.7, 0.75, 1.0)
            self._draw_gate_bars(gid)
            glPopMatrix()
        glEnable(GL_LIGHTING)
        glEnable(GL_TEXTURE_2D)

    def _draw_gate_bars(self, gate_id: str) -> None:
        if str(gate_id) == 'jail':
            for i in range(-2, 3):
                x = float(i) * 0.18
                glPushMatrix()
                glTranslatef(x, 0.0, 0.0)
                glScalef(0.07, 1.0, 0.12)
                self._draw_untextured_cube()
                glPopMatrix()
        else:
            for i in range(-2, 3):
                z = float(i) * 0.18
                glPushMatrix()
                glTranslatef(0.0, 0.0, z)
                glRotatef(90.0, 0.0, 1.0, 0.0)
                glScalef(0.07, 1.0, 0.12)
                self._draw_untextured_cube()
                glPopMatrix()

        glPushMatrix()
        glTranslatef(0.0, 0.42, 0.0)
        glColor4f(0.65, 0.65, 0.7, 1.0)
        if str(gate_id) == 'jail':
            glScalef(0.95, 0.12, 0.16)
        else:
            glRotatef(90.0, 0.0, 1.0, 0.0)
            glScalef(0.95, 0.12, 0.16)
        self._draw_untextured_cube()
        glPopMatrix()

    def _draw_jail_table_and_book(self, anim_t: float) -> None:
        if not getattr(self.core, 'jail_book_cell', None):
            return
        jr, jc = self.core.jail_book_cell
        glDisable(GL_TEXTURE_2D)
        glDisable(GL_LIGHTING)
        glPushMatrix()
        glTranslatef(float(jc) + 0.5, 0.0, float(jr) + 0.5)

        glColor4f(0.35, 0.22, 0.10, 1.0)
        glPushMatrix()
        glTranslatef(0.0, 0.40, 0.0)
        glScalef(0.85, 0.08, 0.60)
        self._draw_untextured_cube()
        glPopMatrix()
        for lx in (-0.35, 0.35):
            for lz in (-0.22, 0.22):
                glPushMatrix()
                glTranslatef(float(lx), 0.20, float(lz))
                glScalef(0.08, 0.40, 0.08)
                self._draw_untextured_cube()
                glPopMatrix()

        glColor4f(0.12, 0.12, 0.14, 1.0)
        glPushMatrix()
        glTranslatef(0.0, 0.48, 0.0)
        glScalef(0.28, 0.04, 0.20)
        self._draw_untextured_cube()
        glPopMatrix()

        glPopMatrix()
        glEnable(GL_LIGHTING)
        glEnable(GL_TEXTURE_2D)
        return

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
        self._ensure_textures_loaded()
        self._ensure_geometry_built()

        glEnable(GL_DEPTH_TEST)
        glEnable(GL_TEXTURE_2D)

        frozen = bool(getattr(self.core, 'simulation_frozen', False))

        now = time.perf_counter()
        if self._last_anim_perf_s is None:
            self._last_anim_perf_s = now
        dt_anim = max(0.0, float(now) - float(self._last_anim_perf_s))
        self._last_anim_perf_s = now
        if not frozen:
            self._anim_clock_s += dt_anim

        try:
            self._last_anim_elapsed_s = float(
                getattr(self.core, 'elapsed_s', 0.0) or 0.0)
        except Exception:
            pass

        anim_t = float(self._anim_clock_s)

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

        glDisable(GL_BLEND)  # Disable blend before 3D scene like PySide
        glDepthMask(True)
        self._draw_world()
        glEnable(GL_BLEND)  # Re-enable blend after 3D scene like PySide

        self._draw_coins(anim_t)

        self._draw_entities(anim_t)

        platform_buffer = self._build_platforms_buffer(anim_t)
        self._draw_platforms(platform_buffer)

        gate_buffer = self._build_gates_buffer(anim_t)
        self._draw_gates(gate_buffer)

        self._draw_jail_table_and_book(anim_t)

        self._draw_sector_signs_and_jail_painting()

        self._draw_ceiling_lamps()

        self._draw_checkpoint_arrow(anim_t)

    def _draw_checkpoint_arrow(self, anim_t: float) -> None:
        """Draw the green exit arrow: a 3D downward-pointing arrow visible through walls."""
        arrow = getattr(self.core, 'checkpoint_arrow', None)
        if arrow is None or not arrow.visible:
            return

        ar, ac = arrow.cell
        cx = float(ac) + 0.5
        cz = float(ar) + 0.5
        bounce = 0.08 * math.sin(anim_t * 2.5)  # Smooth bounce animation
        cy = float(getattr(self.core, 'wall_height', 3.0)) * 0.45 + bounce

        glDisable(GL_TEXTURE_2D)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        pulse = 0.75 + 0.25 * math.sin(anim_t * 3.0)

        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(False)

        yaw = float(self.core.player.yaw)
        rx = math.cos(yaw)
        rz = -math.sin(yaw)

        glow_radius = 1.5
        glow_alpha = 0.25 * pulse

        glColor4f(0.15, 1.0, 0.4, glow_alpha)
        glBegin(GL_TRIANGLE_FAN)
        glVertex3f(cx, cy, cz)
        glColor4f(0.15, 1.0, 0.4, 0.0)  # Edge fades to transparent
        steps = 48  # High segments for perfect circle
        for i in range(steps + 1):
            a = (i / steps) * 2.0 * math.pi
            x = math.cos(a) * glow_radius
            y = math.sin(a) * glow_radius
            glVertex3f(cx + x * rx + 0, cy + y, cz + x * rz)
        glEnd()

        glDepthMask(True)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_DEPTH_TEST)

        glDisable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)

        glMaterialfv(GL_FRONT_AND_BACK, GL_AMBIENT,  [0.0, 0.65, 0.20, 1.0])
        glMaterialfv(GL_FRONT_AND_BACK, GL_DIFFUSE,  [
                     0.0, 0.98, 0.35, 1.0])  # Alpha = 1.0 (solid)
        glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, [0.6, 1.0,  0.7,  1.0])
        glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION, [0.0, 0.45, 0.15, 1.0])
        glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 64.0)

        glPushMatrix()
        glTranslatef(cx, cy, cz)

        shaft_r = 0.12   # shaft cylinder radius
        shaft_h = 0.60   # shaft length
        head_r = 0.30   # arrowhead cone base radius
        head_h = 0.42   # arrowhead cone height
        seg = 32     # increased smoothness

        shaft_top = shaft_h * 0.5          # top of shaft (y+)
        shaft_bot = -shaft_h * 0.5         # bottom of shaft / base of cone
        tip_y = shaft_bot - head_h     # tip of arrowhead

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
            glVertex3f(math.cos(a) * shaft_r, shaft_top, math.sin(a) * shaft_r)
        glEnd()

        glBegin(GL_TRIANGLE_FAN)
        glNormal3f(0.0, 1.0, 0.0)
        glVertex3f(0.0, shaft_bot, 0.0)
        for i in range(seg + 1):
            a = (i / seg) * 2.0 * math.pi
            glVertex3f(math.cos(a) * head_r, shaft_bot, math.sin(a) * head_r)
        glEnd()

        slant = math.atan2(head_r, head_h)   # angle from vertical
        # upward component of outward normal
        ny = math.sin(slant)
        nr = math.cos(slant)                  # radial component
        glBegin(GL_TRIANGLE_FAN)
        glNormal3f(0.0, -1.0, 0.0)           # tip normal points down
        glVertex3f(0.0, tip_y, 0.0)
        for i in range(seg + 1):
            a = (i / seg) * 2.0 * math.pi
            ca, sa = math.cos(a), math.sin(a)
            glNormal3f(ca * nr, ny, sa * nr)
            glVertex3f(ca * head_r, shaft_bot, sa * head_r)
        glEnd()

        glPopMatrix()
        glEnable(GL_DEPTH_TEST)

        glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION, [0.0, 0.0, 0.0, 1.0])
        glMaterialfv(GL_FRONT_AND_BACK, GL_DIFFUSE,  [0.8, 0.8, 0.8, 1.0])
        glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, [0.0, 0.0, 0.0, 1.0])
        glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 0.0)

        glEnable(GL_TEXTURE_2D)

    def _draw_untextured_cube(self) -> None:
        glBegin(GL_QUADS)
        glVertex3f(-0.5, 0.5, -0.5)
        glVertex3f(0.5, 0.5, -0.5)
        glVertex3f(0.5, 0.5, 0.5)
        glVertex3f(-0.5, 0.5, 0.5)
        glVertex3f(-0.5, -0.5, 0.5)
        glVertex3f(0.5, -0.5, 0.5)
        glVertex3f(0.5, -0.5, -0.5)
        glVertex3f(-0.5, -0.5, -0.5)
        glVertex3f(0.5, -0.5, -0.5)
        glVertex3f(0.5, -0.5, 0.5)
        glVertex3f(0.5, 0.5, 0.5)
        glVertex3f(0.5, 0.5, -0.5)
        glVertex3f(-0.5, -0.5, 0.5)
        glVertex3f(-0.5, -0.5, -0.5)
        glVertex3f(-0.5, 0.5, -0.5)
        glVertex3f(-0.5, 0.5, 0.5)
        glVertex3f(-0.5, -0.5, 0.5)
        glVertex3f(-0.5, 0.5, 0.5)
        glVertex3f(0.5, 0.5, 0.5)
        glVertex3f(0.5, -0.5, 0.5)
        glVertex3f(0.5, -0.5, -0.5)
        glVertex3f(0.5, 0.5, -0.5)
        glVertex3f(-0.5, 0.5, -0.5)
        glVertex3f(-0.5, -0.5, -0.5)
        glEnd()

    def _radial_sprite_glow(self, cx: float, cy: float, cz: float, radius: float, color: Tuple[float, float, float], alpha: float) -> None:
        from OpenGL.GL import GL_TRIANGLE_FAN

        yaw = float(getattr(self.core.player, 'yaw', 0.0) or 0.0)
        right_x = math.cos(yaw)
        right_z = -math.sin(yaw)

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

    def _draw_platforms(self) -> None:
        platforms = getattr(self.core, 'platforms', None) or []
        if not platforms:
            return
        glDisable(GL_TEXTURE_2D)
        glDisable(GL_LIGHTING)
        for platform in platforms:
            try:
                r, c = platform.cell
                y = float(getattr(platform, 'y_offset', 0.0) or 0.0)
            except Exception:
                continue

            glPushMatrix()
            glTranslatef(float(c) + 0.5, y + 0.05, float(r) + 0.5)

            glColor4f(0.6, 0.4, 0.2, 1.0)
            glPushMatrix()
            glScalef(0.8, 0.1, 0.8)
            self._draw_untextured_cube()
            glPopMatrix()

            glColor4f(0.4, 0.3, 0.15, 1.0)
            glPushMatrix()
            glTranslatef(0.0, 0.15, 0.35)
            glScalef(0.82, 0.2, 0.05)
            self._draw_untextured_cube()
            glPopMatrix()

            glPushMatrix()
            glTranslatef(0.0, 0.15, -0.35)
            glScalef(0.82, 0.2, 0.05)
            self._draw_untextured_cube()
            glPopMatrix()

            glPushMatrix()
            glTranslatef(-0.35, 0.15, 0.0)
            glScalef(0.05, 0.2, 0.82)
            self._draw_untextured_cube()
            glPopMatrix()

            glPushMatrix()
            glTranslatef(0.35, 0.15, 0.0)
            glScalef(0.05, 0.2, 0.82)
            self._draw_untextured_cube()
            glPopMatrix()

            glPopMatrix()
        glEnable(GL_LIGHTING)

    def _get_jail_map_texture(self) -> int:
        if self._jail_map_texture is not None:
            return int(self._jail_map_texture)

        grid_h = int(getattr(self.core, 'height', 0) or 0)
        grid_w = int(getattr(self.core, 'width', 0) or 0)
        if grid_h <= 0 or grid_w <= 0:
            return 0

        w, h = 640, 420

        margin = 28
        cell_w = (w - margin * 2) / float(grid_w)
        cell_h = (h - margin * 2) / float(grid_h)
        cell = float(min(cell_w, cell_h))
        map_w = cell * grid_w
        map_h = cell * grid_h
        ox = (w - map_w) * 0.5
        oy = (h - map_h) * 0.5

        bmp = wx.Bitmap(int(w), int(h))
        mdc = wx.MemoryDC(bmp)
        try:
            mdc.SetBackground(wx.Brush(wx.Colour(50, 42, 36, 255)))
            mdc.Clear()

            # Use 'layout' instead of 'maze'
            maze = getattr(self.core, 'layout', None)
            if maze is None:
                return 0

            palette: dict[str, wx.Colour] = {
                'A': wx.Colour(80, 120, 200, 255),
                'B': wx.Colour(180, 130, 80, 255),
                'C': wx.Colour(80, 180, 100, 255),
                'D': wx.Colour(110, 180, 180, 255),
                'E': wx.Colour(180, 100, 140, 255),
                'F': wx.Colour(180, 180, 90, 255),
                'G': wx.Colour(160, 100, 190, 255),
                'H': wx.Colour(150, 150, 150, 255),
            }

            for r in range(grid_h):
                for c in range(grid_w):
                    if (r, c) in getattr(self.core, 'walls', set()):
                        continue
                    sid = ''
                    if hasattr(self.core, 'sector_id_for_cell'):
                        sid = self.core.sector_id_for_cell((r, c))
                    col = palette.get(sid)
                    if not col:
                        continue
                    x0 = int(ox + c * cell)
                    y0 = int(oy + r * cell)
                    x1 = int(ox + (c + 1) * cell)
                    y1 = int(oy + (r + 1) * cell)
                    mdc.SetPen(wx.Pen(col))
                    mdc.SetBrush(wx.Brush(col))
                    mdc.DrawRectangle(x0, y0, max(1, x1 - x0), max(1, y1 - y0))

            acc: dict[str, tuple[float, float, int]] = {}
            sid_for = getattr(self.core, 'sector_id_for_cell', None)
            if callable(sid_for):
                for rr in range(grid_h):
                    for cc in range(grid_w):
                        try:
                            sid = str(sid_for((rr, cc)) or '')
                        except Exception:
                            sid = ''
                        if not sid:
                            continue
                        sx, sy, n = acc.get(sid, (0.0, 0.0, 0))
                        acc[sid] = (sx + float(rr), sy + float(cc), n + 1)

            font_big = wx.Font(36, wx.FONTFAMILY_SWISS,
                               wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
            mdc.SetFont(font_big)
            mdc.SetTextForeground(wx.Colour(10, 10, 12, 255))
            for sid, (sx, sy, n) in acc.items():
                if n <= 0:
                    continue
                cr = sx / float(n)
                cc = sy / float(n)
                px = ox + (cc + 0.5) * cell
                py = oy + (cr + 0.5) * cell
                mdc.DrawText(str(sid)[:1], int(px - 10), int(py - 18))

            if getattr(self.core, 'exit_cells', None):
                try:
                    er, ec = self.core.exit_cells[0]
                    px = ox + (float(ec) + 0.5) * cell + 5
                    py = oy + (float(er) + 0.5) * cell
                    box_w = 64
                    box_h = 26
                    mdc.SetPen(wx.Pen(wx.Colour(210, 190, 175, 200)))
                    mdc.SetBrush(wx.Brush(wx.Colour(210, 190, 175, 200)))
                    mdc.DrawRectangle(
                        int(px - box_w / 2), int(py - box_h / 2), int(box_w), int(box_h))
                    font_small = wx.Font(
                        18, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
                    mdc.SetFont(font_small)
                    mdc.SetTextForeground(wx.Colour(15, 15, 16, 255))
                    mdc.DrawText('exit', int(
                        px - box_w / 2) + 10, int(py - 11))
                except Exception:
                    pass
        finally:
            mdc.SelectObject(wx.NullBitmap)

        try:
            img = bmp.ConvertToImage()
            img = img.Mirror(False)
            rgb = img.GetDataBuffer()
            if rgb is None:
                return 0
            rgb_b = bytes(rgb)

            import numpy as np
            rgb_array = np.frombuffer(rgb_b, dtype=np.uint8).reshape(w, h, 3)
            # All pixels opaque
            alpha_array = np.full((w, h), 255, dtype=np.uint8)

            rgba_array = np.dstack((rgb_array, alpha_array))
            data_bytes = rgba_array.tobytes()
        except Exception as e:
            return 0
        tex_id = glGenTextures(1)
        if not tex_id:
            return 0
        glBindTexture(GL_TEXTURE_2D, int(tex_id))
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, int(w), int(h),
                     0, GL_RGBA, GL_UNSIGNED_BYTE, data_bytes)
        glBindTexture(GL_TEXTURE_2D, 0)

        self._jail_map_texture = int(tex_id)
        return int(tex_id)

    def _draw_sector_signs_and_jail_painting(self) -> None:
        sector_signs = getattr(self.core, 'sector_signs', None) or {}
        painting = getattr(self.core, 'jail_painting', None)
        if (not sector_signs) and (not painting):
            return

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

        glDisable(GL_LIGHTING)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        if sector_signs:
            for sid, (cell, facing) in sector_signs.items():
                try:
                    r, c = cell
                except Exception:
                    continue
                cx = float(c) + 0.5
                cz = float(r) + 0.5
                cy = 1.65

                glColor4f(0.10, 0.10, 0.12, 0.92)
                glBegin(GL_QUADS)
                _wall_quad(cx, cy, cz, 0.48, 0.18, str(facing))
                glEnd()

                label = f"SECTOR {str(sid)[:1]}"
                tex_id, _, _ = self.get_text_texture(
                    label, font_family='Segoe UI', font_size=28, bold=True, color=(255, 235, 120, 255), pad=12)
                if tex_id:
                    glEnable(GL_TEXTURE_2D)
                    glBindTexture(GL_TEXTURE_2D, int(tex_id))
                    glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
                    glColor4f(1.0, 1.0, 1.0, 0.98)
                    tw = 0.42
                    th = 0.11
                    glBegin(GL_QUADS)
                    f = str(facing)
                    if f == 'N':
                        z = cz - 0.481
                        glTexCoord2f(0.0, 1.0)
                        glVertex3f(cx - tw, cy + th, z)
                        glTexCoord2f(1.0, 1.0)
                        glVertex3f(cx + tw, cy + th, z)
                        glTexCoord2f(1.0, 0.0)
                        glVertex3f(cx + tw, cy - th, z)
                        glTexCoord2f(0.0, 0.0)
                        glVertex3f(cx - tw, cy - th, z)
                    elif f == 'S':
                        z = cz + 0.481
                        glTexCoord2f(0.0, 1.0)
                        glVertex3f(cx + tw, cy + th, z)
                        glTexCoord2f(1.0, 1.0)
                        glVertex3f(cx - tw, cy + th, z)
                        glTexCoord2f(1.0, 0.0)
                        glVertex3f(cx - tw, cy - th, z)
                        glTexCoord2f(0.0, 0.0)
                        glVertex3f(cx + tw, cy - th, z)
                    elif f == 'W':
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
                    glDisable(GL_TEXTURE_2D)

        if painting:
            try:
                (pr, pc), facing = painting
                cx = float(pc) + 0.5
                cz = float(pr) + 0.5
                cy = 1.55
            except Exception:
                cx = cz = cy = 0.0
                facing = 'N'

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

            glColor4f(0.30, 0.20, 0.10, 1.0)
            glBegin(GL_QUADS)
            _wall_quad(cx, cy, cz, 0.78, 0.50, str(facing))
            glEnd()

            glColor4f(0.08, 0.08, 0.10, 0.98)
            glBegin(GL_QUADS)
            _wall_quad(cx, cy, cz, 0.72, 0.44, str(facing))
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
                f = str(facing)
                if f == 'N':
                    z = cz - 0.473
                    glTexCoord2f(0.0, 1.0)
                    glVertex3f(cx - tw, cy + th, z)
                    glTexCoord2f(1.0, 1.0)
                    glVertex3f(cx + tw, cy + th, z)
                    glTexCoord2f(1.0, 0.0)
                    glVertex3f(cx + tw, cy - th, z)
                    glTexCoord2f(0.0, 0.0)
                    glVertex3f(cx - tw, cy - th, z)
                elif f == 'S':
                    z = cz + 0.473
                    glTexCoord2f(0.0, 1.0)
                    glVertex3f(cx + tw, cy + th, z)
                    glTexCoord2f(1.0, 1.0)
                    glVertex3f(cx - tw, cy + th, z)
                    glTexCoord2f(1.0, 0.0)
                    glVertex3f(cx - tw, cy - th, z)
                    glTexCoord2f(0.0, 0.0)
                    glVertex3f(cx + tw, cy - th, z)
                elif f == 'W':
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
                glDisable(GL_TEXTURE_2D)

        glBindTexture(GL_TEXTURE_2D, 0)
        glDisable(GL_TEXTURE_2D)
        glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE,
                  GL_MODULATE)  # reset to default
        glEnable(GL_LIGHTING)

    def _draw_entities(self, anim_t: float) -> None:
        glDisable(GL_TEXTURE_2D)

        px = float(self.core.player.x)
        pz = float(self.core.player.z)

        entity_draw_radius = max(18.0, float(self._fog_end) - 2.0)
        entity_r2 = entity_draw_radius * entity_draw_radius

        cam_yaw = float(self.core.player.yaw)
        right_x = math.cos(cam_yaw)
        right_z = -math.sin(cam_yaw)

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

        key_buffer = self._build_key_fragments_buffer(anim_t)
        self._draw_key_fragments(key_buffer)

        ghost_buffer = self._build_ghosts_buffer(anim_t)
        self._draw_ghosts(ghost_buffer)

        spike_buffer = self._build_spikes_buffer(anim_t)
        self._draw_spikes(spike_buffer)

    def _bind_texture(self, tex: Optional[int]) -> None:
        glBindTexture(GL_TEXTURE_2D, int(tex) if tex else 0)

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

        self._delete_ghost_vbos()

        try:
            if self._coin_geom_vbo is not None:
                glDeleteBuffers(1, [int(self._coin_geom_vbo)])
        except Exception:
            pass
        try:
            if self._coin_tex_vbo is not None:
                glDeleteBuffers(1, [int(self._coin_tex_vbo)])
        except Exception:
            pass
        try:
            if self._glow_additive_vbo is not None:
                glDeleteBuffers(1, [int(self._glow_additive_vbo)])
        except Exception:
            pass
        try:
            if self._spikes_vbo is not None:
                glDeleteBuffers(1, [int(self._spikes_vbo)])
        except Exception:
            pass
        try:
            if self._platforms_vbo is not None:
                glDeleteBuffers(1, [int(self._platforms_vbo)])
        except Exception:
            pass
        try:
            if self._gates_vbo is not None:
                glDeleteBuffers(1, [int(self._gates_vbo)])
        except Exception:
            pass
        self._coin_geom_vbo = None
        self._coin_geom_vertex_count = 0
        self._coin_tex_vbo = None
        self._coin_tex_vertex_count = 0
        self._glow_additive_vbo = None
        self._glow_additive_vertex_count = 0
        self._spikes_vbo = None
        self._spikes_vertex_count = 0
        self._platforms_vbo = None
        self._platforms_vertex_count = 0
        self._gates_vbo = None
        self._gates_vertex_count = 0
        self._key_fragments_vbo = None
        self._key_fragments_vertex_count = 0
        self._ghosts_vbo = None
        self._ghosts_vertex_count = 0

    def _build_world_vbos(self) -> None:
        if self._world_vbo_floor is not None and self._world_vbo_wall is not None:
            if hasattr(self, '_world_vbo_hash'):
                current_hash = hash(
                    (tuple(sorted(self.core.floors)), tuple(sorted(self.core.walls))))
                if current_hash == self._world_vbo_hash:
                    return

        self._delete_world_vbos()

        from array import array

        floor_data = array('f')
        wall_data = array('f')
        chunk_floor: dict[tuple[int, int], array] = {}
        chunk_wall: dict[tuple[int, int], array] = {}

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

        self._world_vbo_hash = hash(
            (tuple(sorted(self.core.floors)), tuple(sorted(self.core.walls))))

    def _build_ghost_vbo(self) -> None:
        """Build VBOs for ghost body and eyes."""
        from array import array

        self._delete_ghost_vbos()

        segments = 26 if self._fast_mode else 40
        body_layers = 11
        radius = 0.20

        def y_and_r(t: float) -> Tuple[float, float]:
            if t < 0.5:
                yv = radius * 0.62 * math.cos(t * math.pi)
                rv = radius * 0.95 * math.sin(t * math.pi)
            else:
                yv = -radius * 0.25 * (t - 0.5) * 2.0
                rv = radius * 0.95
            return yv, rv

        body: array = array('f')
        for layer in range(1, body_layers):
            y_prev, r_prev = y_and_r((layer - 1) / (body_layers - 1))
            y_curr, r_curr = y_and_r(layer / (body_layers - 1))

            for i in range(segments + 1):
                a = (i / segments) * (2.0 * math.pi)
                ca, sa = math.cos(a), math.sin(a)
                body.extend([ca * r_prev, y_prev, sa * r_prev, ca, 0.0, sa])
                body.extend([ca * r_curr, y_curr, sa * r_curr, ca, 0.0, sa])

        self._ghost_body_vertex_count = len(body) // 6
        if self._ghost_body_vertex_count > 0:
            try:
                vbo = glGenBuffers(1)
                self._ghost_body_vbo = int(vbo) if vbo else None
                if self._ghost_body_vbo:
                    glBindBuffer(GL_ARRAY_BUFFER, self._ghost_body_vbo)
                    glBufferData(GL_ARRAY_BUFFER,
                                 body.tobytes(), GL_STATIC_DRAW)
                    glBindBuffer(GL_ARRAY_BUFFER, 0)
            except Exception:
                self._ghost_body_vbo = None
                self._ghost_body_vertex_count = 0

        eye: array = array('f')
        eye_y = radius * 0.22
        eye_z = radius * 1.05
        eye_x = radius * 0.34
        ew = radius * 0.22
        eh = radius * 0.28

        def add_eye_quad(cx: float) -> None:
            for verts in [(cx - ew, eye_y - eh, eye_z), (cx + ew, eye_y - eh, eye_z),
                          (cx + ew, eye_y + eh, eye_z), (cx - ew, eye_y + eh, eye_z),
                          (cx - ew, eye_y - eh, eye_z)]:
                eye.extend(verts)

        add_eye_quad(-eye_x)
        add_eye_quad(eye_x)
        self._ghost_eye_vertex_count = len(eye) // 3
        if self._ghost_eye_vertex_count > 0:
            try:
                vbo = glGenBuffers(1)
                self._ghost_eye_vbo = int(vbo) if vbo else None
                if self._ghost_eye_vbo:
                    glBindBuffer(GL_ARRAY_BUFFER, self._ghost_eye_vbo)
                    glBufferData(GL_ARRAY_BUFFER,
                                 eye.tobytes(), GL_STATIC_DRAW)
                    glBindBuffer(GL_ARRAY_BUFFER, 0)
            except Exception:
                self._ghost_eye_vbo = None
                self._ghost_eye_vertex_count = 0

    def _build_lamp_vbo(self) -> None:
        """Pre-build ceiling lamp geometry (static per level)."""
        from array import array

        if self._lamp_vbo is not None:
            try:
                glDeleteBuffers(1, [int(self._lamp_vbo)])
            except Exception:
                pass
            self._lamp_vbo = None
            self._lamp_vertex_count = 0
            self._lamp_positions = []

        ceil_h = float(self.core.ceiling_height)
        floors = self.core.floors
        walls = self.core.walls

        def is_floor(rr, cc):
            return (rr, cc) in floors and (rr, cc) not in walls

        exclusion_zones = set()

        exclusion_zones.update(self.core.gate_cells)

        gate_cells = []
        if hasattr(self.core, 'layout') and self.core.layout:
            for r, row in enumerate(self.core.layout):
                for c, char in enumerate(row):
                    if char == 'd':
                        gate_cells.append((r, c))

        for start_cell in self.core.start_cells:
            if gate_cells:
                nearest_gate = min(gate_cells, key=lambda g: abs(
                    g[0] - start_cell[0]) + abs(g[1] - start_cell[1]))
                min_r, max_r = min(start_cell[0], nearest_gate[0]), max(
                    start_cell[0], nearest_gate[0])
                min_c, max_c = min(start_cell[1], nearest_gate[1]), max(
                    start_cell[1], nearest_gate[1])
                for r in range(min_r, max_r + 1):
                    for c in range(min_c, max_c + 1):
                        exclusion_zones.add((r, c))

        for exit_cell in self.core.exit_cells:
            if gate_cells:
                nearest_gate = min(gate_cells, key=lambda g: abs(
                    g[0] - exit_cell[0]) + abs(g[1] - exit_cell[1]))
                min_r, max_r = min(exit_cell[0], nearest_gate[0]), max(
                    exit_cell[0], nearest_gate[0])
                min_c, max_c = min(exit_cell[1], nearest_gate[1]), max(
                    exit_cell[1], nearest_gate[1])
                for r in range(min_r, max_r + 1):
                    for c in range(min_c, max_c + 1):
                        exclusion_zones.add((r, c))

        candidates = []
        for (r, c) in floors:
            if (r, c) in walls or (r, c) in exclusion_zones:
                continue
            if is_floor(r, c - 1) and is_floor(r, c + 1) and not is_floor(r, c - 2) and not is_floor(r, c + 2):
                candidates.append((r, c))
                continue
            if is_floor(r - 1, c) and is_floor(r + 1, c) and not is_floor(r - 2, c) and not is_floor(r + 2, c):
                candidates.append((r, c))

        candidates.sort()
        lamps = []
        min_sep2 = 8.0 ** 2
        for rc in candidates:
            if all(((rc[0] - lr) ** 2 + (rc[1] - lc) ** 2) >= min_sep2 for lr, lc in lamps):
                lamps.append(rc)
            if len(lamps) >= 140:
                break

        self._lamp_positions = list(lamps)

        lamp_data = array('f')
        DARK = (0.10, 0.10, 0.12, 1.0)
        METAL = (0.18, 0.18, 0.22, 1.0)
        WARM = (0.98, 0.95, 0.82, 1.0)

        def add_cube(cx, cy, cz, sx, sy, sz, color):
            """Add cube vertices with colors to lamp_data array"""
            x0, x1 = cx - sx, cx + sx
            y0, y1 = cy - sy, cy + sy
            z0, z1 = cz - sz, cz + sz

            lamp_data.extend([x0, y0, z1, *color])
            lamp_data.extend([x1, y0, z1, *color])
            lamp_data.extend([x1, y1, z1, *color])
            lamp_data.extend([x0, y0, z1, *color])
            lamp_data.extend([x1, y1, z1, *color])
            lamp_data.extend([x0, y1, z1, *color])
            lamp_data.extend([x0, y0, z0, *color])
            lamp_data.extend([x0, y1, z0, *color])
            lamp_data.extend([x1, y1, z0, *color])
            lamp_data.extend([x0, y0, z0, *color])
            lamp_data.extend([x1, y1, z0, *color])
            lamp_data.extend([x1, y0, z0, *color])
            lamp_data.extend([x0, y0, z0, *color])
            lamp_data.extend([x0, y0, z1, *color])
            lamp_data.extend([x0, y1, z1, *color])
            lamp_data.extend([x0, y0, z0, *color])
            lamp_data.extend([x0, y1, z1, *color])
            lamp_data.extend([x0, y1, z0, *color])
            lamp_data.extend([x1, y0, z0, *color])
            lamp_data.extend([x1, y1, z0, *color])
            lamp_data.extend([x1, y1, z1, *color])
            lamp_data.extend([x1, y0, z0, *color])
            lamp_data.extend([x1, y1, z1, *color])
            lamp_data.extend([x1, y0, z1, *color])
            lamp_data.extend([x0, y1, z0, *color])
            lamp_data.extend([x1, y1, z0, *color])
            lamp_data.extend([x1, y1, z1, *color])
            lamp_data.extend([x0, y1, z0, *color])
            lamp_data.extend([x1, y1, z1, *color])
            lamp_data.extend([x0, y1, z1, *color])
            lamp_data.extend([x0, y0, z0, *color])
            lamp_data.extend([x0, y0, z1, *color])
            lamp_data.extend([x1, y0, z1, *color])
            lamp_data.extend([x0, y0, z0, *color])
            lamp_data.extend([x1, y0, z1, *color])
            lamp_data.extend([x1, y0, z0, *color])

        for r, c in lamps:
            cx, cz = c + 0.5, r + 0.5
            add_cube(cx, ceil_h - 0.15 + 0.18, cz, 0.015, 0.18, 0.015, DARK)
            add_cube(cx, ceil_h - 0.15 + 0.02, cz, 0.13, 0.05, 0.13, METAL)
            add_cube(cx, ceil_h - 0.15 - 0.02, cz, 0.05, 0.035, 0.05, WARM)

        # 7 floats per vertex (x,y,z,r,g,b,a)
        self._lamp_vertex_count = len(lamp_data) // 7

        if self._lamp_vertex_count > 0:
            try:
                vbo = glGenBuffers(1)
                self._lamp_vbo = int(vbo) if vbo else None
                if self._lamp_vbo:
                    glBindBuffer(GL_ARRAY_BUFFER, self._lamp_vbo)
                    glBufferData(GL_ARRAY_BUFFER,
                                 lamp_data.tobytes(), GL_STATIC_DRAW)
                    glBindBuffer(GL_ARRAY_BUFFER, 0)
            except Exception as e:
                print(f"Error creating lamp VBO: {e}")
                self._lamp_vbo = None
                self._lamp_vertex_count = 0

    def _delete_ghost_vbos(self) -> None:
        """Clean up ghost VBOs."""
        if self._ghost_body_vbo is not None:
            try:
                glDeleteBuffers(1, [int(self._ghost_body_vbo)])
            except Exception:
                pass
        if self._ghost_eye_vbo is not None:
            try:
                glDeleteBuffers(1, [int(self._ghost_eye_vbo)])
            except Exception:
                pass
        self._ghost_body_vbo = None
        self._ghost_body_vertex_count = 0
        self._ghost_eye_vbo = None
        self._ghost_eye_vertex_count = 0

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

    def _draw_world_immediate(self) -> None:
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

    def _build_static_geometry(self) -> None:
        self._static_quads.clear()
        wall_h = float(self.core.wall_height)
        ceil_h = float(self.core.ceiling_height)

        def add_quad(center_r: float, center_c: float, tex: Optional[int], vtx: Tuple[Tuple[float, float, float, float, float], ...]):
            self._static_quads.append((center_r, center_c, tex, vtx))

        floors = self.core.floors
        walls = self.core.walls

        h = int(getattr(self.core, 'height', 0))
        w = int(getattr(self.core, 'width', 0))

        def is_solid(rr: int, cc: int) -> bool:
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

            if not is_inside(r - 1, c):
                add_quad(
                    cz,
                    cx,
                    self._tex_wall,
                    (
                        (0.0, 0.0, cx - 0.5, 0.0, cz - 0.5),
                        (1.0, 0.0, cx + 0.5, 0.0, cz - 0.5),
                        (1.0, 1.0, cx + 0.5, wall_h, cz - 0.5),
                        (0.0, 1.0, cx - 0.5, wall_h, cz - 0.5),
                    ),
                )
            if not is_inside(r + 1, c):
                add_quad(
                    cz,
                    cx,
                    self._tex_wall,
                    (
                        (0.0, 0.0, cx + 0.5, 0.0, cz + 0.5),
                        (1.0, 0.0, cx - 0.5, 0.0, cz + 0.5),
                        (1.0, 1.0, cx - 0.5, wall_h, cz + 0.5),
                        (0.0, 1.0, cx + 0.5, wall_h, cz + 0.5),
                    ),
                )
            if not is_inside(r, c - 1):
                add_quad(
                    cz,
                    cx,
                    self._tex_wall,
                    (
                        (0.0, 0.0, cx - 0.5, 0.0, cz + 0.5),
                        (1.0, 0.0, cx - 0.5, 0.0, cz - 0.5),
                        (1.0, 1.0, cx - 0.5, wall_h, cz - 0.5),
                        (0.0, 1.0, cx - 0.5, wall_h, cz + 0.5),
                    ),
                )
            if not is_inside(r, c + 1):
                add_quad(
                    cz,
                    cx,
                    self._tex_wall,
                    (
                        (0.0, 0.0, cx + 0.5, 0.0, cz - 0.5),
                        (1.0, 0.0, cx + 0.5, 0.0, cz + 0.5),
                        (1.0, 1.0, cx + 0.5, wall_h, cz + 0.5),
                        (0.0, 1.0, cx + 0.5, wall_h, cz - 0.5),
                    ),
                )

        for (r, c) in walls:
            cx = c + 0.5
            cz = r + 0.5
            y0 = 0.0
            y1 = wall_h

            if not is_solid(r - 1, c):
                add_quad(
                    cz,
                    cx,
                    self._tex_wall,
                    (
                        (0.0, 0.0, cx - 0.5, y0, cz - 0.5),
                        (1.0, 0.0, cx + 0.5, y0, cz - 0.5),
                        (1.0, 1.0, cx + 0.5, y1, cz - 0.5),
                        (0.0, 1.0, cx - 0.5, y1, cz - 0.5),
                    ),
                )

            if not is_solid(r + 1, c):
                add_quad(
                    cz,
                    cx,
                    self._tex_wall,
                    (
                        (0.0, 0.0, cx + 0.5, y0, cz + 0.5),
                        (1.0, 0.0, cx - 0.5, y0, cz + 0.5),
                        (1.0, 1.0, cx - 0.5, y1, cz + 0.5),
                        (0.0, 1.0, cx + 0.5, y1, cz + 0.5),
                    ),
                )

            if not is_solid(r, c - 1):
                add_quad(
                    cz,
                    cx,
                    self._tex_wall,
                    (
                        (0.0, 0.0, cx - 0.5, y0, cz + 0.5),
                        (1.0, 0.0, cx - 0.5, y0, cz - 0.5),
                        (1.0, 1.0, cx - 0.5, y1, cz - 0.5),
                        (0.0, 1.0, cx - 0.5, y1, cz + 0.5),
                    ),
                )

            if not is_solid(r, c + 1):
                add_quad(
                    cz,
                    cx,
                    self._tex_wall,
                    (
                        (0.0, 0.0, cx + 0.5, y0, cz - 0.5),
                        (1.0, 0.0, cx + 0.5, y0, cz + 0.5),
                        (1.0, 1.0, cx + 0.5, y1, cz + 0.5),
                        (0.0, 1.0, cx + 0.5, y1, cz - 0.5),
                    ),
                )

            if y1 < ceil_h and (
                (not is_solid(r - 1, c))
                or (not is_solid(r + 1, c))
                or (not is_solid(r, c - 1))
                or (not is_solid(r, c + 1))
            ):
                add_quad(
                    cz,
                    cx,
                    self._tex_wall,
                    (
                        (0.0, 0.0, cx - 0.5, y1, cz + 0.5),
                        (1.0, 0.0, cx + 0.5, y1, cz + 0.5),
                        (1.0, 1.0, cx + 0.5, y1, cz - 0.5),
                        (0.0, 1.0, cx - 0.5, y1, cz - 0.5),
                    ),
                )

    def _load_texture(self, path: str) -> Optional[int]:
        """
        PERFORMANCE NOTE: wxPython texture loading is ~9x slower than PySide6
        due to wx.Image inefficiencies. This is a documented wxPython limitation.
        See: wxpython_texture_performance_analysis.md
        """
        if not os.path.exists(path):
            return None

        if hasattr(self, '_texture_cache'):
            cached = self._texture_cache.get(path)
            if cached:
                return cached
        else:
            self._texture_cache = {}

        try:
            # SLOW: wx.Image is performance bottleneck
            img = wx.Image(str(path))
        except Exception:
            return None
        if img is None or (not img.IsOk()):
            return None

        try:
            if not img.HasAlpha():
                img.InitAlpha()
            else:
                path_lower = str(path).lower()
                if 'coin' in path_lower or 'jema' in path_lower:
                    pass
                else:
                    alpha_buf = img.GetAlphaBuffer()
                    if alpha_buf:
                        alpha_data = bytes(alpha_buf)
                        new_alpha = bytearray(len(alpha_data))
                        for i in range(len(new_alpha)):
                            new_alpha[i] = 255  # Fully opaque
                        img.SetAlphaBuffer(new_alpha)
        except Exception:
            pass
        try:
            img = img.Mirror(False, True)  # Flip vertically like PySide6/Kivy
        except Exception:
            pass

        w = int(img.GetWidth())
        h = int(img.GetHeight())
        try:
            rgb = img.GetDataBuffer()
            alpha = img.GetAlphaBuffer()
            if rgb is None or alpha is None:
                return None
            rgb_arr = np.frombuffer(
                bytes(rgb), dtype=np.uint8).reshape(w * h, 3)
            a_arr = np.frombuffer(bytes(alpha), dtype=np.uint8)
            out = np.empty((w * h, 4), dtype=np.uint8)
            out[:, :3] = rgb_arr
            out[:, 3] = a_arr
            data_bytes = out.tobytes()
        except Exception:
            return None

        tex_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, int(tex_id))
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, int(w), int(h),
                     0, GL_RGBA, GL_UNSIGNED_BYTE, data_bytes)
        glBindTexture(GL_TEXTURE_2D, 0)

        self._texture_cache[path] = int(tex_id)
        return int(tex_id)

    def clear_text_texture_cache(self) -> None:
        """Clear all cached text textures and delete GL textures."""
        if not self._text_texture_cache:
            return

        try:
            for tex_id, _, _ in self._text_texture_cache.values():
                if tex_id and tex_id > 0:
                    glDeleteTextures([tex_id])
        except Exception:
            pass

        self._text_texture_cache.clear()

    def get_text_texture(self, text: str, *, font_family: str = 'Segoe UI', font_size: int = 28, bold: bool = True,
                         color: tuple[int, int, int, int] = (240, 240, 240, 255), pad: int = 10) -> tuple[int, int, int]:
        key = (str(text), str(font_family), int(font_size),
               bool(bold), tuple(int(x) for x in color), int(pad))
        cached = self._text_texture_cache.get(key)
        if cached:
            return cached

        text = str(text)
        if not text:
            return (0, 1, 1)

        if len(self._text_texture_cache) > 200:
            glBindTexture(GL_TEXTURE_2D, 0)  # ADD THIS: Unbind before deleting
            keys_to_remove = list(self._text_texture_cache.keys())[:50]
            for k in keys_to_remove:
                tex_id, _, _ = self._text_texture_cache.pop(k)
                try:
                    if tex_id > 0:
                        glDeleteTextures([tex_id])
                except Exception:
                    pass

        try:
            font = wx.Font(
                int(font_size),
                wx.FONTFAMILY_SWISS,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD if bool(bold) else wx.FONTWEIGHT_NORMAL,
                faceName=str(font_family),
            )
        except Exception:
            font = wx.Font(
                int(font_size),
                wx.FONTFAMILY_SWISS,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD if bool(bold) else wx.FONTWEIGHT_NORMAL,
            )

        try:
            mdc = wx.MemoryDC()
            bmp = wx.Bitmap(4, 4)
            mdc.SelectObject(bmp)
            mdc.SetFont(font)
            tw, th = mdc.GetTextExtent(text)
            mdc.SelectObject(wx.NullBitmap)
        except Exception:
            tw, th = (max(1, int(len(text) * font_size * 0.6)),
                      max(1, int(font_size * 1.2)))

        w = int(max(1, int(tw) + int(pad) * 2))
        h = int(max(1, int(th) + int(pad) * 2))

        bmp = wx.Bitmap(w, h)
        mdc = wx.MemoryDC(bmp)
        try:
            mdc.SetBackground(wx.Brush(wx.Colour(0, 0, 0, 255)))
            mdc.Clear()
            gc = wx.GraphicsContext.Create(mdc)
            if gc is not None:
                try:
                    gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)
                except Exception:
                    pass
                gc.SetFont(font, wx.Colour(255, 255, 255, 255))
                gc.DrawText(text, float(pad), float(pad))
            else:
                mdc.SetFont(font)
                mdc.SetTextForeground(wx.Colour(255, 255, 255, 255))
                mdc.DrawText(text, int(pad), int(pad))
        finally:
            mdc.SelectObject(wx.NullBitmap)

        try:
            img = bmp.ConvertToImage()
            img = img.Mirror(False)
            rgb_buf = img.GetDataBuffer()
            if rgb_buf is None:
                return (0, int(w), int(h))
            rgb_arr = np.frombuffer(
                bytes(rgb_buf), dtype=np.uint8).reshape(w * h, 3)

            lum = rgb_arr.max(axis=1).astype(np.float32) / 255.0

            r_col = int(color[0]) / 255.0
            g_col = int(color[1]) / 255.0
            b_col = int(color[2]) / 255.0
            a_col = int(color[3]) / 255.0

            out = np.empty((w * h, 4), dtype=np.uint8)
            out[:, 0] = np.clip(lum * r_col * 255.0, 0, 255).astype(np.uint8)
            out[:, 1] = np.clip(lum * g_col * 255.0, 0, 255).astype(np.uint8)
            out[:, 2] = np.clip(lum * b_col * 255.0, 0, 255).astype(np.uint8)
            out[:, 3] = np.clip(lum * a_col * 255.0, 0, 255).astype(np.uint8)
            data_bytes = out.tobytes()
        except Exception:
            return (0, int(w), int(h))
        tex_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, int(tex_id))
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, int(w), int(h),
                     0, GL_RGBA, GL_UNSIGNED_BYTE, data_bytes)
        glBindTexture(GL_TEXTURE_2D, 0)

        out = (int(tex_id), int(w), int(h))
        self._text_texture_cache[key] = out
        return out

    def _get_text_texture(self, text: str) -> int:
        tex, _, _ = self.get_text_texture(text)
        return int(tex)

    def _draw_coins(self, anim_t: float) -> None:
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)

        px = float(self.core.player.x)
        pz = float(self.core.player.z)

        entity_draw_radius = max(18.0, float(self._fog_end) - 2.0)
        entity_r2 = entity_draw_radius * entity_draw_radius
        glow_draw_radius = max(12.0, entity_draw_radius * 0.70)
        glow_r2 = glow_draw_radius * glow_draw_radius

        TWO_PI = 6.283185307179586
        RAD_TO_DEG = 57.29577951308232

        yaw = self.core.player.yaw
        right_x = math.cos(yaw)
        right_z = -math.sin(yaw)

        def radial_sprite_glow(cx: float, cy: float, cz: float, radius: float, color: Tuple[float, float, float], alpha: float) -> None:
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

        def _draw_coin_3d_mario(radius: float = 0.13, thickness: float = 0.045, segments: int = 18, *, textured: bool = False) -> None:
            from OpenGL.GL import GL_TRIANGLE_FAN, GL_POINTS

            y0 = -thickness / 2.0
            y1 = thickness / 2.0

            glBegin(GL_QUADS)
            for i in range(segments):
                a0 = (i / segments) * (2.0 * math.pi)
                a1 = ((i + 1) / segments) * (2.0 * math.pi)
                x0 = math.cos(a0) * radius
                z0 = math.sin(a0) * radius
                x1 = math.cos(a1) * radius
                z1 = math.sin(a1) * radius

                if i % 2 == 0:
                    glColor4f(1.0, 0.84, 0.18, 0.98)
                else:
                    glColor4f(240 / 255, 168 / 255, 48 / 255, 0.98)

                glVertex3f(x0, y0, z0)
                glVertex3f(x1, y0, z1)
                glVertex3f(x1, y1, z1)
                glVertex3f(x0, y1, z0)
            glEnd()

            if textured and self._tex_coin is not None:
                inner_radius = radius * 0.92

                glColor4f(1.0, 0.84, 0.18, 0.98)
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

                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, int(self._tex_coin))
                glColor4f(1.0, 1.0, 1.0, 0.98)

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
                glColor4f(1.0, 0.84, 0.18, 0.98)

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
            glVertex3f(0.0, y1, 0.0)
            glVertex3f(0.0, y0, 0.0)
            glEnd()

        coin_buffer = self._build_coin_buffer(anim_t)
        tex_buffer = self._build_coin_tex_buffer(anim_t)
        glow_buffer = self._build_glow_buffer(anim_t)

        self._draw_coin_geometries(coin_buffer)

        self._draw_coin_textures(tex_buffer)

        self._draw_additive_glows(glow_buffer)

    def _draw_ceiling_lamps(self) -> None:
        """Draw ceiling lamps"""
        glDisable(GL_TEXTURE_2D)
        glDisable(GL_LIGHTING)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        ceil_h = float(self.core.ceiling_height)

        def is_floor(rr: int, cc: int) -> bool:
            return (rr, cc) in self.core.floors and (rr, cc) not in self.core.walls

        lamps = self._lamp_positions

        yaw = self.core.player.yaw
        right_x = math.cos(yaw)
        right_z = -math.sin(yaw)

        def floor_glow(cx: float, cz: float, y: float, radius: float, color: Tuple[float, float, float], alpha: float) -> None:
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

        if self._lamp_vbo is not None and self._lamp_vertex_count > 0:
            glDisable(GL_TEXTURE_2D)
            glDisable(GL_LIGHTING)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

            glDisable(GL_LIGHTING)  # Fix GL_LIGHTING state bleed
            glEnableClientState(GL_VERTEX_ARRAY)
            glEnableClientState(GL_COLOR_ARRAY)
            glBindBuffer(GL_ARRAY_BUFFER, self._lamp_vbo)
            # 7 floats per vertex
            glVertexPointer(3, GL_FLOAT, 28, ctypes.c_void_p(0))
            # color starts after position
            glColorPointer(4, GL_FLOAT, 28, ctypes.c_void_p(12))
            glDrawArrays(GL_TRIANGLES, 0, self._lamp_vertex_count)
            glDisableClientState(GL_COLOR_ARRAY)
            glDisableClientState(GL_VERTEX_ARRAY)
            glBindBuffer(GL_ARRAY_BUFFER, 0)

            ceil_h = float(self.core.ceiling_height)
            for r, c in self._lamp_positions:
                cx = c + 0.5
                cz = r + 0.5
                floor_glow(cx, cz, 0.015, 1.75, (0.98, 0.95, 0.82), 0.20)
                floor_glow(cx, cz, 0.016, 0.85, (0.98, 0.95, 0.82), 0.22)
                soft_aura(cx, ceil_h - 0.45, cz, 1.10,
                          (0.98, 0.95, 0.82), 0.08)

        glEnable(GL_TEXTURE_2D)

    def _draw_spike(self, height: float) -> None:
        """Draw a single spike trap - ported from PySide."""
        if height <= 0.02:
            return
        base = 0.18
        glBegin(GL_QUADS)
        glVertex3f(-base, 0.01, -base)
        glVertex3f(base, 0.01, -base)
        glVertex3f(base, 0.01, base)
        glVertex3f(-base, 0.01, base)
        glEnd()
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

    def _build_coin_buffer(self, anim_t: float) -> array:
        """Build coin geometry buffer with exact same math as immediate mode."""
        buf = array('f')
        TWO_PI = math.pi * 2.0
        player = self.core.player
        px, pz = float(player.x), float(player.z)
        entity_r2 = 18.0 ** 2
        glow_r2 = 12.0 ** 2

        for coin in self.core.coins.values():
            if coin.taken:
                continue
            r, c = coin.cell
            cx, cz = c + 0.5, r + 0.5
            dx, dz = float(cx) - px, float(cz) - pz
            d2 = dx * dx + dz * dz
            if d2 > entity_r2:
                continue

            bob = 0.06 * math.sin(anim_t * 1.6 + r * 0.37 + c * 0.51)
            spin = (anim_t * 3.0) % TWO_PI
            cy = 1.22 + bob

            cos_s, sin_s = math.cos(spin), math.sin(spin)

            def xform(lx, ly, lz):
                ax, ay, az = lx, -lz, ly
                wx = ax * cos_s + az * sin_s
                wz = -ax * sin_s + az * cos_s
                return cx + wx, cy + ay, cz + wz

            thickness = 0.04
            radius = 0.14
            segments = 24 if d2 <= glow_r2 else 16
            y0, y1 = -thickness / 2.0, thickness / 2.0

            for i in range(segments):
                a0 = (i / segments) * TWO_PI
                a1 = ((i + 1) / segments) * TWO_PI

                p = [
                    (math.cos(a0) * radius, y0, math.sin(a0) * radius),
                    (math.cos(a1) * radius, y0, math.sin(a1) * radius),
                    (math.cos(a1) * radius, y1, math.sin(a1) * radius),
                    (math.cos(a0) * radius, y0, math.sin(a0) * radius),
                    (math.cos(a1) * radius, y1, math.sin(a1) * radius),
                    (math.cos(a0) * radius, y1, math.sin(a0) * radius),
                ]

                col = (1.0, 0.84, 0.18, 0.98) if i % 2 == 0 else (
                    240/255, 168/255, 48/255, 0.98)

                for (lx, ly, lz) in p:
                    wx, wy, wz = xform(lx, ly, lz)
                    buf.extend([wx, wy, wz, col[0], col[1], col[2], col[3]])

            gold = (1.0, 0.84, 0.18, 0.98)
            for sign, yf in ((1, y1), (-1, y0)):
                for i in range(segments):
                    a0 = (i / segments) * TWO_PI
                    a1 = ((i + 1) / segments) * TWO_PI
                    p0 = (0.0, yf, 0.0)
                    p1 = (math.cos(a0) * radius, yf, math.sin(a0) * radius)
                    p2 = (math.cos(a1) * radius, yf, math.sin(a1) * radius)
                    if sign < 0:
                        p1, p2 = p2, p1  # flip winding
                    for pt in (p0, p1, p2):
                        wx, wy, wz = xform(*pt)
                        buf.extend(
                            [wx, wy, wz, gold[0], gold[1], gold[2], gold[3]])

        return buf

    def _build_coin_tex_buffer(self, anim_t: float) -> array:
        """Build textured coin buffer with exact same texture coordinates as original."""
        buf = array('f')
        TWO_PI = math.pi * 2.0
        player = self.core.player
        px, pz = float(player.x), float(player.z)
        entity_r2 = 18.0 ** 2
        glow_r2 = 12.0 ** 2

        for coin in self.core.coins.values():
            if coin.taken:
                continue
            r, c = coin.cell
            cx, cz = c + 0.5, r + 0.5
            dx, dz = float(cx) - px, float(cz) - pz
            d2 = dx * dx + dz * dz
            if d2 > entity_r2:
                continue

            bob = 0.06 * math.sin(anim_t * 1.6 + r * 0.37 + c * 0.51)
            spin = (anim_t * 3.0) % TWO_PI
            cy = 1.22 + bob

            cos_s, sin_s = math.cos(spin), math.sin(spin)

            def xform(lx, ly, lz):
                ax, ay, az = lx, -lz, ly
                wx = ax * cos_s + az * sin_s
                wz = -ax * sin_s + az * cos_s
                return cx + wx, cy + ay, cz + wz

            thickness = 0.04
            radius = 0.14
            inner_r = radius * 0.92
            segments = 24 if d2 <= glow_r2 else 16
            y1 = thickness / 2.0 + 0.001  # Slight offset for textured layer
            y0 = -thickness / 2.0 - 0.001

            for sign, yf in ((1, y1), (-1, y0)):
                for i in range(segments):
                    a0 = (i / segments) * TWO_PI
                    a1 = ((i + 1) / segments) * TWO_PI
                    p0 = (0.0, yf, 0.0, 0.5, 0.5)  # Center with tex coords
                    p1 = (math.cos(a0) * inner_r, yf, math.sin(a0) * inner_r,
                          0.5 + 0.48 * math.cos(a0), 0.5 + 0.48 * math.sin(a0))
                    p2 = (math.cos(a1) * inner_r, yf, math.sin(a1) * inner_r,
                          0.5 + 0.48 * math.cos(a1), 0.5 + 0.48 * math.sin(a1))
                    if sign < 0:
                        p1, p2 = p2, p1  # flip winding

                    for pt in (p0, p1, p2):
                        wx, wy, wz = xform(pt[0], pt[1], pt[2])
                        buf.extend([wx, wy, wz, pt[3], pt[4]])  # x,y,z,u,v

        return buf

    def _build_glow_buffer(self, anim_t: float) -> array:
        """Build additive glow buffer preserving exact radial_sprite_glow parameters."""
        buf = array('f')
        TWO_PI = math.pi * 2.0
        player = self.core.player
        px, pz = float(player.x), float(player.z)
        entity_r2 = 18.0 ** 2
        glow_r2 = 12.0 ** 2

        yaw = float(getattr(player, 'yaw', 0.0) or 0.0)
        right_x = math.cos(yaw)
        right_z = -math.sin(yaw)

        for coin in self.core.coins.values():
            if coin.taken:
                continue
            r, c = coin.cell
            cx, cz = c + 0.5, r + 0.5
            dx, dz = float(cx) - px, float(cz) - pz
            d2 = dx * dx + dz * dz
            if d2 > entity_r2:
                continue

            if d2 <= glow_r2:
                bob = 0.06 * math.sin(anim_t * 1.6 + r * 0.37 + c * 0.51)
                pulse = 0.16 + 0.06 * \
                    math.sin(anim_t * 2.2 + r * 0.17 + c * 0.23)
                cy = 1.22 + bob

                glow_radius = 0.34
                glow_color = (1.0, 0.90, 0.35)

                buf.extend([cx, cy, cz, glow_color[0],
                           glow_color[1], glow_color[2], pulse])

                for i in range(29):
                    a = (i / 28) * TWO_PI
                    x = math.cos(a) * glow_radius
                    y = math.sin(a) * glow_radius
                    wx = cx + x * right_x
                    wz = cz + x * right_z
                    buf.extend([wx, cy + y, wz, glow_color[0],
                               glow_color[1], glow_color[2], 0.0])

        return buf

    def _draw_coin_geometries(self, coin_buffer: array) -> None:
        """Draw coin geometries with exact OpenGL state as original."""
        if self._coin_geom_vbo is None:
            vbo = glGenBuffers(1)
            self._coin_geom_vbo = int(vbo) if vbo else None
            vbo = glGenBuffers(1)
            self._coin_tex_vbo = int(vbo) if vbo else None
            vbo = glGenBuffers(1)
            self._glow_additive_vbo = int(vbo) if vbo else None

        if not coin_buffer or not self._coin_geom_vbo:
            return

        data = coin_buffer.tobytes()
        stride = 7 * 4  # 7 floats × 4 bytes

        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_COLOR_ARRAY)

        glBindBuffer(GL_ARRAY_BUFFER, self._coin_geom_vbo)
        glBufferData(GL_ARRAY_BUFFER, len(data), data, GL_STREAM_DRAW)
        glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
        glColorPointer(4, GL_FLOAT, stride, ctypes.c_void_p(12))
        glDrawArrays(GL_TRIANGLES, 0, len(coin_buffer) // 7)

        glDisableClientState(GL_COLOR_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def _draw_coin_textures(self, tex_buffer: array) -> None:
        """Draw coin textures with exact OpenGL state as original."""
        if not tex_buffer or not self._coin_tex_vbo or not self._tex_coin:
            return

        data = tex_buffer.tobytes()
        stride = 5 * 4  # 5 floats × 4 bytes

        glDisable(GL_LIGHTING)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, self._tex_coin)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_TEXTURE_COORD_ARRAY)

        glBindBuffer(GL_ARRAY_BUFFER, self._coin_tex_vbo)
        glBufferData(GL_ARRAY_BUFFER, len(data), data, GL_STREAM_DRAW)
        glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
        glTexCoordPointer(2, GL_FLOAT, stride, ctypes.c_void_p(12))
        glColor4f(1.0, 1.0, 1.0, 0.98)  # White color for textured rendering
        glDrawArrays(GL_TRIANGLES, 0, len(tex_buffer) // 5)

        glDisableClientState(GL_TEXTURE_COORD_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)
        glBindTexture(GL_TEXTURE_2D, 0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def _draw_additive_glows(self, glow_buffer: array) -> None:
        """Draw additive glows with exact OpenGL state as original."""
        if not glow_buffer or not self._glow_additive_vbo:
            return

        data = glow_buffer.tobytes()
        stride = 7 * 4  # 7 floats × 4 bytes

        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(False)
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_COLOR_ARRAY)

        glBindBuffer(GL_ARRAY_BUFFER, self._glow_additive_vbo)
        glBufferData(GL_ARRAY_BUFFER, len(data), data, GL_STREAM_DRAW)
        glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
        glColorPointer(4, GL_FLOAT, stride, ctypes.c_void_p(12))

        vertices_per_glow = 30
        glow_count = len(glow_buffer) // (7 * vertices_per_glow)
        for i in range(glow_count):
            offset = i * vertices_per_glow
            glDrawArrays(GL_TRIANGLE_FAN, offset, vertices_per_glow)

        glDepthMask(True)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDisableClientState(GL_COLOR_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def _build_spikes_buffer(self, anim_t: float) -> array:
        """Build spike geometry buffer with exact same math as Kivy."""
        buf = array('f')
        player = self.core.player
        px, pz = float(player.x), float(player.z)
        entity_r2 = 18.0 ** 2

        h_factor = float(self.core.spike_height_factor()) if hasattr(
            self.core, 'spike_height_factor') else 0.0

        for sp in getattr(self.core, 'spikes', []):
            r, c = sp.cell
            cx, cz = c + 0.5, r + 0.5
            dx, dz = float(cx) - px, float(cz) - pz
            d2 = dx * dx + dz * dz
            if d2 > entity_r2:
                continue

            height = 0.85 * h_factor
            if height <= 0.02:
                continue

            base = 0.18
            RED = (0.85, 0.15, 0.15, 1.0) if sp.active else (
                0.45, 0.12, 0.12, 1.0)
            y_base = 0.01
            y_tip = height

            for i in range(8):
                a0 = (i / 8) * (2.0 * math.pi)
                a1 = ((i + 1) / 8) * (2.0 * math.pi)
                x0 = cx + math.cos(a0) * base
                z0 = cz + math.sin(a0) * base
                x1 = cx + math.cos(a1) * base
                z1 = cz + math.sin(a1) * base

                for (lx, ly, lz) in [(x0, y_base, z0), (x1, y_base, z1), (cx, y_base, cz)]:
                    buf.extend([lx, ly, lz, *RED])

            for i in range(8):
                a0 = (i / 8) * (2.0 * math.pi)
                a1 = ((i + 1) / 8) * (2.0 * math.pi)
                x0 = cx + math.cos(a0) * base
                z0 = cz + math.sin(a0) * base
                x1 = cx + math.cos(a1) * base
                z1 = cz + math.sin(a1) * base

                for (lx, ly, lz) in [(x0, y_base, z0), (x1, y_base, z1), (cx, y_tip, cz)]:
                    buf.extend([lx, ly, lz, *RED])

        return buf

    def _build_platforms_buffer(self, anim_t: float) -> array:
        """Build platform geometry buffer with exact same math as Kivy."""
        buf = array('f')
        player = self.core.player
        px, pz = float(player.x), float(player.z)
        entity_r2 = 18.0 ** 2

        BROWN = (0.6, 0.4, 0.2, 1.0)
        DARK = (0.4, 0.3, 0.15, 1.0)

        for plat in getattr(self.core, 'platforms', []):
            r, c = plat.cell
            cx, cz = c + 0.5, r + 0.5
            dx, dz = float(cx) - px, float(cz) - pz
            d2 = dx * dx + dz * dz
            if d2 > entity_r2:
                continue

            cy = plat.y_offset

            sx, sy, sz = 0.4, 0.05, 0.4
            x0, x1 = cx - sx, cx + sx
            y0, y1 = cy, cy + sy * 2  # sy=0.05, so height is 0.1 total
            z0, z1 = cz - sz, cz + sz

            for (lx, ly, lz) in [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z0), (x1, y1, z1), (x0, y1, z1)]:
                buf.extend([lx, ly, lz, *BROWN])

            for (lx, ly, lz) in [(x0, y0, z0), (x0, y0, z1), (x1, y0, z1), (x0, y0, z0), (x1, y0, z1), (x1, y0, z0)]:
                buf.extend([lx, ly, lz, *DARK])

            for (lx, ly, lz) in [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y0, z1), (x1, y1, z1), (x0, y1, z1)]:
                buf.extend([lx, ly, lz, *BROWN])

            for (lx, ly, lz) in [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x0, y0, z0), (x1, y1, z0), (x1, y0, z0)]:
                buf.extend([lx, ly, lz, *BROWN])

            for (lx, ly, lz) in [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y0, z0), (x0, y1, z1), (x0, y1, z0)]:
                buf.extend([lx, ly, lz, *BROWN])

            for (lx, ly, lz) in [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z0), (x1, y1, z1), (x1, y0, z1)]:
                buf.extend([lx, ly, lz, *BROWN])

        return buf

    def _draw_spikes(self, spike_buffer: array) -> None:
        """Draw spikes with exact OpenGL state as original."""
        if self._spikes_vbo is None:
            vbo = glGenBuffers(1)
            self._spikes_vbo = int(vbo) if vbo else None

        if not spike_buffer or not self._spikes_vbo:
            return

        data = spike_buffer.tobytes()
        stride = 7 * 4  # 7 floats × 4 bytes

        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_COLOR_ARRAY)

        glBindBuffer(GL_ARRAY_BUFFER, self._spikes_vbo)
        glBufferData(GL_ARRAY_BUFFER, len(data), data, GL_STREAM_DRAW)
        glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
        glColorPointer(4, GL_FLOAT, stride, ctypes.c_void_p(12))
        glDrawArrays(GL_TRIANGLES, 0, len(spike_buffer) // 7)

        glDisableClientState(GL_COLOR_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def _draw_platforms(self, platform_buffer: array) -> None:
        """Draw platforms with exact OpenGL state as original."""
        if self._platforms_vbo is None:
            vbo = glGenBuffers(1)
            self._platforms_vbo = int(vbo) if vbo else None

        if not platform_buffer or not self._platforms_vbo:
            return

        data = platform_buffer.tobytes()
        stride = 7 * 4  # 7 floats × 4 bytes

        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_COLOR_ARRAY)

        glBindBuffer(GL_ARRAY_BUFFER, self._platforms_vbo)
        glBufferData(GL_ARRAY_BUFFER, len(data), data, GL_STREAM_DRAW)
        glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
        glColorPointer(4, GL_FLOAT, stride, ctypes.c_void_p(12))
        glDrawArrays(GL_TRIANGLES, 0, len(platform_buffer) // 7)

        glDisableClientState(GL_COLOR_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def _build_gates_buffer(self, anim_t: float) -> array:
        """Build gate geometry buffer with exact same math as Kivy."""
        buf = array('f')
        player = self.core.player
        px, pz = float(player.x), float(player.z)
        entity_r2 = 18.0 ** 2

        GRAY = (0.70, 0.70, 0.75, 1.0)
        CB = (0.65, 0.65, 0.70, 1.0)

        wall_h = float(self.core.wall_height)
        for gate in self.core.gates.values():
            for (r, c) in gate.cells:
                cx, cz = c + 0.5, r + 0.5
                dx, dz = float(cx) - px, float(cz) - pz
                d2 = dx * dx + dz * dz
                if d2 > entity_r2:
                    continue

                gx, gy_center, gz = cx, wall_h / 2.0, cz
                bar_h = wall_h
                bar_y_center = gy_center + gate.y_offset
                is_jail = gate.id == 'jail'

                for i in range(-2, 3):
                    if is_jail:
                        bx = gx + i * 0.18
                        bz = gz
                    else:
                        bx = gx
                        bz = gz + i * 0.18

                    sx, sy, sz = 0.035, bar_h * 0.5, 0.06
                    x0, x1 = bx - sx, bx + sx
                    y0, y1 = bar_y_center - sy, bar_y_center + sy
                    z0, z1 = bz - sz, bz + sz

                    for (lx, ly, lz) in [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y0, z1), (x1, y1, z1), (x0, y1, z1)]:
                        buf.extend([lx, ly, lz, *GRAY])
                    for (lx, ly, lz) in [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x0, y0, z0), (x1, y1, z0), (x1, y0, z0)]:
                        buf.extend([lx, ly, lz, *GRAY])
                    for (lx, ly, lz) in [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y0, z0), (x0, y1, z1), (x0, y1, z0)]:
                        buf.extend([lx, ly, lz, *GRAY])
                    for (lx, ly, lz) in [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z0), (x1, y1, z1), (x1, y0, z1)]:
                        buf.extend([lx, ly, lz, *GRAY])
                    for (lx, ly, lz) in [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z0), (x1, y1, z1), (x0, y1, z1)]:
                        buf.extend([lx, ly, lz, *GRAY])
                    for (lx, ly, lz) in [(x0, y0, z0), (x0, y0, z1), (x1, y0, z1), (x0, y0, z0), (x1, y0, z1), (x1, y0, z0)]:
                        buf.extend([lx, ly, lz, *GRAY])

                cb_y = bar_y_center + bar_h * 0.42
                if is_jail:
                    sx, sy, sz = 0.47, 0.06, 0.08
                else:
                    sx, sy, sz = 0.08, 0.06, 0.47

                x0, x1 = gx - sx, gx + sx
                y0, y1 = cb_y - sy, cb_y + sy
                z0, z1 = gz - sz, gz + sz

                for (lx, ly, lz) in [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y0, z1), (x1, y1, z1), (x0, y1, z1)]:
                    buf.extend([lx, ly, lz, *CB])
                for (lx, ly, lz) in [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x0, y0, z0), (x1, y1, z0), (x1, y0, z0)]:
                    buf.extend([lx, ly, lz, *CB])
                    for (lx, ly, lz) in [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y0, z0), (x0, y1, z1), (x0, y1, z0)]:
                        buf.extend([lx, ly, lz, *CB])
                    for (lx, ly, lz) in [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z0), (x1, y1, z1), (x1, y0, z1)]:
                        buf.extend([lx, ly, lz, *CB])
                    for (lx, ly, lz) in [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z0), (x1, y1, z1), (x0, y1, z1)]:
                        buf.extend([lx, ly, lz, *CB])
                    for (lx, ly, lz) in [(x0, y0, z0), (x0, y0, z1), (x1, y0, z1), (x0, y0, z0), (x1, y0, z1), (x1, y0, z0)]:
                        buf.extend([lx, ly, lz, *CB])

        return buf

    def _draw_gates(self, gate_buffer: array) -> None:
        """Draw gates with exact OpenGL state as original."""
        if self._gates_vbo is None:
            vbo = glGenBuffers(1)
            self._gates_vbo = int(vbo) if vbo else None

        if not gate_buffer or not self._gates_vbo:
            return

        data = gate_buffer.tobytes()
        stride = 7 * 4  # 7 floats × 4 bytes

        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_COLOR_ARRAY)

        glBindBuffer(GL_ARRAY_BUFFER, self._gates_vbo)
        glBufferData(GL_ARRAY_BUFFER, len(data), data, GL_STREAM_DRAW)
        glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
        glColorPointer(4, GL_FLOAT, stride, ctypes.c_void_p(12))
        glDrawArrays(GL_TRIANGLES, 0, len(gate_buffer) // 7)

        glDisableClientState(GL_COLOR_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def _build_key_fragments_buffer(self, anim_t: float) -> array:
        """Build key fragment geometry buffer with exact same math as wxPython immediate mode."""
        buf = array('f')
        player = self.core.player
        px, pz = float(player.x), float(player.z)
        entity_r2 = 18.0 ** 2
        glow_r2 = 3.0 ** 2

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
            bob = 0.08 * math.sin(anim_t * 2.4 + seed)
            spin = (anim_t * 140.0 + seed * 37.0) % 360.0

            key_x, key_y, key_z = cx, base_y + bob, cz

            spin_rad = math.radians(spin)
            scale = 1.05

            ring_cx = key_x + 0.23
            ring_cy = key_y + 0.06
            outer_r, inner_r, thickness = 0.16, 0.11, 0.035
            TWO_PI = math.pi * 2

            for i in range(24):
                a0, a1 = TWO_PI * (i / 24), TWO_PI * ((i + 1) / 24)
                c0, s0, c1, s1 = math.cos(a0), math.sin(
                    a0), math.cos(a1), math.sin(a1)

                def transform_vertex(x, y, z):
                    x *= scale
                    y *= scale
                    z *= scale
                    x_rot = -y
                    y_rot = x
                    z_rot = z
                    x_final = x_rot * \
                        math.cos(spin_rad) + z_rot * math.sin(spin_rad)
                    y_final = y_rot
                    z_final = -x_rot * \
                        math.sin(spin_rad) + z_rot * math.cos(spin_rad)
                    return (key_x + x_final, key_y + y_final, key_z + z_final)

                for (lx, ly, lz) in [
                    (ring_cx + outer_r*c0, ring_cy -
                     thickness, key_z + outer_r*s0),
                    (ring_cx + outer_r*c1, ring_cy -
                     thickness, key_z + outer_r*s1),
                    (ring_cx + outer_r*c1, ring_cy +
                     thickness, key_z + outer_r*s1),
                    (ring_cx + outer_r*c0, ring_cy -
                     thickness, key_z + outer_r*s0),
                    (ring_cx + outer_r*c1, ring_cy +
                     thickness, key_z + outer_r*s1),
                    (ring_cx + outer_r*c0, ring_cy + thickness, key_z + outer_r*s0)
                ]:
                    vx, vy, vz = transform_vertex(
                        lx - key_x, ly - key_y, lz - key_z)
                    buf.extend([vx, vy, vz, *base])

                for (lx, ly, lz) in [
                    (ring_cx + inner_r*c1, ring_cy -
                     thickness, key_z + inner_r*s1),
                    (ring_cx + inner_r*c0, ring_cy -
                     thickness, key_z + inner_r*s0),
                    (ring_cx + inner_r*c0, ring_cy +
                     thickness, key_z + inner_r*s0),
                    (ring_cx + inner_r*c1, ring_cy -
                     thickness, key_z + inner_r*s1),
                    (ring_cx + inner_r*c0, ring_cy +
                     thickness, key_z + inner_r*s0),
                    (ring_cx + inner_r*c1, ring_cy + thickness, key_z + inner_r*s1)
                ]:
                    vx, vy, vz = transform_vertex(
                        lx - key_x, ly - key_y, lz - key_z)
                    buf.extend([vx, vy, vz, *base])

                for (lx, ly, lz) in [
                    (ring_cx + inner_r*c0, ring_cy +
                     thickness, key_z + inner_r*s0),
                    (ring_cx + inner_r*c1, ring_cy +
                     thickness, key_z + inner_r*s1),
                    (ring_cx + outer_r*c1, ring_cy +
                     thickness, key_z + outer_r*s1),
                    (ring_cx + inner_r*c0, ring_cy +
                     thickness, key_z + inner_r*s0),
                    (ring_cx + outer_r*c1, ring_cy +
                     thickness, key_z + outer_r*s1),
                    (ring_cx + outer_r*c0, ring_cy + thickness, key_z + outer_r*s0)
                ]:
                    vx, vy, vz = transform_vertex(
                        lx - key_x, ly - key_y, lz - key_z)
                    buf.extend([vx, vy, vz, *base])

                for (lx, ly, lz) in [
                    (ring_cx + outer_r*c0, ring_cy -
                     thickness, key_z + outer_r*s0),
                    (ring_cx + outer_r*c1, ring_cy -
                     thickness, key_z + outer_r*s1),
                    (ring_cx + inner_r*c1, ring_cy -
                     thickness, key_z + inner_r*s1),
                    (ring_cx + outer_r*c0, ring_cy -
                     thickness, key_z + outer_r*s0),
                    (ring_cx + outer_r*c1, ring_cy -
                     thickness, key_z + outer_r*s1),
                    (ring_cx + inner_r*c0, ring_cy - thickness, key_z + inner_r*s0)
                ]:
                    vx, vy, vz = transform_vertex(
                        lx - key_x, ly - key_y, lz - key_z)
                    buf.extend([vx, vy, vz, *base])

            shaft_x, shaft_y, shaft_z = key_x - 0.12, key_y + 0.06, key_z
            sx, sy, sz = 0.26, 0.03, 0.04  # Half of glScalef(0.52, 0.06, 0.08)
            x0, x1 = shaft_x - sx, shaft_x + sx
            y0, y1 = shaft_y - sy, shaft_y + sy
            z0, z1 = shaft_z - sz, shaft_z + sz

            for (lx, ly, lz) in [
                (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0,
                                                           # Front
                                                           y0, z1), (x1, y1, z1), (x0, y1, z1),
                (x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x0,
                                                           # Back
                                                           y0, z0), (x1, y1, z0), (x1, y0, z0),
                (x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0,
                                                           # Left
                                                           y0, z0), (x0, y1, z1), (x0, y1, z0),
                (x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1,
                                                           # Right
                                                           y0, z0), (x1, y1, z1), (x1, y0, z1),
                (x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0,
                                                           # Top
                                                           y1, z0), (x1, y1, z1), (x0, y1, z1),
                (x0, y0, z0), (x0, y0, z1), (x1, y0, z1), (x0,
                                                           # Bottom
                                                           y0, z0), (x1, y0, z1), (x1, y0, z0)
            ]:
                vx, vy, vz = transform_vertex(
                    lx - key_x, ly - key_y, lz - key_z)
                buf.extend([vx, vy, vz, *base])

            for tx, th in [(-0.34, 0.12), (-0.25, 0.09), (-0.18, 0.07)]:
                tooth_x, tooth_y, tooth_z = key_x + tx, key_y + 0.02, key_z
                # Half of glScalef(0.06, th, 0.08)
                sx, sy, sz = 0.03, th * 0.5, 0.04
                x0, x1 = tooth_x - sx, tooth_x + sx
                y0, y1 = tooth_y - sy, tooth_y + sy
                z0, z1 = tooth_z - sz, tooth_z + sz

                for (lx, ly, lz) in [
                    (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0,
                                                               # Front
                                                               y0, z1), (x1, y1, z1), (x0, y1, z1),
                    (x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x0,
                                                               # Back
                                                               y0, z0), (x1, y1, z0), (x1, y0, z0),
                    (x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0,
                                                               # Left
                                                               y0, z0), (x0, y1, z1), (x0, y1, z0),
                    (x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1,
                                                               # Right
                                                               y0, z0), (x1, y1, z1), (x1, y0, z1),
                    (x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0,
                                                               # Top
                                                               y1, z0), (x1, y1, z1), (x0, y1, z1),
                    (x0, y0, z0), (x0, y0, z1), (x1, y0, z1), (x0,
                                                               # Bottom
                                                               y0, z0), (x1, y0, z1), (x1, y0, z0)
                ]:
                    vx, vy, vz = transform_vertex(
                        lx - key_x, ly - key_y, lz - key_z)
                    buf.extend([vx, vy, vz, *base])

        return buf

    def _draw_key_fragments(self, key_buffer: array) -> None:
        """Draw key fragments with exact OpenGL state as original immediate mode."""
        if self._key_fragments_vbo is None:
            vbo = glGenBuffers(1)
            self._key_fragments_vbo = int(vbo) if vbo else None

        if not key_buffer or not self._key_fragments_vbo:
            return

        data = key_buffer.tobytes()
        stride = 7 * 4  # 7 floats × 4 bytes

        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_COLOR_ARRAY)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        glBindBuffer(GL_ARRAY_BUFFER, self._key_fragments_vbo)
        glBufferData(GL_ARRAY_BUFFER, len(data), data, GL_STREAM_DRAW)
        glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
        glColorPointer(4, GL_FLOAT, stride, ctypes.c_void_p(12))
        glDrawArrays(GL_TRIANGLES, 0, len(key_buffer) // 7)

        glDisableClientState(GL_COLOR_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def _build_ghosts_buffer(self, anim_t: float) -> array:
        """Build ghost geometry buffer with exact same math as Kivy."""
        buf = array('f')
        player = self.core.player
        px, pz = float(player.x), float(player.z)
        entity_r2 = 18.0 ** 2

        ghost_colors = {
            1: (1.0, 0.35, 0.20, 0.82),
            2: (0.30, 1.0, 0.55, 0.82),
            3: (0.45, 0.65, 1.0, 0.82),
            4: (1.0, 0.85, 0.25, 0.82),
            5: (0.95, 0.35, 1.0, 0.82),
        }

        segments = 26 if self._fast_mode else 40
        body_layers = 11
        tail_layers = 8
        TWO_PI = math.pi * 2.0

        for g in self.core.ghosts.values():
            gx, gz = float(g.x), float(g.z)
            if (gx - px) ** 2 + (gz - pz) ** 2 > entity_r2:
                continue

            s = float(getattr(g, 'size_scale', 1.0) or 1.0)
            bob = 0.05 * math.sin(anim_t * 2.0 + g.id)
            wobble = 0.06 * math.sin(anim_t * 4.6 + g.id * 0.7)
            y_raise = 0.18 + 0.22 * max(0.0, s - 1.0)

            base_col = ghost_colors.get(g.id, (1.0, 0.55, 0.15, 0.92))
            col = (base_col[0], base_col[1], base_col[2], 0.92)

            yaw_g = float(getattr(g, 'yaw', 0.0) or 0.0)
            sx, sy, sz = 2.10 * s, 2.75 * s, 2.10 * s
            gy = 1.15 + y_raise + bob + wobble

            def build_ghost_vertex(x, y, z):
                return (x, y, z)

            r = 0.20 * s  # Kivy: r = 0.20 * scale

            def y_and_r(t):
                if t < 0.5:
                    return r * 0.62 * math.cos(t * math.pi), r * 0.95 * math.sin(t * math.pi)
                return -r * 0.25 * (t - 0.5) * 2.0, r * 0.95

            temp_vertices = []

            for layer in range(1, body_layers):
                y_prev, r_prev = y_and_r((layer - 1) / (body_layers - 1))
                y_curr, r_curr = y_and_r(layer / (body_layers - 1))
                for i in range(segments):
                    a0 = (i / segments) * TWO_PI
                    a1 = ((i + 1) / segments) * TWO_PI
                    ca0, sa0 = math.cos(a0), math.sin(a0)
                    ca1, sa1 = math.cos(a1), math.sin(a1)

                    p0 = build_ghost_vertex(
                        ca0 * r_prev, 0.0 + y_prev, sa0 * r_prev)  # cy=0
                    p1 = build_ghost_vertex(
                        ca1 * r_prev, 0.0 + y_prev, sa1 * r_prev)  # cy=0
                    p2 = build_ghost_vertex(
                        ca1 * r_curr, 0.0 + y_curr, sa1 * r_curr)  # cy=0
                    p3 = build_ghost_vertex(
                        ca0 * r_curr, 0.0 + y_curr, sa0 * r_curr)  # cy=0

                    for p in [p0, p1, p2]:
                        temp_vertices.append(p)
                    for p in [p0, p2, p3]:
                        temp_vertices.append(p)

            for layer in range(tail_layers):
                layer_ratio = layer / tail_layers
                prev_ratio = (layer - 1) / tail_layers
                base_r = r * 0.95 * (1.0 - layer_ratio * 0.35)
                wave_amp = r * (0.08 + 0.14 * layer_ratio)
                # Kivy: cy - r*0.52 - layer_ratio*r*0.48 (cy=0)
                y_curr_abs = -r * 0.52 - layer_ratio * r * 0.48

                if layer == 0:
                    y_prev_abs = -r * 0.25  # Kivy: cy - r*0.25 (cy=0)
                    pr_prev = r * 0.95
                else:
                    # Kivy: cy - r*0.52 - prev_ratio*r*0.48 (cy=0)
                    y_prev_abs = -r * 0.52 - prev_ratio * r * 0.48
                    pr_prev = r * 0.95 * (1.0 - prev_ratio * 0.35)
                prev_amp = r * (0.08 + 0.14 * prev_ratio)

                for i in range(segments):
                    a = (i / segments) * TWO_PI
                    a1 = ((i + 1) / segments) * TWO_PI
                    ca0, sa0 = math.cos(a), math.sin(a)
                    ca1, sa1 = math.cos(a1), math.sin(a1)

                    sk_c0 = (math.sin(a * 3.0 + anim_t * 2.4 + layer * 0.55) * wave_amp
                             + math.sin(a * 7.0 - anim_t * 1.7 + layer * 0.35) * (wave_amp * 0.55))
                    sk_c1 = (math.sin(a1 * 3.0 + anim_t * 2.4 + layer * 0.55) * wave_amp
                             + math.sin(a1 * 7.0 - anim_t * 1.7 + layer * 0.35) * (wave_amp * 0.55))
                    if layer == 0:
                        sk_p0 = sk_p1 = 0.0
                    else:
                        sk_p0 = (math.sin(a * 3.0 + anim_t * 2.4 + (layer - 1) * 0.55) * prev_amp
                                 + math.sin(a * 7.0 - anim_t * 1.7 + (layer - 1) * 0.35) * (prev_amp * 0.55))
                        sk_p1 = (math.sin(a1 * 3.0 + anim_t * 2.4 + (layer - 1) * 0.55) * prev_amp
                                 + math.sin(a1 * 7.0 - anim_t * 1.7 + (layer - 1) * 0.35) * (prev_amp * 0.55))

                    rc0 = max(r * 0.02, base_r + sk_c0)
                    rc1 = max(r * 0.02, base_r + sk_c1)
                    rp0 = max(r * 0.02, pr_prev + sk_p0)
                    rp1 = max(r * 0.02, pr_prev + sk_p1)

                    p0 = build_ghost_vertex(ca0 * rp0, y_prev_abs, sa0 * rp0)
                    p1 = build_ghost_vertex(ca1 * rp1, y_prev_abs, sa1 * rp1)
                    p2 = build_ghost_vertex(ca1 * rc1, y_curr_abs, sa1 * rc1)
                    p3 = build_ghost_vertex(ca0 * rc0, y_curr_abs, sa0 * rc0)

                    for p in [p0, p1, p2]:
                        temp_vertices.append(p)
                    for p in [p0, p2, p3]:
                        temp_vertices.append(p)

            eye_y = r * 0.22
            eye_z_f = r * 1.05
            eye_x_o = r * 0.34
            ew = r * 0.22
            eh = r * 0.28
            BLACK = (0.06, 0.06, 0.08, 0.96)

            for ex in (-eye_x_o, eye_x_o):
                x0, x1 = ex - ew, ex + ew
                y0, y1 = eye_y - eh, eye_y + eh
                ez = 0.0 + eye_z_f  # Kivy: ez = cz + eye_z_f (cz=0)

                for (lx, ly) in [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]:
                    vx, vy, vz = build_ghost_vertex(lx, ly, ez)
                    temp_vertices.append((vx, vy, vz))

            for i, (vx, vy, vz) in enumerate(temp_vertices):
                # Kivy: sx,sy,sz = 2.10*s, 2.75*s, 2.10*s
                x, y, z = vx * 2.10, vy * 2.75, vz * 2.10
                c = math.cos(yaw_g)  # yaw_g is already in radians
                s = math.sin(yaw_g)
                x_rot = x * c + z * s
                z_rot = -x * s + z * c
                final_x, final_y, final_z = x_rot + gx, y + gy, z_rot + gz

                if i >= len(temp_vertices) - 12:  # Eyes are last 12 vertices
                    vertex_color = BLACK
                else:
                    vertex_color = col

                buf.extend([final_x, final_y, final_z, *vertex_color])

        return buf

    def _draw_ghosts(self, ghost_buffer: array) -> None:
        """Draw ghosts with exact OpenGL state as original."""
        if self._ghosts_vbo is None:
            vbo = glGenBuffers(1)
            self._ghosts_vbo = int(vbo) if vbo else None

        if not ghost_buffer or not self._ghosts_vbo:
            return

        data = ghost_buffer.tobytes()
        stride = 7 * 4  # 7 floats × 4 bytes

        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_COLOR_ARRAY)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        glDepthMask(False)

        glBindBuffer(GL_ARRAY_BUFFER, self._ghosts_vbo)
        glBufferData(GL_ARRAY_BUFFER, len(data), data, GL_STREAM_DRAW)
        glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
        glColorPointer(4, GL_FLOAT, stride, ctypes.c_void_p(12))
        glDrawArrays(GL_TRIANGLES, 0, len(ghost_buffer) // 7)

        glDepthMask(True)  # Re-enable depth writing
        glDisableClientState(GL_COLOR_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
