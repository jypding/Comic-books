uniform float uOutlineWidth;
void main() {
  // 沿法线膨胀：backside hull
  vec3 p = position + normal * uOutlineWidth;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}