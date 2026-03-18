"""
kivy_assembly3d.py  –  3D Assembly Minigame, exact PySide6 parity.

Camera: distance=8, elevation=20°, azimuth=30° (matches setCameraPosition)
Grid:   X lines x=-4..4 at z=0, Y lines y=-2..4 at z=0 (flat XY plane)
Pieces: centered at z=0 on the grid
Coords: pos[0]=X(left/right), pos[1]=Y(depth, front/back), pos[2]=Z(height)
        ↑=(0,1,0) forward  ↓=(0,-1,0) back  ←=(-1,0,0)  →=(1,0,0)
        Z+=(0,0,1) up      Z-=(0,0,-1) down
Check: adjacency graph on integer-rounded positions
Congrats: simulated popup window overlay (same pattern as main dialog)
"""

import ctypes, math, time
from typing import List, Optional, Tuple

import OpenGL.GL as GL
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Callback, Color, Rectangle, Line
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget


# ─── colours ──────────────────────────────────────────────────────────────────
_BG      = (0.290, 0.290, 0.314, 1)   # #4a4a50
_HDR_BG  = (0.220, 0.220, 0.240, 1)
_BTN_BG  = (0.353, 0.353, 0.376, 1)   # #5a5a60
_CHECK_G = (0.302, 0.678, 0.502, 1)   # #4ade80
_QUIT_R  = (0.937, 0.267, 0.267, 1)   # #ef4444
_GOLD    = (1.000, 0.843, 0.000, 1)
_ZKEY_BG = (1.000, 0.973, 0.863, 1)
_WHITE   = (1, 1, 1, 1)
_DARK    = (0.176, 0.176, 0.188, 1)
_GREEN_D = (0.176, 0.353, 0.176, 1)   # #2d5a2d


def _btn(text, fn, bg=_BTN_BG, fg=_WHITE, markup=False, **kw):
    b = Button(text=text, markup=markup, font_size='13sp',
               background_normal='', background_color=bg, color=fg, **kw)
    b.bind(on_press=lambda *_: fn())
    return b


# ─── shader ───────────────────────────────────────────────────────────────────
_VERT = b"""
#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec4 aColor;
out vec4 vColor;
uniform mat4 uMVP;
void main(){ vColor=aColor; gl_Position=uMVP*vec4(aPos,1.0); }
"""
_FRAG = b"""
#version 330 core
in vec4 vColor; out vec4 FragColor;
void main(){ FragColor=vColor; }
"""
_prog: Optional[int] = None

def _get_prog():
    global _prog
    if _prog: return _prog
    def _sh(src, kind):
        s = GL.glCreateShader(kind); GL.glShaderSource(s, src)
        GL.glCompileShader(s)
        if not GL.glGetShaderiv(s, GL.GL_COMPILE_STATUS):
            raise RuntimeError(GL.glGetShaderInfoLog(s).decode())
        return s
    p = GL.glCreateProgram()
    GL.glAttachShader(p, _sh(_VERT, GL.GL_VERTEX_SHADER))
    GL.glAttachShader(p, _sh(_FRAG, GL.GL_FRAGMENT_SHADER))
    GL.glLinkProgram(p)
    if not GL.glGetProgramiv(p, GL.GL_LINK_STATUS):
        raise RuntimeError(GL.glGetProgramInfoLog(p).decode())
    _prog = p; return p


# ─── math ─────────────────────────────────────────────────────────────────────
def _mul(a, b):
    o = [0.0]*16
    for c in range(4):
        for r in range(4):
            o[r+c*4] = sum(a[r+k*4]*b[k+c*4] for k in range(4))
    return o

def _persp(fov, asp, n, f):
    t = 1/math.tan(math.radians(fov)/2); nf = 1/(n-f)
    return [t/asp,0,0,0, 0,t,0,0, 0,0,(f+n)*nf,-1, 0,0,2*f*n*nf,0]

def _lookat(ex,ey,ez, cx,cy,cz, ux,uy,uz):
    fx,fy,fz = cx-ex,cy-ey,cz-ez
    fl = math.sqrt(fx*fx+fy*fy+fz*fz) or 1e-9
    fx/=fl; fy/=fl; fz/=fl
    rx=fy*uz-fz*uy; ry=fz*ux-fx*uz; rz=fx*uy-fy*ux
    rl = math.sqrt(rx*rx+ry*ry+rz*rz) or 1e-9
    rx/=rl; ry/=rl; rz/=rl
    upx=ry*fz-rz*fy; upy=rz*fx-rx*fz; upz=rx*fy-ry*fx
    return [rx,upx,-fx,0, ry,upy,-fy,0, rz,upz,-fz,0,
            -(rx*ex+ry*ey+rz*ez),-(upx*ex+upy*ey+upz*ez),(fx*ex+fy*ey+fz*ez),1]

