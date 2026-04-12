from .kivy_assembly3d import KivyAssembly3DMinigame
from .kivy_silhouette import KivySilhouetteMinigame
from .kivy_renderer import KivyRenderer
from core.performance_monitor import PerformanceMonitor
from core.game_core import GameCore
import OpenGL.GL as GL
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget
from kivy.graphics import Callback, Canvas, Color, Ellipse, Rectangle, Line, Triangle
from kivy.core.audio import SoundLoader
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.app import App
import json
import math
import os
import time
import random
from typing import List, Optional, Set, Tuple

from kivy.config import Config
Config.set('input', 'mouse', 'mouse,disable_multitouch')


FPS_CAMERA_SENSITIVITY = 0.002


_PANEL_BG = (18/255, 18/255, 22/255, 235/255)
_BORDER = (220/255, 220/255, 220/255, 1)
_BTN_BG = (32/255, 32/255, 40/255, 235/255)
_BTN_FG = (1, 1, 1, 1)
_PAUSED_COL = (1, 220/255, 110/255, 1)
_OVERLAY = (0, 0, 0, 160/255)
_BLACK = (0, 0, 0, 1)


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

    def _draw_border(widget, *_):
        widget.canvas.after.clear()
        with widget.canvas.after:
            Color(*_BORDER)
            Line(rectangle=(widget.x, widget.y, widget.width, widget.height), width=1)
    b.bind(pos=_draw_border, size=_draw_border)
    return b


class _GameGLWidget(Widget):
    def __init__(self, renderer, **kwargs):
        super().__init__(**kwargs)
        self.renderer = renderer
        self.performance_monitor: Optional[PerformanceMonitor] = None
        with self.canvas.before:
            Callback(self._measure_actual_fps)
        with self.canvas:
            Callback(self._draw_scene)

        Clock.schedule_interval(lambda dt: self.canvas.ask_update(), 1/60.)

    def _measure_actual_fps(self, instr):
        if not hasattr(self, '_parent_widget'):
            return

        if hasattr(self, 'performance_monitor') and self.performance_monitor:
            if self.performance_monitor.startup_time_ms is None:
                startup_ms = (time.perf_counter() -
                              self.performance_monitor._startup_begin) * 1000
                self.performance_monitor.record_startup_time(startup_ms)

        paused = bool(getattr(self._parent_widget.core, 'paused', False))
        stats_visible = bool(
            getattr(self._parent_widget, '_stats_visible', False))
        show_the_end = bool(
            getattr(self._parent_widget, '_show_the_end', False))

        if not paused and not stats_visible and not show_the_end:
            if hasattr(self, 'performance_monitor') and self.performance_monitor:
                self.performance_monitor.record_frame()
        else:
            if hasattr(self, 'performance_monitor') and self.performance_monitor:
                self.performance_monitor.record_frame(is_pause_frame=True)

    def _draw_scene(self, instr):
        try:
            pm = getattr(self, 'performance_monitor', None)
            if pm is not None:
                try:
                    if pm.resolution == (0, 0):
                        pm.set_resolution(int(Window.width),
                                          int(Window.height))
                except Exception:
                    pass
            self.renderer.render(max(1, int(Window.width)),
                                 max(1, int(Window.height)))
        except Exception:
            import traceback
            traceback.print_exc()


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
            self._coin.stop()
            self._coin.play()
        except Exception:
            pass

    def play_gate(self) -> None:
        if self._gate is None:
            return
        try:
            self._gate.stop()
            self._gate.play()
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
            self._ghost.stop()
            self._ghost.play()
        except Exception:
            pass

    def on_touch_down(self, touch): return False
    def on_touch_move(self, touch): return False
    def on_touch_up(self,   touch): return False


class _ClosingAnimWidget(Widget):
    def __init__(self, gw, **kwargs):
        super().__init__(**kwargs)
        self._gw = gw
        Clock.schedule_interval(lambda *_: self._redraw(), 1/60.)

    def _redraw(self, *_):
        self.canvas.clear()
        gw = getattr(self, '_gw', None)
        core = getattr(gw, 'core', None) if gw else None
        if core is None:
            return
        prog = float(getattr(core, 'screen_close_progress', 0.0) or 0.0)
        if prog <= 0.0:
            return

        w = float(Window.width)
        h = float(Window.height)
        if w < 1 or h < 1:
            return

        with self.canvas:
            if prog < 1.0:
                bar_h = h * prog * 0.5
                Color(0, 0, 0, 1)
                Rectangle(pos=(0, h - bar_h), size=(w, bar_h))  # Top bar
                Rectangle(pos=(0, 0), size=(w, bar_h))  # Bottom bar
            else:
                Color(0, 0, 0, 1)
                Rectangle(pos=(0, 0), size=(w, h))


