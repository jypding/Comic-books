
(function() {
    let renderer, loader;
    let pages = [];
    let frameViews = [];
    let currentIdx = 0;
    let viewMode = 'paging'; // 'paging' or 'scrolling'
    
    // 5.2 FIX: 视频/图片纹理缓存，防止内存泄漏和重复加载
    const videoCache = new Map();
    const textureCache = new Map();

    const container = document.getElementById('canvas-container');
    const scrollContainer = document.getElementById('vertical-scroll-container');
    const loadingOverlay = document.getElementById('loading-overlay');
    const loadingText = document.getElementById('loading-text');
    const errorOverlay = document.getElementById('error-overlay');
    const pageIndicator = document.getElementById('page-indicator');
    const bookTitle = document.getElementById('book-title');
    const btnToggle = document.getElementById('btn-toggle-mode');
    
    console.log("[3DComic] Video media module loaded");

    class FrameView {
        constructor(pageData, pageId, index) {
            this.pageData = pageData;
            this.pageId = pageId;
            this.index = index;
            this.loaded = false;
            this.model = null;
            this.placeholder = null;
            this.width = pageData.width || 1920;
            this.height = pageData.height || 1080;
            
            this.scene = new THREE.Scene();
            this.scene.background = new THREE.Color(0x05070a);
            
            // [MODERN_CAMERA] 初始使用占位相机，加载后将被 GLB Camera 替换
            this.camera = new THREE.PerspectiveCamera(45, this.width / this.height, 0.1, 1000);
            
            this.mixer = null;
            this.clock = new THREE.Clock();
            
            const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
            this.scene.add(ambientLight);
            
            const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
            dirLight.position.set(5, 10, 7);
            this.scene.add(dirLight);

            this.controls = null;
        }

        async load() {
            if (this.loaded) return;
            try {
                const pageRes = await fetch(`pages/${this.pageId}/page.json?t=${Date.now()}`);
                const fullPageData = await pageRes.json();
                
                this.width = fullPageData.width || this.width;
                this.height = fullPageData.height || this.height;

                if (fullPageData.model && fullPageData.model.glb) {
                    const glbUrl = `pages/${this.pageId}/${fullPageData.model.glb}?t=${Date.now()}`;
                    const gltf = await new Promise((resolve, reject) => {
                        loader.load(glbUrl, resolve, undefined, reject);
                    });
                    this.model = gltf.scene;
                    this.scene.add(this.model);
                    
                    // 1. 优先绑定相机实例
                    this.applyCamera(fullPageData);

                    // 2. 诊断相机绑定状态
                    if (this.camera) {
                        const cp = this.camera.position;
                        const cq = this.camera.quaternion;
                        console.log(`[CAMERA_AUDIT]`);
                        console.log(`  page=${this.pageId}`);
                        console.log(`  blenderName=${fullPageData.camera ? fullPageData.camera.blender_camera_name : 'N/A'}`);
                        console.log(`  actualName=${this.camera.name}`);
                        console.log(`  uuid=${this.camera.uuid}`);
                        console.log(`  parent=${this.camera.parent ? this.camera.parent.name : 'null'}`);
                        console.log(`  isCamera=true`);
                        console.log(`  cameraPosition=${cp.x.toFixed(4)},${cp.y.toFixed(4)},${cp.z.toFixed(4)}`);
                        console.log(`  cameraQuaternion=${cq.x.toFixed(4)},${cq.y.toFixed(4)},${cq.z.toFixed(4)},${cq.w.toFixed(4)}`);
                    }

                    // 3. 诊断控制器状态
                    if (this.controls) {
                        console.log(`[CONTROLS_AUDIT]`);
                        console.log(`  page=${this.pageId}`);
                        console.log(`  controlsObjectName=${this.controls.object ? this.controls.object.name : 'null'}`);
                        console.log(`  controlsObjectUUID=${this.controls.object ? this.controls.object.uuid : 'null'}`);
                        console.log(`  cameraName=${this.camera.name}`);
                        console.log(`  sameReference=${this.controls.object === this.camera}`);
                    }

                    // 4. [MODERN_CAMERA] 恢复原作者逻辑：全量播放 GLB 动画 + 深度归属审计
                    if (gltf.animations && gltf.animations.length > 0) {
                        this.mixer = new THREE.AnimationMixer(this.model);
                        let hasDirectCameraTracks = false;

                        gltf.animations.forEach(clip => {
                            console.log(`[MODERN_ANIM] Playing clip: ${clip.name}`);
                            clip.tracks.forEach(track => {
                                const targetName = track.name.split('.')[0];
                                const targetObject = this.model.getObjectByName(targetName);
                                const isCurrent = targetObject === this.camera;
                                if (isCurrent) hasDirectCameraTracks = true;

                                console.log(`[ANIM_TARGET]`);
                                console.log(`  page=${this.pageId}`);
                                console.log(`  clip=${clip.name}`);
                                console.log(`  track=${track.name}`);
                                console.log(`  resolvedName=${targetObject ? targetObject.name : 'NOT_FOUND'}`);
                                console.log(`  resolvedUUID=${targetObject ? targetObject.uuid : 'null'}`);
                                console.log(`  targetType=${targetObject ? targetObject.type : 'null'}`);
                                console.log(`  targetIsCamera=${targetObject ? !!targetObject.isCamera : false}`);
                                console.log(`  targetIsCurrentCamera=${isCurrent}`);
                            });

                            const action = this.mixer.clipAction(clip);
                            action.play();

                            console.log(`[MIXER_AUDIT]`);
                            console.log(`  page=${this.pageId}`);
                            console.log(`  actionCount=${gltf.animations.length}`);
                            console.log(`  clip=${clip.name}`);
                            console.log(`  enabled=${action.enabled}`);
                            console.log(`  paused=${action.paused}`);
                            console.log(`  timeScale=${action.timeScale}`);
                            console.log(`  loopMode=${action.loop}`);
                        });

                        console.log(`[CAMERA_ANIM]`);
                        console.log(`  page=${this.pageId}`);
                        console.log(`  camera=${this.camera.name}`);
                        console.log(`  hasDirectCameraTracks=${hasDirectCameraTracks}`);
                        console.log(`  tracks=${gltf.animations.length}`);
                    }
                    
                    // NEW: Video Media Layer Support
                    if (fullPageData.media && Array.isArray(fullPageData.media)) {
                        console.log(`[MEDIA-CHECK] ${this.pageId} total media:`, fullPageData.media.length);
                        fullPageData.media.forEach((m, i) => {
                            console.log(`[MEDIA-CHECK] ${this.pageId} item ${i}: mesh=${m.mesh_name}, type=${m.type}`);
                            if (m.type === 'sequence') {
                                console.log("[SEQ] DISCOVERED", m);
                                this.setupSequence(m);
                            } else {
                                this.setupVideo(m);
                            }
                        });
                    }

                    this.loaded = true;
                    if (this.placeholder) {
                        this.placeholder.classList.add('active');
                        this.updatePlaceholderSize();
                    }
                    console.log(`[VERTICAL GLB] Loaded: ${this.pageId}`);
                }
            } catch (e) {
                console.error(`[FRAME ${this.index}] Load failed:`, e);
            }
        }

        updatePlaceholderSize() {
            if (this.placeholder && this.width && this.height) {
                const containerWidth = this.placeholder.clientWidth;
                const targetHeight = (containerWidth * this.height) / this.width;
                this.placeholder.style.height = targetHeight + 'px';
            }
        }

        applyCamera(pageData) {
            // [MODERN_CAMERA] 恢复原作者逻辑：直接引用 GLB 内部 Camera 实例
            if (this.model && pageData.camera && pageData.camera.blender_camera_name) {
                const camName = pageData.camera.blender_camera_name;
                const normalizedCamName = camName.replace(/\./g, ''); // 兼容 GLTFLoader 的名称规范化
                let glbCamera = null;
                
                console.log(`[MODERN_CAMERA] Searching for: ${camName} (Normalized: ${normalizedCamName})`);
                
                this.model.traverse(obj => {
                    if (obj.isCamera) {
                        // 兼容严格名称与规范化名称匹配
                        if (obj.name === camName || obj.name === normalizedCamName) {
                            console.log(`[MODERN_CAMERA] Match found: ${obj.name} isCamera: true`);
                            glbCamera = obj;
                        }
                    }
                });
                
                if (glbCamera) {
                    console.log(`[MODERN_CAMERA] Found GLB Camera: ${glbCamera.name}`);
                    // 1. 对象引用赋值
                    this.camera = glbCamera; 
                    // 2. 引用切换，必须更新控制器
                    if (this.controls) {
                        this.controls.object = this.camera;
                    }
                    console.log(`[MODERN_CAMERA] this.camera === glbCamera: ${this.camera === glbCamera}`);
                    return;
                }
            }
            // Fallback: 仅在 GLB 中找不到相机时打印日志并保持占位相机
            if (!this.camera || !this.camera.isCamera) {
                console.warn("[MODERN_CAMERA] GLB camera not found, using fallback");
            }
        }

        setupVideo(media) {
            if (media.type === 'sequence') {
                this.setupSequence(media);
                return;
            }

            // 5.2 FIX: 复用视频实例
            let video = videoCache.get(media.src);
            if (!video) {
                video = document.createElement('video');
                video.src = media.src;
                video.loop = media.loop !== false;
                video.muted = media.muted !== false;
                video.autoplay = media.autoplay !== false;
                video.playsInline = true;
                video.crossOrigin = "anonymous";
                video.style.display = 'none';
                document.body.appendChild(video);
                videoCache.set(media.src, video);
                console.log(`[VIDEO] Created new video instance: ${video.src}`);
            } else {
                console.log(`[VIDEO] Reusing video instance: ${video.src}`);
            }
            
            const texture = new THREE.VideoTexture(video);
            texture.colorSpace = THREE.SRGBColorSpace;
            texture.minFilter = THREE.LinearFilter;
            texture.magFilter = THREE.LinearFilter;
            
            // 5.2 FIX: 彻底修复视频180°倒立问题
            // glTF 导出的模型 UV 坐标系通常要求 flipY = false
            texture.flipY = false; 
            console.log(`[VIDEO] texture orientation: flipY = ${texture.flipY}, mesh = ${media.mesh_name}`);
            
            if (!this.videoMaterials) this.videoMaterials = [];

            this.findTargetMeshes(media.mesh_name, (child) => {
                const materials = Array.isArray(child.material) ? child.material : [child.material];
                materials.forEach(mat => {
                    // 销毁旧纹理，防止 WebGL 报错
                    if (mat.map && mat.map.dispose) mat.map.dispose();
                    
                    mat.map = texture;
                    mat.emissiveMap = texture; 
                    mat.emissive = new THREE.Color(0xffffff);
                    mat.emissiveIntensity = 1.0;
                    mat.transparent = false;
                    mat.needsUpdate = true;
                    this.videoMaterials.push(mat);
                });
            });

            video.onerror = () => {
                console.error(`[VIDEO] ❌ LOAD ERROR: ${video.src}`);
            };

            const startPlay = () => {
                video.play().catch(err => {
                    const forcePlay = () => {
                        video.play();
                        window.removeEventListener('click', forcePlay);
                        window.removeEventListener('touchstart', forcePlay);
                    };
                    window.addEventListener('click', forcePlay);
                    window.addEventListener('touchstart', forcePlay);
                });
            };

            if (video.autoplay) startPlay();
        }

        setupSequence(media) {
            console.log(`[SEQ] SETUP`);
            console.log(`[SEQ] mesh = ${media.mesh_name}`);
            
            if (!this.sequencePlayers) this.sequencePlayers = [];
            
            const frames = Array.isArray(media.frames) ? media.frames : [media.src];
            const fps = Math.max(1, Number(media.fps) || 12);
            
            console.log(`[SEQ] frameCount = ${frames.length}`);
            console.log(`[SEQ] fps = ${fps}`);
            console.log(`[SEQ] frames =`, frames);
            
            const player = {
                media: media,
                frames: frames,
                currentFrame: -1,
                fps: fps,
                startTime: performance.now(),
                textures: new Array(frames.length).fill(null),
                materials: [],
                meshName: media.mesh_name
            };

            this.findTargetMeshes(media.mesh_name, (child) => {
                const materials = Array.isArray(child.material) ? child.material : [child.material];
                materials.forEach(mat => {
                    player.materials.push(mat);
                });
            });

            // 预加载所有帧到缓存
            const loader = new THREE.TextureLoader();
            frames.forEach((url, i) => {
                if (textureCache.has(url)) {
                    player.textures[i] = textureCache.get(url);
                    // 如果是第一帧，立即显示
                    if (i === 0 && player.currentFrame === -1) {
                        player.currentFrame = 0;
                        const tex = player.textures[i];
                        player.materials.forEach(mat => {
                            mat.map = tex;
                            mat.needsUpdate = true;
                        });
                    }
                } else {
                    loader.load(url, (tex) => {
                        tex.colorSpace = THREE.SRGBColorSpace;
                        tex.flipY = false; // 与 glTF UV 匹配
                        player.textures[i] = tex;
                        textureCache.set(url, tex);
                        
                        // 如果是第一帧且尚未显示，立即显示
                        if (i === 0 && player.currentFrame === -1) {
                            player.currentFrame = 0;
                            player.materials.forEach(mat => {
                                mat.map = tex;
                                mat.needsUpdate = true;
                            });
                        }
                    });
                }
            });

            this.sequencePlayers.push(player);
        }

        findTargetMeshes(targetName, callback) {
            let foundCount = 0;
            this.model.traverse(child => {
                if (child.isMesh) {
                    let matchType = null;
                    if (child.name === targetName) {
                        matchType = "精确命中";
                    } else if (child.name.startsWith(targetName + ".")) {
                        const suffix = child.name.slice(targetName.length);
                        if (/^\.\d+$/.test(suffix)) {
                            matchType = "后缀容错命中";
                        }
                    }

                    if (matchType) {
                        console.log(`[MEDIA] ✅ ${matchType}: Binding to mesh ${child.name}`);
                        callback(child);
                        foundCount++;
                    }
                }
            });
            
            if (foundCount === 0) {
                console.warn(`[MEDIA] ❌ 完全找不到目标网格: '${targetName}'`);
            }
        }

        initControls(element) {
            if (this.controls) {
                if (this.controls.domElement === element) return;
                // 5.2 FIX: Safe dispose check
                if (typeof this.controls.dispose === 'function') {
                    this.controls.dispose();
                }
                this.controls = null;
            }
            if (typeof THREE.OrbitControls !== 'undefined') {
                this.controls = new THREE.OrbitControls(this.camera, element);
                this.controls.enableDamping = true;
                this.controls.dampingFactor = 0.05;
                this.controls.screenSpacePanning = true;
                
                // 移动端优化：单指旋转，双指缩放/平移
                this.controls.enableZoom = true;
                this.controls.enableRotate = true;
                this.controls.enablePan = true;
                
                if (element !== renderer.domElement) {
                    // element.style.touchAction = 'none'; // 5.2 REMOVED: Allow page scrolling on mobile
                }
            }
        }
    }

    function init() {
        try {
            if (typeof THREE === 'undefined') {
                showError('Three.js 未加载，请检查 assets/js/vendors/three.min.js');
                return;
            }

            renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
            renderer.setPixelRatio(window.devicePixelRatio);
            renderer.setSize(window.innerWidth, window.innerHeight);
            renderer.toneMapping = THREE.ACESFilmicToneMapping;
            renderer.autoClear = false;
            
            if (renderer.outputColorSpace !== undefined) {
                renderer.outputColorSpace = THREE.SRGBColorSpace;
            }
            
            container.appendChild(renderer.domElement);
            
            if (typeof THREE.GLTFLoader === 'undefined') {
                showError('GLTFLoader 未加载');
                return;
            }
            loader = new THREE.GLTFLoader();

            viewMode = window.innerWidth < 768 ? 'scrolling' : 'paging';
            
            btnToggle.onclick = toggleMode;
            document.getElementById('btn-prev').onclick = () => switchPagingPage(currentIdx - 1);
            document.getElementById('btn-next').onclick = () => switchPagingPage(currentIdx + 1);
            window.addEventListener('resize', onWindowResize);
            document.addEventListener('keydown', onKeyDown);

            loadIndex();
            animate();
        } catch (err) {
            showError('初始化失败: ' + err.message);
        }
    }

    async function loadIndex() {
        try {
            const res = await fetch(`pages/index.json?t=${Date.now()}`);
            const data = await res.json();
            pages = data.pages || [];
            bookTitle.textContent = data.book_title || '3D Comic';
            
            frameViews = pages.map((p, i) => new FrameView(p, p.page_id, i));
            
            syncUI();
            
            if (viewMode === 'paging') {
                switchPagingPage(0);
            } else {
                initScrollingMode();
            }
            
            loadingOverlay.style.opacity = 0;
            setTimeout(() => loadingOverlay.style.display = 'none', 500);
        } catch (e) {
            showError('加载失败: ' + e.message);
        }
    }

    function syncUI() {
        document.body.className = `mode-${viewMode}`;
        btnToggle.textContent = viewMode === 'paging' ? '切换模式：分页' : '切换模式：纵向';
        
        if (viewMode === 'paging') {
            scrollContainer.style.display = 'none';
            container.style.pointerEvents = 'auto';
        } else {
            scrollContainer.style.display = 'block';
            container.style.pointerEvents = 'none';
        }
    }

    function toggleMode() {
        viewMode = viewMode === 'paging' ? 'scrolling' : 'paging';
        syncUI();
        if (viewMode === 'paging') {
            switchPagingPage(currentIdx);
        } else {
            initScrollingMode();
        }
    }

    function switchPagingPage(idx) {
        if (idx < 0 || idx >= frameViews.length) return;
        currentIdx = idx;
        const frame = frameViews[idx];
        frame.initControls(renderer.domElement);
        frame.load();
        pageIndicator.textContent = `Page ${idx + 1} / ${pages.length}`;
    }

    function initScrollingMode() {
        scrollContainer.innerHTML = '';
        console.log(`[VERTICAL] Initializing scrolling mode for ${frameViews.length} frames`);
        frameViews.forEach((frame, i) => {
            const placeholder = document.createElement('div');
            placeholder.className = 'frame-placeholder';
            placeholder.id = `frame-${i}`;
            scrollContainer.appendChild(placeholder);
            frame.placeholder = placeholder;
            frame.initControls(placeholder);
            // 5.2 FIX: Proactively trigger load for vertical mode
            console.log(`[VERTICAL] Creating FrameView ${i}: ${frame.pageId}`);
            frame.load(); 
        });
    }

    function onWindowResize() {
        renderer.setSize(window.innerWidth, window.innerHeight);
        frameViews.forEach(f => f.updatePlaceholderSize());
    }

    function onKeyDown(e) {
        if (viewMode === 'paging') {
            if (e.key === 'ArrowLeft') switchPagingPage(currentIdx - 1);
            if (e.key === 'ArrowRight') switchPagingPage(currentIdx + 1);
        }
    }

    function animate() {
        requestAnimationFrame(animate);
        
        try {
            renderer.setScissorTest(false);
            renderer.setClearColor(0x05070a);
            renderer.clear();

            if (viewMode === 'paging') {
                const frame = frameViews[currentIdx];
                if (frame) {
                    // NEW: Update AnimationMixer
                    if (frame.mixer) {
                        const delta = frame.clock.getDelta();
                        frame.mixer.update(delta);
                    }
                    
                    if (frame.controls) frame.controls.update();
                    
                    // 5.2 FIX: 视频材质强制更新逻辑 (增加 videoWidth 判断防止 WebGL 报错)
                    if (frame.videoMaterials) {
                        frame.videoMaterials.forEach(m => {
                            if (m.map && m.map.isVideoTexture) {
                                const v = m.map.image;
                                if (v && v.videoWidth > 0) {
                                    m.map.needsUpdate = true;
                                }
                            }
                        });
                    }
                    
                    // 5.2 FIX: 图片序列帧更新逻辑
                    if (frame.sequencePlayers && frame.sequencePlayers.length > 0) {
                        const now = performance.now();
                        frame.sequencePlayers.forEach(p => {
                            if (p.frames.length < 2) return;
                            
                            // [SEQ] TICK 日志仅在调试时开启，此处为了满足要求临时打印，但加个频率限制或条件
                            // console.log(`[SEQ] TICK`); 
                            
                            const elapsed = now - p.startTime;
                            const frameIndex = Math.floor(elapsed / (1000 / p.fps)) % p.frames.length;
                            
                            if (frameIndex !== p.currentFrame) {
                                const tex = p.textures[frameIndex];
                                if (tex) {
                                    console.log(`[SEQ] FRAME old=${p.currentFrame} new=${frameIndex}`);
                                    p.currentFrame = frameIndex;
                                    p.materials.forEach(mat => {
                                        mat.map = tex;
                                        mat.needsUpdate = true;
                                    });
                                }
                            }
                        });
                    }
                    
                    // 5.2 FIX: Maintain Aspect Ratio in Paging Mode
                    const winW = window.innerWidth;
                    const winH = window.innerHeight;
                    const frameAspect = frame.width / frame.height;
                    const winAspect = winW / winH;
                    
                    let viewW, viewH, viewL, viewB;
                    if (winAspect > frameAspect) {
                        viewH = winH;
                        viewW = winH * frameAspect;
                        viewL = (winW - viewW) / 2;
                        viewB = 0;
                    } else {
                        viewW = winW;
                        viewH = winW / frameAspect;
                        viewL = 0;
                        viewB = (winH - viewH) / 2;
                    }
                    
                    renderer.setViewport(viewL, viewB, viewW, viewH);
                    renderer.setScissor(viewL, viewB, viewW, viewH);
                    // [MODERN_CAMERA] 严禁手动改写投影参数，直接使用原生 Camera 渲染
                    renderer.setScissorTest(true);
                    renderer.render(frame.scene, frame.camera);
                    renderer.setScissorTest(false);
                }
            } else {
                renderer.setScissorTest(true);
                frameViews.forEach(frame => {
                    if (!frame.placeholder) return;
                    
                    const rect = frame.placeholder.getBoundingClientRect();
                    // Culling: Only render if visible
                    if (rect.bottom < 0 || rect.top > window.innerHeight) return;
                    
                    if (!frame.loaded) frame.load();

                    const width = rect.right - rect.left;
                    const height = rect.bottom - rect.top;
                    const left = rect.left;
                    const bottom = window.innerHeight - rect.bottom;

                    if (width <= 0 || height <= 0) return;

                    // 5.2 FIX: Clamp scissor/viewport to avoid negative values or overflows
                    const scissorLeft = Math.max(0, left);
                    const scissorBottom = Math.max(0, bottom);
                    const scissorWidth = Math.min(width, window.innerWidth - scissorLeft);
                    const scissorHeight = Math.min(height, window.innerHeight - scissorBottom);

                    renderer.setViewport(left, bottom, width, height);
                    renderer.setScissor(scissorLeft, scissorBottom, scissorWidth, scissorHeight);

                    // [MODERN_CAMERA] 严禁手动改写投影参数

                    // NEW: Update AnimationMixer (Scrolling)
                    if (frame.mixer) {
                        const delta = frame.clock.getDelta();
                        frame.mixer.update(delta);
                    }

                    if (frame.controls) frame.controls.update();
                    
                    // 5.2 FIX: 视频材质强制更新逻辑 (增加 videoWidth 判断防止 WebGL 报错)
                    if (frame.videoMaterials) {
                        frame.videoMaterials.forEach(m => {
                            if (m.map && m.map.isVideoTexture) {
                                const v = m.map.image;
                                if (v && v.videoWidth > 0) {
                                    m.map.needsUpdate = true;
                                }
                            }
                        });
                    }

                    // 5.2 FIX: 图片序列帧更新逻辑
                    if (frame.sequencePlayers && frame.sequencePlayers.length > 0) {
                        const now = performance.now();
                        frame.sequencePlayers.forEach(p => {
                            if (p.frames.length < 2) return;
                            
                            const elapsed = now - p.startTime;
                            const frameIndex = Math.floor(elapsed / (1000 / p.fps)) % p.frames.length;
                            
                            if (frameIndex !== p.currentFrame) {
                                const tex = p.textures[frameIndex];
                                if (tex) {
                                    console.log(`[SEQ] FRAME old=${p.currentFrame} new=${frameIndex}`);
                                    p.currentFrame = frameIndex;
                                    p.materials.forEach(mat => {
                                        mat.map = tex;
                                        mat.needsUpdate = true;
                                    });
                                }
                            }
                        });
                    }

                    renderer.render(frame.scene, frame.camera);
                });
            }
        } catch (err) {
            console.error("Render loop error:", err);
        }
    }

    function showError(msg) {
        errorOverlay.textContent = msg;
        errorOverlay.style.display = 'flex';
        loadingOverlay.style.display = 'none';
    }

    init();
})();
