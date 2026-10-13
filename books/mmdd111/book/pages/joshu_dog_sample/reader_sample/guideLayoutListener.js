// guideLayoutListener.js
// PASS 1：优先读 Blender V1 JSON (./voicebook/<pageId>.json)
//        找不到时回退旧 guide_rect.json（样板逻辑）
(function () {
    "use strict";
    const TOP_BOTTOM_TEXT_RATIO = 0.4;

    function getCurrentPageId() {
        const params = new URLSearchParams(location.search);
        const fromUrl = params.get("page");
        if (fromUrl) return fromUrl;
        // 与 main.js 消费同一个 V1 文件（manifest 的 scene_name），
        // 避免两个脚本各读一份内容不同的 JSON 互相覆盖
        if (typeof window.getCurrentPageId === "function") {
            const id = window.getCurrentPageId();
            if (id) return id;
        }
        return "p.0000.w1h1";
    }

    function getLayoutMode() {
        const c = document.body.classList;
        if (c.contains("layout-left-right")) return "left-right";
        if (c.contains("layout-fullscreen")) return "fullscreen";
        return "top-bottom";
    }

    // ============ 旧逻辑：百分比布局（原样保留） ============
    function applyRect_legacy(page) {
        const panel = document.getElementById("text-panel");
        if (!panel) return;
        panel.style.position = "";
        panel.style.left = "";
        panel.style.top = "";
        panel.style.width = "";
        panel.style.height = "";
        panel.style.zIndex = "";

        const fullW = (page.fullUI && page.fullUI.width) || 1920;
        const leftW = (page.leftText && page.leftText.width) || 0;
        const textRatioW = Math.max(0.1, Math.min(0.9, leftW / fullW));

        const body = document.body;
        body.style.setProperty("--lr-text-w",   Math.round(textRatioW * 100) + "%");
        body.style.setProperty("--lr-canvas-w", Math.round((1 - textRatioW) * 100) + "%");
        body.style.setProperty("--tb-text-h",   Math.round(TOP_BOTTOM_TEXT_RATIO * 100) + "%");
        body.style.setProperty("--tb-canvas-h", Math.round((1 - TOP_BOTTOM_TEXT_RATIO) * 100) + "%");

        window.dispatchEvent(new Event("resize"));
        console.log("[GuideLayout] " + getCurrentPageId() +
            " | 左图右文: 文 " + Math.round(textRatioW * 100) + "% / 图 " + Math.round((1 - textRatioW) * 100) + "%" +
            " | 上图下文: 文 " + Math.round(TOP_BOTTOM_TEXT_RATIO * 100) + "% / 图 " + Math.round((1 - TOP_BOTTOM_TEXT_RATIO) * 100) + "%" +
            " | 模式: " + getLayoutMode());
    }

    // ============ PASS 1 新增：V1 → 旧 pageManifest（供 main.js 用） ============
    function v1ToPageManifest(v1) {
        // 同时兼容下划线（left_right）与连字符（left-right）两种 V1 写法
        const layoutMap = {
            left_right: "left-right",
            top_bottom: "top-bottom",
            "left-right": "left-right",
            "top-bottom": "top-bottom",
            full: "fullscreen",
            fullscreen: "fullscreen",
        };
        const rawLayout = v1.layout && v1.layout.type;
        if (!layoutMap[rawLayout]) {
            console.warn("[VoiceBook PASS1] 未知 V1 layout:", rawLayout);
            return null;
        }
        const title = (v1.textBoxes && v1.textBoxes.title && v1.textBoxes.title.text) || "";
        let body = (v1.textBoxes && v1.textBoxes.body && v1.textBoxes.body.text) || "";
        if (!body && v1.blocks && v1.blocks.length) {
            body = v1.blocks.map(function (b) { return b.text || ""; })
                .filter(Boolean).join("\n");
        }
        return {
            layout: layoutMap[rawLayout],
            title: title,
            body: body,
            pageId: v1.pageId || "",
        };
    }

    // ============ PASS 1 新增：V1 → 旧 rect（供 applyRect_legacy 用） ============
    function v1ToLegacyRect(v1) {
        const canvasW = (v1.canvas && v1.canvas.width) || 1920;
        const canvasH = (v1.canvas && v1.canvas.height) || 1080;
        const textArea = (v1.layout && v1.layout.textArea) || {};
        const sceneArea = (v1.layout && v1.layout.sceneArea) || {};
        return {
            fullUI: { width: canvasW, height: canvasH },
            leftText: {
                // 与 main.js 的 (textArea.x + textArea.w) / canvasW 算法保持一致
                width: (textArea.x || 0) + (textArea.w || 0),
                height: textArea.h || canvasH,
            },
            rightScene: {
                width: sceneArea.w || 0,
                height: sceneArea.h || canvasH,
            },
        };
    }

    // ============ PASS 1 新增：写文字到 DOM ============
    function applyManifestText(manifest) {
        const titleEl = document.getElementById("text-title")
                     || document.getElementById("textTitle");
        const bodyEl  = document.getElementById("text-body")
                     || document.getElementById("textBody");
        if (titleEl) titleEl.textContent = manifest.title || "";
        if (bodyEl)  bodyEl.textContent  = manifest.body  || "";
    }

    // ============ 主入口 ============
    async function loadGuideRects() {
        const pageId = getCurrentPageId();

        // ★ 优先：Blender V1 JSON
        try {
            const url = "./voicebook/" + pageId + ".json?t=" + Date.now();
            const res = await fetch(url, { cache: "no-store" });
            if (res.ok) {
                const v1 = await res.json();
                if (v1 && v1.canvas && v1.layout && v1.textBoxes) {
                    const manifest = v1ToPageManifest(v1);
                    if (!manifest) {
                        console.warn("[VoiceBook PASS1] manifest 转换失败，回退 guide_rect");
                    } else {
                        const rect = v1ToLegacyRect(v1);
                        applyRect_legacy(rect);        // ① 先设百分比布局
                        applyManifestText(manifest);   // ② 再覆盖文字
                        console.log("[VoiceBook PASS1] V1 → Reader", {
                            pageId: manifest.pageId,
                            layout: manifest.layout,
                            title: manifest.title,
                            body: manifest.body,
                        });
                        return;
                    }
                }
            }
        } catch (e) {
            console.warn("[VoiceBook PASS1] V1 加载失败，回退 guide_rect：", e.message);
        }

        // 旧逻辑：guide_rect.json
        try {
            const res = await fetch("./guide_rect.json?t=" + Date.now(), { cache: "no-store" });
            if (!res.ok) return;
            const data = await res.json();
            const page = data[pageId] || data[pageId.replace(/\./g, "")];
            if (!page || !page.leftText) {
                console.warn("[GuideLayout] 找不到页 " + pageId);
                return;
            }
            applyRect_legacy(page);
        } catch (e) {
            console.warn("[GuideLayout] fetch 失败:", e.message);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", loadGuideRects);
    } else {
        loadGuideRects();
    }

    document.addEventListener("click", function (e) {
        if (e.target.closest("#layout-nav button")) {
            setTimeout(loadGuideRects, 100);
        }
    });

    window.__reloadGuideLayout = loadGuideRects;
})();
