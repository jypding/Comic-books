/**
 * cinematic 模式阅读器（3D 漫画，Needle/Three 驱动）。
 *
 * 硬规则：
 *  - 禁止直接 import @runtime/runtime-setup / @comic-runtime/*；必须通过 CinematicRuntimeAdapter
 *  - Needle/Three 仅在 manifest.mode === "cinematic"（或 page.mode 覆盖）时初始化加载；reading/voice 模式完全不触发
 *  - 若 Adapter.init 抛错（Needle 不可用 / three 初始化失败），ReaderFactory 会 fallback 到 ImageReader reading
 */
import { ComicReader } from "@core/ComicReader";
import type { Manifest, UnifiedPage } from "@core/ProjectLoader";
import { CinematicRuntimeAdapter } from "./CinematicRuntimeAdapter";
import { UiController } from "@comic-runtime/UiController";
import cinematicTemplateHtml from "@ui/cinematic/template.html?raw";
import "@ui/common/common.css";
import "@ui/cinematic/cinematic.css";

const CINEMATIC_ROOT_ID = "cinematic-root";
const READING_ROOT_ID = "reading-root";
const COMIC_UI_ROOT_ID = "comic-ui-root";

export class Cinematic3DReader implements ComicReader {
    private manifest: Manifest;
    private manifestBase: string;
    private root: HTMLElement | null = null;
    private uiRoot: HTMLElement | null = null;
    private adapter: CinematicRuntimeAdapter | null = null;
    private uiController: UiController | null = null;
    private currentPage: UnifiedPage | null = null;
    private initialized = false;

    constructor(manifest: Manifest, manifestBase: string = "./book") {
        this.manifest = manifest;
        this.manifestBase = manifestBase;
    }

    async init(): Promise<void> {
        try {
            this.root = document.getElementById(CINEMATIC_ROOT_ID);
            this.uiRoot = document.getElementById(COMIC_UI_ROOT_ID);
            this.showCinematicRoot();
            if (!this.root) throw new Error(`#${CINEMATIC_ROOT_ID} not found`);
            
            this.adapter = new CinematicRuntimeAdapter(this.root);
            this.adapter.onStatus = (msg) => {
                this.uiController?.setStatus(msg);
            };
            
            await this.adapter.init();
            this.uiController = new UiController();
            this.initialized = true;
        } catch (err) {
            console.error("[Cinematic3DReader] init failed:", err);
            throw err; // 让 ReaderFactory catch 并 fallback
        }
    }

    async loadPage(page: UnifiedPage, pagePath: string): Promise<void> {
        try {
            if (!this.adapter) throw new Error("adapter not initialized");
            this.currentPage = page;
            this.showCinematicRoot();
            this.injectCinematicOverlay();
            this.renderDialogue(page);

            // 解析 GLB 路径
            const glbName = page.model?.glb ?? "scene.glb";
            const pageDirUrl = pagePath.replace(/\.json$/, "");
            const glbUrl = this.isAbsoluteOrRemote(glbName) ? glbName : `${pageDirUrl}/${glbName}`;

            await this.adapter.loadPage(page as any, glbUrl);
        } catch (err) {
            console.error("[Cinematic3DReader] loadPage failed:", err);
            throw err;
        }
    }

    async unloadPage(): Promise<void> {
        try {
            if (this.adapter) await this.adapter.unloadPage();
            this.currentPage = null;
        } catch (err) {
            console.error("[Cinematic3DReader] unloadPage failed:", err);
        }
    }

    play(): void {
        this.adapter?.play();
    }

    pause(): void {
        this.adapter?.pause();
    }

    dispose(): void {
        try {
            this.uiController?.dispose();
            this.uiController = null;
            this.adapter?.dispose();
            this.adapter = null;
            this.removeCinematicOverlay();
            if (this.root) {
                this.root.innerHTML = "";
                this.root.style.display = "none";
            }
            this.initialized = false;
            this.currentPage = null;
        } catch (err) {
            console.error("[Cinematic3DReader] dispose failed:", err);
        }
    }

    private showCinematicRoot(): void {
        if (this.root) this.root.style.display = "block";
        const reading = document.getElementById(READING_ROOT_ID);
        if (reading) reading.style.display = "none";
    }

    private injectCinematicOverlay(): void {
        if (!this.uiRoot) return;
        if (this.uiRoot.querySelector(".cinematic-overlay")) return;
        this.uiRoot.insertAdjacentHTML("beforeend", cinematicTemplateHtml);
    }

    private removeCinematicOverlay(): void {
        this.uiRoot?.querySelector(".cinematic-overlay")?.remove();
    }

    private renderDialogue(page: UnifiedPage): void {
        if (!this.uiRoot) return;
        const speakerEl = this.uiRoot.querySelector<HTMLElement>(".cinematic-speaker");
        const textEl = this.uiRoot.querySelector<HTMLElement>(".cinematic-dialog-text");
        const d = page.dialogues?.[0] ?? page.dialogue;

        if (speakerEl) speakerEl.textContent = d?.speaker ?? "";
        if (textEl) textEl.textContent = d?.text ?? "";

        if (d?.text) this.uiController?.showSubtitle(d.text);
        else this.uiController?.showSubtitle("");
    }

    private isAbsoluteOrRemote(path?: string): boolean {
        if (!path) return false;
        return /^(https?:)?\/\//i.test(path) || path.startsWith("/") || path.startsWith("data:");
    }
}
