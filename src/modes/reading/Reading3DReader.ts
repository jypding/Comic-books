import { ComicReader } from "@core/ComicReader";
import type { Manifest, UnifiedPage } from "@core/ProjectLoader";
import { CinematicRuntimeAdapter } from "../cinematic/CinematicRuntimeAdapter";
import reading3dTemplateHtml from "@ui/reading/reading3d.template.html?raw";
import "@ui/reading/reading3d.css";

const READING_ROOT_ID = "reading-root";
const CINEMATIC_ROOT_ID = "cinematic-root";

export class Reading3DReader implements ComicReader {
    protected manifest: Manifest;
    protected manifestBase: string;
    public readonly mode: string = "reading";
    protected root: HTMLElement | null = null;
    protected adapter: CinematicRuntimeAdapter | null = null;
    protected currentPage: UnifiedPage | null = null;
    protected initialized = false;
    protected audio: HTMLAudioElement | null = null;
    protected readingStyleTag: HTMLStyleElement | null = null;

    // 导航回调
    public onNextRequested?: () => void;
    public onPrevRequested?: () => void;
    public onToggleTheme?: () => void;

    constructor(manifest: Manifest, manifestBase: string = "./book") {
        this.manifest = manifest;
        this.manifestBase = manifestBase;
    }

    async init(): Promise<void> {
        try {
            this.root = document.getElementById(READING_ROOT_ID);
            this.showReadingRoot();
            if (!this.root) throw new Error(`#${READING_ROOT_ID} not found`);

            // 1. 加载数据包内的基础 Reading 主题样式 (数据驱动)
            await this.loadReadingStyles();

            // 2. 注入模板并设置布局类
            this.root.classList.add("reading3d-layout");
            this.injectTemplate();

            // 3. 初始化适配器，挂载到 3D 视口容器
            const stageRoot = this.root.querySelector<HTMLElement>("#reading3d-stage-root");
            if (stageRoot) {
                this.adapter = new CinematicRuntimeAdapter(stageRoot);
                await this.adapter.init();
            }

            this.bindEvents();
            this.initialized = true;
        } catch (err) {
            console.error("[Reading3DReader] init failed:", err);
            throw err;
        }
    }

    protected injectTemplate(): void {
        if (this.root) {
            this.root.innerHTML = reading3dTemplateHtml;
        }
    }

    protected async loadReadingStyles(): Promise<void> {
        // 读取基础主题 JSON
        const themeFile = this.mode === "voice" ? "voice-theme.json" : "reading-theme.json";
        const themeUrl = this.joinBase(this.manifestBase, `../styles/${themeFile}`);
        try {
            const themeRes = await fetch(themeUrl);
            if (themeRes.ok) {
                const data = await themeRes.json();
                this.applyReadingTheme(data);
            }
        } catch (e) {
            console.warn(`[Reading3DReader] Failed to load ${themeFile}`, e);
        }

        // 读取并注入基础 CSS
        const cssFile = this.mode === "voice" ? "voice-book.css" : "reading-book.css";
        const cssUrl = this.joinBase(this.manifestBase, `../styles/${cssFile}`);
        try {
            const cssRes = await fetch(cssUrl);
            if (cssRes.ok) {
                const cssText = await cssRes.text();
                if (!this.readingStyleTag) {
                    this.readingStyleTag = document.createElement("style");
                    this.readingStyleTag.id = "reading-book-dynamic-css";
                    document.head.appendChild(this.readingStyleTag);
                }
                this.readingStyleTag.textContent = cssText;
            }
        } catch (e) {
            console.warn(`[Reading3DReader] Failed to load ${cssFile}`, e);
        }
    }

