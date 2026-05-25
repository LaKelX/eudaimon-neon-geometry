"""
NeonHandController v2 — TouchDesigner extension for reactive neon hand visuals.
Eudaimon Visual System | Angelo Greene

Network: /project1/neon_geometry/

Expected operators (by name):
  fingertip_thumb / _index / _middle / _ring / _pinky  — Circle SOPs
  mat_thumb / _index / _middle / _ring / _pinky         — Constant MATs
  mat_aura                                               — Constant MAT for aura ring
  neon_geo                                               — central Geometry COMP
  aura_ring                                              — Circle SOP for hand halo
  pinch_burst_trigger                                    — any op with a .pulse par
  glsl_uniforms                                          — Table DAT (written each frame)
  constellation_lines                                    — Table DAT (finger connection pairs)
  particle_out                                           — Table DAT (active particles)

Install:
  1. Text DAT -> file = /scripts/neon_hand_controller.py
  2. On neon_geometry Base COMP: Customize Component -> Extensions
       Class: NeonHandController   Object: op('.')   Args: (me)   Promote: On
  3. Wire MediaPipe output -> Callbacks DAT -> hand_data_callbacks.py

Custom parameters auto-created under page 'Neon':
  Trailfade / Pinchthreshold / Huespeed / Breathdepth
  Particlelife / Glowintensity / Geoscale
  Showtrails / Showconstel / Showaura
  Mode (menu) / Palette (menu)
"""

import math
import random
from collections import deque

TAU = math.pi * 2.0


# ============================================================
# Color Palettes  (hue in degrees, saturation, value)
# ============================================================

PALETTES = {
    'cosmic':   [(200, 0.90, 1.0), (270, 0.80, 1.0), (180, 0.70, 1.0)],
    'fire':     [(  0, 0.90, 1.0), ( 30, 1.00, 1.0), ( 55, 0.80, 1.0)],
    'earth':    [(120, 0.80, 0.9), ( 80, 0.70, 1.0), ( 40, 0.60, 0.9)],
    'aether':   [(240, 0.20, 1.0), (200, 0.10, 1.0), (280, 0.30, 1.0)],
    'eudaimon': [(195, 0.95, 1.0), ( 45, 1.00, 1.0), (285, 0.90, 1.0)],
}


# ============================================================
# Utilities
# ============================================================

