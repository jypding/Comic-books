import { UnifiedPage, Manifest } from "@core/ProjectLoader";
import { Reading3DReader } from "../reading/Reading3DReader";
import voicePlayerTemplate from "@ui/voice/voice-player.template.html?raw";
import voiceReaderTemplate from "@ui/voice/voice-reader.template.html?raw";

const READING_ROOT_ID = "reading-root";

export class VoiceBookReader extends Reading3DReader {
    public override readonly mode: string = "voice";
    protected cues: Array<{start:number;end:number;time:number;name:string;frame:number}> = [];
    private bgmAudio: HTMLAudioElement | null = null;
    private themeData: any = null;
    private currentTheme: "light" | "dark" | "paper" = "light";

    /**
     * 直接复用 Reading3DReader 的初始化逻辑
     * 仅在此基础上增加语音提示点 (Voice Cues) 加载和播放器 UI
     */
    async init(): Promise<void> {
        // 1. 调用父类初始化，完成布局注入、3D 适配器初始化和事件绑定
        await super.init();

        // 2. 注入 Voice 专用播放器 UI 到 Reading 面板中
        this.injectVoicePlayer();

        // 3. 加载语音同步数据
        await this.loadVoiceCues();
        
        // 4. 初始化 BGM (如果 manifest 中定义了)
        this.setupBGM();

        // 5. 绑定音频同步与播放器 UI 事件
        this.bindVoiceEvents();

        // 6. 处理书籍包主题
        await this.initVoiceTheme();
    }

    protected override injectTemplate(): void {
        if (this.root) {
            this.root.innerHTML = voiceReaderTemplate;
        }
    }

    private async initVoiceTheme() {
        const themeUrl = this.joinBase(this.manifestBase, "../styles/voice-theme.json");
        try {
            const res = await fetch(themeUrl);
            if (res.ok) {
                this.themeData = await res.json();
                // 默认应用 light 主题
                this.applyVoiceTheme("light");
            }
        } catch (e) {
            console.warn("[VoiceBookReader] voice-theme.json not found, using defaults");
        }
    }

    private applyVoiceTheme(theme: "light" | "dark" | "paper") {
        this.currentTheme = theme;
        if (this.themeData) {
            this.applyReadingTheme(this.themeData, theme);
        } else {
            // 回退到默认样式处理
            const root = document.documentElement;
            if (theme === "dark") {
                root.style.setProperty("--paper", "#17171B");
                root.style.setProperty("--ink", "#E9E3D5");
            } else if (theme === "paper") {
                root.style.setProperty("--paper", "#f4ecd8");
                root.style.setProperty("--ink", "#2b2b2b");
            } else {
                root.style.setProperty("--paper", "#F3EDDF");
                root.style.setProperty("--ink", "#1E1E24");
            }
        }
        
        // 更新 UI 状态
        const panel = this.root?.querySelector(".reading3d-panel");
        const themeBtn = this.root?.querySelector(".btn-theme");
        
        if (panel) {
            panel.classList.remove("light", "dark", "paper");
            panel.classList.add(theme);
        }

        if (themeBtn) {
            const icons = { light: "☀️", dark: "🌙", paper: "📜" };
            themeBtn.textContent = icons[theme];
        }
    }

    protected override bindEvents(): void {
        super.bindEvents();
        if (!this.root) return;

        // 主题切换循环
        this.root.querySelector(".btn-theme")?.addEventListener("click", (e) => {
            e.stopPropagation(); // 阻止冒泡到父类的事件
            const themeOrder: Array<"light" | "dark" | "paper"> = ["light", "dark", "paper"];
            const nextIndex = (themeOrder.indexOf(this.currentTheme) + 1) % themeOrder.length;
            this.applyVoiceTheme(themeOrder[nextIndex]);
        });

        // 重新绑定 Sit 按钮 (覆盖父类简单切换)
        this.root.querySelector(".btn-sit")?.addEventListener("click", () => {
            const panel = this.root?.querySelector(".reading3d-panel");
            if (panel) {
                const isHidden = panel.classList.toggle("hidden");
                // 同步更新 3D 视口高度
                const stage = this.root?.querySelector(".reading3d-stage") as HTMLElement;
                if (stage) {
                    stage.style.height = isHidden ? "100%" : "48%";
                }
            }
        });

        // 段落音频跳转
        this.root.querySelector(".reading3d-speak-btn")?.addEventListener("click", () => {
            const audioEl = this.root?.querySelector<HTMLAudioElement>(".reading3d-audio");
            if (audioEl) {
                audioEl.currentTime = 0;
                audioEl.play();
            }
        });
    }

