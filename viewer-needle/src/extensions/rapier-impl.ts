/**
 * Rapier 物理实现占位（阶段三）
 * 接入 @needle-tools/engine 内置 Rapier 后替换本文件实现。
 */
import type { RapierModule } from './rapier-stub';

export function createRapierModule(): RapierModule {
  return {
    name: 'rapier',
    async enable() {},
    disable() {},
    addRigidbody() { return {}; },
    addCollider() {},
    raycast() { return null; },
    createCharacterController() {
      return { move() {}, isGrounded() { return false; } };
    },
  };
}