    protected applyReadingTheme(data: any, themeName: string = "light"): void {
        const root = document.documentElement;
        const theme = data.theme?.[themeName] || data.theme?.["light"];
        
        if (theme) {
            Object.entries(theme).forEach(([key, value]) => {
                root.style.setProperty(`--${key}`, value as string);
            });
        }
        
        if (data.theme?.["font-serif"]) {
            root.style.setProperty("--serif", data.theme["font-serif"]);
        }
        
        if (data.theme?.["font-sans"]) {
            root.style.setProperty("--sans", data.theme["font-sans"]);
        }
    }

    async loadPage(page: UnifiedPage, pagePath: string): Promise<void> {
        try {
            if (!this.adapter) throw new Error("adapter not initialized");
            this.currentPage = page;
            this.showReadingRoot();
            this.renderPage(page);

            // 加载 3D 模型
            const glbName = page.model?.glb ?? "scene.glb";
            const pageDirUrl = pagePath.replace(/\.json$/, "");
            const glbUrl = this.isAbsoluteOrRemote(glbName) ? glbName : `${pageDirUrl}/${glbName}`;
            
            await this.adapter.loadPage(page as any, glbUrl);
            
            // 设置音频
            this.setupAudio(page);
        } catch (err) {
            console.error("[Reading3DReader] loadPage failed:", err);
            throw err;
        }
    }

    async unloadPage(): Promise<void> {
        if (this.adapter) await this.adapter.unloadPage();
        if (this.audio) {
            this.audio.pause();
            this.audio.src = "";
            this.audio = null;
        }
        this.currentPage = null;
    }

    play(): void {
        this.adapter?.play();
        if (this.audio) void this.audio.play();
    }

    pause(): void {
        this.adapter?.pause();
        if (this.audio) this.audio.pause();
    }

    dispose(): void {
        try {
            this.adapter?.dispose();
            this.adapter = null;
            if (this.root) {
                this.root.innerHTML = "";
                this.root.style.display = "none";
            }
            this.initialized = false;
            this.currentPage = null;
        } catch (err) {
            console.error("[Reading3DReader] dispose failed:", err);
        }
    }

    protected showReadingRoot(): void {
        if (this.root) this.root.style.display = "block";
        const cinematic = document.getElementById(CINEMATIC_ROOT_ID);
        if (cinematic) cinematic.style.display = "none";
    }

    protected bindEvents(): void {
        if (!this.root) return;

        // 导航按钮
        this.root.querySelector(".btn-prev")?.addEventListener("click", () => this.onPrevRequested?.());
        this.root.querySelector(".btn-next")?.addEventListener("click", () => this.onNextRequested?.());
        this.root.querySelector(".btn-contents")?.addEventListener("click", () => {
            // 返回目录或主页
            window.location.search = ""; 
        });

        // 样式切换
        this.root.querySelector(".btn-theme")?.addEventListener("click", () => {
            const panel = this.root?.querySelector(".reading3d-panel");
            const isDark = panel?.classList.toggle("dark");
            const themeBtn = this.root?.querySelector(".btn-theme");
            if (themeBtn) themeBtn.textContent = isDark ? "☼" : "🌙";
            this.onToggleTheme?.();
        });

        // 朗读
        this.root.querySelector(".btn-read-aloud")?.addEventListener("click", () => {
            if (this.audio) {
                if (this.audio.paused) {
                    this.audio.play();
                    this.root?.querySelector(".btn-read-aloud")?.classList.add("active");
                } else {
                    this.audio.pause();
                    this.root?.querySelector(".btn-read-aloud")?.classList.remove("active");
                }
            }
        });

        // THE CASE 旁边的音频图标
        this.root.querySelector(".reading3d-speak-btn")?.addEventListener("click", () => {
            if (this.audio) {
                this.audio.currentTime = 0;
                this.audio.play();
            }
        });

        // Sit 按钮
        this.root.querySelector(".btn-sit")?.addEventListener("click", () => {
            // 进入沉浸式模式，隐藏面板
            const panel = this.root?.querySelector(".reading3d-panel");
            if (panel) panel.classList.toggle("hidden");
            // 可以在这里触发相机进入特定的 "Sit" 视角
        });

        // 3D 悬浮按钮
        this.root.querySelector(".btn-music")?.addEventListener("click", (e) => {
            const btn = e.currentTarget as HTMLElement;
            btn.classList.toggle("active");
            // TODO: 控制 BGM
        });

        this.root.querySelector(".btn-visible")?.addEventListener("click", (e) => {
            const btn = e.currentTarget as HTMLElement;
            btn.classList.toggle("active");
            // TODO: 控制 3D 场景可见性
        });

        this.root.querySelector(".btn-camera")?.addEventListener("click", () => {
            // TODO: 重置相机到 Blender 导出位置
        });

        this.root.querySelector(".btn-fullscreen")?.addEventListener("click", () => {
            if (!document.fullscreenElement) {
                document.documentElement.requestFullscreen();
            } else {
                document.exitFullscreen();
            }
        });
    }

