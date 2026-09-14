/**
 * Cinematic 运行时适配器：封装 Needle / three / comic-runtime 的生命周期。
 *
 * 唯一职责：对外暴露统一的 init / loadPage / unloadPage / dispose，
 * 内部组合 runtime-setup（three 底座）与 comic-runtime（PageManager / GlbLoader / AnimationPlayer / CameraController）。
 *
 * 严格隔离：本模块是唯一允许直接 import @runtime/runtime-setup 与 @comic-runtime/* 的文件；
 * Cinematic3DReader 只依赖 Adapter 接口，禁止直接触碰这些依赖。
 *
 * 类型注意：本模块不直接 import three 类型，避免在 src/ 下触发对 viewer-needle/node_modules/three 的类型依赖。
 */
import { createViewer } from "@runtime/runtime-setup";
import { PageManager, type PageData } from "@comic-runtime/PageManager";

export interface AdapterLoadedPage {
  page: PageData;
  glbUrl: string;
}

export interface MinimalViewerContext {
  renderer: { dispose(): void; domElement: HTMLElement };
}

export class CinematicRuntimeAdapter {
  private appContainer: HTMLElement;
  private ctx: MinimalViewerContext | null = null;
  private pageManager: PageManager | null = null;
  private initialized = false;
  private disposed = false;
  private currentPage: AdapterLoadedPage | null = null;

  onStatus?: (msg: string) => void;

  constructor(appContainer: HTMLElement) {
    this.appContainer = appContainer;
  }

  get renderer(): { dispose(): void; domElement: HTMLElement } | null {
    return this.ctx?.renderer ?? null;
  }
  get isInitialized(): boolean {
    return this.initialized;
  }
  get loadedPage(): AdapterLoadedPage | null {
    return this.currentPage;
  }

  async init(): Promise<void> {
    if (this.initialized || this.disposed) return;
    this.appContainer.innerHTML = "";
    const appDiv = document.createElement("div");
    appDiv.id = "app";
    appDiv.style.width = "100%";
    appDiv.style.height = "100%";
    this.appContainer.appendChild(appDiv);

    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    
    // 明确传递 appDiv 给 createViewer，避免 getElementById 歧义
    const ctxAny = (await createViewer(appDiv)) as unknown as MinimalViewerContext;
    this.ctx = ctxAny;
    this.pageManager = new PageManager();
    this.pageManager.onStatus = (msg) => this.onStatus?.(msg);
    this.initialized = true;
  }

  async loadPage(page: PageData, glbUrl: string): Promise<void> {
    if (!this.initialized) await this.init();
    if (!this.pageManager) throw new Error("CinematicRuntimeAdapter not initialized");
    this.currentPage = { page, glbUrl };
    await this.pageManager.loadPage(page, glbUrl);
    this.pageManager.startLoop();
  }

  async unloadPage(): Promise<void> {
    if (this.pageManager) {
      try {
        this.pageManager.stopLoop();
        this.pageManager.pause();
      } catch { /* ignore */ }
    }
    this.currentPage = null;
  }

  play(): void {
    this.pageManager?.play();
  }
  pause(): void {
    this.pageManager?.pause();
  }
  get playing(): boolean {
    return this.pageManager?.playing ?? false;
  }

  setCamera(name: string): boolean {
    return this.pageManager?.setCamera(name) ?? false;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.initialized = false;
    try {
      if (this.pageManager) {
        this.pageManager.dispose();
        this.pageManager = null;
      }
      if (this.ctx) {
        try {
          this.ctx.renderer.dispose();
          if (this.ctx.renderer.domElement && this.ctx.renderer.domElement.parentNode) {
            this.ctx.renderer.domElement.parentNode.removeChild(this.ctx.renderer.domElement);
          }
        } catch { /* renderer 已销毁 */ }
        try {
          const win = window as unknown as { __comicViewer?: unknown };
          if (win.__comicViewer === this.ctx) {
            delete win.__comicViewer;
          }
        } catch { /* ignore */ }
        this.ctx = null;
      }
    } finally {
      this.appContainer.innerHTML = "";
      this.currentPage = null;
    }
  }
}
