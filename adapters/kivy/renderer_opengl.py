
import ctypes
import math
import os
import time
from array import array as _array
from typing import Dict, List, Optional, Tuple, Any, Callable

import OpenGL.GL as GL

from core.game_core import GameCore
from kivy.core.text import Label as CoreLabel
from kivy.graphics import (
    Callback, Color, Ellipse, Rectangle, Line, Triangle,
    Fbo, ClearColor, ClearBuffers
)

_FOG_START   = 22.0
_FOG_END     = 40.0
_SKY_COLOR   = (0.05, 0.05, 0.08, 1.0)
_CAMERA_H    = 1.6
_FOV_DEG     = 60.0
_NEAR        = 0.15
_FAR         = 80.0
_ENTITY_R2   = 18.0 ** 2
_GLOW_R2     = 12.0 ** 2


_TEXTURED_VERT = b"""
#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec2 aUV;
out vec2 vUV;
out float vFogFactor;
out vec3 vWorldPos;
uniform mat4 uMVP;
uniform float uFogStart;
uniform float uFogEnd;
void main(){
    vec4 world = uMVP * vec4(aPos, 1.0);
    gl_Position = world;
    float dist = abs(world.z);
    vFogFactor = clamp((uFogEnd - dist) / (uFogEnd - uFogStart), 0.0, 1.0);
    vUV = aUV;
    vWorldPos = aPos;
}
"""

_TEXTURED_FRAG = b"""
#version 330 core
in vec2 vUV;
in float vFogFactor;
in vec3 vWorldPos;
out vec4 FragColor;
uniform sampler2D uTex;
uniform vec4 uFogColor;
uniform vec3 uPlayerPos;
uniform float uTime;
uniform bool uEnableDynamicLight;
void main(){
    vec4 texColor = texture(uTex, vUV);
    
    if (uEnableDynamicLight) {
        // Dynamic player light - softer effect with ambient darkening outside radius
        float lightDist = distance(vWorldPos, uPlayerPos);
        float lightRadius = 8.0;
        float lightIntensity = smoothstep(lightRadius, 0.0, lightDist);
        
        // Ambient level: 70% at edge, 100% at center
        float ambientLevel = 0.7 + lightIntensity * 0.3;
        vec3 baseColor = texColor.rgb * ambientLevel;
        
        // Add warm light near player (subtle, not harsh)
        vec3 lightColor = vec3(1.0, 0.95, 0.85);
        vec3 litColor = baseColor + lightColor * lightIntensity * 0.15;
        
        // Pulsing light effect - very subtle
        float pulse = 0.98 + 0.02 * sin(uTime * 2.0);
        litColor *= pulse;
        
        vec4 finalColor = vec4(litColor, texColor.a);
        FragColor = mix(uFogColor, finalColor, vFogFactor);
    } else {
        // No dynamic lighting - use base color at full brightness
        FragColor = mix(uFogColor, texColor, vFogFactor);
    }
}
"""

_COLORED_VERT = b"""
#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec4 aColor;
out vec4 vColor;
out float vFogFactor;
out vec3 vWorldPos;
uniform mat4 uMVP;
uniform float uFogStart;
uniform float uFogEnd;
void main(){
    vec4 world = uMVP * vec4(aPos, 1.0);
    gl_Position = world;
    float dist = abs(world.z);
    vFogFactor = clamp((uFogEnd - dist) / (uFogEnd - uFogStart), 0.0, 1.0);
    vColor = aColor;
    vWorldPos = aPos;
}
"""

_COLORED_FRAG = b"""
#version 330 core
in vec4 vColor;
in float vFogFactor;
in vec3 vWorldPos;
out vec4 FragColor;
uniform vec4 uFogColor;
uniform vec3 uPlayerPos;
uniform float uTime;
uniform bool uEnableFlicker;
void main(){
    vec4 finalColor = vColor;
    
    if (uEnableFlicker) {
        // Lamp flickering effect when player is close
        // Use vertical position for lamp glow detection (lamps are at ceiling height)
        float lampHeight = 2.0; // Approximate lamp height
        vec3 lampPos = vec3(vWorldPos.x, lampHeight, vWorldPos.z);
        float lightDist = distance(lampPos, uPlayerPos);
        float flickerRadius = 6.0;
        float flickerIntensity = smoothstep(flickerRadius, 0.0, lightDist);
        
        if (flickerIntensity > 0.0) {
            // Flicker every 2.5 seconds
            float flickerCycle = mod(uTime, 2.5);
            float flicker = 1.0;
            if (flickerCycle < 0.15) {
                // Quick flicker off during the 2.5 second cycle
                flicker = 0.3 + 0.7 * sin(flickerCycle * 40.0);
            }
            finalColor.rgb *= flicker;
        }
    }
    
    FragColor = mix(uFogColor, finalColor, vFogFactor);
}
"""


def _mat_identity() -> List[float]:
    return [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]

def _mat_mul(a: List[float], b: List[float]) -> List[float]:
    # Multiply two 4x4 column-major matrices.
    out = [0.0]*16
    for col in range(4):
        for row in range(4):
            s = 0.0
            for k in range(4):
                s += a[row + k*4] * b[k + col*4]
            out[row + col*4] = s
    return out

def _perspective(fov_deg: float, aspect: float, near: float, far: float) -> List[float]:
    f = 1.0 / math.tan(math.radians(fov_deg) / 2.0)
    nf = 1.0 / (near - far)
    return [
        f/aspect, 0,  0,               0,
        0,        f,  0,               0,
        0,        0,  (far+near)*nf,  -1,
        0,        0,  2*far*near*nf,   0,
    ]

def _look_at(ex, ey, ez, cx, cy, cz, ux, uy, uz) -> List[float]:
    fx, fy, fz = cx-ex, cy-ey, cz-ez
    fl = math.sqrt(fx*fx+fy*fy+fz*fz)
    if fl == 0: fl = 1e-9
    fx/=fl; fy/=fl; fz/=fl
    rx = fy*uz - fz*uy; ry = fz*ux - fx*uz; rz = fx*uy - fy*ux
    rl = math.sqrt(rx*rx+ry*ry+rz*rz)
    if rl == 0: rl = 1e-9
    rx/=rl; ry/=rl; rz/=rl
    upx = ry*fz - rz*fy; upy = rz*fx - rx*fz; upz = rx*fy - ry*fx
    return [
        rx,  upx, -fx, 0,
        ry,  upy, -fy, 0,
        rz,  upz, -fz, 0,
        -(rx*ex+ry*ey+rz*ez), -(upx*ex+upy*ey+upz*ez), (fx*ex+fy*ey+fz*ez), 1,
    ]

def _translate(tx, ty, tz) -> List[float]:
    m = _mat_identity()
    m[12]=tx; m[13]=ty; m[14]=tz
    return m

def _scale(sx, sy, sz) -> List[float]:
    return [sx,0,0,0, 0,sy,0,0, 0,0,sz,0, 0,0,0,1]

def _rot_y(a) -> List[float]:
    c=math.cos(a); s=math.sin(a)
    return [c,0,-s,0, 0,1,0,0, s,0,c,0, 0,0,0,1]

def _rot_x(a) -> List[float]:
    c=math.cos(a); s=math.sin(a)
    return [1,0,0,0, 0,c,s,0, 0,-s,c,0, 0,0,0,1]

def _rot_z(a) -> List[float]:
    c=math.cos(a); s=math.sin(a)
    return [c,s,0,0, -s,c,0,0, 0,0,1,0, 0,0,0,1]


def _rot_pt_x(x: float, y: float, z: float, a: float) -> tuple[float, float, float]:
    c = math.cos(a); s = math.sin(a)
    return (x, y * c - z * s, y * s + z * c)


def _rot_pt_y(x: float, y: float, z: float, a: float) -> tuple[float, float, float]:
    c = math.cos(a); s = math.sin(a)
    return (x * c + z * s, y, -x * s + z * c)


def _rot_pt_z(x: float, y: float, z: float, a: float) -> tuple[float, float, float]:
    c = math.cos(a); s = math.sin(a)
    return (x * c - y * s, x * s + y * c, z)


def _flip_rgba_v(pixels: bytes, w: int, h: int) -> bytes:
    # flip RGBA pixel buffer (top<->bottom).
    if not pixels or w <= 0 or h <= 0:
        return pixels
    row_bytes = int(w) * 4
    out = bytearray(len(pixels))
    for y in range(int(h)):
        src_row = (int(h) - 1 - y) * row_bytes
        dst_row = y * row_bytes
        out[dst_row:dst_row + row_bytes] = pixels[src_row:src_row + row_bytes]
    return bytes(out)


def _compile_shader(src: bytes, kind) -> int:
    sh = GL.glCreateShader(kind)
    GL.glShaderSource(sh, src)
    GL.glCompileShader(sh)
    if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
        raise RuntimeError(GL.glGetShaderInfoLog(sh).decode())
    return sh

def _build_program(vert: bytes, frag: bytes) -> int:
    vs = _compile_shader(vert, GL.GL_VERTEX_SHADER)
    fs = _compile_shader(frag, GL.GL_FRAGMENT_SHADER)
    prog = GL.glCreateProgram()
    GL.glAttachShader(prog, vs)
    GL.glAttachShader(prog, fs)
    GL.glLinkProgram(prog)
    if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
        raise RuntimeError(GL.glGetProgramInfoLog(prog).decode())
    return prog

def _load_texture_from_path(path: str) -> Optional[int]:
    # load PNG/JPG using CoreImage
    if not os.path.exists(path):
        return None
    try:
        from kivy.core.image import Image as KivyCoreImage
        img = KivyCoreImage(path)
        pixels = img.texture.pixels
        w, h = img.texture.size
        tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        # GL_LINEAR texture filter
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, w, h, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, pixels)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        return int(tex)
    except Exception as e:
        print(f"[KivyRenderer] texture load failed {path}: {e}")
        return None

def _make_fallback_texture(color_rgba: Tuple[int,int,int,int] = (180, 90, 60, 255)) -> int:
    # simple solid color fallback texture
    data = bytes(color_rgba) * (64 * 64)
    tex = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, 64, 64, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, data)
    GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
    return int(tex)

def _upload_vao_textured(raw: _array) -> Tuple[int, int]:
    # Upload float array (x,y,z,u,v per vertex) into a new VAO/VBO. Returns (vao, vtx_count).
    if not raw:
        return 0, 0
    vtx_count = len(raw) // 5
    data = (ctypes.c_float * len(raw))(*raw)
    stride = 5 * 4
    vao = GL.glGenVertexArrays(1)
    GL.glBindVertexArray(vao)
    vbo = GL.glGenBuffers(1)
    GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
    GL.glBufferData(GL.GL_ARRAY_BUFFER, ctypes.sizeof(data), data, GL.GL_STATIC_DRAW)
    GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(0))
    GL.glEnableVertexAttribArray(0)
    GL.glVertexAttribPointer(1, 2, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(12))
    GL.glEnableVertexAttribArray(1)
    GL.glBindVertexArray(0)
    GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
    return int(vao), vtx_count


def _update_dynamic_vao_textured(vao: int, vbo: int, raw: _array) -> Tuple[int, int]:
    # Update/reuse a dynamic textured VAO/VBO. Returns (vao, vtx_count).
    if not raw:
        return vao, 0
    vtx_count = len(raw) // 5
    data = (ctypes.c_float * len(raw))(*raw)
    stride = 5 * 4
    if vao == 0:
        vao = GL.glGenVertexArrays(1)
    GL.glBindVertexArray(vao)
    GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
    GL.glBufferData(GL.GL_ARRAY_BUFFER, ctypes.sizeof(data), data, GL.GL_DYNAMIC_DRAW)
    GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(0))
    GL.glEnableVertexAttribArray(0)
    GL.glVertexAttribPointer(1, 2, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(12))
    GL.glEnableVertexAttribArray(1)
    GL.glBindVertexArray(0)
    GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
    return int(vao), int(vtx_count)

