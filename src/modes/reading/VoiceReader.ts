import { ComicReader } from "@core/ComicReader";
import { Manifest, BookMode, UnifiedPage, ProjectLoader, VoiceStylePackage } from "@core/ProjectLoader";
import readingTemplateHtml from "@ui/reading/template.html?raw";
import "@ui/reading/reading.css";

const READING_ROOT_ID = "reading-root";
const CINEMATIC_ROOT_ID = "cinematic-root";

export class VoiceReader implements ComicReader {
    private manifest: Manifest;
    private manifestBase: string;
    public readonly mode: BookMode;
    private root: HTMLElement | null = null;
    private audio: HTMLAudioElement | null = null;
    private progressEl: HTMLElement | null = null;
    private isPlaying = false;
    private initialized = false;
    private currentPage: UnifiedPage | null = null;
    private stylePackage: VoiceStylePackage | null = null;
    private pageCardEl: HTMLElement | null = null;
    private pageCardTimer: any = null;

    public onNextRequested?: () => void;

    private boundAudioTimeUpdate = (): void => { this.updateProgress(); };
    private boundAudioEnded = (): void => { this.onAudioEnded(); };
    private boundAudioLoaded = (): void => { this.updateProgress(); };

    constructor(manifest: Manifest, mode: BookMode = "voice", manifestBase: string = "./book") {
        this.manifest = manifest;
        this.mode = mode;
        this.manifestBase = manifestBase;
    }

    async init(): Promise<void> {
        try {
            this.root = document.getElementById(READING_ROOT_ID);
            this.showReadingRoot();
            this.initialized = true;
        } catch (err) {
            console.error("[VoiceReader] init failed:", err);
        }
    }

    async loadPage(page: UnifiedPage, _pagePath: string): Promise<void> {
        try {
            this.currentPage = page;
            this.showReadingRoot();
            if (this.root) {
                if (!this.root.querySelector(".reading-container")) {
                    this.root.innerHTML = readingTemplateHtml;
                }
            }

            // 加载 Style Package
            if (page.style) {
                const stylePath = page.style.includes('/') ? page.style : `./books/styles/voice/${page.style}/package.json`;
                const loaded = await ProjectLoader.loadStyle(stylePath);
                if ((loaded as VoiceStylePackage).style) {
                    this.stylePackage = loaded as VoiceStylePackage;
                    this.applyStylePackage(this.stylePackage);
                }
            }

            this.renderPage(page);
            this.setupAudio(page);
            this.setupInteractions(page);
            
            if (this.stylePackage?.timeline?.pagination?.showPageCard) {
                this.showPageCard(page);
            }
        } catch (err) {
            console.error("[VoiceReader] loadPage failed:", err);
        }
    }

    async unloadPage(): Promise<void> {
        if (this.audio) {
            this.audio.pause();
            this.audio.removeEventListener("timeupdate", this.boundAudioTimeUpdate);
            this.audio.removeEventListener("ended", this.boundAudioEnded);
            this.audio.removeEventListener("loadedmetadata", this.boundAudioLoaded);
            this.audio = null;
        }
        this.isPlaying = false;
        this.currentPage = null;
    }

    play(): void {
        if (this.audio) {
            void this.audio.play();
            this.isPlaying = true;
        }
    }

    pause(): void {
        if (this.audio) {
            this.audio.pause();
            this.isPlaying = false;
        }
    }

    dispose(): void {
        void this.unloadPage();
        if (this.root) {
            this.root.innerHTML = "";
            this.root.style.display = "none";
        }
        this.initialized = false;
    }

    private showReadingRoot(): void {
        if (this.root) this.root.style.display = "block";
        const cinematic = document.getElementById(CINEMATIC_ROOT_ID);
        if (cinematic) cinematic.style.display = "none";
    }

    private applyStylePackage(pkg: VoiceStylePackage): void {
        if (!this.root) return;
        const rootStyle = this.root.style;
        const theme = pkg.style.theme.light;
        const layout = pkg.layout;
        const ui = pkg.ui;

        rootStyle.setProperty("--paper", theme.paper);
        rootStyle.setProperty("--ink", theme.ink);
        rootStyle.setProperty("--gray", theme.gray);
        rootStyle.setProperty("--accent", theme.accent);
        rootStyle.setProperty("--serif", pkg.style.theme.fontFamily);
        rootStyle.setProperty("--panel-w", layout.size.panelWidth);
        
        const container = this.root.querySelector<HTMLElement>(".reading-container");
        if (container) {
            container.style.padding = layout.size.desktopPadding;
            container.style.backgroundColor = theme.paper;
            container.style.color = theme.ink;
        }

        if (pkg.interaction?.feedback?.highlightColor) {
            rootStyle.setProperty("--voice-highlight", pkg.interaction.feedback.highlightColor);
        }

        // UI 可见性控制
        const progressWrap = this.root.querySelector<HTMLElement>(".reading-progress-wrap");
        if (progressWrap) {
            progressWrap.style.display = ui.components.progress.visible ? "block" : "none";
        }
    }

