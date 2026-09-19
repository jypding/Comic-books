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
  const manifestRes = await fetch('./manifest.json');
  manifest = await manifestRes.json();

  layoutController = new ReaderLayoutController();
  layoutController.setRatios(params.layoutRatios);
  layoutController.onResizeCallback = onWindowResize;

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

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xF3EDDF);

  camera = new THREE.PerspectiveCamera(
    params.camera.fov,
    container.clientWidth / container.clientHeight,
    params.camera.near,
    params.camera.far
  );
  camera.position.fromArray(params.camera.position);

  controls = new OrbitControls(camera, renderer.domElement);
  applyControlsConfig(params.controls);
  controls.target.fromArray(params.camera.target);
  controls.update();

  buildPageNav();
  loadGLB();
  goToPage(0);
  renderer.setAnimationLoop(animate);
}

function buildPageNav() {
  const pageNav = document.getElementById('page-nav');
  manifest.pages.forEach((page, index) => {
    const btn = document.createElement('button');
    btn.className = 'page-btn';
    btn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
        <path d="M6 2h9l5 5v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/>
      </svg>
      Page ${page.pageId.replace('p0', '')}
    `;
    btn.onclick = () => goToPage(index);
    pageNav.appendChild(btn);
  });
}

function updateNavActive(index) {
  const btns = document.querySelectorAll('#page-nav button');
  btns.forEach((btn, i) => {
    if (i === index) btn.classList.add('active');
    else btn.classList.remove('active');
  });
}

function goToPage(index) {
  if (index < 0 || index >= manifest.pages.length) return;
  currentPageIndex = index;
  updateNavActive(index);

  const page = manifest.pages[index];
  layoutController.applyPageManifest(page);

  const titleEl = document.getElementById('text-title');
  const sectionEl = document.getElementById('text-section');
  const bodyEl = document.getElementById('text-body');
  const pageNumEl = document.getElementById('text-page-number');
  if (titleEl) titleEl.textContent = page.title || '';
  if (sectionEl) sectionEl.textContent = (page.labels && page.labels.section) || 'THE CASE';
  if (bodyEl) bodyEl.textContent = page.longText || page.body || '';
  if (pageNumEl) pageNumEl.textContent = index + 1;

  if (page.cameraOverride) {
    if (page.cameraOverride.position) camera.position.fromArray(page.cameraOverride.position);
    if (page.cameraOverride.target) controls.target.fromArray(page.cameraOverride.target);
    controls.update();
  } else if (page.cameraTargetOverride) {
    controls.target.fromArray(page.cameraTargetOverride);
    controls.update();
  }
  if (page.orbitControls) applyControlsConfig(page.orbitControls);
}

function applyControlsConfig(config) {
  controls.enabled = config.enable !== false;
  controls.enableDamping = config.enableDamping !== false;
  controls.dampingFactor = config.dampingFactor || 0.05;
  controls.minDistance = config.minDistance || 0;
  controls.maxDistance = config.maxDistance || Infinity;
}

function loadGLB() {
  const ambient = new THREE.AmbientLight(0xffffff, 1.2);
  scene.add(ambient);

  const dirLight = new THREE.DirectionalLight(0xffffff, 2.0);
  dirLight.position.set(8, 12, 6);
  dirLight.castShadow = true;
  scene.add(dirLight);

  const fillLight = new THREE.DirectionalLight(0xffffff, 0.6);
  fillLight.position.set(-8, 6, -6);
  scene.add(fillLight);

  const draco = new DRACOLoader();
  draco.setDecoderPath('https://www.gstatic.com/draco/versioned/decoders/1.5.6/');
  const loader = new GLTFLoader();
  loader.setDRACOLoader(draco);

  loader.load(
    './web_layout_base.glb',
    (gltf) => {
      console.log('[GLB SUCCESS] loaded scene', gltf.scene);

      gltf.scene.traverse((child) => {
        if (child.isMesh) {
          child.castShadow = true;
          child.receiveShadow = true;

          let needFix = false;
          if (!child.material) {
            needFix = true;
          } else {
            const mats = Array.isArray(child.material) ? child.material : [child.material];
            mats.forEach((m) => {
              if (!m.color || m.color.getHex() === 0x000000) needFix = true;
            });
          }
          if (needFix) {
            child.material = new THREE.MeshStandardMaterial({
              color: 0xD8D2C4,
              roughness: 0.85,
              metalness: 0.0,
            });
          } else {
            const mats = Array.isArray(child.material) ? child.material : [child.material];
            mats.forEach((m) => {
              m.needsUpdate = true;
              if (m.roughness === undefined) m.roughness = 0.85;
            });
          }
        }
      });

      const box = new THREE.Box3().setFromObject(gltf.scene);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z, 1);
      console.log('[GLB] size:', size.toArray(), 'center:', center.toArray());

      camera.near = 0.01;
      camera.far = maxDim * 20;
      camera.position.set(
        center.x,
        center.y + maxDim * 0.3,
        center.z + maxDim * 1.2
      );
      camera.lookAt(center);
      camera.updateProjectionMatrix();
      if (controls) {
        controls.target.copy(center);
        controls.update();
      }

      // 播放 GLB 内嵌关键帧动画
      if (gltf.animations && gltf.animations.length > 0) {
        mixer = new THREE.AnimationMixer(gltf.scene);
        gltf.animations.forEach((clip) => mixer.clipAction(clip).play());
        console.log('[GLB] animations:', gltf.animations.length);
      }

      scene.add(gltf.scene);
      console.log('[GLB] ✅模型已加入场景');
    },
    (progress) => {
      if (progress.total) {
        const percent = Math.round((progress.loaded / progress.total) * 100);
        console.log(`[GLB] 加载进度 ${percent}%`);
      }
    },
    (err) => {
      console.error('[GLB LOAD FAILED]', err);
      const geo = new THREE.SphereGeometry(2, 16, 16);
      const mat = new THREE.MeshStandardMaterial({ color: 0xff4444, wireframe: true });
      scene.add(new THREE.Mesh(geo, mat));
    }
  );
}

function onWindowResize(width, height) {
  if (!camera || !renderer) return;
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
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

  scene.traverse((o) => {
    if (o.isMesh && o.visible) {
      const b = new THREE.Box3().setFromObject(o);
      const s = b.getSize(new THREE.Vector3());
      if (Math.max(s.x, s.y, s.z) > 20) return;
      o.rotation.y += deltaTime * 0.15;
    }
  });

  if (mixer) mixer.update(deltaTime);
  if (controls && controls.enableDamping) controls.update();
  renderer.render(scene, camera);
  updateHUD();
}

// 主题切换
(function () {
  const themes = ['theme-light', 'theme-dark', 'theme-paper', 'theme-black'];
  const labels = ['Light', 'Green', 'Paper', 'Black'];
  let idx = 0;
  document.addEventListener('click', function (e) {
    const btn = e.target.closest('#btn-theme, .btn-theme');
    if (!btn) return;
    idx = (idx + 1) % themes.length;
    document.body.classList.remove('theme-light', 'theme-dark', 'theme-paper', 'theme-black');
    document.body.classList.add(themes[idx]);
    btn.textContent = labels[idx];
    console.log('[THEME]', themes[idx]);
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