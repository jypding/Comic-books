import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { ReaderLayoutController } from './readerLayoutController.js';

let scene, camera, renderer, controls;
let layoutController;
let params, manifest;
let currentPageIndex = 0;
let mixer;
const clock = new THREE.Clock();
const fpsPanel = document.getElementById('fps-panel');
const cameraPanel = document.getElementById('camera-panel');
let lastTime = performance.now();
let frames = 0;

async function init() {
  const paramsRes = await fetch('./params.json');
  params = await paramsRes.json();
  const manifestRes = await fetch('./manifest.json?t=' + Date.now(), { cache: 'no-store' });
  manifest = await manifestRes.json();

  layoutController = new ReaderLayoutController();
  layoutController.setRatios(params.layoutRatios);
  layoutController.onResizeCallback = onWindowResize;

  // 暴露给 editMode.js
  window.__layoutController = layoutController;
  window.__currentPageId = () => {
    const page = manifest.pages[currentPageIndex];
    return (page && (page.pageId || page.page_id)) || ('p' + String(currentPageIndex).padStart(4, '0'));
  };
  // boot 数据通知器通过此函数解析当前页（优先使用与 voicebook JSON 同名的 scene_name）
  window.getCurrentPageId = () => {
    const page = manifest.pages[currentPageIndex];
    if (!page) return '';
    return page.scene_name || page.pageId || page.page_id || '';
  };

  const container = document.getElementById('canvas-container');
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setClearColor(0xF3EDDF, 1);

  if (params.rendering.shadowEnabled) {
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  }

  container.appendChild(renderer.domElement);
  window.threeRenderer = renderer;

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xF3EDDF);

  // 正交相机：1:1 还原 Blender VoiceBook 排版（无透视畸变）
  camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 500);
  camera.position.fromArray(params.camera.position);
  window.threeCamera = camera;
  frameOrthoScene();

  controls = new OrbitControls(camera, renderer.domElement);
  applyControlsConfig(params.controls);
  controls.target.fromArray(params.camera.target);
  controls.update();

  buildPageNav();
  bindNavButtons();
  goToPage(0);
  renderer.setAnimationLoop(animate);

  // ===== 动态加载编辑模式（保证 controller 已就绪）=====
  const urlParams = new URLSearchParams(location.search);
  const pageParam = urlParams.get('page');
  const editParam = urlParams.get('edit');

  if (pageParam) {
    const idx = manifest.pages.findIndex(p =>
      (p.pageId || p.page_id) === pageParam ||
      (p.scene_name || '').replace('.w1h1', '') === pageParam
    );
    if (idx >= 0) goToPage(idx);
  }

  if (editParam === '1') {
    import('./editMode.js').then(() => {
      if (window.LayoutEditMode && typeof window.LayoutEditMode.enable === 'function') {
        window.LayoutEditMode.enable();
        console.log('[EditMode] 已启用');
      }
    }).catch(err => {
      console.error('[EditMode] 加载失败:', err);
    });
  }
}

function buildPageNav() {
  const pageNav = document.getElementById('page-nav');
  pageNav.innerHTML = '';
  const span = document.createElement('span');
  span.id = 'page-current-display';
  span.className = 'page-current';
  span.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M6 2h9l5 5v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/></svg> <span class="page-current-id">p.0000</span>';
  pageNav.appendChild(span);
}

function updatePageCurrent(index) {
  const el = document.querySelector('#page-current-display .page-current-id');
  if (!el) return;
  const page = manifest.pages[index];
  const id = (page && (page.pageId || page.page_id)) || ('p' + String(index).padStart(4, '0'));
  el.textContent = id;
}

function updateNavActive(index) {
  updatePageCurrent(index);
}

// 视频页：manifest 该页带 video 字段时，场景区叠加 <video> 播放 mp4
//（glTF 不支持视频纹理，GLB 里对应的 sora2* 白板由 loadPageGLB 隐藏）
function applyPageVideo(page) {
  const v = document.getElementById('page-video');
  if (!v) return;
  const url = page && page.video;
  if (url) {
    const abs = new URL(url, location.href).href;
    if (v.src !== abs) v.src = url;
    v.style.display = 'block';
    window.__pageVideoActive = true;
    v.play().catch(() => {});
  } else {
    window.__pageVideoActive = false;
    v.pause();
    v.style.display = 'none';
    v.removeAttribute('src');
    v.load();
  }
}