def _tmat(tx,ty,tz):
    m=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]; m[12]=tx;m[13]=ty;m[14]=tz; return m

def _rot_y(a):
    c=math.cos(a); s=math.sin(a)
    return [c,0,-s,0, 0,1,0,0, s,0,c,0, 0,0,0,1]

def _camera_vp(w, h, rot_z_extra=0.0):
    """
    Camera matching pyqtgraph GLViewWidget:
      distance=8, elevation=20°, azimuth=30°
    Match our mesh orientation (Y-up):
    - eye_x = dist * cos(elev) * cos(azim)
    - eye_y = dist * cos(elev) * sin(azim)  (Y is depth)
    - eye_z = dist * sin(elev)  (Z is height)
    up vector = (0, 0, 1)  (Z is up)
    FOV = 60° (pyqtgraph GLViewWidget default)
    """
    dist=8.0
    elev=math.radians(20)
    azim=math.radians(30) + rot_z_extra
    ex = dist * math.cos(elev) * math.cos(azim)
    ey = dist * math.cos(elev) * math.sin(azim)  # Y is depth
    ez = dist * math.sin(elev)  # Z is height
    proj = _persp(60.0, w/h, 0.1, 80.0)
    view = _lookat(ex, ey, ez,  0, 0, 0,  0, 0, 1)   # up = Z axis
    return _mul(proj, view)


# ─── geometry ─────────────────────────────────────────────────────────────────
def _cube(col):
    r,g,b,a=col; v=[]
    for q in [
        [(-0.5,-0.5,0.5),(0.5,-0.5,0.5),(0.5,0.5,0.5),(-0.5,0.5,0.5)],
        [(0.5,-0.5,-0.5),(-0.5,-0.5,-0.5),(-0.5,0.5,-0.5),(0.5,0.5,-0.5)],
        [(-0.5,-0.5,-0.5),(-0.5,-0.5,0.5),(-0.5,0.5,0.5),(-0.5,0.5,-0.5)],
        [(0.5,-0.5,0.5),(0.5,-0.5,-0.5),(0.5,0.5,-0.5),(0.5,0.5,0.5)],
        [(-0.5,0.5,0.5),(0.5,0.5,0.5),(0.5,0.5,-0.5),(-0.5,0.5,-0.5)],
        [(-0.5,-0.5,-0.5),(0.5,-0.5,-0.5),(0.5,-0.5,0.5),(-0.5,-0.5,0.5)],
    ]:
        p0,p1,p2,p3=q
        for p in [p0,p1,p2,p0,p2,p3]: v.extend([*p,r,g,b,a])
    return v

def _pyramid(col):
    """Pyramid (Y-up)."""
    r,g,b,a=col
    verts = [
        (0.0, 0.5, 0.0),
        (0.5, -0.5, 0.5),
        (0.5, -0.5, -0.5),
        (-0.5, -0.5, -0.5),
        (-0.5, -0.5, 0.5),
    ]
    faces = [
        (0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1),
        (1, 2, 3), (1, 3, 4),
    ]
    v=[]
    for (a0,b0,c0) in faces:
        for p in (verts[a0], verts[b0], verts[c0]):
            v.extend([p[0], p[1], p[2], r, g, b, a])
    return v

def _grid_verts():
    """
    X-Y plane grid at Z=0.
      X-lines: (x,y0,0)→(x,y1,0)  for x=-4..4, y=-1.5..2.5
      Y-lines: (x0,y,0)→(x1,y,0)  for y=-1..3
    Gold for axis lines (x=0, y=0), grey for others.
    """
    v = []
    GREY = (0.30, 0.30, 0.30, 0.22)
    GOLD = (1.0,  0.84, 0.0,  0.32)
    for x in range(-4, 5):
        c = GOLD if x == 0 else GREY
        v.extend([x, -1.5, 0, *c,  x, 2.5, 0, *c])
    for y in range(-1, 4):
        c = GOLD if y == 0 else GREY
        v.extend([-4, y, 0, *c,  4, y, 0, *c])
    return v

def _upload(raw):
    if not raw: return 0,0
    data=(ctypes.c_float*len(raw))(*raw); stride=7*4
    vao=GL.glGenVertexArrays(1); GL.glBindVertexArray(vao)
    vbo=GL.glGenBuffers(1); GL.glBindBuffer(GL.GL_ARRAY_BUFFER,vbo)
    GL.glBufferData(GL.GL_ARRAY_BUFFER,ctypes.sizeof(data),data,GL.GL_STATIC_DRAW)
    GL.glVertexAttribPointer(0,3,GL.GL_FLOAT,GL.GL_FALSE,stride,ctypes.c_void_p(0))
    GL.glEnableVertexAttribArray(0)
    GL.glVertexAttribPointer(1,4,GL.GL_FLOAT,GL.GL_FALSE,stride,ctypes.c_void_p(12))
    GL.glEnableVertexAttribArray(1)
    GL.glBindVertexArray(0); return int(vao),len(raw)//7


