import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { ReaderLayoutController } from './readerLayoutController.js';

let scene, camera, renderer, controls;
let layoutController;
let params, manifest;
let currentPageIndex = 0;

let cubeMesh, sphereMesh, torusKnotMesh;
let mixer;
const clock = new THREE.Clock();

const fpsPanel = document.getElementById('fps-panel');
const cameraPanel = document.getElementById('camera-panel');

let lastTime = performance.now();
let frames = 0;

async function init() {
  // 1. Fetch configs
  const paramsRes = await fetch('./params.json');
  params = await paramsRes.json();

  const manifestRes = await fetch('./manifest.json');
  manifest = await manifestRes.json();

  // 2. Setup Layout Controller
  layoutController = new ReaderLayoutController();
  layoutController.setRatios(params.layoutRatios);
  layoutController.onResizeCallback = onWindowResize;

  // 3. Setup Three.js
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
  scene.background = new THREE.Color(0xf0ebe0);

  // Fallback camera
  camera = new THREE.PerspectiveCamera(
    params.camera.fov,
    container.clientWidth / container.clientHeight,
    params.camera.near,
    params.camera.far
  );
  camera.position.fromArray(params.camera.position);

  // Controls
  controls = new OrbitControls(camera, renderer.domElement);
  applyControlsConfig(params.controls);
  controls.target.fromArray(params.camera.target);
  controls.update();

  // 4. Build UI Navigation
  buildPageNav();

  // 5. Load GLB
  loadGLB();

  // 6. Apply initial page
  goToPage(0);

  // 7. Start Render Loop
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
  
  // Apply layout and text
  layoutController.applyPageManifest(page);

  // 缁戝畾鏂扮殑 UI 鍏冪礌
  const titleEl = document.getElementById('text-title');
  const sectionEl = document.getElementById('text-section');
  const bodyEl = document.getElementById('text-body');
  const pageNumEl = document.getElementById('text-page-number');

  if (titleEl) titleEl.textContent = page.title || '';
  if (sectionEl) sectionEl.textContent = (page.labels && page.labels.section) || 'THE CASE';
  if (bodyEl) bodyEl.textContent = page.longText || page.body || '';
  if (pageNumEl) pageNumEl.textContent = index + 1;

  // Apply Camera Override
  if (page.cameraOverride) {
    if (page.cameraOverride.position) {
      camera.position.fromArray(page.cameraOverride.position);
    }
    if (page.cameraOverride.target) {
      controls.target.fromArray(page.cameraOverride.target);
    }
    controls.update();
  } else if (page.cameraTargetOverride) {
    controls.target.fromArray(page.cameraTargetOverride);
    controls.update();
  }

  // Apply OrbitControls Override
  if (page.orbitControls) {
    applyControlsConfig(page.orbitControls);
  }
}

function applyControlsConfig(config) {
  controls.enabled = config.enable !== false;
  controls.enableDamping = config.enableDamping !== false;
  controls.dampingFactor = config.dampingFactor || 0.05;
  controls.minDistance = config.minDistance || 0;
  controls.maxDistance = config.maxDistance || Infinity;
}

