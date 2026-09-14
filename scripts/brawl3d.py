#!/usr/bin/env python3
"""Xyzide Arena -- a playable 3D arena brawler that renders inside the terminal.

The scene is drawn with a small software renderer: the ground is raycast per
pixel, everything else is rasterised as z-buffered boxes.  Each terminal cell
carries two pixels via the upper-half-block glyph, so the vertical resolution
is twice the row count.

Controls are printed in the HUD; ESC or Q quits.
"""

import math
import os
import random
import select
import shutil
import signal
import sys
import termios
import time
import tty

import numpy as np

try:
    from arena_audio import Audio, Silent
except Exception:                       # numpy present but no audio module
    Audio = None

    class Silent:                       # noqa: D101 - mirrors arena_audio.Silent
        enabled = False
        muted = True
        status = "off"

        def play(self, *_a, **_k):
            pass

        def pump(self, _dt):
            pass

        def toggle_mute(self):
            return True

        def close(self):
            pass

# ---------------------------------------------------------------- constants --

FOV = math.radians(54.0)
NEAR = 0.15
CAM_DIST = 8.0          # how far the chase camera trails the player
CAM_HEIGHT = 12.0       # and how high it floats -- together these give the
CAM_LOOK_AHEAD = 2.0    # ~50 degree, top-down-ish brawler perspective
ARENA = 11.0            # half-extent of the playfield
TICK = 1.0 / 30.0
MAX_PIXELS = 190 * 120  # guard rail so a huge pane cannot stall the loop

SKY_TOP = np.array([26, 30, 58], np.float32)
SKY_BOTTOM = np.array([84, 72, 120], np.float32)
FOG = np.array([70, 66, 104], np.float32)
FOG_START, FOG_END = 14.0, 34.0


