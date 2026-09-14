/**
 * Multiplayer 实现占位（阶段五）
 * 接入 Needle Engine 内置多人同步 / VoIP 后替换本文件实现。
 */
import type { MultiplayerModule, SyncedRoom, SyncedTransform, SyncedCamera, SyncField, VoiceOverIp } from './multiplayer-stub';

function makeRoom(): SyncedRoom {
  return { roomId: '', async connect() {}, async disconnect() {} };
}
function makeTransform(): SyncedTransform {
  return { entityId: '', sync() {} };
}
function makeCamera(): SyncedCamera {
  return { entityId: '', sync() {} };
}
function makeField(): SyncField {
  return { key: '' };
}
function makeVoip(): VoiceOverIp {
  return { async join() {}, async leave() {}, muted: true };
}

export function createMultiplayerModule(): MultiplayerModule {
  return {
    name: 'multiplayer',
    createRoom: makeRoom,
    createSyncedTransform: makeTransform,
    createSyncedCamera: makeCamera,
    createSyncField: makeField,
    createVoip: makeVoip,
  };
}
