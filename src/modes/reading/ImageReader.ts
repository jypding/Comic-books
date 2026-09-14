/**
 * reading / voice 模式阅读器（纯图文/语音，无 3D / 无 Needle / 无 Three / 无 comic-runtime）。
 *
 * 硬规则：
 *  - 仅允许 import @core/* 与 @ui/*，严禁 import @comic-runtime/* / @needle-tools/engine / three
 *  - 不加载 Needle Engine；浏览器网络面板无 needle-tools / three 相关资源
 *
 * 职责：
 *  - 仅负责 DOM 渲染、图片展示、长文展示。
 *  - 仅负责语音音频播放与进度同步。
 *  - 不负责页面切换逻辑，不负责 Manifest 调度。
 */
import { ComicReader } from "@core/ComicReader";
import { Manifest, BookMode, UnifiedPage, ProjectLoader, VoiceStyle } from "@core/ProjectLoader";
import readingTemplateHtml from "@ui/reading/reading3d.template.html?raw";
import "@ui/reading/reading.css";

const READING_ROOT_ID = "reading-root";
const CINEMATIC_ROOT_ID = "cinematic-root";

export class ImageReader implements ComicReader {
    private manifest: Manifest;
    private manifestBase: string;
    public readonly mode: BookMode;
    private root: HTMLElement | null = null;
    private audio: HTMLAudioElement | null = null;
    private progressEl: HTMLElement | null = null;
    private isPlaying = false;
    private initialized = false;
    private currentPage: UnifiedPage | null = null;
    private voiceStyle: VoiceStyle | null = null;
    private pageCardEl: HTMLElement | null = null;
    private pageCardTimer: any = null;

    // 导航回调，避免循环依赖
    public onNextRequested?: () => void;

    private boundAudioTimeUpdate = (): void => { this.updateProgress(); };
    private boundAudioEnded = (): void => { this.onAudioEnded(); };
    private boundAudioLoaded = (): void => { this.updateProgress(); };

    constructor(manifest: Manifest, mode: BookMode = "reading", manifestBase: string = "./book") {
        this.manifest = manifest;
        this.mode = mode === "cinematic" ? "reading" : mode;
        this.manifestBase = manifestBase;
    }

    async init(): Promise<void> {
        try {
            this.root = document.getElementById(READING_ROOT_ID);
            this.showReadingRoot();
            this.initialized = true;
        } catch (err) {
            console.error("[ImageReader] init failed:", err);
        }
    }

    async loadPage(page: UnifiedPage, _pagePath: string): Promise<void> {
        try {
            this.currentPage = page;
            this.showReadingRoot();
            
            if (this.root) {
                // 1. 确保布局类已添加
                this.root.classList.add("reading3d-layout");
                
                // 2. 注入并编译模板 (替换 {{variable}} 占位符)
                this.root.innerHTML = this.compileTemplate(readingTemplateHtml, page);
            }

            // 处理 Voice Style
            if (this.mode === "voice" && page.style && !page.style.includes("{")) {
                await this.loadAndApplyVoiceStyle(page.style);
            }

            this.renderPage(page);
            this.setupAudio(page);
            
            // 显示 PageCard
            if (this.voiceStyle?.pagination.showPageCard) {
                this.showPageCard(page);
            }
        } catch (err) {
            console.error("[ImageReader] loadPage failed:", err);
        }
    }

    private compileTemplate(html: string, page: UnifiedPage): string {
        const pageNum = page.page_id.replace(/^p/, "").replace(/^0+/, "") || "1";
        const title = page.chapterTitle || page.title || "";
        const sectionLabel = (page as any).labels?.section || "THE CASE";
        const longText = page.longText || "";

        return html
            .replace(/\{\{pageNumber\}\}/g, pageNum)
            .replace(/\{\{pageTitle\}\}/g, title)
            .replace(/\{\{sectionLabel\}\}/g, sectionLabel)
            .replace(/\{\{longText\}\}/g, longText);
    }

