/**
 * GLB 加载器（迁移自旧 app.js 的 GLB Loader）
 *
 * 职责：加载 ModernExporter 输出的标准 GLB，提取原生 three 对象。
 * 关键约束：不修改 GLB 相机数据；相机与动画轨道原样交给上层使用。
 */
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

export interface LoadedGlb {
  scene: THREE.Group;
  cameras: THREE.Camera[]; // GLB 内原生相机对象
  animations: THREE.AnimationClip[]; // GLB 内原生动画轨道（含相机 NLA）
}

const loader = new GLTFLoader();

export async function loadGlb(url: string): Promise<LoadedGlb> {
  const gltf = await loader.loadAsync(url);

  const cameras: THREE.Camera[] = [];
  gltf.scene.traverse((o) => {
    if ((o as THREE.Camera).isCamera) cameras.push(o as THREE.Camera);
  });

  return {
    scene: gltf.scene,
    cameras,
    animations: gltf.animations,
  };
}

export { loader };
