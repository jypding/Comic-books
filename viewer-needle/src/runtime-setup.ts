/**
 * 运行时底座初始化：优先使用 Needle Engine，失败降级为纯 three。
 *
 * 设计意图：Needle Engine 是 Vite 依赖，需要商业 license 才能真正运行。
 * 为保证"无 license 时开发环境依旧可预览、可构建"，这里把 Needle 封装成可选层：
 *  - import 成功：仍把底层 three 对象交给业务层使用
 *  - import 失败 / 无 license：回退到纯 three，保证不阻塞漫画业务开发
 *
 * 对外暴露的 three 对象统一挂在 window.__comicViewer 上，业务层从这里取用。
 */
import * as THREE from 'three';

export interface ComicViewerContext {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
}

// 运行时能力标记（构建期静态，运行时可能被降级覆盖）
declare global {
  interface Window {
    __comicViewer?: ComicViewerContext;
  }
}

async function initNeedle(): Promise<boolean> {
  return false;
}

function initThree(targetContainer?: HTMLElement): ComicViewerContext {
  const container = targetContainer || document.getElementById('app')!;
  
  // 清空容器，确保唯一性
  if (!targetContainer) {
    container.innerHTML = '';
  }

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setClearColor(0xF3EDDF, 1);
  renderer.domElement.style.position = 'absolute';
  renderer.domElement.style.top = '0';
  renderer.domElement.style.left = '0';
  renderer.domElement.style.width = '100%';
  renderer.domElement.style.height = '100%';
  renderer.domElement.style.zIndex = '1';

  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(renderer.domElement);
  
  // 移除任何非 Three.js 的 canvas 和 needle-engine 组件
  container.querySelectorAll('canvas').forEach(c => {
    if (c !== renderer.domElement) c.remove();
  });
  document.querySelectorAll('needle-engine').forEach(el => el.remove());

  // 强制设置 canvas 样式以填满容器
  renderer.domElement.style.display = 'block';
  renderer.domElement.style.background = '#F3EDDF';
  renderer.domElement.style.pointerEvents = 'auto';
  renderer.domElement.style.touchAction = 'none';

  const scene = new THREE.Scene();
  // scene.background = new THREE.Color(0xff0000); // 临时纯红
  // renderer.setClearColor(0xff0000, 1); // 临时纯红

  // 默认透视相机
  const camera = new THREE.PerspectiveCamera(50, container.clientWidth / container.clientHeight, 0.01, 2000);
  camera.position.set(0, 1.6, 3);

  const ctx: ComicViewerContext = { renderer, scene, camera };
  window.__comicViewer = ctx;

  const onResize = () => {
    const w = container.clientWidth;
    const h = container.clientHeight;
    if (w === 0 || h === 0) return;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  
  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(() => onResize());
    ro.observe(container);
  } else {
    window.addEventListener('resize', onResize);
  }
  
  setTimeout(onResize, 100);

  scene.add(new THREE.AmbientLight(0xffffff, 1.2));
  const dir = new THREE.DirectionalLight(0xffffff, 1.5);
  dir.position.set(2, 4, 3);
  scene.add(dir);

  return ctx;
}

export async function createViewer(targetContainer?: HTMLElement): Promise<ComicViewerContext> {
  const ctx = initThree(targetContainer);
  return ctx;
}