    async unloadPage(): Promise<void> {
        try {
            if (this.audio) {
                this.audio.pause();
                this.audio.removeEventListener("timeupdate", this.boundAudioTimeUpdate);
                this.audio.removeEventListener("ended", this.boundAudioEnded);
                this.audio.removeEventListener("loadedmetadata", this.boundAudioLoaded);
                this.audio.src = "";
                this.audio.load?.();
                this.audio = null;
            }
            this.isPlaying = false;
            this.currentPage = null;
        } catch (err) {
            console.error("[ImageReader] unloadPage failed:", err);
        }
    }

    play(): void {
        try {
            if (this.audio) {
                void this.audio.play();
                this.isPlaying = true;
            }
        } catch (err) {
            console.error("[ImageReader] play failed:", err);
        }
    }

    pause(): void {
        try {
            if (this.audio) {
                this.audio.pause();
                this.isPlaying = false;
            }
        } catch (err) {
            console.error("[ImageReader] pause failed:", err);
        }
    }

    dispose(): void {
        try {
            void this.unloadPage();
            if (this.root) {
                this.root.innerHTML = "";
                this.root.style.display = "none";
            }
            const styleId = "reading-page-style";
            document.getElementById(styleId)?.remove();
            
            this.initialized = false;
            this.isPlaying = false;
        } catch (err) {
            console.error("[ImageReader] dispose failed:", err);
        }
    }

    private showReadingRoot(): void {
        if (this.root) this.root.style.display = "block";
        const cinematic = document.getElementById(CINEMATIC_ROOT_ID);
        if (cinematic) cinematic.style.display = "none";
    }

    private async loadAndApplyVoiceStyle(styleId: string): Promise<void> {
        try {
            // TODO: 建立更通用的 style 路径映射
            const stylePath = `./books/styles/voice/${styleId}.json`;
            this.voiceStyle = await ProjectLoader.loadStyle(stylePath);
            this.applyVoiceStyleVars(this.voiceStyle);
        } catch (err) {
            console.warn(`[ImageReader] Failed to load voice style ${styleId}:`, err);
        }
    }

    private applyVoiceStyleVars(style: VoiceStyle): void {
        if (!this.root) return;
        const s = style.theme.light; // 默认使用 light，后续可扩展 dark mode 支持
        const rootStyle = this.root.style;

        // 设置 CSS 变量
        rootStyle.setProperty("--paper", s.paper);
        rootStyle.setProperty("--ink", s.ink);
        rootStyle.setProperty("--gray", s.gray);
        rootStyle.setProperty("--accent", s.accent);
        rootStyle.setProperty("--serif", style.theme.fontFamily);
        rootStyle.setProperty("--panel-w", style.size.panelWidth);
        
        // 应用布局与间距
        const container = this.root.querySelector<HTMLElement>(".reading-container");
        if (container) {
            container.style.padding = style.size.desktopPadding;
            container.style.fontFamily = style.theme.fontFamily;
            container.style.backgroundColor = s.paper;
            container.style.color = s.ink;
        }

        // 设置音频高亮颜色
        rootStyle.setProperty("--voice-highlight", style.audio.highlightColor);
    }

    private showPageCard(page: UnifiedPage): void {
        if (!this.root || !this.voiceStyle) return;

        if (!this.pageCardEl) {
            this.pageCardEl = document.createElement("div");
            this.pageCardEl.className = "voice-page-card";
            this.root.appendChild(this.pageCardEl);
        }

        const card = this.pageCardEl;
        card.innerHTML = `
            <div class="num">${page.page_id || ""}</div>
            <div class="ttl">${page.chapterTitle || page.title || ""}</div>
        `;
        
        card.style.top = this.voiceStyle.pagination.pageCardTop;
        card.classList.add("show");

        if (this.pageCardTimer) clearTimeout(this.pageCardTimer);
        this.pageCardTimer = setTimeout(() => {
            card.classList.remove("show");
            this.pageCardTimer = null;
        }, this.voiceStyle.pagination.pageCardHoldMs);
    }