# ─── piece / target data (coords: [x, y_depth, z_height]) ────────────────────
Y_COL=(1,0.875,0,1); B_COL=(0,0.584,1,1); R_COL=(1,0.271,0,1)

def _make_pieces(kind):
    """Initial piece positions. y=depth, z=height. Pieces at z=0 sit on grid."""
    k=(kind or 'KP').upper()
    if k=='KP': return [
        {'type':'cube',   'color':Y_COL, 'pos':[2., 0., 0.]},
        {'type':'cube',   'color':B_COL, 'pos':[-2.,0., 0.]},
        {'type':'pyramid','color':R_COL, 'pos':[0., 0., 0.]},
    ]
    if k=='K':
        cs=[B_COL,Y_COL,R_COL,R_COL,B_COL]
        return [{'type':'cube','color':c,'pos':[-3.+i, 0., 0.]} for i,c in enumerate(cs)]
    return [
        {'type':'cube',   'color':Y_COL,'pos':[-2., 0., 0.]},
        {'type':'cube',   'color':R_COL,'pos':[-1., 0., 0.]},
        {'type':'pyramid','color':B_COL,'pos':[0.,  0., 0.]},
        {'type':'pyramid','color':Y_COL,'pos':[1.,  0., 0.]},
    ]

def _make_target(kind):
    """
    Target structure. Positions are INTEGER grid coords [x, y_depth, z_height].
    Adjacency check rounds piece positions to integers before comparing.
    Stacking: z=1 means one unit above z=0. y=1 means one unit deeper.
    """
    k=(kind or 'KP').upper()
    if k=='KP':
        # Exactly as PySide6: pieces at (0,0,0),(0,1,0),(0,2,0) — along Y(depth)
        return [
            {'type':'cube',    'pos':[0, 0, 0]},
            {'type':'cube',    'pos':[0, 1, 0]},
            {'type':'pyramid', 'pos':[0, 2, 0]},
        ]
    if k=='K':
        # Exactly as PySide6: base row x=0,1,2 at y=0; stack at y=1
        return [
            {'type':'cube','pos':[0,0,0]},{'type':'cube','pos':[1,0,0]},
            {'type':'cube','pos':[2,0,0]},{'type':'cube','pos':[0,1,0]},
            {'type':'cube','pos':[1,1,0]},
        ]
    # Exactly as PySide6: 2 base cubes at y=0, 2 pyramids at y=1
    return [
        {'type':'cube',    'pos':[0,0,0]},{'type':'cube',    'pos':[1,0,0]},
        {'type':'pyramid', 'pos':[0,1,0]},{'type':'pyramid', 'pos':[1,1,0]},
    ]


