/**
 * 相机控制器（迁移自旧 app.js 的 Camera 查找 / 切换）
 *
 * 在 GLB 导出的原生相机中按名字查找并激活为渲染相机。
 * 只做"查找 + 挂载到渲染器"，不改动相机投影参数。
 */
import * as THREE from 'three';
import type { LoadedGlb } from './GlbLoader';

export class CameraController {
  private cameras: THREE.Camera[] = [];
  private active: THREE.Camera | null = null;

  bind(glb: LoadedGlb, activeName?: string) {
    this.cameras = glb.cameras;
    const target =
      this.cameras.find((c) => c.name === activeName) ?? this.cameras[0] ?? null;
    this.active = target;
  }

  getActive(): THREE.Camera | null {
    return this.active;
  }

  /** 切换相机（按名字） */
  switchTo(name: string): boolean {
    const next = this.cameras.find((c) => c.name === name);
    if (next) {
      this.active = next;
      return true;
    }
    return false;
  }

  getCameraNames(): string[] {
    return this.cameras.map((c) => c.name);
  }
}