    protected setupBGM(): void {
        if (!this.manifest.bgm) return;

        const bgmSrc = this.resolveBgmSrc(this.manifest.bgm);
        if (!bgmSrc) return;

        this.bgmAudio = new Audio(bgmSrc);
        this.bgmAudio.loop = true;
        this.bgmAudio.volume = 0.3; // 默认较低音量作为背景
        
    }

    protected resolveBgmSrc(bgm: string): string | null {
        if (this.isAbsoluteOrRemote(bgm)) return bgm;
        // 对齐到 books/<项目>/audio/
        // 如果 bgm 路径包含 "audio/"，则直接拼接；否则补齐 audioDir
        const audioDir = this.manifest.audioDir ?? "audio";
        const relPath = bgm.startsWith(audioDir + "/") ? bgm : `../${audioDir}/${bgm}`;
        const path = this.joinBase(this.manifestBase, relPath);
        return path;
    }

    protected injectVoicePlayer(): void {
        if (!this.root) return;
        const readAloudContainer = this.root.querySelector(".reading3d-read-aloud");
        if (readAloudContainer) {
            // 清空原有的简单播放按钮，换成复杂的播放器组件
            readAloudContainer.innerHTML = voicePlayerTemplate;
        }
    }

    protected bindVoiceEvents(): void {
        if (!this.root) return;
        const audioEl = this.root.querySelector<HTMLAudioElement>(".reading3d-audio");
        if (!audioEl) return;

        const playPauseBtn = this.root.querySelector(".btn-voice-play-pause");
        const progressBar = this.root.querySelector(".voice-progress-bar") as HTMLElement;
        const progressContainer = this.root.querySelector(".voice-progress-container") as HTMLElement;
        const timeDisplay = this.root.querySelector(".voice-time-display");

        // 播放/暂停
        playPauseBtn?.addEventListener("click", () => {
            if (audioEl.paused) {
                audioEl.play().catch(e => console.warn("[VoiceBookReader] Play failed:", e));
                this.bgmAudio?.play().catch(e => console.warn("[VoiceBookReader] BGM Play failed:", e));
            } else {
                audioEl.pause();
                this.bgmAudio?.pause();
            }
        });

        audioEl.addEventListener("play", () => {
            if (playPauseBtn) playPauseBtn.querySelector(".icon")!.textContent = "⏸";
            this.bgmAudio?.play().catch(e => console.warn("[VoiceBookReader] BGM Play failed:", e));
        });

        audioEl.addEventListener("pause", () => {
            if (playPauseBtn) playPauseBtn.querySelector(".icon")!.textContent = "▶";
            this.bgmAudio?.pause();
        });

        // 进度更新
        audioEl.addEventListener("timeupdate", () => {
            const currentTime = audioEl.currentTime;

            // 更新进度条
            if (progressBar && audioEl.duration) {
                const percent = (currentTime / audioEl.duration) * 100;
                progressBar.style.width = `${percent}%`;
            }

            // 更新时间显示
            if (timeDisplay) {
                timeDisplay.textContent = `${this.formatTime(currentTime)} / ${this.formatTime(audioEl.duration || 0)}`;
            }

            // 同步 3D 场景与相机
            const cue = this.getActiveCue(currentTime);
            if (cue && this.adapter) {
                // 1. 同步动画帧
                if (typeof (this.adapter as any).gotoFrame === "function") {
                    (this.adapter as any).gotoFrame(cue.frame);
                } else if (typeof (this.adapter as any).playClip === "function" && cue.name) {
                    (this.adapter as any).playClip(cue.name);
                }

                // 2. 自动机位切换 (如果 cue 中定义了相机位置或视角名)
                if ((cue as any).camera && typeof (this.adapter as any).setCamera === "function") {
                    (this.adapter as any).setCamera((cue as any).camera);
                }
            }

            // 文本同步滚动
            this.syncTextScroll(currentTime);
        });

        // 点击进度条跳转
        progressContainer?.addEventListener("click", (e) => {
            const rect = progressContainer.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const percent = x / rect.width;
            if (audioEl.duration) {
                audioEl.currentTime = percent * audioEl.duration;
            }
        });

        // 上一个/下一个提示点
        this.root.querySelector(".btn-prev-cue")?.addEventListener("click", () => {
            const current = audioEl.currentTime;
            const prevCue = [...this.cues].reverse().find(c => c.start < current - 0.5);
            if (prevCue) audioEl.currentTime = prevCue.start;
            else audioEl.currentTime = 0;
        });

        this.root.querySelector(".btn-next-cue")?.addEventListener("click", () => {
            const current = audioEl.currentTime;
            const nextCue = this.cues.find(c => c.start > current);
            if (nextCue) audioEl.currentTime = nextCue.start;
        });
    }