async function goToPage(index) {
  if (index < 0 || index >= manifest.pages.length) return;
  currentPageIndex = index;
  updateNavActive(index);
  updateNavButtons();

  const page = manifest.pages[index];
  layoutController.applyPageManifest(page);
  applyPageVideo(page);

  const titleEl = document.getElementById('text-title');
  const sectionEl = document.getElementById('text-section');
  const bodyEl = document.getElementById('text-body');
  const pageNumEl = document.getElementById('text-page-number');
  if (titleEl) titleEl.textContent = page.title || '';
  if (sectionEl) sectionEl.textContent = (page.labels && page.labels.section) || 'THE CASE';
  if (bodyEl) bodyEl.textContent = page.longText || page.body || '';
  if (pageNumEl) pageNumEl.textContent = index + 1;

  // 翻页后文字栏回到顶部，保证 Contents/‹/› 导航行可见
  const textPanelEl = document.getElementById('text-panel');
  if (textPanelEl) textPanelEl.scrollTop = 0;

  if (page.cameraOverride) {
    if (page.cameraOverride.position) camera.position.fromArray(page.cameraOverride.position);
    if (page.cameraOverride.target) controls.target.fromArray(page.cameraOverride.target);
    controls.update();
  } else if (page.cameraTargetOverride) {
    controls.target.fromArray(page.cameraTargetOverride);
    controls.update();
  }
  if (page.orbitControls) applyControlsConfig(page.orbitControls);

  // 加载当前页的 VoiceBook V1 JSON（Blender 导出的唯一布局真值）
  const v1 = await fetchVoiceBook(page);
  if (v1) {
    currentV1 = v1;
    applyV1Data(v1);
  } else {
    currentV1 = null;
    resetFallbackView(page);
  }

  // 加载当前页 GLB
  loadPageGLB(page.glb || './web_layout_base.glb');

  // 通知 guide 监听器按当前页 V1 文件重新对齐（翻页后其内部 pageId 已过期）
  if (typeof window.__reloadGuideLayout === 'function') {
    window.__reloadGuideLayout();
  }

  // 翻页时重置音频与进度
  resetAudioForPage(page);
}

function applyControlsConfig(config) {
  controls.enabled = config.enable !== false;
  controls.enableDamping = config.enableDamping !== false;
  controls.dampingFactor = config.dampingFactor || 0.05;
  controls.minDistance = config.minDistance || 0;
  controls.maxDistance = config.maxDistance || Infinity;
}

let currentGLBScene = null;
let lightsInitialized = false;
let glbLoadSeq = 0; // GLB 请求序号：快速翻页时丢弃过期回调

function ensureLights() {
  if (lightsInitialized) return;
  const ambient = new THREE.AmbientLight(0xffffff, 1.2);
  scene.add(ambient);
  const dirLight = new THREE.DirectionalLight(0xffffff, 2.0);
  dirLight.position.set(8, 12, 6);
  dirLight.castShadow = true;
  scene.add(dirLight);
  const fillLight = new THREE.DirectionalLight(0xffffff, 0.6);
  fillLight.position.set(-8, 6, -6);
  scene.add(fillLight);
  lightsInitialized = true;
}

function disposeCurrentGLB() {
  if (currentGLBScene) {
    scene.remove(currentGLBScene);
    currentGLBScene.traverse((child) => {
      if (child.geometry) child.geometry.dispose();
      if (child.material) {
        const mats = Array.isArray(child.material) ? child.material : [child.material];
        mats.forEach(m => m.dispose && m.dispose());
      }
    });
    currentGLBScene = null;
  }
  if (mixer) {
    mixer.stopAllAction();
    mixer = null;
  }
}