    protected renderPage(page: UnifiedPage): void {
        if (!this.root) return;

        // 更新文本内容
        const pageNum = page.page_id.replace(/^p/, "").replace(/^0+/, "") || "1";
        const title = page.chapterTitle || page.title || "";
        const sectionLabel = (page as any).labels?.section || "THE CASE"; 
        const longText = page.longText || "";

        const sealEl = this.root.querySelector(".reading3d-seal");
        if (sealEl) sealEl.textContent = pageNum;

        const titleEl = this.root.querySelector(".reading3d-title");
        if (titleEl) titleEl.textContent = title;

        const sectionLabelEl = this.root.querySelector(".reading3d-section-label");
        if (sectionLabelEl && this.mode !== "voice") {
            // 只保留文本节点，不覆盖子元素（如音频图标）
            const textNode = Array.from(sectionLabelEl.childNodes).find(n => n.nodeType === Node.TEXT_NODE);
            if (textNode) textNode.textContent = sectionLabel + " ";
            else sectionLabelEl.prepend(document.createTextNode(sectionLabel + " "));
        }

        const textEl = this.root.querySelector(".reading3d-text");
        if (textEl) textEl.textContent = longText;
        
        // 更新按钮状态
        const prevBtn = this.root.querySelector<HTMLButtonElement>(".btn-prev");
        const nextBtn = this.root.querySelector<HTMLButtonElement>(".btn-next");
        if (prevBtn) prevBtn.disabled = !page.prev;
        if (nextBtn) nextBtn.disabled = !page.next;

        // 重置滚动条
        const panel = this.root.querySelector(".reading3d-panel");
        if (panel) panel.scrollTop = 0;
    }

    protected setupAudio(page: UnifiedPage): void {
        if (!this.root) return;
        const audioEl = this.root.querySelector<HTMLAudioElement>(".reading3d-audio");
        if (!audioEl) return;

        const src = this.resolveAudioSrc(page);
        if (src) {
            audioEl.src = src;
            audioEl.load();
            this.audio = audioEl;
        } else {
            audioEl.src = "";
            this.audio = null;
        }
    }

    protected resolveAudioSrc(page: UnifiedPage): string | null {
        const file = page.narrationAudio || page.audioFile || page.dialogue?.audio || page.dialogues?.[0]?.audio;
        if (!file) return null;
        if (this.isAbsoluteOrRemote(file)) return file;
        
        const audioDir = this.manifest.audioDir ?? "audio";
        return this.joinBase(this.manifestBase, `../${audioDir}/${file}`);
    }

    protected isAbsoluteOrRemote(path?: string): boolean {
        if (!path) return false;
        return /^(https?:)?\/\//i.test(path) || path.startsWith("/") || path.startsWith("data:");
    }

    protected joinBase(base: string, rel: string): string {
        if (this.isAbsoluteOrRemote(rel)) return rel;
        if (rel.startsWith("./")) rel = rel.slice(2);
        return `${base.replace(/\/+$/, "")}/${rel}`;
    }
}