def _upload_vao_colored(raw: _array) -> Tuple[int, int]:
    # Upload float array (x,y,z,r,g,b,a per vertex) into a new VAO/VBO. Returns (vao, vtx_count).
    if not raw:
        return 0, 0
    vtx_count = len(raw) // 7
    data = (ctypes.c_float * len(raw))(*raw)
    stride = 7 * 4
    vao = GL.glGenVertexArrays(1)
    GL.glBindVertexArray(vao)
    vbo = GL.glGenBuffers(1)
    GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
    GL.glBufferData(GL.GL_ARRAY_BUFFER, ctypes.sizeof(data), data, GL.GL_STATIC_DRAW)
    GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(0))
    GL.glEnableVertexAttribArray(0)
    GL.glVertexAttribPointer(1, 4, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(12))
    GL.glEnableVertexAttribArray(1)
    GL.glBindVertexArray(0)
    GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
    return int(vao), vtx_count

def _delete_vao(vao: int) -> None:
    if vao:
        try:
            GL.glDeleteVertexArrays(1, [vao])
        except Exception:
            pass


class _GeoBuilder:
    # Accumulates textured (5-float) or colored (7-float) vertex data.

    def __init__(self, textured: bool):
        self._tex = textured
        self.data: _array = _array('f')

    def quad_tex(self, p0, p1, p2, p3, uv0, uv1, uv2, uv3):
        for p, uv in [(p0,uv0),(p1,uv1),(p2,uv2), (p0,uv0),(p2,uv2),(p3,uv3)]:
            self.data.extend([p[0],p[1],p[2], uv[0],uv[1]])

    def quad_col(self, p0, p1, p2, p3, c):
        for p in [p0,p1,p2, p0,p2,p3]:
            self.data.extend([p[0],p[1],p[2], c[0],c[1],c[2],c[3]])

    def tri_col(self, p0, p1, p2, c):
        x0,y0,z0 = p0; x1,y1,z1 = p1; x2,y2,z2 = p2
        r,g,b,a = c
        self.data.extend([x0,y0,z0, r,g,b,a, x1,y1,z1, r,g,b,a, x2,y2,z2, r,g,b,a])

    def tri_col_vc(self, p0, c0, p1, c1, p2, c2):
        # Triangle with per-vertex color (needed for smooth glow falloff).
        x0,y0,z0 = p0; x1,y1,z1 = p1; x2,y2,z2 = p2
        r0,g0,b0,a0 = c0; r1,g1,b1,a1 = c1; r2,g2,b2,a2 = c2
        self.data.extend([
            x0,y0,z0, r0,g0,b0,a0,
            x1,y1,z1, r1,g1,b1,a1,
            x2,y2,z2, r2,g2,b2,a2,
        ])

    def cube_col(self, cx, cy, cz, sx, sy, sz, c):
        # Axis-aligned box centered at (cx,cy,cz) with half-extents (sx,sy,sz).
        x0,x1 = cx-sx, cx+sx
        y0,y1 = cy-sy, cy+sy
        z0,z1 = cz-sz, cz+sz
        self.quad_col((x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1), c)
        self.quad_col((x1,y0,z0),(x0,y0,z0),(x0,y1,z0),(x1,y1,z0), c)
        self.quad_col((x0,y0,z0),(x0,y0,z1),(x0,y1,z1),(x0,y1,z0), c)
        self.quad_col((x1,y0,z1),(x1,y0,z0),(x1,y1,z0),(x1,y1,z1), c)
        self.quad_col((x0,y1,z1),(x1,y1,z1),(x1,y1,z0),(x0,y1,z0), c)
        self.quad_col((x0,y0,z0),(x1,y0,z0),(x1,y0,z1),(x0,y0,z1), c)

    def cube_tex(self, cx, cy, cz, sx, sy, sz, uv_scale=1.0):
        x0,x1 = cx-sx, cx+sx
        y0,y1 = cy-sy, cy+sy
        z0,z1 = cz-sz, cz+sz
        # Front
        self.quad_tex((x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1),
                      (0.0,0.0),(uv_scale,0.0),(uv_scale,uv_scale),(0.0,uv_scale))
        # Back
        self.quad_tex((x1,y0,z0),(x0,y0,z0),(x0,y1,z0),(x1,y1,z0),
                      (0.0,0.0),(uv_scale,0.0),(uv_scale,uv_scale),(0.0,uv_scale))
        # Left
        self.quad_tex((x0,y0,z0),(x0,y0,z1),(x0,y1,z1),(x0,y1,z0),
                      (0.0,0.0),(uv_scale,0.0),(uv_scale,uv_scale),(0.0,uv_scale))
        # Right
        self.quad_tex((x1,y0,z1),(x1,y0,z0),(x1,y1,z0),(x1,y1,z1),
                      (0.0,0.0),(uv_scale,0.0),(uv_scale,uv_scale),(0.0,uv_scale))
        # Top
        self.quad_tex((x0,y1,z1),(x1,y1,z1),(x1,y1,z0),(x0,y1,z0),
                      (0.0,0.0),(uv_scale,0.0),(uv_scale,uv_scale),(0.0,uv_scale))
        # Bottom
        self.quad_tex((x0,y0,z0),(x1,y0,z0),(x1,y0,z1),(x0,y0,z1),
                      (0.0,0.0),(uv_scale,0.0),(uv_scale,uv_scale),(0.0,uv_scale))

    def disc_fan_col(self, cx, cy, cz, radius, segments, c, normal_up=True):
        TWO_PI = math.pi * 2.0
        for i in range(segments):
            a0 = (i/segments)*TWO_PI; a1 = ((i+1)/segments)*TWO_PI
            x0 = cx + math.cos(a0)*radius; z0 = cz + math.sin(a0)*radius
            x1 = cx + math.cos(a1)*radius; z1 = cz + math.sin(a1)*radius
            if normal_up:
                self.tri_col((cx,cy,cz),(x0,cy,z0),(x1,cy,z1), c)
            else:
                self.tri_col((cx,cy,cz),(x1,cy,z1),(x0,cy,z0), c)

    def disc_fan_tex(self, cx, cy, cz, radius, segments, uv_center=(0.5, 0.5), uv_radius=0.5, normal_up=True):
        # Textured disc in the XZ plane (like coin faces).
        TWO_PI = math.pi * 2.0
        uc, vc = uv_center
        for i in range(segments):
            a0 = (i / segments) * TWO_PI; a1 = ((i + 1) / segments) * TWO_PI
            x0 = cx + math.cos(a0)*radius; z0 = cz + math.sin(a0)*radius
            x1 = cx + math.cos(a1)*radius; z1 = cz + math.sin(a1)*radius
            u0 = uc + math.cos(a0)*uv_radius; v0 = vc + math.sin(a0)*uv_radius
            u1 = uc + math.cos(a1)*uv_radius; v1 = vc + math.sin(a1)*uv_radius
            if normal_up:
                self.data.extend([cx, cy, cz, uc, vc, x0, cy, z0, u0, v0, x1, cy, z1, u1, v1])
            else:
                self.data.extend([cx, cy, cz, uc, vc, x1, cy, z1, u1, v1, x0, cy, z0, u0, v0])

    def cylinder_side_col(self, cx, cy0, cz, cy1, radius, segments, c):
        TWO_PI = math.pi * 2.0
        for i in range(segments):
            a0 = (i/segments)*TWO_PI; a1 = ((i+1)/segments)*TWO_PI
            x0 = cx + math.cos(a0)*radius; z0 = cz + math.sin(a0)*radius
            x1 = cx + math.cos(a1)*radius; z1 = cz + math.sin(a1)*radius
            self.quad_col((x0,cy0,z0),(x1,cy0,z1),(x1,cy1,z1),(x0,cy1,z0), c)

    def coin_col(self, cx, cy, cz, radius=0.14, thickness=0.04, segments=16):
        # Gold coin at (cx, cy, cz), flat along Y.
        y0, y1 = cy - thickness/2.0, cy + thickness/2.0
        TWO_PI = math.pi * 2.0
        gold1 = (1.0, 0.84, 0.18, 0.98)
        gold2 = (240/255, 168/255, 48/255, 0.98)
        for i in range(segments):
            a0 = (i/segments)*TWO_PI; a1 = ((i+1)/segments)*TWO_PI
            x0 = cx + math.cos(a0)*radius; z0 = cz + math.sin(a0)*radius
            x1 = cx + math.cos(a1)*radius; z1 = cz + math.sin(a1)*radius
            c = gold1 if i % 2 == 0 else gold2
            self.quad_col((x0,y0,z0),(x1,y0,z1),(x1,y1,z1),(x0,y1,z0), c)
        self.disc_fan_col(cx, y1, cz, radius, segments, gold1)
        self.disc_fan_col(cx, y0, cz, radius, segments, gold1, normal_up=False)

    def key_col(self, cx, cy, cz, scale=1.0):
        # Simple key silhouette (ring + shaft + teeth).
        s = scale
        SILVER = (0.72, 0.72, 0.82, 0.95)
        self.cylinder_side_col(cx+0.23*s, cy-0.06*s, cz, cy+0.18*s, 0.16*s, 16, SILVER)
        self.cube_col(cx-0.12*s, cy+0.06*s, cz, 0.26*s, 0.06*s, 0.08*s, SILVER)
        for tx, th in ((-0.34*s, 0.06*s), (-0.25*s, 0.045*s), (-0.18*s, 0.035*s)):
            self.cube_col(cx+tx, cy+0.02*s, cz, 0.03*s, th, 0.08*s, SILVER)

    def key_col_custom(self, cx, cy, cz, scale=1.0, color=(0.72, 0.72, 0.82, 0.95)):
        s = scale
        self.ring_col(cx+0.23*s, cy+0.06*s, cz, 0.16*s, 0.11*s, 0.035*s, 24, color)
        self.cube_col(cx-0.12*s, cy+0.06*s, cz, 0.26*s, 0.03*s, 0.04*s, color)
        for tx, th in ((-0.34*s, 0.12*s), (-0.25*s, 0.09*s), (-0.18*s, 0.07*s)):
            self.cube_col(cx+tx, cy+0.02*s, cz, 0.03*s, th*0.5, 0.04*s, color)

    def ring_col(self, cx, cy, cz, outer_r, inner_r, thickness, segments, color):
        TWO_PI = math.pi * 2
        for i in range(segments):
            a0, a1 = TWO_PI * (i / segments), TWO_PI * ((i + 1) / segments)
            c0, s0, c1, s1 = math.cos(a0), math.sin(a0), math.cos(a1), math.sin(a1)
            
            # Outer face
            self.quad_col(
                (cx + outer_r*c0, cy - thickness, cz + outer_r*s0),
                (cx + outer_r*c1, cy - thickness, cz + outer_r*s1),
                (cx + outer_r*c1, cy + thickness, cz + outer_r*s1),
                (cx + outer_r*c0, cy + thickness, cz + outer_r*s0),
                color
            )
            # Inner face
            self.quad_col(
                (cx + inner_r*c1, cy - thickness, cz + inner_r*s1),
                (cx + inner_r*c0, cy - thickness, cz + inner_r*s0),
                (cx + inner_r*c0, cy + thickness, cz + inner_r*s0),
                (cx + inner_r*c1, cy + thickness, cz + inner_r*s1),
                color
            )
            # Top face
            self.quad_col(
                (cx + inner_r*c0, cy + thickness, cz + inner_r*s0),
                (cx + inner_r*c1, cy + thickness, cz + inner_r*s1),
                (cx + outer_r*c1, cy + thickness, cz + outer_r*s1),
                (cx + outer_r*c0, cy + thickness, cz + outer_r*s0),
                color
            )
            # Bottom face
            self.quad_col(
                (cx + outer_r*c0, cy - thickness, cz + outer_r*s0),
                (cx + outer_r*c1, cy - thickness, cz + outer_r*s1),
                (cx + inner_r*c1, cy - thickness, cz + inner_r*s1),
                (cx + inner_r*c0, cy - thickness, cz + inner_r*s0),
                color
            )

    def ghost_col(self, cx, cy, cz, scale, color, anim_t, segments: int = 26):
        # Ghost shape
        r = 0.20 * scale
        seg = segments
        body_layers = 11
        tail_layers = 8
        TWO_PI = math.pi * 2.0

        def y_and_r(t):
            if t < 0.5:
                return r*0.62*math.cos(t*math.pi), r*0.95*math.sin(t*math.pi)
            return -r*0.25*(t-0.5)*2.0, r*0.95

        # Body
        for layer in range(1, body_layers):
            y_prev, r_prev = y_and_r((layer-1)/(body_layers-1))
            y_curr, r_curr = y_and_r(layer/(body_layers-1))
            for i in range(seg):
                a0=(i/seg)*TWO_PI;   a1=((i+1)/seg)*TWO_PI
                ca0,sa0=math.cos(a0),math.sin(a0)
                ca1,sa1=math.cos(a1),math.sin(a1)
                self.quad_col(
                    (cx+ca0*r_prev, cy+y_prev, cz+sa0*r_prev),
                    (cx+ca1*r_prev, cy+y_prev, cz+sa1*r_prev),
                    (cx+ca1*r_curr, cy+y_curr, cz+sa1*r_curr),
                    (cx+ca0*r_curr, cy+y_curr, cz+sa0*r_curr),
                    color)

        # Tail
        for layer in range(tail_layers):
            layer_ratio  = layer / tail_layers
            prev_ratio   = (layer-1) / tail_layers
            base_r       = r*0.95*(1.0 - layer_ratio*0.35)
            wave_amp     = r*(0.08 + 0.14*layer_ratio)
            y_curr_abs   = cy - r*0.52 - layer_ratio*r*0.48

            if layer == 0:
                y_prev_abs = cy - r*0.25
                pr_prev    = r*0.95
            else:
                y_prev_abs = cy - r*0.52 - prev_ratio*r*0.48
                pr_prev    = r*0.95*(1.0 - prev_ratio*0.35)
            prev_amp = r*(0.08 + 0.14*prev_ratio)

            for i in range(seg):
                a =(i/seg)*TWO_PI; a1=((i+1)/seg)*TWO_PI
                sk_c0=(math.sin(a *3.0+anim_t*2.4+layer*0.55)*wave_amp
                      +math.sin(a *7.0-anim_t*1.7+layer*0.35)*(wave_amp*0.55))
                sk_c1=(math.sin(a1*3.0+anim_t*2.4+layer*0.55)*wave_amp
                      +math.sin(a1*7.0-anim_t*1.7+layer*0.35)*(wave_amp*0.55))
                if layer == 0:
                    sk_p0 = sk_p1 = 0.0
                else:
                    sk_p0=(math.sin(a *3.0+anim_t*2.4+(layer-1)*0.55)*prev_amp
                          +math.sin(a *7.0-anim_t*1.7+(layer-1)*0.35)*(prev_amp*0.55))
                    sk_p1=(math.sin(a1*3.0+anim_t*2.4+(layer-1)*0.55)*prev_amp
                          +math.sin(a1*7.0-anim_t*1.7+(layer-1)*0.35)*(prev_amp*0.55))
                rc0=max(r*0.02, base_r+sk_c0); rc1=max(r*0.02, base_r+sk_c1)
                rp0=max(r*0.02, pr_prev+sk_p0); rp1=max(r*0.02, pr_prev+sk_p1)
                ca0,sa0=math.cos(a), math.sin(a)
                ca1,sa1=math.cos(a1),math.sin(a1)
                self.quad_col(
                    (cx+ca0*rp0, y_prev_abs, cz+sa0*rp0),
                    (cx+ca1*rp1, y_prev_abs, cz+sa1*rp1),
                    (cx+ca1*rc1, y_curr_abs, cz+sa1*rc1),
                    (cx+ca0*rc0, y_curr_abs, cz+sa0*rc0),
                    color)

        # Eyes
        eye_y   = cy + r*0.22
        eye_z_f = r*1.05
        eye_x_o = r*0.34
        ew = r*0.22; eh = r*0.28
        BLACK = (0.06, 0.06, 0.08, 0.96)
        for ex in (-eye_x_o, eye_x_o):
            x0,x1 = cx+ex-ew, cx+ex+ew
            y0,y1 = eye_y-eh, eye_y+eh
            ez = cz + eye_z_f
            self.quad_col((x0,y0,ez),(x1,y0,ez),(x1,y1,ez),(x0,y1,ez), BLACK)

    def spike_col(self, cx, cz, height):
        if height <= 0.02:
            return
        base = 0.18
        RED = (0.85, 0.15, 0.15, 1.0)
        y_base = 0.01
        y_tip = height
        self.disc_fan_col(cx, y_base, cz, base, 8, RED)
        seg = 8
        TWO_PI = math.pi * 2.0
        for i in range(seg):
            a0 = (i/seg)*TWO_PI; a1 = ((i+1)/seg)*TWO_PI
            x0 = cx + math.cos(a0)*base; z0 = cz + math.sin(a0)*base
            x1 = cx + math.cos(a1)*base; z1 = cz + math.sin(a1)*base
            self.tri_col((x0,y_base,z0),(x1,y_base,z1),(cx,y_tip,cz), RED)

    def gate_bars_col(self, gx, gy_center, gz, wall_h, y_offset, is_jail):
        # Vertical bars for a gate
        GRAY = (0.70, 0.70, 0.75, 1.0)
        bar_h = wall_h
        bar_y_center = gy_center + y_offset
        for i in range(-2, 3):
            if is_jail:
                bx = gx + i * 0.18; bz = gz
            else:
                bx = gx; bz = gz + i * 0.18
            self.cube_col(bx, bar_y_center, bz, 0.035, bar_h*0.5, 0.06, GRAY)

    def gate_bars_tex(self, gx, gy_center, gz, wall_h, y_offset, is_jail):
        # Textured bars
        bar_h = wall_h
        bar_y_center = gy_center + y_offset
        for i in range(-2, 3):
            if is_jail:
                bx = gx + i * 0.18; bz = gz
            else:
                bx = gx; bz = gz + i * 0.18

            self.cube_tex(bx, bar_y_center, bz, 0.035, bar_h*0.5, 0.06, uv_scale=2.0)
        if is_jail:
            self.cube_tex(gx, bar_y_center + bar_h*0.42, gz, 0.47, 0.06, 0.08, uv_scale=2.0)
        else:
            self.cube_tex(gx, bar_y_center + bar_h*0.42, gz, 0.08, 0.06, 0.47, uv_scale=2.0)

    def platform_col(self, cx, cy, cz):
        BROWN = (0.6, 0.4, 0.2, 1.0)
        DARK  = (0.4, 0.3, 0.15, 1.0)
        self.cube_col(cx, cy+0.05, cz, 0.4, 0.05, 0.4, BROWN)
        self.cube_col(cx,       cy+0.15, cz+0.35, 0.41, 0.10, 0.025, DARK)
        self.cube_col(cx,       cy+0.15, cz-0.35, 0.41, 0.10, 0.025, DARK)
        self.cube_col(cx+0.35,  cy+0.15, cz,      0.025, 0.10, 0.41, DARK)
        self.cube_col(cx-0.35,  cy+0.15, cz,      0.025, 0.10, 0.41, DARK)

    def platform_tex(self, cx, cy, cz):
        # Textured moving platform
        self.cube_tex(cx, cy+0.05, cz, 0.4, 0.05, 0.4, uv_scale=1.0)
        self.cube_tex(cx,       cy+0.15, cz+0.35, 0.41, 0.10, 0.025, uv_scale=1.0)
        self.cube_tex(cx,       cy+0.15, cz-0.35, 0.41, 0.10, 0.025, uv_scale=1.0)
        self.cube_tex(cx+0.35,  cy+0.15, cz,      0.025, 0.10, 0.41, uv_scale=1.0)
        self.cube_tex(cx-0.35,  cy+0.15, cz,      0.025, 0.10, 0.41, uv_scale=1.0)

    def table_book_col(self, cx, cy, cz, glow_pulse):
        BROWN = (0.35, 0.22, 0.10, 1.0)
        BOOK  = (0.12, 0.12, 0.14, 1.0)
        self.cube_col(cx, cy+0.40, cz, 0.425, 0.04, 0.30, BROWN)
        for lx in (-0.35, 0.35):
            for lz in (-0.22, 0.22):
                self.cube_col(cx+lx, cy+0.20, cz+lz, 0.04, 0.20, 0.04, BROWN)
        self.cube_col(cx, cy+0.48, cz, 0.14, 0.02, 0.10, BOOK)
        GLOW = (0.95, 0.85, 0.35, min(0.6, glow_pulse))
        self.disc_fan_col(cx, cy+0.01, cz, 0.55, 16, GLOW)

    def table_tex_book_col(self, cx, cy, cz, glow_pulse):
        # Table texture
        self.cube_tex(cx, cy+0.40, cz, 0.425, 0.04, 0.30, uv_scale=1.0)
        for lx in (-0.35, 0.35):
            for lz in (-0.22, 0.22):
                self.cube_tex(cx+lx, cy+0.20, cz+lz, 0.04, 0.20, 0.04, uv_scale=1.0)

    def table_book_col_glow(self, cx, cy, cz, glow_pulse):
        # Book only (no glow)
        BOOK = (0.12, 0.12, 0.14, 1.0)
        self.cube_col(cx, cy+0.48, cz, 0.14, 0.02, 0.10, BOOK)

    def lamp_col(self, cx, cz, ceil_h):
        DARK  = (0.10, 0.10, 0.12, 1.0)
        METAL = (0.18, 0.18, 0.22, 1.0)
        WARM  = (0.98, 0.95, 0.82, 1.0)
        self.cube_col(cx, ceil_h-0.15+0.18, cz, 0.015, 0.18, 0.015, DARK)
        self.cube_col(cx, ceil_h-0.15+0.02, cz, 0.13,  0.05, 0.13,  METAL)
        self.cube_col(cx, ceil_h-0.15-0.02, cz, 0.05,  0.035, 0.05,  WARM)

    def arrow3d_col(self, cx: float, cy: float, cz: float, *, col: Tuple[float, float, float, float],
                    shaft_r: float = 0.12, shaft_h: float = 0.60,
                    head_r: float = 0.30, head_h: float = 0.42, seg: int = 32) -> None:
        r, g, b, a = col
        shaft_top = shaft_h * 0.5
        shaft_bot = -shaft_h * 0.5
        tip_y = shaft_bot - head_h
        TWO_PI = math.pi * 2.0
        for i in range(seg):
            a0 = (i/seg)*TWO_PI; a1 = ((i+1)/seg)*TWO_PI
            ca0,sa0 = math.cos(a0),math.sin(a0)
            ca1,sa1 = math.cos(a1),math.sin(a1)
            p0 = (cx+ca0*shaft_r, cy+shaft_top, cz+sa0*shaft_r)
            p1 = (cx+ca1*shaft_r, cy+shaft_top, cz+sa1*shaft_r)
            p2 = (cx+ca1*shaft_r, cy+shaft_bot, cz+sa1*shaft_r)
            p3 = (cx+ca0*shaft_r, cy+shaft_bot, cz+sa0*shaft_r)
            self.quad_col(p0, p1, p2, p3, (r,g,b,a))
        apex = (cx, cy+tip_y, cz)
        for i in range(seg):
            a0 = (i/seg)*TWO_PI; a1 = ((i+1)/seg)*TWO_PI
            ca0,sa0 = math.cos(a0),math.sin(a0)
            ca1,sa1 = math.cos(a1),math.sin(a1)
            b0 = (cx+ca0*head_r, cy+shaft_bot, cz+sa0*head_r)
            b1 = (cx+ca1*head_r, cy+shaft_bot, cz+sa1*head_r)
            self.tri_col(b0, b1, apex, (r,g,b,a))

    def sign_col(self, cx, cy, cz, facing, w, h):
        DARK = (0.10, 0.10, 0.12, 0.92)
        off = 0.482
        if facing == 'N':
            z = cz - off
            self.quad_col((cx-w,cy-h,z),(cx+w,cy-h,z),(cx+w,cy+h,z),(cx-w,cy+h,z), DARK)
        elif facing == 'S':
            z = cz + off
            self.quad_col((cx+w,cy-h,z),(cx-w,cy-h,z),(cx-w,cy+h,z),(cx+w,cy+h,z), DARK)
        elif facing == 'W':
            x = cx - off
            self.quad_col((x,cy-h,cz+w),(x,cy-h,cz-w),(x,cy+h,cz-w),(x,cy+h,cz+w), DARK)
        else:
            x = cx + off
            self.quad_col((x,cy-h,cz-w),(x,cy-h,cz+w),(x,cy+h,cz+w),(x,cy+h,cz-w), DARK)


