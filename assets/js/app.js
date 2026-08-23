
(function() {
    let scene, camera, renderer, loader, controls;
    let pages = [];
    let currentIdx = 0;
    let currentModel = null;

    const container = document.getElementById('canvas-container');
    const loadingOverlay = document.getElementById('loading-overlay');
    const loadingText = document.getElementById('loading-text');
    const errorOverlay = document.getElementById('error-overlay');
    const pageIndicator = document.getElementById('page-indicator');
    const bookTitle = document.getElementById('book-title');

    function init() {
        if (typeof THREE === 'undefined') {
            showError('Three.js 未加载，请检查 assets/js/vendors/three.min.js');
            return;
        }

        scene = new THREE.Scene();
        scene.background = new THREE.Color(0x05070a);

        camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 1000);
        
        renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.setPixelRatio(window.devicePixelRatio);
        // Compatibility for older Three.js versions
        if (renderer.outputColorSpace !== undefined) {
            renderer.outputColorSpace = THREE.SRGBColorSpace;
        } else if (renderer.outputEncoding !== undefined) {
            renderer.outputEncoding = THREE.sRGBEncoding;
        }
        
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        container.appendChild(renderer.domElement);

        // Initialize OrbitControls
        if (typeof THREE.OrbitControls !== 'undefined') {
            controls = new THREE.OrbitControls(camera, renderer.domElement);
            controls.enableDamping = true;
            controls.dampingFactor = 0.05;
            controls.screenSpacePanning = true;
        }

        const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
        scene.add(ambientLight);

        const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
        dirLight.position.set(5, 10, 7);
        scene.add(dirLight);

        if (typeof THREE.GLTFLoader === 'undefined') {
            showError('GLTFLoader 未加载，请检查 assets/js/vendors/GLTFLoader.js');
            return;
        }
        loader = new THREE.GLTFLoader();

        window.addEventListener('resize', onWindowResize);
        document.addEventListener('keydown', onKeyDown);
        document.getElementById('btn-prev').onclick = prevPage;
        document.getElementById('btn-next').onclick = nextPage;

        loadIndex();
        animate();
    }

    async function loadIndex() {
        try {
            const res = await fetch("pages/index.json");
            const data = await res.json();
            pages = data.pages || [];
            bookTitle.textContent = data.book_title || '3D Comic';
            if (pages.length > 0) {
                loadPage(0);
            } else {
                showError('未找到漫画页面');
            }
        } catch (e) {
            showError('加载 index.json 失败: ' + e.message);
        }
    }

    async function loadPage(idx) {
        if (idx < 0 || idx >= pages.length) return;
        currentIdx = idx;
        const pageInfo = pages[idx];
        const pageId = pageInfo.page_id;
        
        loadingOverlay.style.opacity = 1;
        loadingOverlay.style.display = 'flex';
        loadingText.textContent = `加载第 ${idx + 1} 页...`;
        pageIndicator.textContent = `Page ${idx + 1} / ${pages.length}`;

        try {
            const pageRes = await fetch(`pages/${pageId}/page.json`);
            const pageData = await pageRes.json();
            console.log("[PAGE DATA]", pageData);

            // 清理旧模型
            if (currentModel) {
                scene.remove(currentModel);
                currentModel.traverse(child => {
                    if (child.geometry) child.geometry.dispose();
                    if (child.material) {
                        if (Array.isArray(child.material)) {
                            child.material.forEach(m => m.dispose());
                        } else {
                            child.material.dispose();
                        }
                    }
                });
            }

            // 加载新模型
            if (pageData.model && pageData.model.glb) {
                const glbUrl = `pages/${pageId}/${pageData.model.glb}`;
                console.log("[GLB URL]", glbUrl);
                
                const gltf = await new Promise((resolve, reject) => {
                    loader.load(glbUrl, resolve, undefined, reject);
                });
                
                currentModel = gltf.scene;
                scene.add(currentModel);
                console.log("[GLB LOADED]", currentModel);

                const box = new THREE.Box3().setFromObject(currentModel);
                console.log("[GLB BOUNDS]", box.min.toArray(), box.max.toArray());

                // 应用相机
                applyCamera(pageData, currentModel);
            }

            loadingOverlay.style.opacity = 0;
            setTimeout(() => loadingOverlay.style.display = 'none', 500);
        } catch (e) {
            console.error("[GLB FAILED]", e);
            showError(`加载页面 ${pageId} 失败: ` + e.message);
        }
    }

    function applyCamera(pageData, model) {
        console.log("[CAMERA RAW] pos:", JSON.stringify(pageData.camera.position), "target:", JSON.stringify(pageData.camera.target));
        
        let validCamera = false;
        if (pageData.camera) {
            const p = pageData.camera.position;
            const t = pageData.camera.target;
            
            // 校验数据有效性
            if (p && t && p.every(v => isFinite(v)) && t.every(v => isFinite(v))) {
            // 5.2 FIX: 经验证 Blender Z-up -> Three.js Y-up 转换是必要的
            // 转换逻辑: [X, Y, Z] -> [X, Z, -Y]
            camera.position.set(p[0], p[2], -p[1]);
            
            const targetVec = new THREE.Vector3(t[0], t[2], -t[1]);
            camera.lookAt(targetVec);
            
            if (controls) {
                controls.target.copy(targetVec);
                controls.update();
            }

            camera.fov = pageData.camera.fov || 45;
                camera.updateProjectionMatrix();
                validCamera = true;
                console.log("[CAMERA APPLIED] Blender coordinates");
            }
        }

        // 防黑屏 Fallback
        if (!validCamera) {
            console.warn("[CAMERA INVALID] Using GLB bounds fallback");
            const box = new THREE.Box3().setFromObject(model);
            const center = box.getCenter(new THREE.Vector3());
            const size = box.getSize(new THREE.Vector3());
            const maxDim = Math.max(size.x, size.y, size.z);
            const fov = camera.fov * (Math.PI / 180);
            let cameraZ = Math.abs(maxDim / 2 / Math.tan(fov / 2));
            cameraZ *= 1.5; // 留一点边距

            camera.position.set(center.x, center.y, center.z + cameraZ);
            camera.lookAt(center);

            if (controls) {
                controls.target.copy(center);
                controls.update();
            }

            camera.updateProjectionMatrix();
        }
    }

    function showError(msg) {
        errorOverlay.textContent = msg;
        errorOverlay.style.display = 'flex';
        loadingOverlay.style.display = 'none';
    }

    function prevPage() { if (currentIdx > 0) loadPage(currentIdx - 1); }
    function nextPage() { if (currentIdx < pages.length - 1) loadPage(currentIdx + 1); }

    function onKeyDown(e) {
        if (e.key === 'ArrowLeft') prevPage();
        if (e.key === 'ArrowRight') nextPage();
    }

    function onWindowResize() {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
    }

    function animate() {
        requestAnimationFrame(animate);
        if (controls) controls.update();
        renderer.render(scene, camera);
    }

    init();
})();
