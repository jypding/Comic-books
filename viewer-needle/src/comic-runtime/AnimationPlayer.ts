/**
 * 动画播放器（迁移自旧 app.js 的 Animation playback / timing）
 *
 * 使用 GLB 原生 AnimationMixer 驱动相机动画。
 * 绝不修改相机 projectionMatrix / aspect —— 动画仅作用于节点的
 * position / quaternion / scale 属性，FOV 与宽高比保持 Blender 导出值。
 */
import * as THREE from 'three';
import type { LoadedGlb } from './GlbLoader';

export class AnimationPlayer {
  private mixer: THREE.AnimationMixer | null = null;
  private actions: THREE.AnimationAction[] = [];
  private clock = new THREE.Clock();
  private playing = false;

  /** 绑定 GLB，为其创建原生混合器 */
  bind(glb: LoadedGlb) {
    this.dispose();
    this.mixer = new THREE.AnimationMixer(glb.scene);
    this.actions = glb.animations.map((clip) => this.mixer!.clipAction(clip));
  }

  /** 按轨道名播放指定动画 */
  playTrack(name?: string) {
    if (!this.mixer) return;
    this.stopAll();
    const target = name
      ? this.actions.find((a) => a.getClip().name === name)
      : this.actions[0];
    if (target) {
      target.reset().play();
      this.playing = true;
    }
  }

  toggle() {
    this.playing = !this.playing;
    if (this.playing) this.playTrack();
    else this.stopAll();
    return this.playing;
  }

  stopAll() {
    this.playing = false;
    this.actions.forEach((a) => a.stop());
  }

  /** 每帧更新（渲染循环内调用） */
  update() {
    if (this.mixer && this.playing) {
      this.mixer.update(this.clock.getDelta());
    }
  }

  dispose() {
    this.actions.forEach((a) => a.stop());
    this.mixer?.stopAllAction();
    this.mixer = null;
    this.actions = [];
  }
}
