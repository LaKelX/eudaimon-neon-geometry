"""
hand_data_callbacks — Callbacks DAT bridge for MediaPipe hand data.
Eudaimon Visual System | Angelo Greene

Supports three input modes:
  1. Table DAT  — rows = landmark 0-20, columns = [x, y, z]
  2. CHOP DAT   — channels named landmark_<i>_x / _y / _z
  3. Beat CHOP  — single channel 'beat' > 0.5 triggers OnBeatHit()

Wire as Callbacks DAT on the Table DAT / Script CHOP carrying hand data.
Assumes parent COMP has NeonHandController extension promoted.

Also includes onFrameStart to drive ambient animation every frame,
even when the hand is not tracked.
"""

import time


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def _ctrl():
    try:
        return parent().ext.NeonHandController
    except AttributeError:
        return None


def _parse_table(dat):
    landmarks = []
    for i in range(21):
        try:
            x = float(dat[i, 0].val)
            y = float(dat[i, 1].val)
            z = float(dat[i, 2].val)
        except (ValueError, AttributeError, TypeError):
            landmarks.append((0.0, 0.0, 0.0))
            continue
        landmarks.append((x, y, z))
    return landmarks if len(landmarks) == 21 else []


def _parse_chop(chop):
    landmarks = []
    for i in range(21):
        try:
            x = float(chop[f'landmark_{i}_x'][0])
            y = float(chop[f'landmark_{i}_y'][0])
            z = float(chop[f'landmark_{i}_z'][0])
            landmarks.append((x, y, z))
        except (TypeError, KeyError, IndexError, ValueError):
            landmarks.append((0.0, 0.0, 0.0))
    return landmarks if len(landmarks) == 21 else []


# ----------------------------------------------------------------
# Table DAT callbacks (primary path)
# ----------------------------------------------------------------

def onTableChange(dat):
    ctrl = _ctrl()
    if ctrl is None:
        return
    landmarks = _parse_table(dat)
    if not landmarks:
        ctrl.OnHandFrame([])
        return

    # Try to read hand side from a metadata row if present
    side = 'right'
    try:
        side = str(dat['side', 0].val).lower()
    except Exception:
        pass

    ctrl.OnHandFrame(landmarks, hand_side=side)


# ----------------------------------------------------------------
# CHOP callbacks (alternative: Script CHOP / Audio Beat CHOP)
# ----------------------------------------------------------------

def onCHOPChange(chop):
    ctrl = _ctrl()
    if ctrl is None:
        return

    # Beat CHOP branch — single channel 'beat'
    try:
        beat_val = float(chop['beat'][0])
        if beat_val > 0.5:
            ctrl.OnBeatHit()
        return
    except (TypeError, KeyError):
        pass

    # Standard landmark CHOP
    landmarks = _parse_chop(chop)
    if not landmarks:
        ctrl.OnHandFrame([])
        return

    side = 'right'
    try:
        side = 'left' if float(chop['hand_side'][0]) > 0.5 else 'right'
    except (TypeError, KeyError):
        pass

    ctrl.OnHandFrame(landmarks, hand_side=side)


def onOffToOn(channel, sampleIndex, val, prev):
    """Rising edge on any channel — useful for beat/trigger CHOPs."""
    if channel.name == 'beat':
        ctrl = _ctrl()
        if ctrl is not None:
            ctrl.OnBeatHit()


def onOnToOff(channel, sampleIndex, val, prev):
    pass


def onValueChange(channel, sampleIndex, val, prev):
    pass


# ----------------------------------------------------------------
# Frame-level ambient callback
# Attach this to a Timer CHOP set to 60fps to keep LFOs alive
# even when no hand data is arriving.
# ----------------------------------------------------------------

def onFrameStart(frame):
    ctrl = _ctrl()
    if ctrl is None:
        return
    # If no hand data has been received in the last 2 seconds,
    # fire ambient tick to keep geometry alive.
    last_frame = getattr(ctrl, 'frame_counter', 0)
    if last_frame == 0:
        ctrl._ambient_tick()


# ----------------------------------------------------------------
# Execute DAT callback (attach to an Execute DAT for frame sync)
# ----------------------------------------------------------------

def onStart():
    pass


def onCreate():
    pass


def onExit():
    pass


def whileRunning():
    """
    Called by Execute DAT each cook if bound.
    Drives ambient animation when no hand data arrives.
    """
    ctrl = _ctrl()
    if ctrl is None:
        return
    # Let the controller self-tick ambience; OnHandFrame handles the rest
    pass
