// In-game CRT shader
// Author: sarphiv
// License: CC BY-NC-SA 4.0
// Description:
//   Shader for Ghostty with a focus on being usable while looking like a stylized CRT terminal from a modern video game.
//   + top/bottom text blur/distortion + rich saturated orange + animated film grain (vhs style, in crt on text)
//   + micro drift + light VHS wobble + tape wear (from vhs.glsl)

// Based on:
//   1. https://gist.github.com/mitchellh/39d62186910dcc27cad097fed16eb882 (forces the choice of license)
//   2. https://gist.github.com/qwerasd205/c3da6c610c8ffe17d6d2d3cc7068f17f
//   3. https://gist.github.com/seanwcom/0fbe6b270aaa5f28823e053d3dbb14ca
//   4. https://www.shadertoy.com/view/ltB3zD



// Settings:
// How straight the terminal is in each axis
// (x, y) \in R^2 : x, y > 0
// Increased for flatter, no wave effect
#define CURVE 3.3, 3.0  // lens reduced 1.5x (flatter)

// How far apart the different colors are from each other
// x \in R
#define COLOR_FRINGING_SPREAD 0.0  // no RGB color anywhere

// How much the ghost images are spread out
// x \in R : x >= 0
#define GHOSTING_SPREAD 0.5
// How visible ghost images are
// x \in R : x >= 0
#define GHOSTING_STRENGTH 0.0  // disabled to remove halo/outline on background

// How much of the non-linearly darkened colors are mixed in
// [0, 1]
#define DARKEN_MIX 0.4

// How far in the vignette spreads
// x \in R : x >= 0
#define VIGNETTE_SPREAD 0.3
// How bright the vignette is
// x \in R : x >= 0
#define VIGNETTE_BRIGHTNESS 1.65  // слегка ярче в центре

// Tint all colors
// [0, 1]^3
#define TINT 1.0, 0.68, 0.25  // richer more saturated beautiful orange (stronger pull)

// How visible the scan line effect is
// NOTE: Technically these are not scan lines, but rather the lack of them
// [0, 1]
#define SCAN_LINES_STRENGTH 0.08
// How bright the spaces between the lines are
// [0, 1]
#define SCAN_LINES_VARIANCE 0.25
// Pixels per scan line effect
// x \in R : x > 0
#define SCAN_LINES_PERIOD 4.0

// How visible the aperture grille is
// x \in R : x >= 0
#define APERTURE_GRILLE_STRENGTH 0.08
// Pixels per aperture grille
// x \in R : x > 0
#define APERTURE_GRILLE_PERIOD 2.0

// How much the screen flickers
// x \in R : x >= 0
#define FLICKER_STRENGTH 0.005
// How fast the screen flickers
// x \in R : x > 0
#define FLICKER_FREQUENCY 15.0

// How big the bloom is
// x \in R : x >= 0
#define BLOOM_SPREAD 8.0
// How visible the bloom is
// [0, 1]
#define BLOOM_STRENGTH 0.0  // no extra bloom/glow, only main CRT + color

// Backgrond opacity
// [0, 1]
#define BACKGROUND_OPACITY 1.0


// Disabled values for when the settings are not defined
#ifndef COLOR_FRINGING_SPREAD
#define COLOR_FRINGING_SPREAD 0.0
#endif

#if !defined(GHOSTING_SPREAD) || !defined(GHOSTING_STRENGTH)
#undef GHOSTING_SPREAD
#undef GHOSTING_STRENGTH
#define GHOSTING_SPREAD 0.0
#define GHOSTING_STRENGTH 0.0
#endif

#ifndef DARKEN_MIX
#define DARKEN_MIX 0.0
#endif

#if !defined(VIGNETTE_SPREAD) || !defined(VIGNETTE_BRIGHTNESS)
#undef VIGNETTE_SPREAD
#undef VIGNETTE_BRIGHTNESS
#define VIGNETTE_SPREAD 0.0
#define VIGNETTE_BRIGHTNESS 1.0
#endif

#ifndef TINT
#define TINT 1.0, 0.68, 0.25
#endif

#if !defined(SCAN_LINES_STRENGTH) || !defined(SCAN_LINES_VARIANCE) || !defined(SCAN_LINES_PERIOD)
#undef SCAN_LINES_STRENGTH
#undef SCAN_LINES_VARIANCE
#undef SCAN_LINES_PERIOD
#define SCAN_LINES_STRENGTH 0.0
#define SCAN_LINES_VARIANCE 1.0
#define SCAN_LINES_PERIOD 1.0
#endif

#if !defined(APERTURE_GRILLE_STRENGTH) || !defined(APERTURE_GRILLE_PERIOD)
#undef APERTURE_GRILLE_STRENGTH
#undef APERTURE_GRILLE_PERIOD
#define APERTURE_GRILLE_STRENGTH 0.0
#define APERTURE_GRILLE_PERIOD 1.0
#endif

