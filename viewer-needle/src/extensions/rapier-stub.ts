/**
 * 阶段三：Rapier 物理扩展占位（Needle Engine 内置 Rapier）
 *
 * 约束：
 *  - 仅当 page.json 标记 enable_physics:true 时才动态 import 本模块
 *  - 物理独立 update 循环，绝不干预 GLB AnimationMixer 相机动画
 *  - 现阶段只实现类型/外壳，不做完整物理逻辑
 */

export interface Rigidbody {
  bodyType: 'static' | 'dynamic' | 'kinematic';
  mass: number;
}

export interface Collider {
  kind: 'cuboid' | 'ball' | 'capsule' | 'trimesh';
  offset: [number, number, number];
  size: [number, number, number];
}

export interface RaycastHit {
  entity: unknown;
  point: [number, number, number];
  distance: number;
}

export interface CharacterController {
  move(delta: [number, number, number]): void;
  isGrounded(): boolean;
}

export interface RapierModule {
  readonly name: 'rapier';
  enable(): Promise<void>;
  disable(): void;
  addRigidbody(rb: Rigidbody): unknown;
  addCollider(c: Collider): void;
  raycast(origin: [number, number, number], dir: [number, number, number], maxDist: number): RaycastHit | null;
  createCharacterController(): CharacterController;
}

/**
 * 动态加载物理模块。传入页面配置，只有 enable_physics 为 true 时才真正 import 引擎。
 * @returns 未开启时返回 null，不加载任何 WASM。
 */
export async function loadPhysics(enabled: boolean): Promise<RapierModule | null> {
  if (!enabled) return null;
  // TODO: 接入 @needle-tools/engine 内置 Rapier 绑定
  const mod = await import(/* webpackChunkName: "rapier" */ './rapier-impl');
  return mod.createRapierModule();
}
