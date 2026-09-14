/**
 * 阶段五：Multiplayer 扩展占位
 *
 * 约束：
 *  - 仅当 page.json 标记 enable_multiplayer:true 时动态 import
 *  - 单机漫画主路径完全不受影响；本模块只定义未来接口
 */

export interface SyncedRoom {
  readonly roomId: string;
  connect(url: string): Promise<void>;
  disconnect(): Promise<void>;
}

export interface SyncedTransform {
  readonly entityId: string;
  sync(): void;
}

export interface SyncedCamera {
  readonly entityId: string;
  sync(viewMatrix: Float32Array): void;
}

/** 标记某个字段/属性参与网络同步 */
export interface SyncField {
  readonly key: string;
  readonly lerp?: number;
}

export interface VoiceOverIp {
  join(channel: string): Promise<void>;
  leave(): Promise<void>;
  readonly muted: boolean;
}

export interface MultiplayerModule {
  readonly name: 'multiplayer';
  createRoom(): SyncedRoom;
  createSyncedTransform(): SyncedTransform;
  createSyncedCamera(): SyncedCamera;
  createSyncField(): SyncField;
  createVoip(): VoiceOverIp;
}

export async function loadMultiplayer(enabled: boolean): Promise<MultiplayerModule | null> {
  if (!enabled) return null;
  // TODO: 接入 Needle Engine 内置多人同步 / VoIP 组件
  const mod = await import(/* webpackChunkName: "multiplayer" */ './multiplayer-impl');
  return mod.createMultiplayerModule();
}
