uniform sampler2D tDiffuse;
uniform vec2      uResolution;
uniform float     uToneBlack;
uniform float     uToneWhite;
uniform float     uBands;
uniform float     uHatchDensity;

varying vec2 vUv;

void main() {
  vec3 src = texture2D(tDiffuse, vUv).rgb;

  // 1. grayscale
  float lit = dot(src, vec3(0.2126, 0.7152, 0.0722));

  // 2. tone
  float tone = smoothstep(uToneBlack, uToneWhite, lit);
  tone = clamp(tone, 0.0, 1.0);

  // 3. bands（灰阶分层）
  float bands = max(uBands, 1.0);
  float scaled = tone * bands;
  float lower  = floor(scaled);
  float frac   = scaled - lower;
  float stepv  = step(0.5, frac);
  float banded = clamp((lower + stepv) / bands, 0.0, 1.0);

  // 4. hatch 线
  float darkness = 1.0 - banded;
  vec2 suv = gl_FragCoord.xy / uResolution;
  // 45°斜线：斜率=1
  float s = (suv.x + suv.y) * uHatchDensity * 3.14159;
  float line = abs(sin(s));
  // 线宽：line < 0.35 算“墨线”
  float hatchLine = 1.0 - step(0.35, line);   // 1=墨线, 0=空白

  // 5. 只在暗部叠线：暗度越大，线越明显
  float hatchStrength = smoothstep(0.4, 1.0, darkness);

  // 6. 合成：
  //    outVal = 底色 * (1 - line*strength)  → 在线条处压暗底色
  float outVal = banded - hatchLine * hatchStrength * 0.55;
  outVal = clamp(outVal, 0.0, 1.0);

  gl_FragColor = vec4(vec3(outVal), 1.0);
}