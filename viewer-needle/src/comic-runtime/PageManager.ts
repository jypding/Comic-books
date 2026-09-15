/**
 * 页面/画格管理器（迁移自旧 app.js 的页面切换逻辑）
 *
 * 数据驱动：由 Cinematic3DReader 外部驱动单页加载，
 * PageManager 负责加载 GLB、绑定 Blender 命名相机、驱动 AnimationMixer 动画。
 *
 * PageData 严格对齐 R3 遗留工程 page schema：
 * {page_id, title, thumbnail, width, height, camera:{blender_camera_name},
 *  dialogue, media, animations:{active_actions:[]}, model:{glb}, next, prev}
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { loadGlb } from './GlbLoader';
import { AnimationPlayer } from './AnimationPlayer';
import { CameraController } from './CameraController';

/** R3 遗留工程 page schema（cinematic 专用，不与 reading 合并） */
export interface PageData {
  page_id: string;
  title?: string;
  thumbnail?: string;
  width?: number;
  height?: number;
  camera?: { blender_camera_name?: string };
  dialogue?: { text?: string; speaker?: string; audio?: string | null };
  media?: unknown[];
  animations?: { active_actions?: string[] };
  model?: { glb?: string; splat?: string | null };
  next?: string | null;
  prev?: string | null;
}

export class PageManager {
  private renderer!: THREE.WebGLRenderer;
  private scene!: THREE.Scene;
  private fallbackCamera!: THREE.PerspectiveCamera;

  private player = new AnimationPlayer();
  private camCtrl = new CameraController();

  private loadedScene: THREE.Group | null = null;
  private activeActionName: string | undefined;
  private isPlaying = false;
  private rafId: number | null = null;
  private disposed = false;
  private controls: OrbitControls | null = null;

  onStatus?: (msg: string) => void;

  constructor() {
    const ctx = window.__comicViewer!;
    this.renderer = ctx.renderer;
    this.scene = ctx.scene;
    this.fallbackCamera = ctx.camera;
  }

  /** 加载单页：GLB → 场景 → Blender 命名相机 → AnimationMixer 动画（由 Cinematic3DReader 外部调用） */
  async loadPage(page: PageData, glbUrl: string): Promise<void> {
    this.onStatus?.(`loading: ${page.page_id} (${glbUrl})`);

    // 卸载上一页
    this.unloadCurrentPage();

    console.log('[GLB-URL]', glbUrl);
    const glb = await loadGlb(glbUrl);
    this.loadedScene = glb.scene;
    // 白名单：只保留 Cube / Sphere / TorusKnot / Ground
    const keepNames = ['Cube', 'Sphere', 'TorusKnot', 'Ground'];
    const toRemove: any[] = [];
    glb.scene.traverse((o: any) => {
      if (o.isMesh) {
        const keep = keepNames.some((n) => o.name === n || o.name.startsWith(n + '.'));
        if (!keep) toRemove.push(o);
      }
    });
    toRemove.forEach((o) => {
      console.log('[GLB-REMOVE]', o.name);
      if (o.parent) o.parent.remove(o);
    });

    console.log('[GLB-ROOT]', glb.scene.children.map((c: any) => c.name || c.type));
    glb.scene.traverse((o: any) => {
      if (o.isMesh) {
        console.log('[GLB-MESH]', o.name, '| material:', o.material?.name || '(none)');
      }
    });
    // 强制相机对准 GLB 场景
    this.scene.add(glb.scene);

    // 相机适配：排除 Ground（48x48 地面会撑大包围盒）
    const contentBox = new THREE.Box3();
    glb.scene.traverse((o: any) => {
      if (!o.isMesh) return;
      if (o.name === 'Ground' || o.name.startsWith('Ground.')) return;
      contentBox.expandByObject(o);
    });
    if (contentBox.isEmpty()) {
      contentBox.setFromObject(glb.scene);
    }
    const center = contentBox.getCenter(new THREE.Vector3());
    const size = contentBox.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z, 1);

    console.log('[CAM-CONTENT] center=', center.x.toFixed(2), center.y.toFixed(2), center.z.toFixed(2));
    console.log('[CAM-CONTENT] size=', size.x.toFixed(2), size.y.toFixed(2), size.z.toFixed(2));
    console.log('[CAM-CONTENT] maxDim=', maxDim.toFixed(2));

    this.fallbackCamera.fov = 50;
    this.fallbackCamera.near = 0.1;
    this.fallbackCamera.far = maxDim * 20;
    this.fallbackCamera.position.set(
      center.x,
      center.y + maxDim * 0.2,
      center.z + maxDim * 1.5
    );
    this.fallbackCamera.lookAt(center);
    this.fallbackCamera.updateProjectionMatrix();

    // 检查所有 mesh 的贴图状态
    glb.scene.traverse((o: any) => {
      if (o.isMesh && o.material) {
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach((m: any) => {
          console.log('[MAT]', o.name, 
            '| map=', m.map ? 'YES' : 'NO',
            '| color=', m.color ? m.color.getHexString() : 'none',
            '| transparent=', m.transparent,
            '| opacity=', m.opacity,
            '| alphaTest=', m.alphaTest);
        });
      }
    });

    if (this.controls) this.controls.dispose();
    this.controls = new OrbitControls(this.fallbackCamera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.target.copy(center);
    this.controls.update();

    console.log('[FIX] OrbitControls attached. canvas:', this.renderer.domElement.width, 'x', this.renderer.domElement.height);

    // 绑定 Blender 命名相机（按 camera.blender_camera_name 查找）
    // this.camCtrl.bind(glb, page.camera?.blender_camera_name);
    console.log('[PageManager] GLB camera bind disabled, using fallbackCamera');

    // 绑定动画混合器
    this.player.bind(glb);

    // 播放 active_actions 中的轨道（R3 schema: animations.active_actions[0]）
    this.activeActionName = page.animations?.active_actions?.[0];
    this.player.playTrack(this.activeActionName);
    this.isPlaying = true;

    this.onStatus?.(`ready: ${page.page_id}`);
  }

  /** 启动渲染循环 */
  startLoop(): void {
    if (this.rafId !== null || this.disposed) return;
    const tick = () => {
      this.rafId = requestAnimationFrame(tick);
      this.player.update();
      this.controls?.update();
      const cam = this.fallbackCamera;
      this.renderer.render(this.scene, cam);
    };
    this.rafId = requestAnimationFrame(tick);
  }

  /** 停止渲染循环 */
  stopLoop(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
  }

  play(): void {
    this.player.playTrack(this.activeActionName);
    this.isPlaying = true;
  }

  pause(): void {
    this.player.stopAll();
    this.isPlaying = false;
  }

  togglePlay(): void {
    if (this.isPlaying) this.pause();
    else this.play();
  }

  get playing(): boolean {
    return this.isPlaying;
  }

  setCamera(name: string): boolean {
    return this.camCtrl.switchTo(name);
  }

  private unloadCurrentPage(): void {
    if (this.loadedScene) {
      this.player.dispose();
      this.scene.remove(this.loadedScene);
      this.loadedScene = null;
    }
  }

  dispose(): void {
    this.disposed = true;
    this.stopLoop();
    this.unloadCurrentPage();
    this.isPlaying = false;
    if (this.controls) {
      this.controls.dispose();
      this.controls = null;
    }
  }
}