class KivyRenderer:
    def __init__(self, core: GameCore):
        self.core = core
        self.width  = 800
        self.height = 600

        # Ghost segments: 26 (fast_mode) / 40
        self._fast_mode: bool = True

        self._anim_t: float = 0.0
        self._last_anim_t: Optional[float] = None

        # GL handles
        self._tex_prog: int  = 0
        self._col_prog: int  = 0
        self._tex_wall: Optional[int] = None
        self._tex_floor: Optional[int] = None
        self._tex_coin: Optional[int] = None
        self._jail_map_texture: Optional[int] = None
        self._jail_map_fbo = None  # Keep Fbo reference to prevent GC

        # Static world VAOs
        self._wall_vao:  int = 0;  self._wall_vtx:  int = 0
        self._floor_vao: int = 0;  self._floor_vtx: int = 0

        # Dynamic VAO
        self._dyn_vao: int = 0;  self._dyn_vtx: int = 0
        self._dyn_vbo: int = 0

        # Dynamic textured VAO (coins decals + sector sign text)
        self._dyn_tex_vao: int = 0
        self._dyn_tex_vtx: int = 0
        self._dyn_tex_vbo: int = 0

        # Text texture cache with 200 entry max
        self._text_tex_cache: Dict[str, Tuple[int, int, int]] = {}

        # Lamp VAO (static, built once)
        self._lamp_vao: int = 0; self._lamp_vtx: int = 0
        self._lamps: List[Tuple[int, int]] = []

        # Ghost particle
        from collections import deque as _deque
        self._ghost_trails: Dict[int, Any] = {}
        self._ghost_trail_deque = _deque  # keep reference for later use
        self._ghost_trail_last_sample: Dict[int, float] = {}
        _TRAIL_SAMPLE_INTERVAL = 0.05  # seconds between trail position samples
        self._TRAIL_SAMPLE_INTERVAL = _TRAIL_SAMPLE_INTERVAL
        self._TRAIL_MAX_POINTS = 60    # max positions stored per ghost

        self._gl_ready = False

    def initialize(self) -> None:
        start_time = time.perf_counter()

        self._anim_t = 0.0
        self._last_anim_t = None

        try:
            self._tex_prog = _build_program(_TEXTURED_VERT, _TEXTURED_FRAG)
            self._col_prog = _build_program(_COLORED_VERT,  _COLORED_FRAG)
        except Exception as e:
            print(f"[KivyRenderer] shader compile failed: {e}")
            raise

        self._tex_wall  = (_load_texture_from_path(os.path.join('assets','image.png'))
                           or _make_fallback_texture((180, 90, 60, 255)))
        self._tex_floor = (_load_texture_from_path(os.path.join('assets','path.png'))
                           or _make_fallback_texture((80, 80, 100, 255)))

        self._tex_coin = _load_texture_from_path(os.path.join('assets', 'JEMA GER 1640-11.png'))
        if self._tex_coin:
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._tex_coin)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

        self._tex_gate = _load_texture_from_path(os.path.join('assets', 'jail.jpg'))
        if self._tex_gate:
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._tex_gate)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

        self._tex_platform = _load_texture_from_path(os.path.join('assets', 'wood.jpg'))
        if self._tex_platform:
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._tex_platform)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

        self._build_world_vao()
        self._build_lamp_vao()

        self._dyn_vbo = GL.glGenBuffers(1)
        self._dyn_tex_vbo = GL.glGenBuffers(1)

        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthFunc(GL.GL_LEQUAL)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glDisable(GL.GL_CULL_FACE)

        self._gl_ready = True

        load_time = time.perf_counter() - start_time
        
        # texture loading time PerformanceMonitor
        tex_load_ms = load_time * 1000
        try:
            perf = getattr(self.core, '_performance_monitor', None)
            if perf:
                perf.record_texture_load_time(tex_load_ms)
        except Exception:
            pass
        
        # OpenGL info PDF report
        try:
            from core.pdf_export import get_system_collector
            collector = get_system_collector()
            try:
                vendor   = GL.glGetString(GL.GL_VENDOR)
                renderer = GL.glGetString(GL.GL_RENDERER)
                version  = GL.glGetString(GL.GL_VERSION)
                collector.record_opengl_info(vendor, renderer, version)
            except Exception:
                pass
        except ImportError:
            pass

        print("[KivyRenderer] initialized")

    def _get_text_texture(self, text: str) -> Optional[Tuple[int, int, int]]:
        t = str(text or '')
        if not t:
            return None
        cached = self._text_tex_cache.get(t)
        if cached:
            return cached

        # 200 entry LRU eviction
        if len(self._text_tex_cache) >= 200:
            keys_to_remove = list(self._text_tex_cache.keys())[:50]
            for key in keys_to_remove:
                tex_id, _, _ = self._text_tex_cache.pop(key)
                try:
                    if tex_id > 0:
                        GL.glDeleteTextures(1, [int(tex_id)])
                except Exception:
                    pass

        tex_start = time.perf_counter()
        try:
            lbl = CoreLabel(text=t, font_size=22, bold=True, color=(255/255, 235/255, 120/255, 1))
            lbl.refresh()
            tex = lbl.texture
            if not tex:
                return None
            w, h = tex.size
            pixels = _flip_rgba_v(tex.pixels, int(w), int(h))

            gl_tex = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, gl_tex)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, w, h, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, pixels)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            out = (int(gl_tex), int(w), int(h))
            self._text_tex_cache[t] = out

            # Record texture generation time (ms)
            tex_duration_ms = (time.perf_counter() - tex_start) * 1000
            try:
                perf = getattr(self.core, '_performance_monitor', None)
                if perf:
                    perf.record_texture_generation(tex_duration_ms)
            except Exception:
                pass

            return out
        except Exception:
            return None

    def _get_jail_map_texture(self) -> int:
        # sector map texture FBO
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

        # FBO for off-screen rendering
        from kivy.graphics import Fbo, ClearColor, ClearBuffers, Color, Rectangle
        fbo = Fbo(size=(w, h), with_depthbuffer=False)
        
        # canvas instructions for map
        with fbo:
            ClearColor(0.196, 0.165, 0.141, 1.0)  # (50, 42, 36) / 255
            ClearBuffers()
            
            palette = {
                'A': (0.314, 0.471, 0.784),  # (80, 120, 200)
                'B': (0.706, 0.510, 0.314),  # (180, 130, 80)
                'C': (0.314, 0.706, 0.392),  # (80, 180, 100)
                'D': (0.431, 0.706, 0.706),  # (110, 180, 180)
                'E': (0.706, 0.392, 0.549),  # (180, 100, 140)
                'F': (0.706, 0.706, 0.353),  # (180, 180, 90)
                'G': (0.627, 0.392, 0.745),  # (160, 100, 190)
                'H': (0.588, 0.588, 0.588),  # (150, 150, 150)
            }
            
            walls = getattr(self.core, 'walls', set()) or set()
            sid_for = getattr(self.core, 'sector_id_for_cell', None)
            
            acc: Dict[str, Tuple[float, float, int]] = {}
            for r in range(grid_h):
                for c in range(grid_w):
                    if (r, c) in walls:
                        continue
                    try:
                        sid = str(sid_for((r, c)) or '') if callable(sid_for) else ''
                    except Exception:
                        sid = ''
                    col = palette.get(sid)
                    if not col:
                        continue
                    sx, sy, n = acc.get(sid, (0.0, 0.0, 0))
                    acc[sid] = (sx + float(r), sy + float(c), n + 1)
                    x0 = int(ox + c * cell)
                    y0 = int(oy + r * cell)
                    cell_size = int(cell) + 1  # +1 for overlap
                    Color(*col)
                    Rectangle(pos=(x0, h - y0 - cell_size), size=(cell_size, cell_size))
            
            for sid, (sx, sy, n) in acc.items():
                if n <= 0:
                    continue
                cr = sx / float(n)
                cc = sy / float(n)
                px = ox + (cc + 0.5) * cell
                py = oy + (cr + 0.5) * cell
                label = str(sid)[:1]
                
                lbl = CoreLabel(text=label, font_size=56, bold=True, 
                               color=(0.039, 0.039, 0.047, 1.0))  # (10, 10, 12)
                lbl.refresh()
                tex = lbl.texture
                if tex:
                    tw, th = tex.size
                    lx = int(px - tw / 2)
                    ly = int(h - py - th / 2)  # Flip Y for OpenGL
                    Color(1, 1, 1, 1)
                    Rectangle(pos=(lx, ly), size=(tw, th), texture=tex)
            
            # exit label
            if getattr(self.core, 'exit_cells', None):
                try:
                    er, ec = self.core.exit_cells[0]
                    px = ox + (float(ec) + 0.5) * cell + 5
                    py = oy + (float(er) + 0.5) * cell
                    
                    rect_w, rect_h = 64, 26
                    Color(0.824, 0.745, 0.686, 0.784)  # (210, 190, 175, 200)
                    Rectangle(pos=(int(px - rect_w//2), h - int(py + rect_h//2)), 
                             size=(rect_w, rect_h))
                    
                    lbl = CoreLabel(text="exit", font_size=22, bold=True,
                                   color=(0.059, 0.059, 0.063, 1.0))  # (15, 15, 16)
                    lbl.refresh()
                    tex = lbl.texture
                    if tex:
                        tw, th = tex.size
                        lx = int(px - tw / 2)
                        ly = int(h - py - th / 2 - 2)
                        Color(1, 1, 1, 1)
                        Rectangle(pos=(lx, ly), size=(tw, th), texture=tex)
                except Exception:
                    pass

        # Render and get pixels
        fbo.draw()
        pixels = fbo.pixels  # RGBA bytes, bottom-up
        fbo.clear()
        
        # Flip vertically
        pixels_flipped = _flip_rgba_v(pixels, w, h)
        
        # OpenGL texture
        tex_id = GL.glGenTextures(1)
        if not tex_id:
            return 0
        
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex_id)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        
        try:
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, w, h, 0,
                           GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, pixels_flipped)
        except Exception:
            GL.glDeleteTextures(1, [tex_id])
            return 0
        finally:
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        
        self._jail_map_texture = tex_id
        return int(tex_id)

    def resize(self, w: int, h: int) -> None:
        self.width  = max(1, w)
        self.height = max(1, h)

    def _build_world_vao(self) -> None:
        _delete_vao(self._wall_vao)
        _delete_vao(self._floor_vao)

        wall_h = float(self.core.wall_height)
        ceil_h = float(self.core.ceiling_height)
        walls  = self.core.walls
        floors = self.core.floors
        H      = self.core.height
        W      = self.core.width

        def solid(r, c): return (r,c) in walls
        def inside(r, c): return 0 <= r < H and 0 <= c < W

        wb = _GeoBuilder(textured=True)
        for (r, c) in walls:
            cx, cz = c + 0.5, r + 0.5
            for (dr, dc, face) in [(-1,0,'N'),(1,0,'S'),(0,-1,'W'),(0,1,'E')]:
                if not solid(r+dr, c+dc):
                    # UV tiling: horizontal wraps once (0-1), vertical tiles by wall height (0-wall_h)
                    if face == 'N':
                        wb.quad_tex((cx-0.5,0,cz-0.5),(cx+0.5,0,cz-0.5),(cx+0.5,wall_h,cz-0.5),(cx-0.5,wall_h,cz-0.5),(0,0),(1,0),(1,wall_h),(0,wall_h))
                    elif face == 'S':
                        wb.quad_tex((cx+0.5,0,cz+0.5),(cx-0.5,0,cz+0.5),(cx-0.5,wall_h,cz+0.5),(cx+0.5,wall_h,cz+0.5),(0,0),(1,0),(1,wall_h),(0,wall_h))
                    elif face == 'W':
                        wb.quad_tex((cx-0.5,0,cz+0.5),(cx-0.5,0,cz-0.5),(cx-0.5,wall_h,cz-0.5),(cx-0.5,wall_h,cz+0.5),(0,0),(1,0),(1,wall_h),(0,wall_h))
                    else:
                        wb.quad_tex((cx+0.5,0,cz-0.5),(cx+0.5,0,cz+0.5),(cx+0.5,wall_h,cz+0.5),(cx+0.5,wall_h,cz-0.5),(0,0),(1,0),(1,wall_h),(0,wall_h))
            exposed = any(not solid(r+dr, c+dc) for dr,dc in ((-1,0),(1,0),(0,-1),(0,1)))
            if exposed and wall_h < ceil_h:
                wb.quad_tex((cx-0.5,wall_h,cz+0.5),(cx+0.5,wall_h,cz+0.5),(cx+0.5,wall_h,cz-0.5),(cx-0.5,wall_h,cz-0.5),(0,0),(1,0),(1,1),(0,1))

        for (r, c) in floors:
            cx, cz = c+0.5, r+0.5
            for (dr, dc, face) in [(-1,0,'N'),(1,0,'S'),(0,-1,'W'),(0,1,'E')]:
                if not inside(r+dr, c+dc):
                    # UV tiling: horizontal wraps once (0-1), vertical tiles by wall height (0-wall_h)
                    if face == 'N':
                        wb.quad_tex((cx-0.5,0,cz-0.5),(cx+0.5,0,cz-0.5),(cx+0.5,wall_h,cz-0.5),(cx-0.5,wall_h,cz-0.5),(0,0),(1,0),(1,wall_h),(0,wall_h))
                    elif face == 'S':
                        wb.quad_tex((cx+0.5,0,cz+0.5),(cx-0.5,0,cz+0.5),(cx-0.5,wall_h,cz+0.5),(cx+0.5,wall_h,cz+0.5),(0,0),(1,0),(1,wall_h),(0,wall_h))
                    elif face == 'W':
                        wb.quad_tex((cx-0.5,0,cz+0.5),(cx-0.5,0,cz-0.5),(cx-0.5,wall_h,cz-0.5),(cx-0.5,wall_h,cz+0.5),(0,0),(1,0),(1,wall_h),(0,wall_h))
                    else:
                        wb.quad_tex((cx+0.5,0,cz-0.5),(cx+0.5,0,cz+0.5),(cx+0.5,wall_h,cz+0.5),(cx+0.5,wall_h,cz-0.5),(0,0),(1,0),(1,wall_h),(0,wall_h))

        self._wall_vao, self._wall_vtx = _upload_vao_textured(wb.data)

        fb = _GeoBuilder(textured=True)
        for (r, c) in floors:
            cx, cz = c+0.5, r+0.5
            fb.quad_tex((cx-0.5,0,cz-0.5),(cx+0.5,0,cz-0.5),(cx+0.5,0,cz+0.5),(cx-0.5,0,cz+0.5),(0,0),(1,0),(1,1),(0,1))
            fb.quad_tex((cx-0.5,ceil_h,cz+0.5),(cx+0.5,ceil_h,cz+0.5),(cx+0.5,ceil_h,cz-0.5),(cx-0.5,ceil_h,cz-0.5),(0,0),(1,0),(1,1),(0,1))

        self._floor_vao, self._floor_vtx = _upload_vao_textured(fb.data)

    def _build_lamp_vao(self) -> None:
        # Prebuild ceiling lamp
        _delete_vao(self._lamp_vao)
        ceil_h = float(self.core.ceiling_height)
        floors = self.core.floors
        walls  = self.core.walls

        def is_floor(r, c): return (r,c) in floors and (r,c) not in walls

        # exclusion zones for lamp
        exclusion_zones = set()
        
        # all gate cells
        exclusion_zones.update(self.core.gate_cells)
        
        # 'd' gate
        gate_cells = []
        if hasattr(self.core, 'layout') and self.core.layout:
            for r, row in enumerate(self.core.layout):
                for c, char in enumerate(row):
                    if char == 'd':
                        gate_cells.append((r, c))
        
        # Exclude from start cells to nearest gate
        for start_cell in self.core.start_cells:
            if gate_cells:
                nearest_gate = min(gate_cells, key=lambda g: abs(g[0] - start_cell[0]) + abs(g[1] - start_cell[1]))
                min_r, max_r = min(start_cell[0], nearest_gate[0]), max(start_cell[0], nearest_gate[0])
                min_c, max_c = min(start_cell[1], nearest_gate[1]), max(start_cell[1], nearest_gate[1])
                for r in range(min_r, max_r + 1):
                    for c in range(min_c, max_c + 1):
                        exclusion_zones.add((r, c))
        
        # Exclude from exit cells to nearest gate
        for exit_cell in self.core.exit_cells:
            if gate_cells:
                nearest_gate = min(gate_cells, key=lambda g: abs(g[0] - exit_cell[0]) + abs(g[1] - exit_cell[1]))
                min_r, max_r = min(exit_cell[0], nearest_gate[0]), max(exit_cell[0], nearest_gate[0])
                min_c, max_c = min(exit_cell[1], nearest_gate[1]), max(exit_cell[1], nearest_gate[1])
                for r in range(min_r, max_r + 1):
                    for c in range(min_c, max_c + 1):
                        exclusion_zones.add((r, c))

        candidates = []
        for (r, c) in floors:
            if (r,c) in walls or (r,c) in exclusion_zones: continue
            if is_floor(r,c-1) and is_floor(r,c+1) and not is_floor(r,c-2) and not is_floor(r,c+2):
                candidates.append((r,c)); continue
            if is_floor(r-1,c) and is_floor(r+1,c) and not is_floor(r-2,c) and not is_floor(r+2,c):
                candidates.append((r,c))
        candidates.sort()
        lamps: List[Tuple[int, int]] = []
        min_sep2 = 8.0**2
        for rc in candidates:
            if all(((rc[0]-lr)**2+(rc[1]-lc)**2) >= min_sep2 for lr,lc in lamps):
                lamps.append(rc)
            if len(lamps) >= 140: break

        self._lamps = list(lamps)

        gb = _GeoBuilder(textured=False)
        for r, c in lamps:
            gb.lamp_col(c+0.5, r+0.5, ceil_h)
        self._lamp_vao, self._lamp_vtx = _upload_vao_colored(gb.data)

    def _set_fog_uniforms(self, prog: int) -> None:
        GL.glUniform1f(GL.glGetUniformLocation(prog, b"uFogStart"), _FOG_START)
        GL.glUniform1f(GL.glGetUniformLocation(prog, b"uFogEnd"),   _FOG_END)
        GL.glUniform4f(GL.glGetUniformLocation(prog, b"uFogColor"), *_SKY_COLOR)
        # dynamic light and flickering - player pos, time
        player = self.core.player
        GL.glUniform3f(GL.glGetUniformLocation(prog, b"uPlayerPos"), float(player.x), float(player.y), float(player.z))
        GL.glUniform1f(GL.glGetUniformLocation(prog, b"uTime"), self._anim_t)
        if prog == self._tex_prog:
            GL.glUniform1i(GL.glGetUniformLocation(prog, b"uEnableDynamicLight"), 1)
        if prog == self._col_prog:
            GL.glUniform1i(GL.glGetUniformLocation(prog, b"uEnableFlicker"), 0)

    def _set_no_fog_uniforms(self, prog: int) -> None:
        try:
            GL.glUniform1f(GL.glGetUniformLocation(prog, b"uFogStart"), 0.0)
            GL.glUniform1f(GL.glGetUniformLocation(prog, b"uFogEnd"),   1e9)
            GL.glUniform4f(GL.glGetUniformLocation(prog, b"uFogColor"), *_SKY_COLOR)
        except Exception:
            pass

    def _set_mvp(self, prog: int, mvp: List[float]) -> None:
        loc = GL.glGetUniformLocation(prog, b"uMVP")
        GL.glUniformMatrix4fv(loc, 1, GL.GL_FALSE, (ctypes.c_float * 16)(*mvp))

    def _draw_vao(self, vao: int, vtx: int) -> None:
        if not vao or vtx <= 0:
            return
        GL.glBindVertexArray(vao)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, vtx)
        GL.glBindVertexArray(0)

    def _draw_dynamic_tex(self, raw: _array, mvp: List[float], tex_id: int) -> None:
        if not raw or not tex_id:
            return
        self._set_mvp(self._tex_prog, mvp)
        self._set_fog_uniforms(self._tex_prog)
        self._dyn_tex_vao, self._dyn_tex_vtx = _update_dynamic_vao_textured(self._dyn_tex_vao, self._dyn_tex_vbo, raw)
        if self._dyn_tex_vtx <= 0:
            return
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex_id)
        GL.glUniform1i(GL.glGetUniformLocation(self._tex_prog, b"uTex"), 0)
        self._draw_vao(self._dyn_tex_vao, self._dyn_tex_vtx)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

    def _draw_dynamic_col(self, raw: _array, mvp: List[float]) -> None:
        if not raw:
            return
        vtx = len(raw) // 7
        data = raw.tobytes()
        stride = 7 * 4
        GL.glUseProgram(self._col_prog)
        self._set_mvp(self._col_prog, mvp)
        self._set_fog_uniforms(self._col_prog)
        if self._dyn_vao == 0:
            self._dyn_vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self._dyn_vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._dyn_vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, len(data), data, GL.GL_STREAM_DRAW)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(0))
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(1, 4, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(12))
        GL.glEnableVertexAttribArray(1)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, vtx)
        GL.glBindVertexArray(0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)

    def _draw_dynamic_col_with_flicker(self, raw: _array, mvp: List[float]) -> None:
        if not raw:
            return
        vtx = len(raw) // 7
        data = raw.tobytes()
        stride = 7 * 4
        GL.glUseProgram(self._col_prog)
        self._set_mvp(self._col_prog, mvp)
        GL.glUniform1f(GL.glGetUniformLocation(self._col_prog, b"uFogStart"), _FOG_START)
        GL.glUniform1f(GL.glGetUniformLocation(self._col_prog, b"uFogEnd"),   _FOG_END)
        GL.glUniform4f(GL.glGetUniformLocation(self._col_prog, b"uFogColor"), *_SKY_COLOR)
        player = self.core.player
        GL.glUniform3f(GL.glGetUniformLocation(self._col_prog, b"uPlayerPos"), float(player.x), float(player.y), float(player.z))
        GL.glUniform1f(GL.glGetUniformLocation(self._col_prog, b"uTime"), self._anim_t)
        GL.glUniform1i(GL.glGetUniformLocation(self._col_prog, b"uEnableFlicker"), 1)
        if self._dyn_vao == 0:
            self._dyn_vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self._dyn_vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._dyn_vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, len(data), data, GL.GL_STREAM_DRAW)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(0))
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(1, 4, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(12))
        GL.glEnableVertexAttribArray(1)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, vtx)
        GL.glBindVertexArray(0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)

    # ------------------------------------------------------------------
    def render(self, viewport_w: int, viewport_h: int) -> None:
        if not self._gl_ready:
            try:
                self.initialize()
            except Exception:
                import traceback
                traceback.print_exc()
                return

        now = time.perf_counter()
        if self._last_anim_t is None:
            self._last_anim_t = now
        else:
            dt = max(0.0, min(0.1, now - self._last_anim_t))
            self._last_anim_t = now
            if not bool(getattr(self.core, 'simulation_frozen', False)):
                self._anim_t += dt

        w = max(1, viewport_w)
        h = max(1, viewport_h)

        GL.glViewport(0, 0, w, h)
        GL.glClearColor(*_SKY_COLOR)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthMask(True)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

        player = self.core.player
        px = float(player.x); py = float(player.y) + _CAMERA_H; pz = float(player.z)
        yaw = float(player.yaw); pitch = float(player.pitch)

        # camera sway
        sway_time = self._anim_t * 3.0
        sway_offset_x = 0.0
        sway_offset_y = 0.0
        if not hasattr(self, '_prev_player_pos'):
            self._prev_player_pos = (px, pz)
        prev_px, prev_pz = self._prev_player_pos
        moved = math.sqrt((px - prev_px)**2 + (pz - prev_pz)**2) > 0.001
        self._prev_player_pos = (px, pz)
        if moved:
            sway_offset_y = math.sin(sway_time * 2.0) * 0.08
            sway_offset_x = math.cos(sway_time) * 0.04
        py += sway_offset_y
        px += sway_offset_x

        lx = px + math.sin(yaw)*math.cos(pitch)
        ly = py + math.sin(pitch)
        lz = pz + math.cos(yaw)*math.cos(pitch)

        fy = (ly - py)
        f_len = math.sqrt((lx-px)**2 + fy**2 + (lz-pz)**2)
        fy_norm = fy / (f_len or 1.0)
        upx, upy, upz = (1.0, 0.0, 0.0) if abs(fy_norm) > 0.97 else (0.0, 1.0, 0.0)

        proj = _perspective(_FOV_DEG, w/h, _NEAR, _FAR)
        view = _look_at(px, py, pz, lx, ly, lz, upx, upy, upz)
        vp   = _mat_mul(proj, view)

        GL.glUseProgram(self._tex_prog)
        self._set_fog_uniforms(self._tex_prog)
        self._set_mvp(self._tex_prog, vp)

        if self._tex_wall:
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._tex_wall)
            GL.glUniform1i(GL.glGetUniformLocation(self._tex_prog, b"uTex"), 0)
            self._draw_vao(self._wall_vao, self._wall_vtx)

        if self._tex_floor:
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._tex_floor)
            GL.glUniform1i(GL.glGetUniformLocation(self._tex_prog, b"uTex"), 0)
            self._draw_vao(self._floor_vao, self._floor_vtx)

        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

        GL.glUseProgram(self._col_prog)
        self._set_fog_uniforms(self._col_prog)
        self._set_mvp(self._col_prog, vp)
        GL.glUniform1i(GL.glGetUniformLocation(self._col_prog, b"uEnableFlicker"), 1)
        self._draw_vao(self._lamp_vao, self._lamp_vtx)
        GL.glUniform1i(GL.glGetUniformLocation(self._col_prog, b"uEnableFlicker"), 0)

        self._draw_entities(vp)

        GL.glUseProgram(0)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

    def _draw_entities(self, vp: List[float]) -> None:
        ghost_segments = 26 if self._fast_mode else 40

        gb_bg       = _GeoBuilder(textured=False)
        gb_fg       = _GeoBuilder(textured=False)
        gb_coin_tex = _GeoBuilder(textured=True)
        gb_gate_tex = _GeoBuilder(textured=True)
        gb_platform_tex = _GeoBuilder(textured=True)
        gb_table_tex = _GeoBuilder(textured=True)
        gb_sign_tex: Dict[int, _array] = {}
        gb_glow     = _GeoBuilder(textured=False)
        gb_ghost    = _GeoBuilder(textured=False)
        gb_arrow    = _GeoBuilder(textured=False)
        gb_dust     = _GeoBuilder(textured=False)
        anim = self._anim_t
        TWO_PI = math.pi * 2.0

        px = float(self.core.player.x)
        pz = float(self.core.player.z)
        ceil_h = float(self.core.ceiling_height)

        player = self.core.player
        yaw   = float(getattr(player, 'yaw',   0.0) or 0.0)
        pitch = float(getattr(player, 'pitch', 0.0) or 0.0)
        fx = math.sin(yaw)*math.cos(pitch)
        fy = math.sin(pitch)
        fz = math.cos(yaw)*math.cos(pitch)
        fl = math.sqrt(fx*fx+fy*fy+fz*fz) or 1.0
        fx/=fl; fy/=fl; fz/=fl
        upx, upy, upz = (1.0,0.0,0.0) if abs(fy)>0.97 else (0.0,1.0,0.0)
        rx = fy*upz - fz*upy; ry = fz*upx - fx*upz; rz = fx*upy - fy*upx
        rl = math.sqrt(rx*rx+ry*ry+rz*rz) or 1.0
        rx/=rl; ry/=rl; rz/=rl
        ux = ry*fz-rz*fy; uy = rz*fx-rx*fz; uz = rx*fy-ry*fx

        def billboard_quad_col(cx, cy, cz, w, h, col):
            hx=(w*0.5)*rx; hy=(w*0.5)*ry; hz=(w*0.5)*rz
            vx=(h*0.5)*ux; vy=(h*0.5)*uy; vz=(h*0.5)*uz
            p0=(cx-hx-vx,cy-hy-vy,cz-hz-vz); p1=(cx+hx-vx,cy+hy-vy,cz+hz-vz)
            p2=(cx+hx+vx,cy+hy+vy,cz+hz+vz); p3=(cx-hx+vx,cy-hy+vy,cz-hz+vz)
            gb_glow.quad_col(p0,p1,p2,p3,col)

        def radial_sprite_glow_col(cx, cy, cz, radius, rgb, alpha, segments=24):
            if alpha<=0.0 or radius<=0.0: return
            r,g,b = rgb
            c0=(r,g,b,float(alpha)); c1=(r,g,b,0.0)
            for i in range(segments):
                a0=(i/segments)*TWO_PI; a1=((i+1)/segments)*TWO_PI
                p0=(cx,cy,cz)
                ca0,sa0=math.cos(a0),math.sin(a0)
                ca1,sa1=math.cos(a1),math.sin(a1)
                p1=(cx+ca0*radius*rx,cy+sa0*radius,cz+ca0*radius*rz)
                p2=(cx+ca1*radius*rx,cy+sa1*radius,cz+ca1*radius*rz)
                gb_glow.tri_col_vc(p0,c0,p1,c1,p2,c1)

        def floor_glow_col(cx, cy, cz, radius, rgb, alpha, segments=22):
            if alpha<=0.0 or radius<=0.0: return
            r,g,b = rgb
            c0=(r,g,b,float(alpha)); c1=(r,g,b,0.0)
            for i in range(segments):
                a0=(i/segments)*TWO_PI; a1=((i+1)/segments)*TWO_PI
                p0=(cx,cy,cz)
                p1=(cx+math.cos(a0)*radius,cy,cz+math.sin(a0)*radius)
                p2=(cx+math.cos(a1)*radius,cy,cz+math.sin(a1)*radius)
                gb_glow.tri_col_vc(p0,c0,p1,c1,p2,c1)

        # --- Coins ---
        for coin in self.core.coins.values():
            if coin.taken: continue
            r, c = coin.cell
            cx, cz = c+0.5, r+0.5
            if (cx-px)**2+(cz-pz)**2 > _ENTITY_R2: continue
            bob = 0.06*math.sin(anim*1.6+r*0.37+c*0.51)
            spin = (anim*3.0) % TWO_PI
            cy = 1.22+bob
            tmp = _GeoBuilder(textured=False)
            tmp.coin_col(0.0, 0.0, 0.0)
            ax = math.pi*0.5
            for i in range(0, len(tmp.data), 7):
                x,y,z = tmp.data[i],tmp.data[i+1],tmp.data[i+2]
                x,y,z = _rot_pt_x(x,y,z,ax); x,y,z = _rot_pt_y(x,y,z,spin)
                gb_fg.data.extend([x+cx,y+cy,z+cz,tmp.data[i+3],tmp.data[i+4],tmp.data[i+5],tmp.data[i+6]])
            if self._tex_coin:
                ttmp = _GeoBuilder(textured=True)
                inner_r = 0.14*0.92; thickness = 0.04
                y0,y1 = -thickness/2.0, thickness/2.0; eps = 0.001
                ttmp.disc_fan_tex(0.0,y1+eps,0.0,inner_r,24)
                ttmp.disc_fan_tex(0.0,y0-eps,0.0,inner_r,24,normal_up=False)
                for i in range(0, len(ttmp.data), 5):
                    x,y,z = ttmp.data[i],ttmp.data[i+1],ttmp.data[i+2]
                    x,y,z = _rot_pt_x(x,y,z,ax); x,y,z = _rot_pt_y(x,y,z,spin)
                    gb_coin_tex.data.extend([x+cx,y+cy,z+cz,ttmp.data[i+3],ttmp.data[i+4]])
            d2 = (cx-px)**2+(cz-pz)**2
            if d2 <= _GLOW_R2:
                pulse = 0.16+0.06*math.sin(anim*2.2+r*0.17+c*0.23)
                radial_sprite_glow_col(cx,1.22+bob,cz,0.34,(1.0,0.90,0.35),pulse)

        # --- Key fragments ---
        for frag in self.core.key_fragments.values():
            if frag.taken: continue
            r, c = frag.cell
            cx, cz = c+0.5, r+0.5
            if (cx-px)**2+(cz-pz)**2 > _ENTITY_R2: continue
            kind = getattr(frag,'kind','')
            
            if kind == 'KH':
                base, glow_rgb = (0.55, 0.95, 1.0, 0.95), (0.65, 1.0, 1.0)
            elif kind == 'KP':
                base, glow_rgb = (0.9, 0.65, 1.0, 0.95), (0.95, 0.75, 1.0)
            else:
                base, glow_rgb = (0.75, 1.0, 0.65, 0.95), (0.85, 1.0, 0.75)
            
            base_y = (ceil_h-0.85) if kind=='KP' else 1.18
            seed = float(sum((i+1)*ord(ch) for i,ch in enumerate(str(getattr(frag,'id','')))) % 997)
            bob = 0.08*math.sin(anim*2.4+seed)
            spin_y = (anim*140.0+seed*37.0)*(math.pi/180.0)
            
            tmp = _GeoBuilder(textured=False)
            tmp.key_col_custom(0.0,0.0,0.0,scale=1.05,color=base)
            az = math.pi*0.5; cy = base_y+bob
            for i in range(0, len(tmp.data), 7):
                x,y,z = tmp.data[i],tmp.data[i+1],tmp.data[i+2]
                x,y,z = _rot_pt_z(x,y,z,az); x,y,z = _rot_pt_y(x,y,z,spin_y)
                gb_fg.data.extend([x+cx,y+cy,z+cz,tmp.data[i+3],tmp.data[i+4],tmp.data[i+5],tmp.data[i+6]])
            
            if (cx-px)**2+(cz-pz)**2 <= _GLOW_R2:
                radial_sprite_glow_col(cx, base_y+bob+0.05, cz, 0.55, glow_rgb, 0.12)

        # --- Ghosts ---
        ghost_colors = {
            1:(1.0,0.35,0.20,0.82), 2:(0.30,1.0,0.55,0.82),
            3:(0.45,0.65,1.0,0.82), 4:(1.0,0.85,0.25,0.82),
            5:(0.95,0.35,1.0,0.82),
        }

        # Trail constants
        _TRAIL_FADE_DIST  = 4.0
        _TRAIL_START_DIST = 1.0
        _TRAIL_FULL_DIST  = 1.8 
        _TRAIL_BASE_ALPHA = 0.55

        def _sparkle_star(bx, by, bz, size, cr, cg, cb, alpha):
            if alpha <= 0.005 or size <= 0.0:
                return
            h = size * 0.5
            phase = (bx * 7.3 + bz * 13.7 + by * 3.1 + anim * 2.5)
            ca0 = math.cos(phase);          sa0 = math.sin(phase)
            ca1 = math.cos(phase + 1.047);  sa1 = math.sin(phase + 1.047)
            ca2 = math.cos(phase + 2.094);  sa2 = math.sin(phase + 2.094)
            twinkle = 0.65 + 0.35 * math.sin(anim * 8.0 + bx * 5.1 + bz * 3.7)
            a = alpha * twinkle
            col_c = (cr, cg, cb, a)
            col_e = (cr, cg, cb, 0.0)
            # Arm 0 (XZ plane rotated by phase)
            p0 = (bx - ca0*h, by,      bz - sa0*h)
            p1 = (bx + ca0*h, by,      bz + sa0*h)
            p2 = (bx,         by + h,  bz)
            p3 = (bx,         by - h,  bz)
            gb_glow.tri_col_vc(p0, col_e, p2, col_c, p1, col_e)
            gb_glow.tri_col_vc(p0, col_e, p1, col_e, p3, col_c)
            # Arm 1 (rotated 60)
            q0 = (bx - ca1*h, by,      bz - sa1*h)
            q1 = (bx + ca1*h, by,      bz + sa1*h)
            gb_glow.tri_col_vc(q0, col_e, p2, col_c, q1, col_e)
            gb_glow.tri_col_vc(q0, col_e, q1, col_e, p3, col_c)
            # Arm 2 (rotated 120)
            r0 = (bx - ca2*h, by,      bz - sa2*h)
            r1 = (bx + ca2*h, by,      bz + sa2*h)
            gb_glow.tri_col_vc(r0, col_e, p2, col_c, r1, col_e)
            gb_glow.tri_col_vc(r0, col_e, r1, col_e, p3, col_c)

        import time as _time
        now_t = _time.perf_counter()

        for g in self.core.ghosts.values():
            gx=float(g.x); gz=float(g.z)
            if (gx-px)**2+(gz-pz)**2 > _ENTITY_R2: continue
            s = float(getattr(g,'size_scale',1.0) or 1.0)
            bob = 0.05*math.sin(anim*2.0+g.id)
            wobble = 0.06*math.sin(anim*4.6+g.id*0.7)
            y_raise = 0.18+0.22*max(0.0,s-1.0)
            base_col = ghost_colors.get(g.id,(1.0,0.55,0.15,0.92))
            col = (base_col[0],base_col[1],base_col[2],0.92)
            tmp = _GeoBuilder(textured=False)
            tmp.ghost_col(0.0,0.0,0.0,1.0,col,anim,segments=ghost_segments)
            yaw_g = float(getattr(g,'yaw',0.0) or 0.0)
            sx,sy,sz = 2.10*s, 2.75*s, 2.10*s
            gy = 1.15+y_raise+bob+wobble
            for i in range(0, len(tmp.data), 7):
                x,y,z = tmp.data[i],tmp.data[i+1],tmp.data[i+2]
                x*=sx; y*=sy; z*=sz
                x,y,z = _rot_pt_y(x,y,z,yaw_g)
                gb_ghost.data.extend([x+gx,y+gy,z+gz,tmp.data[i+3],tmp.data[i+4],tmp.data[i+5],tmp.data[i+6]])
            glow_y = 1.15+y_raise+bob+0.08
            radial_sprite_glow_col(gx,glow_y,gz,0.55*s,(col[0],col[1],col[2]),0.12)
            radial_sprite_glow_col(gx,glow_y,gz,0.95*s,(col[0],col[1],col[2]),0.05)

            # --- Ghost particle trail ---
            gid = g.id
            if gid not in self._ghost_trails:
                from collections import deque as _dq
                self._ghost_trails[gid] = _dq(maxlen=self._TRAIL_MAX_POINTS)
                self._ghost_trail_last_sample[gid] = now_t

            trail = self._ghost_trails[gid]
            last_t = self._ghost_trail_last_sample.get(gid, now_t)

            # Sample a new position every _TRAIL_SAMPLE_INTERVAL seconds
            if now_t - last_t >= self._TRAIL_SAMPLE_INTERVAL:
                trail.append((gx, gy, gz, now_t))
                self._ghost_trail_last_sample[gid] = now_t

            # Draw trail (furthest to closest)
            cr, cg, cb = base_col[0], base_col[1], base_col[2]
            for tx, ty, tz, _ts in trail:
                dist = math.sqrt((tx - gx)**2 + (tz - gz)**2)
                if dist < _TRAIL_START_DIST or dist > _TRAIL_FADE_DIST:
                    continue
                if dist <= _TRAIL_FULL_DIST:
                    fade = (dist - _TRAIL_START_DIST) / (_TRAIL_FULL_DIST - _TRAIL_START_DIST)
                else:
                    fade = 1.0 - (dist - _TRAIL_FULL_DIST) / (_TRAIL_FADE_DIST - _TRAIL_FULL_DIST)
                fade = max(0.0, min(1.0, fade))


                skip_thresh = fade  # 1.0 = always draw, 0.0 = never
                hash_val = (tx * 31.7 + tz * 17.3 + gid * 7.1) % 1.0
                if hash_val > skip_thresh:
                    continue

                alpha = _TRAIL_BASE_ALPHA * fade
                p_size = 0.04 + 0.10 * fade * s

                jitter_x = math.sin(tx * 11.3 + tz * 7.9 + gid) * 0.18 * s
                jitter_z = math.cos(tx * 7.1 + tz * 13.1 + gid) * 0.18 * s
                jitter_y = math.sin(tx * 5.7 + tz * 9.3) * 0.06 * s
                particle_y = ty - 0.75 + jitter_y

                _sparkle_star(tx + jitter_x, particle_y, tz + jitter_z,
                              p_size, cr, cg, cb, alpha)

                if fade > 0.5:
                    jx2 = math.cos(tx * 13.9 + tz * 5.7 + gid * 2) * 0.12 * s
                    jz2 = math.sin(tx * 9.3 + tz * 11.1 + gid * 3) * 0.12 * s
                    _sparkle_star(tx + jx2, particle_y * 0.5 + ty * 0.5, tz + jz2,
                                  p_size * 0.55, cr, cg, cb, alpha * 0.7)

        # --- Ceiling lamp glow ---
        ceil_h = float(self.core.ceiling_height)
        for r, c in (getattr(self,'_lamps',None) or []):
            lx=float(c)+0.5; lz=float(r)+0.5
            floor_glow_col(lx,0.015,lz,1.75,(0.98,0.95,0.82),0.20)
            floor_glow_col(lx,0.016,lz,0.85,(0.98,0.95,0.82),0.22)
            ay=ceil_h-0.45; base=1.10
            for scale,a in ((1.0,0.08),(1.4,0.05),(1.9,0.03),(2.6,0.015)):
                billboard_quad_col(lx,ay,lz,base*scale,base*scale,(0.98,0.95,0.82,a))

        # --- Floating dust particles ---
        dust_count = 50
        dust_radius = 8.0
        dust_height_range = 2.5
        dust_color = (0.8, 0.8, 0.85, 0.4)
        for i in range(dust_count):
            seed = i * 73.7
            angle = (seed + anim * 0.3) % TWO_PI
            radius = 2.0 + (seed * 0.1 % (dust_radius - 2.0))
            dx = px + math.cos(angle) * radius
            dz = pz + math.sin(angle) * radius
            dy = 0.5 + (seed * 0.5 % dust_height_range) + math.sin(anim * 0.5 + seed) * 0.3
            
            size = 0.008 + (seed * 0.01 % 0.01)
            alpha = 0.2 + 0.3 * math.sin(anim * 1.5 + seed)
            particle_color = (dust_color[0], dust_color[1], dust_color[2], alpha)
            
            gb_dust.quad_col(
                (dx - size, dy - size, dz),
                (dx + size, dy - size, dz),
                (dx + size, dy + size, dz),
                (dx - size, dy + size, dz),
                particle_color
            )

        # --- Spikes ---
        spikes = getattr(self.core,'spikes',None) or []
        if spikes:
            h_factor = float(self.core.spike_height_factor()) if hasattr(self.core,'spike_height_factor') else 0.0
            for sp in spikes:
                r,c = sp.cell
                gb_bg.spike_col(c+0.5,r+0.5,0.85*h_factor)

        # --- Gates ---
        wall_h = float(self.core.wall_height)
        for gate in self.core.gates.values():
            for (r,c) in gate.cells:
                if self._tex_gate:
                    gb_gate_tex.gate_bars_tex(c+0.5,wall_h/2.0,r+0.5,wall_h,gate.y_offset,gate.id=='jail')
                else:
                    gb_bg.gate_bars_col(c+0.5,wall_h/2.0,r+0.5,wall_h,gate.y_offset,gate.id=='jail')

        # --- Moving platform ---
        for plat in getattr(self.core,'platforms',[]):
            r,c = plat.cell
            if self._tex_platform:
                gb_platform_tex.platform_tex(c+0.5,plat.y_offset,r+0.5)
            else:
                gb_bg.platform_col(c+0.5,plat.y_offset,r+0.5)

        # --- Jail table + book ---
        if getattr(self.core,'jail_book_cell',None):
            jr,jc = self.core.jail_book_cell
            cx,cz = jc+0.5,jr+0.5
            pulse = 0.16+0.06*math.sin(anim*2.2)
            radial_sprite_glow_col(cx,0.6,cz,0.9,(1.0,0.9,0.4),0.5)
            if self._tex_platform:
                gb_table_tex.table_tex_book_col(cx,0.0,cz,pulse)
            else:
                gb_bg.table_book_col(cx,0.0,cz,pulse)
            gb_bg.table_book_col_glow(cx,0.0,cz,pulse)

        # --- Checkpoint arrow ---
        arrow = getattr(self.core,'checkpoint_arrow',None)
        if arrow and arrow.visible:
            ar,ac = arrow.cell
            cx=float(ac)+0.5; cz=float(ar)+0.5
            bounce = 0.08*math.sin(anim*2.5)
            cy = float(getattr(self.core,'wall_height',3.0))*0.45+bounce
            pulse = 0.75+0.25*math.sin(anim*3.0)
            radial_sprite_glow_col(cx,cy,cz,1.5,(0.15,1.0,0.4),0.25*pulse,segments=48)
            gb_arrow.arrow3d_col(cx,cy,cz,col=(0.0,0.98,0.35,1.0))

        # --- Sector signs ---
        sector_signs = getattr(self.core,'sector_signs',{}) or {}
        for sid,(cell,facing) in sector_signs.items():
            r,c = cell
            gb_bg.sign_col(c+0.5,1.65,r+0.5,facing,0.48,0.18)
            label = f"SECTOR {str(sid)[:1]}"
            info = self._get_text_texture(label)
            if info:
                tex_id,_,_ = info
                arr = gb_sign_tex.get(tex_id)
                if arr is None:
                    arr = _array('f'); gb_sign_tex[tex_id] = arr
                cx=c+0.5; cz=r+0.5; cy=1.65; tw,th=0.42,0.11; off=0.473
                if facing=='N':
                    z=cz-off; pts=[(cx-tw,cy+th,z,0.0,1.0),(cx+tw,cy+th,z,1.0,1.0),(cx+tw,cy-th,z,1.0,0.0),(cx-tw,cy-th,z,0.0,0.0)]
                elif facing=='S':
                    z=cz+off; pts=[(cx+tw,cy+th,z,0.0,1.0),(cx-tw,cy+th,z,1.0,1.0),(cx-tw,cy-th,z,1.0,0.0),(cx+tw,cy-th,z,0.0,0.0)]
                elif facing=='W':
                    x=cx-off; pts=[(x,cy+th,cz+tw,0.0,1.0),(x,cy+th,cz-tw,1.0,1.0),(x,cy-th,cz-tw,1.0,0.0),(x,cy-th,cz+tw,0.0,0.0)]
                else:
                    x=cx+off; pts=[(x,cy+th,cz-tw,0.0,1.0),(x,cy+th,cz+tw,1.0,1.0),(x,cy-th,cz+tw,1.0,0.0),(x,cy-th,cz-tw,0.0,0.0)]
                (x0,y0,z0,u0,v0),(x1,y1,z1,u1,v1),(x2,y2,z2,u2,v2),(x3,y3,z3,u3,v3) = pts
                arr.extend([x0,y0,z0,u0,v0,x1,y1,z1,u1,v1,x2,y2,z2,u2,v2,x0,y0,z0,u0,v0,x2,y2,z2,u2,v2,x3,y3,z3,u3,v3])

        # --- Jail painting ---
        painting = getattr(self.core,'jail_painting',None)
        jail_painting_arr = None
        jail_tex = None
        if painting:
            (pr_cell,pc_cell),facing = painting
            cx,cz,cy = pc_cell+0.5,pr_cell+0.5,1.55
            dr,dc = {'N':(-1,0),'S':(1,0),'W':(0,-1)}.get(facing,(0,1))
            wr,wc = pr_cell+dr,pc_cell+dc
            if (wr,wc) in getattr(self.core,'walls',set()):
                neg,pos = 0,0
                if facing in ('N','S'):
                    cc2=wc-1
                    while (wr,cc2) in self.core.walls: neg+=1; cc2-=1
                    cc2=wc+1
                    while (wr,cc2) in self.core.walls: pos+=1; cc2+=1
                    cx += max(-0.28,min(0.28,(pos-neg)*0.12))
                else:
                    rr2=wr-1
                    while (rr2,wc) in self.core.walls: neg+=1; rr2-=1
                    rr2=wr+1
                    while (rr2,wc) in self.core.walls: pos+=1; rr2+=1
                    cz += max(-0.28,min(0.28,(pos-neg)*0.12))

            def wall_quad_col(cx0,cy0,cz0,w0,h0,facing0,col0,off0=0.49):
                if facing0=='N':
                    z=cz0-off0; gb_bg.quad_col((cx0-w0,cy0+h0,z),(cx0+w0,cy0+h0,z),(cx0+w0,cy0-h0,z),(cx0-w0,cy0-h0,z),col0)
                elif facing0=='S':
                    z=cz0+off0; gb_bg.quad_col((cx0+w0,cy0+h0,z),(cx0-w0,cy0+h0,z),(cx0-w0,cy0-h0,z),(cx0+w0,cy0-h0,z),col0)
                elif facing0=='W':
                    x=cx0-off0; gb_bg.quad_col((x,cy0+h0,cz0+w0),(x,cy0+h0,cz0-w0),(x,cy0-h0,cz0-w0),(x,cy0-h0,cz0+w0),col0)
                else:
                    x=cx0+off0; gb_bg.quad_col((x,cy0+h0,cz0-w0),(x,cy0+h0,cz0+w0),(x,cy0-h0,cz0+w0),(x,cy0-h0,cz0-w0),col0)

            wall_quad_col(cx,cy,cz,0.78,0.50,facing,(0.30,0.20,0.10,1.0))
            wall_quad_col(cx,cy,cz,0.72,0.44,facing,(0.08,0.08,0.10,0.98))
            jail_tex = self._get_jail_map_texture()
            if jail_tex:
                tw,th=0.70,0.41; off=0.473
                off_z = off - 0.02  # 0.02 units in front of wall
                if facing=='N':
                    z=cz-off_z; pts=[(cx-tw,cy+th,z,0.0,0.0),(cx+tw,cy+th,z,1.0,0.0),(cx+tw,cy-th,z,1.0,1.0),(cx-tw,cy-th,z,0.0,1.0)]
                elif facing=='S':
                    z=cz+off_z; pts=[(cx+tw,cy+th,z,0.0,0.0),(cx-tw,cy+th,z,1.0,0.0),(cx-tw,cy-th,z,1.0,1.0),(cx+tw,cy-th,z,0.0,1.0)]
                elif facing=='W':
                    x=cx-off_z; pts=[(x,cy+th,cz+tw,0.0,0.0),(x,cy+th,cz-tw,1.0,0.0),(x,cy-th,cz-tw,1.0,1.0),(x,cy-th,cz+tw,0.0,1.0)]
                else:
                    x=cx+off_z; pts=[(x,cy+th,cz-tw,0.0,0.0),(x,cy+th,cz+tw,1.0,0.0),(x,cy-th,cz+tw,1.0,1.0),(x,cy-th,cz-tw,0.0,1.0)]
                (x0,y0,z0,u0,v0),(x1,y1,z1,u1,v1),(x2,y2,z2,u2,v2),(x3,y3,z3,u3,v3) = pts
                jail_painting_arr = _array('f')
                jail_painting_arr.extend([x0,y0,z0,u0,v0,x1,y1,z1,u1,v1,x2,y2,z2,u2,v2,x0,y0,z0,u0,v0,x2,y2,z2,u2,v2,x3,y3,z3,u3,v3])
            else:
                pass
        else:
            pass

        self._draw_dynamic_col(gb_bg.data, vp)

        if gb_sign_tex:
            GL.glUseProgram(self._tex_prog)
            for tex_id, arr in gb_sign_tex.items():
                self._draw_dynamic_tex(arr, vp, tex_id)

        # jail painting WITH depth test 
        if jail_painting_arr is not None and jail_tex:
            GL.glUseProgram(self._tex_prog)
            self._draw_dynamic_tex(jail_painting_arr, vp, jail_tex)

        if gb_fg.data:
            self._draw_dynamic_col(gb_fg.data, vp)

        if gb_arrow.data:
            try:
                self._set_no_fog_uniforms(self._col_prog)
            except Exception:
                pass
            GL.glDisable(GL.GL_DEPTH_TEST)
            self._draw_dynamic_col(gb_arrow.data, vp)
            GL.glEnable(GL.GL_DEPTH_TEST)
            try:
                self._set_fog_uniforms(self._col_prog)
            except Exception:
                pass

        # Render coins
        if self._tex_coin and gb_coin_tex.data:
            GL.glUseProgram(self._tex_prog)
            self._draw_dynamic_tex(gb_coin_tex.data, vp, self._tex_coin)

        # Render gate bars
        if self._tex_gate and gb_gate_tex.data:
            GL.glUseProgram(self._tex_prog)
            self._draw_dynamic_tex(gb_gate_tex.data, vp, self._tex_gate)

        # Render platforms
        if self._tex_platform and gb_platform_tex.data:
            GL.glUseProgram(self._tex_prog)
            self._draw_dynamic_tex(gb_platform_tex.data, vp, self._tex_platform)

        # Render jail table
        if self._tex_platform and gb_table_tex.data:
            GL.glUseProgram(self._tex_prog)
            self._draw_dynamic_tex(gb_table_tex.data, vp, self._tex_platform)

        if gb_ghost.data:
            GL.glDepthMask(False)
            self._draw_dynamic_col(gb_ghost.data, vp)
            GL.glDepthMask(True)

        if gb_glow.data:
            GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE)
            GL.glDepthMask(False)
            self._draw_dynamic_col_with_flicker(gb_glow.data, vp)
            GL.glDepthMask(True)
            GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)

        # Render dust particles
        if gb_dust.data:
            GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
            GL.glDepthMask(False)
            GL.glDisable(GL.GL_DEPTH_TEST)
            self._draw_dynamic_col(gb_dust.data, vp)
            GL.glEnable(GL.GL_DEPTH_TEST)
            GL.glDepthMask(True)
            GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)


    def rebuild_geometry(self) -> None:
        # rebuild static VAOs.
        if not self._gl_ready:
            return
        self._build_world_vao()
        self._build_lamp_vao()

    def cleanup(self) -> None:
        _delete_vao(self._wall_vao)
        _delete_vao(self._floor_vao)
        _delete_vao(self._lamp_vao)

        for attr in ('_dyn_vao', '_dyn_tex_vao'):
            v = getattr(self, attr, 0)
            if v:
                try: GL.glDeleteVertexArrays(1, [int(v)])
                except Exception: pass

        for attr in ('_dyn_vbo', '_dyn_tex_vbo'):
            v = getattr(self, attr, 0)
            if v:
                try: GL.glDeleteBuffers(1, [int(v)])
                except Exception: pass

        if getattr(self, '_tex_coin', None):
            try: GL.glDeleteTextures(1, [int(self._tex_coin)])
            except Exception: pass

        if getattr(self, '_jail_map_texture', None):
            try: GL.glDeleteTextures(1, [int(self._jail_map_texture)])
            except Exception: pass
            self._jail_map_texture = None

        for tex_id, _, _ in getattr(self, '_text_tex_cache', {}).values():
            try: GL.glDeleteTextures(1, [int(tex_id)])
            except Exception: pass
        if hasattr(self, '_text_tex_cache'):
            self._text_tex_cache.clear()