function loadGLB() {
  const loader = new GLTFLoader();
  loader.load('./web_layout_base.glb', (gltf) => {
    
    // We can extract camera from GLB if present
    // const gltfCamera = gltf.cameras && gltf.cameras[0];
    // if (gltfCamera) {
    //   // Just copy position, fov, etc. Avoid quaternion lock with OrbitControls
    //   camera.position.copy(gltfCamera.position);
    //   camera.fov = gltfCamera.fov;
    //   camera.near = gltfCamera.near;
    //   camera.far = gltfCamera.far;
    //   camera.updateProjectionMatrix();
    // } else {
    //   camera.position.set(0, 2, 15);
    //   controls.target.set(0, 1, 0);
    //   controls.update();
    // }

    const box = new THREE.Box3().setFromObject(gltf.scene);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z, 1);

    console.log('[SCENE] center:', center.toArray(), 'size:', size.toArray(), 'maxDim:', maxDim);

    camera.near = 0.01;
    camera.far = maxDim * 20;
    camera.position.set(center.x, center.y + maxDim * 0.1, center.z + maxDim * 0.6);
    camera.lookAt(center);
    camera.updateProjectionMatrix();

    if (controls) {
      controls.target.copy(center);
      controls.update();
    }

    // Keep the materials loaded from GLB, do not override with defaultMat/groundMat
    gltf.scene.traverse((child) => {
      if (child.isMesh) {
        child.castShadow = true;
        child.receiveShadow = true;
        
        if (child.name.includes('Cube')) cubeMesh = child;
        if (child.name.includes('Sphere')) sphereMesh = child;
        if (child.name.includes('Torus')) torusKnotMesh = child;
        
        if (child.name.includes('Ground') || child.name.includes('Plane')) {
          child.receiveShadow = true;
          child.castShadow = false;
        } else {
          child.castShadow = true;
          child.receiveShadow = true;
          // Add Edges for Outline Effect
          if (params.rendering.outlineEnabled) {
            const edges = new THREE.EdgesGeometry(child.geometry);
            const line = new THREE.LineSegments(
              edges, 
              new THREE.LineBasicMaterial({ color: params.rendering.outlineColor })
            );
            child.add(line);
          }
        }

        // Tweak material parameters
        if (child.material) {
          child.material.roughness = 0.8;
          child.material.wireframe = false;
          child.material.flatShading = false;
          child.material.needsUpdate = true;
        }
      }
      
      // Map GLB Lights
      if (child.isLight) {
        child.castShadow = params.rendering.shadowEnabled;
        if (child.isDirectionalLight) {
          child.shadow.mapSize.width = 1024;
          child.shadow.mapSize.height = 1024;
          child.shadow.camera.near = 0.5;
          child.shadow.camera.far = 50;
        }
      }
    });

    if (gltf.animations && gltf.animations.length > 0) {
      mixer = new THREE.AnimationMixer(gltf.scene);
      gltf.animations.forEach((clip) => {
        mixer.clipAction(clip).play();
      });
    }

    // === 自动修复 ===
    // 1. 隐藏过大的 Background_Paper
    gltf.scene.traverse((o) => {
      if (o.isMesh) {
        const b = new THREE.Box3().setFromObject(o);
        const s = b.getSize(new THREE.Vector3());
        const c = b.getCenter(new THREE.Vector3());
        console.log('[MESH]', o.name, '| size:', s.toArray().map(v=>v.toFixed(2)).join(','), '| center:', c.toArray().map(v=>v.toFixed(2)).join(','));
        // 隐藏所有超过 10 单位的大平面
        if (s.x > 10 || s.y > 10 || s.z > 10) {
          o.visible = false;
          console.log('[MESH] HIDDEN huge plane:', o.name);
        }
      }
    });

    // 2. 固定相机能看到场景
    camera.position.set(0, 3, 15);
    camera.near = 0.1;
    camera.far = 500;
    camera.updateProjectionMatrix();
    camera.lookAt(0, 1, 0);
    if (controls) {
      controls.target.set(0, 1, 0);
      controls.update();
    }

    // 3. 米黄清屏色
    renderer.setClearColor(0xF3EDDF, 1);

    scene.add(gltf.scene);
  });
}

function onWindowResize(width, height) {
  if (!camera || !renderer) return;
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
}

function updateHUD() {
  // FPS
  const now = performance.now();
  frames++;
  if (now > lastTime + 1000) {
    const fps = Math.round((frames * 1000) / (now - lastTime));
    fpsPanel.textContent = `FPS: ${fps}`;
    frames = 0;
    lastTime = now;
  }

  // Camera Params
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

  scene.traverse(function(obj) {
    if (obj.isMesh && obj.visible) {
      const box = new THREE.Box3().setFromObject(obj);
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z);
      if (maxDim > 20) return;
      obj.rotation.y += deltaTime * 0.4;
      obj.rotation.x += deltaTime * 0.15;
    }
  });

  if (mixer) {
    mixer.update(deltaTime);
  }

  if (controls && controls.enableDamping) {
    controls.update();
  }

  renderer.render(scene, camera);

  if (cameraPanel) {
    const pos = camera.position;
    const tgt = controls.target;
    const dist = pos.distanceTo(tgt);
    cameraPanel.innerHTML =
      '<div>Pos: ' + pos.x.toFixed(2) + ', ' + pos.y.toFixed(2) + ', ' + pos.z.toFixed(2) + '</div>' +
      '<div>Target: ' + tgt.x.toFixed(2) + ', ' + tgt.y.toFixed(2) + ', ' + tgt.z.toFixed(2) + '</div>' +
      '<div>Dist: ' + dist.toFixed(2) + '</div>';
  }
}

// Bootstrap
init();
// === 主题切换（唯一版本） ===
(function() {
  const themes = ['theme-light', 'theme-dark', 'theme-paper'];
  const labels = ['Theme', 'Dark', 'Paper'];
  let idx = 0;
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn-theme');
    if (!btn) return;
    idx = (idx + 1) % themes.length;
    document.body.classList.remove('theme-light', 'theme-dark', 'theme-paper');
    document.body.classList.add(themes[idx]);
    btn.textContent = labels[idx];
    console.log('[THEME]', themes[idx]);
  });
})();

// === THEME ===
(function() {
  const themes = ['theme-light', 'theme-dark', 'theme-paper', 'theme-black'];
  const labels = ['Light', 'Green', 'Paper', 'Black'];
  let idx = 0;
  document.addEventListener('click', function(e) {
    const btn = e.target.closest('#btn-theme');
    if (!btn) return;
    idx = (idx + 1) % themes.length;
    document.body.classList.remove('theme-light', 'theme-dark', 'theme-paper', 'theme-black');
    document.body.classList.add(themes[idx]);
    btn.textContent = labels[idx];
    console.log('[THEME]', themes[idx]);
  });
})();
