﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿/**
 * VoiceBook V1 像素级排版渲染器（PASS 2 完整版）
 * 基准画布：1920 × 1080
 * 数据驱动：textBoxes / audioButton 像素级定位 + 背景图
 * 兼容：constructor 参数可以传 id 字符串，也可以传 DOM 元素
 */
(function () {
  'use strict';

  const BASE_W = 1920;
  const BASE_H = 1080;

  class VoiceBookV1Renderer {
    constructor(containerOrId) {
      this.baseWidth = BASE_W;
      this.baseHeight = BASE_H;
      this.scale = 1;
      this.currentData = null;

      // 兼容传 DOM 或传 id
      let el = null;
      if (typeof containerOrId === 'string') {
        el = document.getElementById(containerOrId);
      } else if (containerOrId && containerOrId.nodeType === 1) {
        el = containerOrId;
      }

      if (!el) {
        // 自动创建 stage
        el = document.getElementById('vb-fullstage');
        if (!el) {
          el = document.createElement('div');
          el.id = 'vb-fullstage';
          document.body.appendChild(el);
        }
      }

      this.stage = el;
      this._initDom();
      this._bindResize();
    }

    _initDom() {
      this.stage.innerHTML = '';
      this.stage.style.position = 'fixed';
      this.stage.style.top = '0';
      this.stage.style.left = '0';
      this.stage.style.width = '100vw';
      this.stage.style.height = '100vh';
      this.stage.style.overflow = 'hidden';
      this.stage.style.display = 'flex';
      this.stage.style.alignItems = 'center';
      this.stage.style.justifyContent = 'center';
      this.stage.style.zIndex = '50';
      this.stage.style.pointerEvents = 'none';

      // 基准画布
      this.canvas = document.createElement('div');
      this.canvas.id = 'vb-v1-canvas';
      this.canvas.style.position = 'relative';
      this.canvas.style.width = this.baseWidth + 'px';
      this.canvas.style.height = this.baseHeight + 'px';
      this.canvas.style.transformOrigin = 'top left';
      this.canvas.style.flexShrink = '0';
      this.canvas.style.pointerEvents = 'auto';

      // 背景层
      this.bgLayer = document.createElement('div');
      this.bgLayer.className = 'vb-v1-layer bg-layer';
      this.bgLayer.style.position = 'absolute';
      this.bgLayer.style.top = '0';
      this.bgLayer.style.left = '0';
      this.bgLayer.style.width = '100%';
      this.bgLayer.style.height = '100%';
      this.bgLayer.style.backgroundSize = '100% 100%';
      this.bgLayer.style.backgroundPosition = 'center';
      this.bgLayer.style.backgroundRepeat = 'no-repeat';
      this.bgLayer.style.pointerEvents = 'none';
      this.bgLayer.style.zIndex = '0';

      // 3D 场景层（独立 <img>，按 sceneArea 像素定位）
      this.sceneLayer = document.createElement('img');
      this.sceneLayer.className = 'vb-v1-layer scene-layer';
      this.sceneLayer.style.position = 'absolute';
      this.sceneLayer.style.left = '0';
      this.sceneLayer.style.top = '0';
      this.sceneLayer.style.width = '0';
      this.sceneLayer.style.height = '0';
      this.sceneLayer.style.objectFit = 'fill';
      this.sceneLayer.style.pointerEvents = 'none';
      this.sceneLayer.style.zIndex = '1';

      // 绘画层 - 必须同时设置 width/height 属性，避免拉伸模糊
      this.paintLayer = document.createElement('canvas');
      this.paintLayer.id = 'vb-v1-paint-layer';
      this.paintLayer.className = 'vb-v1-layer paint-layer';
      this.paintLayer.width = 1920;   // 绘图缓冲区宽度 = 逻辑像素
      this.paintLayer.height = 1080;  // 绘图缓冲区高度 = 逻辑像素
      this.paintLayer.style.width = '100%';
      this.paintLayer.style.height = '100%';
      this.paintLayer.style.touchAction = 'none';
      this.paintLayer.style.pointerEvents = 'none';
      this.paintLayer.style.zIndex = '2';

      // 文本层
      this.textLayer = document.createElement('div');
      this.textLayer.className = 'vb-v1-layer text-layer';
      this.textLayer.style.position = 'absolute';
      this.textLayer.style.top = '0';
      this.textLayer.style.left = '0';
      this.textLayer.style.width = '100%';
      this.textLayer.style.height = '100%';
      this.textLayer.style.pointerEvents = 'none';
      this.textLayer.style.zIndex = '3';

      // 控件层
      this.widgetLayer = document.createElement('div');
      this.widgetLayer.className = 'vb-v1-layer widget-layer';
      this.widgetLayer.style.position = 'absolute';
      this.widgetLayer.style.top = '0';
      this.widgetLayer.style.left = '0';
      this.widgetLayer.style.width = '100%';
      this.widgetLayer.style.height = '100%';
      this.widgetLayer.style.pointerEvents = 'none';
      this.widgetLayer.style.zIndex = '4';

      this.canvas.appendChild(this.bgLayer);
      this.canvas.appendChild(this.sceneLayer);
      this.canvas.appendChild(this.paintLayer);
      this.canvas.appendChild(this.textLayer);
      this.canvas.appendChild(this.widgetLayer);
      this.stage.appendChild(this.canvas);

      // 右侧浮动面板（层级 z-index:100，高于所有画布层）
      this.floatPanel = document.createElement('div');
      this.floatPanel.className = 'vb-float-panel';
      this.floatPanel.style.pointerEvents = 'auto';

      // 绘画层设计按钮：展开/收起工具条
      this.paintToggleBtn = document.createElement('button');
      this.paintToggleBtn.className = 'vb-btn paint-toggle';
      this.paintToggleBtn.textContent = '绘画层设计';
      this.floatPanel.appendChild(this.paintToggleBtn);

      // 工具条（默认收起）
      this.paintToolbar = document.createElement('div');
      this.paintToolbar.className = 'vb-paint-toolbar';
      this.paintToolbar.style.display = 'none';

      this._buildPaintToolbar();
      this.floatPanel.appendChild(this.paintToolbar);
      this.stage.appendChild(this.floatPanel);

      // 绘图事件绑定（坐标换算 + 画笔/橡皮擦）
      this._initPaintTools();

      this._updateScale();
    }

    // ---------------------------------------------------------------
    // 绘画层工具
    // ---------------------------------------------------------------
    _buildPaintToolbar() {
      const bar = this.paintToolbar;

      // 画笔
      const brushBtn = document.createElement('button');
      brushBtn.className = 'vb-btn paint-tool active';
      brushBtn.dataset.tool = 'brush';
      brushBtn.textContent = '画笔';
      bar.appendChild(brushBtn);

      // 橡皮擦
      const eraserBtn = document.createElement('button');
      eraserBtn.className = 'vb-btn paint-tool';
      eraserBtn.dataset.tool = 'eraser';
      eraserBtn.textContent = '橡皮擦';
      bar.appendChild(eraserBtn);

      // 颜色选择器
      const colorRow = document.createElement('label');
      colorRow.className = 'vb-paint-row';
      colorRow.appendChild(document.createTextNode('颜色'));
      const colorInput = document.createElement('input');
      colorInput.type = 'color';
      colorInput.className = 'vb-paint-color';
      colorInput.value = '#1E1E24';
      colorRow.appendChild(colorInput);
      bar.appendChild(colorRow);

      // 线宽选择
      const widthRow = document.createElement('label');
      widthRow.className = 'vb-paint-row';
      widthRow.appendChild(document.createTextNode('线宽'));
      const widthInput = document.createElement('input');
      widthInput.type = 'range';
      widthInput.className = 'vb-paint-width';
      widthInput.min = '1';
      widthInput.max = '50';
      widthInput.value = '4';
      const widthVal = document.createElement('span');
      widthVal.className = 'vb-paint-width-val';
      widthVal.textContent = '4';
      widthRow.appendChild(widthInput);
      widthRow.appendChild(widthVal);
      bar.appendChild(widthRow);

      // 清屏
      const clearBtn = document.createElement('button');
      clearBtn.className = 'vb-btn paint-clear';
      clearBtn.textContent = '清屏';
      bar.appendChild(clearBtn);

      // 引用保存
      this.paintBrushBtn = brushBtn;
      this.paintEraserBtn = eraserBtn;
      this.paintColorInput = colorInput;
      this.paintWidthInput = widthInput;

      // 工具切换
      const setTool = (tool) => {
          this._paintTool = tool;
          brushBtn.classList.toggle('active', tool === 'brush');
          eraserBtn.classList.toggle('active', tool === 'eraser');
      };
      brushBtn.addEventListener('click', () => setTool('brush'));
      eraserBtn.addEventListener('click', () => setTool('eraser'));

      // 颜色 / 线宽实时生效
      colorInput.addEventListener('input', () => {
          this._getPaintCtx().strokeStyle = colorInput.value;
      });
      widthInput.addEventListener('input', () => {
          widthVal.textContent = widthInput.value;
          this._getPaintCtx().lineWidth = parseInt(widthInput.value, 10);
      });

      // 清屏
      clearBtn.addEventListener('click', () => {
          const ctx = this._getPaintCtx();
          ctx.save();
          ctx.globalCompositeOperation = 'source-over';
          ctx.clearRect(0, 0, this.paintLayer.width, this.paintLayer.height);
          ctx.restore();
      });

      // 展开 / 收起
      this.paintToggleBtn.addEventListener('click', () => {
          const opening = this.paintToolbar.style.display === 'none';
          this.paintToolbar.style.display = opening ? 'flex' : 'none';
          this.paintLayer.style.display = opening ? 'block' : 'none';
          // 显示时允许接收指针事件，收起时关闭
          this.paintLayer.style.pointerEvents = opening ? 'auto' : 'none';
          if (opening) setTool(this._paintTool || 'brush');
      });
    }

    _getPaintCtx() {
      if (!this._paintCtx) {
        this._paintCtx = this.paintLayer.getContext('2d');
        const ctx = this._paintCtx;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.lineWidth = parseInt(this.paintWidthInput ? this.paintWidthInput.value : '4', 10);
        ctx.strokeStyle = this.paintColorInput ? this.paintColorInput.value : '#1E1E24';
      }
      return this._paintCtx;
    }

    // 鼠标/指针坐标 → 1920×1080 逻辑画布坐标（自动抵消 transform scale）
    _getPaintCoord(clientX, clientY) {
      const canvas = this.paintLayer;
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      return {
        x: (clientX - rect.left) * scaleX,
        y: (clientY - rect.top) * scaleY
      };
    }

    _initPaintTools() {
      this._paintDrawing = false;
      this._paintTool = 'brush'; // brush / eraser
      this._paintLastX = 0;
      this._paintLastY = 0;

      const canvas = this.paintLayer;

      canvas.addEventListener('pointerdown', (e) => {
          if (canvas.style.display === 'none') return;
          this._paintDrawing = true;
          canvas.setPointerCapture(e.pointerId);
          const p = this._getPaintCoord(e.clientX, e.clientY);
          this._paintLastX = p.x;
          this._paintLastY = p.y;
          const ctx = this._getPaintCtx();
          ctx.globalCompositeOperation = (this._paintTool === 'eraser')
              ? 'destination-out'
              : 'source-over';
          // 单点起笔（点击不落空；destination-out 下填充即擦除）
          ctx.beginPath();
          ctx.arc(p.x, p.y, ctx.lineWidth / 2, 0, Math.PI * 2);
          ctx.fillStyle = ctx.strokeStyle;
          ctx.fill();
      });

      canvas.addEventListener('pointermove', (e) => {
          if (!this._paintDrawing) return;
          const p = this._getPaintCoord(e.clientX, e.clientY);
          const ctx = this._getPaintCtx();
          ctx.beginPath();
          ctx.moveTo(this._paintLastX, this._paintLastY);
          ctx.lineTo(p.x, p.y);
          ctx.stroke();
          this._paintLastX = p.x;
          this._paintLastY = p.y;
      });

      const stop = () => { this._paintDrawing = false; };
      canvas.addEventListener('pointerup', stop);
      canvas.addEventListener('pointercancel', stop);
      canvas.addEventListener('pointerleave', stop);
    }

    _updateScale() {
      const winW = window.innerWidth;
      const winH = window.innerHeight;
      const sx = winW / this.baseWidth;
      const sy = winH / this.baseHeight;
      this.scale = Math.min(sx, sy);
      this.canvas.style.transform = 'scale(' + this.scale + ')';
      console.log('[VoiceBook V1 PASS2] scale =', this.scale.toFixed(3), 'viewport =', winW + 'x' + winH);
    }

    _bindResize() {
      window.addEventListener('resize', () => this._updateScale());
    }

    renderPage(v1Data) {
      if (!v1Data) return;
      this.currentData = v1Data;

      this.textLayer.innerHTML = '';
      this.widgetLayer.innerHTML = '';

      // 皮肤切换（与 voice.css 的 theme-dark 对应）
      const skin = v1Data.skin_type || 'Sit';
      const themeBtn = document.getElementById('btn-theme');
      if (skin === 'Dark') {
          document.body.classList.add('theme-dark');
          if (themeBtn) themeBtn.classList.add('active');
      } else {
          document.body.classList.remove('theme-dark');
          if (themeBtn) themeBtn.classList.remove('active');
      }

      // 同步版式到 body 类名
      // 新格式: layout.layout = "left-right"/"top-bottom"/"fullscreen"
      // 旧格式兼容: layout.type = "left_right"/"top_bottom"/"full"
      const layoutData = v1Data.layout || {};
      let layoutType = layoutData.layout || layoutData.type || 'fullscreen';
      layoutType = String(layoutType).replace(/_/g, '-');
      if (layoutType === 'full') layoutType = 'fullscreen';
      document.body.classList.remove('layout-left-right', 'layout-top-bottom', 'layout-fullscreen');
      document.body.classList.add('layout-' + layoutType);

      // 0. 3D 场景层（按 layout.sceneArea 定位）
      this._renderSceneLayer(v1Data);

      // 1. 背景
      const bg = v1Data.background || v1Data.base_image_path;
      if (bg) this._renderBackground(bg);

      // 2. 文本框
      if (v1Data.textBoxes) this._renderTextBoxes(v1Data.textBoxes);

      // 3. 音频按钮
      if (v1Data.audioButton) this._renderAudioButton(v1Data.audioButton);

      console.log('[VoiceBook V1 PASS2]', {
        pageId: v1Data.pageId,
        canvas: this.baseWidth + 'x' + this.baseHeight,
        title: v1Data.textBoxes && v1Data.textBoxes.title,
        body: v1Data.textBoxes && v1Data.textBoxes.body,
        audio: v1Data.audioButton
      });
    }

    _renderSceneLayer(v1Data) {
      if (!this.sceneLayer) return;
      const layout = v1Data.layout || {};
      const sa = layout.sceneArea;
      if (!sa || sa.w <= 0 || sa.h <= 0) {
        this.sceneLayer.style.display = 'none';
        return;
      }
      const pageId = v1Data.pageId || 'page_0000';
      const url = './voicebook/' + pageId + '_scene_part.png?t=' + Date.now();
      this.sceneLayer.src = url;
      this.sceneLayer.style.display = 'block';
      this.sceneLayer.style.left = (sa.x || 0) + 'px';
      this.sceneLayer.style.top = (sa.y || 0) + 'px';
      this.sceneLayer.style.width = (sa.w || 0) + 'px';
      this.sceneLayer.style.height = (sa.h || 0) + 'px';
      console.log('[VoiceBook V1 PASS2] sceneLayer:', url, sa);
    }

    _renderBackground(url) {
      if (!url) return;
      this.bgLayer.style.backgroundImage = 'url("' + url + '")';
    }

    _renderTextBoxes(textBoxes) {
      for (const key of Object.keys(textBoxes)) {
        const box = textBoxes[key];
        if (!box) continue;

        const el = document.createElement('div');
        el.className = 'vb-textbox vb-textbox-' + key;
        el.style.position = 'absolute';
        el.style.left = (box.x || 0) + 'px';
        el.style.top = (box.y || 0) + 'px';
        el.style.width = (box.w || box.width || 200) + 'px';
        el.style.height = (box.h || box.height || 80) + 'px';
        el.style.fontSize = (box.fontSize || box.size || 32) + 'px';
        el.style.lineHeight = (box.lineHeight || 1.2) + 'px';
        el.style.color = box.color || '#1E1E24';
        el.style.overflow = 'hidden';
        el.style.wordBreak = 'break-word';
        el.style.whiteSpace = 'pre-wrap';
        el.style.boxSizing = 'border-box';
        el.style.pointerEvents = 'auto';
        el.textContent = box.text || box.content || '';

        this.textLayer.appendChild(el);
      }
    }

    _renderAudioButton(btn) {
      const el = document.createElement('button');
      el.className = 'vb-audio-btn';
      el.style.position = 'absolute';
      el.style.left = (btn.x || 0) + 'px';
      el.style.top = (btn.y || 0) + 'px';
      el.style.width = (btn.w || btn.width || 64) + 'px';
      el.style.height = (btn.h || btn.height || 64) + 'px';
      el.style.border = 'none';
      el.style.borderRadius = '50%';
      el.style.background = '#C73E3A';
      el.style.color = '#fff';
      el.style.cursor = 'pointer';
      el.style.fontSize = '24px';
      el.style.pointerEvents = 'auto';
      el.textContent = '♪';
      el.addEventListener('click', () => {
        console.log('[VoiceBook V1 PASS2] audio button clicked');
      });
      this.widgetLayer.appendChild(el);
    }

    destroy() {
      if (this.stage) this.stage.innerHTML = '';
    }
  }

  window.VoiceBookV1Renderer = VoiceBookV1Renderer;
})();
