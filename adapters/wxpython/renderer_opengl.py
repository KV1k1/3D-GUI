import ctypes
import math
import os
import time
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

        # Initialize text texture cache with reasonable size limit
        self._text_texture_cache: dict[tuple, tuple[int, int, int]] = {}
        self._jail_map_texture: Optional[int] = None

        # Performance optimization flags
        self._textures_loaded = False
        self._geometry_built = False

    def initialize(self) -> None:
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

    def _ensure_textures_loaded(self) -> None:
        if self._textures_loaded:
            return

        # Load textures efficiently with caching
        start_time = time.perf_counter()

        # Pre-check if files exist to avoid unnecessary processing
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

        # Optional: Log load time for debugging
        load_time = time.perf_counter() - start_time
        if load_time > 1.0:
            print(f"Textures loaded in {load_time:.2f}s")

    def _ensure_geometry_built(self) -> None:
        if self._geometry_built:
            return

        # Build geometry in a more efficient way
        start_time = time.perf_counter()

        self._build_static_geometry()
        self._build_world_vbos()
        self._geometry_built = True

        # Optional: Log build time for debugging
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
        # Visual cue for interactable jail book (ported from PySide).
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

        # Book glow marker
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(False)
        self._radial_sprite_glow(0.0, 0.70, 0.0, 0.55,
                                 (0.95, 0.85, 0.35), 0.16)
        self._radial_sprite_glow(0.0, 0.70, 0.0, 0.95,
                                 (0.95, 0.85, 0.35), 0.06)
        glDepthMask(True)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

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
        # Lazy load textures and geometry on first render
        self._ensure_textures_loaded()
        self._ensure_geometry_built()

        glEnable(GL_DEPTH_TEST)
        glEnable(GL_TEXTURE_2D)

        frozen = bool(getattr(self.core, 'simulation_frozen', False))

        # Drive small renderer-only animations (ghost bob, coin spin, etc.) from wall clock.
        # Using core.elapsed_s can stall if the update loop is paused or dt is clamped.
        now = time.perf_counter()
        if self._last_anim_perf_s is None:
            self._last_anim_perf_s = now
        dt_anim = max(0.0, float(now) - float(self._last_anim_perf_s))
        self._last_anim_perf_s = now
        if not frozen:
            self._anim_clock_s += dt_anim

        # Keep this for compatibility with any other code that might still expect it.
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

        self._draw_platforms()

        self._draw_gates()

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
        # Position lower (was 0.62, now 0.45) + bounce instead of bob
        bounce = 0.08 * math.sin(anim_t * 2.5)  # Smooth bounce animation
        cy = float(getattr(self.core, 'wall_height', 3.0)) * 0.45 + bounce

        glDisable(GL_TEXTURE_2D)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        # Pulsing alpha
        pulse = 0.75 + 0.25 * math.sin(anim_t * 3.0)

        # ── Ultra-smooth glow halo (coin-style single layer) ─────────────────────
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(False)

        # Camera vectors for glow orientation (like coins)
        yaw = float(self.core.player.yaw)
        rx = math.cos(yaw)
        rz = -math.sin(yaw)

        # Single large glow with perfect radial fade (coin technique)
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

        # ── Solid 3D arrow (visible through walls) ────────────────────────────────
        # Disable depth test to make arrow visible through walls
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)

        # Solid materials (no transparency)
        glMaterialfv(GL_FRONT_AND_BACK, GL_AMBIENT,  [0.0, 0.65, 0.20, 1.0])
        glMaterialfv(GL_FRONT_AND_BACK, GL_DIFFUSE,  [
                     0.0, 0.98, 0.35, 1.0])  # Alpha = 1.0 (solid)
        glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, [0.6, 1.0,  0.7,  1.0])
        glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION, [0.0, 0.45, 0.15, 1.0])
        glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 64.0)

        glPushMatrix()
        glTranslatef(cx, cy, cz)
        # No rotation - just bounce

        # Arrow dimensions (slightly larger for better visibility)
        shaft_r = 0.12   # shaft cylinder radius
        shaft_h = 0.60   # shaft length
        head_r = 0.30   # arrowhead cone base radius
        head_h = 0.42   # arrowhead cone height
        seg = 32     # increased smoothness

        # Arrow points DOWNWARD: tip at bottom (0, -shaft_h/2 - head_h, 0)
        shaft_top = shaft_h * 0.5          # top of shaft (y+)
        shaft_bot = -shaft_h * 0.5         # bottom of shaft / base of cone
        tip_y = shaft_bot - head_h     # tip of arrowhead

        # ── Shaft: cylinder (enhanced smoothness) ───────────────────────────────────
        glBegin(GL_TRIANGLE_STRIP)
        for i in range(seg + 1):
            a = (i / seg) * 2.0 * math.pi
            ca, sa = math.cos(a), math.sin(a)
            glNormal3f(ca, 0.0, sa)
            glVertex3f(ca * shaft_r, shaft_top, sa * shaft_r)
            glVertex3f(ca * shaft_r, shaft_bot, sa * shaft_r)
        glEnd()

        # Shaft top cap
        glBegin(GL_TRIANGLE_FAN)
        glNormal3f(0.0, 1.0, 0.0)
        glVertex3f(0.0, shaft_top, 0.0)
        for i in range(seg + 1):
            a = (i / seg) * 2.0 * math.pi
            glVertex3f(math.cos(a) * shaft_r, shaft_top, math.sin(a) * shaft_r)
        glEnd()

        # ── Arrowhead cone base cap ─────────────────────────────────────────
        glBegin(GL_TRIANGLE_FAN)
        glNormal3f(0.0, 1.0, 0.0)
        glVertex3f(0.0, shaft_bot, 0.0)
        for i in range(seg + 1):
            a = (i / seg) * 2.0 * math.pi
            glVertex3f(math.cos(a) * head_r, shaft_bot, math.sin(a) * head_r)
        glEnd()

        # ── Arrowhead cone side (smooth normals along slant) ────────────────
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

        # Reset material to default so other geometry is unaffected
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
                    # Use sector mapping like PySide version
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

            # Sector letters: compute centroid per sector id.
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

            # Exit label
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

            # Skip InitAlpha() - it sets all alpha to 0 (invisible)
            # Instead, force all alpha values to 255 (opaque) using numpy
            import numpy as np
            rgb_array = np.frombuffer(rgb_b, dtype=np.uint8).reshape(w, h, 3)
            # All pixels opaque
            alpha_array = np.full((w, h), 255, dtype=np.uint8)

            # Combine RGB and Alpha into RGBA
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
        # Ported from PySide renderer: wall-mounted "SECTOR X" signs + jail painting (sector map texture).
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
            _wall_quad(cx, cy, cz, 0.78, 0.50, str(facing))
            glEnd()

            # Canvas background
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

        # Reset texture environment and ensure proper state cleanup
        glBindTexture(GL_TEXTURE_2D, 0)
        glDisable(GL_TEXTURE_2D)
        glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE,
                  GL_MODULATE)  # reset to default
        glEnable(GL_LIGHTING)

    def _draw_entities(self, anim_t: float) -> None:
        # Minimal parity: key fragments + ghosts (ported from PySide immediate-mode entities).
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
            # Seamless circular glow oriented towards the camera.
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

        # Key fragments
        def _draw_key_3d() -> None:
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

                glVertex3f(outer_r * c0, -thickness, outer_r * s0)
                glVertex3f(outer_r * c1, -thickness, outer_r * s1)
                glVertex3f(outer_r * c1, +thickness, outer_r * s1)
                glVertex3f(outer_r * c0, +thickness, outer_r * s0)

                glVertex3f(inner_r * c1, -thickness, inner_r * s1)
                glVertex3f(inner_r * c0, -thickness, inner_r * s0)
                glVertex3f(inner_r * c0, +thickness, inner_r * s0)
                glVertex3f(inner_r * c1, +thickness, inner_r * s1)

                glVertex3f(inner_r * c0, +thickness, inner_r * s0)
                glVertex3f(inner_r * c1, +thickness, inner_r * s1)
                glVertex3f(outer_r * c1, +thickness, outer_r * s1)
                glVertex3f(outer_r * c0, +thickness, outer_r * s0)

                glVertex3f(outer_r * c0, -thickness, outer_r * s0)
                glVertex3f(outer_r * c1, -thickness, outer_r * s1)
                glVertex3f(inner_r * c1, -thickness, inner_r * s1)
                glVertex3f(inner_r * c0, -thickness, inner_r * s0)
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

        glow_r2 = max(5.0 * 5.0, (float(self._fog_end) * 0.65) ** 2)
        for frag in getattr(self.core, 'key_fragments', {}).values():
            try:
                if frag.taken:
                    continue
                r, c = frag.cell
            except Exception:
                continue

            cx = float(c) + 0.5
            cz = float(r) + 0.5
            dx = cx - px
            dz = cz - pz
            d2 = dx * dx + dz * dz
            if d2 > entity_r2:
                continue

            kind = str(getattr(frag, 'kind', '') or '')
            if kind == 'KH':
                base = (0.55, 0.95, 1.0, 0.95)
                glow_rgb = (0.65, 1.0, 1.0)
            elif kind == 'KP':
                base = (0.9, 0.65, 1.0, 0.95)
                glow_rgb = (0.95, 0.75, 1.0)
            else:
                base = (0.75, 1.0, 0.65, 0.95)
                glow_rgb = (0.85, 1.0, 0.75)

            if kind == 'KP':
                base_y = float(self.core.ceiling_height) - 0.85
            else:
                base_y = 1.18

            seed = float(sum((i + 1) * ord(ch)
                         for i, ch in enumerate(str(getattr(frag, 'id', '')))) % 997)
            bob = 0.08 * math.sin(anim_t * 2.4 + seed)
            spin_degrees = (anim_t * 140.0 + seed * 37.0) % 360.0

            glPushMatrix()
            glTranslatef(cx, base_y + bob, cz)
            glRotatef(spin_degrees, 0.0, 1.0, 0.0)
            glRotatef(90.0, 0.0, 0.0, 1.0)
            glScalef(1.05, 1.05, 1.05)

            glDisable(GL_LIGHTING)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glColor4f(base[0], base[1], base[2], base[3])
            _draw_key_3d()

            if d2 <= glow_r2:
                soft_aura(cx, base_y + bob + 0.05, cz, 0.55, glow_rgb, 0.12)

            glPopMatrix()
            glEnable(GL_LIGHTING)

        # Ghosts
        ghost_colors = {
            1: (1.0, 0.35, 0.20, 0.82),
            2: (0.30, 1.0, 0.55, 0.82),
            3: (0.45, 0.65, 1.0, 0.82),
            4: (1.0, 0.85, 0.25, 0.82),
            5: (0.95, 0.35, 1.0, 0.82),
        }

        def _draw_ghost_3d(color: Tuple[float, float, float, float]) -> None:
            from OpenGL.GL import GL_TRIANGLE_STRIP

            radius = 0.20
            segments = 26 if self._fast_mode else 40
            body_layers = 11
            tail_layers = 8

            glDisable(GL_TEXTURE_2D)
            glDisable(GL_LIGHTING)
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
                    glBegin(GL_TRIANGLE_STRIP)
                    for i in range(segments + 1):
                        a = (i / segments) * (2.0 * math.pi)
                        ca = math.cos(a)
                        sa = math.sin(a)
                        skirt = (
                            math.sin(a * 3.0 + anim_t * 2.4 +
                                     layer * 0.55) * wave_amp
                            + math.sin(a * 7.0 - anim_t * 1.7 +
                                       layer * 0.35) * (wave_amp * 0.55)
                        )
                        r_skirt = max(radius * 0.02, base_r + skirt)
                        glVertex3f(ca * radius * 0.95, -radius *
                                   0.25, sa * radius * 0.95)
                        glVertex3f(ca * r_skirt, y_curr, sa * r_skirt)
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
                            math.sin(a * 3.0 + anim_t * 2.4 +
                                     (layer - 1) * 0.55) * prev_amp
                            + math.sin(a * 7.0 - anim_t * 1.7 +
                                       (layer - 1) * 0.35) * (prev_amp * 0.55)
                        )
                        skirt_curr = (
                            math.sin(a * 3.0 + anim_t * 2.4 +
                                     layer * 0.55) * wave_amp
                            + math.sin(a * 7.0 - anim_t * 1.7 +
                                       layer * 0.35) * (wave_amp * 0.55)
                        )
                        r_prev2 = max(radius * 0.02, prev_base_r + skirt_prev)
                        r_curr2 = max(radius * 0.02, base_r + skirt_curr)
                        glVertex3f(ca * r_prev2, y_prev, sa * r_prev2)
                        glVertex3f(ca * r_curr2, y_curr, sa * r_curr2)
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

        for g in getattr(self.core, 'ghosts', {}).values():
            try:
                gx = float(getattr(g, 'x', 0.0) or 0.0)
                gz = float(getattr(g, 'z', 0.0) or 0.0)
                gid = int(getattr(g, 'id', 0) or 0)
            except Exception:
                continue

            dx = gx - px
            dz = gz - pz
            d2 = dx * dx + dz * dz
            if d2 > entity_r2:
                continue

            bob = 0.05 * math.sin(anim_t * 2.0 + gid)
            wobble = 0.06 * math.sin(anim_t * 4.6 + gid * 0.7)
            s = float(getattr(g, 'size_scale', 1.0) or 1.0)
            y_raise = 0.18 + 0.22 * max(0.0, s - 1.0)

            glPushMatrix()
            glTranslatef(gx, 1.15 + y_raise + bob + wobble, gz)
            glRotatef(math.degrees(
                float(getattr(g, 'yaw', 0.0) or 0.0)), 0.0, 1.0, 0.0)
            glScalef(2.10 * s, 2.75 * s, 2.10 * s)

            glDepthMask(False)
            _draw_ghost_3d(ghost_colors.get(gid, (1.0, 0.55, 0.15, 0.92)))
            glDepthMask(True)

            glPopMatrix()

            col = ghost_colors.get(gid, (1.0, 0.55, 0.15, 0.92))
            radial_sprite_glow(gx, 1.15 + y_raise + bob + 0.08,
                               gz, 0.55 * s, (col[0], col[1], col[2]), 0.12)
            radial_sprite_glow(gx, 1.15 + y_raise + bob + 0.08,
                               gz, 0.95 * s, (col[0], col[1], col[2]), 0.05)

        # Spike traps - ported from PySide
        spikes_data = getattr(self.core, 'spikes', [])
        if spikes_data:
            # Ensure lighting is off for glColor4f to work
            glDisable(GL_LIGHTING)
            # Get global spike height factor like PySide
            h = float(getattr(self.core, 'spike_height_factor', lambda: 1.0)())

            for spike in spikes_data:
                try:
                    # Spikes have cell=(row, col), not x,z
                    cell = getattr(spike, 'cell', (0, 0))
                    r, c = cell  # row, col like PySide
                    # Add 0.5 offset like PySide for center positioning
                    sx = float(c) + 0.5
                    sz = float(r) + 0.5
                    # Check active state like PySide
                    is_active = getattr(spike, 'active', False)
                except Exception:
                    continue

                dx = sx - px
                dz = sz - pz
                d2 = dx * dx + dz * dz
                if d2 > entity_r2:
                    continue

                glPushMatrix()
                glTranslatef(sx, 0.0, sz)

                # Color based on active state (like PySide)
                if is_active:
                    glColor4f(0.85, 0.15, 0.15, 1.0)  # Bright red when active
                else:
                    glColor4f(0.45, 0.12, 0.12, 1.0)  # Dark red when inactive

                self._draw_spike(height=0.85 * h)
                glPopMatrix()

        glEnable(GL_LIGHTING)

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

    def _build_world_vbos(self) -> None:
        # Only rebuild VBOs if they don't exist or world has changed
        if self._world_vbo_floor is not None and self._world_vbo_wall is not None:
            if hasattr(self, '_world_vbo_hash'):
                current_hash = hash(
                    (tuple(sorted(self.core.floors)), tuple(sorted(self.core.walls))))
                if current_hash == self._world_vbo_hash:
                    return

        # Clear existing VBOs (single deletion - no double delete)
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

        # Store hash to detect changes (moved from _draw_world)
        self._world_vbo_hash = hash(
            (tuple(sorted(self.core.floors)), tuple(sorted(self.core.walls))))

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

        # Cache texture IDs by path to avoid reloading
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

        # Ensure RGBA and flip vertically to match OpenGL texture coords.
        try:
            if not img.HasAlpha():
                # Create proper alpha channel - make fully opaque
                img.InitAlpha()
            else:
                # For wall/floor textures, ensure full opacity
                # For coin textures, preserve transparency
                path_lower = str(path).lower()
                if 'coin' in path_lower or 'jema' in path_lower:
                    # Keep transparency for coins
                    pass
                else:
                    # Make walls/floors fully opaque
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
            img = img.Mirror(False)
        except Exception:
            pass

        w = int(img.GetWidth())
        h = int(img.GetHeight())
        try:
            rgb = img.GetDataBuffer()
            alpha = img.GetAlphaBuffer()
            if rgb is None or alpha is None:
                return None
            # Interleave RGB + A into RGBA using numpy (40-50x faster than Python loop).
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

        # Cache the texture ID
        self._texture_cache[path] = int(tex_id)
        return int(tex_id)

    def clear_text_texture_cache(self) -> None:
        """Clear all cached text textures and delete GL textures."""
        if not self._text_texture_cache:
            return

        try:
            # Delete all GL textures
            for tex_id, _, _ in self._text_texture_cache.values():
                if tex_id and tex_id > 0:
                    glDeleteTextures([tex_id])
        except Exception:
            pass

        # Clear the cache
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

        # Limit cache size to prevent memory bloat
        if len(self._text_texture_cache) > 200:
            # Remove oldest 50 entries and delete GL textures
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

        # Measure via wx.DC.
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
            # Render WHITE text on BLACK background regardless of requested color
            # Then use luminance as alpha, and tint the RGB to the requested color
            mdc.SetBackground(wx.Brush(wx.Colour(0, 0, 0, 255)))
            mdc.Clear()
            gc = wx.GraphicsContext.Create(mdc)
            if gc is not None:
                try:
                    gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)
                except Exception:
                    pass
                # Always render in white — we'll colorize in the RGBA step
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

            # Use max channel as alpha (luminance mask) — smooth antialiasing preserved
            lum = rgb_arr.max(axis=1).astype(np.float32) / 255.0

            # Colorize: multiply white coverage by requested color
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
        # Backwards-compatible helper: return only the texture id.
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

        # Camera vectors for glow effects
        yaw = self.core.player.yaw
        right_x = math.cos(yaw)
        right_z = -math.sin(yaw)

        def radial_sprite_glow(cx: float, cy: float, cz: float, radius: float, color: Tuple[float, float, float], alpha: float) -> None:
            # Seamless circular glow oriented towards the camera (no rectangular billboard edges).
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

                # Solid base cap (full radius) to avoid any see-through ring between
                # the textured disc and the rim.
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

        for coin in self.core.coins.values():
            if coin.taken:
                continue

            r, c = coin.cell
            cx = c + 0.5
            cz = r + 0.5

            dx = float(cx) - px
            dz = float(cz) - pz
            d2 = dx * dx + dz * dz
            if d2 > entity_r2:
                continue

            spin = (anim_t * 3.0) % TWO_PI
            spin_degrees = spin * RAD_TO_DEG
            bob = 0.06 * math.sin(anim_t * 1.6 + (r * 0.37 + c * 0.51))

            glPushMatrix()
            glTranslatef(cx, 1.22 + bob, cz)
            glRotatef(spin_degrees, 0.0, 1.0, 0.0)
            glRotatef(90.0, 1.0, 0.0, 0.0)

            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            seg = 24 if d2 <= glow_r2 else 16
            _draw_coin_3d_mario(radius=0.14, thickness=0.04,
                                segments=seg, textured=True)

            glColor4f(1.0, 1.0, 1.0, 1.0)

            glPopMatrix()

            # Glow around the coin only (seamless circle, no floor spill)
            if d2 <= glow_r2:
                pulse = 0.16 + 0.06 * \
                    math.sin(anim_t * 2.2 + (r * 0.17 + c * 0.23))
                radial_sprite_glow(cx, 1.22 + bob, cz, 0.34,
                                   (1.0, 0.90, 0.35), pulse)

    def _draw_ceiling_lamps(self) -> None:
        """Draw ceiling lamps exactly like PySide version"""
        glDisable(GL_TEXTURE_2D)
        glDisable(GL_LIGHTING)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        ceil_h = float(self.core.wall_height)

        def is_floor(rr: int, cc: int) -> bool:
            return (rr, cc) in self.core.floors and (rr, cc) not in self.core.walls

        # Corridor-center lamps (for 3-wide corridors, place on the middle tile).
        # We sample candidates and then thin them out by spacing.
        lamp_candidates = []
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
        lamps = []
        min_sep2 = 8.0 * 8.0
        for rc in lamp_candidates:
            if all(((rc[0] - lr) ** 2 + (rc[1] - lc) ** 2) >= min_sep2 for (lr, lc) in lamps):
                lamps.append(rc)
            if len(lamps) >= 140:
                break

        # Camera vectors for billboard effects
        yaw = self.core.player.yaw
        right_x = math.cos(yaw)
        right_z = -math.sin(yaw)

        def floor_glow(cx: float, cz: float, y: float, radius: float, color: Tuple[float, float, float], alpha: float) -> None:
            # Camera-independent circular glow projected onto the floor.
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

    def _draw_spike(self, height: float) -> None:
        """Draw a single spike trap - ported from PySide."""
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