    private renderPage(page: UnifiedPage): void {
        if (!this.root) return;

        // 样式应用
        this.applyStyles(page.style);

        // 3D 舞台模拟 (在 ImageReader 中我们只放一张背景图)
        const stageRoot = this.root.querySelector<HTMLElement>("#reading3d-stage-root");
        if (stageRoot) {
            stageRoot.style.backgroundColor = "transparent";
            let img = stageRoot.querySelector<HTMLImageElement>(".reading-image");
            if (!img) {
                img = document.createElement("img");
                img.className = "reading-image";
                img.style.width = "100%";
                img.style.height = "100%";
                img.style.objectFit = "cover";
                stageRoot.appendChild(img);
            }
            const imgSrc = this.resolveImageSrc(page);
            if (imgSrc) {
                img.src = imgSrc;
                this.applyCamera(img, page.camera);
            }
        }

        // 更新文本内容 (虽然 compileTemplate 已经处理了，但为了动态更新这里保留)
        const pageNum = page.page_id.replace(/^p/, "").replace(/^0+/, "") || "1";
        const title = page.chapterTitle || page.title || "";
        const longText = page.longText || "";

        const sealEl = this.root.querySelector(".reading3d-seal");
        if (sealEl) sealEl.textContent = pageNum;

        const titleEl = this.root.querySelector(".reading3d-title");
        if (titleEl) titleEl.textContent = title;

        const textEl = this.root.querySelector(".reading3d-text");
        if (textEl) textEl.textContent = longText;

        // 特效处理
        this.applyEffects(page.effects);

        // 进度条逻辑 (ImageReader 默认可能没有复杂的播放器 UI，这里保持简单更新)
        this.progressEl = this.root.querySelector<HTMLElement>(".reading3d-progress-bar");
    }

    private applyStyles(style?: string): void {
        const styleId = "reading-page-style";
        let styleEl = document.getElementById(styleId);
        if (style) {
            if (!styleEl) {
                styleEl = document.createElement("style");
                styleEl.id = styleId;
                document.head.appendChild(styleEl);
            }
            styleEl.textContent = style;
        } else if (styleEl) {
            styleEl.textContent = "";
        }
    }

    private applyCamera(img: HTMLImageElement, camera?: UnifiedPage["camera"]): void {
        if (!camera) {
            img.style.transform = "";
            return;
        }
        
        const { position, rotation, fov } = camera;
        let transform = "";
        
        // 1. 处理 Z (深度 -> 缩放)
        let scale = 1.0;
        if (fov) {
            scale *= (90 / fov);
        }
        if (position && position.z !== undefined) {
            // Blender Z 增加通常是相机后退，所以 scale 减小
            // 假设 0 是标准距离，正数是远离，负数是靠近
            scale *= Math.pow(1.1, -position.z);
        }
        if (scale !== 1.0) {
            transform += `scale(${scale.toFixed(3)}) `;
        }

        // 2. 处理 XY 位移 (Blender XY 坐标系与 CSS 不同，这里做简单映射)
        if (position) {
            const tx = position.x * 50; // 放大倍数以增强视觉效果
            const ty = -position.y * 50; // Blender Y 向上，CSS Y 向下
            transform += `translate(${tx.toFixed(1)}px, ${ty.toFixed(1)}px) `;
        }

        // 3. 处理旋转 (主要关注 Z 轴旋转，即平面旋转)
        if (rotation) {
            // Blender 使用弧度，这里假设导出的是角度；如果是弧度需转换
            const rz = rotation.z;
            transform += `rotate(${rz.toFixed(1)}deg) `;
        }

        img.style.transform = transform.trim();
        img.style.transition = "transform 0.5s ease-out"; // 添加平滑过渡
    }

