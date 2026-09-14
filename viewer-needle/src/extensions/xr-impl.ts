/**
 * XR 实现占位（阶段六）
 * 接入 Needle Engine 内置 WebXR 后替换本文件实现。
 */
import type { XrModule } from './xr-stub';

export function createXrModule(): XrModule {
  return {
    name: 'xr',
    async requestSession() {},
    async endSession() {},
    isPresenting: false,
  };
}
