import { ComicReader } from "./ComicReader";
import type { Manifest, BookMode, UnifiedPage } from "./ProjectLoader";

export class ReaderFactory {
    private static manifest: Manifest | null = null;
    private static manifestBase: string = "./book";
    private static currentReader: ComicReader | null = null;
    private static currentIndex: number = -1;
    private static currentPageId: string | null = null;

    public static async init(
        manifest: Manifest,
        options?: { manifestBase?: string }
    ): Promise<void> {
        this.manifest = manifest;
        this.manifestBase = options?.manifestBase ?? "./book";
        this.currentIndex = -1;
        this.currentPageId = null;
        this.disposeCurrent();
        this.bindGlobalEvents();
    }

    private static bindGlobalEvents(): void {
        const btnPrev = document.getElementById("btn-prev");
        const btnNext = document.getElementById("btn-next");
        const btnPlay = document.getElementById("btn-play");

        btnPrev?.replaceWith(btnPrev.cloneNode(true));
        btnNext?.replaceWith(btnNext.cloneNode(true));
        btnPlay?.replaceWith(btnPlay.cloneNode(true));

        document.getElementById("btn-prev")?.addEventListener("click", () => this.prev());
        document.getElementById("btn-next")?.addEventListener("click", () => this.next());
        document.getElementById("btn-play")?.addEventListener("click", () => {
            if (this.currentReader) {
                // 这里可以简单切换 play/pause 状态，或者由 reader 自行管理内部状态
                // 暂时简单调用
                this.play(); 
            }
        });
    }

    public static getCurrentReader(): ComicReader | null {
        return this.currentReader;
    }

    public static getManifest(): Manifest | null {
        return this.manifest;
    }

    public static getManifestBase(): string {
        return this.manifestBase;
    }

    public static disposeCurrent(): void {
        if (this.currentReader) {
            try {
                this.currentReader.dispose();
            } catch (err) {
                console.error("[ReaderFactory] dispose old reader failed:", err);
            }
            this.currentReader = null;
        }
    }

    /**
     * 打开指定页面，处理模式切换与降级
     */
    public static async openPage(pageId: string): Promise<void> {
        if (!this.manifest) throw new Error("ReaderFactory not initialized");

        const idx = this.manifest.pages.indexOf(pageId);
        if (idx === -1) {
            console.warn(`[ReaderFactory] pageId ${pageId} not found in manifest`);
        }
        this.currentIndex = idx;
        this.currentPageId = pageId;

        let pageUrl = this.joinBase(this.manifestBase, pageId);
        if (!pageUrl.endsWith(".json")) pageUrl += ".json";
        
        const res = await fetch(pageUrl);
        if (!res.ok) throw new Error(`fetch page failed: ${res.status} ${pageUrl}`);
        
        const rawPage: UnifiedPage = await res.json();
        const page = this.normalizePage(rawPage);

        // 确定目标模式：页面覆盖 > 全局默认
        const targetMode = page.mode ?? this.manifest.mode;
        
        // 如果模式变化，或者当前无 reader，则创建/切换
        const currentMode = this.getCurrentReaderMode();
        if (!this.currentReader || currentMode !== targetMode) {
            await this.createReader(targetMode);
        }

        if (this.currentReader) {
            await this.currentReader.loadPage(page, pageUrl);
        }
    }

    public static async next(): Promise<void> {
        if (!this.manifest || this.currentIndex >= this.manifest.pages.length - 1) return;
        await this.openPage(this.manifest.pages[this.currentIndex + 1]);
    }

    public static async prev(): Promise<void> {
        if (!this.manifest || this.currentIndex <= 0) return;
        await this.openPage(this.manifest.pages[this.currentIndex - 1]);
    }

    public static play(): void {
        this.currentReader?.play();
    }

    public static pause(): void {
        this.currentReader?.pause();
    }

    private static async createReader(mode: BookMode): Promise<ComicReader> {
        this.disposeCurrent();
        try {
            console.log("[ReaderFactory] createReader mode=", mode);
            if (mode === "reading") {
                const { Reading3DReader } = await import("../modes/reading/Reading3DReader");
                const reader = new Reading3DReader(this.manifest!, this.manifestBase);
                reader.onNextRequested = () => this.next();
                reader.onPrevRequested = () => this.prev();
                await reader.init();
                this.currentReader = reader;
                return reader;
            } else if (mode === "voice") {
                console.log("[ReaderFactory] dynamic importing VoiceBookReader...");
                const { VoiceBookReader } = await import("../modes/voice/VoiceBookReader");
                const reader = new VoiceBookReader(this.manifest!, this.manifestBase);
                reader.onNextRequested = () => this.next();
                reader.onPrevRequested = () => this.prev();
                await reader.init();
                this.currentReader = reader;
                return reader;
            } else if (mode === "cinematic") {
                const { Cinematic3DReader } = await import("../modes/cinematic/Cinematic3DReader");
                const reader = new Cinematic3DReader(this.manifest!, this.manifestBase);
                await reader.init();
                this.currentReader = reader;
                return reader;
            } else {
                throw new Error(`unsupported mode: ${mode}`);
            }
        } catch (err) {
            if (mode === "cinematic") {
                console.warn("[ReaderFactory] cinematic init failed, fallback to reading:", err);
                return await this.createReader("reading");
            }
            throw err;
        }
    }

    private static getCurrentReaderMode(): BookMode | null {
        if (!this.currentReader) return null;
        
        // 显式检查 reader 的 mode 属性
        const reader = this.currentReader as any;
        if (reader.mode) return reader.mode;

        const name = this.currentReader.constructor.name;
        if (name === "Cinematic3DReader") return "cinematic";
        return null;
    }

    private static normalizePage(raw: UnifiedPage): UnifiedPage {
        const id = raw.page_id ?? raw.pageId ?? "";
        return { ...raw, page_id: id, pageId: id };
    }

    private static joinBase(base: string, rel: string): string {
        if (/^(https?:)?\/\//i.test(rel) || rel.startsWith("/") || rel.startsWith("data:")) return rel;
        if (rel.startsWith("./")) rel = rel.slice(2);
        return `${base.replace(/\/+$/, "")}/${rel}`;
    }
}