    private renderPage(page: UnifiedPage): void {
        if (!this.root) return;

        const img = this.root.querySelector<HTMLImageElement>(".reading-image");
        const imgSrc = this.resolveImageSrc(page);
        if (img && imgSrc) {
            img.src = imgSrc;
            this.applyCamera(img, page.camera);
        }

        const titleEl = this.root.querySelector<HTMLElement>(".reading-chapter-title");
        if (titleEl) titleEl.textContent = page.chapterTitle ?? page.title ?? "";

        const narrationEl = this.root.querySelector<HTMLElement>(".reading-narration-text");
        if (narrationEl) narrationEl.textContent = page.narration ?? "";

        const speakerEl = this.root.querySelector<HTMLElement>(".reading-speaker");
        const dialogueEl = this.root.querySelector<HTMLElement>(".reading-dialogue-text");
        const d = page.dialogues?.[0] ?? page.dialogue;
        if (speakerEl) speakerEl.textContent = d?.speaker ?? "";
        if (dialogueEl) dialogueEl.textContent = d?.text ?? "";

        this.progressEl = this.root.querySelector<HTMLElement>(".reading-progress");
    }

    private setupAudio(page: UnifiedPage): void {
        if (!this.root) return;
        const audio = this.root.querySelector<HTMLAudioElement>(".reading-audio");
        if (!audio) return;

        const src = this.resolveAudioSrc(page);
        if (src) {
            audio.src = src;
            
            // 应用 audio.json 设置
            if (this.stylePackage?.audio) {
                audio.volume = this.stylePackage.audio.defaultVolume || 1.0;
            }

            audio.addEventListener("timeupdate", this.boundAudioTimeUpdate);
            audio.addEventListener("ended", this.boundAudioEnded);
            audio.addEventListener("loadedmetadata", this.boundAudioLoaded);
            this.audio = audio;
            if (this.stylePackage?.timeline?.autoAdvance) {
                void audio.play();
                this.isPlaying = true;
            }
        }
    }

    private setupInteractions(page: UnifiedPage): void {
        if (!page.interaction || !this.root) return;
        
        const container = this.root.querySelector(".reading-container");
        if (!container) return;

        // 清除旧的交互
        const interactiveEls = container.querySelectorAll("[data-interactive]");
        interactiveEls.forEach(el => el.remove());

        page.interaction.forEach((inter: any) => {
            if (inter.target === "dog" || inter.target === "object") {
                const trigger = document.createElement("div");
                trigger.setAttribute("data-interactive", "true");
                trigger.style.position = "absolute";
                trigger.style.right = "10%";
                trigger.style.bottom = "20%";
                trigger.style.width = "100px";
                trigger.style.height = "100px";
                trigger.style.cursor = "pointer";
                trigger.style.zIndex = "10";
                
                trigger.addEventListener("click", () => {
                    console.log("[VoiceReader] Interaction triggered:", inter);
                    if (inter.action === "play_sound") {
                        const soundSrc = `./books/${this.manifest.bookTitle}/audio/effects/${inter.sound}.mp3`;
                        const sfx = new Audio(soundSrc);
                        void sfx.play();
                    }
                });
                
                container.appendChild(trigger);
            }
        });
    }

    private applyCamera(img: HTMLImageElement, camera?: UnifiedPage["camera"]): void {
        if (!camera) return;
        const { position, rotation, fov } = camera;
        let transform = "";
        if (fov) transform += `scale(${90/fov}) `;
        if (position) transform += `translate(${position.x * 20}px, ${-position.y * 20}px) `;
        if (rotation) transform += `rotate(${rotation.z}deg) `;
        img.style.transform = transform;
        img.style.transition = "transform 1.2s ease-in-out";
    }

    private showPageCard(page: UnifiedPage): void {
        if (!this.root || !this.stylePackage) return;
        const timeline = this.stylePackage.timeline;
        if (!this.pageCardEl) {
            this.pageCardEl = document.createElement("div");
            this.pageCardEl.className = "voice-page-card";
            this.root.appendChild(this.pageCardEl);
        }
        this.pageCardEl.innerHTML = `<div class="num">${page.page_id}</div><div class="ttl">${page.title}</div>`;
        this.pageCardEl.classList.add("show");
        if (this.pageCardTimer) clearTimeout(this.pageCardTimer);
        this.pageCardTimer = setTimeout(() => this.pageCardEl?.classList.remove("show"), timeline.pagination.pageCardHoldMs);
    }

    private updateProgress(): void {
        if (!this.progressEl || !this.audio) return;
        const cur = this.audio.currentTime;
        const dur = this.audio.duration;
        const pct = (cur / dur) * 100;
        this.progressEl.style.width = `${pct}%`;
    }

    private onAudioEnded(): void {
        if (this.stylePackage?.timeline?.autoAdvance) {
            this.onNextRequested?.();
        }
    }

    private resolveAudioSrc(page: UnifiedPage): string | null {
        const file = page.narrationAudio || page.audioFile;
        if (!file) return null;
        if (file.startsWith('http') || file.startsWith('/') || file.startsWith('data:')) return file;
        
        // 保持相对路径结构
        return `./books/${this.manifest.bookTitle}/${file}`;
    }

    private resolveImageSrc(page: UnifiedPage): string | null {
        if (!page.image) return null;
        if (page.image.startsWith('http') || page.image.startsWith('/') || page.image.startsWith('data:')) return page.image;
        
        return `./books/${this.manifest.bookTitle}/${page.image}`;
    }
}
