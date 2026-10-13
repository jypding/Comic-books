/* VoiceBook V1 Boot（数据通知器模式）
 * 主动 fetch ./voicebook/<pageId>.json；
 * 数据变化时通过 window.__voicebookV1Notify(pageId, data) 通知主页面（main.js），
 * 不再自行创建全屏覆盖画布，避免与 Three.js 双渲染器冲突。
 * pageId 来源：URL ?page=xxx（主）→ window.getCurrentPageId() → 其他 fallback
 */
(function () {
    "use strict";
    const V1_DIR = "./voicebook/";
    const POLL_MS = 500;
    let activePageId = "";
    let activeSignature = "";

    function getCurrentPageId() {
        // 主：从 URL 拿
        const p = new URLSearchParams(location.search);
        const fromUrl = p.get("page");
        if (fromUrl) return fromUrl;

        // fallback
        if (typeof window.getCurrentPageId === "function") {
            const id = window.getCurrentPageId();
            if (id) return id;
        }
        if (typeof window.__currentPageId === "function") {
            const id = window.__currentPageId();
            if (id) return id;
        }
        if (window.currentPageId) return window.currentPageId;
        const el = document.querySelector("[data-page-id]");
        return el ? el.dataset.pageId : "";
    }

    async function loadV1(pageId) {
        if (!pageId) return null;
        const url = V1_DIR + encodeURIComponent(pageId) + ".json?t=" + Date.now();
        try {
            const res = await fetch(url, { cache: "no-store" });
            if (!res.ok) return null;
            const v1 = await res.json();
            if (!v1 || !v1.canvas || !v1.layout || !v1.textBoxes) {
                console.warn("[VoiceBook Sync] V1 结构无效:", pageId);
                return null;
            }
            return v1;
        } catch (e) {
            return null;
        }
    }

    function notify(pageId, v1) {
        if (typeof window.__voicebookV1Notify === "function") {
            window.__voicebookV1Notify(pageId, v1);
        }
    }

    async function checkCurrentPage() {
        const pageId = getCurrentPageId();

        // 页面切换：重置签名，强制按新页处理
        if (pageId !== activePageId) {
            activePageId = pageId;
            activeSignature = "";
        }
        if (!pageId) return;

        const v1 = await loadV1(pageId);
        if (!v1) return;

        // 同一页内容变化（Blender 重新导出）也要通知
        const sig = JSON.stringify(v1);
        if (sig === activeSignature) return;
        activeSignature = sig;

        notify(pageId, v1);
    }

    function start() {
        checkCurrentPage();
        setInterval(checkCurrentPage, POLL_MS);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }

    // ===== build-version-watch：服务端 main.js 令牌与本页不一致 → 自动硬刷新一次
    // （防止导出/改码后旧标签页一直显示旧画面；刷新后令牌一致不再触发）=====
    let buildReloadDone = false;
    async function checkBuildVersion() {
        if (buildReloadDone) return;
        try {
            const res = await fetch("./main.js?buildcheck=" + Date.now(), { cache: "no-store" });
            if (!res.ok) return;
            const txt = await res.text();
            const m = txt.match(/__VOICEBOOK_BUILD_TOKEN\s*=\s*["']([^"']+)["']/);
            const servedToken = m ? m[1] : "";
            const localToken = window.__VOICEBOOK_BUILD_TOKEN || "";
            if (servedToken && servedToken !== localToken) {
                buildReloadDone = true;
                console.warn("[BuildWatch] 检测到新版本，自动硬刷新:", servedToken);
                location.reload();
            }
        } catch (e) { /* 忽略瞬时失败 */ }
    }
    setTimeout(checkBuildVersion, 1500);
})();
