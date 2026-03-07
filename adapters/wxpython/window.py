import json
import math
import os
import time
from typing import Optional

import wx
import wx.adv
from wx import glcanvas

from OpenGL.GL import (
    GL_BLEND,
    GL_DEPTH_TEST,
    GL_LIGHTING,
    GL_MODELVIEW,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_PROJECTION,
    GL_QUADS,
    GL_TRIANGLE_FAN,
    GL_SRC_ALPHA,
    GL_TEXTURE_2D,
    glBegin,
    glBlendFunc,
    glColor4f,
    glDisable,
    glEnable,
    glEnd,
    glLoadIdentity,
    glMatrixMode,
    glOrtho,
    glPopMatrix,
    glPushMatrix,
    glTexCoord2f,
    glVertex2f,
 )

from core.game_core import GameCore
from .renderer_opengl import OpenGLRenderer


HUD_FS_SMALL = 14
HUD_FS_MED = 16
HUD_FS_PAUSE_TITLE = 30
HUD_COL_WHITE = (240, 240, 240, 255)
HUD_COL_YELLOW = (255, 220, 110, 255)


class GameGLCanvas(glcanvas.GLCanvas):
    def __init__(self, parent: wx.Window, core: GameCore):
        attribs = [
            glcanvas.WX_GL_RGBA,
            glcanvas.WX_GL_DOUBLEBUFFER,
            glcanvas.WX_GL_DEPTH_SIZE,
            24,
            0,
        ]

        # Request a modern accelerated context. Without this, some Windows setups fall back
        # to a very slow software GL implementation (massive stutter / multi-second input lag).
        ctx_attribs = None
        try:
            ctx_attribs = [
                glcanvas.WX_GL_CONTEXT_MAJOR_VERSION,
                3,
                glcanvas.WX_GL_CONTEXT_MINOR_VERSION,
                3,
                glcanvas.WX_GL_CONTEXT_PROFILE_MASK,
                glcanvas.WX_GL_CONTEXT_COMPATIBILITY_PROFILE,
                0,
            ]
        except Exception:
            ctx_attribs = None

        super().__init__(parent, attribList=attribs)

        # Prevent background erase flicker and allow stable 2D overlay drawing.
        try:
            self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        except Exception:
            pass

        self.core = core
        self.renderer = OpenGLRenderer(core)

        try:
            if ctx_attribs is not None:
                self._gl_context = glcanvas.GLContext(self, ctxAttribs=ctx_attribs)
            else:
                self._gl_context = glcanvas.GLContext(self)
        except Exception:
            self._gl_context = glcanvas.GLContext(self)
        self._gl_initialized = False

        self._printed_gl_info = False

        self._mouse_captured = False
        self._mouse_center: tuple[int, int] | None = None

        self._cam_icon = None
        self._cam_icon_scaled_cache: dict[int, wx.Bitmap] = {}
        self._cam_icon_tex: Optional[int] = None
        try:
            self._cam_icon = wx.Bitmap(os.path.join('assets', 'cam.jpg'))
        except Exception:
            self._cam_icon = None

        self._minimap_until = 0.0
        self._minimap_cooldown_until = 0.0
        self._cam_icon_rect: wx.Rect = wx.Rect(0, 0, 0, 0)

        self._modal_visible = False
        self._modal_kind: str = ''
        self._modal_title: str = ''
        self._modal_body: str = ''
        self._modal_btn_rects: dict[str, wx.Rect] = {}
        self._modal_allow_close: bool = True
        self._modal_return_to_pause: bool = False

        self._lore_queue: list[str] = []
        self._lore_current: str = ''
        self._lore_current_start: float = 0.0
        self._lore_current_end: float = 0.0

        self._pause_btn_rects: dict[str, wx.Rect] = {}

        self._hud_font = wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName='Segoe UI')
        self._hud_font_bold = wx.Font(11, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, faceName='Segoe UI')
        self._hud_font_big_bold = wx.Font(22, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, faceName='Segoe UI')
        self._hud_font_level_title = wx.Font(28, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, faceName='Segoe UI')
        self._hud_font_level_sub = wx.Font(13, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName='Segoe UI')
        self._hud_font_pause_title = wx.Font(22, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, faceName='Segoe UI')
        self._hud_font_modal_btn = wx.Font(18, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, faceName='Segoe UI')

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_ERASE_BACKGROUND, self._on_erase_background)

        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOTION, self._on_mouse_move)

        self.SetFocus()

    def _on_erase_background(self, _evt: wx.EraseEvent) -> None:
        # No background erase; OpenGL clears the scene and we draw overlays in EVT_PAINT.
        return

    def _ensure_gl(self) -> None:
        if self._gl_initialized:
            return
        self.SetCurrent(self._gl_context)
        self.renderer.initialize()

        # Optional: load cam icon as a GL texture for the HUD.
        try:
            self._cam_icon_tex = self.renderer._load_texture(os.path.join('assets', 'cam.jpg'))
        except Exception:
            self._cam_icon_tex = None

        w, h = self.GetClientSize()
        self.renderer.resize(int(w), int(h))
        if not self._printed_gl_info:
            try:
                from OpenGL.GL import glGetString, GL_RENDERER, GL_VENDOR, GL_VERSION

                vendor = glGetString(GL_VENDOR)
                renderer = glGetString(GL_RENDERER)
                version = glGetString(GL_VERSION)
                print('[wxpython][opengl] vendor=', vendor)
                print('[wxpython][opengl] renderer=', renderer)
                print('[wxpython][opengl] version=', version)
            except Exception:
                pass
            self._printed_gl_info = True
        self._gl_initialized = True

    def _on_size(self, _evt: wx.SizeEvent) -> None:
        self.Refresh(False)

    def _on_left_down(self, evt: wx.MouseEvent) -> None:
        if bool(getattr(self.core, 'paused', False)):
            evt.Skip()
            return

        if self._modal_visible:
            evt.Skip()
            return

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
        self.hide_mouse_capture()
        evt.Skip()

    def _on_mouse_move(self, evt: wx.MouseEvent) -> None:
        if bool(getattr(self.core, 'paused', False)):
            evt.Skip()
            return

        if not self._mouse_captured or not self._mouse_center:
            evt.Skip()
            return

        mx, my = evt.GetPosition()
        cx, cy = self._mouse_center
        dx = mx - cx
        dy = my - cy

        if abs(dx) > 1 or abs(dy) > 1:
            sensitivity = 0.002
            self.core.rotate_player(-float(dx) * sensitivity)
            self.core.tilt_camera(-float(dy) * sensitivity)
            self.WarpPointer(cx, cy)

        evt.Skip()

    def hide_mouse_capture(self) -> None:
        try:
            if self.HasCapture():
                self.ReleaseMouse()
        except Exception:
            pass
        self._mouse_captured = False
        self._mouse_center = None
        try:
            self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))
        except Exception:
            pass

    def _on_paint(self, _evt: wx.PaintEvent) -> None:
        _ = wx.PaintDC(self)

        self._ensure_gl()
        self.SetCurrent(self._gl_context)

        w, h = self.GetClientSize()
        self.renderer.resize(int(w), int(h))
        self.renderer.render()

        try:
            self._draw_hud_gl(int(w), int(h))
        except Exception:
            pass

        self.SwapBuffers()

    def _draw_hud_gl(self, w: int, h: int) -> None:
        if w <= 1 or h <= 1:
            return

        def rect(x: float, y: float, ww: float, hh: float, r: float, g: float, b: float, a: float) -> None:
            self._gl_rect(x, y, ww, hh, r, g, b, a)

        def text(x: float, y: float, txt: str, scale: float = 1.0) -> None:
            self._gl_text(x, y, txt, scale)

        # 2D overlay pass
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(0.0, float(w), float(h), 0.0, -1.0, 1.0)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()

        # Objective HUD
        pad = 10
        box_w = 320
        box_h = 56
        x = (w - box_w) // 2
        y = pad
        rect(float(x), float(y), float(box_w), float(box_h), 0.0, 0.0, 0.0, 0.62)

        t = int(getattr(self.core, 'elapsed_s', 0.0) or 0.0)
        mm = t // 60
        ss = t % 60
        self._gl_text(float(x + 12), float(y + 6), f'Time: {mm:02d}:{ss:02d}', 1.0, font_size=HUD_FS_MED, bold=True, color=HUD_COL_WHITE)

        coins = int(getattr(self.core, 'coins_collected', 0))
        coins_req = int(getattr(self.core, 'coins_required', 0))
        keys = int(getattr(self.core, 'keys_collected', 0))
        keys_req = int(getattr(self.core, 'keys_required', 0))
        self._gl_text(float(x + 12), float(y + 32), f'Coins: {coins}/{coins_req}   Keys: {keys}/{keys_req}', 1.0, font_size=HUD_FS_SMALL, bold=False, color=HUD_COL_WHITE)

        # Minimap icon
        icon_size = 54
        ix = w - icon_size - 16
        iy = h - icon_size - 16
        self._cam_icon_rect = wx.Rect(ix, iy, icon_size, icon_size)

        rect(float(ix - 6), float(iy - 6), float(icon_size + 12), float(icon_size + 12), 0.0, 0.0, 0.0, 0.50)

        if self._cam_icon_tex:
            from OpenGL.GL import glBindTexture

            glEnable(GL_TEXTURE_2D)
            glBindTexture(GL_TEXTURE_2D, int(self._cam_icon_tex))
            glColor4f(1.0, 1.0, 1.0, 1.0)
            glBegin(GL_QUADS)
            # Textures are uploaded flipped vertically (PIL negative stride). Top uses v=1.
            glTexCoord2f(0.0, 1.0)
            glVertex2f(float(ix), float(iy))
            glTexCoord2f(1.0, 1.0)
            glVertex2f(float(ix + icon_size), float(iy))
            glTexCoord2f(1.0, 0.0)
            glVertex2f(float(ix + icon_size), float(iy + icon_size))
            glTexCoord2f(0.0, 0.0)
            glVertex2f(float(ix), float(iy + icon_size))
            glEnd()
            glBindTexture(GL_TEXTURE_2D, 0)

        now = time.perf_counter()
        if now < float(self._minimap_cooldown_until):
            remaining = max(0.0, float(self._minimap_cooldown_until) - now)
            rect(float(ix), float(iy), float(icon_size), float(icon_size), 0.0, 0.0, 0.0, 0.62)
            self._gl_text(float(ix + 10), float(iy + 16), f'{int(math.ceil(remaining))}s', 1.0, font_size=HUD_FS_MED, bold=True, color=(255, 210, 90, 255))

        if now < float(self._minimap_until):
            self._draw_minimap_overlay_gl(w, h)

        # Sector popup (bottom-center)
        popup_t = float(getattr(self.core, '_sector_popup_timer', 0.0) or 0.0)
        popup_id = str(getattr(self.core, '_sector_popup_id', '') or '')
        if popup_t > 0.0 and popup_id:
            fade_in = 0.25
            fade_out = 0.5
            total = 2.0
            alpha = 1.0
            if popup_t > (total - fade_in):
                alpha = max(0.0, min(1.0, (total - popup_t) / max(0.001, fade_in)))
            elif popup_t < fade_out:
                alpha = max(0.0, min(1.0, popup_t / max(0.001, fade_out)))

            txt = f'SECTOR {popup_id}'
            _, tw_px, th_px = self.renderer.get_text_texture(txt, font_family='Segoe UI', font_size=28, bold=True, color=(255, 220, 110, 255), pad=8)
            tw = float(tw_px)
            th = float(th_px)
            bx = float((w - tw) * 0.5)
            by = float(h - 25)
            pad_px = 10.0
            self._gl_rect(float(bx - pad_px), float(by - th), float(tw + pad_px * 2), float(th + 10), 0.0, 0.0, 0.0, float((150 / 255) * alpha))
            self._gl_text(float(bx), float(by - th + 6), txt, 1.0, font_size=28, bold=True, color=(255, 220, 110, int(255 * alpha)))

        if (not self._modal_visible) and bool(getattr(self.core, 'paused', False)):
            self._draw_pause_panel_gl(w, h)

        if self._modal_visible:
            self._draw_modal_gl(w, h)

        self._draw_lore_fade_gl(w, h)

        # Restore matrices
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)

        glDisable(GL_TEXTURE_2D)
        glEnable(GL_DEPTH_TEST)

    def _gl_rect(self, x: float, y: float, ww: float, hh: float, r: float, g: float, b: float, a: float) -> None:
        glDisable(GL_TEXTURE_2D)
        glColor4f(r, g, b, a)
        glBegin(GL_QUADS)
        glVertex2f(x, y)
        glVertex2f(x + ww, y)
        glVertex2f(x + ww, y + hh)
        glVertex2f(x, y + hh)
        glEnd()

    def _gl_text(self, x: float, y: float, txt: str, scale: float = 1.0, *,
                 font_size: int = 28, bold: bool = True,
                 color: tuple[int, int, int, int] = (240, 240, 240, 255)) -> None:
        tex_id, tw_px, th_px = self.renderer.get_text_texture(
            str(txt),
            font_family='Segoe UI',
            font_size=int(font_size),
            bold=bool(bold),
            color=tuple(int(x) for x in color),
            pad=8,
        )
        tex_id = int(tex_id)
        if tex_id <= 0 or tw_px <= 0 or th_px <= 0:
            return
        tw = float(tw_px) * float(scale)
        th = float(th_px) * float(scale)
        glEnable(GL_TEXTURE_2D)
        from OpenGL.GL import glBindTexture

        glBindTexture(GL_TEXTURE_2D, tex_id)
        glColor4f(1.0, 1.0, 1.0, 1.0)
        glBegin(GL_QUADS)
        # Text textures are uploaded flipped vertically (PIL tobytes with negative stride).
        # Flip V here so text appears upright.
        glTexCoord2f(0.0, 1.0)
        glVertex2f(float(x), float(y))
        glTexCoord2f(1.0, 1.0)
        glVertex2f(float(x + tw), float(y))
        glTexCoord2f(1.0, 0.0)
        glVertex2f(float(x + tw), float(y + th))
        glTexCoord2f(0.0, 0.0)
        glVertex2f(float(x), float(y + th))
        glEnd()
        glBindTexture(GL_TEXTURE_2D, 0)

    def _gl_text_center(self, x: float, y: float, ww: float, hh: float, txt: str, scale: float = 1.0, *,
                        font_size: int = 28, bold: bool = True,
                        color: tuple[int, int, int, int] = (240, 240, 240, 255)) -> None:
        _, tw_px, th_px = self.renderer.get_text_texture(
            str(txt),
            font_family='Segoe UI',
            font_size=int(font_size),
            bold=bool(bold),
            color=tuple(int(x) for x in color),
            pad=8,
        )
        tw = float(tw_px) * float(scale)
        th = float(th_px) * float(scale)
        self._gl_text(float(x + (ww - tw) * 0.5), float(y + (hh - th) * 0.5), txt, scale, font_size=font_size, bold=bold, color=color)

    def _try_open_minimap(self) -> None:
        now = time.perf_counter()
        if now < float(self._minimap_cooldown_until):
            return
        self._minimap_until = now + 10.0
        self._minimap_cooldown_until = now + 30.0

    def enqueue_lore_lines(self, lines: list[str]) -> None:
        for ln in (lines or []):
            s = str(ln or '').strip()
            if not s:
                continue
            self._lore_queue.append(s)
        if (not self._lore_current) and self._lore_queue:
            self._advance_lore_line()

    def _advance_lore_line(self) -> None:
        if not self._lore_queue:
            self._lore_current = ''
            self._lore_current_start = 0.0
            self._lore_current_end = 0.0
            return
        now = time.perf_counter()
        self._lore_current = self._lore_queue.pop(0)
        self._lore_current_start = now
        self._lore_current_end = now + 2.5

    def _draw_lore_fade_gl(self, w: int, h: int) -> None:
        if not self._lore_current:
            if self._lore_queue:
                self._advance_lore_line()
            else:
                return

        now = time.perf_counter()
        if now >= float(self._lore_current_end):
            if not self._lore_current:
                return
            self._lore_current = ''
            self._lore_current_start = 0.0
            self._lore_current_end = 0.0
            return

        duration = max(0.01, float(self._lore_current_end) - float(self._lore_current_start))
        t = max(0.0, min(1.0, (now - float(self._lore_current_start)) / duration))
        fade = 0.18
        if t < fade:
            a = t / fade
        elif t > 1.0 - fade:
            a = (1.0 - t) / fade
        else:
            a = 1.0

        alpha = int(230 * max(0.0, min(1.0, a)))
        if alpha <= 0:
            return

        text = str(self._lore_current)
        # Render centered around 56% height, outlined with 8 offsets.
        _, tw_px, th_px = self.renderer.get_text_texture(text, font_family='Segoe UI', font_size=18, bold=False, color=(255, 255, 255, 255), pad=10)
        tw = float(min(w - 80, int(tw_px)))
        th = float(th_px)
        bx = float((w - tw) * 0.5)
        by = float(int(h * 0.56))

        outline_col = (0, 0, 0, alpha)
        for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            self._gl_text(bx + float(ox), by + float(oy), text, 1.0, font_size=18, bold=False, color=outline_col)
        self._gl_text(bx, by, text, 1.0, font_size=18, bold=False, color=(255, 255, 255, alpha))

    def _draw_minimap_overlay_gl(self, w: int, h: int) -> None:
        # Centered full-maze minimap (match PySide sizing heuristics)
        layout = getattr(self.core, 'layout', None) or []
        maze_rows = len(layout)
        maze_cols = len(layout[0]) if maze_rows > 0 else 0
        if maze_rows <= 0 or maze_cols <= 0:
            return

        max_cell_width = int(w * 0.85 / maze_cols)
        max_cell_height = int((h - 40) / maze_rows)
        cell_px = max(1, int(min(max_cell_width, max_cell_height)))

        maze_content_width = maze_cols * cell_px
        maze_content_height = maze_rows * cell_px

        x0 = (w - maze_content_width) // 2
        y0 = 20 + ((h - 40) - maze_content_height) // 2

        glColor4f(10 / 255, 10 / 255, 12 / 255, 210 / 255)
        glBegin(GL_QUADS)
        glVertex2f(float(x0), float(y0))
        glVertex2f(float(x0 + maze_content_width), float(y0))
        glVertex2f(float(x0 + maze_content_width), float(y0 + maze_content_height))
        glVertex2f(float(x0), float(y0 + maze_content_height))
        glEnd()

        # Walls/floors
        for r in range(maze_rows):
            row = layout[r]
            for c in range(maze_cols):
                ch = row[c]
                rx = x0 + c * cell_px
                ry = y0 + r * cell_px
                if ch == '#':
                    glColor4f(18 / 255, 18 / 255, 22 / 255, 1.0)
                else:
                    glColor4f(55 / 255, 55 / 255, 62 / 255, 1.0)
                glBegin(GL_QUADS)
                glVertex2f(float(rx), float(ry))
                glVertex2f(float(rx + cell_px), float(ry))
                glVertex2f(float(rx + cell_px), float(ry + cell_px))
                glVertex2f(float(rx), float(ry + cell_px))
                glEnd()

        def to_screen(world_r: float, world_c: float) -> tuple[int, int]:
            sx = int(x0 + world_c * cell_px)
            sy = int(y0 + world_r * cell_px)
            return sx, sy

        # Coins
        coin_size = max(4, int(cell_px * 0.35))
        glColor4f(1.0, 0.85, 0.25, 0.95)
        for coin in getattr(self.core, 'coins', {}).values():
            try:
                if getattr(coin, 'taken', False):
                    continue
                rr, cc = coin.cell
            except Exception:
                continue
            sx, sy = to_screen(float(rr) + 0.5, float(cc) + 0.5)
            self._gl_rect(float(sx - coin_size // 2), float(sy - coin_size // 2), float(coin_size), float(coin_size), 1.0, 0.85, 0.25, 0.9)

        # Key fragments
        frag_size = max(6, int(cell_px * 0.45))
        for frag in getattr(self.core, 'key_fragments', {}).values():
            try:
                if getattr(frag, 'taken', False):
                    continue
                rr, cc = frag.cell
                kind = str(getattr(frag, 'kind', '') or '')
            except Exception:
                continue
            if kind == 'KH':
                col = (0.55, 0.95, 1.0)
            elif kind == 'KP':
                col = (0.9, 0.65, 1.0)
            else:
                col = (0.75, 1.0, 0.65)
            sx, sy = to_screen(float(rr) + 0.5, float(cc) + 0.5)
            self._gl_rect(float(sx - frag_size // 2), float(sy - frag_size // 2), float(frag_size), float(frag_size), col[0], col[1], col[2], 0.95)

        # Ghosts
        ghost_colors: dict[int, tuple[float, float, float]] = {
            1: (1.0, 80 / 255, 60 / 255),
            2: (80 / 255, 1.0, 140 / 255),
            3: (110 / 255, 170 / 255, 1.0),
            4: (1.0, 220 / 255, 80 / 255),
            5: (1.0, 90 / 255, 1.0),
        }
        ghost_size = max(8, int(cell_px * 0.6))

        def _circle(cx: float, cy: float, radius: float, col: tuple[float, float, float, float]) -> None:
            glColor4f(col[0], col[1], col[2], col[3])
            glBegin(GL_TRIANGLE_FAN)
            glVertex2f(cx, cy)
            steps = 18
            for i in range(steps + 1):
                a = (i / steps) * (2.0 * math.pi)
                glVertex2f(cx + math.cos(a) * radius, cy + math.sin(a) * radius)
            glEnd()

        for ghost in getattr(self.core, 'ghosts', {}).values():
            try:
                gr = float(getattr(ghost, 'z', 0.0))
                gc = float(getattr(ghost, 'x', 0.0))
                gid = int(getattr(ghost, 'id', 0) or 0)
                s = float(getattr(ghost, 'size_scale', 1.0) or 1.0)
            except Exception:
                continue
            gsz = int(max(8, ghost_size * s))
            col = ghost_colors.get(gid, (1.0, 120 / 255, 30 / 255))
            sx, sy = to_screen(gr + 0.5, gc + 0.5)

            # Body (circle)
            _circle(float(sx), float(sy), float(gsz) * 0.5, (col[0], col[1], col[2], 0.95))

            # Eyes (match PySide minimap: white eyes + black pupils)
            eye_size = max(2, int(gsz * 0.15))
            eye_offset_x = float(gsz) * 0.25
            eye_offset_y = float(gsz) * 0.10
            _circle(float(sx - eye_offset_x), float(sy - eye_offset_y), float(eye_size) * 0.6, (1.0, 1.0, 1.0, 1.0))
            _circle(float(sx + eye_offset_x), float(sy - eye_offset_y), float(eye_size) * 0.6, (1.0, 1.0, 1.0, 1.0))

            pupil_size = max(1, int(eye_size * 0.5))
            _circle(float(sx - eye_offset_x), float(sy - eye_offset_y), float(pupil_size) * 0.6, (0.0, 0.0, 0.0, 1.0))
            _circle(float(sx + eye_offset_x), float(sy - eye_offset_y), float(pupil_size) * 0.6, (0.0, 0.0, 0.0, 1.0))

        # Player marker
        px = float(getattr(self.core.player, 'x', 0.0))
        pz = float(getattr(self.core.player, 'z', 0.0))
        yaw = float(getattr(self.core.player, 'yaw', 0.0))

        pr = int(pz)
        pc = int(px)
        cx = x0 + int((pc + 0.5) * cell_px)
        cy = y0 + int((pr + 0.5) * cell_px)

        r0 = max(2, int(cell_px * 0.25))
        glColor4f(1.0, 220 / 255, 110 / 255, 0.86)
        glBegin(GL_QUADS)
        glVertex2f(float(cx - r0), float(cy - r0))
        glVertex2f(float(cx + r0), float(cy - r0))
        glVertex2f(float(cx + r0), float(cy + r0))
        glVertex2f(float(cx - r0), float(cy + r0))
        glEnd()

        # Facing line
        fx = math.sin(yaw)
        fz = math.cos(yaw)
        line_len = max(6, int(cell_px * 0.75))
        # Facing line (as a thin quad)
        x1 = cx + int(fx * line_len)
        y1 = cy + int(fz * line_len)
        glColor4f(1.0, 220 / 255, 110 / 255, 1.0)
        glBegin(GL_QUADS)
        glVertex2f(float(cx), float(cy))
        glVertex2f(float(x1), float(y1))
        glVertex2f(float(x1 + 1), float(y1 + 1))
        glVertex2f(float(cx + 1), float(cy + 1))
        glEnd()

    def _draw_pause_panel_gl(self, w: int, h: int) -> None:
        # Full-screen dim
        self._gl_rect(0.0, 0.0, float(w), float(h), 0.0, 0.0, 0.0, 160 / 255)

        panel_w = 560
        panel_h = 610
        x0 = (w - panel_w) // 2
        y0 = (h - panel_h) // 2

        self._gl_rect(float(x0), float(y0), float(panel_w), float(panel_h), 18 / 255, 18 / 255, 22 / 255, 235 / 255)

        # Title
        title = 'PAUSED'
        self._gl_text_center(float(x0), float(y0 + 10), float(panel_w), 54.0, title, 1.0, font_size=HUD_FS_PAUSE_TITLE, bold=True, color=HUD_COL_YELLOW)

        # Stats area (visual parity; values can be refined later)
        stats_x = x0 + 36
        stats_y = y0 + 96
        line_h = 24
        self._gl_text(float(stats_x), float(stats_y + line_h * 0), 'FPS: ...', 1.0, font_size=HUD_FS_SMALL, bold=False, color=(235, 235, 235, 255))
        self._gl_text(float(stats_x), float(stats_y + line_h * 1), 'Avg input latency: ... ms', 1.0, font_size=HUD_FS_SMALL, bold=False, color=(235, 235, 235, 255))
        self._gl_text(float(stats_x), float(stats_y + line_h * 2), 'RAM usage: ... MB', 1.0, font_size=HUD_FS_SMALL, bold=False, color=(235, 235, 235, 255))

        btn_w = 280
        btn_h = 48
        gap = 16
        center_x = x0 + (panel_w - btn_w) // 2
        top_btn_y = y0 + 200

        buttons = [
            ('resume', 'Resume', center_x, top_btn_y + (btn_h + gap) * 0),
            ('levels', 'Levels', center_x, top_btn_y + (btn_h + gap) * 1),
            ('save', 'Save Game', center_x, top_btn_y + (btn_h + gap) * 2),
            ('save_exit', 'Save + Exit', center_x, top_btn_y + (btn_h + gap) * 3),
            ('restart', 'Restart', center_x, top_btn_y + (btn_h + gap) * 4),
            ('exit', 'Exit (No Save)', center_x, top_btn_y + (btn_h + gap) * 5),
        ]

        self._pause_btn_rects.clear()
        for key, label, bx, by in buttons:
            r = wx.Rect(int(bx), int(by), int(btn_w), int(btn_h))
            self._pause_btn_rects[key] = r
            self._gl_rect(float(r.x), float(r.y), float(r.width), float(r.height), 32 / 255, 32 / 255, 40 / 255, 235 / 255)
            self._gl_text_center(float(r.x), float(r.y), float(r.width), float(r.height), label, 1.0, font_size=HUD_FS_MED, bold=True, color=(255, 255, 255, 255))

    def _draw_modal_gl(self, w: int, h: int) -> None:
        self._gl_rect(0.0, 0.0, float(w), float(h), 0.0, 0.0, 0.0, 150 / 255)
        self._modal_btn_rects.clear()

        if self._modal_kind == 'level_select':
            title = self._modal_title or 'Select Level'
            body = self._modal_body or ''

            self._gl_text_center(float(0), float(h * 0.10), float(w), 80.0, title, 1.0, font_size=38, bold=True, color=HUD_COL_WHITE)
            if body:
                self._gl_text_center(float(0), float(h * 0.10 + 60), float(w), 50.0, body, 1.0, font_size=18, bold=False, color=(200, 200, 200, 255))

            btn_w = min(620, int(w * 0.62))
            btn_h = 82
            gap = 22
            bx = (w - btn_w) // 2
            by1 = int(h * 0.34)
            by2 = by1 + btn_h + gap

            modal_unlocked = set(getattr(self, '_modal_unlocked', None) or set())

            def draw_btn(key: str, yy: int, label: str, enabled: bool) -> None:
                r = wx.Rect(int(bx), int(yy), int(btn_w), int(btn_h))
                if enabled:
                    self._gl_rect(float(r.x), float(r.y), float(r.width), float(r.height), 22 / 255, 22 / 255, 26 / 255, 1.0)
                else:
                    self._gl_rect(float(r.x), float(r.y), float(r.width), float(r.height), 22 / 255, 22 / 255, 26 / 255, 190 / 255)
                self._gl_text_center(float(r.x), float(r.y), float(r.width), float(r.height), label, 1.0, font_size=26, bold=True, color=HUD_COL_WHITE if enabled else (140, 140, 140, 255))
                self._modal_btn_rects[key] = r

            draw_btn('level1', by1, 'Level 1', True)
            lvl2_enabled = 'level2' in modal_unlocked
            draw_btn('level2', by2, 'Level 2' if lvl2_enabled else 'Level 2 (Locked)', lvl2_enabled)

            close_size = 38
            close_x = w - close_size - 20
            close_y = 18
            close_r = wx.Rect(int(close_x), int(close_y), int(close_size), int(close_size))
            self._modal_btn_rects['close'] = close_r

            a = 220 / 255 if self._modal_allow_close else 120 / 255
            self._gl_rect(float(close_r.x), float(close_r.y), float(close_r.width), float(close_r.height), a, a, a, 0.15)

    def show_level_select_modal(self, *, unlocked: set[str], allow_close: bool, return_to_pause: bool) -> None:
        self._modal_visible = True
        self._modal_kind = 'level_select'
        self._modal_title = 'Select Level'
        self._modal_body = ''
        self._modal_unlocked = set(unlocked)
        self._modal_levels = [('level1', 'Level 1'), ('level2', 'Level 2')]
        self._modal_allow_close = bool(allow_close)
        self._modal_return_to_pause = bool(return_to_pause)
        self.hide_mouse_capture()

    def hide_modal(self) -> None:
        self._modal_visible = False
        self._modal_kind = ''
        self._modal_title = ''
        self._modal_body = ''
        self._modal_btn_rects.clear()

    def hit_test_modal(self, pos: wx.Point) -> Optional[str]:
        if not self._modal_visible:
            return None
        for key, rect in self._modal_btn_rects.items():
            if rect.Contains(pos):
                return str(key)
        return None

    def hit_test_pause(self, pos: wx.Point) -> Optional[str]:
        if not bool(getattr(self.core, 'paused', False)):
            return None
        for key, rect in self._pause_btn_rects.items():
            if rect.Contains(pos):
                return str(key)
        return None


class WxGameWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title='Within the Walls (WxPython)', size=(1280, 800))

        self._progress_path = os.path.abspath('progression.json')
        self._progress = self._load_progression()

        unlocked = set(self._progress.get('unlocked_levels') or [])
        last_level = str(self._progress.get('last_level') or 'level1')
        if last_level not in unlocked:
            last_level = 'level1'

        self._save_path = os.path.abspath('savegame.json')

        autoload_level1_save = False
        if last_level == 'level1' and os.path.exists(self._save_path):
            autoload_level1_save = True

        self.core = GameCore(level_id=last_level)
        self._current_level_id = last_level

        self._asset_dir = os.path.abspath('assets')
        self._sfx_coin = self._load_sound('drop-coin-384921.wav')
        self._sfx_gate = self._load_sound('closing-metal-door-44280.wav')
        self._sfx_ghost = self._load_sound('ghost-horror-sound-382709.wav')
        self._sfx_footsteps = self._load_sound('running-on-concrete-268478.wav')

        self._lore_flags: dict[str, bool] = {}
        self._persist_seen: dict[str, bool] = {}

        self._callbacks_core_token: int = 0

        self.keys_pressed: set[int] = set()

        self.canvas = GameGLCanvas(self, self.core)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.canvas, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_TIMER, self._on_tick)

        # Route input through the canvas (focus stays there during gameplay).
        self.canvas.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.canvas.Bind(wx.EVT_KEY_UP, self._on_key_up)
        self.canvas.Bind(wx.EVT_LEFT_DOWN, self._on_click)

        self._tick = wx.Timer(self)
        self._tick.Start(16)

        self._last_update_time = time.perf_counter()

        self._register_core_callbacks()

        if self._current_level_id == 'level2':
            self._set_paused(False)
            self._start_level('level2', load_save=os.path.exists(self._save_path))
        elif autoload_level1_save:
            self._set_paused(False)
            self._start_level('level1', load_save=True)
        else:
            self._open_level_select_modal(startup=True)

    def _load_sound(self, filename: str) -> Optional[wx.adv.Sound]:
        try:
            path = os.path.join(self._asset_dir, str(filename))
            if not os.path.exists(path):
                return None
            snd = wx.adv.Sound(path)
            if not snd.IsOk():
                return None
            return snd
        except Exception:
            return None

    def _play_sfx(self, snd: Optional[wx.adv.Sound]) -> None:
        try:
            if snd is None:
                return
            snd.Play(wx.adv.SOUND_ASYNC)
        except Exception:
            pass

    def _register_core_callbacks(self) -> None:
        try:
            token = id(self.core)
            if int(getattr(self, '_callbacks_core_token', 0) or 0) == int(token):
                return
            self._callbacks_core_token = int(token)

            self.core.register_event_callback('coin_picked', self._on_coin_picked)
            self.core.register_event_callback('gate_opened', self._on_gate_moved)
            self.core.register_event_callback('gate_closed', self._on_gate_moved)
            self.core.register_event_callback('time_penalty', self._on_time_penalty)
            self.core.register_event_callback('exit_unlocked', self._on_exit_unlocked)
            self.core.register_event_callback('sector_entered', self._on_sector_entered)
            self.core.register_event_callback('sent_to_jail', self._on_sent_to_jail)
            self.core.register_event_callback('left_jail', self._on_left_jail)
            self.core.register_event_callback('key_fragment_encountered', self._on_key_fragment_encountered)
            self.core.register_event_callback('key_picked', self._on_key_picked)
        except Exception:
            pass

    def _show_lore_line(self, text: str) -> None:
        try:
            self.canvas.enqueue_lore_lines([str(text)])
        except Exception:
            pass

    def _on_coin_picked(self, data: dict) -> None:
        self._play_sfx(self._sfx_coin)
        try:
            if float(self.core.coins_collected) >= float(self.core.coins_required) * 0.5:
                key = f'coins_half_{self._current_level_id}'
                if (not self._lore_flags.get('coins_half')) and (not self._persist_seen.get(key)):
                    self._lore_flags['coins_half'] = True
                    self._persist_seen[key] = True
                    if self._current_level_id == 'level1':
                        self._show_lore_line('Halfway.')
                    elif self._current_level_id == 'level2':
                        self._show_lore_line('The maze likes it when I collect.')
        except Exception:
            pass

    def _on_gate_moved(self, _data: dict) -> None:
        self._play_sfx(self._sfx_gate)

    def _on_time_penalty(self, data: dict) -> None:
        # PySide shows a +Ns popup; we at least do the lore/sfx parity here.
        try:
            seconds = int((data or {}).get('seconds', 0) or 0)
            if seconds > 0:
                self._show_lore_line(f'+{seconds}s')
        except Exception:
            pass

    def _on_exit_unlocked(self, _data: dict) -> None:
        return

    def _on_sector_entered(self, data: dict) -> None:
        sid = str((data or {}).get('id', '') or '')
        if (self._current_level_id == 'level2') and (sid == 'F'):
            try:
                req_met = (int(self.core.coins_collected) >= int(self.core.coins_required)) and (int(self.core.keys_collected) >= int(self.core.keys_required))
            except Exception:
                req_met = False
            if req_met and (not self._lore_flags.get('l2_sector_f_done')):
                self._lore_flags['l2_sector_f_done'] = True
                self._show_lore_line('A dream... Far too lucid.')

    def _on_sent_to_jail(self, _data: dict) -> None:
        if self._current_level_id != 'level1':
            return
        if not self._persist_seen.get('tutorial_jail'):
            self._persist_seen['tutorial_jail'] = True
            self.canvas._modal_visible = True
            self.canvas._modal_kind = 'tutorial'
            self.canvas._modal_title = 'Jail'
            self.canvas._modal_body = (
                'This is not death.\n'
                'To escape, find the table and press E to interact with the glowing book.\n\n'
                'A sector map is displayed here. Use it to orient yourself before returning to the maze.'
            )
            self.canvas._modal_allow_close = True
            self.canvas._modal_return_to_pause = False
            # Tutorial modal should not force a permanent pause; ESC will close it and gameplay can continue.
            self._set_paused(False)

    def _on_left_jail(self, _data: dict) -> None:
        return

    def _on_key_picked(self, data: dict) -> None:
        try:
            cnt = int((data or {}).get('count', 0) or 0)
            if (self._current_level_id == 'level2') and (cnt >= 3) and (not self._lore_flags.get('l2_frags_done')):
                self._lore_flags['l2_frags_done'] = True
                self._show_lore_line('The key is done... I am watched.')
        except Exception:
            pass

    def _on_key_fragment_encountered(self, data: dict) -> None:
        # Minigame port comes next; for now we mimic PySide: freeze sim + show modal prompt.
        if getattr(self.core, 'paused', False):
            return
        frag_id = str((data or {}).get('id', '') or '')
        if not frag_id:
            return

        prev_frozen = bool(getattr(self.core, 'simulation_frozen', False))
        self._set_paused(False)
        self.core.simulation_frozen = True
        self.canvas._modal_visible = True
        self.canvas._modal_kind = 'tutorial'
        self.canvas._modal_title = 'Key Fragment'
        self.canvas._modal_body = 'Minigame port in progress. Press ESC to close.'
        self.canvas._modal_allow_close = True
        self.canvas._modal_return_to_pause = False

        # Remember we froze simulation so we can unfreeze on modal close.
        self.canvas._modal_freeze_simulation = True
        self.canvas._modal_prev_simulation_frozen = prev_frozen

    def _handle_interact(self) -> None:
        if getattr(self.core, 'paused', False):
            return
        try:
            action = self.core.interact()
        except Exception:
            action = None
        if not action:
            return

        if action == 'jail_book':
            prev_frozen = bool(getattr(self.core, 'simulation_frozen', False))
            self.core.simulation_frozen = True
            self._set_paused(True)

            self.canvas._modal_visible = True
            self.canvas._modal_kind = 'tutorial'
            self.canvas._modal_title = 'Jail'
            self.canvas._modal_body = 'Minigame port in progress. Press ESC to close.'
            self.canvas._modal_allow_close = True
            self.canvas._modal_return_to_pause = False
            self.canvas._modal_freeze_simulation = True
            self.canvas._modal_prev_simulation_frozen = prev_frozen
            return

        if action == 'gate_jail':
            try:
                self.core.try_leave_jail()
            except Exception:
                pass
            return

        if action in ('exit_locked', 'jail_locked'):
            return

        return

    def _load_progression(self) -> dict:
        if not os.path.exists(self._progress_path):
            return {'unlocked_levels': ['level1']}
        try:
            with open(self._progress_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {'unlocked_levels': ['level1']}
            unlocked = data.get('unlocked_levels')
            if not isinstance(unlocked, list) or 'level1' not in unlocked:
                return {'unlocked_levels': ['level1']}
            return data
        except Exception:
            return {'unlocked_levels': ['level1']}

    def _save_progression(self) -> None:
        try:
            with open(self._progress_path, 'w', encoding='utf-8') as f:
                json.dump(self._progress, f, indent=2)
        except Exception:
            pass

    def _set_paused(self, paused: bool) -> None:
        self.core.paused = bool(paused)
        if paused:
            self.canvas.hide_mouse_capture()

    def _toggle_pause(self) -> None:
        if self.core.screen_closing or self.core.game_completed or self.core.game_won:
            return
        now_paused = not bool(getattr(self.core, 'paused', False))
        self._set_paused(now_paused)
        self.canvas.Refresh(False)

    def _open_level_select_modal(self, *, startup: bool) -> None:
        unlocked = set(self._progress.get('unlocked_levels') or [])
        self._set_paused(True)
        self.canvas.show_level_select_modal(unlocked=unlocked, allow_close=(not startup), return_to_pause=(not startup))

    def _start_level(self, level_id: str, *, load_save: bool) -> None:
        level_id = str(level_id or 'level1')
        paused_was = bool(getattr(self.core, 'paused', False))

        self.core = GameCore(level_id=level_id)
        self._current_level_id = level_id
        self.canvas.core = self.core

        for k in ('coins_half', 'ghost_close', 'l2_frags_done', 'l2_sector_f_done'):
            self._lore_flags.pop(k, None)

        try:
            self.canvas.SetCurrent(self.canvas._gl_context)
            self.canvas.renderer = OpenGLRenderer(self.core)
            w, h = self.canvas.GetClientSize()
            self.canvas.renderer.resize(int(w), int(h))
            self.canvas.renderer.initialize()
        except Exception:
            try:
                self.canvas.renderer.core = self.core
            except Exception:
                pass

        self.keys_pressed.clear()
        self._register_core_callbacks()
        if paused_was:
            self._set_paused(True)
        self._last_update_time = time.perf_counter()
        self.canvas.Refresh(False)

    def _on_tick(self, _evt: wx.TimerEvent) -> None:
        if not hasattr(self, '_last_update_time'):
            self._last_update_time = time.perf_counter()
            return

        current_time = time.perf_counter()
        dt = current_time - self._last_update_time
        self._last_update_time = current_time
        dt = min(dt, 0.1)

        paused = bool(getattr(self.core, 'paused', False))
        if not paused:
            self.core.update(dt)

        if paused:
            # Still repaint so pause/menu overlays remain responsive.
            self.canvas.Refresh(False)
            return

        move_speed = 0.18 if str(getattr(self, '_current_level_id', '')) == 'level1' else 0.30
        dx = 0.0
        dz = 0.0

        if ord('W') in self.keys_pressed:
            dz += move_speed
        if ord('S') in self.keys_pressed:
            dz -= move_speed
        if ord('A') in self.keys_pressed:
            dx -= move_speed
        if ord('D') in self.keys_pressed:
            dx += move_speed

        if dx != 0.0 or dz != 0.0:
            self.core.move_player(dx, dz)

        # Drive the render loop at the same cadence as gameplay updates.
        self.canvas.Refresh(False)

    def _on_key_down(self, evt: wx.KeyEvent) -> None:
        code = int(evt.GetKeyCode())
        self.keys_pressed.add(code)

        if code in (ord('E'), ord('e')):
            self._handle_interact()
            return

        if code == wx.WXK_ESCAPE:
            if getattr(self.canvas, '_modal_visible', False):
                return_to_pause = bool(getattr(self.canvas, '_modal_return_to_pause', False))
                self.canvas.hide_modal()
                try:
                    if bool(getattr(self.canvas, '_modal_freeze_simulation', False)):
                        self.canvas._modal_freeze_simulation = False
                        prev = bool(getattr(self.canvas, '_modal_prev_simulation_frozen', False))
                        self.core.simulation_frozen = prev
                except Exception:
                    pass
                # Match click-close logic: if modal was opened from pause, return to pause; else resume gameplay.
                if return_to_pause:
                    self._set_paused(True)
                else:
                    self._set_paused(False)
                return
            self._toggle_pause()
            return

        evt.Skip()

    def _on_key_up(self, evt: wx.KeyEvent) -> None:
        self.keys_pressed.discard(int(evt.GetKeyCode()))
        evt.Skip()

    def _on_click(self, evt: wx.MouseEvent) -> None:
        pos = evt.GetPosition()

        # Minimap icon click
        try:
            if self.canvas._cam_icon_rect.Contains(pos):
                self.canvas._try_open_minimap()
                self.canvas.Refresh(False)
                return
        except Exception:
            pass

        hit_modal = self.canvas.hit_test_modal(pos)
        if hit_modal:
            if hit_modal == 'close':
                self.canvas.hide_modal()
                if getattr(self.canvas, '_modal_return_to_pause', False):
                    self._set_paused(True)
                else:
                    self._set_paused(False)
                return

            if hit_modal in ('level1', 'level2'):
                self.canvas.hide_modal()
                self._set_paused(False)
                try:
                    self._progress['last_level'] = str(hit_modal)
                    self._save_progression()
                except Exception:
                    pass
                self._start_level(str(hit_modal), load_save=False)
                return

        hit_pause = self.canvas.hit_test_pause(pos)
        if hit_pause:
            self._on_pause_action(hit_pause)
            return

        evt.Skip()

    def _on_pause_action(self, action: str) -> None:
        if action == 'resume':
            self._toggle_pause()
            return
        if action == 'levels':
            self._toggle_pause()
            self._open_level_select_modal(startup=False)
            return
        if action == 'save':
            self._save_game()
            return
        if action == 'save_exit':
            self._save_game()
            self.Close()
            return
        if action == 'exit':
            self.Close()
            return
        if action == 'restart':
            self._start_level(self._current_level_id, load_save=False)
            return

    def _save_game(self) -> None:
        # Minimal save parity for now: persist only a subset so resume works as we expand.
        try:
            data = {
                'level_id': str(self._current_level_id),
                'player': {
                    'x': float(self.core.player.x),
                    'z': float(self.core.player.z),
                    'yaw': float(self.core.player.yaw),
                    'pitch': float(self.core.player.pitch),
                },
                'coins_collected': int(getattr(self.core, 'coins_collected', 0)),
                'keys_collected': int(getattr(self.core, 'keys_collected', 0)),
                'elapsed_s': float(getattr(self.core, 'elapsed_s', 0.0)),
            }
            with open(self._save_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _on_close(self, evt: wx.CloseEvent) -> None:
        try:
            self.canvas.hide_mouse_capture()
        except Exception:
            pass
        evt.Skip()


def run() -> int:
    app = wx.App(False)
    win = WxGameWindow()
    win.Show(True)
    return int(app.MainLoop() or 0)
