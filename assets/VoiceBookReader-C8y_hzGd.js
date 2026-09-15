import{Reading3DReader as l}from"./Reading3DReader-Np4qxaMX.js";import"./CinematicRuntimeAdapter-JKXjqv6w.js";const d=`<div class="voice-player-widget">
    <div class="voice-progress-container">
        <div class="voice-progress-bar"></div>
    </div>
    <div class="voice-player-controls">
        <button class="voice-btn btn-prev-cue" title="Previous Cue">⏮</button>
        <button class="voice-btn btn-voice-play-pause" title="Play/Pause">
            <span class="icon">▶</span>
        </button>
        <button class="voice-btn btn-next-cue" title="Next Cue">⏭</button>
        <div class="voice-time-display">0:00 / 0:00</div>
    </div>
</div>
`,u=`<!-- 上半区：3D 视口容器 -->
<div class="reading3d-stage">
    <!-- Needle Engine 画布将挂载到这里 -->
    <div id="reading3d-stage-root" style="width: 100%; height: 100%;"></div>
    
    <!-- 右上角悬浮按钮组 (3D 演示区悬浮) -->
    <div class="reading3d-toolbar">
        <button class="reading3d-tool-btn btn-music" title="Music">🎵</button>
        <button class="reading3d-tool-btn btn-visible" title="Visibility">👁️</button>
        <button class="reading3d-tool-btn btn-camera" title="Reset Camera">📷</button>
        <button class="reading3d-tool-btn btn-fullscreen" title="Fullscreen">⛶</button>
    </div>
</div>

<!-- 下半区：滚动文本阅读面板 -->
<div class="reading3d-panel">
    <!-- 导航与工具栏 -->
    <div class="reading3d-nav-bar">
        <button class="reading3d-btn btn-contents">‹ Contents</button>
        <button class="reading3d-btn btn-prev">‹</button>
        <button class="reading3d-btn btn-next">›</button>
        
        <div class="spacer"></div>
        
        <!-- 主题切换按钮 (循环切换：浅色/暗色/纸感) -->
        <button class="reading3d-btn btn-theme" title="Switch Theme">☀️</button>
        <!-- Sit 沉浸模式按钮 -->
        <button class="reading3d-btn btn-sit">Sit</button>
    </div>

    <!-- 标题区块 -->
    <div class="reading3d-head">
        <div class="reading3d-seal">{{pageNumber}}</div>
        <h2 class="reading3d-title">{{pageTitle}}</h2>
    </div>

    <!-- 播放器区域 (VoiceBookReader 会注入播放器 UI) -->
    <div class="reading3d-read-aloud">
        <!-- 默认显示 Read aloud 按钮，初始化后被替换为完整播放器 -->
        <button class="reading3d-btn btn-read-aloud">
            <span style="margin-right: 8px;">▶</span> Read aloud
        </button>
    </div>

    <!-- 正文区域 -->
    <div class="reading3d-section">
        <div class="reading3d-section-label">
            <span class="label-text">{{sectionLabel}}</span>
            <span class="reading3d-speak-btn" title="Play Segment">♫</span>
        </div>
        <div class="reading3d-text-container">
            <!-- 文字内容会按段落渲染，以便插入音符按钮 -->
            <div class="reading3d-text">{{longText}}</div>
        </div>
    </div>
</div>

<!-- 隐藏的音频元素 -->
<audio class="reading3d-audio"></audio>
`;class m extends l{constructor(){super(...arguments),this.mode="voice",this.cues=[],this.bgmAudio=null,this.themeData=null,this.currentTheme="light"}async init(){await super.init(),this.injectVoicePlayer(),await this.loadVoiceCues(),this.setupBGM(),this.bindVoiceEvents(),await this.initVoiceTheme()}injectTemplate(){this.root&&(this.root.innerHTML=u)}async initVoiceTheme(){const e=this.joinBase(this.manifestBase,"../styles/voice-theme.json");try{const t=await fetch(e);t.ok&&(this.themeData=await t.json(),this.applyVoiceTheme("paper"))}catch{console.warn("[VoiceBookReader] voice-theme.json not found, using defaults")}}applyVoiceTheme(e){if(this.currentTheme=e,this.themeData)this.applyReadingTheme(this.themeData,e);else{const o=document.documentElement;e==="dark"?(o.style.setProperty("--paper","#17171B"),o.style.setProperty("--ink","#E9E3D5")):e==="paper"?(o.style.setProperty("--paper","#f4ecd8"),o.style.setProperty("--ink","#2b2b2b")):(o.style.setProperty("--paper","#F3EDDF"),o.style.setProperty("--ink","#1E1E24"))}const t=this.root?.querySelector(".reading3d-panel"),i=this.root?.querySelector(".btn-theme");if(t&&(t.classList.remove("light","dark","paper"),t.classList.add(e)),i){const o={light:"☀️",dark:"🌙",paper:"📜"};i.textContent=o[e]}}bindEvents(){super.bindEvents(),this.root&&(this.root.querySelector(".btn-theme")?.addEventListener("click",e=>{e.stopPropagation();const t=["light","dark","paper"],i=(t.indexOf(this.currentTheme)+1)%t.length;this.applyVoiceTheme(t[i])}),this.root.querySelector(".btn-sit")?.addEventListener("click",()=>{const e=this.root?.querySelector(".reading3d-panel");if(e){const t=e.classList.toggle("hidden"),i=this.root?.querySelector(".reading3d-stage");i&&(i.style.height=t?"100%":"48%")}}),this.root.querySelector(".reading3d-speak-btn")?.addEventListener("click",()=>{const e=this.root?.querySelector(".reading3d-audio");e&&(e.currentTime=0,e.play())}))}setupBGM(){if(!this.manifest.bgm)return;const e=this.resolveBgmSrc(this.manifest.bgm);e&&(this.bgmAudio=new Audio(e),this.bgmAudio.loop=!0,this.bgmAudio.volume=.3)}resolveBgmSrc(e){if(this.isAbsoluteOrRemote(e))return e;const t=this.manifest.audioDir??"audio",i=e.startsWith(t+"/")?e:`../${t}/${e}`;return this.joinBase(this.manifestBase,i)}injectVoicePlayer(){if(!this.root)return;const e=this.root.querySelector(".reading3d-read-aloud");e&&(e.innerHTML=d)}bindVoiceEvents(){if(!this.root)return;const e=this.root.querySelector(".reading3d-audio");if(!e)return;const t=this.root.querySelector(".btn-voice-play-pause"),i=this.root.querySelector(".voice-progress-bar"),o=this.root.querySelector(".voice-progress-container"),a=this.root.querySelector(".voice-time-display");t?.addEventListener("click",()=>{e.paused?(e.play().catch(s=>console.warn("[VoiceBookReader] Play failed:",s)),this.bgmAudio?.play().catch(s=>console.warn("[VoiceBookReader] BGM Play failed:",s))):(e.pause(),this.bgmAudio?.pause())}),e.addEventListener("play",()=>{t&&(t.querySelector(".icon").textContent="⏸"),this.bgmAudio?.play().catch(s=>console.warn("[VoiceBookReader] BGM Play failed:",s))}),e.addEventListener("pause",()=>{t&&(t.querySelector(".icon").textContent="▶"),this.bgmAudio?.pause()}),e.addEventListener("timeupdate",()=>{const s=e.currentTime;if(i&&e.duration){const r=s/e.duration*100;i.style.width=`${r}%`}a&&(a.textContent=`${this.formatTime(s)} / ${this.formatTime(e.duration||0)}`);const n=this.getActiveCue(s);n&&this.adapter&&(typeof this.adapter.gotoFrame=="function"?this.adapter.gotoFrame(n.frame):typeof this.adapter.playClip=="function"&&n.name&&this.adapter.playClip(n.name),n.camera&&typeof this.adapter.setCamera=="function"&&this.adapter.setCamera(n.camera)),this.syncTextScroll(s)}),o?.addEventListener("click",s=>{const n=o.getBoundingClientRect(),c=(s.clientX-n.left)/n.width;e.duration&&(e.currentTime=c*e.duration)}),this.root.querySelector(".btn-prev-cue")?.addEventListener("click",()=>{const s=e.currentTime,n=[...this.cues].reverse().find(r=>r.start<s-.5);n?e.currentTime=n.start:e.currentTime=0}),this.root.querySelector(".btn-next-cue")?.addEventListener("click",()=>{const s=e.currentTime,n=this.cues.find(r=>r.start>s);n&&(e.currentTime=n.start)})}syncTextScroll(e){if(!this.root||this.cues.length===0)return;const t=this.root.querySelector(".reading3d-panel");if(!t)return;const i=this.root.querySelector(".reading3d-audio");if(i&&i.duration){const o=e/i.duration,a=t.scrollHeight-t.clientHeight;t.scrollTop=a*o}}formatTime(e){const t=Math.floor(e/60),i=Math.floor(e%60);return`${t}:${i.toString().padStart(2,"0")}`}async loadVoiceCues(){try{const e=`${this.manifestBase}/pages/voice_cues.json`,t=await fetch(e);if(t.ok){const i=await t.json();this.cues=i.cues??[]}}catch(e){console.warn("[VoiceBookReader] voice_cues.json load failed",e),this.cues=[]}}renderPage(e){super.renderPage(e);const t=e.labels?.section||"THE CASE",i=this.root?.querySelector(".reading3d-section-label");i&&(i.innerHTML=`<span class="label-text">${t}</span>`);const o=this.root?.querySelector(".reading3d-text");if(o&&e.longText){const s=e.longText.split(`
`).filter(n=>n.trim());o.innerHTML=s.map((n,r)=>`
                <div class="paragraph-wrap" style="display:flex; align-items: flex-start; gap: 10px; margin-bottom: 12px;">
                    <span class="segment-note" data-index="${r}" style="cursor:pointer; color:var(--accent); font-size: 1.2em;">♫</span>
                    <p style="margin:0;">${n}</p>
                </div>
            `).join(""),o.querySelectorAll(".segment-note").forEach(n=>{n.addEventListener("click",r=>{const c=parseInt(r.target.dataset.index||"0");this.jumpToParagraph(c)})})}const a=this.root?.querySelector("#reading3d-stage-root");if(a){const s=this.resolveImageSrc(e);if(s){let n=a.querySelector(".reading3d-scene-image");n||(n=document.createElement("img"),n.className="reading3d-scene-image",n.style.cssText="width:100%;height:100%;object-fit:cover;position:absolute;top:0;left:0;z-index:1;",a.appendChild(n)),n.src=s,n.style.display="block"}}}jumpToParagraph(e){if(this.cues.length>e){const t=this.root?.querySelector(".reading3d-audio");t&&(t.currentTime=this.cues[e].start,t.play())}}resolveImageSrc(e){if(!e.image)return null;if(this.isAbsoluteOrRemote(e.image))return e.image;const t=this.manifest.imagesDir??"images";return this.joinBase(this.manifestBase,`../${t}/${e.image}`)}async loadPage(e,t){try{if(this.currentPage=e,this.showReadingRoot(),this.renderPage(e),this.setupAudio(e),this.adapter){const i=e.model?.glb??"scene.glb",o=t.replace(/\.json$/,""),a=this.isAbsoluteOrRemote(i)?i:`${o}/${i}`;try{await this.adapter.loadPage(e,a)}catch(s){console.warn("[VoiceBookReader] GLB load failed, but continuing for voice:",s)}}}catch(i){console.error("[VoiceBookReader] loadPage failed:",i)}setTimeout(()=>{window.dispatchEvent(new Event("resize"))},100)}resolveAudioSrc(e){const t=e.narrationAudio||e.audioFile||e.dialogue?.audio;if(!t)return null;if(["chime.mp3","k1_case.mp3","k1_comment.mp3","k1_verse.mp3"].includes(t))return console.warn(`[VoiceBookReader] Skipping 0-byte audio file: ${t}`),null;if(this.isAbsoluteOrRemote(t))return t;const o=this.manifest.audioDir??"audio";return this.joinBase(this.manifestBase,`../${o}/${t}`)}getActiveCue(e){return this.cues.find(t=>e>=t.start&&e<t.end)??null}play(){super.play(),this.bgmAudio?.play().catch(e=>console.warn("[VoiceBookReader] BGM Play failed:",e))}pause(){super.pause(),this.bgmAudio?.pause()}dispose(){super.dispose(),this.cues.length=0,this.bgmAudio&&(this.bgmAudio.pause(),this.bgmAudio.src="",this.bgmAudio=null),this.root&&this.root.classList.remove("reading3d-layout")}}export{m as VoiceBookReader};