function loadPageGLB(glbPath) {
  ensureLights();
  disposeCurrentGLB();
  const seq = ++glbLoadSeq;
  if (!glbPath) return;
  const draco = new DRACOLoader();
  draco.setDecoderPath('https://www.gstatic.com/draco/versioned/decoders/1.5.6/');
  const loader = new GLTFLoader();
  loader.setDRACOLoader(draco);
  loader.load(
    glbPath + (glbPath.includes('?') ? '&' : '?') + 't=' + Date.now(), // 防缓存：避免浏览器复用旧 GLB 副本
    (gltf) => {
      // 过期响应：用户已翻到别的页，释放资源但不挂载
      if (seq !== glbLoadSeq) {
        disposeGltfRoot(gltf.scene);
        return;
      }
      gltf.scene.traverse((child) => {
        // 只隐藏纯模板辅助物（Guide/BTN/TXT 模板、相机目标、材质集合）
        // Ground 地面必须保留：场景是空间 3D，地面+阴影是空间感的一部分
        if (child.name && /^(Guide_|BTN_|TXT_|Camera_Target|Materials\.)/.test(child.name)) {
          child.visible = false;
        }
        // 视频页：GLB 里的 sora2 网格纹理已被 glTF 导出丢弃（白板），由 <video> 替代
        if (window.__pageVideoActive && child.name && /^sora2/i.test(child.name)) {
          child.visible = false;
        }
        if (child.isMesh) {
          child.castShadow = true;
          child.receiveShadow = true;
        }
      });
      // 构图盒排除辅助物和 Ground 大地面（48×48 会撑大取景让内容物变得极小），
      // 相机只框内容物体；Ground 保持可见、只是不参与取景
      const GUIDE_RE = /^(Guide_|BTN_|TXT_|Camera_Target|Materials\.|Ground)/;
      // 真实内容尺寸 2~3、地面 48；超出此值的必为被"停在远处"的未用骨架部件
      const SANE_LIMIT = 1000;
      currentSceneBox = new THREE.Box3();
      // 逐网格取景：跳过停在 ±SANE_LIMIT 外的未用部件，防止相机被拖到
      // 十万单位外造成空白。仅作用于取景计算，不隐藏/不过滤任何渲染物体。
      gltf.scene.traverse((child) => {
        if (!child.isMesh) return;
        if (child.name && GUIDE_RE.test(child.name)) return;
        const b = new THREE.Box3().setFromObject(child);
        if (b.isEmpty()) return;
        if (
          Math.abs(b.min.x) > SANE_LIMIT || Math.abs(b.min.y) > SANE_LIMIT ||
          Math.abs(b.min.z) > SANE_LIMIT || Math.abs(b.max.x) > SANE_LIMIT ||
          Math.abs(b.max.y) > SANE_LIMIT || Math.abs(b.max.z) > SANE_LIMIT
        ) return;
        currentSceneBox.union(b);
      });
      if (currentSceneBox.isEmpty()) {
        currentSceneBox = new THREE.Box3().setFromObject(gltf.scene);
      }
      frameOrthoScene();
      if (controls) {
        const c = currentSceneBox.getCenter(new THREE.Vector3());
        controls.target.copy(c);
        controls.update();
      }
      if (gltf.animations && gltf.animations.length > 0) {
        mixer = new THREE.AnimationMixer(gltf.scene);
        gltf.animations.forEach((clip) => mixer.clipAction(clip).play());
      }
      currentGLBScene = gltf.scene;
      scene.add(gltf.scene);
    },
    undefined,
    (err) => {
      if (seq !== glbLoadSeq) return;
      console.error('[GLB LOAD FAILED]', err);
      const geo = new THREE.SphereGeometry(2, 16, 16);
      const mat = new THREE.MeshStandardMaterial({ color: 0xff4444, wireframe: true });
      scene.add(new THREE.Mesh(geo, mat));
    }
  );
}

// 释放未挂载的 gltf 根（过期回调专用）
function disposeGltfRoot(root) {
  root.traverse((child) => {
    if (child.geometry) child.geometry.dispose();
    if (child.material) {
      const mats = Array.isArray(child.material) ? child.material : [child.material];
      mats.forEach((m) => m.dispose && m.dispose());
    }
  });
}

function onWindowResize(width, height) {
  if (!camera || !renderer) return;
  renderer.setSize(width, height);
  frameOrthoScene();
}

function updateHUD() {
  const now = performance.now();
  frames++;
  if (now > lastTime + 1000) {
    const fps = Math.round((frames * 1000) / (now - lastTime));
    fpsPanel.textContent = `FPS: ${fps}`;
    frames = 0;
    lastTime = now;
  }
  if (camera && controls) {
    const pos = camera.position;
    const tgt = controls.target;
    const dist = pos.distanceTo(tgt);
    cameraPanel.innerHTML = `
      <div>Pos: ${pos.x.toFixed(2)}, ${pos.y.toFixed(2)}, ${pos.z.toFixed(2)}</div>
      <div>Target: ${tgt.x.toFixed(2)}, ${tgt.y.toFixed(2)}, ${tgt.z.toFixed(2)}</div>
      <div>Dist: ${dist.toFixed(2)}</div>
    `;
  }
}

