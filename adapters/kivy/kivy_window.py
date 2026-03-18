"""
kivy_window.py  –  Kivy port, exact visual parity with PySide6/WxPython.
No from __future__ needed on Python 3.10+.
"""

# VERSION: V4
print("kivy_window.py V4 LOADING")

import json, math, os, time, random
from typing import List, Optional, Set, Tuple

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.core.audio import SoundLoader
from kivy.graphics import Color, Rectangle, Line, Ellipse, Triangle
from kivy.uix.widget import Widget
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.graphics import Callback

import OpenGL.GL as GL

from core.game_core import GameCore
from core.performance_monitor import PerformanceMonitor
from .kivy_renderer import KivyRenderer
from .kivy_silhouette import KivySilhouetteMinigame
from .kivy_assembly3d import KivyAssembly3DMinigame


# ─── colours ───────────────────────────────────────────────────────────
# QColor(18,18,22,235)   panel bg
_PANEL_BG     = (18/255, 18/255, 22/255, 235/255)
# QColor(220,220,220)    panel border / button border
_BORDER       = (220/255, 220/255, 220/255, 1)
# QColor(32,32,40,235)   button bg
_BTN_BG       = (32/255, 32/255, 40/255, 235/255)
# QColor(255,255,255)    button text
_BTN_FG       = (1, 1, 1, 1)
# QColor(255,220,110)    "PAUSED" yellow
_PAUSED_COL   = (1, 220/255, 110/255, 1)
# QColor(0,0,0,160)      overlay
_OVERLAY      = (0, 0, 0, 160/255)
# QColor(0,0,0,255)      level-select full black
_BLACK        = (0, 0, 0, 1)


# ─── helper: create a styled button ─────────────────────────────────────────
def _make_btn(text, on_press, **kw):
    b = Button(
        text=text,
        font_size='14sp',
        background_normal='',
        background_color=_BTN_BG,
        color=_BTN_FG,
        **kw,
    )
    b.bind(on_press=lambda *_: on_press())
    # Draw border manually (Kivy buttons have no border by default)
    def _draw_border(widget, *_):
        widget.canvas.after.clear()
        with widget.canvas.after:
            Color(*_BORDER)
            Line(rectangle=(widget.x, widget.y, widget.width, widget.height), width=1)
    b.bind(pos=_draw_border, size=_draw_border)
    return b


# ─────────────────────────────────────────────────────────────────────────────
# GL scene widget
# ─────────────────────────────────────────────────────────────────────────────

class _GameGLWidget(Widget):
    def __init__(self, renderer, **kwargs):
        super().__init__(**kwargs)
        self.renderer = renderer
        self.performance_monitor: Optional[PerformanceMonitor] = None
        with self.canvas:
            Callback(self._draw_scene)
        Clock.schedule_interval(lambda *_: self.canvas.ask_update(), 0)

    def _draw_scene(self, instr):
        try:
            pm = getattr(self, 'performance_monitor', None)
            if pm is not None:
                try:
                    if pm.resolution == (0, 0):
                        pm.set_resolution(int(Window.width), int(Window.height))
                except Exception:
                    pass
                try:
                    pm.start_frame()
                except Exception:
                    pass
            self.renderer.render(max(1, int(Window.width)), max(1, int(Window.height)))
            if pm is not None:
                try:
                    pm.record_input_response(time.perf_counter())
                except Exception:
                    pass
                try:
                    pm.end_frame()
                except Exception:
                    pass
        except Exception:
            import traceback; traceback.print_exc()


class _KivyAudioEngine:
    def __init__(self, asset_dir: str):
        self._asset_dir = str(asset_dir or '')
        self._footsteps_playing = False
        self._footsteps = self._load('running-on-concrete-268478.wav')
        self._coin = self._load('drop-coin-384921.wav')
        self._gate = self._load('closing-metal-door-44280.wav')
        self._ghost = self._load('ghost-horror-sound-382709.wav')

        if self._footsteps is not None:
            try:
                self._footsteps.volume = 0.22
                self._footsteps.loop = True
            except Exception:
                pass
        if self._coin is not None:
            try:
                self._coin.volume = 0.55
            except Exception:
                pass
        if self._gate is not None:
            try:
                self._gate.volume = 0.55
            except Exception:
                pass
        if self._ghost is not None:
            try:
                self._ghost.volume = 0.40
            except Exception:
                pass

    def _load(self, filename: str):
        try:
            path = os.path.join(self._asset_dir, str(filename))
            if not os.path.exists(path):
                return None
            return SoundLoader.load(path)
        except Exception:
            return None

    @property
    def enabled(self) -> bool:
        return any(s is not None for s in (self._footsteps, self._coin, self._gate, self._ghost))

    def shutdown(self) -> None:
        try:
            self.set_footsteps(False)
        except Exception:
            pass

    def set_footsteps(self, playing: bool) -> None:
        playing = bool(playing)
        if playing == self._footsteps_playing:
            return
        self._footsteps_playing = playing
        if self._footsteps is None:
            return
        try:
            if playing:
                self._footsteps.play()
            else:
                self._footsteps.stop()
        except Exception:
            pass

    def play_coin(self) -> None:
        if self._coin is None:
            return
        try:
            self._coin.stop(); self._coin.play()
        except Exception:
            pass

    def play_gate(self) -> None:
        if self._gate is None:
            return
        try:
            self._gate.stop(); self._gate.play()
        except Exception:
            pass

    def play_ghost(self, *, volume: float) -> None:
        if self._ghost is None:
            return
        try:
            self._ghost.volume = max(0.0, min(1.0, float(volume)))
        except Exception:
            pass
        try:
            self._ghost.stop(); self._ghost.play()
        except Exception:
            pass

    def on_touch_down(self, touch): return False
    def on_touch_move(self, touch): return False
    def on_touch_up(self,   touch): return False


# ─────────────────────────────────────────────────────────────────────────────
# Vignette widget (sits between GL scene and HUD)
# ─────────────────────────────────────────────────────────────────────────────

