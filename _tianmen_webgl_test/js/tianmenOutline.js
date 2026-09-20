import * as THREE from 'three';

export function attachTianmenOutline(root, opts = {}) {
  const width = opts.width ?? 0.02;
  const color = new THREE.Color(opts.color ?? 0.04);

  const outlines = [];
  const meshes = [];

  root.traverse((o) => {
    if (o.isMesh) meshes.push(o);
  });

  meshes.forEach((src) => {
    if (!src.geometry || !src.geometry.attributes || !src.geometry.attributes.normal) {
      console.warn('[outline] skip (no normal):', src.name);
      return;
    }

    const outlineMat = new THREE.ShaderMaterial({
      uniforms: {
        uOutlineWidth: { value: width },
        uOutlineColor: { value: color.clone() },
      },
      vertexShader: `
        uniform float uOutlineWidth;
        void main() {
          vec3 p = position + normal * uOutlineWidth;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
        }
      `,
      fragmentShader: `
        uniform vec3 uOutlineColor;
        void main() {
          gl_FragColor = vec4(uOutlineColor, 1.0);
        }
      `,
      side: THREE.BackSide,
      depthWrite: true,
    });

    const outlineMesh = new THREE.Mesh(src.geometry, outlineMat);
    outlineMesh.name = src.name + '_outline';
    outlineMesh.castShadow = false;
    outlineMesh.receiveShadow = false;
    outlineMesh.renderOrder = -1;
    outlineMesh.frustumCulled = false;

    // 关键：和 src 做兄弟，用局部变换（不用 world 矩阵），避免双重变换
    outlineMesh.position.copy(src.position);
    outlineMesh.quaternion.copy(src.quaternion);
    outlineMesh.scale.copy(src.scale);

    src.parent.add(outlineMesh);

    outlines.push({ mesh: outlineMesh, material: outlineMat, src });
  });

  return {
    outlines,
    setWidth(w) {
      outlines.forEach((o) => { o.material.uniforms.uOutlineWidth.value = w; });
    },
    setColor(c) {
      outlines.forEach((o) => { o.material.uniforms.uOutlineColor.value.set(c); });
    },
    update() {
      outlines.forEach((o) => {
        o.mesh.matrix.copy(o.src.matrixWorld);
        o.mesh.matrixWorldNeedsUpdate = true;
      });
    }
  };
}