"""
sacred_geometry_sop — Script SOP for NeonHandController visual output.
Eudaimon Visual System | Angelo Greene

Attach this as the Script SOP's cookScript.  It reads live data from the
NeonHandController extension and builds three layers of geometry:

  Layer 0 — Sacred geometry circles (Flower, Metatron, Sri Yantra, etc.)
  Layer 1 — Particle trail point cloud
  Layer 2 — Constellation line segments

TouchDesigner Script SOP API used:
  scriptOp.geometry        — SOP geometry object
  geo.createPoint()        — add a point
  geo.createPrim()         — add a primitive
  pt.P                     — position tuple
  pt.attribCreate()        — vertex/point attributes
  prim.createVertex(pt)    — add vertex to primitive

Place this in a Text DAT, then create a Script SOP and set its
'DAT cook script' parameter to point here.
"""

import math

TAU = math.pi * 2.0


def _get_ctrl():
    try:
        return op('..').ext.NeonHandController
    except AttributeError:
        pass
    # Fallback: walk up to the Base COMP
    try:
        return parent().ext.NeonHandController
    except AttributeError:
        return None


def cook(scriptOp):
    geo  = scriptOp.geometry
    ctrl = _get_ctrl()

    if ctrl is None:
        return

    geo.clear()

    frame = ctrl.frame_counter
    mode  = ctrl.current_mode

    # ----------------------------------------------------------------
    # Color attribute helper
    # ----------------------------------------------------------------
    cd_attrib = geo.attribCreate('Cd', geo.attribType.Point, 3, (1.0, 1.0, 1.0))

    def _add_point(x, y, z, r, g, b):
        pt = geo.createPoint()
        pt.P = (x, y, z)
        pt.Cd = (r, g, b)
        return pt

    # ----------------------------------------------------------------
    # Layer 0 — Sacred geometry circles (rendered as polygon rings)
    # ----------------------------------------------------------------
    hue_base  = ctrl.hue_drift
    geo_scale = ctrl.geo_scale * ctrl.owner.par.Geoscale.eval()
    cx0, cy0  = ctrl.hand_centroid
    breath    = ctrl.lfos['breath'].value()
    orbit     = ctrl.lfos['orbit'].value()

    sacred_pts = ctrl.get_sacred_geometry_points(scale=geo_scale * 0.6)

    CIRCLE_SEGS = 32
    for idx, (pcx, pcy, pr) in enumerate(sacred_pts):
        # Offset by hand centroid + slight orbital drift
        world_x = pcx + cx0 + math.cos(orbit * TAU + idx) * 0.004
        world_y = pcy + cy0 + math.sin(orbit * TAU + idx) * 0.004
        world_z = math.sin(frame * 0.02 + idx * 0.5) * 0.015

        hue    = (hue_base + idx * 0.08) % 1.0
        r, g, b = _hsv(hue, 0.85, 1.0)
        pulse  = 1.0 + breath * 0.10 + ctrl.beat_flash * 0.20
        radius = pr * pulse

        # Build polygon ring
        ring_pts = []
        for seg in range(CIRCLE_SEGS):
            a  = seg * TAU / CIRCLE_SEGS
            px = world_x + math.cos(a) * radius
            py = world_y + math.sin(a) * radius
            ring_pts.append(_add_point(px, py, world_z, r, g, b))

        prim = geo.createPrim(geo.primType.Polygon)
        prim.setAttribValue('closed', 1)
        for pt in ring_pts:
            prim.createVertex(pt)
        # Close
        prim.createVertex(ring_pts[0])

    # ----------------------------------------------------------------
    # Layer 1 — Particle trail point cloud
    # ----------------------------------------------------------------
    particles = ctrl.get_particle_list()
    for (px, py, r, g, b, alpha, size) in particles:
        pt = _add_point(px, py, 0.0, r * alpha, g * alpha, b * alpha)
        # Write alpha into a custom attrib for downstream compositing
        try:
            alpha_attrib = geo.attribCreate('Alpha', geo.attribType.Point, 1, (1.0,))
            pt.attribValue(alpha_attrib.name)[0] = alpha
        except Exception:
            pass

    # ----------------------------------------------------------------
    # Layer 2 — Constellation line segments
    # ----------------------------------------------------------------
    if ctrl.owner.par.Showconstel.eval():
        lines = ctrl.get_constellation_list()
        hue_c = (hue_base + 0.5) % 1.0
        rc, gc, bc = _hsv(hue_c, 0.6, 1.0)
        glow  = ctrl.lfos['shimmer'].value() * 0.3

        for (x1, y1, x2, y2, alpha) in lines:
            a = alpha * (0.6 + glow)
            p1 = _add_point(x1, y1, 0.0, rc * a, gc * a, bc * a)
            p2 = _add_point(x2, y2, 0.0, rc * a, gc * a, bc * a)
            prim = geo.createPrim(geo.primType.PolyCurve)
            prim.createVertex(p1)
            prim.createVertex(p2)

    # ----------------------------------------------------------------
    # Layer 3 — Trail history ribbons
    # ----------------------------------------------------------------
    if ctrl.owner.par.Showtrails.eval():
        trail = ctrl.get_trail_list()
        if trail:
            # Group by finger (5 fingers, HISTORY_LEN points each)
            chunk = len(trail) // 5
            for f in range(5):
                seg_pts = trail[f * chunk: (f + 1) * chunk]
                if len(seg_pts) < 2:
                    continue
                prim = geo.createPrim(geo.primType.PolyCurve)
                for (tx, ty, tz, tr, tg, tb, talpha) in seg_pts:
                    pt = _add_point(tx, ty, tz, tr * talpha, tg * talpha, tb * talpha)
                    prim.createVertex(pt)


# ----------------------------------------------------------------
# Minimal HSV util (can't import from controller inside Script SOP)
# ----------------------------------------------------------------

def _hsv(h, s, v):
    h = h / 360.0 if h > 1.0 else h
    i = int(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i %= 6
    return [(v,t,p),(q,v,p),(p,v,t),(p,q,v),(t,p,v),(v,p,q)][i]
