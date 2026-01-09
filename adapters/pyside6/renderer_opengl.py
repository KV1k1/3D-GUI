import math
import os
from typing import List, Optional, Tuple

from PySide6.QtGui import QImage
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

        self._static_quads: List[Tuple[float, float, Optional[int], Tuple[Tuple[float, float, float, float, float], ...]]] = []

        self._anim_t = 0.0

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
        self._tex_wall = self._load_texture(os.path.join('assets', 'image.png'))
        self._tex_floor = self._load_texture(os.path.join('assets', 'path.png'))
        self._tex_coin = self._load_texture(os.path.join('assets', 'JEMA GER 1640-11.png'))

        self._build_static_geometry()

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
        self._draw_world_immediate()

    def resize(self, width: int, height: int) -> None:
        self.width = max(1, width)
        self.height = max(1, height)
        glViewport(0, 0, self.width, self.height)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(self.fov, self.width / self.height, self.near_plane, self.far_plane)

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

        for (r, c) in walls:
            cx = c + 0.5
            cz = r + 0.5
            y0 = 0.0
            y1 = wall_h
            add_quad(
                cz, cx, self._tex_wall,
                (
                    (0.0, 0.0, cx - 0.5, y0, cz - 0.5),
                    (1.0, 0.0, cx + 0.5, y0, cz - 0.5),
                    (1.0, 1.0, cx + 0.5, y1, cz - 0.5),
                    (0.0, 1.0, cx - 0.5, y1, cz - 0.5),
                ),
            )
            add_quad(
                cz, cx, self._tex_wall,
                (
                    (0.0, 0.0, cx + 0.5, y0, cz + 0.5),
                    (1.0, 0.0, cx - 0.5, y0, cz + 0.5),
                    (1.0, 1.0, cx - 0.5, y1, cz + 0.5),
                    (0.0, 1.0, cx + 0.5, y1, cz + 0.5),
                ),
            )
            add_quad(
                cz, cx, self._tex_wall,
                (
                    (0.0, 0.0, cx - 0.5, y0, cz + 0.5),
                    (1.0, 0.0, cx - 0.5, y0, cz - 0.5),
                    (1.0, 1.0, cx - 0.5, y1, cz - 0.5),
                    (0.0, 1.0, cx - 0.5, y1, cz + 0.5),
                ),
            )
            add_quad(
                cz, cx, self._tex_wall,
                (
                    (0.0, 0.0, cx + 0.5, y0, cz - 0.5),
                    (1.0, 0.0, cx + 0.5, y0, cz + 0.5),
                    (1.0, 1.0, cx + 0.5, y1, cz + 0.5),
                    (0.0, 1.0, cx + 0.5, y1, cz - 0.5),
                ),
            )
            add_quad(
                cz, cx, self._tex_wall,
                (
                    (0.0, 0.0, cx - 0.5, y1, cz + 0.5),
                    (1.0, 0.0, cx + 0.5, y1, cz + 0.5),
                    (1.0, 1.0, cx + 0.5, y1, cz - 0.5),
                    (0.0, 1.0, cx - 0.5, y1, cz - 0.5),
                ),
            )
            add_quad(
                cz, cx, self._tex_wall,
                (
                    (0.0, 0.0, cx - 0.5, y0, cz - 0.5),
                    (1.0, 0.0, cx + 0.5, y0, cz - 0.5),
                    (1.0, 1.0, cx + 0.5, y0, cz + 0.5),
                    (0.0, 1.0, cx - 0.5, y0, cz + 0.5),
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
                billboard_quad(cx, cy, cz, s, s, (color[0], color[1], color[2], a))
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
                glVertex3f(cx + math.cos(a) * radius, y, cz + math.sin(a) * radius)
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
                inner_radius = radius * 0.9995
                glBegin(GL_TRIANGLE_FAN)
                glTexCoord2f(0.5, 0.5)
                glVertex3f(0.0, y1 + 0.001, 0.0)
                for i in range(segments + 1):
                    a = (i / segments) * (2.0 * math.pi)
                    u = 0.5 + 0.5 * math.cos(a)
                    v = 0.5 + 0.5 * math.sin(a)
                    glTexCoord2f(u, v)
                    glVertex3f(math.cos(a) * inner_radius, y1 + 0.001, math.sin(a) * inner_radius)
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
                    u = 0.5 + 0.5 * math.cos(a)
                    v = 0.5 + 0.5 * math.sin(a)
                    glTexCoord2f(u, v)
                    glVertex3f(math.cos(a) * inner_radius, y0 - 0.001, math.sin(a) * inner_radius)
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
                wave_amp = 0.14 * layer_ratio
                wave = (
                    math.sin(self._anim_t * 2.2 + layer * 0.55) * wave_amp
                    + math.sin(self._anim_t * 3.1 + layer * 0.35) * wave_amp * 0.55
                )
                r_curr = base_r * (1.0 + wave)
                y_curr = -radius * 0.52 - layer_ratio * radius * 0.48

                if layer == 0:
                    # Connect tail to body
                    glBegin(GL_TRIANGLE_STRIP)
                    for i in range(segments + 1):
                        a = (i / segments) * (2.0 * math.pi)
                        ca = math.cos(a)
                        sa = math.sin(a)
                        glVertex3f(ca * radius * 0.95, -radius * 0.25, sa * radius * 0.95)
                        glVertex3f(ca * r_curr, y_curr, sa * r_curr)
                    glEnd()
                else:
                    prev_base_r = radius * 0.95 * (1.0 - prev_ratio * 0.35)
                    prev_amp = 0.14 * prev_ratio
                    prev_wave = (
                        math.sin(self._anim_t * 2.2 + (layer - 1) * 0.55) * prev_amp
                        + math.sin(self._anim_t * 3.1 + (layer - 1) * 0.35) * prev_amp * 0.55
                    )
                    r_prev = prev_base_r * (1.0 + prev_wave)
                    y_prev = -radius * 0.52 - prev_ratio * radius * 0.48

                    glBegin(GL_TRIANGLE_STRIP)
                    for i in range(segments + 1):
                        a = (i / segments) * (2.0 * math.pi)
                        ca = math.cos(a)
                        sa = math.sin(a)
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
            glColor4f(1.0, 0.84, 0.18, 0.98)
            _draw_coin_3d_mario(radius=0.14, thickness=0.04, segments=24, textured=True)
            
            glPopMatrix()
            
            # Glow effects - clean ground lighting only
            floor_glow(cx, cz, 0.015, 1.05, (1.0, 0.90, 0.35), 0.12)
            floor_glow(cx, cz, 0.016, 0.55, (1.0, 0.90, 0.35), 0.14)

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
            
            # Place KP fragment at ceiling height, others at normal height
            if frag.kind == 'KP':
                fragment_y = 4.0  # Near ceiling
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
            billboard_quad(cx, arrow_y + 0.1, cz, 1.0, 0.8, (0.2, 1.0, 0.2, 0.2))
            # Medium glow triangle
            billboard_quad(cx, arrow_y, cz, 0.8, 0.6, (0.3, 1.0, 0.3, 0.3))
            
            # Main arrow body - bright green triangle pointing down
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            
            # Draw arrow as triangle shape using multiple quads to form a downward arrow
            # Arrow shaft (longer vertical rectangle)
            billboard_quad(cx, arrow_y, cz, 0.3, 0.8, (0.2, 1.0, 0.2, 0.9))
            
            # Arrow head (wider at bottom, triangular shape)
            billboard_quad(cx, arrow_y - 0.3, cz, 0.6, 0.3, (0.2, 1.0, 0.2, 0.9))
            
            # Arrow tip (point at bottom)
            billboard_quad(cx, arrow_y - 0.5, cz, 0.2, 0.2, (0.1, 0.8, 0.1, 1.0))
            
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
            billboard_quad(0.0, 0.70, 0.0, 0.60, 0.60, (0.95, 0.85, 0.35, 0.22))
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
            soft_aura(g.x, 1.15 + bob + 0.05, g.z, 0.70, (col[0], col[1], col[2]), 0.14)

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
        glVertex3f(-base, 0.01, -base); glVertex3f(base, 0.01, -base); glVertex3f(0.0, height, 0.0)
        glVertex3f(base, 0.01, -base); glVertex3f(base, 0.01, base); glVertex3f(0.0, height, 0.0)
        glVertex3f(base, 0.01, base); glVertex3f(-base, 0.01, base); glVertex3f(0.0, height, 0.0)
        glVertex3f(-base, 0.01, base); glVertex3f(-base, 0.01, -base); glVertex3f(0.0, height, 0.0)
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
        glTexCoord2f(0.0, 0.0); glVertex3f(-0.5, -0.5, 0.5)
        glTexCoord2f(1.0, 0.0); glVertex3f(0.5, -0.5, 0.5)
        glTexCoord2f(1.0, 1.0); glVertex3f(0.5, 0.5, 0.5)
        glTexCoord2f(0.0, 1.0); glVertex3f(-0.5, 0.5, 0.5)
        # Back
        glTexCoord2f(0.0, 0.0); glVertex3f(-0.5, -0.5, -0.5)
        glTexCoord2f(1.0, 0.0); glVertex3f(-0.5, 0.5, -0.5)
        glTexCoord2f(1.0, 1.0); glVertex3f(0.5, 0.5, -0.5)
        glTexCoord2f(0.0, 1.0); glVertex3f(0.5, -0.5, -0.5)
        # Right
        glTexCoord2f(0.0, 0.0); glVertex3f(0.5, -0.5, -0.5)
        glTexCoord2f(1.0, 0.0); glVertex3f(0.5, 0.5, -0.5)
        glTexCoord2f(1.0, 1.0); glVertex3f(0.5, 0.5, 0.5)
        glTexCoord2f(0.0, 1.0); glVertex3f(0.5, -0.5, 0.5)
        # Left
        glTexCoord2f(0.0, 0.0); glVertex3f(-0.5, -0.5, -0.5)
        glTexCoord2f(1.0, 0.0); glVertex3f(-0.5, -0.5, 0.5)
        glTexCoord2f(1.0, 1.0); glVertex3f(-0.5, 0.5, 0.5)
        glTexCoord2f(0.0, 1.0); glVertex3f(-0.5, 0.5, -0.5)
        # Top
        glTexCoord2f(0.0, 0.0); glVertex3f(-0.5, 0.5, -0.5)
        glTexCoord2f(1.0, 0.0); glVertex3f(-0.5, 0.5, 0.5)
        glTexCoord2f(1.0, 1.0); glVertex3f(0.5, 0.5, 0.5)
        glTexCoord2f(0.0, 1.0); glVertex3f(0.5, 0.5, -0.5)
        # Bottom
        glTexCoord2f(0.0, 0.0); glVertex3f(-0.5, -0.5, -0.5)
        glTexCoord2f(1.0, 0.0); glVertex3f(0.5, -0.5, -0.5)
        glTexCoord2f(1.0, 1.0); glVertex3f(0.5, -0.5, 0.5)
        glTexCoord2f(0.0, 1.0); glVertex3f(-0.5, -0.5, 0.5)
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
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        glBindTexture(GL_TEXTURE_2D, 0)
        return int(tex_id)

    def _bind_texture(self, tex_id: Optional[int]) -> None:
        if tex_id is None:
            glBindTexture(GL_TEXTURE_2D, 0)
            return
        glBindTexture(GL_TEXTURE_2D, tex_id)
