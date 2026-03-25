import json
import math
import os
import time
from typing import Optional

import wx
import wx.adv
from wx import glcanvas

from .silhouette_minigame import SilhouetteMatchDialog
from .assembly3d_minigame import Assembly3DMinigame
from .renderer_opengl import OpenGLRenderer

from OpenGL.GL import (
    GL_BLEND,
    GL_DEPTH_TEST,
    GL_LINES,
    GL_LIGHTING,
    GL_MODELVIEW,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_PROJECTION,
    GL_QUADS,
    GL_TEXTURE_ENV,
    GL_TEXTURE_ENV_MODE,
    GL_TRIANGLE_FAN,
    GL_TRIANGLE_STRIP,
    GL_SRC_ALPHA,
    GL_TEXTURE_2D,
    GL_MODULATE,
    GL_REPLACE,
    glBegin,
    glBlendFunc,
    glColor4f,
    glDisable,
    glEnable,
    glEnd,
    glIsEnabled,
    glLineWidth,
    glLoadIdentity,
    glMatrixMode,
    glOrtho,
    glPopMatrix,
    glPushMatrix,
    glTexCoord2f,
    glTexEnvi,
    glVertex2f,
)

from core.game_core import GameCore
from core.performance_monitor import PerformanceMonitor


class _SimpleAudio:
    """
    Single-channel audio wrapper around wx.adv.Sound.

    wx.adv.Sound plays only one sound at a time system-wide. The priority scheme is:
      ghost / gate (long SFX) > coin (short SFX) > footsteps (looping background)

    All wx calls must be made from the main thread. threading.Timer is NOT used —
    wx is not thread-safe. wx.CallLater schedules the footstep resume on the main thread.
    """

    def __init__(self, asset_dir: str):
        self._asset_dir = str(asset_dir or '')
        self._footsteps_requested = False
        self._footsteps_playing = False
        # Absolute perf_counter time until which the channel belongs to a priority SFX.
        self._sfx_until = 0.0

        self._footsteps_path = os.path.join(
            self._asset_dir, 'running-on-concrete-268478.wav')
        self._coin_path = os.path.join(self._asset_dir, 'drop-coin-384921.wav')
        self._gate_path = os.path.join(
            self._asset_dir, 'closing-metal-door-44280.wav')
        self._ghost_path = os.path.join(
            self._asset_dir, 'ghost-horror-sound-382709.wav')

        self._snd_footsteps = wx.adv.Sound(
            self._footsteps_path) if os.path.exists(self._footsteps_path) else None
        self._snd_coin = wx.adv.Sound(
            self._coin_path) if os.path.exists(self._coin_path) else None
        self._snd_gate = wx.adv.Sound(
            self._gate_path) if os.path.exists(self._gate_path) else None
        self._snd_ghost = wx.adv.Sound(
            self._ghost_path) if os.path.exists(self._ghost_path) else None

    @property
    def enabled(self) -> bool:
        return True

    def shutdown(self) -> None:
        try:
            self.set_footsteps(False)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal helpers — main thread only
    # ------------------------------------------------------------------

    def _start_footsteps_loop(self) -> None:
        if self._snd_footsteps is None:
            return
        try:
            self._snd_footsteps.Play(wx.adv.SOUND_ASYNC | wx.adv.SOUND_LOOP)
            self._footsteps_playing = True
        except Exception:
            self._footsteps_playing = False

    def _stop_footsteps(self) -> None:
        self._footsteps_playing = False
        if self._snd_footsteps is None:
            return
        try:
            self._snd_footsteps.Stop()
        except Exception:
            pass

    def _resume_footsteps_if_needed(self) -> None:
        """Scheduled via wx.CallLater — always runs on the main thread."""
        if not self._footsteps_requested:
            return
        if time.perf_counter() < self._sfx_until:
            # A later SFX extended the window; don't fight it — let its CallLater handle it.
            return
        if not self._footsteps_playing:
            self._start_footsteps_loop()

    def _play_priority_sfx(self, snd: Optional[wx.adv.Sound], *, cooldown_s: float) -> None:
        """
        Play a priority SFX (coin, gate, ghost).
        Stops footsteps, plays the sound, schedules footstep resume via wx.CallLater.
        """
        if snd is None:
            return
        self._stop_footsteps()
        now = time.perf_counter()
        # Extend the silent window if a longer SFX is already running.
        self._sfx_until = max(self._sfx_until, now + cooldown_s)
        try:
            snd.Play(wx.adv.SOUND_ASYNC)
        except Exception:
            return
        try:
            wx.CallLater(int(cooldown_s * 1000),
                         self._resume_footsteps_if_needed)
        except Exception:
            pass

    # Public API
    # ------------------------------------------------------------------

    def set_footsteps(self, playing: bool) -> None:
        playing = bool(playing)
        self._footsteps_requested = playing
        if not playing:
            self._stop_footsteps()
            return
        if time.perf_counter() < self._sfx_until:
            return  # Priority SFX still owns the channel
        if self._footsteps_playing:
            return
        self._start_footsteps_loop()

    def play_coin(self) -> None:
        self._play_priority_sfx(self._snd_coin, cooldown_s=0.35)

    def play_gate(self, *, volume: float = 0.8) -> None:
        self._play_priority_sfx(self._snd_gate, cooldown_s=3.0)

    def play_ghost(self, *, volume: float = 0.8) -> None:
        self._play_priority_sfx(self._snd_ghost, cooldown_s=3.5)


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

        # Request a basic OpenGL context for better compatibility
        ctx_attribs = None
        # Don't request specific version/profile to avoid driver issues

        super().__init__(parent, attribList=attribs)

        # Stable 2D overlay drawing - prevents flicker :)
        try:
            self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        except Exception:
            pass

        self.core = core
        self.renderer = OpenGLRenderer(core)

        try:
            if ctx_attribs is not None:
                self._gl_context = glcanvas.GLContext(
                    self, ctxAttribs=ctx_attribs)
            else:
                self._gl_context = glcanvas.GLContext(self)
        except Exception:
            self._gl_context = glcanvas.GLContext(self)
        self._gl_initialized = False

        self._printed_gl_info = False

        self._mouse_captured = False
        self._mouse_center: tuple[int, int] | None = None

        self._assets_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', '..', 'assets'))
        self._cam_icon = None
        self._cam_icon_scaled_cache: dict[int, wx.Bitmap] = {}
        self._cam_icon_tex: Optional[int] = None
        try:
            self._cam_icon = wx.Bitmap(
                os.path.join(self._assets_dir, 'cam.jpg'))
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

        self._show_the_end: bool = False

        self._pause_btn_rects: dict[str, wx.Rect] = {}

        # Performance monitor (assigned by WxGameWindow after construction)
        self.performance_monitor: Optional[PerformanceMonitor] = None

        # Stats / end-screen state
        # True WHILE frozen stats screen is shown
        self._stats_visible: bool = False
        self._stats_text: str = ''                 # Summary text
        # True on level-2 completion (the end)
        self._end_screen_visible: bool = False

        self._hud_font = wx.Font(
            10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName='Arial')
        self._hud_font_bold = wx.Font(
            11, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, faceName='Arial')
        self._hud_font_big_bold = wx.Font(
            22, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, faceName='Arial')
        self._hud_font_level_title = wx.Font(
            28, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, faceName='Arial')
        self._hud_font_level_sub = wx.Font(
            13, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName='Arial')
        self._hud_font_pause_title = wx.Font(
            22, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, faceName='Arial')
        self._hud_font_modal_btn = wx.Font(
            18, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, faceName='Arial')

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_ERASE_BACKGROUND, self._on_erase_background)

        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOTION, self._on_mouse_move)

        self.SetFocus()

    def show_stats_screen(self, text: str) -> None:
        """Freeze the game and display the performance-summary stats screen."""
        self._stats_text = str(text or '')
        self._stats_visible = True
        self._end_screen_visible = False
        self.hide_mouse_capture()

    def show_end_screen(self, text: str) -> None:
        """Show the final 'The End' screen (level 2 completion)."""
        self._stats_text = str(text or '')
        self._stats_visible = True
        self._end_screen_visible = True
        self.hide_mouse_capture()

    def hide_stats_screen(self) -> None:
        self._stats_visible = False
        self._end_screen_visible = False
        self._stats_text = ''

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
            self._cam_icon_tex = self.renderer._load_texture(
                os.path.join(self._assets_dir, 'cam.jpg'))
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

                # Capture system info instead of printing
                try:
                    from core.pdf_export import get_system_collector
                    collector = get_system_collector()
                    collector.record_opengl_info(vendor, renderer, version)
                except ImportError:
                    # PDF export not available, just skip system info capture
                    pass

            except Exception:
                pass
            self._printed_gl_info = True
        self._gl_initialized = True

    def _on_size(self, _evt: wx.SizeEvent) -> None:
        self.Refresh(False)

    def _on_left_down(self, evt: wx.MouseEvent) -> None:
        # Ignore all clicks while the end/stats screen is showing
        if getattr(self, '_stats_visible', False):
            return

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

    def _on_mouse_capture_lost(self, evt: wx.MouseCaptureLostEvent) -> None:
        """Handle mouse capture being lost unexpectedly (window losing focus, etc.)"""
        self._mouse_captured = False
        self._mouse_center = None
        try:
            self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))
        except Exception:
            pass
        evt.Skip()

    def _on_size(self, evt: wx.SizeEvent) -> None:
        """Handle resize events and update OpenGL viewport"""
        if not self._gl_initialized:
            evt.Skip()
            return

        self._ensure_gl()
        self.SetCurrent(self._gl_context)

        w, h = self.GetClientSize()

        # Reload textures if window reached proper size
        if w >= 1800 and h >= 900:
            if not getattr(self, '_textures_reloaded_for_fullscreen', False):
                self.renderer._ensure_geometry_built()
                self.renderer._ensure_textures_loaded()
                self._textures_reloaded_for_fullscreen = True

        self.renderer.resize(int(w), int(h))
        self.renderer.render()
        self._draw_hud_gl(int(w), int(h))

        # Restore proper GL state after HUD rendering (PySide parity)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)

        self.SwapBuffers()

    def _on_paint(self, _evt: wx.PaintEvent) -> None:
        _ = wx.PaintDC(self)

        self._ensure_gl()
        self.SetCurrent(self._gl_context)

        w, h = self.GetClientSize()
        self.renderer.resize(int(w), int(h))
        self.renderer.render()
        self._draw_hud_gl(int(w), int(h))

        # Restore proper GL state after HUD rendering (PySide parity)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)

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

        # Fix matrix stack overflow - completely reset both stacks efficiently
        # Reset PROJECTION stack to clean state
        glMatrixMode(GL_PROJECTION)
        try:
            # Get current stack depth
            from OpenGL.GL import glGetIntegerv, GL_PROJECTION_STACK_DEPTH
            stack_depth = glGetIntegerv(GL_PROJECTION_STACK_DEPTH)[0]
            # Pop all matrices
            for _ in range(stack_depth):
                glPopMatrix()
        except Exception:
            # Fallback to original method if glGetIntegerv fails
            while True:
                try:
                    glPopMatrix()
                except Exception:
                    break
        glLoadIdentity()
        glPushMatrix()

        glLoadIdentity()
        glOrtho(0.0, float(w), float(h), 0.0, -1.0, 1.0)

        # Reset MODELVIEW stack to clean state
        glMatrixMode(GL_MODELVIEW)
        try:
            # Get current stack depth
            from OpenGL.GL import glGetIntegerv, GL_MODELVIEW_STACK_DEPTH
            stack_depth = glGetIntegerv(GL_MODELVIEW_STACK_DEPTH)[0]
            # Pop all matrices
            for _ in range(stack_depth):
                glPopMatrix()
        except Exception:
            # Fallback to original method if glGetIntegerv fails
            while True:
                try:
                    glPopMatrix()
                except Exception:
                    break
        glLoadIdentity()
        glPushMatrix()
        glLoadIdentity()

        # ADD THIS: Guaranteed state reset before any HUD text rendering
        glDisable(GL_LIGHTING)
        glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE)
        glColor4f(1.0, 1.0, 1.0, 1.0)

        # Objective HUD
        pad = 10
        box_w = 320
        box_h = 56
        x = (w - box_w) // 2
        y = pad
        rect(float(x), float(y), float(box_w),
             float(box_h), 0.0, 0.0, 0.0, 0.62)
        self._gl_outline_rect(float(x), float(y), float(
            box_w), float(box_h), color=(240, 240, 240, 255))

        t = int(getattr(self.core, 'elapsed_s', 0.0) or 0.0)
        mm = t // 60
        ss = t % 60
        self._gl_text(float(x + 12), float(y + 1),
                      f'Time: {mm:02d}:{ss:02d}', 1.0, font_size=11, bold=True, color=HUD_COL_WHITE)

        coins = int(getattr(self.core, 'coins_collected', 0))
        coins_req = int(getattr(self.core, 'coins_required', 0))
        keys = int(getattr(self.core, 'keys_collected', 0))
        keys_req = int(getattr(self.core, 'keys_required', 0))
        self._gl_text(float(x + 12), float(y + 22),
                      f'Coins: {coins}/{coins_req}   Keys: {keys}/{keys_req}', 1.0, font_size=11, bold=False, color=HUD_COL_WHITE)

        # Minimap icon
        icon_size = 54
        ix = w - icon_size - 16
        iy = h - icon_size - 16
        self._cam_icon_rect = wx.Rect(ix, iy, icon_size, icon_size)

        rect(float(ix - 6), float(iy - 6), float(icon_size + 12),
             float(icon_size + 12), 0.0, 0.0, 0.0, 0.50)
        self._gl_outline_rect(float(ix - 6), float(iy - 6), float(icon_size + 12),
                              float(icon_size + 12), color=(220, 220, 220, 255))

        if self._cam_icon_tex:
            from OpenGL.GL import glBindTexture

            glEnable(GL_TEXTURE_2D)
            glBindTexture(GL_TEXTURE_2D, int(self._cam_icon_tex))
            glColor4f(1.0, 1.0, 1.0, 1.0)
            glBegin(GL_QUADS)
            # Minimap icon needs to be upright - compensate for vertical texture flip
            glTexCoord2f(0.0, 0.0)  # Top-left (flipped from 1.0)
            glVertex2f(float(ix), float(iy))
            glTexCoord2f(1.0, 0.0)  # Top-right (flipped from 1.0)
            glVertex2f(float(ix + icon_size), float(iy))
            glTexCoord2f(1.0, 1.0)  # Bottom-right (flipped from 0.0)
            glVertex2f(float(ix + icon_size), float(iy + icon_size))
            glTexCoord2f(0.0, 1.0)  # Bottom-left (flipped from 0.0)
            glVertex2f(float(ix), float(iy + icon_size))
            glEnd()
            glBindTexture(GL_TEXTURE_2D, 0)

        now = time.perf_counter()
        if now < float(self._minimap_cooldown_until):
            remaining = max(0.0, float(self._minimap_cooldown_until) - now)
            rect(float(ix), float(iy), float(icon_size),
                 float(icon_size), 0.0, 0.0, 0.0, 0.62)
            self._gl_text(float(ix + 10), float(iy + 16), f'{int(math.ceil(remaining))}s',
                          1.0, font_size=HUD_FS_MED, bold=True, color=(255, 210, 90, 255))

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
                alpha = max(
                    0.0, min(1.0, (total - popup_t) / max(0.001, fade_in)))
            elif popup_t < fade_out:
                alpha = max(0.0, min(1.0, popup_t / max(0.001, fade_out)))

            txt = f'SECTOR {popup_id}'
            _, tw_px, th_px = self.renderer.get_text_texture(
                txt, font_family='Arial', font_size=11, bold=False, color=(255, 220, 110, 255), pad=2)
            tw = float(tw_px)
            th = float(th_px)
            bx = float((w - tw) * 0.5)
            by = float(h - 20)
            pad_px = 10
            self._gl_rect(float(bx), float(by - th), float(tw + pad_px),
                          float(th + 12), 0.0, 0.0, 0.0, float((150 / 255) * alpha))
            self._gl_text(float(bx), float(by - th), txt, 1.0, font_size=11,
                          bold=True, color=(255, 220, 110, int(255 * alpha)))

        if (not self._modal_visible) and bool(getattr(self.core, 'paused', False)):
            self._draw_pause_panel_gl(w, h)

        # Closing animation: iris-wipe to black when screen_closing is set.
        # Suppressed once stats/end screen takes over (it draws its own black bg).
        if not getattr(self, '_stats_visible', False):
            screen_close_progress = float(
                getattr(self.core, 'screen_close_progress', 0.0) or 0.0)
            if screen_close_progress > 0.0:
                self._draw_closing_animation_gl(w, h, screen_close_progress)

        # Stats / end screen overlays (drawn on top of everything else)
        if getattr(self, '_stats_visible', False):
            if getattr(self, '_end_screen_visible', False):
                self._draw_end_screen_gl(w, h)
            else:
                self._draw_stats_screen_gl(w, h)
            # Draw modal on top of stats/end screen
            if getattr(self, '_modal_visible', False):
                self._draw_modal_gl(w, h)

        # Draw lore fade (after modal, before pause panel)
        self._draw_lore_fade_gl(w, h)

        # Draw "THE END" screen (if Level 2 complete)
        if getattr(self, '_show_the_end', False):
            self._draw_the_end_gl(w, h)

        # Draw modal on top of everything else (when stats not visible)
        if getattr(self, '_modal_visible', False) and not getattr(self, '_stats_visible', False):
            self._draw_modal_gl(w, h)

        # Restore matrices - safe cleanup even if stack was reset
        try:
            glMatrixMode(GL_MODELVIEW)
            glPopMatrix()
        except Exception:
            pass  # Stack was reset, nothing to pop

        try:
            glMatrixMode(GL_PROJECTION)
            glPopMatrix()
        except Exception:
            pass  # Stack was reset, nothing to pop

        glMatrixMode(GL_MODELVIEW)

        glDisable(GL_TEXTURE_2D)
        glEnable(GL_DEPTH_TEST)

    def _draw_the_end_gl(self, w: int, h: int) -> None:
        """Draw 'THE END' screen with black background and white text - matches PySide version"""
        # Draw black background
        self._gl_rect(0.0, 0.0, float(w), float(h), 0.0, 0.0, 0.0, 1.0)

        # Draw "THE END" text in white, centered, large font
        self._gl_text_center(0.0, 0.0, float(w), float(
            h), 'THE END', 1.0, font_size=68, bold=True, color=(255, 255, 255, 255))

    def _gl_rect(self, x: float, y: float, ww: float, hh: float, r: float, g: float, b: float, a: float) -> None:
        # Save and manage OpenGL state properly
        # Note: In HUD context, only manage texture state, don't affect depth testing
        texture_2d_enabled = glIsEnabled(GL_TEXTURE_2D)
        glDisable(GL_TEXTURE_2D)
        glColor4f(r, g, b, a)
        glBegin(GL_QUADS)
        glVertex2f(x, y)
        glVertex2f(x + ww, y)
        glVertex2f(x + ww, y + hh)
        glVertex2f(x, y + hh)
        glEnd()

        # Restore only texture state
        if texture_2d_enabled:
            glEnable(GL_TEXTURE_2D)

    def _gl_text(self, x: float, y: float, txt: str, scale: float = 1.0, *,
                 font_size: int = 28, bold: bool = True,
                 color: tuple[int, int, int, int] = (240, 240, 240, 255)) -> None:
        tex_id, tw_px, th_px = self.renderer.get_text_texture(
            str(txt),
            font_family='Arial',
            font_size=int(font_size),
            bold=bool(bold),
            color=tuple(int(c) for c in color),
            pad=8,
        )
        tex_id = int(tex_id)
        if tex_id <= 0 or tw_px <= 0 or th_px <= 0:
            return
        tw = float(tw_px) * float(scale)
        th = float(th_px) * float(scale)

        # Force proper OpenGL state for text rendering
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)
        glEnable(GL_TEXTURE_2D)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        # ADD THIS: Use texture color directly
        glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE)

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
            font_family='Arial',
            font_size=int(font_size),
            bold=bool(bold),
            color=tuple(int(c) for c in color),
            pad=8,
        )
        tw = float(tw_px) * float(scale)
        th = float(th_px) * float(scale)
        self._gl_text(float(x + (ww - tw) * 0.5), float(y + (hh - th) * 0.5),
                      txt, scale, font_size=font_size, bold=bold, color=color)

    def _gl_line(self, x1: float, y1: float, x2: float, y2: float, *, color: tuple[int, int, int, int]) -> None:
        # Save and manage OpenGL state properly
        texture_2d_enabled = glIsEnabled(GL_TEXTURE_2D)
        glDisable(GL_TEXTURE_2D)
        glColor4f(float(color[0]) / 255.0, float(color[1]) / 255.0,
                  float(color[2]) / 255.0, float(color[3]) / 255.0)
        glBegin(GL_LINES)
        glVertex2f(float(x1), float(y1))
        glVertex2f(float(x2), float(y2))
        glEnd()

        # Restore only texture state, preserve depth testing state for HUD
        if texture_2d_enabled:
            glEnable(GL_TEXTURE_2D)

    def _gl_outline_rect(self, x: float, y: float, ww: float, hh: float, *, color: tuple[int, int, int, int]) -> None:
        self._gl_line(float(x), float(y), float(x + ww), float(y), color=color)
        self._gl_line(float(x + ww), float(y), float(x + ww),
                      float(y + hh), color=color)
        self._gl_line(float(x + ww), float(y + hh),
                      float(x), float(y + hh), color=color)
        self._gl_line(float(x), float(y + hh), float(x), float(y), color=color)

    def _wrap_text_lines(self, text: str, *, max_width_px: int, font_size: int, bold: bool) -> list[str]:
        s = str(text or '')
        out: list[str] = []
        for para in s.split('\n'):
            p = str(para).strip()
            if not p:
                out.append('')
                continue
            words = p.split(' ')
            line = ''
            for w in words:
                trial = (line + ' ' + w).strip() if line else w
                _, tw, _ = self.renderer.get_text_texture(trial, font_family='Arial', font_size=int(
                    font_size), bold=bool(bold), color=(220, 220, 220, 255), pad=8)
                if int(tw) <= int(max_width_px) or not line:
                    line = trial
                    continue
                out.append(line)
                line = w
            if line:
                out.append(line)
        return out

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

    def is_lore_playing(self) -> bool:
        """Check if lore is currently playing"""
        return bool(self._lore_current)

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

    def _draw_closing_animation_gl(self, w: int, h: int, progress: float) -> None:
        """Iris-wipe to black as screen_close_progress goes 0 → 1."""
        # The iris shrinks from full screen to a dot, then covers everything
        cx = float(w) * 0.5
        cy = float(h) * 0.5
        max_r = math.sqrt(cx * cx + cy * cy) + 4.0
        # Ease the iris inward
        ease = progress * progress
        inner_r = max_r * (1.0 - ease)

        glDisable(GL_TEXTURE_2D)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glColor4f(0.0, 0.0, 0.0, 1.0)

        # Draw a full-screen black quad with a circular hole (stencil-free approach:
        # draw the outer ring as a triangle fan from edge to inner_r)
        steps = 64
        outer_r = max_r + 4.0
        glBegin(GL_TRIANGLE_STRIP)
        for i in range(steps + 1):
            a = (i / steps) * 2.0 * math.pi
            ca = math.cos(a)
            sa = math.sin(a)
            glVertex2f(cx + ca * inner_r, cy + sa * inner_r)
            glVertex2f(cx + ca * outer_r, cy + sa * outer_r)
        glEnd()

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

        duration = max(0.01, float(self._lore_current_end) -
                       float(self._lore_current_start))
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
        _, tw_px, th_px = self.renderer.get_text_texture(
            text, font_family='Arial', font_size=18, bold=False, color=(255, 255, 255, 255), pad=10)
        tw = float(min(w - 80, int(tw_px)))
        th = float(th_px)
        bx = float((w - tw) * 0.5)
        by = float(int(h * 0.56))

        outline_col = (0, 0, 0, alpha)
        # Approximate QPen width(3) - two rings of offsets
        offsets = [
            (-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1),
            (-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2), (-2, 2), (2, -2),
        ]
        for ox, oy in offsets:
            self._gl_text_center(bx + float(ox), by + float(oy), tw, th +
                                 4.0, text, 1.0, font_size=18, bold=False, color=outline_col)
        self._gl_text_center(bx, by, tw, th + 4.0, text, 1.0,
                             font_size=18, bold=False, color=(255, 255, 255, alpha))

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
        glVertex2f(float(x0 + maze_content_width),
                   float(y0 + maze_content_height))
        glVertex2f(float(x0), float(y0 + maze_content_height))
        glEnd()

        # Walls/floors (match PySide palette)
        for r in range(maze_rows):
            row = layout[r]
            for c in range(maze_cols):
                ch = row[c]
                rx = x0 + c * cell_px
                ry = y0 + r * cell_px
                if ch == '#':
                    glColor4f(45 / 255, 45 / 255, 55 / 255, 1.0)
                else:
                    if (r, c) in getattr(self.core, 'floors', set()):
                        glColor4f(125 / 255, 125 / 255, 135 / 255, 1.0)
                    else:
                        glColor4f(15 / 255, 15 / 255, 18 / 255, 1.0)
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

        def _circle(cx: float, cy: float, radius: float, col: tuple[float, float, float, float]) -> None:
            glColor4f(col[0], col[1], col[2], col[3])
            glBegin(GL_TRIANGLE_FAN)
            glVertex2f(cx, cy)
            steps = 18
            for i in range(steps + 1):
                a = (i / steps) * (2.0 * math.pi)
                glVertex2f(cx + math.cos(a) * radius,
                           cy + math.sin(a) * radius)
            glEnd()

        # Coins (match PySide: yellow circle with subtle outline)
        coin_size = max(6, int(cell_px * 0.35))
        for coin in getattr(self.core, 'coins', {}).values():
            try:
                if getattr(coin, 'taken', False):
                    continue
                rr, cc = coin.cell
            except Exception:
                continue
            sx, sy = to_screen(float(rr) + 0.5, float(cc) + 0.5)
            r = float(coin_size) * 0.5
            _circle(float(sx), float(sy), r * 1.08, (1.0, 200 / 255, 0.0, 1.0))
            _circle(float(sx), float(sy), r, (1.0, 215 / 255, 0.0, 1.0))

        # Ghosts
        ghost_colors: dict[int, tuple[float, float, float]] = {
            1: (1.0, 80 / 255, 60 / 255),
            2: (80 / 255, 1.0, 140 / 255),
            3: (110 / 255, 170 / 255, 1.0),
            4: (1.0, 220 / 255, 80 / 255),
            5: (1.0, 90 / 255, 1.0),
        }
        ghost_size = max(8, int(cell_px * 0.6))

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
            _circle(float(sx), float(sy), float(gsz) *
                    0.5, (col[0], col[1], col[2], 0.95))

            # Eyes (match PySide minimap: white eyes + black pupils)
            eye_size = max(2, int(gsz * 0.15))
            eye_offset_x = float(gsz) * 0.25
            eye_offset_y = float(gsz) * 0.10
            _circle(float(sx - eye_offset_x), float(sy - eye_offset_y),
                    float(eye_size) * 0.6, (1.0, 1.0, 1.0, 1.0))
            _circle(float(sx + eye_offset_x), float(sy - eye_offset_y),
                    float(eye_size) * 0.6, (1.0, 1.0, 1.0, 1.0))

            pupil_size = max(1, int(eye_size * 0.5))
            _circle(float(sx - eye_offset_x), float(sy - eye_offset_y),
                    float(pupil_size) * 0.6, (0.0, 0.0, 0.0, 1.0))
            _circle(float(sx + eye_offset_x), float(sy - eye_offset_y),
                    float(pupil_size) * 0.6, (0.0, 0.0, 0.0, 1.0))

        # Player marker
        px = float(getattr(self.core.player, 'x', 0.0))
        pz = float(getattr(self.core.player, 'z', 0.0))
        yaw = float(getattr(self.core.player, 'yaw', 0.0))

        pr = int(pz)
        pc = int(px)
        cx = x0 + int((pc + 0.5) * cell_px)
        cy = y0 + int((pr + 0.5) * cell_px)

        player_size = max(12, int(cell_px * 0.7))
        half = float(player_size) * 0.5
        # Diamond fill
        glColor4f(50 / 255, 255 / 255, 50 / 255, 1.0)
        glBegin(GL_QUADS)
        glVertex2f(float(cx), float(cy - half))
        glVertex2f(float(cx + half), float(cy))
        glVertex2f(float(cx), float(cy + half))
        glVertex2f(float(cx - half), float(cy))
        glEnd()
        # Outline (green, width 2)
        try:
            glLineWidth(2.0)
        except Exception:
            pass
        self._gl_line(float(cx), float(cy - half), float(cx +
                      half), float(cy), color=(0, 255, 0, 255))
        self._gl_line(float(cx + half), float(cy), float(cx),
                      float(cy + half), color=(0, 255, 0, 255))
        self._gl_line(float(cx), float(cy + half), float(cx -
                      half), float(cy), color=(0, 255, 0, 255))
        self._gl_line(float(cx - half), float(cy), float(cx),
                      float(cy - half), color=(0, 255, 0, 255))
        try:
            glLineWidth(1.0)
        except Exception:
            pass

        # Center white dot
        center_size = float(player_size) * 0.4
        _circle(float(cx), float(cy), float(
            center_size) * 0.5, (1.0, 1.0, 1.0, 1.0))

        # Facing line (keep as-is for now)
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

        self._gl_rect(float(x0), float(y0), float(panel_w), float(
            panel_h), 18 / 255, 18 / 255, 22 / 255, 235 / 255)

        # Title
        title = 'PAUSED'
        self._gl_text_center(float(x0), float(y0 + 10), float(panel_w), 54.0, title,
                             1.0, font_size=HUD_FS_PAUSE_TITLE, bold=True, color=HUD_COL_YELLOW)

        # Stats area — live values from PerformanceMonitor
        stats_x = x0 + 36
        stats_y = y0 + 96
        line_h = 24
        pm = getattr(self, 'performance_monitor', None)
        if pm is not None:
            fps_val = int(pm.stable_fps())
            lat_val = pm.avg_input_latency_ms()
            ram_val = pm.current_ram_mb()
            fps_str = f'FPS: {fps_val}'
            lat_str = f'Avg input latency: {lat_val:.1f} ms'
            ram_str = f'RAM usage: {ram_val:.1f} MB'
        else:
            fps_str = 'FPS: —'
            lat_str = 'Avg input latency: — ms'
            ram_str = 'RAM usage: — MB'
        self._gl_text(float(stats_x), float(stats_y + line_h * 0), fps_str,
                      1.0, font_size=HUD_FS_SMALL, bold=False, color=(235, 235, 235, 255))
        self._gl_text(float(stats_x), float(stats_y + line_h * 1), lat_str,
                      1.0, font_size=HUD_FS_SMALL, bold=False, color=(235, 235, 235, 255))
        self._gl_text(float(stats_x), float(stats_y + line_h * 2), ram_str,
                      1.0, font_size=HUD_FS_SMALL, bold=False, color=(235, 235, 235, 255))

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
            self._gl_rect(float(r.x), float(r.y), float(r.width), float(
                r.height), 32 / 255, 32 / 255, 40 / 255, 235 / 255)
            self._gl_text_center(float(r.x), float(r.y), float(r.width), float(
                r.height), label, 1.0, font_size=HUD_FS_MED, bold=True, color=(255, 255, 255, 255))

    def _draw_stats_screen_gl(self, w: int, h: int) -> None:
        """Full-screen stats overlay drawn when the level ends."""
        self._gl_rect(0.0, 0.0, float(w), float(h), 0.0, 0.0, 0.0, 1.0)

        text = str(getattr(self, '_stats_text', '') or '')
        if not text:
            return

        lines = [ln.rstrip() for ln in text.split('\n')]
        # Remove leading/trailing blank lines
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()

        # Auto-fit: shrink line height so all lines fit with top/bottom padding
        usable_h = h - 80  # 40px padding top + 40px for ESC hint at bottom
        ideal_line_h = 26
        line_h = min(ideal_line_h, max(14, usable_h // max(1, len(lines))))
        total_h = len(lines) * line_h
        start_y = max(36, (h - total_h - 50) // 2)

        # Font size scales with line height
        fs_body = max(10, min(14, line_h - 4))
        fs_header = fs_body + 1

        for i, ln in enumerate(lines):
            y = start_y + i * line_h
            is_sep = ln.startswith('─')
            is_header = (ln.isupper() and len(ln) > 2
                         and not ln.startswith('•') and not is_sep)
            if is_sep:
                color: tuple[int, int, int, int] = (100, 100, 100, 200)
                fs = fs_body
            elif is_header:
                color = (255, 220, 80, 255)
                fs = fs_header
            else:
                color = (230, 230, 230, 255)
                fs = fs_body
            self._gl_text_center(0.0, float(y), float(w), float(line_h),
                                 ln, 1.0, font_size=fs, bold=is_header, color=color)

        self._gl_text_center(0.0, float(h - 46), float(w), 30.0,
                             'Press ESC to continue', 1.0,
                             font_size=13, bold=False, color=(160, 160, 160, 255))

    def _draw_end_screen_gl(self, w: int, h: int) -> None:
        """End screen stats display (Level 2) - shows only stats, no extra text."""
        # Draw black background
        self._gl_rect(0.0, 0.0, float(w), float(h), 0.0, 0.0, 0.0, 1.0)

        # Draw stats text
        text = str(getattr(self, '_stats_text', '') or '')
        if text:
            lines = [ln.rstrip() for ln in text.split('\n')]
            while lines and not lines[0]:
                lines.pop(0)
            while lines and not lines[-1]:
                lines.pop()
            # Auto-fit: shrink line height so all lines fit with top/bottom padding
            usable_h = h - 80  # 40px padding top + 40px for ESC hint at bottom
            ideal_line_h = 26
            line_h = min(ideal_line_h, max(14, usable_h // max(1, len(lines))))
            total_h = len(lines) * line_h
            start_y = max(36, (h - total_h - 50) // 2)

            # Font size scales with line height
            fs_body = max(10, min(14, line_h - 4))
            fs_header = fs_body + 1

            for i, ln in enumerate(lines):
                y = start_y + i * line_h
                is_sep = ln.startswith('─')
                is_header = (ln.isupper() and len(ln) > 2
                             and not ln.startswith('•') and not is_sep)
                if is_sep:
                    color: tuple[int, int, int, int] = (100, 100, 100, 200)
                    fs = fs_body
                elif is_header:
                    color = (255, 210, 60, 255)
                    fs = fs_header
                else:
                    color = (210, 210, 210, 255)
                    fs = fs_body
                self._gl_text_center(0.0, float(y), float(w), float(line_h),
                                     ln, 1.0, font_size=fs, bold=is_header, color=color)

        self._gl_text_center(0.0, float(h - 46), float(w), 30.0,
                             'Press ESC to continue', 1.0, font_size=14, bold=False,
                             color=(150, 150, 150, 255))

    def _draw_modal_gl(self, w: int, h: int) -> None:
        # Save current OpenGL state before modal rendering
        texture_2d_enabled = glIsEnabled(GL_TEXTURE_2D)
        blend_enabled = glIsEnabled(GL_BLEND)
        depth_test_enabled = glIsEnabled(GL_DEPTH_TEST)
        lighting_enabled = glIsEnabled(GL_LIGHTING)

        # Set proper state for modal rendering
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        if self._modal_kind == 'level_select':
            self._gl_rect(0.0, 0.0, float(w), float(h),
                          0.0, 0.0, 0.0, 255 / 255)
        else:
            self._gl_rect(0.0, 0.0, float(w), float(h),
                          0.0, 0.0, 0.0, 160 / 255)
        self._modal_btn_rects.clear()

        if self._modal_kind == 'level_select':
            title = self._modal_title or 'Select Level'
            body = self._modal_body or ''

            self._gl_text_center(float(0), float(
                h * 0.10), float(w), 80.0, title, 1.0, font_size=38, bold=True, color=HUD_COL_WHITE)
            if body:
                self._gl_text_center(float(0), float(h * 0.10 + 60), float(
                    w), 50.0, body, 1.0, font_size=14, bold=False, color=(200, 200, 200, 255))

            btn_w = min(620, int(w * 0.62))
            btn_h = 82
            gap = 22
            bx = (w - btn_w) // 2
            by1 = int(h * 0.34)
            by2 = by1 + btn_h + gap

            modal_unlocked = set(
                getattr(self, '_modal_unlocked', None) or set())

            def draw_btn(key: str, yy: int, label: str, enabled: bool) -> None:
                r = wx.Rect(int(bx), int(yy), int(btn_w), int(btn_h))
                if enabled:
                    self._gl_rect(float(r.x), float(r.y), float(r.width), float(
                        r.height), 22 / 255, 22 / 255, 26 / 255, 1.0)
                else:
                    self._gl_rect(float(r.x), float(r.y), float(r.width), float(
                        r.height), 22 / 255, 22 / 255, 26 / 255, 190 / 255)
                self._gl_text_center(float(r.x), float(r.y), float(r.width), float(
                    r.height), label, 1.0, font_size=26, bold=True, color=HUD_COL_WHITE if enabled else (140, 140, 140, 255))
                self._modal_btn_rects[key] = r

            draw_btn('level1', by1, 'Level 1', True)
            lvl2_enabled = 'level2' in modal_unlocked
            draw_btn(
                'level2', by2, 'Level 2' if lvl2_enabled else 'Level 2 (Locked)', lvl2_enabled)

            close_size = 38
            close_x = w - close_size - 20
            close_y = 18
            close_r = wx.Rect(int(close_x), int(close_y),
                              int(close_size), int(close_size))
            self._modal_btn_rects['close'] = close_r

            a = 220 / 255 if self._modal_allow_close else 120 / 255
            self._gl_rect(float(close_r.x), float(close_r.y), float(
                close_r.width), float(close_r.height), a, a, a, 0.15)
            self._gl_text_center(float(close_r.x), float(close_r.y), float(close_r.width), float(
                close_r.height), 'X', 1.0, font_size=22, bold=True, color=(255, 255, 255, 255 if self._modal_allow_close else 140))

        elif self._modal_kind == 'tutorial':
            title = str(self._modal_title or '')
            body = str(self._modal_body or '')

            panel_w = min(840, int(w * 0.74))
            panel_h = min(440, int(h * 0.56))
            x0 = (w - panel_w) // 2
            y0 = (h - panel_h) // 2

            self._gl_rect(float(x0), float(y0), float(panel_w), float(
                panel_h), 18 / 255, 18 / 255, 22 / 255, 245 / 255)
            self._gl_outline_rect(float(x0), float(y0), float(
                panel_w), float(panel_h), color=(235, 235, 235, 255))

            # Title
            if title:
                self._gl_text(float(x0 + 24), float(y0 + 44), title, 1.0,
                              font_size=18, bold=True, color=(235, 235, 235, 255))

            # Body (multiline)
            body_rect_x = x0 + 24
            body_rect_y = y0 + 84
            body_rect_w = panel_w - 48
            lines = self._wrap_text_lines(body, max_width_px=int(
                body_rect_w), font_size=14, bold=False)
            lh = 18
            for i, ln in enumerate(lines):
                if ln == '':
                    continue
                self._gl_text(float(body_rect_x), float(body_rect_y + i * lh),
                              ln, 1.0, font_size=14, bold=False, color=(220, 220, 220, 255))

            # Close button (top-right)
            close_size = 32
            close_x = x0 + panel_w - 24 - close_size
            close_y = y0 + 22
            close_r = wx.Rect(int(close_x), int(close_y),
                              int(close_size), int(close_size))
            self._modal_btn_rects['close'] = close_r
            pen = (220, 220, 220, 255) if self._modal_allow_close else (
                120, 120, 120, 255)
            self._gl_line(float(close_x), float(close_y), float(
                close_x + close_size), float(close_y), color=pen)
            self._gl_line(float(close_x + close_size), float(close_y),
                          float(close_x + close_size), float(close_y + close_size), color=pen)
            self._gl_line(float(close_x + close_size), float(close_y + close_size),
                          float(close_x), float(close_y + close_size), color=pen)
            self._gl_line(float(close_x), float(close_y + close_size),
                          float(close_x), float(close_y), color=pen)
            self._gl_line(float(close_x + 7), float(close_y + 7), float(close_x +
                          close_size - 7), float(close_y + close_size - 7), color=pen)
            self._gl_line(float(close_x + close_size - 7), float(close_y + 7),
                          float(close_x + 7), float(close_y + close_size - 7), color=pen)

        # Restore OpenGL state after modal rendering
        if texture_2d_enabled:
            glEnable(GL_TEXTURE_2D)
        else:
            glDisable(GL_TEXTURE_2D)

        if blend_enabled:
            glEnable(GL_BLEND)
        else:
            glDisable(GL_BLEND)

        if depth_test_enabled:
            glEnable(GL_DEPTH_TEST)
        else:
            glDisable(GL_DEPTH_TEST)

        if lighting_enabled:
            glEnable(GL_LIGHTING)
        else:
            glDisable(GL_LIGHTING)

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
        # Use actual screen size instead of ShowFullScreen to avoid sizing issues
        screen = wx.Display().GetClientArea()
        width, height = screen.GetWidth(), screen.GetHeight()

        super().__init__(None, title='Within the Walls (WxPython)', size=(width, height))
        self.Show()
        self.Center()

        self._progress_path = os.path.abspath('progression_wx.json')
        self._progress = self._load_progression()

        unlocked = set(self._progress.get('unlocked_levels') or [])
        last_level = str(self._progress.get('last_level') or 'level1')
        if last_level not in unlocked:
            last_level = 'level1'

        self._save_path = os.path.abspath('savegame_wx.json')

        self._autoload_level1_save = False
        if last_level == 'level1' and os.path.exists(self._save_path):
            self._autoload_level1_save = True

        self.core = GameCore(level_id=last_level)
        self._current_level_id = last_level

        self._asset_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', '..', 'assets'))

        # Use the working audio system
        self._audio = _SimpleAudio(self._asset_dir)

        # Ghost sound timer - every 10 seconds globally
        self._ghost_sound_timer_active = True
        self._schedule_ghost_sound()

        self._key_minigame_open = False
        self._assembly_minigame: Optional[Assembly3DMinigame] = None

        self._lore_flags: dict[str, bool] = {}
        self._persist_seen: dict[str, bool] = {}

        self._pending_gameplay_tutorial = False

        self._callbacks_core_token: int = 0

        self.keys_pressed: set[int] = set()

        # Performance monitor — shared reference given to canvas after construction
        self.performance_monitor = PerformanceMonitor(framework='wxPython')

        # Connect performance monitor to game core for tracking
        self.core._performance_monitor = self.performance_monitor
        self.performance_monitor._game_start_time = time.perf_counter()

        self.canvas = GameGLCanvas(self, self.core)
        self.canvas.performance_monitor = self.performance_monitor

        # Level-end flow state
        # True once we've handled game_won for this level
        self._level_end_triggered: bool = False
        # True once PDF has been exported for this level
        self._perf_pdf_exported: bool = False

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.canvas, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)
        self.Bind(wx.EVT_ICONIZE, self._on_iconize)
        self.Bind(wx.EVT_TIMER, self._on_tick)

        # Route input through the canvas (focus stays there during gameplay).
        self.canvas.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.canvas.Bind(wx.EVT_KEY_UP, self._on_key_up)
        self.canvas.Bind(wx.EVT_LEFT_DOWN, self._on_click)
        self.canvas.Bind(wx.EVT_KILL_FOCUS, self._on_kill_focus)
        # Bind mouse capture lost event to prevent wxPython assertion errors
        try:
            self.canvas.Bind(wx.EVT_MOUSE_CAPTURE_LOST,
                             self.canvas._on_mouse_capture_lost)
        except AttributeError:
            # Handler might not exist yet, bind after canvas is fully initialized
            wx.CallAfter(lambda: self.canvas.Bind(
                wx.EVT_MOUSE_CAPTURE_LOST, self.canvas._on_mouse_capture_lost))

        self._tick = wx.Timer(self)
        self._tick.Start(16)

        self._last_update_time = time.perf_counter()

        # Defer VBO building to avoid blocking startup
        wx.CallLater(100, self._deferred_initialization)

        self._register_core_callbacks()

    def _deferred_initialization(self) -> None:
        """Build VBOs after window is shown to avoid blocking startup"""
        if hasattr(self.canvas, 'renderer') and self.canvas.renderer:
            try:
                # Wait for window to be properly sized before loading textures
                wx.CallLater(1000, self._check_canvas_size_and_load)
            except Exception:
                pass

    def _check_canvas_size_and_load(self) -> None:
        """Check if canvas is properly sized before loading textures"""
        w, h = self.canvas.GetClientSize()

        # Force canvas to resize if it's still small
        if w < 1800 or h < 900:
            # Force window layout update
            self.Layout()
            self.Update()
            self.Refresh()

        # Check again after layout update
        w, h = self.canvas.GetClientSize()

        # Only load textures when canvas is at proper size
        if w >= 1800 and h >= 900:
            self._deferred_texture_loading()
        else:
            # Canvas still too small, wait longer
            wx.CallLater(500, self._check_canvas_size_and_load)

    def _deferred_texture_loading(self) -> None:
        """Load textures and build geometry after window is fully shown"""
        if hasattr(self.canvas, 'renderer') and self.canvas.renderer:
            try:
                self.canvas.renderer._ensure_geometry_built()
                self.canvas.renderer._ensure_textures_loaded()
            except Exception:
                pass

        if self._current_level_id == 'level2':
            self._set_paused(False)
            self._start_level(
                'level2', load_save=os.path.exists(self._save_path))
        elif self._autoload_level1_save:
            self._set_paused(False)
            self._start_level('level1', load_save=True)
        else:
            self._open_level_select_modal(startup=True)

    def _schedule_ghost_sound(self) -> None:
        """Schedule next ghost sound check using CallLater"""
        if not getattr(self, '_ghost_sound_timer_active', False):
            return
        # Every 10 seconds globally
        wx.CallLater(10000, self._ghost_sound_check)

    def _ghost_sound_check(self) -> None:
        """Called by CallLater to play ghost sounds globally"""
        if not getattr(self, '_ghost_sound_timer_active', False):
            return
        self._play_ghost_sound_global()
        # Schedule next check
        self._schedule_ghost_sound()

    def _play_ghost_sound_global(self) -> None:
        """Play ghost sound globally"""
        try:
            # Only check if game is paused or won - ignore player movement
            if getattr(self.core, 'paused', False):
                return
            if bool(getattr(self.core, 'game_won', False)) or bool(getattr(self.core, 'game_completed', False)):
                return

            # Play ghost sound globally using the working method
            self._audio.play_ghost(volume=0.8)
        except Exception:
            pass

    def _set_footsteps_playing(self, playing: bool) -> None:
        try:
            self._audio.set_footsteps(bool(playing))
        except Exception:
            pass

    def _reset_input_state(self) -> None:
        try:
            self.keys_pressed.clear()
        except Exception:
            pass
        try:
            self.canvas.hide_mouse_capture()
        except Exception:
            pass
        try:
            self._set_footsteps_playing(False)
        except Exception:
            pass

    def _on_activate(self, evt: wx.ActivateEvent) -> None:
        try:
            if not bool(evt.GetActive()):
                self._reset_input_state()
        except Exception:
            pass
        evt.Skip()

    def _on_iconize(self, evt: wx.IconizeEvent) -> None:
        try:
            if bool(evt.IsIconized()):
                self._reset_input_state()
        except Exception:
            pass
        evt.Skip()

    def _on_kill_focus(self, evt: wx.FocusEvent) -> None:
        self._reset_input_state()
        evt.Skip()

    def _register_core_callbacks(self) -> None:
        try:
            token = id(self.core)
            if int(getattr(self, '_callbacks_core_token', 0) or 0) == int(token):
                return
            self._callbacks_core_token = int(token)

            self.core.register_event_callback(
                'coin_picked', self._on_coin_picked)
            self.core.register_event_callback(
                'gate_opened', self._on_gate_moved)
            self.core.register_event_callback(
                'gate_closed', self._on_gate_moved)
            self.core.register_event_callback(
                'time_penalty', self._on_time_penalty)
            self.core.register_event_callback(
                'exit_unlocked', self._on_exit_unlocked)
            self.core.register_event_callback(
                'sector_entered', self._on_sector_entered)
            self.core.register_event_callback(
                'sent_to_jail', self._on_sent_to_jail)
            self.core.register_event_callback('left_jail', self._on_left_jail)
            self.core.register_event_callback(
                'key_fragment_encountered', self._on_key_fragment_encountered)
            self.core.register_event_callback(
                'key_picked', self._on_key_picked)
        except Exception:
            pass

    def _trigger_lore(self, key: str) -> None:
        """Trigger lore events"""
        # Backwards-compatible no-op mapping layer.
        # Lore is now code-driven (no lore.md dependency). Only a small set of keys are supported.
        key = str(key or '').strip()
        if not key:
            return

        txt: Optional[str] = None

        if key == 'ON_GHOST_CLOSE':
            if self._current_level_id == 'level1':
                txt = 'Why are you here?'
            elif self._current_level_id == 'level2':
                txt = 'Wake me up.'
        elif key == 'COIN_HALF':
            if self._current_level_id == 'level1':
                txt = 'Halfway.'
            elif self._current_level_id == 'level2':
                txt = 'The maze likes it when I collect.'
        elif key == 'LEVEL1_INTRO':
            txt = 'A basement? This feels like a test.'
        elif key == 'LEVEL2_INTRO':
            txt = 'This place feels familiar.'

        if txt is not None:
            self._show_lore_line(txt)

    def _show_tutorial_modal(self, title: str, body: str) -> None:
        """Show tutorial modal"""
        try:
            self._set_paused(True)
            self.canvas._modal_visible = True
            self.canvas._modal_kind = 'tutorial'
            self.canvas._modal_title = title
            self.canvas._modal_body = body
            self.canvas._modal_return_to_pause = False
            self.canvas.hide_mouse_capture()
            self.keys_pressed.clear()
        except Exception:
            pass

    def _show_lore_line(self, text: str) -> None:
        try:
            self.canvas.enqueue_lore_lines([str(text)])
        except Exception:
            pass

    def _on_coin_picked(self, data: dict) -> None:
        try:
            self._audio.play_coin()
        except Exception:
            pass
        try:
            if float(self.core.coins_collected) >= float(self.core.coins_required) * 0.5:
                key = f'coins_half_{self._current_level_id}'
                if (not self._lore_flags.get('coins_half')) and (not self._persist_seen.get(key)):
                    self._lore_flags['coins_half'] = True
                    self._persist_seen[key] = True
                    self._trigger_lore('COIN_HALF')
        except Exception:
            pass

    def _on_gate_moved(self, _data: dict) -> None:
        try:
            self._audio.play_gate(volume=1.0)
        except Exception:
            pass

    def _on_time_penalty(self, data: dict) -> None:
        # PySide shows a +Ns popup; we at least do the lore/sfx parity here.
        try:
            seconds = int((data or {}).get('seconds', 0) or 0)
            if seconds > 0:
                self._show_lore_line(f'+{seconds}s')
        except Exception:
            pass

    def _on_exit_unlocked(self, _data: dict) -> None:
        self._show_lore_line('Exit unlocked.')

    def _on_sector_entered(self, data: dict) -> None:
        sid = str((data or {}).get('id', '') or '')
        if (self._current_level_id == 'level2') and (sid == 'F'):
            try:
                req_met = (int(self.core.coins_collected) >= int(self.core.coins_required)) and (
                    int(self.core.keys_collected) >= int(self.core.keys_required))
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

        # Track jail entry for performance monitor
        try:
            self.canvas.performance_monitor.record_jail_entry()
        except Exception:
            pass
            self.canvas.hide_mouse_capture()
            self.keys_pressed.clear()
            # Tutorial modal should not force a permanent pause; ESC will close it and gameplay can continue.
            # Respect existing pause state instead of forcing unpaused
            pass

    def _on_left_jail(self, _data: dict) -> None:
        pass

    def _on_key_picked(self, data: dict) -> None:
        try:
            cnt = int((data or {}).get('count', 0) or 0)
            if (self._current_level_id == 'level2') and (cnt >= 3) and (not self._lore_flags.get('l2_frags_done')):
                self._lore_flags['l2_frags_done'] = True
                self._show_lore_line('The key is done... I am watched.')
        except Exception:
            pass

    def _on_key_fragment_encountered(self, data: dict) -> None:
        if getattr(self.core, 'paused', False):
            return
        if self._key_minigame_open:
            return
        frag_id = str((data or {}).get('id', '') or '')
        if not frag_id:
            return

        frag_kind = ''
        try:
            frag = getattr(self.core, 'key_fragments', {}).get(frag_id)
            frag_kind = str(getattr(frag, 'kind', '') or '')
        except Exception:
            frag_kind = ''

        self._key_minigame_open = True
        self.keys_pressed.clear()
        self._set_footsteps_playing(False)
        self.canvas.hide_mouse_capture()

        prev_frozen = bool(getattr(self.core, 'simulation_frozen', False))
        self.core.simulation_frozen = True

        if self._assembly_minigame is None:
            self._assembly_minigame = Assembly3DMinigame(
                self, kind=frag_kind or 'KP')
        else:
            self._assembly_minigame.reset(kind=frag_kind or 'KP')

        ok = False
        try:
            ok = bool(self._assembly_minigame.ShowModal() == wx.ID_OK)
        finally:
            self.core.simulation_frozen = prev_frozen

        if ok:
            try:
                self.core.mark_key_fragment_taken(frag_id)
            except Exception:
                pass
        else:
            try:
                self.core.clear_pending_key_fragment(frag_id)
                self.core.defer_key_fragment(frag_id)
            except Exception:
                pass

        self.keys_pressed.clear()
        self._key_minigame_open = False
        return

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
            self.keys_pressed.clear()
            self._set_footsteps_playing(False)
            self.canvas.hide_mouse_capture()

            prev_frozen = bool(getattr(self.core, 'simulation_frozen', False))
            self.core.simulation_frozen = True

            dlg = SilhouetteMatchDialog(self)
            ok = False
            try:
                ok = bool(dlg.ShowModal() == wx.ID_OK)
            finally:
                self.core.simulation_frozen = prev_frozen

            if ok:
                try:
                    self.core.mark_jail_puzzle_success()
                except Exception:
                    pass
                if (self._current_level_id == 'level1') and (not self._lore_flags.get('l1_jail_puzzle_success')):
                    self._lore_flags['l1_jail_puzzle_success'] = True
                    self._show_lore_line(
                        'The maze resets what it cannot control.')

            self.keys_pressed.clear()
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

    def _save_game(self) -> None:
        try:
            self._progress['last_level'] = str(
                getattr(self, '_current_level_id', 'level1') or 'level1')
            self._save_progression()
        except Exception:
            pass

        try:
            state = self.core.get_save_state()
            if isinstance(state, dict):
                state['ui_seen'] = dict(self._persist_seen)
            with open(self._save_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def _load_save_if_present(self) -> None:
        if not os.path.exists(self._save_path):
            return
        try:
            with open(self._save_path, 'r', encoding='utf-8') as f:
                state = json.load(f)

            if isinstance(state, dict):
                saved_level = str(state.get('level_id') or '')
                if saved_level and saved_level != str(getattr(self, '_current_level_id', '') or ''):
                    return
                seen = state.get('ui_seen')
                if isinstance(seen, dict):
                    self._persist_seen.update(
                        {str(k): bool(v) for k, v in seen.items()})
            self.core.load_save_state(state)
        except Exception:
            return

    def _set_paused(self, paused: bool) -> None:
        self.core.paused = bool(paused)
        if paused:
            self.keys_pressed.clear()
            self.canvas.hide_mouse_capture()
            self._set_footsteps_playing(False)

    def _toggle_pause(self) -> None:
        if self.core.screen_closing or self.core.game_completed or self.core.game_won:
            return
        now_paused = not bool(getattr(self.core, 'paused', False))
        self._set_paused(now_paused)
        self.canvas.Refresh(False)

    def _open_level_select_modal(self, *, startup: bool) -> None:
        unlocked = set(self._progress.get('unlocked_levels') or [])
        # Pause the game when showing modal (PySide parity)
        if not startup:
            self._set_paused(True)
        try:
            self.canvas.hide_mouse_capture()
        except Exception:
            pass
        self.canvas.show_level_select_modal(unlocked=unlocked, allow_close=(
            not startup), return_to_pause=(not startup))
        # Force immediate refresh to show modal
        self.canvas.Refresh(False)

    def _start_level(self, level_id: str, *, load_save: bool) -> None:
        level_id = str(level_id or 'level1')
        paused_was = bool(getattr(self.core, 'paused', False))

        # Reset frozen state on old core before replacement
        try:
            self.core.simulation_frozen = False
        except Exception:
            pass

        self.core = GameCore(level_id=level_id)
        self._current_level_id = level_id
        self.canvas.core = self.core

        # Reset level-end guard and performance monitor for the new level
        self._level_end_triggered = False
        self._perf_pdf_exported = False
        self._level_complete = False  # Reset level complete flag

        # Explicit cleanup to ensure no cached data persists
        # This prevents minimum FPS and frame drop counts from carrying over
        try:
            self.performance_monitor.frozen_stats = None
            self.performance_monitor.frame_times.clear()
            self.performance_monitor.fps_history.clear()
            self.performance_monitor.input_events.clear()
            self.performance_monitor.input_latencies.clear()
            self.performance_monitor.memory_samples.clear()
            self.performance_monitor.distance_walked = 0.0
        except Exception:
            pass

        # Create fresh performance monitor for the new level
        try:
            self.performance_monitor = PerformanceMonitor(framework='wxPython')
            self.canvas.performance_monitor = self.performance_monitor

            # Connect performance monitor to game core
            self.core._performance_monitor = self.performance_monitor
            self.performance_monitor._game_start_time = time.perf_counter()
        except Exception:
            pass

        for k in ('coins_half', 'ghost_close', 'l2_frags_done', 'l2_sector_f_done'):
            self._lore_flags.pop(k, None)

        # Reset first-movement tracker
        self.__dict__.pop('_player_has_moved', None)

        # Reset "THE END" screen flag
        self.canvas._show_the_end = False

        try:
            self.canvas.SetCurrent(self.canvas._gl_context)
            # Clear text texture cache before replacing renderer
            if hasattr(self.canvas, 'renderer') and self.canvas.renderer:
                self.canvas.renderer.clear_text_texture_cache()
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

        # Load UI/tutorial and saved state
        if bool(load_save):
            try:
                self._load_save_if_present()
            except Exception:
                pass

        # Level intro lore (fresh start only)
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
        dt = min(dt, 0.05)

        # Performance monitor: tick-to-tick wall time
        try:
            self.performance_monitor.record_frame()
        except Exception:
            pass

        paused = bool(getattr(self.core, 'paused', False))
        if not paused:
            self.core.update(dt)

        # Update scene data (resolution + objects)
        try:
            self.performance_monitor.set_resolution(
                *self.canvas.GetClientSize())
            self.performance_monitor.update_scene_data(
                walls_rendered=len(getattr(self.core, 'walls', set())),
                coins=len(getattr(self.core, 'coins', [])),
                ghosts=len(getattr(self.core, 'ghosts', {})),
                spike_traps=len(getattr(self.core, 'spikes', [])),
                moving_platforms=len(getattr(self.core, 'platforms', [])),
            )
        except Exception:
            pass

        # Level-end: game_won fires once per level — freeze, show stats, queue level-select
        game_won = bool(getattr(self.core, 'game_won', False))
        if game_won and not getattr(self, '_level_end_triggered', False):
            self._level_end_triggered = True
            self._handle_level_end()
            return

        # Process pending gameplay tutorial
        if self._pending_gameplay_tutorial and (not getattr(self.canvas, '_modal_visible', False)):
            if not self.canvas.is_lore_playing():
                self._pending_gameplay_tutorial = False

                if (self._current_level_id == 'level1') and (not self._persist_seen.get('tutorial_gameplay')):
                    self._persist_seen['tutorial_gameplay'] = True
                    self._show_tutorial_modal(
                        'Gameplay',
                        'Press WASD to move.\n'
                        'Hold Left Mouse Button to look around.\n'
                        'Press ESC to pause. You can also save and exit from the pause menu.\n\n'
                        'Press M or click the camera icon to open the minimap.\n'
                        'The minimap stays open for 10 seconds, then goes on a 20 second cooldown.\n\n'
                        'Collect all coins and key fragments to unlock the exit.\n'
                        'Avoid hazards. If you get caught, you will be sent to jail.'
                    )

        if paused:
            # Still repaint so pause/menu overlays remain responsive.
            self.canvas.Refresh(False)
            return

        # Freeze player movement and game time when modal is visible
        modal_open = bool(getattr(self.canvas, '_modal_visible', False))
        if modal_open:
            self.canvas.Refresh(False)
            return  # Don't update movement or time when modal is shown

        move_speed = 0.12 if self._current_level_id == 'level1' else 0.18
        dx = 0.0
        dz = 0.0

        W, S, A, D = ord('W'), ord('S'), ord('A'), ord('D')
        if W in self.keys_pressed:
            dz += move_speed
        if S in self.keys_pressed:
            dz -= move_speed
        if A in self.keys_pressed:
            dx -= move_speed
        if D in self.keys_pressed:
            dx += move_speed

        moved = False
        if dx != 0.0 or dz != 0.0:
            try:
                moved = bool(self.core.move_player(dx, dz))
                if moved:
                    _now = time.perf_counter()
                    for kc in (W, S, A, D):
                        if kc in self.keys_pressed:
                            self.performance_monitor.record_input_response(
                                kc, _now)
                # Track first movement for intro lore + tutorial
                if moved and not hasattr(self, '_player_has_moved'):
                    self._player_has_moved = True
                    if self._current_level_id == 'level1' and not self._persist_seen.get('l1_intro'):
                        self._persist_seen['l1_intro'] = True
                        self._trigger_lore('LEVEL1_INTRO')
                        self._pending_gameplay_tutorial = True
                    elif self._current_level_id == 'level2' and not self._persist_seen.get('l2_intro'):
                        self._persist_seen['l2_intro'] = True
                        self._trigger_lore('LEVEL2_INTRO')
            except Exception:
                moved = False

        # Footsteps loop (match PySide: play only when actual movement succeeds)
        modal_open = bool(getattr(self.canvas, '_modal_visible', False))
        sim_frozen = bool(getattr(self.core, 'simulation_frozen', False))
        key_minigame = bool(getattr(self, '_key_minigame_open', False))
        self._set_footsteps_playing(moved and (not modal_open) and (not sim_frozen) and (
            not key_minigame) and (not bool(getattr(self.core, 'paused', False))))

        # Ghost close (distance threshold; once only)
        try:
            # Manual ghost distance calculation like PySide
            nearest = None
            if hasattr(self.core, 'ghosts') and hasattr(self.core, 'player'):
                for g in self.core.ghosts.values():
                    d = math.hypot(g.x - self.core.player.x,
                                   g.z - self.core.player.z)
                    if nearest is None or d < nearest:
                        nearest = d

            if nearest is not None and nearest <= 2.0:
                if not self._lore_flags.get('ghost_close'):
                    self._lore_flags['ghost_close'] = True
                    if not self._persist_seen.get(f'ghost_close_{self._current_level_id}'):
                        self._persist_seen[f'ghost_close_{self._current_level_id}'] = True
                        self._trigger_lore('ON_GHOST_CLOSE')

                # Track ghost encounter for performance monitor
                try:
                    # Ghost encounters removed from tracking
                    pass
                except Exception:
                    pass
        except Exception:
            pass

        # Drive the render loop at the same cadence as gameplay updates.
        self.canvas.Refresh(False)

    def _on_key_down(self, evt: wx.KeyEvent) -> None:
        code = int(evt.GetKeyCode())
        self.keys_pressed.add(code)

        # Handle minimap toggle with 'M' key
        if code == ord('M') or code == ord('m'):
            self.canvas._try_open_minimap()
            return

        # Record input event time for latency measurement (only for movement keys)
        try:
            if code in (ord('W'), ord('S'), ord('A'), ord('D')):
                self.performance_monitor.record_input_event(
                    code, time.perf_counter())
        except Exception:
            pass

        if code in (ord('E'), ord('e')):
            self._handle_interact()
            return

        if code == wx.WXK_ESCAPE:
            # Stats screen / end screen: ESC advances to level-select or exits
            if getattr(self.canvas, '_stats_visible', False):
                self._on_stats_screen_esc()
                return

            if getattr(self.canvas, '_modal_visible', False):
                return_to_pause = bool(
                    getattr(self.canvas, '_modal_return_to_pause', False))
                self.canvas.hide_modal()
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
        # Ignore clicks while stats/end screen is up — only ESC advances it
        if getattr(self.canvas, '_stats_visible', False):
            return

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

    def _handle_level_end(self) -> None:
        """Called once when game_won becomes True. Freezes gameplay, freezes stats,
        then shows either the stats screen (level 1) or the end screen (level 2)."""
        self._level_end_triggered = True
        self._level_complete = True
        # Freeze game simulation
        self.core.simulation_frozen = True
        self._set_footsteps_playing(False)

        # Unlock level 2 if we just finished level 1
        if self._current_level_id == 'level1':
            unlocked = set(self._progress.get('unlocked_levels') or ['level1'])
            unlocked.add('level2')
            self._progress['unlocked_levels'] = sorted(unlocked)
            self._save_progression()

        # Freeze & build the summary text
        try:
            self.performance_monitor.update_scene_data(
                walls_rendered=len(getattr(self.core, 'walls', set())),
                coins=len(getattr(self.core, 'coins', [])),
                ghosts=len(getattr(self.core, 'ghosts', {})),
                spike_traps=len(getattr(self.core, 'spikes', [])),
                moving_platforms=len(getattr(self.core, 'platforms', [])),
            )
            self.performance_monitor._game_core_elapsed_s = self.core.elapsed_s
            self.performance_monitor.freeze_stats()
            t = int(getattr(self.core, 'elapsed_s', 0.0) or 0.0)
            mm, ss = divmod(t, 60)
            gameplay_metrics = {
                'Level': str(self._current_level_id).replace('level', 'Level '),
                'Time': f'{mm:02d}:{ss:02d}',
                'Coins collected': f"{getattr(self.core, 'coins_collected', 0)}/{getattr(self.core, 'coins_required', 0)}",
            }
            summary_text = self.performance_monitor.format_summary_text(
                gameplay_metrics)
        except Exception as exc:
            summary_text = f'Level complete!\n\nPress ESC to continue.\n\n({exc})'

        try:
            # Export PDF only once per level completion
            if not self._perf_pdf_exported:
                # Get performance data from the monitor
                performance_data = self.performance_monitor.get_performance_summary()

                # Prepare gameplay metrics with unified stats
                gameplay_metrics = {
                    'coins_collected': f'{self.core.coins_collected}/{self.core.coins_required}',
                    'keys_collected': f'{self.core.keys_collected}/{self.core.keys_required}',
                    'jail_entries': str(self.core.jail_entries),
                    'avg_coin_collection_time': f'{self.core.avg_coin_time:.1f}s',
                }

                # Import PDF export here to avoid circular imports
                from core.pdf_export import export_performance_pdf

                export_performance_pdf(
                    framework='wxpython',
                    level_id=str(self._current_level_id),
                    performance_data=performance_data,
                    gameplay_metrics=gameplay_metrics,
                    out_dir=os.path.abspath('performance_reports'),
                )
                self._perf_pdf_exported = True
                print(f"[wxPython] PDF report exported to performance_reports/")
        except ImportError as e:
            print(f"[wxPython] PDF export not available: {e}")
        except Exception as e:
            print(f"[wxPython] PDF export failed: {e}")
            import traceback
            traceback.print_exc()

        # Show the appropriate screen
        if self._current_level_id == 'level2':
            self.canvas.show_end_screen(summary_text)
        else:
            self.canvas.show_stats_screen(summary_text)

        self.canvas.Refresh(False)

    def _on_stats_screen_esc(self) -> None:
        """ESC pressed while stats or end screen is visible."""
        if not getattr(self, '_level_complete', False):
            return

        if getattr(self, '_current_level_id', '') == 'level2':
            # Level 2 complete: show "THE END" screen
            self.canvas.hide_stats_screen()
            self.canvas._show_the_end = True
            self.canvas.Refresh(False)
            return

        # Level 1 complete: hide the stats overlay and show the level select modal.
        self.canvas.hide_stats_screen()
        self._level_complete = False
        self._open_level_select_modal(startup=False)
        # Force immediate refresh to show modal
        self.canvas.Refresh(False)

    def _on_close(self, evt: wx.CloseEvent) -> None:
        try:
            self.canvas.hide_mouse_capture()
        except Exception:
            pass
        try:
            self._audio.shutdown()
        except Exception:
            pass
        # Stop ghost sound timer to prevent crashes after window destruction
        self._ghost_sound_timer_active = False
        evt.Skip()


def run() -> int:
    app = wx.App(False)
    win = WxGameWindow()
    win.Show(True)
    return int(app.MainLoop() or 0)
