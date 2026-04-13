import json
import math
import os
import time
from typing import Dict, List, Optional, Set, Tuple

import wx
import wx.adv
from wx import glcanvas

import winsound

from OpenGL.GL import (
    GL_BLEND, GL_DEPTH_TEST, GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA,
    glBlendFunc, glDisable, glEnable, glLineWidth,
)

from .silhouette_minigame import SilhouetteMatchDialog
from .assembly3d_minigame import Assembly3DMinigame
from .renderer_opengl import OpenGLRenderer

from core.game_core import GameCore
from core.performance_monitor import PerformanceMonitor

FPS_CAMERA_SENSITIVITY = 0.002


class _SimpleAudio:

    def __init__(self, asset_dir: str):
        self._asset_dir = str(asset_dir or '')
        self._footsteps_requested = False
        self._footsteps_playing = False
        self._sfx_until = 0.0

        def _path(name): return os.path.join(self._asset_dir, name)

        self._footsteps_path = _path('running-on-concrete-268478.wav')
        self._coin_path = _path('drop-coin-384921.wav')
        self._gate_path = _path('closing-metal-door-44280.wav')
        self._ghost_path = _path('ghost-horror-sound-382709.wav')

        def _snd(p): return wx.adv.Sound(p) if os.path.exists(p) else None
        self._snd_footsteps = _snd(self._footsteps_path)
        self._snd_coin = _snd(self._coin_path)
        self._snd_gate = _snd(self._gate_path)
        self._snd_ghost = _snd(self._ghost_path)

    def shutdown(self) -> None:
        self.set_footsteps(False)

    def _start_footsteps_loop(self) -> None:
        if self._snd_footsteps is not None:
            try:
                self._snd_footsteps.Play(
                    wx.adv.SOUND_ASYNC | wx.adv.SOUND_LOOP)
                self._footsteps_playing = True
                return
            except Exception:
                pass
        try:
            if os.path.exists(self._footsteps_path):
                winsound.PlaySound(self._footsteps_path,
                                   winsound.SND_ASYNC | winsound.SND_LOOP)
                self._footsteps_playing = True
        except Exception:
            self._footsteps_playing = False

    def _stop_footsteps(self) -> None:
        self._footsteps_playing = False
        if self._snd_footsteps is not None:
            try:
                self._snd_footsteps.Stop()
                return
            except Exception:
                pass
        try:
            winsound.PlaySound(None, winsound.SND_ASYNC)
        except Exception:
            pass

    def _resume_footsteps_if_needed(self) -> None:
        if not self._footsteps_requested:
            return
        if time.perf_counter() < self._sfx_until:
            return
        if not self._footsteps_playing:
            self._start_footsteps_loop()

    def _play_priority_sfx(self, snd: Optional[wx.adv.Sound], path: str, cooldown_s: float) -> None:
        self._stop_footsteps()
        self._sfx_until = max(
            self._sfx_until, time.perf_counter() + cooldown_s)
        played = False
        if snd is not None:
            try:
                snd.Play(wx.adv.SOUND_ASYNC)
                played = True
            except Exception:
                pass
        if not played and os.path.exists(path):
            try:
                winsound.PlaySound(path, winsound.SND_ASYNC)
            except Exception:
                pass
        try:
            wx.CallLater(int(cooldown_s * 1000),
                         self._resume_footsteps_if_needed)
        except Exception:
            pass

    def set_footsteps(self, playing: bool) -> None:
        playing = bool(playing)
        self._footsteps_requested = playing
        if not playing:
            self._stop_footsteps()
            return
        if time.perf_counter() < self._sfx_until:
            return
        if not self._footsteps_playing:
            self._start_footsteps_loop()

    def play_coin(
        self) -> None: self._play_priority_sfx(self._snd_coin,  self._coin_path,  0.35)

    def play_gate(
        self) -> None: self._play_priority_sfx(self._snd_gate,  self._gate_path,  3.0)
    def play_ghost(
        self) -> None: self._play_priority_sfx(self._snd_ghost, self._ghost_path, 3.5)


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
            glcanvas.WX_GL_DEPTH_SIZE, 24,
            0,
        ]
        try:
            a = glcanvas.GLContextAttrs()
            a = a.PlatformDefaults().CoreProfile().OGLVersion(3, 3).EndList()
            ctx_attribs = a
        except Exception:
            ctx_attribs = None

        super().__init__(parent, attribList=attribs)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

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

        self._hud_prog_col:  int = 0
        self._hud_prog_tex:  int = 0
        self._hud_vao_col:   int = 0
        self._hud_vbo_col:   int = 0
        self._hud_vao_tex:   int = 0
        self._hud_vbo_tex:   int = 0
        self._hud_u_mvp_col: int = -1
        self._hud_u_mvp_tex: int = -1
        self._hud_u_tex:     int = -1

        self._mouse_captured = False
        self._mouse_center: Optional[Tuple[int, int]] = None
        self._mouse_skip_next_delta = False

        self._assets_dir = 'assets'
        self._cam_icon_tex: Optional[int] = None

        self._minimap_until = 0.0
        self._minimap_cooldown_until = 0.0
        self._cam_icon_rect = wx.Rect(0, 0, 0, 0)

        self._minimap_static_tex:       Optional[int] = None
        self._minimap_static_layout_id: int = 0
        self._minimap_static_size:      Tuple[int, int, int] = (0, 0, 0)

        self._modal_visible = False
        self._modal_kind:   str = ''
        self._modal_title:  str = ''
        self._modal_body:   str = ''
        self._modal_btn_rects: Dict[str, wx.Rect] = {}
        self._modal_allow_close = True
        self._modal_return_to_pause = False
        self._modal_unlocked: Set[str] = set()

        self._lore_queue:        List[str] = []
        self._lore_current:      str = ''
        self._lore_current_start: float = 0.0
        self._lore_current_end:   float = 0.0

        self._time_bonus_text:   str = ''
        self._time_bonus_until:  float = 0.0

        self._show_the_end = False
        self._pause_btn_rects: Dict[str, wx.Rect] = {}
        self.performance_monitor: Optional[PerformanceMonitor] = None

        self._stats_visible = False
        self._stats_text = ''
        self._end_screen_visible = False

        self._flash_until: float = 0.0
        self._flash_color: Tuple[float, float, float, float] = (
            20/255, 20/255, 25/255, 180/255)

        self._hud_font = wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL,
                                 wx.FONTWEIGHT_NORMAL, faceName='Arial')
        self._hud_font_bold = wx.Font(11, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL,
                                      wx.FONTWEIGHT_BOLD,   faceName='Arial')

        self.Bind(wx.EVT_PAINT,              self._on_paint)
        self.Bind(wx.EVT_SIZE,               self._on_size)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self.Bind(wx.EVT_LEFT_DOWN,          self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP,            self._on_left_up)
        self.Bind(wx.EVT_MOTION,             self._on_mouse_move)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)
        self.SetFocus()

    def _ensure_gl(self) -> None:
        if self._gl_initialized:
            return
        self._gl_initialized = True
        self.SetCurrent(self._gl_context)
        self.renderer.initialize()
        self._init_hud_gl()
        try:
            self._cam_icon_tex = self.renderer._load_texture(
                os.path.join(self._assets_dir, 'cam.jpg'))
        except Exception:
            pass
        w, h = self.GetClientSize()
        self.renderer.resize(int(w), int(h))

    def _init_hud_gl(self) -> None:
        from OpenGL.GL import (
            glCreateShader, glShaderSource, glCompileShader, glGetShaderiv,
            glGetShaderInfoLog, GL_VERTEX_SHADER, GL_FRAGMENT_SHADER,
            glCreateProgram, glAttachShader, glLinkProgram, glGetProgramiv,
            GL_COMPILE_STATUS, GL_LINK_STATUS,
            glGenVertexArrays, glGenBuffers, glBindVertexArray, glBindBuffer,
            GL_ARRAY_BUFFER, glEnableVertexAttribArray, glVertexAttribPointer,
            GL_FLOAT, GL_FALSE, glGetUniformLocation,
        )
        import ctypes

        vert_col = b"""
#version 330 core
layout(location=0) in vec2 aPos;
layout(location=1) in vec4 aColor;
out vec4 vColor;
uniform mat4 uMVP;
void main(){ vColor=aColor; gl_Position=uMVP*vec4(aPos,0.0,1.0); }
"""
        frag_col = b"""
#version 330 core
in vec4 vColor; out vec4 FragColor;
void main(){ FragColor=vColor; }
"""
        vert_tex = b"""
#version 330 core
layout(location=0) in vec2 aPos;
layout(location=1) in vec2 aUV;
out vec2 vUV;
uniform mat4 uMVP;
void main(){ vUV=aUV; gl_Position=uMVP*vec4(aPos,0.0,1.0); }
"""
        frag_tex = b"""
#version 330 core
in vec2 vUV; out vec4 FragColor;
uniform sampler2D uTex;
void main(){ FragColor=texture(uTex,vUV); }
"""

        def _compile(src, kind):
            sh = glCreateShader(kind)
            glShaderSource(sh, src)
            glCompileShader(sh)
            if not glGetShaderiv(sh, GL_COMPILE_STATUS):
                raise RuntimeError(glGetShaderInfoLog(sh).decode())
            return int(sh)

        def _link(vs, fs):
            prog = glCreateProgram()
            glAttachShader(prog, vs)
            glAttachShader(prog, fs)
            glLinkProgram(prog)
            if not glGetProgramiv(prog, GL_LINK_STATUS):
                raise RuntimeError("Shader link failed")
            return int(prog)

        self._hud_prog_col = _link(
            _compile(vert_col, GL_VERTEX_SHADER), _compile(frag_col, GL_FRAGMENT_SHADER))
        self._hud_prog_tex = _link(
            _compile(vert_tex, GL_VERTEX_SHADER), _compile(frag_tex, GL_FRAGMENT_SHADER))

        self._hud_u_mvp_col = glGetUniformLocation(self._hud_prog_col, 'uMVP')
        self._hud_u_mvp_tex = glGetUniformLocation(self._hud_prog_tex, 'uMVP')
        self._hud_u_tex = glGetUniformLocation(self._hud_prog_tex, 'uTex')

        stride_col = 6 * 4
        self._hud_vao_col = int(glGenVertexArrays(1))
        self._hud_vbo_col = int(glGenBuffers(1))
        glBindVertexArray(self._hud_vao_col)
        glBindBuffer(GL_ARRAY_BUFFER, self._hud_vbo_col)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride_col,
                              ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride_col,
                              ctypes.c_void_p(8))
        glBindVertexArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

        stride_tex = 4 * 4
        self._hud_vao_tex = int(glGenVertexArrays(1))
        self._hud_vbo_tex = int(glGenBuffers(1))
        glBindVertexArray(self._hud_vao_tex)
        glBindBuffer(GL_ARRAY_BUFFER, self._hud_vbo_tex)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride_tex,
                              ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride_tex,
                              ctypes.c_void_p(8))
        glBindVertexArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def show_stats_screen(self, text: str) -> None:
        self._stats_text = str(text or '')
        self._stats_visible = True
        self._end_screen_visible = False
        self.hide_mouse_capture()

    def show_end_screen(self, text: str) -> None:
        self._stats_text = str(text or '')
        self._stats_visible = True
        self._end_screen_visible = True
        self.hide_mouse_capture()

    def hide_stats_screen(self) -> None:
        self._stats_visible = False
        self._end_screen_visible = False
        self._stats_text = ''

    def trigger_flash(self, duration_ms: float = 300, color: Optional[Tuple[float, float, float, float]] = None) -> None:
        self._flash_until = time.perf_counter() + (duration_ms / 1000.0)
        if color:
            self._flash_color = color
        self.Refresh(False)

    def _on_size(self, _evt: wx.SizeEvent) -> None:
        self.Refresh(False)

    def _on_paint(self, _evt: wx.PaintEvent) -> None:
        _ = wx.PaintDC(self)
        self._ensure_gl()
        self.SetCurrent(self._gl_context)
        w, h = self.GetClientSize()
        self.renderer.resize(int(w), int(h))
        self.renderer.render()
        self._draw_hud_gl(int(w), int(h))
        glEnable(GL_DEPTH_TEST)
        self.SwapBuffers()

        if self.performance_monitor:
            paused = bool(getattr(self.core, 'paused', False))
            stats_visible = bool(getattr(self, '_stats_visible', False)) or bool(
                getattr(self, '_show_the_end', False))
            if not paused and not stats_visible:
                self.performance_monitor.record_frame()
            else:
                self.performance_monitor.record_frame(is_pause_frame=True)
            if not hasattr(self, '_startup_recorded'):
                self._startup_recorded = True
                ms = (time.perf_counter() -
                      self.performance_monitor._startup_begin) * 1000
                self.performance_monitor.record_startup_time(ms)

    def _hud_mvp(self, w: int, h: int) -> List[float]:
        sx = 2.0 / max(1, w)
        sy = -2.0 / max(1, h)
        return [sx, 0, 0, 0,  0, sy, 0, 0,  0, 0, 1, 0,  -1.0, 1.0, 0, 1]

    def _hud_draw_col(self, w: int, h: int, verts: List[float]) -> None:
        if not verts:
            return
        import ctypes
        from OpenGL.GL import (
            glUseProgram, glUniformMatrix4fv, GL_FALSE, glBindVertexArray,
            glBindBuffer, GL_ARRAY_BUFFER, GL_DYNAMIC_DRAW, glBufferData,
            glDrawArrays, GL_TRIANGLES,
        )
        mvp = self._hud_mvp(w, h)
        glUseProgram(self._hud_prog_col)
        if self._hud_u_mvp_col >= 0:
            glUniformMatrix4fv(self._hud_u_mvp_col, 1, GL_FALSE,
                               (ctypes.c_float * 16)(*mvp))
        glBindVertexArray(self._hud_vao_col)
        glBindBuffer(GL_ARRAY_BUFFER, self._hud_vbo_col)
        data = (ctypes.c_float * len(verts))(*verts)
        glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(
            data), data, GL_DYNAMIC_DRAW)
        glDrawArrays(GL_TRIANGLES, 0, len(verts) // 6)
        glBindVertexArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glUseProgram(0)

    def _hud_draw_tex(self, w: int, h: int, tex_id: int, verts: List[float]) -> None:
        if not tex_id or not verts:
            return
        import ctypes
        from OpenGL.GL import (
            glUseProgram, glUniformMatrix4fv, glUniform1i, GL_FALSE,
            glActiveTexture, GL_TEXTURE0, glBindTexture, GL_TEXTURE_2D,
            glBindVertexArray, glBindBuffer, GL_ARRAY_BUFFER, GL_DYNAMIC_DRAW,
            glBufferData, glDrawArrays, GL_TRIANGLES,
        )
        mvp = self._hud_mvp(w, h)
        glUseProgram(self._hud_prog_tex)
        if self._hud_u_mvp_tex >= 0:
            glUniformMatrix4fv(self._hud_u_mvp_tex, 1, GL_FALSE,
                               (ctypes.c_float * 16)(*mvp))
        if self._hud_u_tex >= 0:
            glUniform1i(self._hud_u_tex, 0)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, int(tex_id))
        glBindVertexArray(self._hud_vao_tex)
        glBindBuffer(GL_ARRAY_BUFFER, self._hud_vbo_tex)
        data = (ctypes.c_float * len(verts))(*verts)
        glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(
            data), data, GL_DYNAMIC_DRAW)
        glDrawArrays(GL_TRIANGLES, 0, len(verts) // 4)
        glBindVertexArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindTexture(GL_TEXTURE_2D, 0)
        glUseProgram(0)

    def _gl_rect(self, x, y, ww, hh, r, g, b, a) -> None:
        x0, y0, x1, y1 = float(x), float(y), float(x + ww), float(y + hh)
        v = [x0, y0, r, g, b, a,  x1, y0, r, g, b, a,  x1, y1, r, g, b, a,
             x0, y0, r, g, b, a,  x1, y1, r, g, b, a,  x0, y1, r, g, b, a]
        cw, ch = self.GetClientSize()
        self._hud_draw_col(int(cw), int(ch), v)

    def _gl_textured_rect(self, x, y, ww, hh, tex_id: int) -> None:
        x0, y0, x1, y1 = float(x), float(y), float(x + ww), float(y + hh)
        v = [x0, y0, 0.0, 1.0,  x1, y0, 1.0, 1.0,  x1, y1, 1.0, 0.0,
             x0, y0, 0.0, 1.0,  x1, y1, 1.0, 0.0,  x0, y1, 0.0, 0.0]
        cw, ch = self.GetClientSize()
        self._hud_draw_tex(int(cw), int(ch), int(tex_id), v)

    def _gl_line(self, x1, y1, x2, y2, *, color: Tuple[int, int, int, int]) -> None:
        rr, gg, bb, aa = (color[0]/255, color[1]/255,
                          color[2]/255, color[3]/255)
        dx, dy = float(x2) - float(x1), float(y2) - float(y1)
        inv = 1.0 / (math.sqrt(dx * dx + dy * dy) or 1e-9)
        # 1px width (0.5 each side) to match PySide6/Kivy
        nx, ny = -dy * inv * 0.5, dx * inv * 0.5
        ax, ay = float(x1) + nx, float(y1) + ny
        bx, by = float(x1) - nx, float(y1) - ny
        cx2, cy2 = float(x2) - nx, float(y2) - ny
        dx2, dy2 = float(x2) + nx, float(y2) + ny
        v = [ax, ay, rr, gg, bb, aa,  bx, by, rr, gg, bb, aa,
             cx2, cy2, rr, gg, bb, aa,
             ax, ay, rr, gg, bb, aa,  cx2, cy2, rr, gg, bb, aa,
             dx2, dy2, rr, gg, bb, aa]
        cw, ch = self.GetClientSize()
        self._hud_draw_col(int(cw), int(ch), v)

    def _gl_outline_rect(self, x, y, ww, hh, *, color: Tuple[int, int, int, int]) -> None:
        self._gl_line(x,       y,       x + ww, y,       color=color)
        self._gl_line(x + ww,  y,       x + ww, y + hh,  color=color)
        self._gl_line(x + ww,  y + hh,  x,      y + hh,  color=color)
        self._gl_line(x,       y + hh,  x,      y,       color=color)

    def _gl_text(self, x, y, txt, scale=1.0, *, font_size=28, bold=True,
                 color: Tuple[int, int, int, int] = (240, 240, 240, 255)) -> None:
        tid, tw, th = self.renderer.get_text_texture(
            str(txt), font_family='Arial', font_size=int(font_size),
            bold=bool(bold), color=tuple(int(c) for c in color), pad=10)
        if not tid:
            return
        self._gl_textured_rect(float(x), float(y),
                               float(tw) * float(scale),
                               float(th) * float(scale), tid)

    def _gl_text_center(self, x, y, ww, hh, txt, scale=1.0, *,
                        font_size=28, bold=True,
                        color: Tuple[int, int, int, int] = (240, 240, 240, 255)) -> None:
        _, tw, th = self.renderer.get_text_texture(
            str(txt), font_family='Arial', font_size=int(font_size),
            bold=bool(bold), color=tuple(int(c) for c in color), pad=8)
        self._gl_text(float(x + (ww - tw * scale) * 0.5),
                      float(y + (hh - th * scale) * 0.5),
                      txt, scale, font_size=font_size, bold=bold, color=color)

    def _wrap_text_lines(self, text: str, *, max_width_px: int,
                         font_size: int, bold: bool) -> List[str]:
        out: List[str] = []
        for para in str(text or '').split('\n'):
            p = para.strip()
            if not p:
                out.append('')
                continue
            words = p.split(' ')
            line = ''
            for word in words:
                trial = (line + ' ' + word).strip() if line else word
                _, tw, _ = self.renderer.get_text_texture(
                    trial, font_family='Arial', font_size=font_size,
                    bold=bold, color=(220, 220, 220, 255), pad=8)
                if tw <= max_width_px or not line:
                    line = trial
                else:
                    out.append(line)
                    line = word
            if line:
                out.append(line)
        return out

    def _draw_hud_gl(self, w: int, h: int) -> None:
        if w <= 1 or h <= 1:
            return

        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        if self._stats_visible:
            if self._end_screen_visible:
                self._draw_end_screen_gl(w, h)
            else:
                self._draw_stats_screen_gl(w, h)
            if self._modal_visible:
                self._draw_modal_gl(w, h)
            self._draw_lore_fade_gl(w, h)
            return

        now = time.perf_counter()
        if now < self._flash_until:
            remaining = self._flash_until - now
            total_flash = 0.3  # 300ms default
            fade = max(0.0, min(1.0, remaining / total_flash))
            r, g, b, a = self._flash_color
            alpha = a * fade
            self._gl_rect(0, 0, float(w), float(h), r, g, b, alpha)

        pad = 10
        box_w = 320
        box_h = 56
        x = (w - box_w) // 2
        y = pad
        self._gl_rect(float(x), float(y), float(
            box_w), float(box_h), 0, 0, 0, 0.62)
        self._gl_outline_rect(float(x), float(y), float(box_w), float(box_h),
                              color=(240, 240, 240, 255))
        t = int(getattr(self.core, 'elapsed_s', 0.0) or 0.0)
        self._gl_text(float(x + 12), float(y),
                      f'Time: {t // 60:02d}:{t % 60:02d}',
                      font_size=11, bold=True, color=HUD_COL_WHITE)

        now = time.perf_counter()
        if self._time_bonus_text and now < self._time_bonus_until:
            self._gl_text(float(x + 210), float(y + 8),
                          self._time_bonus_text,
                          font_size=22, bold=True, color=(255, 220, 60, 255))
        elif self._time_bonus_text and now >= self._time_bonus_until:
            self._time_bonus_text = ''

        self._gl_text(float(x + 12), float(y + 22),
                      f'Coins: {getattr(self.core, "coins_collected", 0)}'
                      f'/{getattr(self.core, "coins_required", 0)}'
                      f'   Keys: {getattr(self.core, "keys_collected", 0)}'
                      f'/{getattr(self.core, "keys_required", 0)}',
                      font_size=11, bold=False, color=HUD_COL_WHITE)

        icon_size = 54
        ix = w - icon_size - 16
        iy = h - icon_size - 16
        self._cam_icon_rect = wx.Rect(ix, iy, icon_size, icon_size)
        self._gl_rect(float(ix - 6), float(iy - 6),
                      float(icon_size + 12), float(icon_size + 12), 0, 0, 0, 0.50)
        self._gl_outline_rect(float(ix - 6), float(iy - 6),
                              float(icon_size + 12), float(icon_size + 12),
                              color=(220, 220, 220, 255))
        if self._cam_icon_tex:
            self._gl_textured_rect(float(ix), float(iy),
                                   float(icon_size), float(icon_size),
                                   self._cam_icon_tex)

        now = time.perf_counter()
        if now < self._minimap_cooldown_until:
            remaining = max(0.0, self._minimap_cooldown_until - now)
            self._gl_rect(float(ix), float(iy),
                          float(icon_size), float(icon_size), 0, 0, 0, 0.62)
            self._gl_text_center(float(ix), float(iy), float(icon_size), float(icon_size),
                                 f'{int(math.ceil(remaining))}s',
                                 font_size=HUD_FS_SMALL, bold=False, color=(255, 210, 90, 255))

        if now < self._minimap_until:
            self._draw_minimap_overlay_gl(w, h)

        popup_t = float(getattr(self.core, '_sector_popup_timer', 0.0) or 0.0)
        popup_id = str(getattr(self.core, '_sector_popup_id', '') or '')
        if popup_t > 0.0 and popup_id:
            fade_in = 0.25
            fade_out = 0.5
            total = 2.0
            if popup_t > (total - fade_in):
                alpha = max(
                    0.0, min(1.0, (total - popup_t) / max(0.001, fade_in)))
            elif popup_t < fade_out:
                alpha = max(0.0, min(1.0, popup_t / max(0.001, fade_out)))
            else:
                alpha = 1.0
            txt = f'SECTOR {popup_id}'
            _, tw, th = self.renderer.get_text_texture(
                txt, font_family='Arial', font_size=11,
                bold=False, color=(255, 220, 110, 255), pad=2)
            bx = (w - tw) * 0.5
            by = float(h - 25)
            self._gl_rect(float(bx - 10), float(by - th), float(tw + 20), float(th + 5),
                          0, 0, 0, (150 / 255) * alpha)
            self._gl_text_center(bx, by - th, float(tw), float(th + 0.3), txt,
                                 font_size=11, bold=True,
                                 color=(255, 220, 110, int(255 * alpha)))

        if (not self._modal_visible) and bool(getattr(self.core, 'paused', False)):
            self._draw_pause_panel_gl(w, h)

        prog = float(getattr(self.core, 'screen_close_progress', 0.0) or 0.0)
        if prog > 0.0:
            self._draw_closing_animation_gl(w, h, prog)

        self._draw_lore_fade_gl(w, h)

        if self._show_the_end:
            self._draw_the_end_gl(w, h)

        if self._modal_visible:
            self._draw_modal_gl(w, h)

    def _ensure_minimap_static_texture(self, w: int, h: int) -> Tuple[int, int, int, int, int]:
        layout = getattr(self.core, 'layout', None) or []
        maze_rows = len(layout)
        maze_cols = len(layout[0]) if maze_rows else 0
        if not maze_rows or not maze_cols:
            return (0, 0, 0, 0, 0)

        cell_px = max(1, min(int(w * 0.85 / maze_cols),
                             int((h - 40) / maze_rows)))
        mw = maze_cols * cell_px
        mh = maze_rows * cell_px
        x0 = (w - mw) // 2
        y0 = 20 + ((h - 40) - mh) // 2

        current_layout_id = id(layout)
        current_size = (mw, mh, cell_px)
        needs_rebuild = (
            not self._minimap_static_tex
            or self._minimap_static_layout_id != current_layout_id
            or self._minimap_static_size != current_size
        )

        if not needs_rebuild:
            return (int(self._minimap_static_tex or 0),
                    int(x0), int(y0), int(mw), int(mh))

        bmp = wx.Bitmap(mw, mh, 32)
        mdc = wx.MemoryDC(bmp)
        gc = wx.GraphicsContext.Create(mdc)

        gc.SetBrush(wx.Brush(wx.Colour(10, 10, 12, 210)))
        gc.SetPen(wx.Pen(wx.Colour(230, 230, 230, 255), 1))
        gc.DrawRectangle(0, 0, mw, mh)

        walls = getattr(self.core, 'walls',  set())
        floors = getattr(self.core, 'floors', set())
        gc.SetPen(wx.NullPen)

        gc.SetBrush(wx.Brush(wx.Colour(45, 45, 55, 255)))
        for r in range(maze_rows):
            for c in range(maze_cols):
                if (r, c) in walls:
                    gc.DrawRectangle(c * cell_px, r * cell_px,
                                     cell_px + 1, cell_px + 1)

        gc.SetBrush(wx.Brush(wx.Colour(125, 125, 135, 255)))
        for r in range(maze_rows):
            for c in range(maze_cols):
                if (r, c) in floors and (r, c) not in walls:
                    gc.DrawRectangle(c * cell_px, r * cell_px,
                                     cell_px + 1, cell_px + 1)

        gc.SetBrush(wx.Brush(wx.Colour(15, 15, 18, 255)))
        for r in range(maze_rows):
            for c in range(maze_cols):
                if (r, c) not in walls and (r, c) not in floors:
                    gc.DrawRectangle(c * cell_px, r * cell_px,
                                     cell_px + 1, cell_px + 1)

        del gc
        mdc.SelectObject(wx.NullBitmap)

        if self._minimap_static_tex:
            try:
                from OpenGL.GL import glDeleteTextures
                glDeleteTextures(1, [int(self._minimap_static_tex)])
            except Exception:
                pass
            self._minimap_static_tex = None

        self._minimap_static_tex = int(self._bitmap_to_texture(bmp))
        self._minimap_static_layout_id = current_layout_id
        self._minimap_static_size = current_size

        return (int(self._minimap_static_tex or 0),
                int(x0), int(y0), int(mw), int(mh))

    def _draw_minimap_overlay_gl(self, w: int, h: int) -> None:
        tex_id, x0, y0, mw, mh = self._ensure_minimap_static_texture(w, h)
        if not tex_id or mw <= 0 or mh <= 0:
            return

        self._gl_textured_rect(float(x0), float(
            y0), float(mw), float(mh), int(tex_id))

        layout = getattr(self.core, 'layout', None) or []
        maze_rows = len(layout)
        maze_cols = len(layout[0]) if maze_rows else 0
        if not maze_rows or not maze_cols:
            return
        cell_px = int(self._minimap_static_size[2] or 1)

        def to_screen(wr: float, wc: float) -> Tuple[float, float]:
            return float(x0 + wc * cell_px), float(y0 + wr * cell_px)

        def _circle(cx: float, cy: float, radius: float,
                    col: Tuple[float, float, float, float]) -> None:
            steps = 18
            verts: List[float] = []
            for i in range(steps):
                a0 = (i / steps) * 2.0 * math.pi
                a1 = ((i + 1) / steps) * 2.0 * math.pi
                verts.extend([
                    cx, cy, col[0], col[1], col[2], col[3],
                    cx + math.cos(a0) * radius, cy + math.sin(a0) * radius,
                    col[0], col[1], col[2], col[3],
                    cx + math.cos(a1) * radius, cy + math.sin(a1) * radius,
                    col[0], col[1], col[2], col[3],
                ])
            self._hud_draw_col(w, h, verts)

        coin_r = float(max(6, int(cell_px * 0.35))) * 0.5
        for coin in getattr(self.core, 'coins', {}).values():
            if getattr(coin, 'taken', False):
                continue
            rr, cc = coin.cell
            sx, sy = to_screen(rr + 0.5, cc + 0.5)
            _circle(sx, sy, coin_r, (1.0, 215 / 255, 0.0, 1.0))

        ghost_colors = {
            1: (1, 80 / 255, 60 / 255),
            2: (80 / 255, 1, 140 / 255),
            3: (110 / 255, 170 / 255, 1),
            4: (1, 220 / 255, 80 / 255),
            5: (1, 90 / 255, 1),
        }
        ghost_r = max(4, int(cell_px * 0.6)) * 0.5
        for ghost in getattr(self.core, 'ghosts', {}).values():
            gr = float(getattr(ghost, 'z', 0.0) or 0.0)
            gcx = float(getattr(ghost, 'x', 0.0) or 0.0)
            gid = int(getattr(ghost, 'id', 0) or 0)
            s = float(getattr(ghost, 'size_scale', 1.0) or 1.0)
            gsz = ghost_r * s
            col = ghost_colors.get(gid, (1, 120 / 255, 30 / 255))
            sx, sy = to_screen(gr + 0.5, gcx + 0.5)
            _circle(sx, sy, gsz, (col[0], col[1], col[2], 0.95))

            eye_size = max(2.0, gsz * 0.15)
            eye_ox = gsz * 0.25
            eye_oy = gsz * 0.10
            for ex in (sx - eye_ox, sx + eye_ox):
                ey = sy - eye_oy
                _circle(float(ex), float(ey), float(
                    eye_size), (1.0, 1.0, 1.0, 1.0))
                pupil = max(1.0, eye_size * 0.5)
                _circle(float(ex), float(ey), float(
                    pupil), (0.0, 0.0, 0.0, 1.0))

        px_w = float(getattr(self.core.player, 'x', 0.0) or 0.0)
        pz_w = float(getattr(self.core.player, 'z', 0.0) or 0.0)
        yaw = float(getattr(self.core.player, 'yaw', 0.0) or 0.0)
        cx, cy = to_screen(pz_w + 0.5, px_w + 0.5)
        half = max(6, int(cell_px * 0.35))
        col = (50 / 255, 1.0, 50 / 255, 1.0)
        verts = [
            cx, cy - half, *col,
            cx + half, cy, *col,
            cx, cy + half, *col,
            cx, cy - half, *col,
            cx, cy + half, *col,
            cx - half, cy, *col,
        ]
        self._hud_draw_col(w, h, [float(v) for v in verts])
        _circle(cx, cy, half * 0.4, (1, 1, 1, 1))
        ll = max(6, int(cell_px * 0.75))
        self._gl_line(float(cx), float(cy),
                      float(cx + math.sin(yaw) * ll),
                      float(cy + math.cos(yaw) * ll),
                      color=(255, 220, 110, 255))

        now = time.perf_counter()
        if now < self._minimap_until:
            remaining = max(0.0, self._minimap_until - now)
            ctext = f'MAP: {int(remaining + 0.5)}s'
            try:
                _, tw, th = self.renderer.get_text_texture(
                    ctext, font_family='Arial', font_size=HUD_FS_MED,
                    bold=True, color=(255, 255, 255, 255), pad=2)
            except Exception:
                tw, th = 90, 18
            cx2 = float(x0 + mw - tw - 10)
            cy2 = float(y0 + th + 5)
            self._gl_rect(cx2 - 3, cy2 - th + 3, float(tw + 6), float(th + 3),
                          0, 0, 0, 180 / 255)
            self._gl_text(cx2, cy2 - th + 2, ctext,
                          font_size=HUD_FS_MED, bold=True, color=(255, 255, 255, 255))

    def _bitmap_to_texture(self, bmp: wx.Bitmap) -> int:
        import ctypes
        from OpenGL.GL import (
            glGenTextures, glBindTexture, GL_TEXTURE_2D, glTexParameteri,
            GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER, GL_LINEAR,
            glTexImage2D, GL_RGBA, GL_UNSIGNED_BYTE, GL_RGBA8,
        )
        img = bmp.ConvertToImage()
        try:
            img = img.Mirror(False)
        except Exception:
            pass
        ww, hh = img.GetWidth(), img.GetHeight()
        data = img.GetData()
        has_alpha = img.HasAlpha()
        alpha = img.GetAlpha() if has_alpha else None

        rgba = bytearray(ww * hh * 4)
        for i in range(ww * hh):
            rgba[i * 4] = data[i * 3]
            rgba[i * 4 + 1] = data[i * 3 + 1]
            rgba[i * 4 + 2] = data[i * 3 + 2]
            rgba[i * 4 + 3] = alpha[i] if has_alpha else 255

        tex_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, int(ww), int(hh), 0,
                     GL_RGBA, GL_UNSIGNED_BYTE,
                     (ctypes.c_ubyte * len(rgba))(*rgba))
        glBindTexture(GL_TEXTURE_2D, 0)
        return int(tex_id)

    def _draw_pause_panel_gl(self, w: int, h: int) -> None:
        self._gl_rect(0, 0, float(w), float(h), 0, 0, 0, 160 / 255)

        pw = 560
        ph = 610
        x0 = (w - pw) // 2
        y0 = (h - ph) // 2

        self._gl_rect(float(x0), float(y0), float(pw), float(ph),
                      18 / 255, 18 / 255, 22 / 255, 235 / 255)
        self._gl_outline_rect(float(x0), float(y0), float(pw), float(ph),
                              color=(220, 220, 220, 255))

        self._gl_text_center(float(x0), float(y0 + 10), float(pw), 54,
                             'PAUSED', font_size=HUD_FS_PAUSE_TITLE,
                             bold=True, color=HUD_COL_YELLOW)

        pm = self.performance_monitor
        fps_str = f'FPS: {int(pm.stable_display_fps())}' if pm else 'FPS: —'
        ram_str = f'RAM usage: {pm.current_ram_mb():.1f} MB' if pm else 'RAM usage: — MB'
        sx = x0 + 36
        sy = y0 + 96
        lh = 24
        self._gl_text(float(sx), float(sy),       fps_str,
                      font_size=HUD_FS_SMALL, bold=False, color=(235, 235, 235, 255))
        self._gl_text(float(sx), float(sy + lh),  ram_str,
                      font_size=HUD_FS_SMALL, bold=False, color=(235, 235, 235, 255))

        btn_w = 280
        btn_h = 48
        gap = 16
        bx = x0 + (pw - btn_w) // 2
        top_y = y0 + 200
        buttons = [
            ('resume',    'Resume'),
            ('levels',    'Levels'),
            ('save',      'Save Game'),
            ('save_exit', 'Save + Exit'),
            ('restart',   'Restart'),
            ('exit',      'Exit (No Save)'),
        ]
        self._pause_btn_rects.clear()
        for i, (key, label) in enumerate(buttons):
            by = top_y + (btn_h + gap) * i
            self._pause_btn_rects[key] = wx.Rect(
                int(bx), int(by), int(btn_w), int(btn_h))
            self._gl_rect(float(bx), float(by), float(btn_w), float(btn_h),
                          32 / 255, 32 / 255, 40 / 255, 235 / 255)
            self._gl_outline_rect(float(bx), float(by), float(btn_w), float(btn_h),
                                  color=(220, 220, 220, 255))
            self._gl_text_center(float(bx), float(by), float(btn_w), float(btn_h),
                                 label, font_size=HUD_FS_MED, bold=False,
                                 color=(255, 255, 255, 255))

    def _draw_level_select_modal_gl(self, w: int, h: int) -> None:
        self._gl_rect(0, 0, float(w), float(h), 0, 0, 0, 1.0)

        self._gl_text_center(0, float(h * 0.10), float(w), 80,
                             self._modal_title or 'Select Level',
                             font_size=28, bold=True, color=HUD_COL_WHITE)
        if self._modal_body:
            for i, ln in enumerate(self._modal_body.split('\n')):
                self._gl_text_center(0, float(h * 0.10 + 56 + i * 20), float(w), 22,
                                     ln, font_size=13, bold=False,
                                     color=(200, 200, 200, 255))

        btn_w = min(620, int(w * 0.62))
        btn_h = 82
        gap = 22
        bx = (w - btn_w) // 2
        by1 = int(h * 0.34)
        by2 = by1 + btn_h + gap

        self._modal_btn_rects.clear()

        self._gl_rect(float(bx), float(by1), float(btn_w), float(btn_h),
                      22 / 255, 22 / 255, 26 / 255, 1.0)
        self._gl_outline_rect(float(bx), float(by1), float(btn_w), float(btn_h),
                              color=(240, 240, 240, 255))
        self._gl_text_center(float(bx), float(by1), float(btn_w), float(btn_h),
                             'Level 1', font_size=18, bold=True, color=HUD_COL_WHITE)
        self._modal_btn_rects['level1'] = wx.Rect(
            int(bx), int(by1), int(btn_w), int(btn_h))

        l2_unlocked = 'level2' in self._modal_unlocked
        l2_label = 'Level 2' if l2_unlocked else 'Level 2 (Locked)'
        l2_alpha = 1.0 if l2_unlocked else 190 / 255
        l2_col = HUD_COL_WHITE if l2_unlocked else (140, 140, 140, 255)
        self._gl_rect(float(bx), float(by2), float(btn_w), float(btn_h),
                      22 / 255, 22 / 255, 26 / 255, l2_alpha)
        self._gl_outline_rect(float(bx), float(by2), float(btn_w), float(btn_h),
                              color=l2_col)
        self._gl_text_center(float(bx), float(by2), float(btn_w), float(btn_h),
                             l2_label, font_size=18, bold=True, color=l2_col)
        self._modal_btn_rects['level2'] = wx.Rect(
            int(bx), int(by2), int(btn_w), int(btn_h))

        cs = 38
        cx2 = w - cs - 20
        cy2 = 18
        self._modal_btn_rects['close'] = wx.Rect(int(cx2), int(cy2), cs, cs)
        close_col = (220, 220, 220, 255) if self._modal_allow_close else (
            140, 140, 140, 255)
        self._gl_outline_rect(float(cx2), float(
            cy2), float(cs), float(cs), color=close_col)
        self._gl_line(float(cx2 + 8), float(cy2 + 8),
                      float(cx2 + cs - 8), float(cy2 + cs - 8), color=close_col)
        self._gl_line(float(cx2 + cs - 8), float(cy2 + 8),
                      float(cx2 + 8), float(cy2 + cs - 8), color=close_col)

    def _draw_tutorial_modal_gl(self, w: int, h: int) -> None:
        pw = min(840, int(w * 0.74))
        ph = min(440, int(h * 0.56))
        x0 = (w - pw) // 2
        y0 = (h - ph) // 2
        self._gl_rect(0, 0, float(w), float(h), 0, 0, 0, 160 / 255)
        self._gl_rect(float(x0), float(y0), float(pw), float(ph),
                      18 / 255, 18 / 255, 22 / 255, 245 / 255)
        self._gl_outline_rect(float(x0), float(y0), float(pw), float(ph),
                              color=(235, 235, 235, 255))
        if self._modal_title:
            self._gl_text(float(x0 + 24), float(y0 + 44), self._modal_title,
                          font_size=18, bold=True, color=(235, 235, 235, 255))
        self._gl_line(float(x0 + 24), float(y0 + 96),
                      float(x0 + pw - 24), float(y0 + 96),
                      color=(235, 235, 235, 100))
        lines = self._wrap_text_lines(self._modal_body, max_width_px=pw - 48,
                                      font_size=14, bold=False)
        for i, ln in enumerate(lines):
            if ln:
                self._gl_text(float(x0 + 24), float(y0 + 120 + i * 18), ln,
                              font_size=14, bold=False, color=(220, 220, 220, 255))
        cs = 32
        cx2 = x0 + pw - 24 - cs
        cy2 = y0 + 22
        self._modal_btn_rects['close'] = wx.Rect(int(cx2), int(cy2), cs, cs)
        pen = (220, 220, 220, 255) if self._modal_allow_close else (
            120, 120, 120, 255)
        self._gl_line(float(cx2 + 7), float(cy2 + 7),
                      float(cx2 + cs - 7), float(cy2 + cs - 7), color=pen)
        self._gl_line(float(cx2 + cs - 7), float(cy2 + 7),
                      float(cx2 + 7), float(cy2 + cs - 7), color=pen)
        self._gl_outline_rect(float(cx2), float(
            cy2), float(cs), float(cs), color=pen)

    def _draw_modal_gl(self, w: int, h: int) -> None:
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        self._modal_btn_rects.clear()

        if self._modal_kind == 'level_select':
            self._draw_level_select_modal_gl(w, h)
        elif self._modal_kind == 'tutorial':
            self._draw_tutorial_modal_gl(w, h)

    def _draw_stats_screen_gl(self, w: int, h: int) -> None:
        self._gl_rect(0, 0, float(w), float(h), 0, 0, 0, 1)
        text = str(self._stats_text or '')
        if not text:
            return
        lines = [ln.rstrip() for ln in text.split('\n')]
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        usable_h = h - 80
        lh = min(26, max(14, usable_h // max(1, len(lines))))
        start_y = max(36, (h - len(lines) * lh - 50) // 2)
        fs_body = max(10, min(14, lh - 4))
        fs_hdr = fs_body + 1
        for i, ln in enumerate(lines):
            is_sep = ln.startswith('─')
            is_hdr = (ln.isupper() and len(ln) > 2
                      and not ln.startswith('•') and not is_sep)
            col = ((100, 100, 100, 200) if is_sep
                   else (255, 220, 80, 255) if is_hdr
                   else (230, 230, 230, 255))
            fs = fs_hdr if is_hdr else fs_body
            self._gl_text_center(0, float(start_y + i * lh), float(w), float(lh),
                                 ln, font_size=fs, bold=is_hdr, color=col)
        self._gl_text_center(0, float(h - 46), float(w), 30,
                             'Press ESC to continue',
                             font_size=13, bold=False, color=(160, 160, 160, 255))

    def _draw_end_screen_gl(self, w: int, h: int) -> None:
        self._gl_rect(0, 0, float(w), float(h), 0, 0, 0, 1)
        text = str(self._stats_text or '')
        if text:
            lines = [ln.rstrip() for ln in text.split('\n')]
            while lines and not lines[0]:
                lines.pop(0)
            while lines and not lines[-1]:
                lines.pop()
            usable_h = h - 80
            lh = min(26, max(14, usable_h // max(1, len(lines))))
            start_y = max(36, (h - len(lines) * lh - 50) // 2)
            fs_body = max(10, min(14, lh - 4))
            fs_hdr = fs_body + 1
            for i, ln in enumerate(lines):
                is_sep = ln.startswith('─')
                is_hdr = (ln.isupper() and len(ln) > 2
                          and not ln.startswith('•') and not is_sep)
                col = ((100, 100, 100, 200) if is_sep
                       else (255, 210, 60, 255) if is_hdr
                       else (210, 210, 210, 255))
                fs = fs_hdr if is_hdr else fs_body
                self._gl_text_center(0, float(start_y + i * lh), float(w), float(lh),
                                     ln, font_size=fs, bold=is_hdr, color=col)
        self._gl_text_center(0, float(h - 46), float(w), 30,
                             'Press ESC to continue',
                             font_size=14, bold=False, color=(150, 150, 150, 255))

    def _draw_the_end_gl(self, w: int, h: int) -> None:
        self._gl_rect(0, 0, float(w), float(h), 0, 0, 0, 1)
        self._gl_text_center(0, 0, float(w), float(h), 'THE END',
                             font_size=68, bold=True, color=(255, 210, 60, 255))
        self._gl_text_center(0, float(h - 46), float(w), 30,
                             'Press ESC to continue',
                             font_size=13, bold=False, color=(150, 150, 150, 255))

    def _draw_closing_animation_gl(self, w: int, h: int, progress: float) -> None:
        cx = float(w) * 0.5
        cy = float(h) * 0.5
        max_r = math.sqrt(cx * cx + cy * cy) + 4
        ease = progress * progress
        inner_r = max_r * (1.0 - ease)
        outer_r = max_r + 4
        steps = 64
        col = (0, 0, 0, 1)
        verts: List[float] = []
        for i in range(steps):
            a0 = (i / steps) * 2 * math.pi
            a1 = ((i + 1) / steps) * 2 * math.pi
            x0i = cx + math.cos(a0) * inner_r
            y0i = cy + math.sin(a0) * inner_r
            x1i = cx + math.cos(a1) * inner_r
            y1i = cy + math.sin(a1) * inner_r
            x0o = cx + math.cos(a0) * outer_r
            y0o = cy + math.sin(a0) * outer_r
            x1o = cx + math.cos(a1) * outer_r
            y1o = cy + math.sin(a1) * outer_r
            verts.extend([
                x0i, y0i, *col,  x0o, y0o, *col,  x1o, y1o, *col,
                x0i, y0i, *col,  x1o, y1o, *col,  x1i, y1i, *col,
            ])
        self._hud_draw_col(w, h, verts)

    def enqueue_lore_lines(self, lines: List[str]) -> None:
        for ln in (lines or []):
            s = str(ln or '').strip()
            if s:
                self._lore_queue.append(s)
        if not self._lore_current and self._lore_queue:
            self._advance_lore_line()

    def is_lore_playing(self) -> bool:
        return bool(self._lore_current)

    def _advance_lore_line(self) -> None:
        if not self._lore_queue:
            self._lore_current = ''
            self._lore_current_start = 0
            self._lore_current_end = 0
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
        if now >= self._lore_current_end:
            self._lore_current = ''
            return
        duration = max(0.01, self._lore_current_end - self._lore_current_start)
        t = max(0.0, min(1.0, (now - self._lore_current_start) / duration))
        fade = 0.18
        a = (t / fade if t < fade
             else (1 - t) / fade if t > 1 - fade
             else 1.0)
        alpha = int(230 * max(0.0, min(1.0, a)))
        if alpha <= 0:
            return
        text = str(self._lore_current)
        _, tw, th = self.renderer.get_text_texture(
            text, font_family='Arial', font_size=18,
            bold=False, color=(255, 255, 255, 255), pad=10)
        tw = min(w - 80, tw)
        bx = (w - tw) * 0.5
        by = int(h * 0.56)
        outline = (0, 0, 0, alpha)
        for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1),
                       (-1, -1), (1, 1), (-1, 1), (1, -1)):
            self._gl_text_center(bx + ox, by + oy, float(tw), float(th + 4), text,
                                 font_size=18, bold=False, color=outline)
        self._gl_text_center(bx, by, float(tw), float(th + 4), text,
                             font_size=18, bold=False, color=(255, 255, 255, alpha))

    def show_level_select_modal(self, *, unlocked: Set[str],
                                allow_close: bool, return_to_pause: bool) -> None:
        self._modal_visible = True
        self._modal_kind = 'level_select'
        self._modal_title = 'Select Level'
        self._modal_body = ('Level 2 is locked until you complete Level 1.\n'
                            'Entering a level always starts fresh.')
        self._modal_unlocked = set(unlocked)
        self._modal_allow_close = bool(allow_close)
        self._modal_return_to_pause = bool(return_to_pause)
        self._modal_btn_rects.clear()
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

    def _try_open_minimap(self) -> None:
        now = time.perf_counter()
        if now < self._minimap_cooldown_until:
            return
        self._minimap_until = now + 10.0
        self._minimap_cooldown_until = now + 30.0

    def _close_minimap(self) -> None:
        self._minimap_until = 0.0

    def _toggle_minimap(self) -> None:
        now = time.perf_counter()
        if now < self._minimap_until:
            self._close_minimap()
            return
        self._try_open_minimap()

    def _fps_camera_start(self, center_x: int, center_y: int) -> None:
        self._mouse_captured = True
        self._mouse_center = (center_x, center_y)
        self._mouse_skip_next_delta = True
        self.SetCursor(wx.Cursor(wx.CURSOR_BLANK))
        if not self.HasCapture():
            self.CaptureMouse()
        self.WarpPointer(center_x, center_y)

    def _fps_camera_stop(self) -> None:
        self._mouse_captured = False
        self._mouse_center = None
        self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))
        if self.HasCapture():
            self.ReleaseMouse()

    def _fps_camera_update(self, dx: float, dy: float) -> None:
        self.core.rotate_player(-dx * FPS_CAMERA_SENSITIVITY)
        self.core.tilt_camera(-dy * FPS_CAMERA_SENSITIVITY)

    def _on_left_down(self, evt: wx.MouseEvent) -> None:
        if self._stats_visible:
            return
        if bool(getattr(self.core, 'paused', False)):
            evt.Skip()
            return
        if self._modal_visible:
            evt.Skip()
            return
        self.SetFocus()
        cw, ch = self.GetClientSize()
        self._fps_camera_start(cw // 2, ch // 2)
        evt.Skip()

    def _on_left_up(self, evt: wx.MouseEvent) -> None:
        self._fps_camera_stop()
        evt.Skip()

    def _on_mouse_move(self, evt: wx.MouseEvent) -> None:
        if bool(getattr(self.core, 'paused', False)):
            evt.Skip()
            return
        if not self._mouse_captured or not self._mouse_center:
            evt.Skip()
            return
        if self._mouse_skip_next_delta:
            self._mouse_skip_next_delta = False
            cx, cy = self._mouse_center
            self.WarpPointer(cx, cy)
            evt.Skip()
            return
        mx, my = evt.GetPosition()
        cx, cy = self._mouse_center
        dx, dy = mx - cx, my - cy
        if abs(dx) > 1 or abs(dy) > 1:
            self._fps_camera_update(dx, dy)
            self.WarpPointer(cx, cy)
        evt.Skip()

    def _on_capture_lost(self, _evt: wx.MouseCaptureLostEvent) -> None:
        self._fps_camera_stop()

    def hide_mouse_capture(self) -> None:
        self._fps_camera_stop()


class WxGameWindow(wx.Frame):

    def __init__(self):
        self.performance_monitor = PerformanceMonitor(framework='wxPython')

        screen = wx.Display().GetClientArea()
        super().__init__(None, title='Within the Walls (wxPython)',
                         size=(screen.GetWidth(), screen.GetHeight()))
        self.Show()
        self.Center()

        self._progress_path = os.path.abspath('progression_wx.json')
        self._progress = self._load_progression()

        unlocked = set(self._progress.get('unlocked_levels') or [])
        last_level = str(self._progress.get('last_level') or 'level1')
        if last_level not in unlocked:
            last_level = 'level1'

        self._save_path = os.path.abspath('savegame_wx.json')
        self._current_level_id = last_level

        self.core = GameCore(level_id=last_level)

        self._asset_dir = os.path.abspath('assets')
        self._audio = _SimpleAudio(self._asset_dir)

        self._ghost_sound_active = True
        wx.CallLater(2500, self._ghost_sound_tick)

        self._key_minigame_open = False
        self._assembly_minigame: Optional[Assembly3DMinigame] = None
        self._last_ghost_id: int = 0

        self._lore_flags:    Dict[str, bool] = {}
        self._persist_seen:  Dict[str, bool] = {}
        self._pending_gameplay_tutorial = False
        self._callbacks_core_token = 0

        self.keys_pressed: Set[int] = set()

        self.core._performance_monitor = self.performance_monitor

        self.canvas = GameGLCanvas(self, self.core)
        self.canvas.performance_monitor = self.performance_monitor

        self._level_end_triggered = False
        self._level_complete = False
        self._perf_pdf_exported = False

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.canvas, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self.Bind(wx.EVT_CLOSE,    self._on_close)
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)
        self.Bind(wx.EVT_ICONIZE,  self._on_iconize)
        self.Bind(wx.EVT_TIMER,    self._on_tick)

        self.canvas.Bind(wx.EVT_KEY_DOWN,   self._on_key_down)
        self.canvas.Bind(wx.EVT_KEY_UP,     self._on_key_up)
        self.canvas.Bind(wx.EVT_LEFT_DOWN,  self._on_click)
        self.canvas.Bind(wx.EVT_KILL_FOCUS, self._on_kill_focus)

        self._tick = wx.Timer(self)
        self._tick.Start(16)

        self._last_update_time = time.perf_counter()
        self._register_core_callbacks()

        wx.CallAfter(self._start_initial_level)

    def _start_initial_level(self) -> None:
        autoload = (self._current_level_id == 'level1'
                    and os.path.exists(self._save_path))
        if self._current_level_id == 'level2':
            self._set_paused(False)
            self._start_level(
                'level2', load_save=os.path.exists(self._save_path))
        elif autoload:
            self._set_paused(False)
            self._start_level('level1', load_save=True)
        else:
            self._open_level_select_modal(startup=True)

    def _ghost_sound_tick(self) -> None:
        if not self._ghost_sound_active:
            return
        self._play_ghost_sound()
        wx.CallLater(2500, self._ghost_sound_tick)

    def _play_ghost_sound(self) -> None:
        if getattr(self.core, 'paused', False):
            return
        if getattr(self.core, 'game_won', False) or getattr(self.core, 'game_completed', False):
            return
        if not getattr(self.core, 'ghosts', None):
            return
        px = float(self.core.player.x)
        pz = float(self.core.player.z)
        nearest = min(
            (math.hypot(float(g.x) - px, float(g.z) - pz)
             for g in self.core.ghosts.values()),
            default=None)
        if nearest is None or nearest > 10.0:
            return
        self._audio.play_ghost()

    def _set_footsteps_playing(self, playing: bool) -> None:
        try:
            self._audio.set_footsteps(bool(playing))
        except Exception:
            pass

    def _reset_input_state(self) -> None:
        self.keys_pressed.clear()
        try:
            self.canvas.hide_mouse_capture()
        except Exception:
            pass
        self._set_footsteps_playing(False)

    def _on_activate(self, evt: wx.ActivateEvent) -> None:
        if not evt.GetActive():
            self._reset_input_state()
        evt.Skip()

    def _on_iconize(self, evt: wx.IconizeEvent) -> None:
        if evt.IsIconized():
            self._reset_input_state()
        evt.Skip()

    def _on_kill_focus(self, evt: wx.FocusEvent) -> None:
        self._reset_input_state()
        evt.Skip()

    def _register_core_callbacks(self) -> None:
        token = id(self.core)
        if self._callbacks_core_token == token:
            return
        self._callbacks_core_token = token
        ev = self.core.register_event_callback
        ev('coin_picked',              self._on_coin_picked)
        ev('gate_opened',              self._on_gate_moved)
        ev('gate_closed',              self._on_gate_moved)
        ev('time_penalty',             self._on_time_penalty)
        ev('exit_unlocked',            self._on_exit_unlocked)
        ev('sector_entered',           self._on_sector_entered)
        ev('sent_to_jail',             self._on_sent_to_jail)
        ev('sent_to_spawn',           self._on_sent_to_spawn)
        ev('left_jail', lambda d: None)
        ev('key_fragment_encountered', self._on_key_fragment_encountered)
        ev('key_picked',               self._on_key_picked)
        ev('game_won',                 self._on_game_won)
        ev('checkpoint_reached',       self._on_checkpoint_reached)

    def _on_coin_picked(self, data: dict) -> None:
        self._audio.play_coin()
        try:
            if float(self.core.coins_collected) >= float(self.core.coins_required) * 0.5:
                k = f'coins_half_{self._current_level_id}'
                if not self._lore_flags.get('coins_half') and not self._persist_seen.get(k):
                    self._lore_flags['coins_half'] = True
                    self._persist_seen[k] = True
                    self._show_lore_line('Halfway there.' if self._current_level_id == 'level1'
                                         else 'The maze likes it when I collect.')
        except Exception:
            pass

    def _on_gate_moved(self, _data: dict) -> None:
        self._audio.play_gate()

    def _on_time_penalty(self, data: dict) -> None:
        try:
            s = int((data or {}).get('seconds', 0) or 0)
            if s > 0:
                self.canvas._time_bonus_text = f'+{s}'
                self.canvas._time_bonus_until = time.perf_counter() + 2.5
                self.canvas.Refresh(False)
        except Exception:
            pass

    def _on_exit_unlocked(self, _data: dict) -> None:
        pass

    def _on_sector_entered(self, data: dict) -> None:
        sid = str((data or {}).get('id', '') or '')
        if self._current_level_id == 'level2' and sid == 'F':
            try:
                req = (int(self.core.coins_collected) >= int(self.core.coins_required)
                       and int(self.core.keys_collected) >= int(self.core.keys_required))
            except Exception:
                req = False
            if req and not self._lore_flags.get('l2_sector_f_done'):
                self._lore_flags['l2_sector_f_done'] = True
                self._show_lore_line('A dream... Far too lucid.')

    def _on_sent_to_jail(self, _data: dict) -> None:
        reason = str(_data.get('reason', ''))
        if reason == 'ghost_4':
            self._last_ghost_id = 4
        elif reason.startswith('ghost'):
            self._last_ghost_id = 1  # Normal ghost
        else:
            self._last_ghost_id = 0  # Spikes or other
        if self._current_level_id != 'level1':
            return
        if not self._persist_seen.get('tutorial_jail'):
            self._persist_seen['tutorial_jail'] = True
            self._show_tutorial_modal(
                'Jail',
                'This is not death.\n'
                'To escape, find the table and press E to interact with the glowing book.\n\n'
                'A sector map is displayed here. Use it to orient yourself before returning to the maze.')

    def _on_sent_to_spawn(self, _data: dict) -> None:
        self._show_lore_line('Be safe.')
        self.canvas.trigger_flash(300, (20/255, 20/255, 25/255, 180/255))

    def _on_key_picked(self, data: dict) -> None:
        try:
            cnt = int((data or {}).get('count', 0) or 0)
            if (self._current_level_id == 'level2' and cnt >= 3
                    and not self._lore_flags.get('l2_frags_done')):
                self._lore_flags['l2_frags_done'] = True
                self._show_lore_line('The key is done... I am watched.')
        except Exception:
            pass

    def _on_game_won(self, data: dict) -> None:
        if self._current_level_id != 'level1':
            return
        unlocked = set(self._progress.get('unlocked_levels') or [])
        if 'level2' not in unlocked:
            unlocked.add('level2')
            self._progress['unlocked_levels'] = sorted(unlocked)
            self._save_progression()

    def _on_checkpoint_reached(self, _data: dict) -> None:
        self.core.simulation_frozen = True
        self._set_footsteps_playing(False)
        self._last_update_time = time.perf_counter()
        self.canvas.Refresh(False)

    def _on_key_fragment_encountered(self, data: dict) -> None:
        if getattr(self.core, 'paused', False) or self._key_minigame_open:
            return
        frag_id = str((data or {}).get('id', '') or '')
        if not frag_id:
            return
        try:
            frag = getattr(self.core, 'key_fragments', {}).get(frag_id)
            frag_kind = str(getattr(frag, 'kind', '') or '')
        except Exception:
            frag_kind = ''

        self._key_minigame_open = True
        self.keys_pressed.clear()
        self._set_footsteps_playing(False)
        self.canvas.hide_mouse_capture()
        prev = bool(getattr(self.core, 'simulation_frozen', False))
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
            self.core.simulation_frozen = prev
            self._last_update_time = time.perf_counter()

        if ok:
            self.core.mark_key_fragment_taken(frag_id)
            self.core.defer_key_fragment(frag_id)
        else:
            self.core.clear_pending_key_fragment(frag_id)
            self.core.defer_key_fragment(frag_id)
        self.keys_pressed.clear()
        self._key_minigame_open = False

    def _handle_interact(self) -> None:
        if getattr(self.core, 'paused', False):
            return
        action = self.core.interact()
        if not action:
            return
        if action == 'jail_book':
            self.keys_pressed.clear()
            self._set_footsteps_playing(False)
            self.canvas.hide_mouse_capture()
            prev = bool(getattr(self.core, 'simulation_frozen', False))
            self.core.simulation_frozen = True
            ok = False
            try:
                hard_mode = (self._last_ghost_id == 4)
                ok = bool(SilhouetteMatchDialog(
                    self, hard_mode=hard_mode).ShowModal() == wx.ID_OK)
            finally:
                self.core.simulation_frozen = prev
                self._last_update_time = time.perf_counter()
            if ok:
                self.core.mark_jail_puzzle_success()
                if (self._current_level_id == 'level1'
                        and not self._lore_flags.get('l1_jail_puzzle_success')):
                    self._lore_flags['l1_jail_puzzle_success'] = True
                    self._show_lore_line(
                        'The maze resets what it cannot control.')
            self.keys_pressed.clear()
        elif action == 'gate_jail':
            self.core.try_leave_jail()

    def _load_progression(self) -> dict:
        if not os.path.exists(self._progress_path):
            return {'unlocked_levels': ['level1']}
        try:
            with open(self._progress_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError
            if ('level1' not in (data.get('unlocked_levels') or [])):
                raise ValueError
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
        self._progress['last_level'] = str(self._current_level_id)
        self._save_progression()
        try:
            state = self.core.get_save_state()
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
                if str(state.get('level_id') or '') != self._current_level_id:
                    return
                seen = state.get('ui_seen')
                if isinstance(seen, dict):
                    self._persist_seen.update(
                        {str(k): bool(v) for k, v in seen.items()})
            self.core.load_save_state(state)
        except Exception:
            pass

    def _start_level(self, level_id: str, *, load_save: bool) -> None:
        level_id = str(level_id or 'level1')
        paused_was = bool(getattr(self.core, 'paused', False))
        try:
            self.core.simulation_frozen = False
        except Exception:
            pass

        self.core = GameCore(level_id=level_id)
        self._current_level_id = level_id
        self.canvas.core = self.core

        self._level_end_triggered = False
        self._level_complete = False
        self._perf_pdf_exported = False
        self.canvas._show_the_end = False
        self.canvas._stats_visible = False
        self.canvas._stats_text = ''
        self.canvas._end_screen_visible = False

        for k in ('coins_half', 'ghost_close', 'l2_frags_done', 'l2_sector_f_done'):
            self._lore_flags.pop(k, None)
        self.__dict__.pop('_player_has_moved', None)

        old_startup_time = getattr(
            self.performance_monitor, 'startup_time_ms', None)
        old_texture_load_time = getattr(
            self.performance_monitor, 'texture_load_time_ms', None)

        self.performance_monitor = PerformanceMonitor(framework='wxPython')
        if old_startup_time is not None:
            self.performance_monitor.startup_time_ms = old_startup_time
        if old_texture_load_time is not None:
            self.performance_monitor.texture_load_time_ms = old_texture_load_time

        self.canvas.performance_monitor = self.performance_monitor
        self.core._performance_monitor = self.performance_monitor

        try:
            self.canvas.SetCurrent(self.canvas._gl_context)
            if hasattr(self.canvas, 'renderer') and self.canvas.renderer:
                self.canvas.renderer.clear_text_texture_cache()
            self.canvas.renderer = OpenGLRenderer(self.core)
            cw, ch = self.canvas.GetClientSize()
            self.canvas.renderer.resize(int(cw), int(ch))
            self.canvas.renderer.initialize()
            self.canvas._cam_icon_tex = self.canvas.renderer._load_texture(
                os.path.join(self.canvas._assets_dir, 'cam.jpg'))
        except Exception:
            try:
                self.canvas.renderer.core = self.core
            except Exception:
                pass

        self.keys_pressed.clear()
        self._register_core_callbacks()

        if load_save:
            self._load_save_if_present()
        if paused_was:
            self._set_paused(True)
        self._last_update_time = time.perf_counter()

        if float(getattr(self.core, 'elapsed_s', 0.0) or 0.0) <= 0.0001:
            if level_id == 'level1' and not self._persist_seen.get('l1_intro'):
                self._persist_seen['l1_intro'] = True
                self._show_lore_line('A basement? This feels like a test.')
                self._pending_gameplay_tutorial = True
            elif level_id == 'level2' and not self._persist_seen.get('l2_intro'):
                self._persist_seen['l2_intro'] = True
                self._show_lore_line('This place feels inhabited.')

        if not load_save and float(getattr(self.core, 'elapsed_s', 0.0) or 0.0) <= 0.0001:
            self._audio.play_gate()

        self.canvas.Refresh(False)

    def _set_paused(self, paused: bool) -> None:
        self.core.paused = bool(paused)
        if paused:
            self.keys_pressed.clear()
            self.canvas.hide_mouse_capture()
            self._set_footsteps_playing(False)

    def _toggle_pause(self) -> None:
        if (self.core.screen_closing or self.core.game_completed
                or self.core.game_won):
            return
        self._set_paused(not bool(getattr(self.core, 'paused', False)))
        self.canvas.Refresh(False)

    def _open_level_select_modal(self, *, startup: bool, allow_close: bool | None = None) -> None:
        unlocked = set(self._progress.get('unlocked_levels') or [])
        self._set_paused(True)
        self.canvas.hide_mouse_capture()
        if allow_close is None:
            allow_close = not startup
        self.canvas.show_level_select_modal(
            unlocked=unlocked,
            allow_close=allow_close,
            return_to_pause=(not startup))
        self.canvas.Refresh(False)

    def _on_tick(self, _evt: wx.TimerEvent) -> None:
        now = time.perf_counter()
        dt = min(now - self._last_update_time, 0.05)
        self._last_update_time = now

        paused = bool(getattr(self.core, 'paused', False))

        if self.core.screen_closing and not self.core.game_won:
            self.core._update_screen_close(dt)
        elif not paused:
            self.core.update(dt)

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

        if (bool(getattr(self.core, 'game_won', False))
                and not self._level_end_triggered):
            self._level_end_triggered = True
            self._handle_level_end()

        if paused or self.canvas._modal_visible:
            self.canvas.Refresh(False)
            return

        if self._pending_gameplay_tutorial and not self.canvas._modal_visible:
            if not self.canvas.is_lore_playing():
                self._pending_gameplay_tutorial = False
                if (self._current_level_id == 'level1'
                        and not self._persist_seen.get('tutorial_gameplay')):
                    self._persist_seen['tutorial_gameplay'] = True
                    self._show_tutorial_modal(
                        'Gameplay',
                        'Press WASD to move.\n'
                        'Hold Left Mouse Button to look around.\n'
                        'Press ESC to pause. You can also save and exit from the pause menu.\n\n'
                        'Press M or click the camera icon to open the minimap.\n'
                        'The minimap stays open for 10 seconds, then goes on a 20 second cooldown.\n\n'
                        'Collect all coins and key fragments to unlock the exit.\n'
                        'Avoid hazards. If you get caught, you will be sent to jail.')

        if paused or self.canvas._modal_visible or getattr(self.core, 'simulation_frozen', False):
            self.canvas.Refresh(False)
            return

        move_speed = 4.5 if self._current_level_id == 'level1' else 5.5
        dx = dz = 0.0
        if ord('W') in self.keys_pressed:
            dz += 1.0
        if ord('S') in self.keys_pressed:
            dz -= 1.0
        if ord('A') in self.keys_pressed:
            dx -= 1.0
        if ord('D') in self.keys_pressed:
            dx += 1.0

        if dx != 0.0 and dz != 0.0:
            length = math.sqrt(dx * dx + dz * dz)
            dx /= length
            dz /= length

        # Scale movement by delta time for frame-rate independent speed
        dx *= move_speed * dt
        dz *= move_speed * dt

        moved = False
        if dx != 0.0 or dz != 0.0:
            try:
                moved = bool(self.core.move_player(dx, dz))
            except Exception:
                moved = False
            if moved:
                self.performance_monitor.record_input_processed()
            if moved and not hasattr(self, '_player_has_moved'):
                self._player_has_moved = True

        self._set_footsteps_playing(moved and not self._key_minigame_open)

        try:
            nearest = min(
                (math.hypot(g.x - self.core.player.x, g.z - self.core.player.z)
                 for g in self.core.ghosts.values()),
                default=None)
            if nearest is not None and nearest <= 2.0:
                if not self._lore_flags.get('ghost_close'):
                    self._lore_flags['ghost_close'] = True
                    k = f'ghost_close_{self._current_level_id}'
                    if not self._persist_seen.get(k):
                        self._persist_seen[k] = True
                        txt = ('Why are you here?' if self._current_level_id == 'level1'
                               else 'Wake me up.')
                        self._show_lore_line(txt)
        except Exception:
            pass

        self.canvas.Refresh(False)

    def _handle_level_end(self) -> None:
        self._level_end_triggered = True
        self._level_complete = True
        self.core.simulation_frozen = True
        self._set_footsteps_playing(False)

        if self._current_level_id == 'level1':
            unlocked = set(self._progress.get('unlocked_levels') or ['level1'])
            unlocked.add('level2')
            self._progress['unlocked_levels'] = sorted(unlocked)
            self._save_progression()

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
            summary_text = self.performance_monitor.format_summary_text()
        except Exception as exc:
            summary_text = f'Level complete!\n\nPress ESC to continue.\n\n({exc})'

        try:
            if not self._perf_pdf_exported:
                from core.pdf_export import export_performance_pdf
                performance_data = self.performance_monitor.get_performance_summary()
                export_performance_pdf(
                    framework='wxpython',
                    level_id=self._current_level_id,
                    performance_data=performance_data,
                    out_dir=os.path.abspath('performance_reports'),
                )
                self._perf_pdf_exported = True
                print(f'[wxPython] PDF report exported to performance_reports/')
        except ImportError as e:
            print(f'[wxPython] PDF export not available: {e}')
        except Exception as e:
            print(f'[wxPython] PDF export failed: {e}')
            import traceback
            traceback.print_exc()

        if self._current_level_id == 'level2':
            self.canvas.show_end_screen(summary_text)
        else:
            self.canvas.show_stats_screen(summary_text)
        self.canvas.Refresh(False)

    def _on_stats_screen_esc(self) -> None:
        if not self._level_complete:
            return
        if self._current_level_id == 'level2':
            self.canvas.hide_stats_screen()
            self.canvas._show_the_end = True
            self.canvas.Refresh(False)
            return
        self.canvas.hide_stats_screen()
        self._level_complete = False
        self._open_level_select_modal(startup=False, allow_close=False)
        self.canvas.Refresh(False)

    def _on_key_down(self, evt: wx.KeyEvent) -> None:
        self.performance_monitor.record_input_event()
        code = int(evt.GetKeyCode())
        self.keys_pressed.add(code)

        if code in (ord('M'), ord('m')):
            self.canvas._toggle_minimap()
            return

        if code in (ord('E'), ord('e')):
            self._handle_interact()
            return

        if code == wx.WXK_ESCAPE:
            if self.canvas._show_the_end:
                self.Close()
                return
            if self.canvas._stats_visible:
                self._on_stats_screen_esc()
                return
            if self.canvas._modal_visible:
                rtp = bool(
                    getattr(self.canvas, '_modal_return_to_pause', False))
                self.canvas.hide_modal()
                self._set_paused(rtp)
                return
            self._toggle_pause()
            return

        evt.Skip()

    def _on_key_up(self, evt: wx.KeyEvent) -> None:
        self.keys_pressed.discard(int(evt.GetKeyCode()))
        evt.Skip()

    def _on_click(self, evt: wx.MouseEvent) -> None:
        if self.canvas._stats_visible:
            return
        pos = evt.GetPosition()

        if self.canvas._cam_icon_rect.Contains(pos):
            self.canvas._toggle_minimap()
            self.canvas.Refresh(False)
            return

        hit = self.canvas.hit_test_modal(pos)
        if hit:
            if hit == 'close':
                if not self.canvas._modal_allow_close:
                    return
                rtp = bool(
                    getattr(self.canvas, '_modal_return_to_pause', False))
                self.canvas.hide_modal()
                self._set_paused(rtp)
                return
            if hit in ('level1', 'level2'):
                if hit == 'level2' and hit not in self.canvas._modal_unlocked:
                    return
                self.canvas.hide_modal()
                self._set_paused(False)
                try:
                    self._progress['last_level'] = str(hit)
                    self._save_progression()
                except Exception:
                    pass
                self._start_level(str(hit), load_save=False)
                return
            return

        hit = self.canvas.hit_test_pause(pos)
        if hit:
            self._on_pause_action(hit)
            return
        evt.Skip()

    def _on_pause_action(self, action: str) -> None:
        if action == 'resume':
            self._toggle_pause()
        elif action == 'levels':
            self._toggle_pause()
            self._open_level_select_modal(startup=False)
        elif action == 'save':
            self._save_game()
        elif action == 'save_exit':
            self._save_game()
            self.Close()
        elif action == 'restart':
            self._start_level(self._current_level_id, load_save=False)
        elif action == 'exit':
            self.Close()

    def _show_lore_line(self, text: str) -> None:
        s = str(text or '').strip()
        if s:
            self.canvas.enqueue_lore_lines([s])

    def _show_tutorial_modal(self, title: str, body: str) -> None:
        self._set_paused(True)
        self.canvas._modal_visible = True
        self.canvas._modal_kind = 'tutorial'
        self.canvas._modal_title = str(title)
        self.canvas._modal_body = str(body)
        self.canvas._modal_allow_close = True
        self.canvas._modal_return_to_pause = False
        self.canvas.hide_mouse_capture()
        self.keys_pressed.clear()

    def _on_close(self, evt: wx.CloseEvent) -> None:
        self._ghost_sound_active = False
        try:
            self._tick.Stop()
        except Exception:
            pass
        try:
            self.canvas.hide_mouse_capture()
        except Exception:
            pass
        try:
            self._audio.shutdown()
        except Exception:
            pass
        self.Destroy()
        evt.Skip()


def run() -> int:
    app = wx.App(False)
    win = WxGameWindow()
    win.Maximize(True)
    win.Show(True)
    return int(app.MainLoop() or 0)