function animate() {
  const deltaTime = clock.getDelta();

  // 不做全局自动旋转：Blender 导出的版式是固定排布，旋转会破坏位置对应
  if (mixer) mixer.update(deltaTime);
  if (controls && controls.enableDamping) controls.update();
  renderer.render(scene, camera);
  updateHUD();
}

// 代码版本令牌：voicebook_v1_boot 轮询比对，旧代码标签页自动硬刷新
const BUILD_TOKEN = '20261005-page-video';
window.__VOICEBOOK_BUILD_TOKEN = BUILD_TOKEN;

// 主题切换：Dark 循环 米黄默认 → Green(绿) → Paper(暖纸) → Black(黑)；Sit 复位米黄默认
const THEME_BEIGE_HEX = 0xF3EDDF;
const THEME_DARK_HEX = 0x2C7A66;
const THEME_WARM_HEX = 0xF4ECD8;
const THEME_BLACK_HEX = 0x1A1A1A;
const SKIN_CYCLE = [
  { cls: '',               label: 'Dark',  hex: THEME_BEIGE_HEX },
  { cls: 'theme-dark',     label: 'Green', hex: THEME_DARK_HEX },
  { cls: 'theme-paper',    label: 'Paper', hex: THEME_WARM_HEX },
  { cls: 'theme-black',    label: 'Black', hex: THEME_BLACK_HEX },
];
let skinCycleIndex = 0;

function applySkinCycle(index) {
  skinCycleIndex = ((index % SKIN_CYCLE.length) + SKIN_CYCLE.length) % SKIN_CYCLE.length;
  const cur = SKIN_CYCLE[skinCycleIndex];
  document.body.classList.remove('theme-light', 'theme-dark', 'theme-paper', 'theme-black');
  if (cur.cls) document.body.classList.add(cur.cls);
  const btn = document.getElementById('btn-theme');
  if (btn) btn.textContent = cur.label;
  // 皮肤只作用于页面 CSS，3D 场景背景恒定米黄，皮肤色绝不进入场景
  console.log('[THEME]', cur.cls || 'light');
}

function resetSkin() {
  applySkinCycle(0);
}

(function () {
  document.addEventListener('click', function (e) {
    if (e.target.closest('#btn-theme, .btn-theme')) {
      applySkinCycle(skinCycleIndex + 1);
      return;
    }
    if (e.target.closest('.btn-sit')) resetSkin();
  });
})();

init();

// ===== 音频：绑定到红色圆钮 .btn-play =====
(function setupAudio() {
  const audioEl = document.getElementById('page-audio');
  const playBtn = document.querySelector('.btn-play');

  if (!audioEl || !playBtn) {
    console.warn('音频DOM缺失：page-audio 或 .btn-play');
    return;
  }

  // 红钮：播放 / 暂停
  playBtn.addEventListener('click', async () => {
    try {
      if (audioEl.paused) {
        await audioEl.play();
        playBtn.innerHTML = '⏸';
      } else {
        audioEl.pause();
        playBtn.innerHTML = '▶';
      }
    } catch (err) {
      console.error('[AUDIO] 播放失败:', err);
    }
  });

  audioEl.addEventListener('ended', () => {
    playBtn.innerHTML = '▶';
  });

  // 快退 10 秒
  const rewBtn = document.querySelector('.btn-rew');
  if (rewBtn) {
    rewBtn.addEventListener('click', () => {
      audioEl.currentTime = Math.max(0, audioEl.currentTime - 10);
    });
  }

  // 快进 10 秒
  const ffBtn = document.querySelector('.btn-ff');
  if (ffBtn) {
    ffBtn.addEventListener('click', () => {
      audioEl.currentTime = Math.min(audioEl.duration || 0, audioEl.currentTime + 10);
    });
  }

  // 时间显示
  const timeEl = document.querySelector('.player-time');
  const progressBar = document.querySelector('.player-progress > div, .player-fill');

  audioEl.addEventListener('timeupdate', () => {
    if (timeEl) {
      const fmt = (s) => Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0');
      timeEl.textContent = fmt(audioEl.currentTime) + ' / ' + fmt(audioEl.duration || 0);
    }
    if (progressBar && audioEl.duration > 0) {
      progressBar.style.width = ((audioEl.currentTime / audioEl.duration) * 100) + '%';
    }
  });

  audioEl.addEventListener('loadedmetadata', () => {
    if (timeEl) {
      const fmt = (s) => Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0');
      timeEl.textContent = '0:00 / ' + fmt(audioEl.duration || 0);
    }
  });

  console.log('[AUDIO] 已绑定到红色圆钮 .btn-play');
})();

