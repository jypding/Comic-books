import{C as m}from"./CinematicRuntimeAdapter-JKXjqv6w.js";const y=`<!-- 上半区：3D 视口容器 -->
<div class="reading3d-stage">
    <!-- Needle Engine 画布将挂载到这里，ID 改为专门的容器 ID -->
    <div id="reading3d-stage-root" style="width: 100%; height: 100%;"></div>
    
    <!-- 右上角悬浮按钮组 -->
    <div class="reading3d-toolbar">
        <button class="reading3d-tool-btn btn-music" title="Music">🎵</button>
        <button class="reading3d-tool-btn btn-visible" title="Visibility">👁️</button>
        <button class="reading3d-tool-btn btn-camera" title="Reset Camera">📷</button>
        <button class="reading3d-tool-btn btn-fullscreen" title="Fullscreen">⛶</button>
    </div>
</div>

<!-- 下半区：滚动文本阅读面板 -->
<div class="reading3d-panel">
    <!-- 导航按钮行 -->
    <div class="reading3d-nav-bar">
        <button class="reading3d-btn btn-contents">‹ Contents</button>
        <button class="reading3d-btn btn-prev">‹</button>
        <button class="reading3d-btn btn-next">›</button>
        
        <div class="spacer"></div>
        
        <button class="reading3d-btn btn-theme" title="Dark Mode">🌙</button>
        <button class="reading3d-btn btn-sit">Sit</button>
    </div>

    <!-- 标题区块 -->
    <div class="reading3d-head">
        <div class="reading3d-seal">{{pageNumber}}</div>
        <h2 class="reading3d-title">{{pageTitle}}</h2>
    </div>

    <!-- Read aloud 按钮 -->
    <div class="reading3d-read-aloud">
        <button class="reading3d-btn btn-read-aloud">
            <span style="margin-right: 8px;">▶</span> Read aloud
        </button>
    </div>

    <!-- 章节标签与正文 -->
    <div class="reading3d-section">
        <div class="reading3d-section-label">
            {{sectionLabel}}
            <span class="reading3d-speak-btn">🔊</span>
        </div>
        <div class="reading3d-text">{{longText}}</div>
    </div>
</div>

<!-- 隐藏的音频元素 -->
<audio class="reading3d-audio"></audio>
`,g="reading-root",f="cinematic-root";class R{constructor(t,e="./book"){this.mode="reading",this.root=null,this.adapter=null,this.currentPage=null,this.initialized=!1,this.audio=null,this.readingStyleTag=null,this.manifest=t,this.manifestBase=e}async init(){try{if(this.root=document.getElementById(g),this.showReadingRoot(),!this.root)throw new Error(`#${g} not found`);await this.loadReadingStyles(),this.root.classList.add("reading3d-layout"),this.injectTemplate();const t=this.root.querySelector("#reading3d-stage-root");t&&(this.adapter=new m(t),await this.adapter.init()),this.bindEvents(),this.initialized=!0}catch(t){throw console.error("[Reading3DReader] init failed:",t),t}}injectTemplate(){this.root&&(this.root.innerHTML=y)}async loadReadingStyles(){const t=this.mode==="voice"?"voice-theme.json":"reading-theme.json",e=this.joinBase(this.manifestBase,`../styles/${t}`);try{const n=await fetch(e);if(n.ok){const o=await n.json();this.applyReadingTheme(o)}}catch(n){console.warn(`[Reading3DReader] Failed to load ${t}`,n)}const i=this.mode==="voice"?"voice-book.css":"reading-book.css",s=this.joinBase(this.manifestBase,`../styles/${i}`);try{const n=await fetch(s);if(n.ok){const o=await n.text();this.readingStyleTag||(this.readingStyleTag=document.createElement("style"),this.readingStyleTag.id="reading-book-dynamic-css",document.head.appendChild(this.readingStyleTag)),this.readingStyleTag.textContent=o}}catch(n){console.warn(`[Reading3DReader] Failed to load ${i}`,n)}}applyReadingTheme(t,e="light"){const i=document.documentElement,s=t.theme?.[e]||t.theme?.light;s&&Object.entries(s).forEach(([n,o])=>{i.style.setProperty(`--${n}`,o)}),t.theme?.["font-serif"]&&i.style.setProperty("--serif",t.theme["font-serif"]),t.theme?.["font-sans"]&&i.style.setProperty("--sans",t.theme["font-sans"])}async loadPage(t,e){try{if(!this.adapter)throw new Error("adapter not initialized");this.currentPage=t,this.showReadingRoot(),this.renderPage(t);const i=t.model?.glb??"scene.glb",s=e.replace(/\.json$/,""),n=this.isAbsoluteOrRemote(i)?i:`${s}/${i}`;await this.adapter.loadPage(t,n),this.setupAudio(t)}catch(i){throw console.error("[Reading3DReader] loadPage failed:",i),i}}async unloadPage(){this.adapter&&await this.adapter.unloadPage(),this.audio&&(this.audio.pause(),this.audio.src="",this.audio=null),this.currentPage=null}play(){this.adapter?.play(),this.audio&&this.audio.play()}pause(){this.adapter?.pause(),this.audio&&this.audio.pause()}dispose(){try{this.adapter?.dispose(),this.adapter=null,this.root&&(this.root.innerHTML="",this.root.style.display="none"),this.initialized=!1,this.currentPage=null}catch(t){console.error("[Reading3DReader] dispose failed:",t)}}showReadingRoot(){this.root&&(this.root.style.display="block");const t=document.getElementById(f);t&&(t.style.display="none")}bindEvents(){this.root&&(this.root.querySelector(".btn-prev")?.addEventListener("click",()=>this.onPrevRequested?.()),this.root.querySelector(".btn-next")?.addEventListener("click",()=>this.onNextRequested?.()),this.root.querySelector(".btn-contents")?.addEventListener("click",()=>{window.location.search=""}),this.root.querySelector(".btn-theme")?.addEventListener("click",()=>{const e=this.root?.querySelector(".reading3d-panel")?.classList.toggle("dark"),i=this.root?.querySelector(".btn-theme");i&&(i.textContent=e?"☼":"🌙"),this.onToggleTheme?.()}),this.root.querySelector(".btn-read-aloud")?.addEventListener("click",()=>{this.audio&&(this.audio.paused?(this.audio.play(),this.root?.querySelector(".btn-read-aloud")?.classList.add("active")):(this.audio.pause(),this.root?.querySelector(".btn-read-aloud")?.classList.remove("active")))}),this.root.querySelector(".reading3d-speak-btn")?.addEventListener("click",()=>{this.audio&&(this.audio.currentTime=0,this.audio.play())}),this.root.querySelector(".btn-sit")?.addEventListener("click",()=>{const t=this.root?.querySelector(".reading3d-panel");t&&t.classList.toggle("hidden")}),this.root.querySelector(".btn-music")?.addEventListener("click",t=>{t.currentTarget.classList.toggle("active")}),this.root.querySelector(".btn-visible")?.addEventListener("click",t=>{t.currentTarget.classList.toggle("active")}),this.root.querySelector(".btn-camera")?.addEventListener("click",()=>{}),this.root.querySelector(".btn-fullscreen")?.addEventListener("click",()=>{document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen()}))}renderPage(t){if(!this.root)return;const e=t.page_id.replace(/^p/,"").replace(/^0+/,"")||"1",i=t.chapterTitle||t.title||"",s=t.labels?.section||"THE CASE",n=t.longText||"",o=this.root.querySelector(".reading3d-seal");o&&(o.textContent=e);const r=this.root.querySelector(".reading3d-title");r&&(r.textContent=i);const a=this.root.querySelector(".reading3d-section-label");if(a&&this.mode!=="voice"){const h=Array.from(a.childNodes).find(b=>b.nodeType===Node.TEXT_NODE);h?h.textContent=s+" ":a.prepend(document.createTextNode(s+" "))}const d=this.root.querySelector(".reading3d-text");d&&(d.textContent=n);const l=this.root.querySelector(".btn-prev"),c=this.root.querySelector(".btn-next");l&&(l.disabled=!t.prev),c&&(c.disabled=!t.next);const u=this.root.querySelector(".reading3d-panel");u&&(u.scrollTop=0)}setupAudio(t){if(!this.root)return;const e=this.root.querySelector(".reading3d-audio");if(!e)return;const i=this.resolveAudioSrc(t);i?(e.src=i,e.load(),this.audio=e):(e.src="",this.audio=null)}resolveAudioSrc(t){const e=t.narrationAudio||t.audioFile||t.dialogue?.audio||t.dialogues?.[0]?.audio;if(!e)return null;if(this.isAbsoluteOrRemote(e))return e;const i=this.manifest.audioDir??"audio";return this.joinBase(this.manifestBase,`../${i}/${e}`)}isAbsoluteOrRemote(t){return t?/^(https?:)?\/\//i.test(t)||t.startsWith("/")||t.startsWith("data:"):!1}joinBase(t,e){return this.isAbsoluteOrRemote(e)?e:(e.startsWith("./")&&(e=e.slice(2)),`${t.replace(/\/+$/,"")}/${e}`)}}export{R as Reading3DReader};