# ─── GL 3D view ───────────────────────────────────────────────────────────────
class _GL3DView(Widget):
    """GL view with Kivy-viewport-restoring Callback."""
    def __init__(self, bg_dark=True, allow_rotate=False, *, camera_dist=None, **kw):
        super().__init__(**kw)
        self._dark    = bg_dark
        self._can_rot = allow_rotate
        self._vaos: List[Tuple[int,int]] = []
        self._mats: List[List[float]]    = []
        self._gvao=0; self._gvtx=0
        self._ready   = False
        self._rot_extra = 0.0   # extra azimuth rotation from drag
        self._pitch_extra = 0.0 # extra elevation rotation from drag
        self._camera_dist = float(camera_dist) if camera_dist is not None else None
        self._drag    = False
        self._lpos    = None
        with self.canvas:
            Callback(self._draw)
            Callback(self._restore)
        Clock.schedule_interval(lambda *_: self.canvas.ask_update(), 1/60.)

    def set_scene(self, vaos, mats, gvao=0, gvtx=0):
        self._vaos=vaos; self._mats=mats; self._gvao=gvao; self._gvtx=gvtx

    def on_touch_down(self, touch):
        if not self._can_rot or not self.collide_point(*touch.pos): return False
        self._drag=True; self._lpos=touch.pos; touch.grab(self); return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self: return False
        if self._lpos:
            self._rot_extra -= (touch.pos[0]-self._lpos[0])*0.008
            self._pitch_extra += (touch.pos[1]-self._lpos[1])*0.008
            self._pitch_extra = max(-1.1, min(1.1, self._pitch_extra))
        self._lpos=touch.pos; return False

    def on_touch_up(self, touch):
        if touch.grab_current is self: touch.ungrab(self); self._drag=False
        return False

    def _restore(self, instr):
        GL.glDisable(GL.GL_SCISSOR_TEST)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glViewport(0, 0, int(Window.width), int(Window.height))
        GL.glUseProgram(0)

    def _draw(self, instr):
        if not self._vaos and not self._gvao:
            return
        if not self._ready:
            try:
                _get_prog()
                self._ready = True
            except Exception as e:
                print('[Assembly GL]', e)
                return

        x = int(self.x)
        y = int(self.y)
        w = max(1, int(self.width))
        h = max(1, int(self.height))
        if w<4 or h<4: return
        GL.glEnable(GL.GL_SCISSOR_TEST); GL.glScissor(x,y,w,h)
        GL.glViewport(x,y,w,h); GL.glEnable(GL.GL_DEPTH_TEST)
        if self._dark: GL.glClearColor(0.314,0.314,0.333,1)   # #505055
        else:          GL.glClearColor(0.941,0.941,0.961,1)   # #f0f0f5
        GL.glClear(GL.GL_COLOR_BUFFER_BIT|GL.GL_DEPTH_BUFFER_BIT)

        vp = _camera_vp(w, h, self._rot_extra if self._can_rot else 0.0)
        if self._camera_dist is not None:
            try:
                dist = float(self._camera_dist)
                elev = math.radians(20)
                azim = math.radians(30) + (self._rot_extra if self._can_rot else 0.0)
                ex = dist * math.cos(elev) * math.cos(azim)
                ey = dist * math.cos(elev) * math.sin(azim)  # Y is depth
                ez = dist * math.sin(elev)  # Z is height
                proj = _persp(60.0, w/h, 0.1, 80.0)
                view = _lookat(ex, ey, ez,  0, 0, 0,  0, 0, 1)  # up = Z axis
                vp = _mul(proj, view)
            except Exception:
                pass
        elif self._can_rot and self._pitch_extra != 0.0:
            try:
                dist = 8.0
                elev = math.radians(20) + float(self._pitch_extra)
                azim = math.radians(30) + float(self._rot_extra)
                ex = dist * math.cos(elev) * math.cos(azim)
                ey = dist * math.cos(elev) * math.sin(azim)  # Y is depth
                ez = dist * math.sin(elev)  # Z is height
                proj = _persp(60.0, w/h, 0.1, 80.0)
                view = _lookat(ex, ey, ez,  0, 0, 0,  0, 0, 1)  # up = Z axis
                vp = _mul(proj, view)
            except Exception:
                pass
        p=_get_prog(); GL.glUseProgram(p)
        loc=GL.glGetUniformLocation(p,b'uMVP')
        if self._gvao and self._gvtx:
            GL.glUniformMatrix4fv(loc,1,GL.GL_FALSE,(ctypes.c_float*16)(*vp))
            GL.glBindVertexArray(self._gvao); GL.glDrawArrays(GL.GL_LINES,0,self._gvtx)
            GL.glBindVertexArray(0)
        for i,(vao,vtx) in enumerate(self._vaos):
            if not vao or not vtx: continue
            m = self._mats[i] if i<len(self._mats) else [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
            GL.glUniformMatrix4fv(loc,1,GL.GL_FALSE,(ctypes.c_float*16)(*_mul(vp,m)))
            GL.glBindVertexArray(vao); GL.glDrawArrays(GL.GL_TRIANGLES,0,vtx)
            GL.glBindVertexArray(0)
        GL.glUseProgram(0); GL.glDisable(GL.GL_DEPTH_TEST); GL.glDisable(GL.GL_SCISSOR_TEST)


# ─── congratulations overlay ──────────────────────────────────────────────────
class _CongratsOverlay(FloatLayout):
    """
    Simulated popup congratulations.
    Dark bg, green title 'Congratulations!', white body, gold fragment text, OK button.
    """
    def __init__(self, on_ok, **kw):
        kw.setdefault('size_hint',(1,1)); kw.setdefault('pos',(0,0))
        super().__init__(**kw)
        with self.canvas.before:
            Color(0,0,0,0.72)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(size=lambda w,v:(setattr(self._bg,'size',v),setattr(self._bg,'pos',w.pos)),
                  pos=lambda w,v: setattr(self._bg,'pos',v))

        panel = BoxLayout(orientation='vertical', spacing=16, padding=32,
                          size_hint=(None,None), size=(480,280),
                          pos_hint={'center_x':.5,'center_y':.5})
        with panel.canvas.before:
            Color(*_BG)
            self._pbg = Rectangle(pos=panel.pos, size=panel.size)
        panel.bind(pos=lambda w,v:(setattr(self._pbg,'pos',v),self._draw_border(w)),
                   size=lambda w,v:(setattr(self._pbg,'size',v),self._draw_border(w)))

        panel.add_widget(Label(
            text='[b][color=4ade80]Congratulations![/color][/b]',
            markup=True, font_size='24sp',
            size_hint=(1,None), height=40, halign='center', valign='middle',
        ))
        panel.add_widget(Label(
            text='You have successfully assembled the structure!',
            font_size='16sp', color=(1,1,1,1),
            size_hint=(1,None), height=32, halign='center', valign='middle',
        ))
        panel.add_widget(Label(
            text='[color=ffd700]You collected a key fragment![/color]',
            markup=True, font_size='14sp',
            size_hint=(1,None), height=28, halign='center', valign='middle',
        ))
        ok = Button(text='[b]OK[/b]', markup=True, font_size='15sp',
                    background_normal='', background_color=_CHECK_G,
                    color=_DARK, size_hint=(None,None), size=(160,48),
                    pos_hint={'center_x':.5})
        ok.bind(on_press=lambda *_: on_ok())
        panel.add_widget(Widget(size_hint=(1,1)))  # spacer
        panel.add_widget(ok)
        self.add_widget(panel)

    def _draw_border(self, w):
        w.canvas.after.clear()
        with w.canvas.after:
            Color(0.302,0.678,0.502,1)   # green border like #4ade80
            Line(rectangle=(w.x,w.y,w.width,w.height), width=1.5)


# ─── minigame ─────────────────────────────────────────────────────────────────
class KivyAssembly3DMinigame(FloatLayout):
    """Full-screen overlay."""

    # Constants
    GRID_MIN=-4; GRID_MAX=4; Z_MIN=0; Z_MAX=2

    def __init__(self, kind='KP', **kw):
        kw.setdefault('size_hint',(1,1)); kw.setdefault('pos',(0,0))
        super().__init__(**kw)
        self.kind=(kind or 'KP').upper()
        self._callback   = None
        self._game_parent= None
        self._gl_built   = False
        self._ref_vaos: List[Tuple[int,int]] = []
        self._asm_vaos: List[Tuple[int,int]] = []
        self._asm_mats: List[List[float]]    = []
        self._gvao=0; self._gvtx=0
        self._pieces=_make_pieces(self.kind)
        self._target=_make_target(self.kind)
        self._placed=[False]*len(self._pieces)
        self._selected=None
        self._last_t=time.perf_counter()
        self._flash_t=0.
        self._build_ui()
        Clock.schedule_interval(self._tick, 1/60.)

    def bind_result(self, cb): self._callback=cb

    def open(self):
        Window.add_widget(self)
        self._gl_built=False
        Clock.schedule_once(self._build_gl, 0.15)

    def dismiss(self):
        Clock.unschedule(self._tick)
        try: Window.remove_widget(self)
        except Exception: pass

    def reset(self, kind):
        self.kind=(kind or 'KP').upper()
        self._pieces=_make_pieces(self.kind); self._target=_make_target(self.kind)
        self._placed=[False]*len(self._pieces); self._selected=None; self._flash_t=0.
        self._gl_built=False
        self._rebuild_piece_btns(); self._update_views(); self._set_fb()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        with self.canvas.before:
            Color(0,0,0,0.72)
            self._ol = Rectangle(pos=self.pos, size=self.size)
        self.bind(size=lambda w,v:(setattr(self._ol,'size',v),setattr(self._ol,'pos',w.pos)),
                  pos=lambda w,v: setattr(self._ol,'pos',v))

        dlg = BoxLayout(orientation='vertical',
                        size_hint=(0.78,0.88),
                        pos_hint={'center_x':.5,'center_y':.5},
                        spacing=0)
        with dlg.canvas.before:
            Color(*_BG); self._dbg=Rectangle(pos=dlg.pos,size=dlg.size)
        dlg.bind(pos=lambda w,v:(setattr(self._dbg,'pos',v),self._dlg_border(w)),
                 size=lambda w,v:(setattr(self._dbg,'size',v),self._dlg_border(w)))

        # title bar
        tb=BoxLayout(size_hint=(1,None),height=36,padding=(8,0,4,0),spacing=4)
        with tb.canvas.before:
            Color(*_HDR_BG); self._tbbg=Rectangle(pos=tb.pos,size=tb.size)
        tb.bind(pos=lambda w,v:setattr(self._tbbg,'pos',v),
                size=lambda w,v:setattr(self._tbbg,'size',v))
        tb.add_widget(Label(text='3D Assembly Minigame',bold=True,font_size='13sp',
                            color=(0.9,0.9,0.9,1),halign='left',valign='middle'))
        xb=Button(text='✕',font_size='14sp',size_hint=(None,1),width=36,
                  background_normal='',background_color=_QUIT_R,color=_WHITE)
        xb.bind(on_press=lambda *_:self._finish(False))
        tb.add_widget(xb); dlg.add_widget(tb)

        # content: left (ref) + right (asm + controls)
        ct=BoxLayout(orientation='horizontal',size_hint=(1,1),padding=6,spacing=6)

        # LEFT
        lft=BoxLayout(orientation='vertical',size_hint_x=0.38,spacing=4)
        with lft.canvas.before:
            Color(0.22,0.22,0.24,1); self._lbg=Rectangle(pos=lft.pos,size=lft.size)
        lft.bind(pos=lambda w,v:setattr(self._lbg,'pos',v),
                 size=lambda w,v:setattr(self._lbg,'size',v))
        lft.add_widget(Label(text='Reference',bold=True,font_size='14sp',color=_WHITE,
                             size_hint=(1,None),height=30,halign='center',valign='middle'))
        self._ref_view=_GL3DView(bg_dark=True,allow_rotate=True,size_hint=(1,1))
        lft.add_widget(self._ref_view)
        ct.add_widget(lft)

        # RIGHT
        rgt=BoxLayout(orientation='vertical',size_hint_x=0.62,spacing=4)
        rgt.add_widget(Label(text='Assembly Area',bold=True,font_size='14sp',color=_WHITE,
                             size_hint=(1,None),height=30,halign='center',valign='middle'))

        self._asm_view=_GL3DView(bg_dark=False,allow_rotate=False,camera_dist=5.0,size_hint=(1,1))
        rgt.add_widget(self._asm_view)

        # feedback + Reset/Check/Quit
        ctrl=BoxLayout(orientation='horizontal',size_hint=(1,None),height=42,spacing=6)
        self._feedback=Label(
            text='Select piece → Use arrows to move → Z+/- for height',
            font_size='12sp',markup=True,color=_WHITE,
            halign='left',valign='middle')
        self._feedback.bind(size=self._feedback.setter('text_size'))
        with self._feedback.canvas.before:
            Color(*_BTN_BG); self._fbbg=Rectangle(pos=self._feedback.pos,size=self._feedback.size)
        self._feedback.bind(pos=lambda w,v:setattr(self._fbbg,'pos',v),
                            size=lambda w,v:setattr(self._fbbg,'size',v))
        ctrl.add_widget(self._feedback)
        ctrl.add_widget(_btn('Reset',       self._reset_pieces,   size_hint_x=None,width=64))
        ctrl.add_widget(_btn('[b]Check[/b]',self._check,
                             bg=_CHECK_G,fg=_DARK,markup=True,size_hint_x=None,width=64))
        ctrl.add_widget(_btn('Quit',        lambda:self._finish(False),
                             bg=_QUIT_R,size_hint_x=None,width=54))
        rgt.add_widget(ctrl)

        # piece buttons
        self._piece_row=BoxLayout(orientation='horizontal',size_hint=(1,None),height=38,spacing=4)
        self._piece_btns: List[Button]=[]
        self._rebuild_piece_btns()
        rgt.add_widget(self._piece_row)

        # arrow pad layout:
        # row0: [  ] [↑] [  ] [Z+]
        # row1: [←] [  ] [→] [  ]
        # row2: [  ] [↓] [  ] [Z-]
        # ↑↓ = Y(depth) axis  ←→ = X axis  Z+/Z- = Z(height) axis
        abg=BoxLayout(orientation='horizontal',size_hint=(1,None),height=120,
                      padding=6,spacing=8)
        with abg.canvas.before:
            Color(*_BTN_BG); self._abg=Rectangle(pos=abg.pos,size=abg.size)
        abg.bind(pos=lambda w,v:setattr(self._abg,'pos',v),
                 size=lambda w,v:setattr(self._abg,'size',v))

        ag=GridLayout(cols=4,rows=3,spacing=4,size_hint=(1,1))

        def _a(txt,dx,dy,dz):
            b=Button(text=txt,font_size='18sp',background_normal='',
                     background_color=_BTN_BG,color=_WHITE,size_hint=(1,1))
            b.bind(on_press=lambda inst,x=dx,y=dy,z=dz:self._move(x,y,z))
            return b

        def _z(txt,dz):
            b=Button(text=txt,font_size='13sp',background_normal='',
                     background_color=_ZKEY_BG,color=_DARK,size_hint=(1,1))
            b.bind(on_press=lambda inst,z=dz:self._move(0,0,z))
            return b

        # row 0: ↑ moves +Y (forward/deeper), Z+ raises +Z
        ag.add_widget(Widget()); ag.add_widget(_a('↑', 0, 1, 0))
        ag.add_widget(Widget()); ag.add_widget(_z('Z+', 1))
        # row 1: ←→ move ±X
        ag.add_widget(_a('←',-1,0,0)); ag.add_widget(Widget())
        ag.add_widget(_a('→', 1,0,0)); ag.add_widget(Widget())
        # row 2: ↓ moves -Y, Z- lowers -Z
        ag.add_widget(Widget()); ag.add_widget(_a('↓', 0,-1, 0))
        ag.add_widget(Widget()); ag.add_widget(_z('Z-',-1))

        abg.add_widget(ag); rgt.add_widget(abg)
        ct.add_widget(rgt); dlg.add_widget(ct); self.add_widget(dlg)

    def _dlg_border(self,w):
        w.canvas.after.clear()
        with w.canvas.after:
            Color(0.5,0.5,0.52,1); Line(rectangle=(w.x,w.y,w.width,w.height),width=1)

    def _rebuild_piece_btns(self):
        self._piece_row.clear_widgets(); self._piece_btns=[]
        for i,p in enumerate(self._pieces):
            b=Button(text=f"{p['type'].capitalize()} {i+1}",
                     font_size='13sp',background_normal='',
                     background_color=_BTN_BG,color=_WHITE)
            b.bind(on_press=lambda inst,idx=i:self._select(idx))
            self._piece_btns.append(b); self._piece_row.add_widget(b)

    # ── GL ────────────────────────────────────────────────────────────────────
    def _build_gl(self,*_):
        try:
            _get_prog()
            self._ref_vaos=[]
            for i,t in enumerate(self._target):
                p=self._pieces[i] if i<len(self._pieces) else {'type':'cube','color':Y_COL}
                raw=_cube(p['color']) if t['type']=='cube' else _pyramid(p['color'])
                self._ref_vaos.append(_upload(raw))
            self._ref_view.set_scene(
                self._ref_vaos,
                [_tmat(*[float(v) for v in t['pos']]) for t in self._target])
            self._asm_vaos=[]; self._asm_mats=[]
            for p in self._pieces:
                raw=_cube(p['color']) if p['type']=='cube' else _pyramid(p['color'])
                self._asm_vaos.append(_upload(raw))
                x0,y0,z0 = [float(v) for v in p['pos']]
                self._asm_mats.append(_tmat(x0, y0, z0))
            gv=_grid_verts(); self._gvao,self._gvtx=_upload(gv)
            self._asm_view.set_scene(self._asm_vaos,self._asm_mats,self._gvao,self._gvtx)
            self._gl_built=True
        except Exception as e:
            import traceback; print('[Assembly3D]',e); traceback.print_exc()

    def _update_views(self):
        if not self._gl_built: return
        self._asm_mats=[]
        for p in self._pieces:
            x0,y0,z0 = [float(v) for v in p['pos']]
            self._asm_mats.append(_tmat(x0, y0, z0))
        self._asm_view.set_scene(self._asm_vaos,self._asm_mats,self._gvao,self._gvtx)

    # ── tick / flash ──────────────────────────────────────────────────────────
    def _tick(self,dt):
        now=time.perf_counter()
        if self._game_parent and hasattr(self._game_parent,'core'):
            self._game_parent.core.elapsed_s+=min(now-self._last_t,0.1)
        self._last_t=now; self._flash_t+=dt
        if self._selected is not None and self._gl_built:
            self._flash_selected()

    def _flash_selected(self):
        i=self._selected
        if i is None or i>=len(self._placed) or self._placed[i]: return
        # Smooth flash between original colour and green, period=1s
        phase=(self._flash_t % 1.0)/1.0
        w=0.5-0.5*math.cos(phase*2*math.pi)
        orig=self._pieces[i]['color']
        r0,g0,b0=orig[0],orig[1],orig[2]
        fc=((1-w)*r0, (1-w)*g0+w, (1-w)*b0, 1.0)   # blend toward (0,1,0)
        raw=_cube(fc) if self._pieces[i]['type']=='cube' else _pyramid(fc)
        old,_=self._asm_vaos[i]
        if old:
            try: GL.glDeleteVertexArrays(1,[old])
            except Exception: pass
        self._asm_vaos[i]=_upload(raw)
        self._asm_view.set_scene(self._asm_vaos,self._asm_mats,self._gvao,self._gvtx)

    def _restore_all_piece_colors(self):
        if not self._gl_built: return
        for i,p in enumerate(self._pieces):
            raw=_cube(p['color']) if p['type']=='cube' else _pyramid(p['color'])
            old,_=self._asm_vaos[i]
            if old:
                try: GL.glDeleteVertexArrays(1,[old])
                except Exception: pass
            self._asm_vaos[i]=_upload(raw)
        self._asm_view.set_scene(self._asm_vaos,self._asm_mats,self._gvao,self._gvtx)

    # ── piece actions ─────────────────────────────────────────────────────────
    def _select(self,idx):
        if idx>=len(self._placed) or self._placed[idx]: return
        self._restore_all_piece_colors()   # reset all before new selection
        self._selected=idx; self._flash_t=0.
        for i,b in enumerate(self._piece_btns):
            if self._placed[i]:   b.background_color=(0,0.55,0.8,0.8); b.color=_WHITE
            elif i==idx:          b.background_color=_GOLD;             b.color=_DARK
            else:                 b.background_color=_BTN_BG;           b.color=_WHITE
        self._set_fb()

    def _move(self,dx,dy,dz):
        if self._selected is None or self._placed[self._selected]: return
        p=self._pieces[self._selected]['pos']
        # pos[0]=X, pos[1]=Y(depth), pos[2]=Z(height)
        p[0]=max(self.GRID_MIN,min(self.GRID_MAX,p[0]+dx))
        p[1]=max(self.GRID_MIN,min(self.GRID_MAX,p[1]+dy))
        p[2]=max(self.Z_MIN,   min(self.Z_MAX,   p[2]+dz))
        self._update_views()

    def _check(self):
        """
        Exact port of PySide6 _check_assembly_3d:
        1. type/color match by index
        2. adjacency graph (integer-rounded positions, exactly 1 axis differs by 1)
        """
        def adj(positions):
            a={i:set() for i in range(len(positions))}
            # Round to integers exactly as PySide6 np.round().astype(int)
            ip=[[round(v) for v in pos] for pos in positions]
            for i in range(len(ip)):
                for j in range(i+1,len(ip)):
                    diff=[abs(ip[i][k]-ip[j][k]) for k in range(3)]
                    if sum(1 for d in diff if d==1)==1 and sum(1 for d in diff if d==0)==2:
                        a[i].add(j); a[j].add(i)
            return a

        # type check
        type_ok=all(i<len(self._pieces) and
                    self._pieces[i]['type']==self._target[i]['type']
                    for i in range(len(self._target)))

        # adjacency check
        ta=adj([t['pos'] for t in self._target])
        pa=adj([p['pos'] for p in self._pieces])
        adj_ok=all(pa.get(i,set())==ta.get(i,set()) for i in range(len(self._target)))

        if type_ok and adj_ok:
            self._feedback.text='[b][color=4ade80]Perfect Assembly![/color][/b]'
            with self._feedback.canvas.before:
                Color(*_GREEN_D); self._fbbg=Rectangle(pos=self._feedback.pos,size=self._feedback.size)
            self._placed=[True]*len(self._pieces)
            # Show congratulations overlay
            Clock.schedule_once(self._show_congrats, 0.3)
        else:
            self._feedback.text='[color=ff4444]❌ Incorrect - Keep Trying![/color]'
            with self._feedback.canvas.before:
                Color(0.353,0.176,0.176,1); self._fbbg=Rectangle(pos=self._feedback.pos,size=self._feedback.size)

    def _show_congrats(self,*_):
        def _ok():
            # Remove congrats overlay and finish successfully
            try: self.remove_widget(self._congrats)
            except Exception: pass
            self._finish(True)
        self._congrats=_CongratsOverlay(_ok)
        self.add_widget(self._congrats)

    def _reset_pieces(self):
        fresh=_make_pieces(self.kind)
        for i,p in enumerate(self._pieces): p['pos']=list(fresh[i]['pos'])
        self._placed=[False]*len(self._pieces); self._selected=None; self._flash_t=0.
        for b in self._piece_btns: b.background_color=_BTN_BG; b.color=_WHITE
        if self._gl_built: self._restore_all_piece_colors()
        self._update_views(); self._set_fb()

    def _set_fb(self):
        if self._selected is not None and not self._placed[self._selected]:
            nm=f"{self._pieces[self._selected]['type'].capitalize()} {self._selected+1}"
            self._feedback.text=f'Selected: [b]{nm}[/b] — Use arrows to move → Z+/- for height'
        else:
            self._feedback.text='Select piece → Use arrows to move → Z+/- for height'
        # Reset feedback bg to default
        with self._feedback.canvas.before:
            Color(*_BTN_BG); self._fbbg=Rectangle(pos=self._feedback.pos,size=self._feedback.size)

    def _finish(self,ok):
        self.dismiss()
        if self._callback: self._callback(ok)