// =====================================================================
// VoiceBook 数据链路（Blender V1 JSON 单一真值）
// =====================================================================
let currentV1 = null;
let currentSceneBox = null;

function dataSignature(v) {
  return JSON.stringify(v);
}

// 依次尝试 voicebook/<scene_name>.json、<pageId>.json
async function fetchVoiceBook(page) {
  const names = [];
  for (const key of ['scene_name', 'pageId', 'page_id']) {
    const v = page[key];
    if (v && !names.includes(v)) names.push(v);
  }
  for (const name of names) {
    try {
      const res = await fetch(
        './voicebook/' + encodeURIComponent(name) + '.json?t=' + Date.now(),
        { cache: 'no-store' }
      );
      if (!res.ok) continue;
      const data = await res.json();
      if (data && data.canvas && data.layout && data.textBoxes) return data;
    } catch (e) { /* try next */ }
  }
  return null;
}

function normalizeLayoutType(raw) {
  let t = String(raw || 'fullscreen').replace(/_/g, '-');
  if (t === 'full') t = 'fullscreen';
  return t;
}

function setLayoutRatio(name, v) {
  document.body.style.setProperty(name, v.toFixed(3) + '%');
}

function applyV1Data(v1) {
  const cw = (v1.canvas && v1.canvas.width) || 1920;
  const ch = (v1.canvas && v1.canvas.height) || 1080;
  const layout = v1.layout || {};
  const type = normalizeLayoutType(layout.layout || layout.type);
  const ta = layout.textArea || { x: 0, y: 0, w: cw, h: ch };

  // 1. body 版式类名 + 顶部版式按钮高亮
  document.body.classList.remove('layout-left-right', 'layout-top-bottom', 'layout-fullscreen');
  document.body.classList.add('layout-' + type);
  document.querySelectorAll('#layout-nav button').forEach((b) => {
    b.classList.toggle('active', b.getAttribute('data-layout') === type);
  });

  // 2. CSS 分割比例（index.html 中 var() 规则消费）
  if (type === 'left-right') {
    const textW = ((ta.x + ta.w) / cw) * 100;
    setLayoutRatio('--lr-text-w', textW);
    setLayoutRatio('--lr-canvas-w', 100 - textW);
  } else if (type === 'top-bottom') {
    const textH = ((ch - ta.y) / ch) * 100;
    setLayoutRatio('--tb-text-h', textH);
    setLayoutRatio('--tb-canvas-h', 100 - textH);
  }

  // 3. 文字内容（blocks 拼接优先，回退 textBoxes.body）
  let bodyText = '';
  if (Array.isArray(v1.blocks) && v1.blocks.length) {
    bodyText = v1.blocks.map((b) => b.text || '').join('\n');
  } else if (v1.textBoxes && v1.textBoxes.body) {
    bodyText = v1.textBoxes.body.text || '';
  }
  const titleText = (v1.textBoxes && v1.textBoxes.title && v1.textBoxes.title.text) || '';
  const titleEl = document.getElementById('text-title');
  const bodyEl = document.getElementById('text-body');
  if (titleEl) titleEl.textContent = titleText;
  if (bodyEl) bodyEl.textContent = bodyText;
  const seal = document.getElementById('text-page-number');
  if (seal) seal.textContent = currentPageIndex + 1;

  // 4. 皮肤（与 Blender skin_type 一致：Dark=绿色（历史命名 theme-dark），
  //    其余明确值=米黄默认；无 skin_type 字段时保留用户当前选择）
  if (v1.skin_type === 'Dark' || v1.skin_type === 'dark') {
    applySkinCycle(1); // Green
  } else if (v1.skin_type) {
    resetSkin();
  }

  // 5. 版式变化后重新构图
  requestAnimationFrame(() => frameOrthoScene());
}