    private applyEffects(effects?: UnifiedPage["effects"]): void {
        if (!effects || !this.root) return;
        effects.forEach(effect => {
            if (effect.type === "shake") {
                const intensity = effect.intensity || 5;
                const duration = (effect.duration || 0.5) * 1000;
                
                this.root?.animate([
                    { transform: `translate(-${intensity}px, 0px)` },
                    { transform: `translate(${intensity}px, 0px)` },
                    { transform: `translate(-${intensity}px, 0px)` }
                ], {
                    duration: 100,
                    iterations: duration / 100
                });
            } else if (effect.type === "fade-in") {
                const duration = (effect.duration || 1) * 1000;
                this.root?.animate([
                    { opacity: 0 },
                    { opacity: 1 }
                ], { duration });
            }
        });
    }

    private setupAudio(page: UnifiedPage): void {
        if (!this.root) return;
        const audio = this.root.querySelector<HTMLAudioElement>(".reading3d-audio");
        if (!audio) return;

        const src = this.resolveAudioSrc(page);
        if (!src) {
            audio.src = "";
            this.audio = audio;
            return;
        }
        audio.preload = "metadata";
        audio.src = src;
        audio.addEventListener("timeupdate", this.boundAudioTimeUpdate);
        audio.addEventListener("ended", this.boundAudioEnded);
        audio.addEventListener("loadedmetadata", this.boundAudioLoaded);
        this.audio = audio;
        this.updateProgress();
    }

    private updateProgress(): void {
        if (!this.progressEl || !this.audio) return;
        const a = this.audio;
        const cur = Number.isFinite(a.currentTime) ? a.currentTime : 0;
        const dur = Number.isFinite(a.duration) && a.duration > 0 ? a.duration : 0;
        const pct = dur > 0 ? Math.min(100, Math.max(0, (cur / dur) * 100)) : 0;
        this.progressEl.style.width = `${pct.toFixed(2)}%`;
        this.progressEl.textContent = `${this.formatTime(cur)} / ${this.formatTime(dur)}`;
    }

    private formatTime(sec: number): string {
        if (!Number.isFinite(sec) || sec <= 0) return "0:00";
        const m = Math.floor(sec / 60);
        const s = Math.floor(sec % 60);
        return `${m}:${s.toString().padStart(2, "0")}`;
    }

    private onAudioEnded(): void {
        this.isPlaying = false;
        const autoNext = this.currentPage?.autoNextOnEnded ?? this.manifest.autoNextOnEnded ?? (this.mode === "voice");
        if (autoNext) {
            this.onNextRequested?.();
        }
    }

    private resolveAssetBase(kind: "audio" | "image"): string {
        const dir = kind === "audio"
            ? (this.manifest.audioDir ?? "audio")
            : (this.manifest.imagesDir ?? "images");
        return this.joinBase(this.manifestBase, `../${dir}`);
    }

    private resolveAudioSrc(page: UnifiedPage): string | null {
        const candidates = [
            page.narrationAudio,
            page.audioFile,
            page.dialogue?.audio,
            page.dialogues?.[0]?.audio,
        ];
        for (const c of candidates) {
            if (c) return this.isAbsoluteOrRemote(c) ? c : this.joinBase(this.resolveAssetBase("audio"), c);
        }
        return null;
    }

    private resolveImageSrc(page: UnifiedPage): string | null {
        if (!page.image) return null;
        return this.isAbsoluteOrRemote(page.image) ? page.image : this.joinBase(this.resolveAssetBase("image"), page.image);
    }

    private isAbsoluteOrRemote(path?: string): boolean {
        if (!path) return false;
        return /^(https?:)?\/\//i.test(path) || path.startsWith("/") || path.startsWith("data:");
    }

    private joinBase(base: string, rel: string): string {
        if (this.isAbsoluteOrRemote(rel)) return rel;
        if (rel.startsWith("./")) rel = rel.slice(2);
        return `${base.replace(/\/+$/, "")}/${rel}`;
    }
}