    private syncTextScroll(currentTime: number) {
        if (!this.root || this.cues.length === 0) return;
        const textPanel = this.root.querySelector(".reading3d-panel");
        if (!textPanel) return;

        // 根据时间点找到对应的段落索引 (简单实现：按比例滚动)
        const audioEl = this.root.querySelector<HTMLAudioElement>(".reading3d-audio");
        if (audioEl && audioEl.duration) {
            const progress = currentTime / audioEl.duration;
            const scrollHeight = textPanel.scrollHeight - textPanel.clientHeight;
            textPanel.scrollTop = scrollHeight * progress;
        }
    }

    protected formatTime(seconds: number): string {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, "0")}`;
    }

    protected async loadVoiceCues() {
        try {
            const cuesUrl = `${this.manifestBase}/pages/voice_cues.json`;
            const res = await fetch(cuesUrl);
            if (res.ok) {
                const data = await res.json();
                this.cues = data.cues ?? [];
            }
        } catch (err) {
            console.warn("[VoiceBookReader] voice_cues.json load failed", err);
            this.cues = [];
        }
    }

    /** 复用父类的渲染逻辑，并处理段落音符按钮 */
    protected override renderPage(page: UnifiedPage): void {
        super.renderPage(page);

        // 修复 voice 模板标签重复问题：直接用页面数据覆盖整个 section-label
        const sectionLabel = (page as any).labels?.section || "THE CASE";
        const sectionLabelEl = this.root?.querySelector<HTMLElement>(".reading3d-section-label");
        if (sectionLabelEl) {
            sectionLabelEl.innerHTML = `<span class="label-text">${sectionLabel}</span>`;
        }

        // 处理段落音符按钮
        const textEl = this.root?.querySelector(".reading3d-text");
        if (textEl && page.longText) {
            const paragraphs = page.longText.split("\n").filter(p => p.trim());
            textEl.innerHTML = paragraphs.map((p, idx) => `
                <div class="paragraph-wrap" style="display:flex; align-items: flex-start; gap: 10px; margin-bottom: 12px;">
                    <span class="segment-note" data-index="${idx}" style="cursor:pointer; color:var(--accent); font-size: 1.2em;">♫</span>
                    <p style="margin:0;">${p}</p>
                </div>
            `).join("");

            // 绑定音符点击事件
            textEl.querySelectorAll(".segment-note").forEach(note => {
                note.addEventListener("click", (e) => {
                    const idx = parseInt((e.target as HTMLElement).dataset.index || "0");
                    this.jumpToParagraph(idx);
                });
            });
        }

        // 如果没有 3D 适配器或者 3D 加载失败，尝试显示图片场景
        const stageRoot = this.root?.querySelector<HTMLElement>("#reading3d-stage-root");
        if (stageRoot) {
            const imgSrc = this.resolveImageSrc(page);
            if (imgSrc) {
                let img = stageRoot.querySelector<HTMLImageElement>(".reading3d-scene-image");
                if (!img) {
                    img = document.createElement("img");
                    img.className = "reading3d-scene-image";
                    img.style.cssText = "width:100%;height:100%;object-fit:cover;position:absolute;top:0;left:0;z-index:1;";
                    stageRoot.appendChild(img);
                }
                img.src = imgSrc;
                img.style.display = "block";
            }
        }
    }

    private jumpToParagraph(index: number) {
        if (this.cues.length > index) {
            const audioEl = this.root?.querySelector<HTMLAudioElement>(".reading3d-audio");
            if (audioEl) {
                audioEl.currentTime = this.cues[index].start;
                audioEl.play();
            }
        }
    }

    protected resolveImageSrc(page: UnifiedPage): string | null {
        if (!page.image) return null;
        if (this.isAbsoluteOrRemote(page.image)) return page.image;
        
        // 对齐到 books/<项目>/images/
        const imagesDir = this.manifest.imagesDir ?? "images";
        const path = this.joinBase(this.manifestBase, `../${imagesDir}/${page.image}`);
        return path;
    }

    /**
     * 覆盖父类的 loadPage，增加对 GLB 加载失败的容错，确保 UI 仍然显示
     */
    public override async loadPage(page: UnifiedPage, pagePath: string): Promise<void> {
        try {
            this.currentPage = page;
            this.showReadingRoot();
            this.renderPage(page);

            // 1. 设置音频 (优先于 3D)
            this.setupAudio(page);

            // 2. 加载 3D 模型 (GLB 与 page.json 同目录: pages/<page>/scene.glb)
            if (this.adapter) {
                const glbName = page.model?.glb ?? "scene.glb";
                // 以 pagePath 所在目录为基准拼接 (与 Reading3DReader 一致)
                const pageDirUrl = pagePath.replace(/\.json$/, "");
                const glbUrl = this.isAbsoluteOrRemote(glbName)
                    ? glbName
                    : `${pageDirUrl}/${glbName}`;
                try {
                    await this.adapter.loadPage(page as any, glbUrl);
                } catch (err) {
                    console.warn("[VoiceBookReader] GLB load failed, but continuing for voice:", err);
                }
            }
        } catch (err) {
            console.error("[VoiceBookReader] loadPage failed:", err);
            // 这里不抛出，尽量保持 UI 可见
        }

        setTimeout(() => {
            window.dispatchEvent(new Event('resize'));
        }, 100);
    }

    /**
     * 确保音频路径解析正确对齐到 books/mp3/audio/
     */
    protected override resolveAudioSrc(page: UnifiedPage): string | null {
        // 优先使用 narrationAudio (p001.json 中定义)
        const file = page.narrationAudio || page.audioFile || page.dialogue?.audio;
        if (!file) return null;
        
        // 暂时跳过 0 字节的占位音频文件
        const zeroByteAudioFiles = ["chime.mp3", "k1_case.mp3", "k1_comment.mp3", "k1_verse.mp3"];
        if (zeroByteAudioFiles.includes(file)) {
            console.warn(`[VoiceBookReader] Skipping 0-byte audio file: ${file}`);
            return null;
        }

        if (this.isAbsoluteOrRemote(file)) return file;
        
        // 逻辑：如果 manifestBase 是 /books/mp3/book，音频在 /books/mp3/audio
        // 则相对于 manifestBase 的路径是 ../audio/file
        const audioDir = this.manifest.audioDir ?? "audio";
        const path = this.joinBase(this.manifestBase, `../${audioDir}/${file}`);
        return path;
    }

    public getActiveCue(currentTime: number) {
        return this.cues.find(c => currentTime >= c.start && currentTime < c.end) ?? null;
    }

    public override play(): void {
        super.play();
        this.bgmAudio?.play().catch(e => console.warn("[VoiceBookReader] BGM Play failed:", e));
    }

    public override pause(): void {
        super.pause();
        this.bgmAudio?.pause();
    }

    public override dispose(): void {
        super.dispose();
        this.cues.length = 0;
        if (this.bgmAudio) {
            this.bgmAudio.pause();
            this.bgmAudio.src = "";
            this.bgmAudio = null;
        }
        if (this.root) {
            this.root.classList.remove("reading3d-layout");
        }
    }
}