// 无 V1 JSON 的页面：使用 manifest 字段兜底，保证翻页可用
function resetFallbackView(page) {
  const titleEl = document.getElementById('text-title');
  const bodyEl = document.getElementById('text-body');
  if (titleEl) titleEl.textContent = page.title || '';
  if (bodyEl) bodyEl.textContent = page.longText || page.body || '';
  const seal = document.getElementById('text-page-number');
  if (seal) seal.textContent = currentPageIndex + 1;
}

// 正交构图：场景物体保持 Blender 中的相对位置/比例，contain 拟合到画布容器
function frameOrthoScene() {
  if (!camera) return;
  const container = document.getElementById('canvas-container');
  const w = container.clientWidth || 1;
  const h = container.clientHeight || 1;
  const aspect = w / h;

  const center = new THREE.Vector3(0, 0.5, 0);
  const size = new THREE.Vector3(10, 6, 10);
  if (currentSceneBox && !currentSceneBox.isEmpty()) {
    currentSceneBox.getCenter(center);
    currentSceneBox.getSize(size);
  }

  const FIT_PAD = 1.18; // 四周留白
  const viewH = Math.max(size.y, size.x / aspect) * FIT_PAD;
  const viewW = viewH * aspect;

  camera.left = center.x - viewW / 2;
  camera.right = center.x + viewW / 2;
  camera.top = center.y + viewH / 2;
  camera.bottom = center.y - viewH / 2;
  camera.near = 0.01;
  camera.far = Math.max(
    Math.max(size.x, size.y, size.z) * 20, 100
  );

  // 固定 3/4 正交视角（与 Blender 预览角度一致），不自动旋转
  const dir = new THREE.Vector3(0.35, 0.42, 1).normalize();
  const dist = viewH * 2.2;
  camera.position.set(
    center.x + dir.x * dist,
    center.y + dir.y * dist,
    center.z + dir.z * dist
  );
  camera.lookAt(center);
  camera.updateProjectionMatrix();
}

// 翻页按钮绑定
function bindNavButtons() {
  const contentsBtn = document.querySelector('.btn-contents');
  const prevBtn = document.querySelector('.btn-prev');
  const nextBtn = document.querySelector('.btn-next');
  if (contentsBtn) contentsBtn.addEventListener('click', () => goToPage(0));
  if (prevBtn) prevBtn.addEventListener('click', () => goToPage(currentPageIndex - 1));
  if (nextBtn) nextBtn.addEventListener('click', () => goToPage(currentPageIndex + 1));

  document.addEventListener('keydown', (e) => {
    const tag = (e.target && e.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;
    if (e.key === 'ArrowLeft') goToPage(currentPageIndex - 1);
    if (e.key === 'ArrowRight') goToPage(currentPageIndex + 1);
  });
}

function updateNavButtons() {
  const prevBtn = document.querySelector('.btn-prev');
  const nextBtn = document.querySelector('.btn-next');
  if (prevBtn) prevBtn.disabled = currentPageIndex <= 0;
  if (nextBtn) nextBtn.disabled = currentPageIndex >= manifest.pages.length - 1;
}

// 翻页时重置音频、播放按钮与进度条
function resetAudioForPage() {
  const audioEl = document.getElementById('page-audio');
  if (!audioEl) return;
  audioEl.pause();
  // 仅在确已播放过时回零，避免媒体尚未加载完成时设置 currentTime 触发 ERR_ABORTED
  if (audioEl.currentTime > 0) audioEl.currentTime = 0;
  const playBtn = document.querySelector('.btn-play');
  if (playBtn) {
    playBtn.innerHTML =
      '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
  }
  const bar = document.querySelector('.voice-progress-bar');
  if (bar) bar.style.width = '0%';
  const timeEl = document.querySelector('.player-time');
  if (timeEl) timeEl.textContent = '0:00 / 0:00';
}

// boot 热更新入口：同一页 JSON 在 Blender 端重新导出后自动应用
window.__voicebookV1Notify = function (pageId, v1) {
  const currentId = typeof window.getCurrentPageId === 'function' ? window.getCurrentPageId() : '';
  if (pageId !== currentId) return;
  if (!v1) return;
  if (currentV1 && dataSignature(currentV1) === dataSignature(v1)) return;
  currentV1 = v1;
  applyV1Data(v1);
  console.log('[VoiceBook Sync] 已热更新:', pageId);
};