#if !defined(FLICKER_STRENGTH) || !defined(FLICKER_FREQUENCY)
#undef FLICKER_STRENGTH
#undef FLICKER_FREQUENCY
#define FLICKER_STRENGTH 0.0
#define FLICKER_FREQUENCY 1.0
#endif

#if !defined(BLOOM_SPREAD) || !defined(BLOOM_STRENGTH)
#undef BLOOM_SPREAD
#undef BLOOM_STRENGTH
#define BLOOM_SPREAD 0.0
#define BLOOM_STRENGTH 0.0
#endif

#ifndef BACKGROUND_OPACITY
#define BACKGROUND_OPACITY 1.0
#endif



// Constants:
#define PI 3.1415926535897932384626433832795

#ifdef BLOOM_SPREAD
// Golden spiral samples used for bloom.
//   [x, y, weight] weight is inverse of distance.
const vec3[24] bloomSamples = {
    vec3( 0.1693761725038636,  0.9855514761735895,  1),
    vec3(-1.333070830962943,   0.4721463328627773,  0.7071067811865475),
    vec3(-0.8464394909806497, -1.51113870578065,    0.5773502691896258),
    vec3( 1.554155680728463,  -1.2588090085709776,  0.5),
    vec3( 1.681364377589461,   1.4741145918052656,  0.4472135954999579),
    vec3(-1.2795157692199817,  2.088741103228784,   0.4082482904638631),
    vec3(-2.4575847530631187, -0.9799373355024756,  0.3779644730092272),
    vec3( 0.5874641440200847, -2.7667464429345077,  0.35355339059327373),
    vec3( 2.997715703369726,   0.11704939884745152, 0.3333333333333333),
    vec3( 0.41360842451688395, 3.1351121305574803,  0.31622776601683794),
    vec3(-3.167149933769243,   0.9844599011770256,  0.30151134457776363),
    vec3(-1.5736713846521535, -3.0860263079123245,  0.2886751345948129),
    vec3( 2.888202648340422,  -2.1583061557896213,  0.2773500981126146),
    vec3( 2.7150778983300325,  2.5745586041105715,  0.2672612419124244),
    vec3(-2.1504069972377464,  3.2211410627650165,  0.2581988897471611),
    vec3(-3.6548858794907493, -1.6253643308191343,  0.25),
    vec3( 1.0130775986052671, -3.9967078676335834,  0.24253562503633297),
    vec3( 4.229723673607257,   0.33081361055181563, 0.23570226039551587),
    vec3( 0.40107790291173834, 4.340407413572593,   0.22941573387056174),
    vec3(-4.319124570236028,   1.159811599693438,   0.22360679774997896),
    vec3(-1.9209044802827355, -4.160543952132907,   0.2182178902359924),
    vec3( 3.8639122286635708, -2.6589814382925123,  0.21320071635561041),
    vec3( 3.3486228404946234,  3.4331800232609,     0.20851441405707477),
    vec3(-2.8769733643574344,  3.9652268864187157,  0.20412414523193154)
};
#endif