def _hsv_to_rgb(h, s, v):
    h = h / 360.0 if h > 1.0 else h
    i = int(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i %= 6
    return [(v,t,p),(q,v,p),(p,v,t),(p,q,v),(t,p,v),(v,p,q)][i]


def _lerp(a, b, t):
    return a + (b - a) * t


def _dist2(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


# ============================================================
# LFO — Low Frequency Oscillator
# ============================================================

class LFO:
    """Stateful LFO. Call tick(dt) each frame, read value()."""

    SHAPES = ('sine', 'tri', 'saw', 'square', 'bounce')

    def __init__(self, freq=1.0, phase=0.0, shape='sine'):
        self.freq = freq
        self.shape = shape
        self._t = phase

    def tick(self, dt=1 / 60):
        self._t = (self._t + self.freq * dt) % 1.0
        return self.value()

    def value(self):
        v = self._t
        if self.shape == 'sine':
            return math.sin(v * TAU) * 0.5 + 0.5
        if self.shape == 'tri':
            return 1.0 - abs(v * 2.0 - 1.0)
        if self.shape == 'saw':
            return v
        if self.shape == 'square':
            return 1.0 if v < 0.5 else 0.0
        if self.shape == 'bounce':
            return abs(math.sin(v * TAU))
        return math.sin(v * TAU) * 0.5 + 0.5


# ============================================================
# Particle
# ============================================================

class Particle:
    __slots__ = ['x', 'y', 'z', 'vx', 'vy', 'life', 'max_life', 'hue', 'size', 'spin']

    def __init__(self, x, y, z, vx, vy, hue, size=0.01):
        self.x, self.y, self.z = x, y, z
        self.vx, self.vy = vx, vy
        self.life = 1.0
        self.max_life = 1.0
        self.hue = hue
        self.size = size
        self.spin = (random.random() - 0.5) * 0.02

    def update(self, dt=1 / 60, decay=1.2):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vx *= 0.91
        self.vy *= 0.91
        self.hue = (self.hue + self.spin) % 1.0
        self.life -= dt * decay
        return self.life > 0


# ============================================================
# Main Controller
# ============================================================

class NeonHandController:
    """
    Content-grade reactive neon hand visual engine.

    Gesture → Mode → Palette mappings:
      Open palm  → Flower of Life  → cosmic
      Fist       → Particle Burst  → fire
      Peace ✌   → Metatron's Cube → eudaimon
      Rock 🤘   → Chaos           → fire
      Point ☝   → Pure Trail      → aether
      OK 👌      → Sri Yantra      → earth
      Pinch      → burst flash     → —
    """

    # MediaPipe landmark indices
    WRIST = 0
    THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
    INDEX_MCP,  INDEX_PIP,  INDEX_DIP,  INDEX_TIP  = 5, 6, 7, 8
    MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
    RING_MCP,   RING_PIP,   RING_DIP,   RING_TIP   = 13, 14, 15, 16
    PINKY_MCP,  PINKY_PIP,  PINKY_DIP,  PINKY_TIP  = 17, 18, 19, 20

    FINGERTIPS   = [THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP]
    KNUCKLES     = [THUMB_MCP, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP]
    FINGER_NAMES = ['thumb', 'index', 'middle', 'ring', 'pinky']

    # Gestures
    GESTURE_NONE  = 'none'
    GESTURE_PINCH = 'pinch'
    GESTURE_FIST  = 'fist'
    GESTURE_OPEN  = 'open_palm'
    GESTURE_POINT = 'point'
    GESTURE_PEACE = 'peace'
    GESTURE_ROCK  = 'rock'
    GESTURE_OK    = 'ok'

    # Modes
    MODE_FLOWER   = 'flower_of_life'
    MODE_METATRON = 'metatron_cube'
    MODE_TRAIL    = 'pure_trail'
    MODE_BURST    = 'particle_burst'
    MODE_CONSTEL  = 'constellation'
    MODE_SRI      = 'sri_yantra'
    MODE_CHAOS    = 'chaos'

    MAX_PARTICLES = 600
    HISTORY_LEN   = 50

    def __init__(self, owner_comp):
        self.owner = owner_comp

        self.frame_counter = 0
        self.hue_drift     = 0.0

        # Per-finger state
        self.last_positions   = {n: (0.0, 0.0, 0.0) for n in self.FINGER_NAMES}
        self.smooth_positions  = {n: (0.0, 0.0)      for n in self.FINGER_NAMES}
        self.velocity_buffer  = {n: deque(maxlen=10) for n in self.FINGER_NAMES}
        self.trail_history    = {n: deque(maxlen=self.HISTORY_LEN) for n in self.FINGER_NAMES}
        self.finger_avg_speed = {n: 0.0 for n in self.FINGER_NAMES}

        # Gesture state
        self.current_gesture   = self.GESTURE_NONE
        self.prev_gesture      = self.GESTURE_NONE
        self.gesture_hold      = 0
        self.pinch_active      = False
        self.pinch_cooldown    = 0

        # Mode state
        self.current_mode  = self.MODE_FLOWER
        self._geo_dirty    = True
        self._geo_cache    = {}

        # Palette state
        self.current_palette = 'eudaimon'
        self.target_palette  = 'eudaimon'
        self.palette_t       = 1.0

        # Particles
        self.particles    = []
        self.burst_budget = 0

        # LFOs — 4 independent oscillators for ambient life
        self.lfos = {
            'breath':  LFO(freq=0.18,  phase=0.00, shape='sine'),
            'pulse':   LFO(freq=0.70,  phase=0.25, shape='sine'),
            'shimmer': LFO(freq=3.10,  phase=0.50, shape='tri'),
            'drift':   LFO(freq=0.04,  phase=0.00, shape='sine'),
            'orbit':   LFO(freq=0.08,  phase=0.33, shape='saw'),
            'bounce':  LFO(freq=1.40,  phase=0.70, shape='bounce'),
        }

        # Global scalars
        self.hand_spread    = 0.0
        self.hand_centroid  = (0.0, 0.0)
        self.aura_radius    = 0.18
        self.global_energy  = 0.0
        self.beat_flash     = 0.0
        self.geo_scale      = 1.0
        self.chromatic_amt  = 0.0  # drives GLSL chromatic aberration

        self._ensure_custom_pars()

    # ----------------------------------------------------------------
    # Custom Parameters
    # ----------------------------------------------------------------

    def _ensure_custom_pars(self):
        if any(p.name == 'Neon' for p in self.owner.customPages):
            return
        page = self.owner.appendCustomPage('Neon')
        page.appendFloat('Trailfade',      label='Trail Fade')
        page.appendFloat('Pinchthreshold', label='Pinch Threshold')
        page.appendFloat('Huespeed',       label='Hue Drift Speed')
        page.appendFloat('Breathdepth',    label='Breath Depth')
        page.appendFloat('Particledecay',  label='Particle Decay Rate')
        page.appendFloat('Glowintensity',  label='Glow Intensity')
        page.appendFloat('Geoscale',       label='Geometry Scale')
        page.appendFloat('Smoothing',      label='Position Smoothing')
        page.appendToggle('Showtrails',    label='Show Trails')
        page.appendToggle('Showconstel',   label='Show Constellation')
        page.appendToggle('Showaura',      label='Show Aura Ring')
        page.appendToggle('Beatreactive',  label='Beat Reactive')
        page.appendMenu('Mode',            label='Geometry Mode')
        page.appendMenu('Palette',         label='Color Palette')

        self.owner.par.Trailfade      = 0.93
        self.owner.par.Pinchthreshold = 0.05
        self.owner.par.Huespeed       = 0.40
        self.owner.par.Breathdepth    = 0.30
        self.owner.par.Particledecay  = 1.20
        self.owner.par.Glowintensity  = 2.60
        self.owner.par.Geoscale       = 1.00
        self.owner.par.Smoothing      = 0.35
        self.owner.par.Showtrails     = True
        self.owner.par.Showconstel    = True
        self.owner.par.Showaura       = True
        self.owner.par.Beatreactive   = True

        self.owner.par.Mode.menuNames = [
            self.MODE_FLOWER, self.MODE_METATRON, self.MODE_TRAIL,
            self.MODE_BURST,  self.MODE_CONSTEL,  self.MODE_SRI, self.MODE_CHAOS,
        ]
        self.owner.par.Mode.menuLabels = [
            'Flower of Life', "Metatron's Cube", 'Pure Trail',
            'Particle Burst', 'Constellation',   'Sri Yantra', 'Chaos',
        ]
        self.owner.par.Palette.menuNames  = list(PALETTES.keys())
        self.owner.par.Palette.menuLabels = ['Cosmic', 'Fire', 'Earth', 'Aether', 'Eudaimon']

    # ================================================================
    # Public API
    # ================================================================

    def OnHandFrame(self, landmarks, hand_side='right'):
        """Call each frame with 21 MediaPipe (x, y, z) landmarks, normalized 0..1."""
        if not landmarks or len(landmarks) < 21:
            self._ambient_tick()
            return

        self.frame_counter += 1
        dt = 1.0 / 60.0
        for lfo in self.lfos.values():
            lfo.tick(dt)

        self.hue_drift = (self.hue_drift + self.owner.par.Huespeed.eval() * dt * 0.5) % 1.0

        # Update all fingertips
        for tip_idx, name in zip(self.FINGERTIPS, self.FINGER_NAMES):
            self._update_fingertip(name, landmarks[tip_idx])

        # Aggregate hand metrics
        self._update_hand_metrics(landmarks)

        # Gesture classification + state machine
        gesture = self._classify_gesture(landmarks)
        self._handle_gesture(gesture, landmarks)

        # Central geometry + aura
        self._update_central_geometry()
        self._update_aura()

        # Particles
        decay = self.owner.par.Particledecay.eval()
        self.particles = [p for p in self.particles if p.update(dt, decay)]
        if self.current_mode == self.MODE_BURST:
            self._spawn_ambient_burst()

        # Beat flash / energy decay
        self.beat_flash    = max(0.0, self.beat_flash    - dt * 3.5)
        self.global_energy = max(0.0, self.global_energy - dt * 0.6)
        self.chromatic_amt = _lerp(self.chromatic_amt, self.beat_flash * 0.02, 0.15)

        # Write output tables
        self._write_glsl_table()
        self._write_particle_table()
        self._write_constellation_table()

    def OnBeatHit(self):
        """Trigger from an audio Beat CHOP or Script CHOP for music-reactive bursts."""
        if not self.owner.par.Beatreactive.eval():
            return
        self.beat_flash = 1.0
        cx, cy = self.hand_centroid
        self._spawn_burst(cx, cy, 60, 0.5)

    def OnPinch(self, p1, p2):
        midx = (p1[0] + p2[0]) * 0.5
        midy = (p1[1] + p2[1]) * 0.5
        sx = (midx - 0.5) * 2.0
        sy = (0.5 - midy) * 2.0
        self._spawn_burst(sx, sy, 100, 0.7)
        self.beat_flash = 0.9
        try:
            self.owner.par.Trailfade = 0.50
        except Exception:
            pass
        trigger = op('pinch_burst_trigger')
        if trigger is not None and hasattr(trigger.par, 'pulse'):
            trigger.par.pulse.pulse()

    def get_status(self):
        return {
            'gesture':   self.current_gesture,
            'mode':      self.current_mode,
            'palette':   self.current_palette,
            'energy':    round(self.global_energy, 3),
            'particles': len(self.particles),
            'beat':      round(self.beat_flash, 3),
            'scale':     round(self.geo_scale, 3),
            'frame':     self.frame_counter,
        }

    # ================================================================
    # Gesture Classification
    # ================================================================

    def _classify_gesture(self, lm):
        wrist = lm[self.WRIST]

        def tip_extended(tip, mcp):
            return lm[tip][1] < lm[mcp][1] - 0.04

        index_ext  = tip_extended(self.INDEX_TIP,  self.INDEX_MCP)
        middle_ext = tip_extended(self.MIDDLE_TIP, self.MIDDLE_MCP)
        ring_ext   = tip_extended(self.RING_TIP,   self.RING_MCP)
        pinky_ext  = tip_extended(self.PINKY_TIP,  self.PINKY_MCP)
        spread     = sum([index_ext, middle_ext, ring_ext, pinky_ext])

        # Pinch check
        t = lm[self.THUMB_TIP]
        i = lm[self.INDEX_TIP]
        pinch_dist = _dist2(t, i)
        if pinch_dist < self.owner.par.Pinchthreshold.eval():
            return self.GESTURE_OK if spread >= 3 else self.GESTURE_PINCH

        # Named gestures
        if index_ext and pinky_ext and not middle_ext and not ring_ext:
            return self.GESTURE_ROCK
        if index_ext and middle_ext and not ring_ext and not pinky_ext:
            return self.GESTURE_PEACE
        if index_ext and not middle_ext and not ring_ext and not pinky_ext:
            return self.GESTURE_POINT
        if spread == 4:
            return self.GESTURE_OPEN
        if spread == 0:
            return self.GESTURE_FIST
        return self.GESTURE_NONE

    def _handle_gesture(self, gesture, landmarks):
        if gesture == self.prev_gesture:
            self.gesture_hold += 1
        else:
            self.gesture_hold = 0
            self.prev_gesture = gesture

        if self.gesture_hold < 4:  # debounce: hold 4 frames
            return

        if gesture == self.current_gesture:
            if gesture == self.GESTURE_PINCH and self.pinch_cooldown > 0:
                self.pinch_cooldown -= 1
            return

        # Gesture changed — apply mappings
        GESTURE_MODE = {
            self.GESTURE_OPEN:  self.MODE_FLOWER,
            self.GESTURE_FIST:  self.MODE_BURST,
            self.GESTURE_PEACE: self.MODE_METATRON,
            self.GESTURE_ROCK:  self.MODE_CHAOS,
            self.GESTURE_POINT: self.MODE_TRAIL,
            self.GESTURE_OK:    self.MODE_SRI,
        }
        GESTURE_PALETTE = {
            self.GESTURE_OPEN:  'cosmic',
            self.GESTURE_FIST:  'fire',
            self.GESTURE_PEACE: 'eudaimon',
            self.GESTURE_ROCK:  'fire',
            self.GESTURE_POINT: 'aether',
            self.GESTURE_OK:    'earth',
        }

        if gesture in GESTURE_MODE:
            self._set_mode(GESTURE_MODE[gesture])
        if gesture in GESTURE_PALETTE:
            self.target_palette = GESTURE_PALETTE[gesture]

        if gesture == self.GESTURE_PINCH and not self.pinch_active and self.pinch_cooldown == 0:
            t = landmarks[self.THUMB_TIP]
            i = landmarks[self.INDEX_TIP]
            self.OnPinch(t, i)
            self.pinch_active = True
            self.pinch_cooldown = 20
        elif gesture != self.GESTURE_PINCH:
            self.pinch_active = False

        if self.pinch_cooldown > 0:
            self.pinch_cooldown -= 1

        self.current_gesture = gesture

    # ================================================================
    # Fingertip Updates
    # ================================================================

    def _update_fingertip(self, name, pos):
        x, y, z = pos
        sx = (x - 0.5) * 2.0
        sy = (0.5 - y) * 2.0

        # Smooth position
        smooth = self.owner.par.Smoothing.eval()
        spx, spy = self.smooth_positions[name]
        spx = _lerp(spx, sx, smooth)
        spy = _lerp(spy, sy, smooth)
        self.smooth_positions[name] = (spx, spy)

        # Velocity
        last = self.last_positions[name]
        speed = math.sqrt((sx - last[0]) ** 2 + (sy - last[1]) ** 2 + (z - last[2]) ** 2)
        self.velocity_buffer[name].append(speed)
        self.last_positions[name] = (sx, sy, z)
        avg_speed = sum(self.velocity_buffer[name]) / max(1, len(self.velocity_buffer[name]))
        self.finger_avg_speed[name] = avg_speed
        self.global_energy = _clamp(self.global_energy + avg_speed * 2.5, 0.0, 1.0)

        # Trail history
        self.trail_history[name].append((spx, spy, z, self.hue_drift))

        # Reactive radius — velocity + breathing LFO
        breath = self.lfos['breath'].value() * self.owner.par.Breathdepth.eval()
        radius = 0.018 + _clamp(avg_speed * 5.0, 0.0, 0.10) + breath * 0.022

        # Color from palette
        hue = (self.hue_drift + self.FINGER_NAMES.index(name) * 0.2) % 1.0
        r, g, b = self._palette_color(hue)
        glow = self.owner.par.Glowintensity.eval()
        shimmer = 1.0 + self.lfos['shimmer'].value() * 0.18
        beat_add = self.beat_flash * 0.8

        # Circle SOP
        circle = op(f'fingertip_{name}')
        if circle is not None:
            try:
                circle.par.radx    = radius
                circle.par.rady    = radius
                circle.par.centerx = spx
                circle.par.centery = spy
            except AttributeError:
                pass

        # Constant MAT
        mat = op(f'mat_{name}')
        if mat is not None:
            try:
                mat.par.colorr = r
                mat.par.colorg = g
                mat.par.colorb = b
                mat.par.emitr  = r * glow * shimmer + beat_add
                mat.par.emitg  = g * glow * shimmer + beat_add * 0.4
                mat.par.emitb  = b * glow * shimmer + beat_add
            except AttributeError:
                pass

        # Spawn trail particles on fast motion
        if avg_speed > 0.012 and self.owner.par.Showtrails.eval():
            spawn_count = int(avg_speed * 80)
            for _ in range(min(spawn_count, 6)):
                if len(self.particles) < self.MAX_PARTICLES:
                    vx = (random.random() - 0.5) * avg_speed * 0.6
                    vy = (random.random() - 0.5) * avg_speed * 0.6
                    self.particles.append(Particle(spx, spy, z, vx, vy, hue, radius * 0.45))

    # ================================================================
    # Hand Metrics
    # ================================================================

    def _update_hand_metrics(self, landmarks):
        tips = [landmarks[t] for t in self.FINGERTIPS]
        cx = sum(t[0] for t in tips) / 5.0
        cy = sum(t[1] for t in tips) / 5.0
        self.hand_centroid = ((cx - 0.5) * 2.0, (0.5 - cy) * 2.0)

        wrist = landmarks[self.WRIST]
        spreads = [_dist2(landmarks[t], wrist) for t in self.FINGERTIPS]
        self.hand_spread = sum(spreads) / len(spreads)

        target_scale = 0.5 + self.hand_spread * 3.0
        self.geo_scale = _lerp(self.geo_scale, target_scale, 0.07)

    # ================================================================
    # Central Geometry + Aura
    # ================================================================

    def _update_central_geometry(self):
        geo = op('neon_geo')
        if geo is None:
            return
        cx, cy = self.hand_centroid
        breath = 1.0 + self.lfos['breath'].value() * 0.12
        pulse  = 1.0 + self.lfos['pulse'].value() * 0.06 * self.global_energy
        rot    = (self.frame_counter * 0.35) % 360
        scale  = self.geo_scale * breath * pulse * self.owner.par.Geoscale.eval()
        try:
            geo.par.tx = cx
            geo.par.ty = cy
            geo.par.rz = rot
            geo.par.sx = scale
            geo.par.sy = scale
        except AttributeError:
            pass

    def _update_aura(self):
        if not self.owner.par.Showaura.eval():
            return
        aura = op('aura_ring')
        if aura is None:
            return
        target_r = 0.10 + self.hand_spread * 1.3
        self.aura_radius = _lerp(self.aura_radius, target_r, 0.05)
        breath = 1.0 + self.lfos['breath'].value() * 0.09
        orbit  = self.lfos['orbit'].value()
        rx = self.aura_radius * breath * (1.0 + orbit * 0.04)
        ry = self.aura_radius * breath * (1.0 - orbit * 0.04)
        try:
            aura.par.radx    = rx
            aura.par.rady    = ry
            aura.par.centerx = self.hand_centroid[0]
            aura.par.centery = self.hand_centroid[1]
        except AttributeError:
            pass
        mat = op('mat_aura')
        if mat is not None:
            hue = (self.hue_drift + 0.5) % 1.0
            r, g, b = self._palette_color(hue)
            glow = self.owner.par.Glowintensity.eval() * 0.65
            pulse_add = self.lfos['pulse'].value() * 0.4
            try:
                mat.par.colorr = r * 0.5
                mat.par.colorg = g * 0.5
                mat.par.colorb = b * 0.5
                mat.par.emitr  = r * glow + pulse_add * r
                mat.par.emitg  = g * glow + pulse_add * g
                mat.par.emitb  = b * glow + pulse_add * b
            except AttributeError:
                pass

    # ================================================================
    # Particle System
    # ================================================================

    def _spawn_ambient_burst(self):
        if len(self.particles) >= self.MAX_PARTICLES:
            return
        cx, cy = self.hand_centroid
        hue = self.hue_drift
        for _ in range(5):
            if len(self.particles) >= self.MAX_PARTICLES:
                break
            angle = random.random() * TAU
            speed = 0.008 + random.random() * 0.04
            self.particles.append(
                Particle(cx, cy, 0,
                         math.cos(angle) * speed, math.sin(angle) * speed,
                         hue, 0.009)
            )

    def _spawn_burst(self, cx, cy, count, speed_scale):
        for _ in range(count):
            if len(self.particles) >= self.MAX_PARTICLES:
                break
            angle  = random.random() * TAU
            speed  = (0.02 + random.random() * 0.07) * speed_scale
            hue    = (self.hue_drift + random.random() * 0.35) % 1.0
            size   = 0.008 + random.random() * 0.016
            self.particles.append(
                Particle(cx, cy, 0, math.cos(angle) * speed, math.sin(angle) * speed, hue, size)
            )

    # ================================================================
    # Sacred Geometry Generators
    # Each returns list of (cx, cy, radius) circles
    # ================================================================

    def get_sacred_geometry_points(self, mode=None, scale=1.0):
        mode = mode or self.current_mode
        key  = (mode, round(scale, 3))
        if not self._geo_dirty and key in self._geo_cache:
            return self._geo_cache[key]
        generators = {
            self.MODE_FLOWER:   self._flower_of_life,
            self.MODE_METATRON: self._metatron_cube,
            self.MODE_SRI:      self._sri_yantra,
            self.MODE_CHAOS:    self._chaos_field,
            self.MODE_CONSTEL:  self._vesica_piscis,
        }
        fn  = generators.get(mode, self._flower_of_life)
        pts = fn(scale)
        self._geo_cache[key] = pts
        self._geo_dirty = False
        return pts

    def _flower_of_life(self, scale=1.0):
        """Central circle + 6 petals + outer ring of 12 = Flower of Life."""
        r   = 0.14 * scale
        pts = [(0.0, 0.0, r)]
        for i in range(6):
            a = i * TAU / 6
            pts.append((math.cos(a) * r, math.sin(a) * r, r))
        for i in range(12):
            a = i * TAU / 12
            d = r * 2.0
            pts.append((math.cos(a) * d, math.sin(a) * d, r))
        return pts

    def _metatron_cube(self, scale=1.0):
        """Fruit of Life — 13 circles: center + inner 6 + outer 6."""
        r = 0.13 * scale
        pts = [(0.0, 0.0, r)]
        for i in range(6):
            a = i * TAU / 6
            pts.append((math.cos(a) * r * 2.0, math.sin(a) * r * 2.0, r))
        for i in range(6):
            a = i * TAU / 6 + TAU / 12
            pts.append((math.cos(a) * r * 3.46, math.sin(a) * r * 3.46, r))
        return pts

    def _sri_yantra(self, scale=1.0):
        """
        Concentric triangles approximation of the Sri Yantra.
        9 rings alternating upward/downward triangles.
        """
        pts = []
        radii = [0.04, 0.07, 0.10, 0.14, 0.18, 0.23, 0.28, 0.34, 0.40]
        for idx, rad in enumerate(radii):
            r      = rad * scale
            offset = 0.0 if idx % 2 == 0 else math.pi / 3
            for k in range(3):
                a = offset + k * TAU / 3
                pts.append((math.cos(a) * r, math.sin(a) * r, 0.012 * scale))
        pts.append((0.0, 0.0, 0.022 * scale))  # bindu
        return pts

    def _chaos_field(self, scale=1.0):
        """Seeded pseudo-random scatter that looks deterministic but alive."""
        rng = random.Random(777)
        pts = []
        for _ in range(30):
            a = rng.random() * TAU
            d = rng.random() ** 0.6 * 0.42 * scale
            r = 0.008 + rng.random() * 0.055 * scale
            pts.append((math.cos(a) * d, math.sin(a) * d, r))
        return pts

    def _vesica_piscis(self, scale=1.0):
        """Vesica Piscis — two overlapping circles as constellation seed."""
        r   = 0.20 * scale
        off = r * 0.5
        pts = [(-off, 0.0, r), (off, 0.0, r)]
        # Add intersection arc points as tiny circles
        ix = 0.0
        iy = math.sqrt(r * r - off * off)
        pts.append((ix,  iy, 0.018 * scale))
        pts.append((ix, -iy, 0.018 * scale))
        return pts

    # ================================================================
    # Output Tables (written to DATs for downstream use)
    # ================================================================

    def _write_glsl_table(self):
        dat = op('glsl_uniforms')
        if dat is None:
            return
        try:
            dat.clear()
            dat.appendRow(['uniform', 'value'])
            rows = [
                ('uHue',      f'{self.hue_drift:.6f}'),
                ('uEnergy',   f'{self.global_energy:.6f}'),
                ('uBeat',     f'{self.beat_flash:.6f}'),
                ('uSpread',   f'{self.hand_spread:.6f}'),
                ('uScale',    f'{self.geo_scale:.6f}'),
                ('uBreath',   f'{self.lfos["breath"].value():.6f}'),
                ('uPulse',    f'{self.lfos["pulse"].value():.6f}'),
                ('uShimmer',  f'{self.lfos["shimmer"].value():.6f}'),
                ('uOrbit',    f'{self.lfos["orbit"].value():.6f}'),
                ('uCx',       f'{self.hand_centroid[0]:.6f}'),
                ('uCy',       f'{self.hand_centroid[1]:.6f}'),
                ('uChroma',   f'{self.chromatic_amt:.6f}'),
                ('uGesture',  self.current_gesture),
                ('uMode',     self.current_mode),
                ('uPalette',  self.current_palette),
                ('uFrame',    str(self.frame_counter)),
            ]
            for row in rows:
                dat.appendRow(row)
        except Exception:
            pass

    def _write_particle_table(self):
        dat = op('particle_out')
        if dat is None:
            return
        try:
            dat.clear()
            dat.appendRow(['x', 'y', 'r', 'g', 'b', 'alpha', 'size'])
            for p in self.particles:
                age   = 1.0 - p.life
                alpha = p.life * (1.0 - age * 0.4)
                r, g, b = _hsv_to_rgb(p.hue, 0.88, 1.0)
                dat.appendRow([
                    f'{p.x:.5f}', f'{p.y:.5f}',
                    f'{r:.4f}', f'{g:.4f}', f'{b:.4f}',
                    f'{alpha:.4f}', f'{p.size:.5f}',
                ])
        except Exception:
            pass

    def _write_constellation_table(self):
        if not self.owner.par.Showconstel.eval():
            return
        dat = op('constellation_lines')
        if dat is None:
            return
        try:
            dat.clear()
            dat.appendRow(['x1', 'y1', 'x2', 'y2', 'alpha'])
            positions = list(self.smooth_positions.values())
            for i in range(len(positions)):
                for j in range(i + 1, len(positions)):
                    x1, y1 = positions[i]
                    x2, y2 = positions[j]
                    dist  = math.sqrt((x2-x1)**2 + (y2-y1)**2)
                    alpha = _clamp(1.0 - dist * 1.6)
                    dat.appendRow([
                        f'{x1:.5f}', f'{y1:.5f}',
                        f'{x2:.5f}', f'{y2:.5f}',
                        f'{alpha:.4f}',
                    ])
        except Exception:
            pass

    # ================================================================
    # Public data accessors (for Script SOP)
    # ================================================================

    def get_particle_list(self):
        """Return [(x, y, r, g, b, alpha, size)] for Script SOP."""
        out = []
        for p in self.particles:
            age   = 1.0 - p.life
            alpha = p.life * (1.0 - age * 0.4)
            r, g, b = _hsv_to_rgb(p.hue, 0.88, 1.0)
            out.append((p.x, p.y, r, g, b, alpha, p.size))
        return out

    def get_trail_list(self):
        """Return [(x, y, z, r, g, b, alpha)] for Script SOP."""
        out = []
        for name, history in self.trail_history.items():
            count = len(history)
            for i, (x, y, z, hue) in enumerate(history):
                alpha = (i / max(1, count - 1)) ** 1.8
                r, g, b = self._palette_color(hue)
                out.append((x, y, z, r, g, b, alpha))
        return out

    def get_constellation_list(self):
        """Return [(x1,y1,x2,y2,alpha)] for Script SOP line segments."""
        positions = list(self.smooth_positions.values())
        out = []
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                x1, y1 = positions[i]
                x2, y2 = positions[j]
                dist  = math.sqrt((x2-x1)**2 + (y2-y1)**2)
                alpha = _clamp(1.0 - dist * 1.6)
                out.append((x1, y1, x2, y2, alpha))
        return out

    # ================================================================
    # Ambient Tick (no hand data in frame)
    # ================================================================

    def _ambient_tick(self):
        self.frame_counter += 1
        dt = 1.0 / 60.0
        for lfo in self.lfos.values():
            lfo.tick(dt)
        self.hue_drift    = (self.hue_drift + self.owner.par.Huespeed.eval() * dt * 0.25) % 1.0
        self.beat_flash   = max(0.0, self.beat_flash   - dt * 3.5)
        self.global_energy = max(0.0, self.global_energy - dt * 0.4)
        self.chromatic_amt = _lerp(self.chromatic_amt, 0.0, 0.08)
        decay = self.owner.par.Particledecay.eval()
        self.particles = [p for p in self.particles if p.update(dt, decay)]
        self._write_glsl_table()
        self._write_particle_table()
        self._write_constellation_table()

    # ================================================================
    # Utilities
    # ================================================================

    def _palette_color(self, hue_normalized):
        # Smooth palette crossfade
        if self.current_palette != self.target_palette:
            self.palette_t = _lerp(self.palette_t, 0.0, 0.04)
            if self.palette_t < 0.05:
                self.current_palette = self.target_palette
                self.palette_t = 1.0
        stops = PALETTES[self.current_palette]
        t     = hue_normalized * (len(stops) - 1)
        lo    = int(t) % len(stops)
        hi    = (lo + 1) % len(stops)
        f     = t - int(t)
        h = _lerp(stops[lo][0], stops[hi][0], f)
        s = _lerp(stops[lo][1], stops[hi][1], f)
        v = _lerp(stops[lo][2], stops[hi][2], f)
        return _hsv_to_rgb(h, s, v)

    def _set_mode(self, mode):
        if self.current_mode == mode:
            return
        self.current_mode = mode
        self._geo_dirty   = True
        try:
            self.owner.par.Mode = mode
        except Exception:
            pass