class _CamIconWidget(Button):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_color = (0, 0, 0, 0)
        self._cooldown_until = 0.0
        self._tex = None
        self._cd_text = ''
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
        self._draw_cd_overlay()

    def _draw_cd_overlay(self):
        self.canvas.after.clear()
        if not self._cd_text:
            return
        x, y, sz = self.x, self.y, self.width
        with self.canvas.after:
            Color(0, 0, 0, 0.6)
            Rectangle(pos=(x, y), size=(sz, sz))
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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.core = None
        self._until = 0.0

        self._static_layout_id = None
        self._static_size = None
        self._static_cell = 0
        self._static_ox = 0
        self._static_oy = 0
        self._static_mw = 0
        self._static_mh = 0
        self._static_rows = 0
        self._static_cols = 0

        self._static_canvas = None
        self._dynamic_canvas = None  # Will hold entities

    def on_touch_down(self, touch):
        return False if self.opacity == 0 else super().on_touch_down(touch)

    def _ensure_static_layer(self):
        if not self.core:
            return False

        layout = self.core.layout
        rows = len(layout)
        cols = len(layout[0]) if rows else 0
        if rows == 0 or cols == 0:
            return False

        W, H = Window.width, Window.height
        cell = max(1, min(int(W * 0.85 / max(cols, 1)),
                          int((H - 40) / max(rows, 1))))
        mw, mh = cols*cell, rows*cell
        ox = (W - mw)//2
        oy = 20 + ((H - 40) - mh)//2

        current_layout_id = id(layout)
        current_size = (W, H)

        needs_rebuild = (
            self._static_layout_id != current_layout_id or
            self._static_size != current_size or
            self._static_canvas is None
        )

        if not needs_rebuild:
            return True  # Static layer is still valid

        self._static_layout_id = current_layout_id
        self._static_size = current_size
        self._static_cell = cell
        self._static_ox = ox
        self._static_oy = oy
        self._static_mw = mw
        self._static_mh = mh
        self._static_rows = rows
        self._static_cols = cols

        if self._static_canvas:
            self.canvas.remove(self._static_canvas)
        self._static_canvas = Canvas()

        walls = self.core.walls
        floors = self.core.floors

        with self._static_canvas:
            Color(10/255, 10/255, 12/255, 210/255)
            Rectangle(pos=(ox, oy), size=(mw, mh))

            Color(230/255, 230/255, 230/255, 1)
            Line(rectangle=(ox, oy, mw, mh), width=1.5)

            wall_positions = []
            floor_positions = []
            other_positions = []

            for r in range(rows):
                for c in range(cols):
                    rx = ox + c*cell
                    ry = oy + (rows-1-r)*cell
                    pos_size = (rx, ry, cell+1, cell+1)

                    if (r, c) in walls:
                        wall_positions.append(pos_size)
                    elif (r, c) in floors:
                        floor_positions.append(pos_size)
                    else:
                        other_positions.append(pos_size)

            if wall_positions:
                Color(45/255, 45/255, 55/255, 1)
                for pos_size in wall_positions:
                    Rectangle(pos=(pos_size[0], pos_size[1]), size=(
                        pos_size[2], pos_size[3]))

            if floor_positions:
                Color(125/255, 125/255, 135/255, 1)
                for pos_size in floor_positions:
                    Rectangle(pos=(pos_size[0], pos_size[1]), size=(
                        pos_size[2], pos_size[3]))

            if other_positions:
                Color(15/255, 15/255, 18/255, 1)
                for pos_size in other_positions:
                    Rectangle(pos=(pos_size[0], pos_size[1]), size=(
                        pos_size[2], pos_size[3]))

        self.canvas.add(self._static_canvas)
        return True

    def redraw(self):
        if not self.core:
            return

        if not self._ensure_static_layer():
            return

        ox, oy = self._static_ox, self._static_oy
        cell = self._static_cell
        rows = self._static_rows
        mw, mh = self._static_mw, self._static_mh

        if self._dynamic_canvas:
            self.canvas.remove(self._dynamic_canvas)
        self._dynamic_canvas = Canvas()

        with self._dynamic_canvas:
            csz = max(6, int(cell*0.35))
            Color(255/255, 215/255, 0, 1)
            for coin in self.core.coins.values():
                if coin.taken:
                    continue
                cr, cc = coin.cell
                Ellipse(pos=(ox+cc*cell+cell//2-csz//2,
                             oy+(rows-1-cr)*cell+cell//2-csz//2), size=(csz, csz))

            GCOLS = {1: (1, .314, .235, 1), 2: (.314, 1, .549, 1), 3: (.431, .667, 1, 1),
                     4: (1, .863, .314, 1), 5: (1, .353, 1, 1)}
            gsz = max(10, int(cell*0.6))
            for g in self.core.ghosts.values():
                s = float(getattr(g, 'size_scale', 1.0) or 1.0)
                gsz_scaled = int(max(8, gsz * s))
                Color(*GCOLS.get(g.id, (1, .471, .118, 1)))
                Ellipse(pos=(ox+int(g.x*cell)+cell//2-gsz_scaled//2,
                             oy+(rows-1-int(g.z))*cell+cell//2-gsz_scaled//2), size=(gsz_scaled, gsz_scaled))

                eye_size = max(2, int(gsz_scaled * 0.15))
                eye_ox = gsz_scaled * 0.25
                eye_oy = gsz_scaled * 0.1
                gx = ox+int(g.x*cell)+cell//2
                gy = oy+(rows-1-int(g.z))*cell+cell//2

                for ex in (gx - eye_ox, gx + eye_ox):
                    ey = gy - eye_oy
                    Color(1, 1, 1, 1)
                    Ellipse(pos=(ex - eye_size//2, ey - eye_size//2),
                            size=(eye_size, eye_size))
                    pupil = max(1, int(eye_size * 0.5))
                    Color(0, 0, 0, 1)
                    Ellipse(pos=(ex - pupil//2, ey - pupil//2),
                            size=(pupil, pupil))

            pr = int(self.core.player.z)
            pc = int(self.core.player.x)
            px = ox + pc*cell + cell//2
            py = oy + (rows-1-pr)*cell + cell//2
            psz = max(12, int(cell*0.7))
            half = psz//2

            Color(50/255, 255/255, 50/255, 1)
            Triangle(points=[px, py-half, px+half, py, px, py+half])
            Triangle(points=[px, py-half, px, py+half, px-half, py])

            dot = max(4, psz//3)
            Color(1, 1, 1, 1)
            Ellipse(pos=(px-dot//2, py-dot//2), size=(dot, dot))

            yaw = float(getattr(self.core.player, 'yaw', 0.0))
            fx = math.sin(yaw)
            fz = -math.cos(yaw)  # Negative because Y is flipped in minimap
            line_len = max(6, int(cell * 0.75))
            Color(255/255, 220/255, 110/255, 1)
            Line(points=[px, py, px+int(fx*line_len),
                 py+int(fz*line_len)], width=2)

            rem = max(0.0, float(self._until) - time.perf_counter())
            ctext = f'MAP: {int(rem + 0.5)}s'
            from kivy.core.text import Label as CoreLabel
            lbl = CoreLabel(text=ctext, font_size=14,
                            bold=True, color=(1, 1, 1, 1))
            lbl.refresh()
            tex = lbl.texture
            tw, th = tex.size
            tx = ox + mw - tw - 10
            ty = oy + mh - th - 8
            Color(0, 0, 0, 0.7)
            Rectangle(pos=(tx - 3, ty - 2), size=(tw + 6, th + 4))
            Color(1, 1, 1, 1)
            Rectangle(pos=(tx, ty), size=(tw, th), texture=tex)

        self.canvas.add(self._dynamic_canvas)

    def force_redraw(self):
        self._static_layout_id = None


class _PausePanel(FloatLayout):

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

        panel.add_widget(Label(
            text='PAUSED', bold=True, font_size='22sp',
            color=_PAUSED_COL,
            size_hint=(1, None), height=42,
            halign='center', valign='middle',
        ))

        self._stats = Label(
            text='', font_size='11sp',
            color=(235/255, 235/255, 235/255, 1),
            size_hint=(1, None), height=72,
            halign='left', valign='top',
        )
        self._stats.bind(size=self._stats.setter('text_size'))
        panel.add_widget(self._stats)

        perf_data = [
            ['Average FPS:', 'N/A'],
            ['Minimum FPS:', 'N/A'],
            ['Maximum FPS:', 'N/A'],
            ['Average Frame Time:', 'N/A'],
            ['Worst Frame Time:', 'N/A'],
        ]
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
        fps = p.stable_display_fps(update_interval_s=2.5) if p else 0
        ram = p.current_ram_mb() if p else 0.0
        self._stats.text = (
            f'FPS: {int(fps)}\n'
            f'RAM usage: {ram:.1f} MB'
        )


class _LevelSelectPanel(FloatLayout):

    def __init__(self, gw, **kwargs):
        super().__init__(**kwargs)
        self.allow_close = False
        self.return_to_pause = False
        self._gw = gw

        with self.canvas.before:
            Color(*_BLACK)
            self._bg = Rectangle(size=self.size, pos=self.pos)
        self.bind(
            size=lambda w, v: (setattr(self._bg, 'size', v),
                               setattr(self._bg, 'pos', w.pos)),
            pos=lambda w, v: setattr(self._bg, 'pos', v),
        )

        col = BoxLayout(
            orientation='vertical',
            spacing=22,
            padding=(0, 0, 0, 0),
            size_hint=(None, None),
            width=620,
            height=340,          # 48+24+82+82+gap+gap ≈ 340
            pos_hint={'center_x': .5, 'center_y': .52},
        )

        self._title_lbl = Label(
            text='SELECT LEVEL', bold=True, font_size='28sp',
            color=(240/255, 240/255, 240/255, 1),
            size_hint=(1, None), height=52,
            halign='center', valign='middle',
        )
        self._title_lbl.bind(size=self._title_lbl.setter('text_size'))
        col.add_widget(self._title_lbl)

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

    def on_touch_down(self, touch):
        return False if self.opacity == 0 else super().on_touch_down(touch)

    def set_unlocked(self, unlocked):
        lvl2 = 'level2' in set(unlocked or {'level1'})
        self._l2_btn.disabled = not lvl2
        self._l2_btn.text = 'Level 2' if lvl2 else 'Level 2 (Locked)'
        self._l2_btn.color = ((240/255, 240/255, 240/255, 1) if lvl2
                              else (140/255, 140/255, 140/255, 1))
        self._close_btn.opacity = 1.0 if self.allow_close else 0.0
        self._draw_btn_border(self._l2_btn)
        self._draw_close_btn(self._close_btn)


class _TutorialPanel(FloatLayout):

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

        panel = BoxLayout(
            orientation='vertical',
            spacing=24,
            padding=24,
            size_hint=(None, None),
            pos_hint={'center_x': .5, 'center_y': .5},
        )

        def update_panel_size(instance, value):
            panel.width = min(840, value[0] * 0.74)
            panel.height = min(440, value[1] * 0.56)
        self.bind(size=update_panel_size)
        with panel.canvas.before:
            Color(18/255, 18/255, 22/255, 245/255)
            self._pbg = Rectangle(pos=panel.pos, size=panel.size)
        panel.bind(
            pos=lambda w, v: (setattr(self._pbg, 'pos', v),
                              self._draw_panel_border(w)),
            size=lambda w, v: (setattr(self._pbg, 'size', v),
                               self._draw_panel_border(w)),
        )

        title_row = BoxLayout(
            orientation='horizontal',
            size_hint=(1, None), height=36,
            spacing=8,
        )
        self._title_lbl = Label(
            text='', bold=True, font_name='Arial', font_size='22sp',
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

        sep = Widget(size_hint=(1, None), height=1)
        with sep.canvas:
            Color(235/255, 235/255, 235/255, 0.4)
            self._sep_line = Rectangle(pos=sep.pos, size=sep.size)
        sep.bind(pos=lambda w, v: setattr(self._sep_line, 'pos', v),
                 size=lambda w, v: setattr(self._sep_line, 'size', v))
        panel.add_widget(sep)

        self._body_lbl = Label(
            text='', font_name='Arial', font_size='17sp',
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
        self._body_lbl.text = body


class _EndPanel(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(0, 0, 0, 1)
            self._bg = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=lambda w, v: (setattr(self._bg, 'size', v),
                                     setattr(self._bg, 'pos', w.pos)),
                  pos=lambda w, v: setattr(self._bg, 'pos', v))
        self._lbl = Label(text='', font_size='28sp', markup=True,
                          size_hint=(1, 1), halign='center', valign='middle')
        self._lbl.bind(size=self._lbl.setter('text_size'))
        self.add_widget(self._lbl)

    def on_touch_down(self, touch):
        return False if self.opacity == 0 else super().on_touch_down(touch)

    def update(self, core):
        if getattr(core, 'game_completed', False) or core.screen_close_progress >= 1.0:
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

        try:
            h = float(self.height or 1.0)
            usable_h = max(1.0, h - 80.0)
            ideal_line_h = 26.0
            line_h = min(ideal_line_h, max(
                14.0, usable_h / max(1.0, float(len(lines)))))
            fs_body = int(max(10.0, min(14.0, line_h - 4.0)))
            fs_header = fs_body + 1
        except Exception:
            line_h = 22.0
            fs_body = 12
            fs_header = 13

        try:
            w = float(self.width or 1.0)
            h = float(self.height or 1.0)
            total_h = float(len(lines)) * float(line_h)
            start_y_wx = max(36.0, (h - total_h - 50.0) / 2.0)
        except Exception:
            w = float(self.width or 1.0)
            h = float(self.height or 1.0)
            start_y_wx = 36.0

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
            is_header = (str(ln).isupper() and len(str(ln)) > 2 and (
                not str(ln).startswith('•')) and (not is_sep))
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
        return True if self.opacity > 0 else super().on_touch_down(touch)


class _TheEndPanel(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(0, 0, 0, 1)
            self._bg = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=lambda w, v: (setattr(self._bg, 'size', v), setattr(self._bg, 'pos', w.pos)),
                  pos=lambda w, v: setattr(self._bg, 'pos', v))
        self._lbl = Label(text='THE END', font_size='68sp', bold=True,
                          size_hint=(1, 1), halign='center', valign='middle',
                          color=(1, 1, 1, 1))
        self._lbl.bind(size=self._lbl.setter('text_size'))
        self.add_widget(self._lbl)


class _HUDOverlay(FloatLayout):
    def __init__(self, gw, **kwargs):
        super().__init__(**kwargs)
        self._gw = gw
        self.core = None

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
            self._obj_bg.pos = w.pos
            self._obj_bg.size = w.size
            w.canvas.after.clear()
            with w.canvas.after:
                Color(*_BORDER)
                Line(rectangle=(w.x, w.y, w.width, w.height), width=1)
        self._obj_bar.bind(pos=_upd_obj_bar_bg, size=_upd_obj_bar_bg)

        row1 = BoxLayout(orientation='horizontal',
                         size_hint=(1, None), height=26)
        self._time_lbl = Label(
            text='Time: 00:00', bold=True, font_size='12sp',
            color=(240/255, 240/255, 240/255, 1),
            halign='left', valign='middle',
        )
        self._time_lbl.bind(size=self._time_lbl.setter('text_size'))
        self._bonus_lbl = Label(
            text='', font_size='22sp', markup=True, bold=True,
            color=(1, 220/255, 60/255, 1),
            size_hint_x=None, width=120,
            halign='left', valign='middle',
        )
        self._bonus_lbl.bind(size=self._bonus_lbl.setter('text_size'))
        row1.add_widget(self._time_lbl)
        row1.add_widget(self._bonus_lbl)
        self._obj_bar.add_widget(row1)

        self._coins_lbl = Label(
            text='Coins: 0/0   Keys: 0/0', font_size='11sp',
            color=(240/255, 240/255, 240/255, 1),
            size_hint=(1, None), height=22,
            halign='left', valign='middle',
        )
        self._coins_lbl.bind(size=self._coins_lbl.setter('text_size'))
        self._obj_bar.add_widget(self._coins_lbl)
        self.add_widget(self._obj_bar)

        self._map_btn = _CamIconWidget(
            size_hint=(None, None), size=(54, 54),
        )
        Clock.schedule_once(self._position_map_icon, 0)
        self._map_btn.bind(on_press=lambda *_: gw._toggle_minimap())
        self.add_widget(self._map_btn)

        self._minimap = _MinimapWidget(size_hint=(1, 1), opacity=0)
        self.add_widget(self._minimap)

        self._lore_outlines = []
        outline_offsets = [(-2, 0), (2, 0), (0, -2), (0, 2),
                           (-2, -2), (2, 2), (-2, 2), (2, -2)]
        for ox, oy in outline_offsets:
            outline_lbl = Label(
                text='', font_size='18sp', markup=True,
                size_hint=(.7, None), height=40,
                pos_hint={'center_x': .5, 'center_y': .44},
                halign='center', valign='middle', opacity=0,
                color=(0, 0, 0, 1),
            )
            outline_lbl.pos_hint = {}
            outline_lbl.bind(size=outline_lbl.setter('text_size'))
            self._lore_outlines.append((outline_lbl, ox, oy))
            self.add_widget(outline_lbl)

        self._lore_lbl = Label(
            text='', font_size='18sp', markup=True,
            size_hint=(.7, None), height=40,
            pos_hint={'center_x': .5, 'center_y': .44},
            halign='center', valign='middle', opacity=0,
        )
        self._lore_lbl.bind(size=self._lore_lbl.setter('text_size'))
        self.add_widget(self._lore_lbl)
        self._lore_queue = []
        self._lore_cur = ''
        self._lore_start = 0.0
        self._lore_end = 0.0

        self._flash_until: float = 0.0
        self._flash_color: Tuple[float, float, float, float] = (
            20/255, 20/255, 25/255, 180/255)
        self._flash_widget = Widget(size_hint=(1, 1), pos=(0, 0), opacity=0)
        with self._flash_widget.canvas:
            Color(*self._flash_color)
            self._flash_rect = Rectangle(pos=(0, 0), size=Window.size)
        self._flash_widget.bind(pos=lambda w, v: setattr(self._flash_rect, 'pos', v),
                                size=lambda w, v: setattr(self._flash_rect, 'size', v))
        self.add_widget(self._flash_widget)

        self._sector_bg = Widget(
            size_hint=(None, None), size=(80, 36),
            pos_hint={'center_x': .5, 'y': .03},
            opacity=0,
        )
        with self._sector_bg.canvas:
            Color(0, 0, 0, 150/255)
            self._sector_bg_rect = Rectangle(
                pos=self._sector_bg.pos, size=self._sector_bg.size)
        self._sector_bg.bind(pos=lambda w, v: setattr(self._sector_bg_rect, 'pos', v),
                             size=lambda w, v: setattr(self._sector_bg_rect, 'size', v))
        self.add_widget(self._sector_bg)

        self._sector_lbl = Label(
            text='', font_size='15sp', markup=True,
            size_hint=(None, None), size=(240, 36),
            pos_hint={'center_x': .5, 'y': .03},
            halign='center', valign='middle', opacity=0,
        )
        self._sector_lbl.bind(size=self._sector_lbl.setter('text_size'))
        self.add_widget(self._sector_lbl)

        self._pause = _PausePanel(gw, size_hint=(1, 1), opacity=0)
        self._tut = _TutorialPanel(gw, size_hint=(1, 1), opacity=0)
        self._end = _EndPanel(size_hint=(1, 1), opacity=0)
        self._stats = _StatsScreenPanel(size_hint=(1, 1), opacity=0)
        for p in (self._pause, self._tut, self._end, self._stats):
            self.add_widget(p)

        Clock.schedule_interval(self._tick, 1/30.)

    def _tick(self, dt):
        if not self.core:
            return
        self._upd_obj()
        self._upd_lore()
        self._upd_sector()
        self._upd_minimap()
        self._upd_end()
        self._upd_flash()

    def _upd_flash(self):
        now = time.perf_counter()
        if now < self._flash_until:
            remaining = self._flash_until - now
            total_flash = 0.3  # 300ms default
            fade = max(0.0, min(1.0, remaining / total_flash))
            self._flash_widget.opacity = fade
        else:
            self._flash_widget.opacity = 0.0

    def trigger_flash(self, duration_ms: float = 300, color: Optional[Tuple[float, float, float, float]] = None) -> None:
        self._flash_until = time.perf_counter() + (duration_ms / 1000.0)
        if color:
            self._flash_color = color
            self._flash_widget.canvas.before.clear()
            with self._flash_widget.canvas.before:
                Color(*color)
                self._flash_rect = Rectangle(
                    pos=self._flash_widget.pos, size=self._flash_widget.size)
        self._flash_widget.opacity = 1.0

    def _upd_obj(self):
        t = int(self.core.elapsed_s)
        self._time_lbl.text = f'Time: {t//60:02d}:{t % 60:02d}'
        self._coins_lbl.text = (f'Coins: {self.core.coins_collected}/'
                                f'{self.core.coins_required}   '
                                f'Keys: {self.core.keys_collected}/'
                                f'{self.core.keys_required}')
        if not (self._bonus_until and time.perf_counter() < self._bonus_until):
            self._bonus_lbl.text = ''

    def _upd_lore(self):
        if not self._lore_cur and self._lore_queue:
            now = time.perf_counter()
            self._lore_cur = self._lore_queue.pop(0)
            self._lore_start = now
            self._lore_end = now + 2.8
        if not self._lore_cur:
            self._lore_lbl.opacity = 0
            for outline_lbl, _, _ in self._lore_outlines:
                outline_lbl.opacity = 0
            return
        now = time.perf_counter()
        if now >= self._lore_end:
            self._lore_cur = ''
            self._lore_lbl.opacity = 0
            for outline_lbl, _, _ in self._lore_outlines:
                outline_lbl.opacity = 0
            return
        dur = max(0.01, self._lore_end - self._lore_start)
        t = (now - self._lore_start) / dur
        fade = 0.18
        a = t/fade if t < fade else (1-t)/fade if t > 1-fade else 1.0
        opacity = max(0, min(1, a))

        main_x = self.center_x - self._lore_lbl.width // 2
        main_y = self.height * 0.44 - self._lore_lbl.height // 2

        self._lore_lbl.opacity = opacity
        self._lore_lbl.text = f'[color=ffffff]{self._lore_cur}[/color]'

        for outline_lbl, ox, oy in self._lore_outlines:
            outline_lbl.opacity = opacity
            outline_lbl.text = f'[color=000000]{self._lore_cur}[/color]'
            outline_lbl.pos = (main_x + ox, main_y + oy)

    def _upd_sector(self):
        pt = float(getattr(self.core, '_sector_popup_timer', 0) or 0)
        pid = str(getattr(self.core, '_sector_popup_id', '') or '')
        if pt <= 0 or not pid:
            self._sector_lbl.opacity = 0
            self._sector_bg.opacity = 0
            return
        total = 2.0
        fi = 0.25
        fo = 0.5
        a = (total-pt)/fi if pt > total-fi else pt/fo if pt < fo else 1.0
        alpha = max(0, min(1, a))
        self._sector_lbl.opacity = alpha
        self._sector_bg.opacity = alpha
        self._sector_lbl.text = f'[b][color=ffd700]SECTOR {pid}[/color][/b]'

    def _upd_minimap(self):
        now = time.perf_counter()
        active = now < self._minimap._until
        if active:
            self._minimap.opacity = 1.0
            self._minimap.core = self.core
            self._minimap.redraw()
        else:
            self._minimap.opacity = 0.0

    def _upd_end(self):
        gw = getattr(self, '_gw', None)
        stats_visible = bool(
            getattr(gw, '_stats_visible', False)) if gw else False

        self._stats.opacity = 1.0 if stats_visible else 0.0

        self._end.opacity = 0.0

    def enqueue_lore_lines(self, lines):
        for ln in (lines or []):
            s = str(ln or '').strip()
            if s:
                self._lore_queue.append(s)

    def is_lore_playing(self):
        return bool(self._lore_cur or self._lore_queue)

    def show_level_select_modal(self, *, unlocked, allow_close, return_to_pause):
        gw = getattr(self, '_gw', None)
        if gw:
            gw._levels.set_unlocked(unlocked)
            gw._levels.allow_close = allow_close
            gw._levels.return_to_pause = return_to_pause
            gw._levels.opacity = 1.0
        self._tut.opacity = 0.0
        self._pause.opacity = 0.0

    def hide_modal(self):
        gw = getattr(self, '_gw', None)
        if gw:
            gw._levels.opacity = 0.0
        self._tut.opacity = 0.0

    def show_tutorial_modal(self, *, title, body):
        self._tut.set_content(title, body)
        self._tut.opacity = 1.0
        gw = getattr(self, '_gw', None)
        if gw:
            gw._levels.opacity = 0.0

    @property
    def _modal_visible(self):
        gw = getattr(self, '_gw', None)
        levels_visible = gw._levels.opacity > 0 if gw else False
        return levels_visible or self._tut.opacity > 0

    @property
    def _modal_kind(self):
        gw = getattr(self, '_gw', None)
        if gw and gw._levels.opacity > 0:
            return 'level_select'
        if self._tut.opacity > 0:
            return 'tutorial'
        return ''

    @property
    def _modal_allow_close(self):
        gw = getattr(self, '_gw', None)
        if gw and gw._levels.opacity > 0:
            return gw._levels.allow_close
        return True

    @property
    def _modal_return_to_pause(self):
        gw = getattr(self, '_gw', None)
        if gw and gw._levels.opacity > 0:
            return gw._levels.return_to_pause
        return False

    def show_pause(self):  self._pause.opacity = 1.0
    def hide_pause(self):  self._pause.opacity = 0.0

    def set_time_bonus(self, text, dur=2.5):
        self._bonus_lbl.text = f'[b][color=ffdc3c]{text}[/color][/b]'
        self._bonus_until = time.perf_counter() + dur

    def _position_map_icon(self, *_):
        margin = 16
        icon_size = 54
        self._map_btn.pos = (Window.width - icon_size - margin, margin)
        Window.bind(on_resize=self._on_window_resize)

    def _on_window_resize(self, instance, width, height):
        margin = 16
        icon_size = 54
        self._map_btn.pos = (width - icon_size - margin, margin)

    def open_minimap(self, secs=10.0):
        self._minimap._until = time.perf_counter() + secs

    def close_minimap(self):
        self._minimap._until = 0.0


class _MinimapWidget(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._until = 0.0


class KivyGameWindow(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._perf = PerformanceMonitor(framework='Kivy')

        self._progress_path = os.path.abspath('progression_kivy.json')
        self._progress = self._load_progression()
        unlocked = set(self._progress.get('unlocked_levels') or ['level1'])
        last_level = str(self._progress.get('last_level') or 'level1')
        if last_level not in unlocked:
            last_level = 'level1'

        self._save_path = os.path.abspath('savegame_kivy.json')
        self._current_level_id = last_level
        self.core = GameCore(level_id=last_level)

        self._gl = _GameGLWidget(KivyRenderer(
            self.core), size_hint=(1, 1), pos=(0, 0))
        self._gl._parent_widget = self  # Set reference for FPS measurement
        self._gl.performance_monitor = self._perf  # Assign early so it's available
        self.add_widget(self._gl)

        self._hud = _HUDOverlay(self, size_hint=(1, 1), pos=(0, 0))
        self._hud.core = self.core
        self.add_widget(self._hud)

        self._closing_anim = _ClosingAnimWidget(
            self, size_hint=(1, 1), pos=(0, 0))
        self.add_widget(self._closing_anim)

        self._levels = _LevelSelectPanel(self, size_hint=(1, 1), opacity=0)
        self._the_end = _TheEndPanel(size_hint=(1, 1), opacity=0)
        self.add_widget(self._levels)
        self.add_widget(self._the_end)

        self._stats_panel = _StatsScreenPanel(size_hint=(1, 1), opacity=0)
        self.add_widget(self._stats_panel)

        self.core._performance_monitor = self._perf

        self._audio = _KivyAudioEngine(asset_dir=os.path.abspath('assets'))
        self._ghost_sfx_ev = Clock.schedule_interval(self._tick_ghost_sfx, 2.5)

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
        self._key_mini_open = False
        self._assembly_mini:   Optional[KivyAssembly3DMinigame] = None
        self._last_ghost_id:   int = 0
        self._last_update_t = time.perf_counter()

        self._register_core_callbacks()

        self._kb = Window.request_keyboard(self._kb_closed, self)
        self._kb.bind(on_key_down=self._on_key_down, on_key_up=self._on_key_up)
        Window.bind(on_keyboard=self._on_win_kb)
        Window.bind(mouse_pos=self._on_mouse_pos)
        Window.bind(on_touch_down=self._on_touch_down)
        Window.bind(on_touch_up=self._on_touch_up)

        # Match PySide6's 16ms timer (62.5 FPS)
        Clock.schedule_interval(self._update, 1/62.5)

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

    def _kb_closed(self):
        if self._kb:
            self._kb.unbind(on_key_down=self._on_key_down,
                            on_key_up=self._on_key_up)
        self._kb = None

    def _on_key_down(self, kb, keycode, text, mod):
        key = keycode[1]
        self._perf.record_input_event()
        if bool(getattr(self, '_show_the_end', False)):
            if key in ('escape', 'esc'):
                App.get_running_app().stop()
            return True
        if bool(getattr(self, '_stats_visible', False)):
            if key in ('escape', 'esc'):
                self._on_stats_screen_esc()
            return True
        self.keys_pressed.add(key)

        if key == 'e':
            self._handle_interact()
            return True
        if key == 'm':
            self._toggle_minimap()
            return True
        return False

    def _on_win_kb(self, window, key, *args):
        self._perf.record_input_event()
        if key == 27:
            if self._levels.opacity > 0:
                return True
            if self._level_complete and (self.core.screen_closing or self.core.game_completed):
                self._on_stats_screen_esc()
                return True
            if self._hud._modal_visible:
                self._on_modal_close_clicked()
                return True
            self._toggle_pause()
            return True
        return False

    def _on_key_up(self, kb, keycode):
        self.keys_pressed.discard(keycode[1])

    def _fps_camera_start(self, initial_pos) -> None:
        self._mouse_captured = True
        self._last_mouse_pos = initial_pos
        Window.show_cursor = False

    def _fps_camera_stop(self) -> None:
        self._mouse_captured = False
        self._last_mouse_pos = None
        Window.show_cursor = True

    def _fps_camera_update(self, dx: float, dy: float) -> None:
        self.core.rotate_player(-dx * FPS_CAMERA_SENSITIVITY)
        self.core.tilt_camera(dy * FPS_CAMERA_SENSITIVITY)

    def _on_touch_down(self, win, touch):
        if not hasattr(touch, 'button') or touch.button != 'left':
            return
        if self._hud._modal_visible:
            return
        if bool(getattr(self, '_stats_visible', False)) or bool(getattr(self, '_show_the_end', False)):
            return
        if getattr(self.core, 'paused', False):
            return
        if getattr(self.core, 'simulation_frozen', False):
            return
        if self.core.screen_closing or self.core.game_completed or self.core.game_won:
            return
        self._fps_camera_start(touch.pos)

    def _on_touch_up(self, win, touch):
        if hasattr(touch, 'button') and touch.button == 'left':
            self._fps_camera_stop()

    def _on_mouse_pos(self, win, pos):
        if not self._mouse_captured:
            self._last_mouse_pos = pos
            return

        if getattr(self.core, 'paused', False) or self._hud._modal_visible:
            self._last_mouse_pos = pos
            return
        if bool(getattr(self, '_stats_visible', False)) or bool(getattr(self, '_show_the_end', False)):
            self._fps_camera_stop()
            return
        if self.core.screen_closing or self.core.game_completed or self.core.game_won:
            self._fps_camera_stop()
            return
        if getattr(self.core, 'simulation_frozen', False):
            self._fps_camera_stop()
            return

        if self._last_mouse_pos is None:
            self._last_mouse_pos = pos
            return

        dx = pos[0] - self._last_mouse_pos[0]
        dy = pos[1] - self._last_mouse_pos[1]

        if abs(dx) > 1 or abs(dy) > 1:
            self._fps_camera_update(dx, dy)

        self._last_mouse_pos = pos

    def _update(self, *_):
        now = time.perf_counter()
        dt = min(now - self._last_update_t, 0.05)
        self._last_update_t = now
        paused = bool(getattr(self.core, 'paused', False))

        if self.core.screen_closing and not self.core.game_won:
            self.core._update_screen_close(dt)

        if bool(getattr(self, '_stats_visible', False)) or bool(getattr(self, '_show_the_end', False)):
            return

        if not paused and not self.core.screen_closing and not self.core.game_won:
            self.core.update(dt)

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
        if not paused and not getattr(self.core, 'simulation_frozen', False) and not self.core.screen_closing and not self.core.game_won:
            spd = 0.09 if self._current_level_id == 'level1' else 0.11
            dx = dz = 0.0
            if 'w' in self.keys_pressed:
                dz += 1.0
            if 's' in self.keys_pressed:
                dz -= 1.0
            if 'a' in self.keys_pressed:
                dx -= 1.0
            if 'd' in self.keys_pressed:
                dx += 1.0

            if dx != 0.0 and dz != 0.0:
                length = math.sqrt(dx * dx + dz * dz)
                dx /= length
                dz /= length

            dx *= spd
            dz *= spd
            if dx or dz:
                try:
                    moved = bool(self.core.move_player(dx, dz))
                except Exception:
                    moved = False
                if moved:
                    self._perf.record_input_processed()
        try:
            if paused or self._hud._modal_visible or getattr(self.core, 'simulation_frozen', False) or self.core.screen_closing or self.core.game_won:
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
                t = max(0.0, min(1.0, (hear_dist - nearest) /
                        (hear_dist - near_dist)))
            self._audio.play_ghost(volume=(0.06 + 0.55 * t))
        except Exception:
            return

    def _set_paused(self, v):
        self.core.paused = bool(v)
        if v:
            self.keys_pressed.clear()
            self._mouse_captured = False
            self._hud.show_pause()
        else:
            self._hud.hide_pause()

    def _toggle_pause(self):
        if self.core.screen_closing or self.core.game_completed or self.core.game_won:
            return
        self._set_paused(not bool(self.core.paused))

    def _on_pause_action(self, action):
        if action == 'resume':
            self._toggle_pause()
        elif action == 'levels':
            self._set_paused(False)
            self._open_level_select(startup=False)
        elif action == 'save':
            self._save_game()
        elif action == 'save_exit':
            self._save_game()
            App.get_running_app().stop()
        elif action == 'exit':
            App.get_running_app().stop()
        elif action == 'restart':
            self._restart()

    def _open_level_select(self, *, startup, allow_close=None):
        un = set(self._progress.get('unlocked_levels') or ['level1'])
        self.core.paused = True
        self.keys_pressed.clear()
        self._mouse_captured = False
        self._hud.hide_pause()
        if allow_close is None:
            allow_close = not startup
        self._hud.show_level_select_modal(
            unlocked=un, allow_close=allow_close,
            return_to_pause=(not startup))

    def _on_level_selected(self, lid):
        self._hud.hide_modal()
        self._set_paused(False)
        self._progress['last_level'] = str(lid)
        self._save_progression()
        self._start_level(lid, load_save=False)

    def _on_modal_close_clicked(self):
        if not self._hud._modal_visible:
            return
        if not self._hud._modal_allow_close:
            return
        if (self._hud._modal_kind == 'level_select'
                and self._hud._modal_return_to_pause):
            self._hud.hide_modal()
            self._set_paused(True)
            return
        self._hud.hide_modal()
        self._set_paused(False)

    def _show_tutorial(self, title, body):
        self.core.paused = True
        self.keys_pressed.clear()
        self._mouse_captured = False
        self._hud.hide_pause()   # ensure pause panel is hidden
        self._hud.show_tutorial_modal(title=title, body=body)

    def _show_lore(self, text):
        s = str(text or '').strip()
        if s:
            self._hud.enqueue_lore_lines([s])

    def _try_open_minimap(self):
        now = time.perf_counter()
        if now < self._hud._map_btn._cooldown_until:
            return
        self._hud.open_minimap(10.0)
        self._hud._map_btn._cooldown_until = now + 30.0

    def _toggle_minimap(self):
        now = time.perf_counter()
        if now < self._hud._minimap._until:
            self._hud.close_minimap()
            return
        self._try_open_minimap()

    def _start_level(self, lid, *, load_save):
        lid = str(lid or 'level1')
        self.core = GameCore(level_id=lid)
        self._current_level_id = lid
        self._gl.renderer = KivyRenderer(self.core)
        self._hud.core = self.core

        old_perf = self._perf

        self._perf = PerformanceMonitor(framework='Kivy')
        self._gl.performance_monitor = self._perf

        old_startup_time = getattr(old_perf, 'startup_time_ms', None)
        if old_startup_time is not None:
            self._perf.startup_time_ms = old_startup_time

        self._perf.frozen_stats = None
        self._perf.fps_history.clear()
        self._perf.memory_samples.clear()

        self.core._performance_monitor = self._perf

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
        for k in ('coins_half', 'ghost_close', 'l2_frags_done', 'l2_sector_f_done'):
            self._lore_flags.pop(k, None)
        self.keys_pressed.clear()
        self._register_core_callbacks()
        self._last_update_t = time.perf_counter()
        if load_save:
            self._load_save()

        if not load_save and self.core.elapsed_s <= 0.0001:
            if not self._persist_seen.get('l1_intro'):
                self._persist_seen['l1_intro'] = True
                self._show_lore('A basement? This feels like a test.')
                self._pending_tutorial = True
        if lid == 'level2' and not load_save:
            if float(getattr(self.core, 'elapsed_s', 0)) <= 0.0001:
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
        ev('sent_to_spawn',           self._on_sent_to_spawn)
        ev('left_jail',                self._on_left_jail)
        ev('key_picked',               self._on_key_picked)
        ev('player_move', lambda d: None)

    def _handle_interact(self):
        if getattr(self.core, 'paused', False):
            return
        action = self.core.interact()
        if action == 'jail_book':
            self.keys_pressed.clear()
            self._mouse_captured = False
            prev = self.core.simulation_frozen
            self.core.simulation_frozen = True
            hard_mode = (self._last_ghost_id == 4)
            dlg = KivySilhouetteMinigame(hard_mode=hard_mode)

            def _done(ok):
                self.core.simulation_frozen = prev
                if ok:
                    self.core.mark_jail_puzzle_success()
                    if (self._current_level_id == 'level1'
                            and not self._lore_flags.get('jail_suc')):
                        self._lore_flags['jail_suc'] = True
                        self._show_lore(
                            'The maze resets what it cannot control.')
                self.keys_pressed.clear()
                self._mouse_captured = False
            dlg.bind_result(_done)
            dlg.open()
        elif action == 'gate_jail':
            self.core.try_leave_jail()

    def _on_key_fragment_encountered(self, data):
        if getattr(self.core, 'paused', False) or self._key_mini_open:
            return
        fid = str((data or {}).get('id', ''))
        if not fid:
            return
        frag = getattr(self.core, 'key_fragments', {}).get(fid)
        fkind = str(getattr(frag, 'kind', '') or '')
        self._trigger_lore('ON_KEY_FRAGMENT_DISCOVERED')
        self._key_mini_open = True
        self.keys_pressed.clear()
        self._mouse_captured = False
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
            self.keys_pressed.clear()
            self._mouse_captured = False
        asm.bind_result(_done)
        asm.open()

    def _on_coin_picked(self, data):
        try:
            self._audio.play_coin()
        except Exception:
            pass
        try:
            if float(self.core.coins_collected) >= float(self.core.coins_required)*0.5:
                k = f'coins_half_{self._current_level_id}'
                if not self._lore_flags.get('coins_half') and not self._persist_seen.get(k):
                    self._lore_flags['coins_half'] = True
                    self._persist_seen[k] = True
                    self._show_lore('Halfway.' if self._current_level_id == 'level1'
                                    else 'The maze likes it when I collect.')
        except Exception:
            pass

    def _on_gate_moved(self, data):
        try:
            self._audio.play_gate()
        except Exception:
            pass

    def _on_game_won(self, data):
        if self._current_level_id != 'level1':
            return
        un = set(self._progress.get('unlocked_levels') or [])
        if 'level2' not in un:
            un.add('level2')
            self._progress['unlocked_levels'] = sorted(un)
            self._save_progression()

    def _on_checkpoint_reached(self, data):
        self._last_update_t = time.perf_counter()

    def _on_time_penalty(self, data):
        try:
            amt = int((data or {}).get('seconds', 0) or 0)
            if amt > 0:
                self._hud.set_time_bonus(f'+{amt}')
        except Exception:
            pass

    def _on_sector_entered(self, data):
        sid = str((data or {}).get('id', '') or '')
        if self._current_level_id == 'level2' and sid == 'F':
            try:
                req = (int(self.core.coins_collected) >= int(self.core.coins_required)
                       and int(self.core.keys_collected) >= int(self.core.keys_required))
            except Exception:
                req = False
            if req and not self._lore_flags.get('l2_f'):
                self._lore_flags['l2_f'] = True
                self._show_lore('A dream… Far too lucid.')

    def _on_exit_unlocked(self, data):
        pass

    def _on_sent_to_jail(self, data):
        reason = str(data.get('reason', ''))
        if reason == 'ghost_4':
            self._last_ghost_id = 4
        elif reason.startswith('ghost'):
            self._last_ghost_id = 1
        else:
            self._last_ghost_id = 0
        if self._current_level_id != 'level1':
            return
        if not self._persist_seen.get('tutorial_jail'):
            self._persist_seen['tutorial_jail'] = True
            self._show_tutorial(
                'Jail',
                'This is not death.\n'
                'To escape, find the table and press E to interact with the glowing book.\n\n'
                'A sector map is displayed here. Use it to orient yourself before returning to the maze.')

    def _on_sent_to_spawn(self, data):
        self._show_lore('Be safe.')
        self._hud.trigger_flash(300, (20/255, 20/255, 25/255, 180/255))

    def _on_left_jail(self, data):
        pass

    def _on_key_picked(self, data):
        try:
            cnt = int((data or {}).get('count', 0) or 0)
            if (self._current_level_id == 'level2' and cnt >= 3
                    and not self._lore_flags.get('l2_frags')):
                self._lore_flags['l2_frags'] = True
                self._show_lore('The key is done… I am watched.')
        except Exception:
            pass

    def _trigger_lore(self, key):
        key = str(key or '').strip()
        if not key or key in self._lore_seen:
            return
        txt = None
        if key == 'ON_GHOST_CLOSE':
            txt = 'Why are you here?' if self._current_level_id == 'level1' else 'Wake me up.'
        if not txt:
            return
        self._lore_seen[key] = True
        self._show_lore(txt)

    def _poll_lore(self):
        if getattr(self.core, 'paused', False) or self._hud._modal_visible:
            return
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

        except Exception:
            pass

    def _load_progression(self):
        if not os.path.exists(self._progress_path):
            return {'unlocked_levels': ['level1'], 'last_level': 'level1'}
        try:
            with open(self._progress_path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            if not isinstance(d, dict):
                raise ValueError
            if 'level1' not in (d.get('unlocked_levels') or []):
                d['unlocked_levels'] = ['level1']
            d.setdefault('last_level', 'level1')
            return d
        except Exception:
            return {'unlocked_levels': ['level1'], 'last_level': 'level1'}

    def _save_progression(self):
        try:
            with open(self._progress_path, 'w', encoding='utf-8') as f:
                json.dump(self._progress, f, indent=2)
        except Exception:
            pass

    def _save_game(self):
        try:
            self._progress['last_level'] = self._current_level_id
            self._save_progression()
            state = self.core.get_save_state()
            state['ui_seen'] = dict(self._persist_seen)
            with open(self._save_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f'[save] {e}')

    def _load_save(self):
        if not os.path.exists(self._save_path):
            return
        try:
            with open(self._save_path, 'r', encoding='utf-8') as f:
                st = json.load(f)
            if isinstance(st, dict):
                sl = str(st.get('level_id') or '')
                if sl and sl != self._current_level_id:
                    return
                seen = st.get('ui_seen')
                if isinstance(seen, dict):
                    self._persist_seen.update(
                        {str(k): bool(v) for k, v in seen.items()})
            self.core.load_save_state(st)
        except Exception as e:
            print(f'[load] {e}')

    def _restart(self):
        p = bool(getattr(self.core, 'paused', False))
        self.core = GameCore(level_id=self._current_level_id)
        self._gl.renderer = KivyRenderer(self.core)
        self._hud.core = self.core

        old_perf = self._perf

        self._perf = PerformanceMonitor(framework='Kivy')
        self._gl.performance_monitor = self._perf

        old_startup_time = getattr(old_perf, 'startup_time_ms', None)
        if old_startup_time is not None:
            self._perf.startup_time_ms = old_startup_time

        self._perf.frozen_stats = None
        self._perf.fps_history.clear()
        self._perf.memory_samples.clear()

        self.core._performance_monitor = self._perf

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
        if p:
            self._set_paused(True)
        self._last_update_t = time.perf_counter()

        try:
            self._audio.play_gate()
        except Exception:
            pass

        try:
            self._audio.set_footsteps(False)
        except Exception:
            pass

    def _handle_level_end(self) -> None:

        self._level_complete = True
        try:
            self.core.simulation_frozen = True
        except Exception:
            pass
        try:
            self._audio.set_footsteps(False)
        except Exception:
            pass

        if self._current_level_id == 'level1':
            try:
                unlocked = set(self._progress.get(
                    'unlocked_levels') or ['level1'])
                unlocked.add('level2')
                self._progress['unlocked_levels'] = sorted(unlocked)
                self._save_progression()
            except Exception:
                pass

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
            summary_text = self._perf.format_summary_text()
        except Exception as exc:
            summary_text = f'Level complete!\n\nPress ESC to continue.\n\n({exc})'

        try:
            if not self._perf_pdf_exported:
                performance_data = self._perf.get_performance_summary()

                from core.pdf_export import export_performance_pdf

                export_performance_pdf(
                    framework='kivy',
                    level_id=str(self._current_level_id),
                    performance_data=performance_data,
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
            self._stats_panel.set_text(self._stats_text, end_mode=False)
            self._stats_panel.opacity = 1.0
        except Exception:
            pass
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
            self._stats_panel.set_text(self._stats_text, end_mode=True)
            self._stats_panel.opacity = 1.0
        except Exception:
            pass
        try:
            self._hud._stats.set_text(self._stats_text, end_mode=True)
        except Exception:
            pass

    def hide_stats_screen(self) -> None:
        self._stats_visible = False
        self._end_screen_visible = False
        self._stats_text = ''
        try:
            self._stats_panel.opacity = 0.0
        except Exception:
            pass
        try:
            self._hud._stats.set_text('')
        except Exception:
            pass

    def _on_stats_screen_esc(self) -> None:
        if not bool(getattr(self, '_level_complete', False)):
            return

        if str(getattr(self, '_current_level_id', '')) == 'level2':
            self.hide_stats_screen()
            self.show_end_screen(self._stats_text)
            return

        self.hide_stats_screen()
        self._level_complete = False
        self._open_level_select(startup=False, allow_close=False)


class KivyGameApp(App):
    title = 'Within the Walls (Kivy)'

    def build(self):
        os.environ.setdefault('KIVY_GL_PROFILE', 'core')
        Window.clearcolor = (0.05, 0.05, 0.08, 1)
        Window.size = (1280, 800)
        Window.title = 'Within the Walls (Kivy)'
        Window.maximize()
        return KivyGameWindow(size_hint=(1, 1))


def run():
    KivyGameApp().run()