// Hash from vhs.glsl for animated film grain
float hash(vec2 p) {
    p = fract(p * vec2(443.8975, 397.2973));
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    // Get texture coordinates
    vec2 uv = fragCoord.xy / iResolution.xy;

#ifdef CURVE
    // Curve texture coordinates to mimic non-flat CRT monior
    uv = (uv - 0.5) * 2.0;
    uv.xy *= 1.0 + pow((abs(vec2(uv.y, uv.x)) / vec2(CURVE)), vec2(2.0));
    uv = (uv / 2.0) + 0.5;
#endif

    // Light top & bottom blur + distortion — applied specifically to the TEXT at its top and bottom lines (gated + stronger)
    vec2 base_uv = uv;
    float dist_v = min(uv.y, 1.0 - uv.y);
    float tb_factor = 1.0 - smoothstep(0.0, 0.26, dist_v);   // wider ramp so top/bottom text lines are covered
    if (tb_factor > 0.001) {
        // stronger distortion for visible warp on text at edges (still slow, no shake)
        float phase = uv.y * 5.5 + iTime * 0.07;
        float h_distort = sin(phase) * 0.0028 * tb_factor;
        float v_distort = sin(phase * 1.4) * 0.0013 * tb_factor;
        base_uv.x += h_distort;
        base_uv.y += v_distort;
    }

    // === EFFECT #2 (added carefully): Micro horizontal scan drift / jitter
    // Very subtle vertical jitter on scanlines/text, like old CRT.
    // Tiny amplitude, animated with iTime. Applied to sampling.
    float micro_drift = sin(fragCoord.y * 1.15 + iTime * 0.65) * 0.00038;
    micro_drift += sin(fragCoord.y * 0.55 + iTime * 0.19) * 0.00025;
    base_uv.y += micro_drift;

    // Very light VHS wobble (core sin wobble from vhs.glsl, reduced for cosmetic use)
    // No tracking, no bursts, no jumps — only gentle living wobble on text.
    float vhs_wobble = sin(uv.y * 4.5 + iTime * 1.1) * 0.00025;
    vhs_wobble += sin(uv.y * 8.5 + iTime * 2.9) * 0.00015;
    base_uv.x += vhs_wobble;

    // Retrieve colors from appropriate locations (distorted sampling → text at top/bottom is warped)
    fragColor.r = texture(iChannel0, vec2(base_uv.x + 0.0003 * COLOR_FRINGING_SPREAD, base_uv.y + 0.0003 * COLOR_FRINGING_SPREAD)).x;
    fragColor.g = texture(iChannel0, vec2(base_uv.x + 0.0000 * COLOR_FRINGING_SPREAD, base_uv.y - 0.0006 * COLOR_FRINGING_SPREAD)).y;
    fragColor.b = texture(iChannel0, vec2(base_uv.x - 0.0006 * COLOR_FRINGING_SPREAD, base_uv.y + 0.0000 * COLOR_FRINGING_SPREAD)).z;
    fragColor.a = texture(iChannel0, base_uv).a;

    vec3 original_color = fragColor.rgb;  // preserve for pure background (before ghosting)

    // Vertical blur ONLY on text pixels that are near top or bottom
    float early_lum = dot(fragColor.rgb, vec3(0.299, 0.587, 0.114));
    float text_tb = tb_factor * smoothstep(0.06, 0.22, early_lum);   // gate to actual bright text
    if (text_tb > 0.015) {
        float br = 0.0038 * text_tb;   // ~6-8px blur at edges — now visible on text
        vec2 off1 = vec2(0.0, br);
        vec2 off2 = vec2(0.0, br * 1.7);
        vec4 c1 = texture(iChannel0, base_uv + off1);
        vec4 c2 = texture(iChannel0, base_uv - off1);
        vec4 c3 = texture(iChannel0, base_uv + off2);
        vec4 c4 = texture(iChannel0, base_uv - off2);
        vec3 blurred = (fragColor.rgb + c1.rgb + c2.rgb + c3.rgb + c4.rgb) * 0.2;
        fragColor.rgb = mix(fragColor.rgb, blurred, 0.85);
    }

    // Add faint ghost images
    fragColor.r += 0.04 * GHOSTING_STRENGTH * texture(iChannel0, GHOSTING_SPREAD * vec2(+0.025, -0.027) + uv.xy).x;
    fragColor.g += 0.02 * GHOSTING_STRENGTH * texture(iChannel0, GHOSTING_SPREAD * vec2(-0.022, -0.020) + uv.xy).y;
    fragColor.b += 0.04 * GHOSTING_STRENGTH * texture(iChannel0, GHOSTING_SPREAD * vec2(-0.020, -0.018) + uv.xy).z;

    // Quadratically darken ONLY content (not pure bg)
    float pre_dark_lum = dot(fragColor.rgb, vec3(0.299, 0.587, 0.114));
    float dark_mask = smoothstep(0.02, 0.15, pre_dark_lum);
    fragColor.rgb = mix(fragColor.rgb, fragColor.rgb*fragColor.rgb, DARKEN_MIX * dark_mask);


    // Vignette effect
    // NOTE: Clamp necessary because of curve effect
    fragColor.rgb *= VIGNETTE_BRIGHTNESS * pow(clamp(uv.x * uv.y * (1.0-uv.x) * (1.0-uv.y), 0.0, 1.0), VIGNETTE_SPREAD);


    // Tint ONLY bright parts (text). Keep pure dark background (#050505) without color cast.
    // Halo/AA edge pixels stay dark, no tint on them.
    float lum = dot(fragColor.rgb, vec3(0.299, 0.587, 0.114));
    vec3 tinted = fragColor.rgb * vec3(TINT);
    fragColor.rgb = mix(fragColor.rgb, tinted, smoothstep(0.15, 0.3, lum));  // slightly more saturated now via TINT


    // NOTE: At this point, RGB values may be above 1


    // Add scan lines effect ONLY on text (keep pure dark bg)
    float content_mask = smoothstep(0.02, 0.15, lum);
    fragColor.rgb *= mix(
        1.0,
        SCAN_LINES_VARIANCE/2.0*(1.0 + sin(2*PI* uv.y * iResolution.y/SCAN_LINES_PERIOD)),
        SCAN_LINES_STRENGTH * content_mask
    );


    // Add aperture grille
    int apertureGrilleStep = int(8 * mod(fragCoord.x, APERTURE_GRILLE_PERIOD) / APERTURE_GRILLE_PERIOD);
    float apertureGrilleMask;

    if (apertureGrilleStep < 3)
        apertureGrilleMask = 0.0;
    else if (apertureGrilleStep < 4)
        apertureGrilleMask = mod(8*fragCoord.x, APERTURE_GRILLE_PERIOD) / APERTURE_GRILLE_PERIOD;
    else if (apertureGrilleStep < 7)
        apertureGrilleMask = 1.0;
    else if (apertureGrilleStep < 8)
        apertureGrilleMask = mod(-8*fragCoord.x, APERTURE_GRILLE_PERIOD) / APERTURE_GRILLE_PERIOD;

    fragColor.rgb *= 1.0 - APERTURE_GRILLE_STRENGTH*apertureGrilleMask * content_mask;


    // Add flicker only on text
    fragColor *= 1.0 - FLICKER_STRENGTH/2.0*(1.0 + sin(2*PI*FLICKER_FREQUENCY*iTime)) * content_mask;

    // Анимированное пленочное зерно (из vhs.glsl) - лёгкое но заметное на тексте включая центр
    float tg = fract(iTime);
    float cn1 = hash(fragCoord.xy + tg * 100.0) - 0.5;

    fragColor.rgb += cn1 * 0.055 * content_mask;
    fragColor.rgb += (dot(fragColor.rgb, vec3(0.299,0.587,0.114)) - 0.5) * cn1 * 0.03 * content_mask;

    float grain = (hash(fragCoord.xy * 0.8 + iTime * 15.0) - 0.5) * 0.05 * content_mask;
    fragColor.rgb += grain;

    // второй слой с другой частотой для живой анимации
    float grain2 = (hash(fragCoord.xy * 2.5 + iTime * 47.0) - 0.5) * 0.03 * content_mask;
    fragColor.rgb += grain2;

    // Very light VHS tape wear / dropouts (from vhs.glsl, reduced for cosmetic use)
    // Subtle horizontal wear lines and occasional dropouts on text.
    {
        float luma = dot(fragColor.rgb, vec3(0.299, 0.587, 0.114));
        float tF = smoothstep(0.1, 0.6, luma);
        float vhs_wear = 0.005;  // low but visible

        // Occasional light horizontal dropout/wear
        float dr = floor(fragCoord.y / 4.0);
        float dt = floor(iTime * 0.12);
        if (hash(vec2(dr, dt)) > 1.0 - 0.002 * vhs_wear) {
            float dx = hash(vec2(dr, dt + 1.0));
            if (uv.x > dx && uv.x < dx + 0.12) {
                fragColor.rgb = mix(fragColor.rgb, vec3(1.0), 0.03 * tF * vhs_wear * 5.0);
            }
        }

        // Occasional top-edge wear (high y)
        if (uv.y > 0.95) {
            float hs = smoothstep(0.96, 1.0, uv.y) * tF;
            fragColor.rgb += hs * (hash(vec2(fragCoord.x, floor(iTime * 4.0))) * 2.0 - 1.0) * 0.02 * vhs_wear;
        }
    }

    fragColor.rgb = clamp(fragColor.rgb, 0.0, 1.0);

    // NOTE: At this point, RGB values are again within [0, 1]


    // Remove output outside of screen bounds
    // if (uv.x < 0.0 || uv.x > 1.0)
    //     fragColor.rgb *= 0.0;
    // if (uv.y < 0.0 || uv.y > 1.0)
    //     fragColor.rgb *= 0.0;


#ifdef BLOOM_SPREAD
    // Add bloom
    vec2 step = BLOOM_SPREAD * vec2(1.414) / iResolution.xy;

    for (int i = 0; i < 24; i++) {
        vec3 bloomSample = bloomSamples[i];
        vec4 neighbor = texture(iChannel0, uv + bloomSample.xy * step);
        float luminance = 0.299 * neighbor.r + 0.587 * neighbor.g + 0.114 * neighbor.b;

        fragColor += luminance * bloomSample.z * neighbor * BLOOM_STRENGTH;
    }

    fragColor = clamp(fragColor, 0.0, 1.0);
#endif


    // Set background opacity
    fragColor = vec4(fragColor.rgb*fragColor.a, BACKGROUND_OPACITY);

    // Clip low-luma pixels (font AA halo + shader processing) to pure background.
    // Eliminates the lighter outline behind new text. 
    float final_lum = dot(fragColor.rgb, vec3(0.299, 0.587, 0.114));
    if (final_lum < 0.04) {
      fragColor.rgb = vec3(0.0196);  // pure #050505
    }
}
