// editMode.js - VoiceBook 布局编辑模式（模式感知版）
(function () {
    'use strict';

    const CANVAS = { width: 1920, height: 1080 };
    const MARGIN = { x: 73, y: 14 };
    const GAP = 27;
    const CONTENT_TOTAL_W = CANVAS.width - MARGIN.x * 2 - GAP;
    const CONTENT_TOTAL_H = CANVAS.height - MARGIN.y * 2;
    const DEFAULT_LEFT_RATIO = 710 / CONTENT_TOTAL_W;
    const DEFAULT_TOP_RATIO = 0.6;
    const MIN_RATIO = 0.15;
    const MAX_RATIO = 0.85;

    const state = {
        enabled: false,
        leftRatio: DEFAULT_LEFT_RATIO,
        topRatio: DEFAULT_TOP_RATIO,
        panelElement: null
    };

    // ===== 拖拽分界线 =====
    function createDivider() {
        const mode = getLayoutMode();
        if (mode === 'fullscreen') return null;

        const div = document.createElement('div');
        div.id = 'edit-divider';
        div.style.cssText = 'position:fixed;background:rgba(100,150,255,0.35);z-index:9998;user-select:none;transition:background 0.15s;';
        
        if (mode === 'left-right') {
            div.style.width = '8px';
            div.style.height = '100vh';
            div.style.top = '0';
            div.style.left = ((state.leftRatio * 100) - 0.4) + 'vw';
            div.style.cursor = 'col-resize';
        } else {
            div.style.height = '8px';
            div.style.width = '100vw';
            div.style.left = '0';
            div.style.top = ((state.topRatio * 100) - 0.4) + 'vh';
            div.style.cursor = 'row-resize';
        }

        div.addEventListener('mouseenter', () => { div.style.background = 'rgba(100,150,255,0.8)'; });
        div.addEventListener('mouseleave', () => { div.style.background = 'rgba(100,150,255,0.35)'; });

        document.body.appendChild(div);
        return div;
    }

    function bindDividerDrag(div) {
        let dragging = false;

        div.addEventListener('mousedown', (e) => {
            dragging = true;
            e.preventDefault();
            document.body.style.cursor = (getLayoutMode() === 'left-right') ? 'col-resize' : 'row-resize';
            document.body.style.userSelect = 'none';
        });

        document.addEventListener('mousemove', (e) => {
            if (!dragging) return;
            const mode = getLayoutMode();
            if (mode === 'left-right') {
                const ratio = Math.max(MIN_RATIO, Math.min(MAX_RATIO, e.clientX / window.innerWidth));
                state.leftRatio = ratio;
                div.style.left = ((ratio * 100) - 0.4) + 'vw';
            } else if (mode === 'top-bottom') {
                const ratio = Math.max(MIN_RATIO, Math.min(MAX_RATIO, e.clientY / window.innerHeight));
                state.topRatio = ratio;
                div.style.top = ((ratio * 100) - 0.4) + 'vh';
            }
            applyLayout();
        });

        document.addEventListener('mouseup', () => {
            if (!dragging) return;
            dragging = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        });
    }

    // ===== 监听模式变化，自动重建分界线 =====
    let __lastMode = "";
    let __modeWatcher = null;
    function watchModeChange() {
        if (__modeWatcher) return;
        __modeWatcher = setInterval(() => {
            if (!state.enabled) return;
            const mode = getLayoutMode();
            if (mode !== __lastMode) {
                __lastMode = mode;
                if (state.dividerElement) {
                    state.dividerElement.remove();
                    state.dividerElement = null;
                }
                if (mode !== "fullscreen") {
                    state.dividerElement = createDivider();
                    if (state.dividerElement) bindDividerDrag(state.dividerElement);
                }
                console.log("[EditMode] 模式切换:", mode);
            }
        }, 200);
    }


        function getLayoutMode() {
        const c = document.body.classList;
        if (c.contains('layout-left-right')) return 'left-right';
        if (c.contains('layout-fullscreen')) return 'fullscreen';
        return 'top-bottom';
    }

    function applyLayout() {
        const mode = getLayoutMode();
        const body = document.body;

        if (mode === 'left-right') {
            const leftPercent = (state.leftRatio * 100).toFixed(2) + '%';
            const canvasPercent = ((1 - state.leftRatio) * 100).toFixed(2) + '%';
            body.style.setProperty('--lr-text-w', leftPercent);
            body.style.setProperty('--lr-canvas-w', canvasPercent);
        } else if (mode === 'top-bottom') {
            const canvasPercent = (state.topRatio * 100).toFixed(2) + '%';
            const textPercent = ((1 - state.topRatio) * 100).toFixed(2) + '%';
            body.style.setProperty('--tb-canvas-h', canvasPercent);
            body.style.setProperty('--tb-text-h', textPercent);
        }

        window.dispatchEvent(new Event('resize'));
        updatePanelDisplay();
    }

    function buildPanel() {
        const panel = document.createElement('div');
        panel.id = 'layout-edit-panel';
        panel.style.cssText = `
            position: fixed; top: 60px; right: 16px; width: 220px; padding: 12px;
            background: rgba(0,0,0,0.78); color: #fff; border-radius: 8px;
            font-size: 13px; font-family: system-ui, sans-serif;
            z-index: 9999; backdrop-filter: blur(4px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        `;
        panel.innerHTML = `
            <div style="font-weight:600;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;">
                <span>📐 布局编辑</span>
                <button id="edit-close" style="background:none;border:none;color:#aaa;cursor:pointer;font-size:16px;">×</button>
            </div>
            <div id="mode-label" style="margin-bottom:8px;color:#7ea6f0;font-size:12px;">—</div>
            <div id="ratio-label" style="margin-bottom:8px;color:#ccc;">—</div>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:4px;margin-bottom:10px;">
                <button data-step="-0.05" class="edit-btn">-5%</button>
                <button data-step="-0.01" class="edit-btn">-1%</button>
                <button data-step="0.01" class="edit-btn">+1%</button>
                <button data-step="0.05" class="edit-btn">+5%</button>
            </div>
            <div style="margin-bottom:12px;">
                <input type="number" id="ratio-input" step="0.01"
                    style="width:100%;padding:4px 6px;border-radius:4px;border:1px solid #555;background:#222;color:#fff;text-align:center;">
                <span style="display:block;text-align:center;color:#aaa;margin-top:2px;font-size:12px;">%</span>
            </div>
            <div style="border-top:1px solid #444;padding-top:10px;margin-bottom:10px;font-size:12px;color:#aaa;">
                <div id="px-info">—</div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                <button id="edit-reset" class="edit-btn">重置</button>
                <button id="edit-save" class="edit-btn primary">保存 JSON</button>
            </div>
        `;
        const style = document.createElement('style');
        style.textContent = `
            .edit-btn{padding:5px 0;border:1px solid #555;border-radius:4px;background:#333;color:#fff;cursor:pointer;font-size:12px;}
            .edit-btn:hover{background:#444;}
            .edit-btn.primary{background:#2563eb;border-color:#2563eb;}
            .edit-btn.primary:hover{background:#3b82f6;}
        `;
        document.head.appendChild(style);
        return panel;
    }

    function updatePanelDisplay() {
        if (!state.panelElement) return;
        const mode = getLayoutMode();
        const modeText = { 'left-right': '左图右文', 'top-bottom': '上图下文', 'fullscreen': '全屏' }[mode];
        document.getElementById('mode-label').textContent = '模式：' + modeText;

        if (mode === 'left-right') {
            document.getElementById('ratio-label').textContent = '左栏比例';
            document.getElementById('ratio-input').value = (state.leftRatio * 100).toFixed(2);
            const leftW = Math.round(CONTENT_TOTAL_W * state.leftRatio);
            document.getElementById('px-info').innerHTML = `左栏：${leftW} px<br>右栏：${CONTENT_TOTAL_W - leftW} px`;
        } else if (mode === 'top-bottom') {
            document.getElementById('ratio-label').textContent = '画布高度比例（3D 区）';
            document.getElementById('ratio-input').value = (state.topRatio * 100).toFixed(2);
            const canvasH = Math.round(CANVAS.height * state.topRatio);
            document.getElementById('px-info').innerHTML = `3D 高：${canvasH} px<br>文字高：${CANVAS.height - canvasH} px`;
        } else {
            document.getElementById('ratio-label').textContent = '全屏模式不支持编辑';
            document.getElementById('ratio-input').value = '';
            document.getElementById('px-info').textContent = '—';
        }
    }

    function bindEvents() {
        const panel = state.panelElement;
        panel.querySelectorAll('[data-step]').forEach(btn => {
            btn.addEventListener('click', () => {
                const step = parseFloat(btn.dataset.step);
                const mode = getLayoutMode();
                if (mode === 'left-right') {
                    state.leftRatio = Math.max(MIN_RATIO, Math.min(MAX_RATIO, state.leftRatio + step));
                } else if (mode === 'top-bottom') {
                    state.topRatio = Math.max(MIN_RATIO, Math.min(MAX_RATIO, state.topRatio + step));
                }
                applyLayout();
            });
        });
        document.getElementById('ratio-input').addEventListener('change', (e) => {
            let p = parseFloat(e.target.value);
            if (isNaN(p)) return;
            p = Math.max(MIN_RATIO * 100, Math.min(MAX_RATIO * 100, p));
            const mode = getLayoutMode();
            if (mode === 'left-right') state.leftRatio = p / 100;
            else if (mode === 'top-bottom') state.topRatio = p / 100;
            applyLayout();
        });
        document.getElementById('edit-reset').addEventListener('click', () => {
            const mode = getLayoutMode();
            if (mode === 'left-right') state.leftRatio = DEFAULT_LEFT_RATIO;
            else if (mode === 'top-bottom') state.topRatio = DEFAULT_TOP_RATIO;
            applyLayout();
        });
        document.getElementById('edit-save').addEventListener('click', saveJSON);
        document.getElementById('edit-close').addEventListener('click', disableEditMode);
    }

    function saveJSON() {
        const mode = getLayoutMode();
        const pageId = (typeof window.__currentPageId === 'function' && window.__currentPageId()) || 'p.0000.w1h1';
        const contentH = CANVAS.height - MARGIN.y * 2;

        let regions;
        if (mode === 'left-right') {
            const leftW = Math.round(CONTENT_TOTAL_W * state.leftRatio);
            regions = {
                leftText: { x: MARGIN.x, y: MARGIN.y, width: leftW, height: contentH },
                rightScene: { x: MARGIN.x + leftW + GAP, y: MARGIN.y, width: CONTENT_TOTAL_W - leftW, height: contentH }
            };
        } else {
            const canvasH = Math.round(CANVAS.height * state.topRatio);
            regions = {
                leftText: { x: MARGIN.x, y: MARGIN.y + canvasH, width: CANVAS.width - MARGIN.x * 2, height: contentH - canvasH },
                rightScene: { x: MARGIN.x, y: MARGIN.y, width: CANVAS.width - MARGIN.x * 2, height: canvasH }
            };
        }

        const pageData = {
            pageId,
            canvas: { width: CANVAS.width, height: CANVAS.height },
            regions,
            texts: {
                title: (document.getElementById('text-title') || {}).textContent || '',
                section: (document.getElementById('text-section') || {}).textContent || '',
                body: (document.getElementById('text-body') || {}).textContent || ''
            }
        };
        const blob = new Blob([JSON.stringify(pageData, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${pageId}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function enableEditMode() {
        if (state.enabled) return;
        state.panelElement = buildPanel();
        document.body.appendChild(state.panelElement);
        bindEvents();
        state.enabled = true;

        // 新加：创建分界线
        state.dividerElement = createDivider();
        if (state.dividerElement) bindDividerDrag(state.dividerElement);

        // 启动模式监听
        __lastMode = getLayoutMode();
        watchModeChange();


        // 让文字可编辑
        const editableIds = ['text-title', 'text-section', 'text-body'];
        editableIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.setAttribute('contenteditable', 'true');
                el.style.outline = '1px dashed rgba(100,150,255,0.6)';
                el.style.padding = '4px';
                el.style.minHeight = '1em';
                el.style.cursor = 'text';
            }
        });

        // 输入监听
        document.body.addEventListener('input', function onTextInput(e) {
            if (e.target.contentEditable === 'true') {
                state.textDraft = state.textDraft || {};
                state.textDraft[e.target.id] = e.target.textContent;
                console.log('[TextEdit] ' + e.target.id + ' = ' + e.target.textContent.substring(0, 40));
            }
        });

        applyLayout();
    }

    function disableEditMode() {
        if (!state.enabled) return;
        if (state.panelElement) {
            state.panelElement.remove();
            state.panelElement = null;
        }
        // 移除分界线
        if (state.dividerElement) {
            state.dividerElement.remove();
            state.dividerElement = null;
        }
        // 移除文字编辑
        ['text-title', 'text-section', 'text-body'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.removeAttribute('contenteditable');
                el.style.outline = '';
                el.style.padding = '';
                el.style.minHeight = '';
                el.style.cursor = '';
            }
        });
        state.enabled = false;
    }

    window.LayoutEditMode = {
        rebuildDivider: () => {
            if (!state.enabled) return;
            if (state.dividerElement) state.dividerElement.remove();
            state.dividerElement = createDivider();
            if (state.dividerElement) bindDividerDrag(state.dividerElement);
        },
        enable: enableEditMode,
        disable: disableEditMode,
        get enabled() { return state.enabled; },
        setRatio: (r) => {
            const mode = getLayoutMode();
            if (mode === 'left-right') state.leftRatio = Math.max(MIN_RATIO, Math.min(MAX_RATIO, r));
            else state.topRatio = Math.max(MIN_RATIO, Math.min(MAX_RATIO, r));
            applyLayout();
        },
        reapply: () => { if (state.enabled) applyLayout(); }
    };
})();