def unit(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return v / n if n > 1e-9 else v.copy()


# ----------------------------------------------------------------- renderer --

class Renderer:
    """Half-block framebuffer with a z-buffer and a tiny triangle rasteriser."""

    def __init__(self, width, height):
        self.resize(width, height)

    def resize(self, width, height):
        self.w = max(8, width)
        self.h = max(8, height - (height % 2))
        self.color = np.zeros((self.h, self.w, 3), np.float32)
        self.depth = np.full((self.h, self.w), np.inf, np.float32)
        self._prev = None
        aspect = self.w / self.h
        tan = math.tan(FOV * 0.5)
        xs = (2.0 * (np.arange(self.w, dtype=np.float32) + 0.5) / self.w - 1.0)
        ys = (1.0 - 2.0 * (np.arange(self.h, dtype=np.float32) + 0.5) / self.h)
        self._ndc_x = (xs * tan * aspect)[None, :]
        self._ndc_y = (ys * tan)[:, None]
        self._sx_scale = self.w * 0.5 / (tan * aspect)
        self._sy_scale = self.h * 0.5 / tan

    # -- camera ----------------------------------------------------------

    def set_camera(self, eye, target):
        self.eye = eye.astype(np.float32)
        fwd = unit(target - eye)
        # right = up x forward (not forward x up): the other order yields a
        # left-handed basis, which mirrors the whole scene horizontally.
        right = unit(np.cross(np.array([0.0, 1.0, 0.0], np.float32), fwd))
        up = np.cross(fwd, right)
        self._basis = np.stack([right, up, fwd])          # world -> view rows
        self._rays = (fwd[None, None, :]
                      + self._ndc_x[..., None] * right[None, None, :]
                      + self._ndc_y[..., None] * up[None, None, :])
        self._rays /= np.linalg.norm(self._rays, axis=2, keepdims=True)

    def to_view(self, pts):
        return (np.asarray(pts, np.float32) - self.eye) @ self._basis.T

    # -- background ------------------------------------------------------

    def clear(self):
        t = (np.arange(self.h, dtype=np.float32) / (self.h - 1))[:, None, None]
        self.color[...] = SKY_TOP * (1.0 - t) + SKY_BOTTOM * t
        self.depth[...] = np.inf

    def ground(self):
        dy = self._rays[:, :, 1]
        fwd = self._basis[2]
        with np.errstate(divide="ignore", invalid="ignore"):
            t = -self.eye[1] / dy
        hit = (dy < -1e-6) & (t > 0.0) & np.isfinite(t)
        if not hit.any():
            return
        t = np.where(hit, t, 0.0)
        wx = self.eye[0] + t * self._rays[:, :, 0]
        wz = self.eye[2] + t * self._rays[:, :, 2]
        inside = (np.abs(wx) <= ARENA) & (np.abs(wz) <= ARENA)
        checker = ((np.floor(wx) + np.floor(wz)).astype(np.int32) & 1)
        base = np.where(checker[..., None] == 1,
                        np.array([58, 104, 66], np.float32),
                        np.array([48, 92, 58], np.float32))
        # a lighter ring marks the arena border
        edge = (np.abs(wx) > ARENA - 0.6) | (np.abs(wz) > ARENA - 0.6)
        base = np.where(edge[..., None], np.array([96, 120, 74], np.float32), base)
        # ground keeps going outside the walls, just darker, so the arena does
        # not look like an island floating in the sky
        base = np.where(inside[..., None], base, np.array([34, 38, 52], np.float32))
        depth = t * (self._rays @ fwd)
        shaded = self._fog(base, depth)
        self.color[hit] = shaded[hit]
        self.depth[hit] = depth[hit]

    @staticmethod
    def _fog(rgb, depth):
        f = np.clip((depth - FOG_START) / (FOG_END - FOG_START), 0.0, 1.0)[..., None]
        return rgb * (1.0 - f) + FOG * f

    # -- geometry --------------------------------------------------------

    def _clip_near(self, poly):
        out = []
        n = len(poly)
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            da, db = a[2] - NEAR, b[2] - NEAR
            if da >= 0:
                out.append(a)
            if (da >= 0) != (db >= 0):
                out.append(a + (b - a) * (da / (da - db)))
        return out

    def poly(self, pts, rgb):
        """Rasterise one convex view-space polygon with flat shading."""
        clipped = self._clip_near([np.asarray(p, np.float32) for p in pts])
        if len(clipped) < 3:
            return
        screen = []
        for v in clipped:
            iz = 1.0 / v[2]
            screen.append((self.w * 0.5 + v[0] * iz * self._sx_scale,
                           self.h * 0.5 - v[1] * iz * self._sy_scale,
                           iz))
        self._raster(screen, rgb)

    def _raster(self, pts, rgb):
        n = len(pts)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        lo_x = max(int(math.floor(min(xs))), 0)
        hi_x = min(int(math.ceil(max(xs))), self.w - 1)
        lo_y = max(int(math.floor(min(ys))), 0)
        hi_y = min(int(math.ceil(max(ys))), self.h - 1)
        if lo_x > hi_x or lo_y > hi_y:
            return
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += xs[i] * ys[j] - xs[j] * ys[i]
        if abs(area) < 1e-7:
            return
        sign = 1.0 if area > 0 else -1.0

        # 1/z is affine in screen space for a planar polygon, so fit a plane
        # through three vertices instead of interpolating barycentrics.
        plane = None
        for k in range(2, n):
            ax, ay, aw = pts[0]
            bx, by, bw = pts[1]
            cx, cy, cw = pts[k]
            nx = (by - ay) * (cw - aw) - (bw - aw) * (cy - ay)
            ny = (bw - aw) * (cx - ax) - (bx - ax) * (cw - aw)
            nz = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            if abs(nz) > 1e-9:
                plane = (ax, ay, aw, nx / nz, ny / nz)
                break
        if plane is None:
            return

        px = np.arange(lo_x, hi_x + 1, dtype=np.float32)[None, :] + 0.5
        py = np.arange(lo_y, hi_y + 1, dtype=np.float32)[:, None] + 0.5
        mask = None
        for i in range(n):
            j = (i + 1) % n
            e = ((xs[j] - xs[i]) * (py - ys[i]) - (ys[j] - ys[i]) * (px - xs[i])) * sign
            mask = (e >= 0.0) if mask is None else (mask & (e >= 0.0))
            if not mask.any():
                return

        ax, ay, aw, ka, kb = plane
        invz = aw - (ka * (px - ax) + kb * (py - ay))
        with np.errstate(divide="ignore", invalid="ignore"):
            zed = 1.0 / invz
        sub_d = self.depth[lo_y:hi_y + 1, lo_x:hi_x + 1]
        mask &= np.isfinite(zed) & (zed > 0) & (zed < sub_d)
        if not mask.any():
            return
        shaded = self._fog(np.broadcast_to(np.asarray(rgb, np.float32),
                                           mask.shape + (3,)), zed)
        sub_c = self.color[lo_y:hi_y + 1, lo_x:hi_x + 1]
        sub_c[mask] = shaded[mask]
        sub_d[mask] = zed[mask]

    #      corner indices            shade  outward normal
    _FACES = (
        ((0, 1, 2, 3), 0.62, (0.0, 0.0, -1.0)),
        ((5, 4, 7, 6), 0.62, (0.0, 0.0, 1.0)),
        ((4, 0, 3, 7), 0.74, (-1.0, 0.0, 0.0)),
        ((1, 5, 6, 2), 0.74, (1.0, 0.0, 0.0)),
        ((3, 2, 6, 7), 1.00, (0.0, 1.0, 0.0)),
    )   # the bottom face is never visible from a camera above the floor

    def box(self, center, size, rgb):
        cx, cy, cz = center
        sx, sy, sz = (s * 0.5 for s in size)
        corners = np.array([
            [cx - sx, cy - sy, cz - sz], [cx + sx, cy - sy, cz - sz],
            [cx + sx, cy + sy, cz - sz], [cx - sx, cy + sy, cz - sz],
            [cx - sx, cy - sy, cz + sz], [cx + sx, cy - sy, cz + sz],
            [cx + sx, cy + sy, cz + sz], [cx - sx, cy + sy, cz + sz],
        ], np.float32)
        view = self.to_view(corners)
        if (view[:, 2] < NEAR).all():
            return
        base = np.asarray(rgb, np.float32)
        normals = self._basis @ np.array([f[2] for f in self._FACES], np.float32).T
        for k, (idx, shade, _) in enumerate(self._FACES):
            quad = view[list(idx)]
            # backface cull: the eye sits at the origin of view space
            if float(normals[:, k] @ quad.mean(axis=0)) >= 0.0:
                continue
            self.poly(quad, base * shade)

    # -- 2d overlay ------------------------------------------------------

    def project(self, world):
        v = self.to_view(np.asarray(world, np.float32)[None, :])[0]
        if v[2] <= NEAR:
            return None
        iz = 1.0 / v[2]
        return (self.w * 0.5 + v[0] * iz * self._sx_scale,
                self.h * 0.5 - v[1] * iz * self._sy_scale)

    def bar(self, sx, sy, width, frac, rgb, back=(24, 24, 32)):
        x0 = int(sx - width * 0.5)
        y0 = int(sy)
        if y0 < 0 or y0 + 1 >= self.h:
            return
        filled = int(round(width * max(0.0, min(1.0, frac))))
        for i in range(width):
            x = x0 + i
            if 0 <= x < self.w:
                col = rgb if i < filled else back
                self.color[y0, x] = col
                self.color[y0 + 1, x] = np.asarray(col, np.float32) * 0.65

    # -- output ----------------------------------------------------------

    def to_ansi(self):
        """Emit only the cells that changed since the previous frame."""
        buf = np.clip(self.color, 0, 255).astype(np.uint8)
        # Pack each cell as one int so row comparison and colour-run detection
        # happen on plain Python ints -- numpy scalar indexing is far too slow
        # to do per cell at frame rate.
        packed = (buf[:, :, 0].astype(np.int32) << 16
                  | buf[:, :, 1].astype(np.int32) << 8
                  | buf[:, :, 2].astype(np.int32))
        top = packed[0::2].tolist()
        bot = packed[1::2].tolist()
        prev = self._prev
        out = []
        for row, (trow, brow) in enumerate(zip(top, bot)):
            if prev is not None and trow == prev[0][row] and brow == prev[1][row]:
                continue
            out.append(f"\x1b[{row + 1};1H")
            last_fg = last_bg = -1
            for fg, bg in zip(trow, brow):
                if fg != last_fg:
                    out.append(f"\x1b[38;2;{fg >> 16};{fg >> 8 & 255};{fg & 255}m")
                    last_fg = fg
                if bg != last_bg:
                    out.append(f"\x1b[48;2;{bg >> 16};{bg >> 8 & 255};{bg & 255}m")
                    last_bg = bg
                out.append("▀")
            out.append("\x1b[0m")
        self._prev = (top, bot)
        return "".join(out)

    def invalidate(self):
        self._prev = None


# --------------------------------------------------------------- game model --

TEAM_COLORS = {
    0: (np.array([70, 140, 255], np.float32), "BLUE"),
    1: (np.array([240, 80, 90], np.float32), "RED"),
}

KINDS = {
    # name        hp   speed dmg  range reload shots spread  bullet
    "Ranger":   (3400, 4.4, 460, 9.5,  0.55,  1,   0.00,  14.0),
    "Bruiser":  (5200, 4.0, 300, 5.0,  0.75,  5,   0.13,  12.0),
    "Sniper":   (2600, 4.2, 980, 14.0, 1.05,  1,   0.00,  20.0),
}
ROSTER = ["Ranger", "Bruiser", "Sniper"]

RESPAWN = 3.0
AMMO_MAX = 3
SUPER_NEED = 4200.0
BODY_R = 0.42


class Box:
    __slots__ = ("x", "z", "hx", "hz", "h", "bush")

    def __init__(self, x, z, hx, hz, h, bush=False):
        self.x, self.z, self.hx, self.hz, self.h, self.bush = x, z, hx, hz, h, bush

    def contains(self, px, pz, pad=0.0):
        return abs(px - self.x) <= self.hx + pad and abs(pz - self.z) <= self.hz + pad


class Shot:
    __slots__ = ("x", "z", "vx", "vz", "team", "dmg", "life", "owner", "sup")

    def __init__(self, x, z, vx, vz, team, dmg, owner, sup=False):
        self.x, self.z, self.vx, self.vz = x, z, vx, vz
        self.team, self.dmg, self.owner, self.sup = team, dmg, owner, sup
        self.life = 1.6


class Brawler:
    def __init__(self, name, kind, team, spawn):
        self.name, self.kind, self.team = name, kind, team
        (self.hp_max, self.speed, self.dmg, self.range,
         self.reload, self.shots, self.spread, self.bullet) = KINDS[kind]
        self.spawn = spawn
        self.reset()

    def reset(self):
        self.x, self.z = self.spawn
        self.x += random.uniform(-1.2, 1.2)
        self.z += random.uniform(-1.2, 1.2)
        self.vx = self.vz = 0.0
        self.face = 0.0 if self.team == 0 else math.pi
        self.hp = float(self.hp_max)
        self.ammo = float(AMMO_MAX)
        self.charge = 0.0
        self.alive = True
        self.dead_for = 0.0
        self.hurt_at = -9.0
        self.shot_at = -9.0
        self.ai_strafe = random.choice((-1.0, 1.0))
        self.ai_flip = 0.0

    @property
    def hidden(self):
        return self._hidden

    def hurt(self, dmg, now):
        self.hp -= dmg
        self.hurt_at = now
        if self.hp <= 0:
            self.hp = 0.0
            self.alive = False
            self.dead_for = 0.0
            return True
        return False


class Game:
    def __init__(self, target=10):
        self.target = target
        self.reset()

    # -- setup -----------------------------------------------------------

    def reset(self):
        self.boxes = self._build_arena()
        self.units = []
        for team in (0, 1):
            sign = -1.0 if team == 0 else 1.0
            for i, kind in enumerate(ROSTER):
                spawn = ((i - 1) * 3.4, sign * (ARENA - 2.0))
                who = "YOU" if (team == 0 and i == 0) else kind
                self.units.append(Brawler(who, kind, team, spawn))
        self.me = self.units[0]
        self.shots = []
        self.score = [0, 0]
        self.feed = []
        self.events = []
        self.time = 0.0
        self.over = None
        self._mark_hidden()

    @staticmethod
    def _build_arena():
        boxes = []
        w = 0.8
        for sx, sz, hx, hz in ((0, ARENA, ARENA, w), (0, -ARENA, ARENA, w),
                               (ARENA, 0, w, ARENA), (-ARENA, 0, w, ARENA)):
            boxes.append(Box(sx, sz, hx, hz, 2.2))
        layout = [(0, 0, 1.6, 1.6), (5.5, 5.5, 1.2, 1.2), (-5.5, -5.5, 1.2, 1.2),
                  (5.5, -5.5, 1.2, 1.2), (-5.5, 5.5, 1.2, 1.2),
                  (0, 7.5, 2.4, 0.9), (0, -7.5, 2.4, 0.9)]
        for x, z, hx, hz in layout:
            boxes.append(Box(x, z, hx, hz, 1.8))
        for x, z in ((3.2, 0.0), (-3.2, 0.0), (8.0, 2.6), (-8.0, -2.6),
                     (8.0, -2.6), (-8.0, 2.6)):
            boxes.append(Box(x, z, 1.5, 1.5, 1.0, bush=True))
        return boxes

    def emit(self, name, x=None, z=None):
        """Queue a sound event, attenuated by distance from the player."""
        if x is None:
            gain = 1.0
        else:
            d = math.hypot(x - self.me.x, z - self.me.z)
            gain = max(0.12, min(1.0, 9.0 / (6.0 + d)))
        self.events.append((name, gain))

    def drain(self):
        out = self.events
        self.events = []
        return out

    # -- helpers ---------------------------------------------------------

    def solids(self):
        return (b for b in self.boxes if not b.bush)

    def blocked(self, x, z, pad=0.0):
        return any(b.contains(x, z, pad) for b in self.solids())

    def line_of_sight(self, ax, az, bx, bz):
        dx, dz = bx - ax, bz - az
        steps = max(2, int(math.hypot(dx, dz) / 0.45))
        for i in range(1, steps):
            t = i / steps
            if self.blocked(ax + dx * t, az + dz * t):
                return False
        return True

    def _mark_hidden(self):
        bushes = [b for b in self.boxes if b.bush]
        for u in self.units:
            u._hidden = any(b.contains(u.x, u.z) for b in bushes)

    def _slide(self, u, nx, nz):
        if not self.blocked(nx, u.z, BODY_R):
            u.x = nx
        if not self.blocked(u.x, nz, BODY_R):
            u.z = nz
        u.x = max(-ARENA + 1.0, min(ARENA - 1.0, u.x))
        u.z = max(-ARENA + 1.0, min(ARENA - 1.0, u.z))

    # -- combat ----------------------------------------------------------

    def fire(self, u, sup=False):
        if not u.alive or self.over:
            return
        if sup:
            if u.charge < SUPER_NEED:
                return
            u.charge = 0.0
            count, spread, mult = 7, 0.42, 1.1
        else:
            if u.ammo < 1.0:
                return
            u.ammo -= 1.0
            count, spread, mult = u.shots, u.spread, 1.0
        u.shot_at = self.time
        self.emit("super" if sup else "shoot", u.x, u.z)
        for i in range(count):
            off = 0.0 if count == 1 else (i - (count - 1) * 0.5) * spread
            ang = u.face + off
            self.shots.append(Shot(u.x + math.sin(ang) * 0.6,
                                   u.z + math.cos(ang) * 0.6,
                                   math.sin(ang) * u.bullet,
                                   math.cos(ang) * u.bullet,
                                   u.team, u.dmg * mult, u, sup))

    def _kill(self, victim, killer):
        self.emit("kill", victim.x, victim.z)
        self.score[killer.team] += 1
        self.feed.append((self.time, f"{killer.name} knocked out {victim.name}"))
        del self.feed[:-4]
        if self.score[killer.team] >= self.target:
            self.over = killer.team
            self.emit("win" if self.over == self.me.team else "lose")

    # -- simulation ------------------------------------------------------

    def step(self, dt, want):
        self.time += dt
        if self.over is None:
            self._step_player(dt, want)
            for u in self.units:
                if u is not self.me:
                    self._step_ai(u, dt)
        for u in self.units:
            self._step_common(u, dt)
        self._mark_hidden()
        self._step_shots(dt)

    def _step_common(self, u, dt):
        if not u.alive:
            u.dead_for += dt
            if u.dead_for >= RESPAWN and self.over is None:
                hp_keep = u.charge
                u.reset()
                u.charge = hp_keep * 0.5
                self.emit("spawn", u.x, u.z)
            return
        if u.ammo < AMMO_MAX:
            u.ammo = min(AMMO_MAX, u.ammo + dt / u.reload)
        if self.time - u.hurt_at > 3.0 and u.hp < u.hp_max:
            u.hp = min(u.hp_max, u.hp + u.hp_max * 0.22 * dt)

    def _step_player(self, dt, want):
        u = self.me
        if not u.alive:
            return
        mx, mz = want["move"]
        if mx or mz:
            n = math.hypot(mx, mz)
            u.vx, u.vz = mx / n * u.speed, mz / n * u.speed
        else:
            u.vx *= 0.72 ** (dt * 60)
            u.vz *= 0.72 ** (dt * 60)
        self._slide(u, u.x + u.vx * dt, u.z + u.vz * dt)
        ax, az = want["aim"]
        if ax or az:
            u.face = math.atan2(ax, az)
        elif mx or mz:
            u.face = math.atan2(mx, mz)
        if want["fire"]:
            tgt = self._assist(u)
            if tgt is not None:
                u.face = tgt
            self.fire(u)
        if want["super"]:
            self.fire(u, sup=True)

    def _assist(self, u):
        """Snap aim onto a nearby enemy if the player is roughly pointing at it."""
        best, best_d = None, 1e9
        for e in self.units:
            if e.team == u.team or not e.alive or e._hidden:
                continue
            dx, dz = e.x - u.x, e.z - u.z
            d = math.hypot(dx, dz)
            if d > u.range or not self.line_of_sight(u.x, u.z, e.x, e.z):
                continue
            ang = math.atan2(dx, dz)
            diff = abs((ang - u.face + math.pi) % (2 * math.pi) - math.pi)
            if diff < math.radians(22) and d < best_d:
                best, best_d = ang, d
        return best

    def _step_ai(self, u, dt):
        if not u.alive:
            return
        target, td = None, 1e9
        for e in self.units:
            if e.team == u.team or not e.alive or e._hidden:
                continue
            d = math.hypot(e.x - u.x, e.z - u.z)
            if d < td:
                target, td = e, d
        if target is None:
            u.vx *= 0.9
            u.vz *= 0.9
            self._slide(u, u.x + u.vx * dt, u.z + u.vz * dt)
            return
        dx, dz = target.x - u.x, target.z - u.z
        ang = math.atan2(dx, dz)
        u.face = ang
        want = u.range * 0.72
        drive = 1.0 if td > want * 1.15 else (-1.0 if td < want * 0.6 else 0.0)
        u.ai_flip -= dt
        if u.ai_flip <= 0:
            u.ai_flip = random.uniform(0.8, 2.0)
            u.ai_strafe = -u.ai_strafe
        fx, fz = math.sin(ang), math.cos(ang)
        sx, sz = fz * u.ai_strafe, -fx * u.ai_strafe
        mx = fx * drive + sx * 0.75
        mz = fz * drive + sz * 0.75
        n = math.hypot(mx, mz)
        if n > 1e-6:
            u.vx, u.vz = mx / n * u.speed * 0.92, mz / n * u.speed * 0.92
        self._slide(u, u.x + u.vx * dt, u.z + u.vz * dt)
        if td <= u.range and self.line_of_sight(u.x, u.z, target.x, target.z):
            if u.charge >= SUPER_NEED and td < u.range * 0.8:
                self.fire(u, sup=True)
            elif u.ammo >= 1.0 and self.time - u.shot_at > u.reload * 0.55:
                self.fire(u)

    def _step_shots(self, dt):
        alive = []
        for s in self.shots:
            s.x += s.vx * dt
            s.z += s.vz * dt
            s.life -= dt
            if s.life <= 0 or abs(s.x) > ARENA + 1 or abs(s.z) > ARENA + 1:
                continue
            if self.blocked(s.x, s.z):
                continue
            hit = False
            for e in self.units:
                if not e.alive or e.team == s.team:
                    continue
                if (e.x - s.x) ** 2 + (e.z - s.z) ** 2 <= (BODY_R + 0.2) ** 2:
                    dealt = min(s.dmg, e.hp)
                    self.emit("hurt" if e is self.me else "hit", e.x, e.z)
                    if e.hurt(s.dmg, self.time):
                        self._kill(e, s.owner)
                    if not s.sup:
                        s.owner.charge = min(SUPER_NEED, s.owner.charge + dealt)
                    hit = True
                    break
            if not hit:
                alive.append(s)
        self.shots = alive


# ------------------------------------------------------------------- scene --

CRATE_RGB = np.array([150, 112, 74], np.float32)
WALL_RGB = np.array([104, 100, 128], np.float32)
BUSH_RGB = np.array([58, 148, 74], np.float32)


def draw_scene(r, game, now):
    r.clear()
    r.ground()
    for b in game.boxes:
        if b.bush:
            r.box((b.x, b.h * 0.5, b.z), (b.hx * 2, b.h, b.hz * 2), BUSH_RGB)
        else:
            wall = b.hx >= ARENA or b.hz >= ARENA
            r.box((b.x, b.h * 0.5, b.z), (b.hx * 2, b.h, b.hz * 2),
                  WALL_RGB if wall else CRATE_RGB)
    for s in game.shots:
        rgb = TEAM_COLORS[s.team][0] * (1.6 if s.sup else 1.25)
        r.box((s.x, 0.75, s.z), (0.26, 0.26, 0.26), np.clip(rgb, 0, 255))
    bars = []
    for u in game.units:
        if not u.alive:
            continue
        mine = u is game.me
        if u._hidden and not mine and u.team != game.me.team \
                and now - u.shot_at > 0.6:
            continue
        base = TEAM_COLORS[u.team][0].copy()
        if u._hidden:
            base = base * 0.55 + BUSH_RGB * 0.45
        if now - u.hurt_at < 0.12:
            base = np.minimum(base * 0.4 + 255 * 0.6, 255)
        r.box((u.x, 0.45, u.z), (0.74, 0.9, 0.74), base)
        r.box((u.x, 1.12, u.z), (0.56, 0.44, 0.56), np.clip(base * 1.25, 0, 255))
        if mine:
            r.box((u.x, 1.62, u.z), (0.2, 0.16, 0.2),
                  np.array([255, 214, 70], np.float32))
        gx = u.x + math.sin(u.face) * 0.62
        gz = u.z + math.cos(u.face) * 0.62
        r.box((gx, 0.78, gz), (0.24, 0.22, 0.24), np.array([40, 40, 52], np.float32))
        bars.append(u)
    for u in bars:
        p = r.project((u.x, 1.95, u.z))
        if p is None:
            continue
        col = (90, 230, 120) if u.team == game.me.team else (250, 96, 96)
        # scale with the viewport so the bar does not dwarf the fighter on a
        # small pane
        width = max(6, min(20, int(r.w * 0.075)))
        r.bar(p[0], p[1], width, u.hp / u.hp_max, col)


# --------------------------------------------------------------------- hud --

RESET = "\x1b[0m"


def fit(text, cols):
    """Cut a decorated string to `cols` printable columns.

    Escape sequences are copied through untouched and cost no width.  Nothing
    may ever reach the right edge of the bottom row: the wrap would scroll the
    whole screen and desynchronise the frame-delta cache.
    """
    out = []
    width = 0
    i = 0
    while i < len(text):
        if text[i] == "\x1b":
            j = i + 2
            while j < len(text) and not text[j].isalpha():
                j += 1
            out.append(text[i:j + 1])
            i = j + 1
            continue
        if width >= cols:
            break
        out.append(text[i])
        width += 1
        i += 1
    out.append(RESET)
    return "".join(out)


def hud(game, rows, cols, fps, sound="off"):
    u = game.me
    blue, red = game.score
    lines = []

    def pips(n):
        full = int(u.ammo)
        return "".join("\x1b[38;2;255;210;60m●" if i < full
                       else "\x1b[38;2;90;90;110m○" for i in range(n)) + RESET

    state = ""
    if game.over is not None:
        won = game.over == u.team
        state = ("\x1b[38;2;120;255;140m  ★ VICTORY ★  " if won
                 else "\x1b[38;2;255;110;110m  ✖ DEFEAT ✖  ") + \
                RESET + "\x1b[38;2;200;200;210m press R to rematch" + RESET
    elif not u.alive:
        state = f"\x1b[38;2;255;150;150m respawning in {RESPAWN - u.dead_for:4.1f}s" + RESET

    lines.append(
        f"\x1b[38;2;90;160;255m BLUE {blue}{RESET}"
        f"\x1b[38;2;120;120;140m — {RESET}"
        f"\x1b[38;2;255;100;110m{red} RED{RESET}"
        f"\x1b[38;2;120;120;140m  first to {game.target}{RESET}{state}"
        f"\x1b[38;2;70;70;90m   {fps:4.1f} fps  snd:{sound}{RESET}")

    hp_w = 22
    filled = int(round(hp_w * (u.hp / u.hp_max)))
    hp = ("\x1b[38;2;90;230;120m" + "█" * filled
          + "\x1b[38;2;60;60;76m" + "█" * (hp_w - filled) + RESET)
    sup_w = 12
    ready = u.charge >= SUPER_NEED
    # never show a full bar before the super is actually usable
    sfill = sup_w if ready else int(sup_w * (u.charge / SUPER_NEED))
    sup = (("\x1b[38;2;255;220;90m" if ready else "\x1b[38;2;150;110;220m")
           + "█" * sfill + "\x1b[38;2;60;60;76m" + "█" * (sup_w - sfill) + RESET)
    lines.append(f" HP {hp} {int(u.hp):5d}   AMMO {pips(AMMO_MAX)}   "
                 f"SUPER {sup}{' READY' if ready else ''}")

    tail = [t for t in game.feed if game.time - t[0] < 5.0]
    note = tail[-1][1] if tail else ""
    lines.append(f"\x1b[38;2;110;110;130m WASD move · arrows aim · SPACE fire · "
                 f"E super · M sound · R rematch · Q quit{RESET}  "
                 f"\x1b[38;2;200;180;120m{note}{RESET}")

    out = []
    for i, text in enumerate(lines[:rows]):
        row = rows - len(lines) + i + 1
        out.append(f"\x1b[{row};1H\x1b[2K{fit(text, cols - 1)}")
    return "".join(out)


# ------------------------------------------------------------------- input --

HOLD = 0.16
ARROWS = {"A": (0.0, 1.0), "B": (0.0, -1.0), "C": (1.0, 0.0), "D": (-1.0, 0.0)}
MOVES = {"w": (0.0, 1.0), "s": (0.0, -1.0), "d": (1.0, 0.0), "a": (-1.0, 0.0)}


class Input:
    def __init__(self):
        self.held = {}
        self.quit = False
        self.restart = False
        self.mute = False
        self.fire = False
        self.super = False

    def poll(self, now):
        self.fire = self.super = False
        data = b""
        while select.select([sys.stdin], [], [], 0)[0]:
            chunk = os.read(sys.stdin.fileno(), 1024)
            if not chunk:
                break
            data += chunk
        i = 0
        while i < len(data):
            c = data[i:i + 1]
            if c == b"\x1b":
                if data[i + 1:i + 2] == b"[" and data[i + 2:i + 3]:
                    key = data[i + 2:i + 3].decode("latin1")
                    if key in ARROWS:
                        self.held["arrow" + key] = now
                    i += 3
                    continue
                self.quit = True
                i += 1
                continue
            ch = c.decode("latin1").lower()
            if ch in MOVES:
                self.held[ch] = now
            elif ch == " ":
                self.fire = True
            elif ch == "e":
                self.super = True
            elif ch == "r":
                self.restart = True
            elif ch == "m":
                self.mute = True
            elif ch in ("q", "\x03"):
                self.quit = True
            i += 1
        return self.wants(now)

    def wants(self, now):
        mx = mz = ax = az = 0.0
        for key, (dx, dz) in MOVES.items():
            if now - self.held.get(key, -9.0) < HOLD:
                mx += dx
                mz += dz
        for key, (dx, dz) in ARROWS.items():
            if now - self.held.get("arrow" + key, -9.0) < HOLD:
                ax += dx
                az += dz
        return {"move": (mx, mz), "aim": (ax, az),
                "fire": self.fire, "super": self.super}


# -------------------------------------------------------------------- main --

def camera_goal(me):
    """Follow the player, but keep the camera inside the arena so it never
    drifts off and fills the screen with empty ground."""
    pad = 3.0
    x = max(-ARENA + pad, min(ARENA - pad, me.x))
    z = max(-ARENA + pad, min(ARENA - pad, me.z))
    return np.array([x, CAM_HEIGHT, z - CAM_DIST], np.float32)


def main():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        sys.stderr.write("xyzide arena needs an interactive terminal\n")
        return 1

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    out = sys.stdout
    resized = [True]
    signal.signal(signal.SIGWINCH, lambda *_: resized.__setitem__(0, True))

    # ?7l disables autowrap: without it a single overlong line at the bottom
    # row scrolls the screen and every later delta frame lands one row off.
    out.write("\x1b[?1049h\x1b[?25l\x1b[?7l")
    out.flush()
    try:
        tty.setraw(fd)
        game = Game()
        ctl = Input()
        audio = Audio() if Audio is not None else Silent()
        r = None
        rows = cols = 0
        cam = camera_goal(game.me)
        last = time.monotonic()
        fps = 0.0
        repaint = 3.0
        while True:
            if resized[0]:
                resized[0] = False
                size = shutil.get_terminal_size((100, 30))
                cols, rows = size.columns, size.lines
                view_rows = max(6, rows - 3)
                r = Renderer(cols, view_rows * 2)
                out.write("\x1b[2J")
            now = time.monotonic()
            dt = min(0.1, now - last)
            last = now
            fps = fps * 0.9 + (1.0 / dt) * 0.1 if dt > 0 else fps
            repaint -= dt
            if repaint <= 0.0:          # self-heal if the terminal ever drifts
                repaint = 3.0
                r.invalidate()

            want = ctl.poll(now)
            if ctl.quit:
                break
            if ctl.restart:
                ctl.restart = False
                game.reset()
            if ctl.mute:
                ctl.mute = False
                audio.toggle_mute()
            game.step(dt, want)
            for name, gain in game.drain():
                audio.play(name, gain)
            audio.pump(dt)

            cam += (camera_goal(game.me) - cam) * min(1.0, dt * 7.0)
            r.set_camera(cam, np.array([cam[0], 0.0, cam[2] + CAM_DIST + CAM_LOOK_AHEAD],
                                       np.float32))
            draw_scene(r, game, game.time)
            out.write(r.to_ansi())
            out.write(hud(game, rows, cols, fps, audio.status))
            out.flush()

            rest = TICK - (time.monotonic() - now)
            if rest > 0:
                time.sleep(rest)
    finally:
        try:
            audio.close()
        except Exception:
            pass
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        out.write("\x1b[0m\x1b[?7h\x1b[?25h\x1b[?1049l")
        out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