class _VignetteWidget(Widget):
    """
    Radial vignette:
      - Transparent in centre (r < r_inner)
      - Fades from 0 to alpha=190/255 between r_inner and r_outer
      - Implemented as a Mesh with a radial gradient baked into vertex colours
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Clock.schedule_interval(self._redraw, 1/30.)
        self.bind(size=self._redraw, pos=self._redraw)

    def _redraw(self, *_):
        from kivy.graphics import Color, Triangle
        self.canvas.clear()
        W, H = float(Window.width), float(Window.height)
        
        # Create smooth gradient vignette using multiple triangle layers
        cx, cy = W * 0.5, H * 0.52
        min_dim = min(W, H)
        r_inner = 0.32 * min_dim
        r_outer = 0.74 * min_dim
        r_corner = math.sqrt((max(cx, W - cx))**2 + (max(cy, H - cy))**2) + 4.0
        max_alpha = 190/255 * 0.6  # Reduce overall opacity to 60% of original
        steps = 64
        gradient_layers = 8  # Number of layers for smooth gradient
        
        with self.canvas:
            # Create smooth gradient from transparent center to dark edges
            for layer in range(gradient_layers):
                # Calculate radius and alpha for this layer
                t = layer / (gradient_layers - 1)
                layer_r_inner = r_inner + (r_outer - r_inner) * t
                layer_r_outer = r_corner
                layer_alpha = max_alpha * t  # Gradually increase opacity (but lower overall)
                
                Color(0, 0, 0, layer_alpha)
                
                for i in range(steps):
                    a = (i / steps) * 2.0 * math.pi
                    ca, sa = math.cos(a), math.sin(a)
                    a_next = ((i + 1) / steps) * 2.0 * math.pi
                    ca_next, sa_next = math.cos(a_next), math.sin(a_next)
                    
                    # Calculate points for this segment
                    x1_inner = cx + ca * layer_r_inner
                    y1_inner = cy + sa * layer_r_inner
                    x1_outer = cx + ca * layer_r_outer
                    y1_outer = cy + sa * layer_r_outer
                    
                    x2_inner = cx + ca_next * layer_r_inner
                    y2_inner = cy + sa_next * layer_r_inner
                    x2_outer = cx + ca_next * layer_r_outer
                    y2_outer = cy + sa_next * layer_r_outer
                    
                    # Draw two triangles for this segment
                    Triangle(points=[x1_inner, y1_inner, x1_outer, y1_outer, x2_inner, y2_inner])
                    Triangle(points=[x2_inner, y2_inner, x1_outer, y1_outer, x2_outer, y2_outer])
            
            # Animated fog layer (also with smooth gradient and lower opacity)
            t = time.perf_counter()
            fog_cx = cx + 18.0 * math.sin(t * 0.35)
            fog_cy = cy + 14.0 * math.cos(t * 0.31)
            fog_r_inner = r_outer * 0.55
            fog_r_outer = r_corner * 1.02
            
            fog_layers = 4  # Fewer layers for fog (subtle effect)
            fog_max_alpha = (32/255) * 0.5  # Reduce fog opacity to 50% of original
            
            for layer in range(fog_layers):
                t = layer / (fog_layers - 1)
                layer_r_inner = fog_r_inner + (fog_r_outer - fog_r_inner) * t
                layer_r_outer = fog_r_outer
                layer_alpha = fog_max_alpha * t
                
                Color(0, 0, 0, layer_alpha)
                
                for i in range(steps):
                    a = (i / steps) * 2.0 * math.pi
                    ca, sa = math.cos(a), math.sin(a)
                    a_next = ((i + 1) / steps) * 2.0 * math.pi
                    ca_next, sa_next = math.cos(a_next), math.sin(a_next)
                    
                    # Calculate fog points
                    x1_inner = fog_cx + ca * layer_r_inner
                    y1_inner = fog_cy + sa * layer_r_inner
                    x1_outer = fog_cx + ca * layer_r_outer
                    y1_outer = fog_cy + sa * layer_r_outer
                    
                    x2_inner = fog_cx + ca_next * layer_r_inner
                    y2_inner = fog_cy + sa_next * layer_r_inner
                    x2_outer = fog_cx + ca_next * layer_r_outer
                    y2_outer = fog_cy + sa_next * layer_r_outer
                    
                    # Draw fog triangles
                    Triangle(points=[x1_inner, y1_inner, x1_outer, y1_outer, x2_inner, y2_inner])
                    Triangle(points=[x2_inner, y2_inner, x1_outer, y1_outer, x2_outer, y2_outer])


class _ClosingAnimWidget(Widget):
    def __init__(self, gw, **kwargs):
        super().__init__(**kwargs)
        self._gw = gw
        Clock.schedule_interval(lambda *_: self._redraw(), 1/60.)

    def _redraw(self, *_):
        from kivy.graphics import Mesh
        self.canvas.clear()
        gw = getattr(self, '_gw', None)
        core = getattr(gw, 'core', None) if gw else None
        if core is None:
            return
        # Suppress closing animation when stats screen is showing
        if bool(getattr(gw, '_stats_visible', False)):
            return
        prog = float(getattr(core, 'screen_close_progress', 0.0) or 0.0)
        if prog <= 0.0:
            return

        w = float(Window.width)
        h = float(Window.height)
        cx = w * 0.5
        cy = h * 0.5

        max_r = math.sqrt(cx * cx + cy * cy) + 4.0
        ease = prog * prog
        inner_r = max_r * (1.0 - ease)
        outer_r = max_r + 6.0
        steps = 64

        # Mesh: triangle_strip of (inner, outer) ring, all black.
        verts = []
        idx = []
        for i in range(steps + 1):
            a = (i / steps) * 2.0 * math.pi
            ca = math.cos(a)
            sa = math.sin(a)
            # Kivy Mesh default attribute names are v_pos and v_color.
            verts.extend([cx + ca * inner_r, cy + sa * inner_r, 0.0, 0.0, 0.0, 1.0])
            verts.extend([cx + ca * outer_r, cy + sa * outer_r, 0.0, 0.0, 0.0, 1.0])
        idx = list(range((steps + 1) * 2))

        with self.canvas:
            Mesh(vertices=verts, indices=idx, mode='triangle_strip',
                 fmt=[('v_pos', 2, 'float'), ('v_color', 4, 'float')])

# ─────────────────────────────────────────────────────────────────────────────
# Cam icon widget (bottom-right, loads assets/cam.jpg)
# ─────────────────────────────────────────────────────────────────────────────

class _CamIconWidget(Button):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_color  = (0, 0, 0, 0)
        self._cooldown_until   = 0.0
        self._tex              = None
        self._cd_text          = ''
        Clock.schedule_once(self._load_tex, 0.1)
        Clock.schedule_interval(self._upd, 0.5)
        self.bind(pos=self._redraw, size=self._redraw)

    def _load_tex(self, *_):
        p = os.path.join('assets', 'cam.jpg')
        if os.path.exists(p):
            try:
                from kivy.core.image import Image as KImg
                self._tex = KImg(p).texture
            except Exception:
                pass
        self._redraw()

    def _redraw(self, *_):
        sz = self.width
        x, y = self.x, self.y
        self.canvas.before.clear()
        with self.canvas.before:
            Color(0, 0, 0, 130/255)
            Rectangle(pos=(x-6, y-6), size=(sz+12, sz+12))
            Color(*_BORDER)
            Line(rectangle=(x-6, y-6, sz+12, sz+12), width=1)
            if self._tex:
                Color(1, 1, 1, 1)
                Rectangle(pos=(x, y), size=(sz, sz), texture=self._tex)
            else:
                Color(120/255, 120/255, 120/255, 1)
                Rectangle(pos=(x, y), size=(sz, sz))
        # Draw cooldown text as a child Label drawn at correct position
        self._draw_cd_overlay()

    def _draw_cd_overlay(self):
        self.canvas.after.clear()
        if not self._cd_text:
            return
        # Draw a dark overlay + centered label over the icon
        x, y, sz = self.x, self.y, self.width
        with self.canvas.after:
            Color(0, 0, 0, 0.6)
            Rectangle(pos=(x, y), size=(sz, sz))
        # Use a temporary Label to get the texture and blit it
        from kivy.core.text import Label as CoreLabel
        lbl = CoreLabel(text=self._cd_text, font_size=14,
                        color=(1, 210/255, 90/255, 1))
        lbl.refresh()
        texture = lbl.texture
        tw, th = texture.size
        tx = x + (sz - tw) / 2
        ty = y + (sz - th) / 2
        with self.canvas.after:
            Color(1, 1, 1, 1)
            Rectangle(pos=(tx, ty), size=(tw, th), texture=texture)

    def _upd(self, *_):
        now = time.perf_counter()
        if now < self._cooldown_until:
            rem = int(math.ceil(self._cooldown_until - now))
            self._cd_text = f'{rem}s'
        else:
            self._cd_text = ''
        self._redraw()


# ─────────────────────────────────────────────────────────────────────────────
# Minimap widget
# ─────────────────────────────────────────────────────────────────────────────

class _MinimapWidget(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.core  = None
        self._until = 0.0

    def on_touch_down(self, touch):
        return False if self.opacity == 0 else super().on_touch_down(touch)

    def redraw(self):
        self.canvas.clear()
        if not self.core: return
        layout = self.core.layout
        rows = len(layout)
        cols = len(layout[0]) if rows else 0
        W, H = Window.width, Window.height
        cell = max(1, min(int(W * 0.85 / max(cols, 1)),
                          int((H - 40) / max(rows, 1))))
        mw, mh = cols*cell, rows*cell
        ox = (W - mw)//2
        oy = 20 + ((H - 40) - mh)//2
        walls  = self.core.walls
        floors = self.core.floors
        with self.canvas:
            Color(10/255, 10/255, 12/255, 210/255)
            Rectangle(pos=(ox, oy), size=(mw, mh))
            Color(230/255, 230/255, 230/255, 1)
            Line(rectangle=(ox, oy, mw, mh), width=1.5)
            for r in range(rows):
                for c in range(cols):
                    rx = ox + c*cell
                    ry = oy + (rows-1-r)*cell
                    if (r,c) in walls:
                        Color(45/255, 45/255, 55/255, 1)
                    elif (r,c) in floors:
                        Color(125/255, 125/255, 135/255, 1)
                    else:
                        Color(15/255, 15/255, 18/255, 1)
                    Rectangle(pos=(rx, ry), size=(cell+1, cell+1))
            # Coins
            csz = max(6, int(cell*0.35))
            Color(255/255, 215/255, 0, 1)
            for coin in self.core.coins.values():
                if coin.taken: continue
                cr, cc = coin.cell
                Ellipse(pos=(ox+cc*cell+cell//2-csz//2,
                             oy+(rows-1-cr)*cell+cell//2-csz//2), size=(csz,csz))
            # Ghosts
            GCOLS = {1:(1,.314,.235,1), 2:(.314,1,.549,1), 3:(.431,.667,1,1),
                     4:(1,.863,.314,1), 5:(1,.353,1,1)}
            gsz = max(10, int(cell*0.6))
            for g in self.core.ghosts.values():
                Color(*GCOLS.get(g.id, (1,.471,.118,1)))
                Ellipse(pos=(ox+int(g.x*cell)+cell//2-gsz//2,
                             oy+(rows-1-int(g.z))*cell+cell//2-gsz//2), size=(gsz,gsz))
            # Player: filled green diamond + white dot (matches QPainter drawPolygon)
            pr = int(self.core.player.z); pc = int(self.core.player.x)
            px = ox + pc*cell + cell//2
            py = oy + (rows-1-pr)*cell + cell//2
            psz = max(12, int(cell*0.7)); half = psz//2
            # Filled diamond using two triangles
            Color(50/255, 255/255, 50/255, 1)
            Triangle(points=[px, py-half, px+half, py, px, py+half])
            Triangle(points=[px, py-half, px, py+half, px-half, py])
            # White centre dot
            dot = max(4, psz//3)
            Color(1,1,1,1)
            Ellipse(pos=(px-dot//2, py-dot//2), size=(dot,dot))


# ─────────────────────────────────────────────────────────────────────────────
# Pause panel  — exact PySide6 parity
# panel 560×610, bg QColor(18,18,22,235), border QColor(220,220,220)
# buttons 280×48 bg QColor(32,32,40,235), all same colour, no coloured buttons
# ─────────────────────────────────────────────────────────────────────────────

class _PausePanel(FloatLayout):
    """Pause panel — 560×610 centred, exact PySide6 styling, BoxLayout buttons."""

    def __init__(self, gw, **kwargs):
        super().__init__(**kwargs)
        self._gw = gw

        # Full-screen semi-transparent overlay
        with self.canvas.before:
            Color(*_OVERLAY)
            self._bg = Rectangle(size=self.size, pos=self.pos)
        self.bind(
            size=lambda w, v: (setattr(self._bg, 'size', v),
                               setattr(self._bg, 'pos', w.pos)),
            pos=lambda w, v: setattr(self._bg, 'pos', v),
        )

        # Panel — BoxLayout does all the sizing
        panel = BoxLayout(
            orientation='vertical',
            spacing=16,
            padding=36,
            size_hint=(None, None),
            width=560,
            height=610,
            pos_hint={'center_x': .5, 'center_y': .5},
        )
        with panel.canvas.before:
            Color(*_PANEL_BG)
            self._pbg = Rectangle(pos=panel.pos, size=panel.size)
        panel.bind(
            pos=lambda w, v: (setattr(self._pbg, 'pos', v),
                              self._draw_panel_border(w)),
            size=lambda w, v: (setattr(self._pbg, 'size', v),
                               self._draw_panel_border(w)),
        )

        # Title
        panel.add_widget(Label(
            text='PAUSED', bold=True, font_size='22sp',
            color=_PAUSED_COL,
            size_hint=(1, None), height=42,
            halign='center', valign='middle',
        ))

        # Stats
        self._stats = Label(
            text='', font_size='11sp',
            color=(235/255, 235/255, 235/255, 1),
            size_hint=(1, None), height=72,
            halign='left', valign='top',
        )
        self._stats.bind(size=self._stats.setter('text_size'))
        panel.add_widget(self._stats)

        # Buttons (all same colour — QColor(32,32,40,235))
        for key, lbl in [
            ('resume',    'Resume'),
            ('levels',    'Levels'),
            ('save',      'Save Game'),
            ('save_exit', 'Save + Exit'),
            ('restart',   'Restart'),
            ('exit',      'Exit (No Save)'),
        ]:
            b = _make_btn(lbl, lambda k=key: gw._on_pause_action(k),
                          size_hint=(1, None), height=48)
            panel.add_widget(b)

        self.add_widget(panel)
        Clock.schedule_interval(self._upd_stats, 1.0)

    def _draw_panel_border(self, panel):
        panel.canvas.after.clear()
        with panel.canvas.after:
            Color(*_BORDER)
            Line(rectangle=(panel.x, panel.y, panel.width, panel.height), width=1)

    def on_touch_down(self, touch):
        return False if self.opacity == 0 else super().on_touch_down(touch)

    def _upd_stats(self, *_):
        if self.opacity == 0:
            return
        p = getattr(self._gw, '_perf', None)
        fps = p.stable_fps(update_interval_s=2.5) if p else 0
        lat = p.avg_input_latency_ms() if p else 0.0
        ram = p.current_ram_mb() if p else 0.0
        self._stats.text = (
            f'FPS: {int(fps)}\n'
            f'Avg input latency: {lat:.1f} ms\n'
            f'RAM usage: {ram:.1f} MB'
        )


# ─────────────────────────────────────────────────────────────────────────────
# Level-select panel — exact PySide6 parity
# ─────────────────────────────────────────────────────────────────────────────

class _LevelSelectPanel(FloatLayout):
    """Level selection — full-screen black overlay with centred BoxLayout stack."""

    def __init__(self, gw, **kwargs):
        super().__init__(**kwargs)
        self.allow_close     = False
        self.return_to_pause = False
        self._gw = gw

        # Full black background
        with self.canvas.before:
            Color(*_BLACK)
            self._bg = Rectangle(size=self.size, pos=self.pos)
        self.bind(
            size=lambda w, v: (setattr(self._bg, 'size', v),
                               setattr(self._bg, 'pos', w.pos)),
            pos=lambda w, v: setattr(self._bg, 'pos', v),
        )

        # ── Centred column (BoxLayout does all the layout work) ──
        col = BoxLayout(
            orientation='vertical',
            spacing=22,
            padding=(0, 0, 0, 0),
            size_hint=(None, None),
            width=620,
            height=340,          # 48+24+82+82+gap+gap ≈ 340
            pos_hint={'center_x': .5, 'center_y': .52},
        )

        # Title
        self._title_lbl = Label(
            text='SELECT LEVEL', bold=True, font_size='28sp',
            color=(240/255, 240/255, 240/255, 1),
            size_hint=(1, None), height=52,
            halign='center', valign='middle',
        )
        self._title_lbl.bind(size=self._title_lbl.setter('text_size'))
        col.add_widget(self._title_lbl)

        # Subtitle
        self._sub_lbl = Label(
            text=('Level 2 is locked until you complete Level 1.\n'
                  'Entering a level always starts fresh.'),
            font_size='13sp',
            color=(200/255, 200/255, 200/255, 1),
            size_hint=(1, None), height=40,
            halign='center', valign='middle',
        )
        self._sub_lbl.bind(size=self._sub_lbl.setter('text_size'))
        col.add_widget(self._sub_lbl)

        # Level 1 button
        self._l1_btn = Button(
            text='Level 1', font_size='18sp', bold=True,
            background_normal='',
            background_color=(22/255, 22/255, 26/255, 1),
            color=(240/255, 240/255, 240/255, 1),
            size_hint=(1, None), height=82,
        )
        self._l1_btn.bind(on_press=lambda *_: gw._on_level_selected('level1'))
        self._l1_btn.bind(pos=self._draw_btn_border,
                          size=self._draw_btn_border)
        col.add_widget(self._l1_btn)

        # Level 2 button
        self._l2_btn = Button(
            text='Level 2 (Locked)', font_size='18sp', bold=True,
            background_normal='',
            background_color=(22/255, 22/255, 26/255, 190/255),
            color=(140/255, 140/255, 140/255, 1),
            disabled=True,
            size_hint=(1, None), height=82,
        )
        self._l2_btn.bind(on_press=lambda *_: gw._on_level_selected('level2'))
        self._l2_btn.bind(pos=self._draw_btn_border,
                          size=self._draw_btn_border)
        col.add_widget(self._l2_btn)

        self.add_widget(col)

        # Close ✕ button (top-right corner of window, hidden until allow_close)
        self._close_btn = Button(
            text='',
            background_normal='', background_color=(0, 0, 0, 0),
            size_hint=(None, None), size=(38, 38),
            pos_hint={'right': 0.99, 'top': 0.99},
            opacity=0,
        )
        self._close_btn.bind(on_press=lambda *_: gw._on_modal_close_clicked())
        self._close_btn.bind(pos=self._draw_close_btn,
                             size=self._draw_close_btn)
        self.add_widget(self._close_btn)

    # ── border helpers ─────────────────────────────────────────────────────

    def _draw_btn_border(self, btn, *_):
        btn.canvas.after.clear()
        col = _BORDER if not btn.disabled else (120/255, 120/255, 120/255, 1)
        with btn.canvas.after:
            Color(*col)
            Line(rectangle=(btn.x, btn.y, btn.width, btn.height), width=1)

    def _draw_close_btn(self, btn, *_):
        btn.canvas.after.clear()
        if not self.allow_close:
            return
        x, y, s = btn.x, btn.y, btn.width
        with btn.canvas.after:
            Color(220/255, 220/255, 220/255, 1)
            Line(rectangle=(x, y, s, s), width=1)
            Line(points=[x + 9, y + 9, x + s - 9, y + s - 9], width=1.5)
            Line(points=[x + s - 9, y + 9, x + 9, y + s - 9], width=1.5)

    # ── touch guard ────────────────────────────────────────────────────────

    def on_touch_down(self, touch):
        return False if self.opacity == 0 else super().on_touch_down(touch)

    # ── public API ─────────────────────────────────────────────────────────

    def set_unlocked(self, unlocked):
        lvl2 = 'level2' in set(unlocked or {'level1'})
        self._l2_btn.disabled       = not lvl2
        self._l2_btn.text           = 'Level 2' if lvl2 else 'Level 2 (Locked)'
        self._l2_btn.color          = ((240/255, 240/255, 240/255, 1) if lvl2
                                       else (140/255, 140/255, 140/255, 1))
        self._close_btn.opacity     = 1.0 if self.allow_close else 0.0
        self._draw_btn_border(self._l2_btn)
        self._draw_close_btn(self._close_btn)


# ─────────────────────────────────────────────────────────────────────────────
# Tutorial modal — exact PySide6 parity
# panel min(840,w*0.74) × min(440,h*0.56), X close button (no OK button)
# ─────────────────────────────────────────────────────────────────────────────

class _TutorialPanel(FloatLayout):
    """Tutorial panel — dark overlay + centred BoxLayout panel with X button."""

    def __init__(self, gw, **kwargs):
        super().__init__(**kwargs)
        self._gw = gw

        with self.canvas.before:
            Color(*_OVERLAY)
            self._bg = Rectangle(size=self.size, pos=self.pos)
        self.bind(
            size=lambda w, v: (setattr(self._bg, 'size', v),
                               setattr(self._bg, 'pos', w.pos)),
            pos=lambda w, v: setattr(self._bg, 'pos', v),
        )

        # Outer stack: positions the panel in the centre of the screen
        # We use a single BoxLayout(vertical) that contains:
        #   row1: title + X button (side by side)
        #   row2: body text (expands)
        panel = BoxLayout(
            orientation='vertical',
            spacing=12,
            padding=24,
            size_hint=(0.74, 0.56),
            pos_hint={'center_x': .5, 'center_y': .5},
        )
        with panel.canvas.before:
            Color(18/255, 18/255, 22/255, 245/255)
            self._pbg = Rectangle(pos=panel.pos, size=panel.size)
        panel.bind(
            pos =lambda w, v: (setattr(self._pbg, 'pos', v),
                               self._draw_panel_border(w)),
            size=lambda w, v: (setattr(self._pbg, 'size', v),
                               self._draw_panel_border(w)),
        )

        # Title row: title label + X button
        title_row = BoxLayout(
            orientation='horizontal',
            size_hint=(1, None), height=36,
            spacing=8,
        )
        self._title_lbl = Label(
            text='', bold=True, font_size='18sp',
            color=(235/255, 235/255, 235/255, 1),
            halign='left', valign='middle',
        )
        self._title_lbl.bind(size=self._title_lbl.setter('text_size'))
        title_row.add_widget(self._title_lbl)

        close_btn = Button(
            text='✕', font_size='16sp',
            size_hint=(None, 1), width=36,
            background_normal='', background_color=(0.35, 0.35, 0.38, 1),
            color=(220/255, 220/255, 220/255, 1),
        )
        close_btn.bind(on_press=lambda *_: gw._on_modal_close_clicked())
        title_row.add_widget(close_btn)
        panel.add_widget(title_row)

        # Separator line
        sep = Widget(size_hint=(1, None), height=1)
        with sep.canvas:
            Color(235/255, 235/255, 235/255, 0.4)
            self._sep_line = Rectangle(pos=sep.pos, size=sep.size)
        sep.bind(pos=lambda w,v: setattr(self._sep_line,'pos',v),
                 size=lambda w,v: setattr(self._sep_line,'size',v))
        panel.add_widget(sep)

        # Body text
        self._body_lbl = Label(
            text='', font_size='14sp',
            color=(220/255, 220/255, 220/255, 1),
            halign='left', valign='top',
        )
        self._body_lbl.bind(size=self._body_lbl.setter('text_size'))
        panel.add_widget(self._body_lbl)

        self.add_widget(panel)

    def _draw_panel_border(self, panel):
        panel.canvas.after.clear()
        with panel.canvas.after:
            Color(235/255, 235/255, 235/255, 1)
            Line(rectangle=(panel.x, panel.y, panel.width, panel.height), width=1)

    def on_touch_down(self, touch):
        return False if self.opacity == 0 else super().on_touch_down(touch)

    def set_content(self, title, body):
        self._title_lbl.text = title
        self._body_lbl.text  = body


# ─────────────────────────────────────────────────────────────────────────────
# End screen
# ─────────────────────────────────────────────────────────────────────────────

class _EndPanel(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(0,0,0,1)
            self._bg = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=lambda w,v:(setattr(self._bg,'size',v),
                                   setattr(self._bg,'pos',w.pos)),
                  pos =lambda w,v: setattr(self._bg,'pos',v))
        self._lbl = Label(text='', font_size='28sp', markup=True,
                          size_hint=(1,1), halign='center', valign='middle')
        self._lbl.bind(size=self._lbl.setter('text_size'))
        self.add_widget(self._lbl)

    def on_touch_down(self, touch):
        return False if self.opacity == 0 else super().on_touch_down(touch)

    def update(self, core):
        if getattr(core,'game_completed',False) or core.screen_close_progress >= 1.0:
            t = core.elapsed_s
            self._lbl.text = (
                f'[b]CONGRATULATIONS![/b]\n\n'
                f'Time: {t:.1f}s\n'
                f'Coins: {core.coins_collected}/{core.coins_required}   '
                f'Keys: {core.keys_collected}/{core.keys_required}\n\n'
                f'[size=15sp][color=aaaaaa]Press ESC to return to level select[/color][/size]'
            )


class _StatsScreenPanel(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(0, 0, 0, 1)
            self._bg = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=lambda w, v: (setattr(self._bg, 'size', v), setattr(self._bg, 'pos', w.pos)),
                  pos=lambda w, v: setattr(self._bg, 'pos', v))
        self._text = ''
        self._end_mode = False

    def set_text(self, text: str, *, end_mode: bool = False) -> None:
        self._text = str(text or '')
        self._end_mode = bool(end_mode)
        self._apply_text()

    def _apply_text(self) -> None:
        text = str(self._text or '')
        lines = [ln.rstrip() for ln in text.split('\n')]
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        self.clear_widgets()
        if not lines:
            return

        # wxPython logic: usable_h = h - 80; ideal_line_h=26; clamp line_h to 14..26
        try:
            h = float(self.height or 1.0)
            usable_h = max(1.0, h - 80.0)
            ideal_line_h = 26.0
            line_h = min(ideal_line_h, max(14.0, usable_h / max(1.0, float(len(lines)))))
            fs_body = int(max(10.0, min(14.0, line_h - 4.0)))
            fs_header = fs_body + 1
        except Exception:
            line_h = 22.0
            fs_body = 12
            fs_header = 13

        # Layout positions - compute y from top, then flip for Kivy coordinates
        try:
            w = float(self.width or 1.0)
            h = float(self.height or 1.0)
            total_h = float(len(lines)) * float(line_h)
            start_y_wx = max(36.0, (h - total_h - 50.0) / 2.0)
        except Exception:
            w = float(self.width or 1.0)
            h = float(self.height or 1.0)
            start_y_wx = 36.0

        # Colors
        if self._end_mode:
            col_sep = (100/255, 100/255, 100/255, 200/255)
            col_hdr = (255/255, 210/255, 60/255, 1)
            col_txt = (210/255, 210/255, 210/255, 1)
            hint_col = (150/255, 150/255, 150/255, 1)
            hint_fs = 14
        else:
            col_sep = (100/255, 100/255, 100/255, 200/255)
            col_hdr = (255/255, 220/255, 80/255, 1)
            col_txt = (230/255, 230/255, 230/255, 1)
            hint_col = (160/255, 160/255, 160/255, 1)
            hint_fs = 13

        for i, ln in enumerate(lines):
            is_sep = str(ln).startswith('─')
            is_header = (str(ln).isupper() and len(str(ln)) > 2 and (not str(ln).startswith('•')) and (not is_sep))
            if is_sep:
                color = col_sep
                fs = fs_body
                bold = False
            elif is_header:
                color = col_hdr
                fs = fs_header
                bold = True
            else:
                color = col_txt
                fs = fs_body
                bold = False
            # Convert wx y-down into Kivy y-up.
            y_wx = float(start_y_wx + i * float(line_h))
            y_kivy = float(h - y_wx - float(line_h))
            lbl = Label(text=str(ln), font_size=f'{fs}sp', bold=bold,
                        size_hint=(None, None), size=(w, float(line_h)),
                        pos=(0.0, y_kivy),
                        halign='center', valign='middle', color=color)
            lbl.bind(size=lbl.setter('text_size'))
            self.add_widget(lbl)

        hint = Label(text='Press ESC to continue', font_size=f'{hint_fs}sp',
                     size_hint=(None, None), size=(w, 30.0),
                     pos=(0.0, 16.0),
                     halign='center', valign='middle', color=hint_col)
        hint.bind(size=hint.setter('text_size'))
        self.add_widget(hint)

    def on_touch_down(self, touch):
        # Swallow all touches while visible.
        return True if self.opacity > 0 else super().on_touch_down(touch)


class _TheEndPanel(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(0, 0, 0, 1)
            self._bg = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=lambda w, v: (setattr(self._bg, 'size', v), setattr(self._bg, 'pos', w.pos)),
                  pos=lambda w, v: setattr(self._bg, 'pos', w.pos))
        self._lbl = Label(text='THE END', font_size='68sp', bold=True,
                          size_hint=(1, 1), halign='center', valign='middle',
                          color=(1, 1, 1, 1))
        self._lbl.bind(size=self._lbl.setter('text_size'))
        self.add_widget(self._lbl)


# ─────────────────────────────────────────────────────────────────────────────
# HUD overlay (objective bar + lore + sector popup + all panels)
# ─────────────────────────────────────────────────────────────────────────────

class _HUDOverlay(FloatLayout):
    def __init__(self, gw, **kwargs):
        super().__init__(**kwargs)
        self._gw  = gw
        self.core = None

        # ── Objective bar: 320×56, black bg + border, two text rows ────────────
        self._bonus_until = 0.0
        self._obj_bar = BoxLayout(
            orientation='vertical',
            size_hint=(None, None), size=(320, 56),
            pos_hint={'center_x': .5, 'top': 1.0},
            padding=(12, 4, 12, 4),
            spacing=0,
        )
        with self._obj_bar.canvas.before:
            Color(0, 0, 0, 160/255)
            self._obj_bg = Rectangle(pos=self._obj_bar.pos,
                                     size=self._obj_bar.size)
        def _upd_obj_bar_bg(w, v=None):
            self._obj_bg.pos  = w.pos
            self._obj_bg.size = w.size
            w.canvas.after.clear()
            with w.canvas.after:
                Color(*_BORDER)
                Line(rectangle=(w.x, w.y, w.width, w.height), width=1)
        self._obj_bar.bind(pos=_upd_obj_bar_bg, size=_upd_obj_bar_bg)

        # Row 1: time + bonus
        row1 = BoxLayout(orientation='horizontal', size_hint=(1, None), height=26)
        self._time_lbl = Label(
            text='Time: 00:00', bold=True, font_size='12sp',
            color=(240/255, 240/255, 240/255, 1),
            halign='left', valign='middle',
        )
        self._time_lbl.bind(size=self._time_lbl.setter('text_size'))
        self._bonus_lbl = Label(
            text='', font_size='14sp', markup=True,
            color=(1, 220/255, 60/255, 1),
            size_hint_x=None, width=90,
            halign='left', valign='middle',
        )
        self._bonus_lbl.bind(size=self._bonus_lbl.setter('text_size'))
        row1.add_widget(self._time_lbl)
        row1.add_widget(self._bonus_lbl)
        self._obj_bar.add_widget(row1)

        # Row 2: coins + keys
        self._coins_lbl = Label(
            text='Coins: 0/0   Keys: 0/0', font_size='11sp',
            color=(240/255, 240/255, 240/255, 1),
            size_hint=(1, None), height=22,
            halign='left', valign='middle',
        )
        self._coins_lbl.bind(size=self._coins_lbl.setter('text_size'))
        self._obj_bar.add_widget(self._coins_lbl)
        self.add_widget(self._obj_bar)

        # ── Minimap cam icon (bottom-right) ────────────────────────────────────
        self._map_btn = _CamIconWidget(
            size_hint=(None,None), size=(54,54),
            pos_hint={'right':1.0, 'y':0.0},
        )
        self._map_btn.bind(on_press=lambda *_: gw._try_open_minimap())
        self.add_widget(self._map_btn)

        # ── Minimap overlay ────────────────────────────────────────────────────
        self._minimap = _MinimapWidget(size_hint=(1,1), opacity=0)
        self.add_widget(self._minimap)

        # ── Lore text ──────────────────────────────────────────────────────────
        self._lore_lbl = Label(
            text='', font_size='18sp', markup=True,
            size_hint=(.7,None), height=40,
            pos_hint={'center_x':.5,'center_y':.44},
            halign='center', valign='middle', opacity=0,
        )
        self._lore_lbl.bind(size=self._lore_lbl.setter('text_size'))
        self.add_widget(self._lore_lbl)
        self._lore_queue  = []
        self._lore_cur    = ''
        self._lore_start  = 0.0
        self._lore_end    = 0.0

        # ── Sector popup ───────────────────────────────────────────────────────
        self._sector_lbl = Label(
            text='', font_size='15sp', markup=True,
            size_hint=(None,None), size=(240,36),
            pos_hint={'center_x':.5,'y':.03},
            halign='center', valign='middle', opacity=0,
        )
        self._sector_lbl.bind(size=self._sector_lbl.setter('text_size'))
        self.add_widget(self._sector_lbl)

        # ── Panels (pause/level-select/tutorial/end) ───────────────────────────
        self._pause  = _PausePanel(gw, size_hint=(1,1), opacity=0)
        self._levels = _LevelSelectPanel(gw, size_hint=(1,1), opacity=0)
        self._tut    = _TutorialPanel(gw, size_hint=(1,1), opacity=0)
        self._end    = _EndPanel(size_hint=(1,1), opacity=0)
        self._stats  = _StatsScreenPanel(size_hint=(1,1), opacity=0)
        self._the_end = _TheEndPanel(size_hint=(1,1), opacity=0)
        for p in (self._pause, self._levels, self._tut, self._end, self._stats, self._the_end):
            self.add_widget(p)

        Clock.schedule_interval(self._tick, 1/30.)

    # ── tick ──────────────────────────────────────────────────────────────────
    def _tick(self, dt):
        if not self.core: return
        self._upd_obj()
        self._upd_lore()
        self._upd_sector()
        self._upd_minimap()
        self._upd_end()

    def _upd_obj(self):
        t = int(self.core.elapsed_s)
        self._time_lbl.text  = f'Time: {t//60:02d}:{t%60:02d}'
        self._coins_lbl.text = (f'Coins: {self.core.coins_collected}/'
                                f'{self.core.coins_required}   '
                                f'Keys: {self.core.keys_collected}/'
                                f'{self.core.keys_required}')
        if not (self._bonus_until and time.perf_counter() < self._bonus_until):
            self._bonus_lbl.text = ''

    def _upd_lore(self):
        if not self._lore_cur and self._lore_queue:
            now = time.perf_counter()
            self._lore_cur   = self._lore_queue.pop(0)
            self._lore_start = now
            self._lore_end   = now + 2.8
        if not self._lore_cur:
            self._lore_lbl.opacity = 0; return
        now = time.perf_counter()
        if now >= self._lore_end:
            self._lore_cur = ''; self._lore_lbl.opacity = 0; return
        dur = max(0.01, self._lore_end - self._lore_start)
        t   = (now - self._lore_start) / dur
        fade = 0.18
        a = t/fade if t < fade else (1-t)/fade if t > 1-fade else 1.0
        self._lore_lbl.opacity = max(0, min(1, a))
        self._lore_lbl.text = f'[color=ffffff]{self._lore_cur}[/color]'

    def _upd_sector(self):
        pt  = float(getattr(self.core,'_sector_popup_timer',0) or 0)
        pid = str(getattr(self.core,'_sector_popup_id','') or '')
        if pt <= 0 or not pid:
            self._sector_lbl.opacity = 0; return
        total=2.0; fi=0.25; fo=0.5
        a = (total-pt)/fi if pt > total-fi else pt/fo if pt < fo else 1.0
        self._sector_lbl.opacity = max(0,min(1,a))
        self._sector_lbl.text = f'[b][color=ffd700]SECTOR {pid}[/color][/b]'

    def _upd_minimap(self):
        now    = time.perf_counter()
        active = now < self._minimap._until
        if active:
            self._minimap.opacity = 1.0
            self._minimap.core = self.core
            self._minimap.redraw()
        else:
            self._minimap.opacity = 0.0

    def _upd_end(self):
        gw = getattr(self, '_gw', None)
        stats_visible = bool(getattr(gw, '_stats_visible', False)) if gw else False
        show_the_end = bool(getattr(gw, '_show_the_end', False)) if gw else False

        self._stats.opacity = 1.0 if stats_visible else 0.0
        self._the_end.opacity = 1.0 if show_the_end else 0.0

        # wxPython parity: never show the legacy end panel. Level end uses
        # closing animation -> stats overlay -> THE END.
        self._end.opacity = 0.0

    # ── public API ─────────────────────────────────────────────────────────────
    def enqueue_lore_lines(self, lines):
        for ln in (lines or []):
            s = str(ln or '').strip()
            if s: self._lore_queue.append(s)

    def is_lore_playing(self):
        return bool(self._lore_cur or self._lore_queue)

    def show_level_select_modal(self, *, unlocked, allow_close, return_to_pause):
        self._levels.set_unlocked(unlocked)
        self._levels.allow_close     = allow_close
        self._levels.return_to_pause = return_to_pause
        self._levels.opacity = 1.0
        self._tut.opacity    = 0.0
        self._pause.opacity  = 0.0

    def hide_modal(self):
        self._levels.opacity = 0.0
        self._tut.opacity    = 0.0

    def show_tutorial_modal(self, *, title, body):
        self._tut.set_content(title, body)
        self._tut.opacity    = 1.0
        self._levels.opacity = 0.0

    @property
    def _modal_visible(self):
        return self._levels.opacity > 0 or self._tut.opacity > 0

    @property
    def _modal_kind(self):
        if self._levels.opacity > 0: return 'level_select'
        if self._tut.opacity    > 0: return 'tutorial'
        return ''

    @property
    def _modal_allow_close(self):
        if self._levels.opacity > 0: return self._levels.allow_close
        return True

    @property
    def _modal_return_to_pause(self):
        if self._levels.opacity > 0: return self._levels.return_to_pause
        return False

    def show_pause(self):  self._pause.opacity = 1.0
    def hide_pause(self):  self._pause.opacity = 0.0

    def set_time_bonus(self, text, dur=2.5):
        self._bonus_lbl.text  = f'[b][color=ffdc3c]{text}[/color][/b]'
        self._bonus_until     = time.perf_counter() + dur

    def open_minimap(self, secs=10.0):
        self._minimap._until = time.perf_counter() + secs


# ─────────────────────────────────────────────────────────────────────────────
# Main game window
# ─────────────────────────────────────────────────────────────────────────────

class KivyGameWindow(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._progress_path = os.path.abspath('progression_kivy.json')
        self._progress      = self._load_progression()
        unlocked   = set(self._progress.get('unlocked_levels') or ['level1'])
        last_level = str(self._progress.get('last_level') or 'level1')
        if last_level not in unlocked: last_level = 'level1'

        self._save_path        = os.path.abspath('savegame_kivy.json')
        self._current_level_id = last_level
        self.core = GameCore(level_id=last_level)

        # GL widget (bottom layer)
        self._gl = _GameGLWidget(KivyRenderer(self.core), size_hint=(1,1), pos=(0,0))
        self.add_widget(self._gl)

        # HUD (middle layer)
        self._hud = _HUDOverlay(self, size_hint=(1,1), pos=(0,0))
        self._hud.core = self.core
        self.add_widget(self._hud)

        # Closing animation overlay (above HUD)
        self._closing_anim = _ClosingAnimWidget(self, size_hint=(1, 1), pos=(0, 0))
        self.add_widget(self._closing_anim)

        # Vignette (top layer - renders on top of everything)
        self._vignette = _VignetteWidget(size_hint=(1,1), pos=(0,0))
        self.add_widget(self._vignette)

        self._perf = PerformanceMonitor(framework='Kivy')
        self._gl.performance_monitor = self._perf
        
        # Connect performance monitor to game core for tracking
        self.core._performance_monitor = self._perf
        self._perf._game_start_time = time.perf_counter()

        self._audio = _KivyAudioEngine(asset_dir=os.path.abspath('assets'))
        self._ghost_sfx_ev = Clock.schedule_interval(self._tick_ghost_sfx, 2.5)

        # Stats / end-screen state (wxPython parity)
        self._level_end_triggered: bool = False
        self._level_complete: bool = False
        self._stats_visible: bool = False
        self._stats_text: str = ''
        self._perf_pdf_exported: bool = False
        self._show_the_end: bool = False
        self._end_screen_visible: bool = False

        self.keys_pressed:     Set[str] = set()
        self._mouse_captured:   bool = False
        self._last_mouse_pos:   tuple[float, float] | None = None
        self._lore_seen:       dict = {}
        self._lore_flags:      dict = {}
        self._persist_seen:    dict = {}
        self._pending_tutorial = False
        self._key_mini_open    = False
        self._assembly_mini:   Optional[KivyAssembly3DMinigame] = None
        self._last_update_t    = time.perf_counter()

        self._register_core_callbacks()

        self._kb = Window.request_keyboard(self._kb_closed, self)
        self._kb.bind(on_key_down=self._on_key_down, on_key_up=self._on_key_up)
        Window.bind(on_keyboard=self._on_win_kb)
        Window.bind(mouse_pos=self._on_mouse_pos)
        Window.bind(on_touch_down=self._on_touch_down)
        Window.bind(on_touch_up=self._on_touch_up)

        Clock.schedule_interval(self._update, 1/60.)

        autoload = last_level == 'level1' and os.path.exists(self._save_path)
        if last_level == 'level2':
            self._set_paused(False)
            Clock.schedule_once(
                lambda *_: self._start_level('level2',
                    load_save=os.path.exists(self._save_path)), 0.1)
        elif autoload:
            self._set_paused(False)
            Clock.schedule_once(
                lambda *_: self._start_level('level1', load_save=True), 0.1)
        else:
            Clock.schedule_once(
                lambda *_: self._open_level_select(startup=True), 0.1)

    # ── keyboard ──────────────────────────────────────────────────────────────

    def _kb_closed(self):
        if self._kb:
            self._kb.unbind(on_key_down=self._on_key_down,
                            on_key_up=self._on_key_up)
        self._kb = None

    def _on_key_down(self, kb, keycode, text, mod):
        key = keycode[1]
        if bool(getattr(self, '_stats_visible', False)):
            if key in ('escape', 'esc'):
                self._on_stats_screen_esc()
            return True
        if bool(getattr(self, '_show_the_end', False)):
            return True
        self.keys_pressed.add(key)
        try:
            if key in ('w', 'a', 's', 'd'):
                self._perf.record_input_event(time.perf_counter())
        except Exception:
            pass
        if key == 'e':
            self._handle_interact(); return True
        if key == 'm':
            self._try_open_minimap(); return True
        return False

    def _on_win_kb(self, window, key, *args):
        if key == 27:   # ESC
            if self._hud._modal_visible:
                self._on_modal_close_clicked()
            elif bool(getattr(self, '_stats_visible', False)):
                self._on_stats_screen_esc()
            elif bool(getattr(self, '_show_the_end', False)):
                return True
            else:
                self._toggle_pause()
            return True
        return False

    def _on_key_up(self, kb, keycode):
        self.keys_pressed.discard(keycode[1])

    # ── touch ─────────────────────────────────────────────────────────────────

    def _on_touch_down(self, win, touch):
        if not hasattr(touch,'button') or touch.button != 'left': return
        if self._hud._modal_visible: return
        if bool(getattr(self, '_stats_visible', False)) or bool(getattr(self, '_show_the_end', False)):
            return
        if getattr(self.core,'paused',False): return
        if getattr(self.core, 'simulation_frozen', False): return
        self._mouse_captured = True
        
        # Hide cursor like PySide6
        try:
            Window.set_system_cursor('none')
        except Exception:
            pass
        
        self._last_mouse_pos = touch.pos

    def _on_touch_up(self, win, touch):
        if hasattr(touch,'button') and touch.button == 'left':
            self._mouse_captured = False
            self._mouse_center = None
            try:
                Window.set_system_cursor('arrow')
            except Exception:
                pass

    def _on_mouse_pos(self, win, pos):
        # Only process camera movement if mouse is captured (left click held)
        if not self._mouse_captured:
            self._last_mouse_pos = pos
            return
        
        if getattr(self.core,'paused',False) or self._hud._modal_visible: return
        if bool(getattr(self, '_stats_visible', False)) or bool(getattr(self, '_show_the_end', False)):
            self._mouse_captured = False
            self._last_mouse_pos = pos
            return
        if getattr(self.core, 'simulation_frozen', False):
            self._mouse_captured = False
            self._last_mouse_pos = pos
            return
        
        if self._last_mouse_pos is None:
            self._last_mouse_pos = pos
            return

        # Calculate delta and apply camera rotation (PySide6 style)
        dx = pos[0] - self._last_mouse_pos[0]
        dy = pos[1] - self._last_mouse_pos[1]
        
        sensitivity = 0.002
        if abs(dx) > 1 or abs(dy) > 1:
            self.core.rotate_player(-dx * sensitivity)
            self.core.tilt_camera(-dy * sensitivity)
        
        self._last_mouse_pos = pos

    # ── update ────────────────────────────────────────────────────────────────

    def _update(self, *_):
        now = time.perf_counter()
        dt  = min(now - self._last_update_t, 0.1)
        self._last_update_t = now
        paused = bool(getattr(self.core,'paused',False))

        # While stats/the-end are visible, the game is frozen. Still allow screen-close animation
        # to complete so core.game_won gets set (parity with wx: game_won already true).
        if bool(getattr(self, '_stats_visible', False)) or bool(getattr(self, '_show_the_end', False)):
            if self.core.screen_closing and not self.core.game_won:
                self.core._update_screen_close(dt)
            return
        if self.core.screen_closing and not self.core.game_won:
            self.core._update_screen_close(dt)
        elif not paused:
            self.core.update(dt)

        # Level-end: game_won fires once per level — freeze, show stats/end (wxPython parity)
        try:
            game_won = bool(getattr(self.core, 'game_won', False))
            if game_won and (not bool(getattr(self, '_level_end_triggered', False))):
                self._level_end_triggered = True
                self._handle_level_end()
                return
        except Exception:
            pass
        if not paused and not self._hud._modal_visible:
            self._poll_lore()
        if (self._pending_tutorial and not self._hud._modal_visible
                and not self._hud.is_lore_playing()):
            self._pending_tutorial = False
            if (self._current_level_id == 'level1'
                    and not self._persist_seen.get('tutorial_gameplay')):
                self._persist_seen['tutorial_gameplay'] = True
                self._show_tutorial(
                    'Gameplay',
                    'Press WASD to move.\n'
                    'Hold Left Mouse Button to look around.\n'
                    'Press ESC to pause. Save and exit from the pause menu.\n\n'
                    'Press M or click the camera icon to open the minimap.\n'
                    'The minimap stays open for 10 seconds, then goes on a 20 second cooldown.\n\n'
                    'Collect all coins and key fragments to unlock the exit.\n'
                    'Avoid hazards. If you get caught, you will be sent to jail.'
                )
        moved = False
        if not paused and not getattr(self.core, 'simulation_frozen', False):
            spd = 0.18 if self._current_level_id == 'level1' else 0.30
            dx = dz = 0.0
            if 'w' in self.keys_pressed: dz += spd
            if 's' in self.keys_pressed: dz -= spd
            if 'a' in self.keys_pressed: dx -= spd
            if 'd' in self.keys_pressed: dx += spd
            if dx or dz:
                try:
                    moved = bool(self.core.move_player(dx, dz))
                except Exception:
                    moved = False
        try:
            if paused or self._hud._modal_visible or getattr(self.core, 'simulation_frozen', False):
                self._audio.set_footsteps(False)
            else:
                self._audio.set_footsteps(moved)
        except Exception:
            pass
        self._perf.update_scene_data(
            walls_rendered=len(self.core.walls), coins=len(self.core.coins),
            ghosts=len(self.core.ghosts), spike_traps=len(self.core.spikes),
            moving_platforms=len(self.core.platforms))

    def _tick_ghost_sfx(self, *_):
        try:
            if getattr(self.core, 'paused', False):
                return
            if getattr(self.core, 'game_won', False) or getattr(self.core, 'game_completed', False):
                return
            ghosts = getattr(self.core, 'ghosts', None)
            if not ghosts:
                return
            px = float(self.core.player.x)
            pz = float(self.core.player.z)
            nearest = None
            for g in ghosts.values():
                d = math.hypot(float(g.x) - px, float(g.z) - pz)
                if nearest is None or d < nearest:
                    nearest = d
            if nearest is None:
                return
            hear_dist = 10.0
            near_dist = 2.5
            if nearest > hear_dist:
                return
            if nearest <= near_dist:
                t = 1.0
            else:
                t = max(0.0, min(1.0, (hear_dist - nearest) / (hear_dist - near_dist)))
            self._audio.play_ghost(volume=(0.06 + 0.55 * t))
        except Exception:
            return

    # ── pause ─────────────────────────────────────────────────────────────────

    def _set_paused(self, v):
        self.core.paused = bool(v)
        if v:
            self.keys_pressed.clear(); self._mouse_captured = False
            self._hud.show_pause()
        else:
            self._hud.hide_pause()

    def _toggle_pause(self):
        if self.core.screen_closing or self.core.game_completed or self.core.game_won:
            return
        self._set_paused(not bool(self.core.paused))

    def _on_pause_action(self, action):
        if action == 'resume':    self._toggle_pause()
        elif action == 'levels':  self._set_paused(False); self._open_level_select(startup=False)
        elif action == 'save':    self._save_game()
        elif action == 'save_exit': self._save_game(); App.get_running_app().stop()
        elif action == 'exit':    App.get_running_app().stop()
        elif action == 'restart': self._restart()

    # ── modals ────────────────────────────────────────────────────────────────

    def _open_level_select(self, *, startup):
        un = set(self._progress.get('unlocked_levels') or ['level1'])
        self.core.paused = True
        self.keys_pressed.clear(); self._mouse_captured = False
        self._hud.hide_pause()
        self._hud.show_level_select_modal(
            unlocked=un, allow_close=(not startup),
            return_to_pause=(not startup))

    def _on_level_selected(self, lid):
        self._hud.hide_modal()
        self._set_paused(False)
        self._progress['last_level'] = str(lid)
        self._save_progression()
        self._start_level(lid, load_save=False)

    def _on_modal_close_clicked(self):
        if not self._hud._modal_visible: return
        if not self._hud._modal_allow_close: return
        if (self._hud._modal_kind == 'level_select'
                and self._hud._modal_return_to_pause):
            self._hud.hide_modal(); self._set_paused(True); return
        self._hud.hide_modal(); self._set_paused(False)

    def _show_tutorial(self, title, body):
        # Freeze movement without showing the pause panel
        self.core.paused = True
        self.keys_pressed.clear()
        self._mouse_captured = False
        self._hud.hide_pause()   # ensure pause panel is hidden
        self._hud.show_tutorial_modal(title=title, body=body)

    def _show_lore(self, text):
        s = str(text or '').strip()
        if s: self._hud.enqueue_lore_lines([s])

    # ── minimap ───────────────────────────────────────────────────────────────

    def _try_open_minimap(self):
        now = time.perf_counter()
        if now < self._hud._map_btn._cooldown_until: return
        self._hud.open_minimap(10.0)
        self._hud._map_btn._cooldown_until = now + 30.0

    # ── levels ────────────────────────────────────────────────────────────────

    def _start_level(self, lid, *, load_save):
        lid = str(lid or 'level1')
        self.core = GameCore(level_id=lid)
        self._current_level_id = lid
        self._gl.renderer = KivyRenderer(self.core)
        self._hud.core = self.core
        
        # Reconnect performance monitor to new game core
        self.core._performance_monitor = self._perf
        self._perf._game_start_time = time.perf_counter()

        # Reset level-end state (wxPython parity)
        self._level_end_triggered = False
        self._level_complete = False
        self._stats_visible = False
        self._stats_text = ''
        self._perf_pdf_exported = False
        self._show_the_end = False
        self._end_screen_visible = False
        try:
            self._hud._stats.set_text('')
        except Exception:
            pass
        for k in ('coins_half','ghost_close','l2_frags_done','l2_sector_f_done'):
            self._lore_flags.pop(k,None)
        self.keys_pressed.clear()
        self._register_core_callbacks()
        self._last_update_t = time.perf_counter()
        if load_save: self._load_save()

        # Play gate sound on fresh start only (PySide6 parity: timer at 00:00).
        try:
            if (not load_save) and float(getattr(self.core, 'elapsed_s', 0.0) or 0.0) <= 0.0001:
                self._audio.play_gate()
        except Exception:
            pass
        if lid == 'level1' and not load_save:
            if float(getattr(self.core,'elapsed_s',0)) <= 0.0001:
                if not self._persist_seen.get('l1_intro'):
                    self._persist_seen['l1_intro'] = True
                    self._show_lore('A basement? This feels like a test.')
                    self._pending_tutorial = True
        if lid == 'level2' and not load_save:
            if float(getattr(self.core,'elapsed_s',0)) <= 0.0001:
                if not self._persist_seen.get('l2_intro'):
                    self._persist_seen['l2_intro'] = True
                    self._show_lore('This place feels inhabited.')

    def _register_core_callbacks(self):
        ev = self.core.register_event_callback
        ev('coin_picked',              self._on_coin_picked)
        ev('gate_opened',              self._on_gate_moved)
        ev('gate_closed',              self._on_gate_moved)
        ev('key_fragment_encountered', self._on_key_fragment_encountered)
        ev('game_won',                 self._on_game_won)
        ev('checkpoint_reached',       self._on_checkpoint_reached)
        ev('time_penalty',             self._on_time_penalty)
        ev('exit_unlocked',            self._on_exit_unlocked)
        ev('sector_entered',           self._on_sector_entered)
        ev('sent_to_jail',             self._on_sent_to_jail)
        ev('left_jail',                self._on_left_jail)
        ev('key_picked',               self._on_key_picked)
        ev('player_move',              lambda d: None)

    # ── interact ──────────────────────────────────────────────────────────────

    def _handle_interact(self):
        if getattr(self.core,'paused',False): return
        action = self.core.interact()
        if action == 'jail_book':
            self.keys_pressed.clear(); self._mouse_captured = False
            prev = self.core.simulation_frozen
            self.core.simulation_frozen = True
            dlg = KivySilhouetteMinigame()
            def _done(ok):
                self.core.simulation_frozen = prev
                if ok:
                    self.core.mark_jail_puzzle_success()
                    if (self._current_level_id == 'level1'
                            and not self._lore_flags.get('jail_suc')):
                        self._lore_flags['jail_suc'] = True
                        self._show_lore('The maze resets what it cannot control.')
                self.keys_pressed.clear(); self._mouse_captured = False
            dlg.bind_result(_done); dlg.open()
        elif action == 'gate_jail':
            self.core.try_leave_jail()

    def _on_key_fragment_encountered(self, data):
        if getattr(self.core,'paused',False) or self._key_mini_open: return
        fid = str((data or {}).get('id',''))
        if not fid: return
        frag      = getattr(self.core,'key_fragments',{}).get(fid)
        fkind     = str(getattr(frag,'kind','') or '')
        self._trigger_lore('ON_KEY_FRAGMENT_DISCOVERED')
        self._key_mini_open = True
        self.keys_pressed.clear(); self._mouse_captured = False
        prev = self.core.simulation_frozen
        self.core.simulation_frozen = True

        if self._assembly_mini is None:
            self._assembly_mini = KivyAssembly3DMinigame(kind=fkind or 'KP')
        else:
            self._assembly_mini.reset(kind=fkind or 'KP')
        asm = self._assembly_mini
        asm._game_parent = self
        def _done(ok):
            self.core.simulation_frozen = prev
            if ok:
                self.core.mark_key_fragment_taken(fid)
                self._trigger_lore('ON_ASSEMBLY_SUCCESS')
            else:
                self.core.clear_pending_key_fragment(fid)
                self.core.defer_key_fragment(fid)
            self._key_mini_open = False
            self.keys_pressed.clear(); self._mouse_captured = False
        asm.bind_result(_done); asm.open()

    # ── core events ───────────────────────────────────────────────────────────

    def _on_coin_picked(self, data):
        try:
            self._audio.play_coin()
        except Exception:
            pass
        try:
            if float(self.core.coins_collected) >= float(self.core.coins_required)*0.5:
                k = f'coins_half_{self._current_level_id}'
                if not self._lore_flags.get('coins_half') and not self._persist_seen.get(k):
                    self._lore_flags['coins_half'] = True; self._persist_seen[k] = True
                    self._show_lore('Halfway.' if self._current_level_id=='level1'
                                    else 'The maze likes it when I collect.')
        except Exception: pass

    def _on_gate_moved(self, data):
        try:
            self._audio.play_gate()
        except Exception:
            pass

    def _on_game_won(self, data):
        if self._current_level_id != 'level1': return
        un = set(self._progress.get('unlocked_levels') or [])
        if 'level2' not in un:
            un.add('level2'); self._progress['unlocked_levels'] = sorted(un)
            self._save_progression()

    def _on_checkpoint_reached(self, data):
        self._last_update_t = time.perf_counter()

    def _on_time_penalty(self, data):
        try:
            amt = int((data or {}).get('seconds',0) or 0)
            if amt > 0: self._hud.set_time_bonus(f'+{amt}')
        except Exception: pass

    def _on_sector_entered(self, data):
        sid = str((data or {}).get('id','') or '')
        if self._current_level_id == 'level2' and sid == 'F':
            try:
                req=(int(self.core.coins_collected)>=int(self.core.coins_required)
                     and int(self.core.keys_collected)>=int(self.core.keys_required))
            except Exception: req = False
            if req and not self._lore_flags.get('l2_f'):
                self._lore_flags['l2_f'] = True
                self._show_lore('A dream… Far too lucid.')

    def _on_exit_unlocked(self, data):
        pass  # Exit unlocked message removed per user request

    def _on_sent_to_jail(self, data):
        if self._current_level_id != 'level1': return
        if not self._persist_seen.get('tutorial_jail'):
            self._persist_seen['tutorial_jail'] = True
            self._show_tutorial(
                'Jail',
                'This is not death.\n'
                'To escape, find the table and press E to interact with the glowing book.\n\n'
                'A sector map is displayed here. Use it to orient yourself before returning to the maze.')
        
        # Track jail entry for performance monitor
        try:
            self._perf.record_jail_entry()
        except Exception:
            pass

    def _on_left_jail(self, data):
        pass

    def _on_key_picked(self, data):
        try:
            cnt = int((data or {}).get('count',0) or 0)
            if (self._current_level_id == 'level2' and cnt >= 3
                    and not self._lore_flags.get('l2_frags')):
                self._lore_flags['l2_frags'] = True
                self._show_lore('The key is done… I am watched.')
        except Exception: pass

    # ── lore ──────────────────────────────────────────────────────────────────

    def _trigger_lore(self, key):
        key = str(key or '').strip()
        if not key or key in self._lore_seen: return
        txt = None
        if key == 'ON_GHOST_CLOSE':
            txt = 'Why are you here?' if self._current_level_id=='level1' else 'Wake me up.'
        if not txt: return
        self._lore_seen[key] = True; self._show_lore(txt)

    def _poll_lore(self):
        if getattr(self.core,'paused',False) or self._hud._modal_visible: return
        try:
            nearest = min((math.hypot(g.x-self.core.player.x,
                                       g.z-self.core.player.z)
                           for g in self.core.ghosts.values()), default=None)
            if nearest is not None and nearest <= 2.0:
                if not self._lore_flags.get('ghost_close'):
                    self._lore_flags['ghost_close'] = True
                    k = f'ghost_close_{self._current_level_id}'
                    if not self._persist_seen.get(k):
                        self._persist_seen[k] = True
                        self._trigger_lore('ON_GHOST_CLOSE')
                
                # Track ghost encounter for performance monitor
                try:
                    self._perf.record_ghost_encounter()
                except Exception:
                    pass
        except Exception: pass

    # ── save / load ───────────────────────────────────────────────────────────

    def _load_progression(self):
        if not os.path.exists(self._progress_path):
            return {'unlocked_levels':['level1'],'last_level':'level1'}
        try:
            with open(self._progress_path,'r',encoding='utf-8') as f: d=json.load(f)
            if not isinstance(d,dict): raise ValueError
            if 'level1' not in (d.get('unlocked_levels') or []):
                d['unlocked_levels'] = ['level1']
            d.setdefault('last_level','level1')
            return d
        except Exception:
            return {'unlocked_levels':['level1'],'last_level':'level1'}

    def _save_progression(self):
        try:
            with open(self._progress_path,'w',encoding='utf-8') as f:
                json.dump(self._progress,f,indent=2)
        except Exception: pass

    def _save_game(self):
        try:
            self._progress['last_level'] = self._current_level_id
            self._save_progression()
            state = self.core.get_save_state()
            state['ui_seen'] = dict(self._persist_seen)
            with open(self._save_path,'w',encoding='utf-8') as f:
                json.dump(state,f,indent=2)
        except Exception as e: print(f'[save] {e}')

    def _load_save(self):
        if not os.path.exists(self._save_path): return
        try:
            with open(self._save_path,'r',encoding='utf-8') as f: st=json.load(f)
            if isinstance(st,dict):
                sl = str(st.get('level_id') or '')
                if sl and sl != self._current_level_id: return
                seen = st.get('ui_seen')
                if isinstance(seen,dict):
                    self._persist_seen.update({str(k):bool(v) for k,v in seen.items()})
            self.core.load_save_state(st)
        except Exception as e: print(f'[load] {e}')

    def _restart(self):
        p = bool(getattr(self.core,'paused',False))
        self.core = GameCore(level_id=self._current_level_id)
        self._gl.renderer = KivyRenderer(self.core)
        self._hud.core = self.core
        
        # Reconnect performance monitor to new game core
        self.core._performance_monitor = self._perf
        self._perf._game_start_time = time.perf_counter()

        # Reset level-end state (wxPython parity)
        self._level_end_triggered = False
        self._level_complete = False
        self._stats_visible = False
        self._stats_text = ''
        self._perf_pdf_exported = False
        self._show_the_end = False
        self._end_screen_visible = False
        try:
            self._hud._stats.set_text('')
        except Exception:
            pass
        self.keys_pressed.clear()
        self._register_core_callbacks()
        if p: self._set_paused(True)
        self._last_update_t = time.perf_counter()

        # Restart always begins at 00:00
        try:
            self._audio.play_gate()
        except Exception:
            pass

        try:
            self._audio.set_footsteps(False)
        except Exception:
            pass

    def _handle_level_end(self) -> None:
        """Called once when game_won becomes True. Freezes gameplay, freezes stats,
        then shows either the stats screen (level 1) or the end screen stats (level 2)."""
        self._level_complete = True
        try:
            self.core.simulation_frozen = True
        except Exception:
            pass
        try:
            self._audio.set_footsteps(False)
        except Exception:
            pass

        # Unlock level 2 if we just finished level 1
        if self._current_level_id == 'level1':
            try:
                unlocked = set(self._progress.get('unlocked_levels') or ['level1'])
                unlocked.add('level2')
                self._progress['unlocked_levels'] = sorted(unlocked)
                self._save_progression()
            except Exception:
                pass

        # Freeze & build the summary text (use PerformanceMonitor)
        try:
            self._perf.update_scene_data(
                walls_rendered=len(getattr(self.core, 'walls', set())),
                coins=len(getattr(self.core, 'coins', {})),
                ghosts=len(getattr(self.core, 'ghosts', {})),
                spike_traps=len(getattr(self.core, 'spikes', [])),
                moving_platforms=len(getattr(self.core, 'platforms', [])),
            )
            self._perf._game_core_elapsed_s = self.core.elapsed_s
            self._perf.freeze_stats()
            t = int(getattr(self.core, 'elapsed_s', 0.0) or 0.0)
            mm, ss = divmod(t, 60)
            gameplay_metrics = {
                'Level': str(self._current_level_id).replace('level', 'Level '),
                'Time': f'{mm:02d}:{ss:02d}',
                'Coins collected': f"{getattr(self.core, 'coins_collected', 0)}/{getattr(self.core, 'coins_required', 0)}",
            }
            summary_text = self._perf.format_summary_text(gameplay_metrics)
        except Exception as exc:
            summary_text = f'Level complete!\n\nPress ESC to continue.\n\n({exc})'

        try:
            # Export PDF only once per level completion
            if not self._perf_pdf_exported:
                # Get performance data from the monitor
                performance_data = self._perf.get_performance_summary()
                
                # Prepare gameplay metrics
                gameplay_metrics = {
                    'Coins Collected': f'{self.core.coins_collected}/{self.core.coins_required}',
                    'Keys Collected': f'{self.core.keys_collected}/{self.core.keys_required}',
                    'Jail Entries': str(self.core.jail_entries),
                    'Avg Coin Collection Time': f'{self.core.avg_coin_time:.1f}s',
                }
                
                # Import PDF export here to avoid circular imports
                from core.pdf_export import export_performance_pdf
                
                export_performance_pdf(
                    framework='kivy',
                    level_id=str(self._current_level_id),
                    performance_data=performance_data,
                    gameplay_metrics=gameplay_metrics,
                    out_dir=os.path.abspath('performance_reports'),
                )
                self._perf_pdf_exported = True
                print(f"[Kivy] PDF report exported to performance_reports/")
        except ImportError as e:
            print(f"[Kivy] PDF export not available: {e}")
        except Exception as e:
            print(f"[Kivy] PDF export failed: {e}")
            import traceback
            traceback.print_exc()

        if self._current_level_id == 'level2':
            self.show_end_screen(summary_text)
        else:
            self.show_stats_screen(summary_text)

    def show_stats_screen(self, text: str) -> None:
        self._stats_text = str(text or '')
        self._stats_visible = True
        self._end_screen_visible = False
        self._level_complete = True
        try:
            self._hud._stats.set_text(self._stats_text, end_mode=False)
        except Exception:
            pass

    def show_end_screen(self, text: str) -> None:
        self._stats_text = str(text or '')
        self._stats_visible = True
        self._end_screen_visible = True
        self._level_complete = True
        try:
            self._hud._stats.set_text(self._stats_text, end_mode=True)
        except Exception:
            pass

    def hide_stats_screen(self) -> None:
        self._stats_visible = False
        self._end_screen_visible = False
        self._stats_text = ''
        try:
            self._hud._stats.set_text('')
        except Exception:
            pass

    def _on_stats_screen_esc(self) -> None:
        """ESC pressed while stats screen is visible (wxPython parity)."""
        if not bool(getattr(self, '_level_complete', False)):
            return

        if str(getattr(self, '_current_level_id', '')) == 'level2':
            # Level 2 complete: show THE END
            self.hide_stats_screen()
            self._show_the_end = True
            return

        # Level 1 complete: hide stats and show level select
        self.hide_stats_screen()
        self._level_complete = False
        self._open_level_select(startup=False)


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

class KivyGameApp(App):
    def build(self):
        os.environ.setdefault('KIVY_GL_PROFILE','core')
        Window.clearcolor = (0.05,0.05,0.08,1)
        Window.size  = (1280,800)
        Window.title = 'Within the Walls (Kivy)'
        return KivyGameWindow(size_hint=(1,1))

def run():
    KivyGameApp().run()