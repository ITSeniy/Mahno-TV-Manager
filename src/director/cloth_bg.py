"""Renders the animated "silk cloth" background as a seamless looping video.

This is the flowing REN-TV-style satin that the continuity cards sit on. It's a
one-time asset (render_cloth_bg.py): a WebGL fold shader captured frame by frame
into a short MP4 that loops without a visible seam, then card_render composites
each card's transparent foreground over it.

Seamless loop trick: the shader is driven by a loop phase T in [0, 1) instead of
wall-clock time. Every time-varying term is made periodic in T, so the frame at
T -> 1 is identical to T = 0:
  - the fold drift `p.x*1.3 - NX*TAU*T` shifts by an integer number of 2*PI over
    one loop (NX even so the half-harmonic sin(phase*0.5-..) also closes);
  - the domain warp orbits a circle `R*(cos, sin)(TAU*T)` and returns to start.
The spatial pattern needn't tile - only the time loop must, which it does.

Playwright renders WebGL headlessly via SwiftShader (software GL), so no GPU is
needed on the render box. window.setLoopT(t) draws exactly one deterministic
frame (no requestAnimationFrame), which we screenshot per frame.
"""

import subprocess
import tempfile
from pathlib import Path

CLOTH_WIDTH = 720
CLOTH_HEIGHT = 480
CLOTH_FPS = 25
CLOTH_FRAMES = 250  # 250 / 25fps = a 10s seamless loop

# Headless Chromium needs software GL to give us a real WebGL context.
_GL_ARGS = [
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-webgl",
    "--ignore-gpu-blocklist",
    "--max-active-webgl-contexts=32",
]

CLOTH_HTML = f"""<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{{margin:0;padding:0;background:#0a1030;overflow:hidden}}
  canvas{{display:block;width:{CLOTH_WIDTH}px;height:{CLOTH_HEIGHT}px}}
</style></head><body>
<canvas id="c" width="{CLOTH_WIDTH}" height="{CLOTH_HEIGHT}"></canvas>
<script>
const VS = `attribute vec2 p; void main(){{ gl_Position=vec4(p,0.0,1.0); }}`;
const FS = `
precision highp float;
uniform vec2 u_res; uniform float u_loopT;
const float TAU = 6.28318530718;
const float NX = 2.0;   // whole folds swept per loop (even -> half-harmonic closes)
const float R  = 0.35;  // domain-warp orbit radius
float hash(vec2 p){{ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453123); }}
float noise(vec2 p){{ vec2 i=floor(p),f=fract(p); f=f*f*(3.0-2.0*f);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y); }}
float fbm(vec2 p){{ float v=0.0,a=0.5; for(int i=0;i<3;i++){{ v+=a*noise(p); p=p*2.0+7.0; a*=0.5; }} return v; }}
float height(vec2 p){{
  float A = TAU*u_loopT;                                 // loop angle
  float w = fbm(p*0.6 + R*vec2(cos(A), sin(A)));         // warp orbits -> periodic
  float phase = p.x*1.3 - NX*A + w*4.2 + p.y*0.4;        // drifts +x, closes over the loop
  float f = sin(phase)*0.72 + sin(phase*0.5 - w*1.5)*0.28;
  return f*0.5+0.5;
}}
void main(){{
  vec2 uv = gl_FragCoord.xy/u_res;
  vec2 p = uv*vec2(3.4,2.0);
  float e = 0.02;
  float h=height(p), hx=height(p+vec2(e,0.0)), hy=height(p+vec2(0.0,e));
  vec3 n = normalize(vec3((h-hx)/e,(h-hy)/e,2.2));
  vec3 L = normalize(vec3(0.62,0.35,0.80));
  float diff = clamp(dot(n,L)*0.5+0.5,0.0,1.0);
  float spec = pow(clamp(dot(reflect(-L,n),vec3(0,0,1)),0.0,1.0),14.0);
  vec3 dark=vec3(0.22,0.36,0.60),mid=vec3(0.50,0.68,0.90),lite=vec3(0.95,0.98,1.0);
  vec3 col=mix(dark,mid,diff);
  col=mix(col,lite, spec*0.8 + smoothstep(0.80,1.0,h)*0.32);
  gl_FragColor=vec4(col,1.0);
}}`;
const cv = document.getElementById('c');
// preserveDrawingBuffer so each drawn frame survives until the screenshot reads it.
const gl = cv.getContext('webgl', {{preserveDrawingBuffer:true}}) || cv.getContext('experimental-webgl', {{preserveDrawingBuffer:true}});
function sh(t,s){{ const o=gl.createShader(t); gl.shaderSource(o,s); gl.compileShader(o);
  if(!gl.getShaderParameter(o,gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(o)); return o; }}
const pr=gl.createProgram(); gl.attachShader(pr,sh(gl.VERTEX_SHADER,VS)); gl.attachShader(pr,sh(gl.FRAGMENT_SHADER,FS));
gl.linkProgram(pr); gl.useProgram(pr);
const b=gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER,b);
gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);
const lp=gl.getAttribLocation(pr,'p'); gl.enableVertexAttribArray(lp); gl.vertexAttribPointer(lp,2,gl.FLOAT,false,0,0);
const uR=gl.getUniformLocation(pr,'u_res'), uT=gl.getUniformLocation(pr,'u_loopT');
gl.viewport(0,0,cv.width,cv.height);
// Deterministic single-frame draw for offline capture (no rAF).
window.setLoopT = function(t){{
  gl.uniform2f(uR, cv.width, cv.height);
  gl.uniform1f(uT, t);
  gl.drawArrays(gl.TRIANGLES,0,3);
  gl.finish();
}};
window.setLoopT(0.0);
</script></body></html>"""


def _run_ffmpeg(cmd: list[str], what: str, produced: Path) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0 or not produced.exists():
        raise RuntimeError(f"ffmpeg failed {what} (exit {result.returncode}): {result.stderr.strip()[-800:]}")


def render_cloth_loop(out_mp4: Path, frames: int = CLOTH_FRAMES, fps: int = CLOTH_FPS) -> Path:
    """Capture `frames` deterministic shader frames and encode a seamless
    silent H.264 loop at 720x480. Playwright is imported lazily so importing
    this module (e.g. for the shader string in tests) needs no browser."""
    from playwright.sync_api import sync_playwright

    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        with sync_playwright() as p:
            browser = p.chromium.launch(args=_GL_ARGS)
            try:
                page = browser.new_page(
                    viewport={"width": CLOTH_WIDTH, "height": CLOTH_HEIGHT}, device_scale_factor=1
                )
                page.set_content(CLOTH_HTML, wait_until="load")
                page.wait_for_function("typeof window.setLoopT === 'function'")
                canvas = page.query_selector("canvas")
                for i in range(frames):
                    page.evaluate("(t) => window.setLoopT(t)", i / frames)
                    canvas.screenshot(path=str(tdp / f"frame{i:04d}.png"))
            finally:
                browser.close()

        _run_ffmpeg(
            ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(tdp / "frame%04d.png"),
             "-s", f"{CLOTH_WIDTH}x{CLOTH_HEIGHT}", "-pix_fmt", "yuv420p",
             "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-an", str(out_mp4)],
            "encoding cloth loop", out_mp4,
        )
    return out_mp4
