/* 烟雾层：主页与 Demo 页共用 */
/* ===== 烟雾特效 ===== */
(function smokeLayer(){
  const cv = document.getElementById('smoke');
  if(!cv) return;
  if(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const gl = cv.getContext('webgl', {alpha:true, antialias:false,
                                     premultipliedAlpha:false, powerPreference:'low-power'});
  if(!gl){ cv.style.display = 'none'; return; }   // 没有 WebGL 就交给下面那层 CSS 雾

  const VS = `
    attribute vec2 a;
    void main(){ gl_Position = vec4(a, 0.0, 1.0); }`;

  const FS = `
    precision highp float;
    uniform vec2  u_res;
    uniform float u_time;
    uniform vec4  u_shots[8];      /* xy=起点 t0=开火时刻 w=威力 */
    uniform vec4  u_dirs[8];       /* xy=方向 z=速度 w=尾流宽度（xy≈0 表示手雷） */

    float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }
    float vnoise(vec2 p){
      vec2 i = floor(p), f = fract(p);
      vec2 u = f * f * (3.0 - 2.0 * f);
      return mix(mix(hash(i),                 hash(i + vec2(1.0, 0.0)), u.x),
                 mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
    }
    float fbm(vec2 p){
      mat2 rot = mat2(0.80, 0.60, -0.60, 0.80);
      float v = 0.0, a = 0.55;
      for(int i = 0; i < 5; i++){ v += a * vnoise(p); p = rot * p * 2.03; a *= 0.5; }
      return v;
    }

    void main(){
      vec2 uv  = gl_FragCoord.xy / u_res;
      float asp = u_res.x / u_res.y;
      vec2 p = vec2(uv.x * asp, uv.y) * 3.1;
      float t = u_time * 0.06;

      /* 双层 domain warping —— 烟雾卷曲、撕裂的来源 */
      vec2 q = vec2(fbm(p + vec2(0.0, t * 0.7)), fbm(p + vec2(5.2, 1.3)));
      vec2 r = vec2(fbm(p + 3.6 * q + vec2(1.7, 9.2) + t * 1.2),
                    fbm(p + 3.6 * q + vec2(8.3, 2.8) - t * 0.9));
      /* ---- 弹道：贯穿屏幕的尾流；手雷走径向冲击 ---- */
      vec2 warp = vec2(0.0);
      float flash = 0.0;
      float squeeze = 0.0;   /* 弹道附近噪声被压缩的程度 */
      float carve = 0.0;     /* 弹道中心的通道（烟被清开） */
      for(int i = 0; i < 8; i++){
        vec4 s = u_shots[i];
        if(s.z <= 0.0) continue;
        float age = u_time - s.z;
        if(age < 0.0 || age > 2.4) continue;
        vec4 d = u_dirs[i];
        float dlen = length(d.xy);

        if(dlen < 0.1){
          /* 手雷：径向冲击波 */
          vec2 dv = p - s.xy;
          float rr = max(length(dv), 1e-4);
          float front = age * (1.5 + s.w * 1.5);
          float band  = exp(-pow((rr - front) / (0.30 + s.w * 0.50), 2.0));
          float amp   = band * exp(-age * 1.7) * s.w;
          warp  += (dv / rr) * amp * 0.70;
          flash += amp * exp(-rr * 1.2) * 0.50;
        } else {
          /* 子弹：沿弹道穿过屏幕，把烟横向撕开 */
          vec2 dir = d.xy / dlen;
          vec2 ap  = p - s.xy;
          float head  = age * d.z;                        /* 弹头已飞出的距离 */
          float along = clamp(dot(ap, dir), 0.0, head);    /* 投影到已飞过的那段 */
          vec2 perpV  = ap - dir * along;
          float perp  = length(perpV);

          float trail = exp(-pow(perp / d.w, 2.0));        /* 线状：贴弹道最浓 */
          trail *= exp(-(head - along) * 0.60);            /* 尾巴越后越淡 */
          trail *= exp(-age * 0.95);

          vec2 nrm = perp > 1e-5 ? perpV / perp : vec2(0.0);

          /* 横向撕开：位移垂直弹道，量级接近噪声特征尺度 → 才拉得出丝 */
          warp += nrm * trail * s.w * 2.40;
          /* 沿弹道方向拖行一点，做出尾流的"被带走"感 */
          warp += dir * trail * s.w * 0.80;
          /* 局部压缩：弹道附近噪声频率升高 → 细节变密、出现细丝 */
          squeeze += trail * s.w;
          /* 弹道中心被清出的窄通道 */
          carve += trail * s.w * 0.40;

          flash += trail * s.w * 0.12;                     /* 只留一点亮，不靠它出效果 */
          flash += exp(-length(p - (s.xy + dir * head)) / 0.11) * s.w * 0.45;
        }
      }

      /* 弹道附近把采样坐标压密 → 噪声细节变细，才撕得出丝 */
      vec2 pw = (p + warp) * (1.0 + squeeze * 0.32);

      float f = fbm(pw + 4.6 * r);

      /* 纵向拉伸 + 缓慢上流，像烟往上升 */
      float up = fbm(vec2(pw.x * 1.18, pw.y * 0.50 - t * 2.0) + 2.6 * r);
      f = mix(f, up, 0.62);

      /* 颗粒：高频噪声调制密度，随烟流动，避免塑料感的平滑 */
      float grain = vnoise(p * 27.0 + vec2(t * 2.0, -t * 1.6));
      f += (grain - 0.5) * 0.11;

      /* fbm 集中在 0.4~0.65，窗口放宽一点 → 对比更柔和 */
      float d = smoothstep(0.395, 0.715, f);
      d *= smoothstep(0.0, 0.24, uv.y) * smoothstep(1.0, 0.78, uv.y);
      /* 弹道中心清出通道：烟被子弹带走了 */
      d *= 1.0 - clamp(carve, 0.0, 0.50);

      gl_FragColor = vec4(vec3(0.0), clamp(d * 0.70 + flash, 0.0, 0.92));
    }`;

  function mkShader(type, src){
    const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if(!gl.getShaderParameter(s, gl.COMPILE_STATUS)) console.warn('[smoke]', gl.getShaderInfoLog(s));
    return s;
  }
  const prog = gl.createProgram();
  gl.attachShader(prog, mkShader(gl.VERTEX_SHADER, VS));
  gl.attachShader(prog, mkShader(gl.FRAGMENT_SHADER, FS));
  gl.linkProgram(prog);
  gl.useProgram(prog);

  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER,
    new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'a');
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

  const uRes  = gl.getUniformLocation(prog, 'u_res');
  const uTime = gl.getUniformLocation(prog, 'u_time');
  const uShots = gl.getUniformLocation(prog, 'u_shots[0]');
  const uDirs  = gl.getUniformLocation(prog, 'u_dirs[0]');

  function resize(){
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    cv.width  = Math.round((cv.clientWidth  || window.innerWidth)  * dpr);
    cv.height = Math.round((cv.clientHeight || window.innerHeight) * dpr);
    gl.viewport(0, 0, cv.width, cv.height);
  }
  resize();
  window.addEventListener('resize', resize);

  /* ---- 开火调度：从屏幕左右射入的弹道（speed=穿越速度 width=尾流粗细） ---- */
  const SLOTS  = 8;
  const shotData = new Float32Array(SLOTS * 4);
  const dirData  = new Float32Array(SLOTS * 4);
  const pending  = [];
  let slotIdx = 0, nextAt = 1.2;

  const TYPES = [   /* burst=连发 gap=间隔 power=威力 spread=散布 rest/rand=冷却 */
    { burst: 1,  gap: 0,    power: .55, spread: 0,   rest: 1.0, rand: 1.2, speed: 6.5,  width: .055 }, // 单点
    { burst: 3,  gap: .095, power: .62, spread: .02, rest: 1.4, rand: 1.6, speed: 7.0,  width: .060 }, // 三连发
    { burst: 10, gap: .072, power: .58, spread: .06, rest: 2.2, rand: 2.4, speed: 7.5,  width: .070 }, // 扫射
    { burst: 2,  gap: .30,  power: .95, spread: .02, rest: 1.9, rand: 2.0, speed: 9.0,  width: .100 }, // 连狙
    { burst: 1,  gap: 0,    power: 1.70, spread: 0,  rest: 2.6, rand: 2.8, speed: 12.0, width: .155 }, // 大狙
    { burst: 1,  gap: 0,    power: 2.60, spread: 0,  rest: 7.0, rand: 8.0, speed: 0,    width: 0    }  // 手雷
  ];
  const WEIGHT = [.32, .24, .18, .12, .09, .05];

  function pickType(){
    let x = Math.random(), acc = 0;
    for(let i = 0; i < WEIGHT.length; i++){ acc += WEIGHT[i]; if(x <= acc) return TYPES[i]; }
    return TYPES[0];
  }

  function fire(tSec){
    const c  = pickType();
    const asp = cv.width / Math.max(cv.height, 1);
    const fromLeft = Math.random() < .5;
    /* 方向在 p 空间里归一化（p 的 x 被 asp 拉伸过，必须同步校正） */
    const ux = fromLeft ? 1 : -1;
    const uy = (Math.random() - .5) * 0.55;
    const dl = Math.hypot(ux * asp, uy) || 1;
    const dirX = (ux * asp) / dl, dirY = uy / dl;

    const x0 = (fromLeft ? 0.03 : 0.97) * asp * 3.1;    // 从左右边缘射入
    const y0 = (0.15 + Math.random() * 0.70) * 3.1;

    for(let i = 0; i < c.burst; i++){
      pending.push({
        x: x0,
        y: y0 + (Math.random() - .5) * c.spread * 3.1,
        t0: tSec + i * c.gap,
        power: c.power * (0.85 + Math.random() * 0.3),
        dirx: dirX, diry: dirY,
        speed: c.speed, width: c.width
      });
    }
    return c.rest + Math.random() * c.rand;
  }

  let last = 0, off = false;
  window.__stopSmoke = () => { off = true; };
  function frame(t){
    if(off) return;
    requestAnimationFrame(frame);
    if(t - last < 40) return;              // ~25fps，烟不需要高帧率
    last = t;
    const tSec = t / 1000;

    /* 到点的冲击写进 uniform 槽位（环形复用） */
    for(let i = pending.length - 1; i >= 0; i--){
      const s = pending[i];
      if(s.t0 <= tSec + 0.02){
        shotData[slotIdx * 4]     = s.x;
        shotData[slotIdx * 4 + 1] = s.y;
        shotData[slotIdx * 4 + 2] = s.t0;
        shotData[slotIdx * 4 + 3] = s.power;
        dirData[slotIdx * 4]      = s.dirx;
        dirData[slotIdx * 4 + 1]  = s.diry;
        dirData[slotIdx * 4 + 2]  = s.speed;
        dirData[slotIdx * 4 + 3]  = s.width;
        slotIdx = (slotIdx + 1) % SLOTS;
        pending.splice(i, 1);
      }
    }
    if(tSec > nextAt) nextAt = tSec + fire(tSec);

    gl.uniform2f(uRes, cv.width, cv.height);
    gl.uniform1f(uTime, tSec);
    gl.uniform4fv(uShots, shotData);
    gl.uniform4fv(uDirs,  dirData);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }
  requestAnimationFrame(frame);
})();

