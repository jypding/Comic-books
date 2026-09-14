/**
 * 阶段六：XR 扩展占位（WebXR / AR / VR）
 *
 * 约束：
 *  - 仅当 page.json 标记 enable_xr:true 时动态 import
 *  - 不修改现有 Desktop 相机系统；XR 走独立的沉浸会话入口
 */

export interface XrModule {
  readonly name: 'xr';
  requestSession(mode: 'AR' | 'VR'): Promise<void>;
  endSession(): Promise<void>;
  readonly isPresenting: boolean;
}

export async function loadXr(enabled: boolean): Promise<XrModule | null> {
  if (!enabled) return null;
  // TODO: 接入 Needle Engine 内置 WebXR 组件
  const mod = await import(/* webpackChunkName: "xr" */ './xr-impl');
  return mod.createXrModule();
}
