/*
  neon_glow.glsl — GLSL Pixel TOP shader
  Eudaimon Visual System | Angelo Greene

  Reads live values from the NeonHandController via a Table DAT
  evaluated as uniforms through a GLSL Multi TOP's uniform DAT input.

  Renders: neon bloom / chromatic aberration / scanlines / vignette /
           radial pulse ring / hue-shifted color grading

  TouchDesigner wiring:
    1. Create a GLSL Multi TOP in neon_geometry.
    2. Input 0 → composite of your render (fingertips + geometry + trails).
    3. Input 1 → webcam feed (or leave empty for pure geometry).
    4. Under Parameters → GLSL → Pixel Shader → paste this file path.
    5. Under Parameters → Vectors / CHOP → bind each uniform manually,
       or use the Table DAT evaluated uniform approach:
         - Add a DAT to the GLSL Multi TOP's "Uniform DAT" slot.
         - Table: uniform | value  (written by _write_glsl_table).

  All uniforms have safe fallback defaults so the shader runs standalone.
*/

uniform sampler2D sTD2DInputs[2];   // 0 = render, 1 = webcam
uniform vec4      uTD2DInfos[2];

// Live uniforms from NeonHandController (via Table DAT)
uniform float uHue;       // 0..1  global hue drift
uniform float uEnergy;    // 0..1  overall motion energy
uniform float uBeat;      // 0..1  decaying beat flash
uniform float uSpread;    // 0..   hand spread
uniform float uScale;     // 0..   geometry scale
uniform float uBreath;    // 0..1  LFO breath
uniform float uPulse;     // 0..1  LFO pulse
uniform float uShimmer;   // 0..1  LFO shimmer
uniform float uOrbit;     // 0..1  LFO orbit
uniform float uCx;        // -1..1 hand centroid X
uniform float uCy;        // -1..1 hand centroid Y
uniform float uChroma;    // 0..   chromatic aberration amount

out vec4 fragColor;

// ----------------------------------------------------------------
// Utilities
// ----------------------------------------------------------------

vec3 hsv2rgb(vec3 c) {
    vec4 K = vec4(1.0, 2.0/3.0, 1.0/3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

float luminance(vec3 col) {
    return dot(col, vec3(0.2126, 0.7152, 0.0722));
}

// Radial signed distance to a ring
float ring_sdf(vec2 uv, vec2 center, float radius, float width) {
    float d = length(uv - center) - radius;
    return 1.0 - smoothstep(0.0, width, abs(d));
}

// Chromatic aberration: sample R/G/B at offset UVs
vec4 chromatic_sample(sampler2D tex, vec2 uv, float amt) {
    vec2 dir = normalize(uv - vec2(0.5));
    float r = texture(tex, uv + dir * amt * 1.2).r;
    float g = texture(tex, uv).g;
    float b = texture(tex, uv - dir * amt * 1.0).b;
    return vec4(r, g, b, texture(tex, uv).a);
}

// Soft glow bloom pass (single tap — full bloom needs a Blur TOP upstream)
vec3 neon_bloom(vec3 col, float intensity) {
    float lum   = luminance(col);
    vec3  glow  = col * lum * intensity;
    return col + glow;
}

// Film-grain
float grain(vec2 uv, float time) {
    float n = fract(sin(dot(uv * 300.0 + time, vec2(127.1, 311.7))) * 43758.5);
    return n * 2.0 - 1.0;
}

// Scanlines (horizontal)
float scanline(vec2 uv, float count, float strength) {
    float sl = sin(uv.y * count * 3.14159) * 0.5 + 0.5;
    return 1.0 - sl * strength;
}

// Vignette
float vignette(vec2 uv, float radius, float softness) {
    float d = length(uv - 0.5) * 2.0;
    return smoothstep(radius + softness, radius - softness, d);
}

// ----------------------------------------------------------------
// Main
// ----------------------------------------------------------------

void main() {
    vec2 uv  = vUV.st;
    vec2 uvc = uv - 0.5;              // centered -0.5..0.5

    float time = float(uTD2DInfos[0].z) * 0.016667; // approx seconds

    // ------ Chromatic aberration on render input ------
    float chroma_amt = uChroma + uBeat * 0.008 + uEnergy * 0.003;
    vec4 render = chromatic_sample(sTD2DInputs[0], uv, chroma_amt);

    // ------ Optional webcam underlay blend ------
    vec4 webcam  = texture(sTD2DInputs[1], uv);
    // Darken webcam so neon pops. Adjust mix weight to taste.
    vec3 base    = mix(webcam.rgb * 0.25, render.rgb, render.a + 0.3);

    // ------ Neon bloom on the geometry layer ------
    float bloom_int = 1.0 + uEnergy * 1.4 + uBeat * 2.0 + uBreath * 0.5;
    vec3 bloomed    = neon_bloom(render.rgb, bloom_int);

    // ------ Hue shift driven by uHue ------
    float lum       = luminance(bloomed);
    vec3  accent    = hsv2rgb(vec3(uHue + 0.5, 0.8, 1.0));
    vec3  col       = mix(bloomed, bloomed * accent * 1.4, uEnergy * 0.35);

    // ------ Radial pulse ring (emanates from hand centroid on beat) ------
    vec2 hand_uv = vec2(uCx * 0.5 + 0.5, uCy * 0.5 + 0.5);
    float ring_t = uBeat;
    float ring_r = ring_t * 0.5;
    float ring_w = 0.025 + (1.0 - ring_t) * 0.04;
    float ring   = ring_sdf(uv, hand_uv, ring_r, ring_w) * ring_t;
    vec3 ring_col = hsv2rgb(vec3(uHue, 0.7, 1.0));
    col += ring_col * ring * 2.0;

    // ------ Secondary pulse ring (slower, always on) ------
    float ring2_r = 0.12 + uBreath * 0.06;
    float ring2   = ring_sdf(uv, hand_uv, ring2_r, 0.008) * (0.3 + uPulse * 0.4);
    col += ring_col * ring2 * 0.6;

    // ------ Shimmer iridescence across the frame ------
    float shimmer_mask = sin(uv.x * 8.0 + time * 2.1) * sin(uv.y * 6.0 - time * 1.7);
    vec3  irid_col     = hsv2rgb(vec3(fract(uHue + shimmer_mask * 0.15), 0.9, 1.0));
    col = mix(col, col * irid_col, uShimmer * 0.12 + uBeat * 0.08);

    // ------ Overlay base (webcam) ------
    col = col + base * 0.18;

    // ------ Scanlines (subtle CRT hologram feel) ------
    float sl = scanline(uv, 240.0, 0.04 + uEnergy * 0.02);
    col *= sl;

    // ------ Grain (very light, keeps it organic) ------
    float g = grain(uv, time);
    col += g * 0.012;

    // ------ Vignette ------
    float vig = vignette(uv, 0.85, 0.45);
    col *= vig;

    // ------ Edge glow (frame border lights up on beat) ------
    float edge_d = min(min(uv.x, 1.0 - uv.x), min(uv.y, 1.0 - uv.y));
    float edge   = smoothstep(0.06, 0.0, edge_d) * uBeat;
    col += ring_col * edge * 1.5;

    // ------ Tone map + gamma ------
    col = col / (col + 0.6);   // Reinhard-lite
    col = pow(max(col, 0.0), vec3(0.92));

    fragColor = vec4(col, 1.0);
}
