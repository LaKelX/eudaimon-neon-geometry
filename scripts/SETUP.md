# Neon Geometry — Hand-Reactive TouchDesigner Setup

Two scripts power the network at `/project1/neon_geometry/`:

- `neon_hand_controller.py` — extension class with all logic
- `hand_data_callbacks.py` — bridge from hand-tracking data to the extension

## Wiring it up

### 1. Attach the extension
Select your `neon_geometry` Base COMP → right-click → **Customize Component** → **Extensions** tab:

| Field | Value |
|---|---|
| Object | `op('.')` |
| Extension Class | `NeonHandController` |
| Constructor args | `(me)` |
| Promote Extension | **On** |

The constructor auto-creates a custom page **Neon** with:
- `Trailfade` (0–1) — trail persistence
- `Pinchthreshold` (0–1) — thumb/index distance to fire pinch
- `Huespeed` (0–2) — color drift rate
- `Mode` (menu) — Flower of Life / Metatron's Cube / Pure Trail / Particle Burst

### 2. Hook the callbacks
On your `hand_data_callbacks` DAT:
- Set its **file** parameter to `/scripts/hand_data_callbacks.py`
- Set its target (the upstream Table DAT or Script CHOP carrying MediaPipe data) so `onTableChange` / `onCHOPChange` fires each frame.

### 3. Expected operator names
The controller looks for these by name — match them in your network:

| Operator | Type | Purpose |
|---|---|---|
| `fingertip_thumb` / `_index` / `_middle` / `_ring` / `_pinky` | Circle SOP | per-finger glyph |
| `mat_thumb` / `_index` / `_middle` / `_ring` / `_pinky` | Constant MAT | per-finger color + emit |
| `neon_geo` | Geometry COMP | central reactive geometry |
| `pinch_burst_trigger` (optional) | any op with a pulse par | gesture trigger |

## Gesture map

| Gesture | Trigger | Effect |
|---|---|---|
| **Pinch** (thumb-index) | distance < `Pinchthreshold` | calls `OnPinch`, pulses burst, momentarily drops trail fade for a flash |
| **Open palm** | mean fingertip-to-wrist distance > 0.25 | switches `Mode` → Flower of Life |
| **Fist** | mean fingertip-to-wrist distance < 0.12 | switches `Mode` → Particle Burst |
| **Motion** | per-finger velocity buffer | scales finger radius + drives bloom intensity |

## Content tips

- **Bloom chain**: keep your existing Render → Blur → Composite (add). For shareable footage, push `emit*` on the constants to 2.5–4.0 and add a final Lookup TOP with a teal/magenta LUT.
- **Trails**: use a Feedback TOP with `Trailfade` bound to its mix; pinch flashes make great beat-drop moments.
- **Audio reactive (optional)**: feed an Audio Spectrum CHOP into `Huespeed` for color that pulses with music.
- **Capture**: render at 1080×1920 (vertical) for IG/TikTok. Movie File Out TOP at 60fps, ProRes 422 HQ.
