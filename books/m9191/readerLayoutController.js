export class ReaderLayoutController {
  constructor() {
    this.body = document.body;
    this.canvasContainer = document.getElementById('canvas-container');
    this.textPanel = document.getElementById('text-panel');
    this.textTitle = document.getElementById('text-title');
    this.textBody = document.body.querySelector('#text-body');
    
    this.layoutNavButtons = document.querySelectorAll('#layout-nav button');
    
    this.currentLayout = 'top-bottom';
    this.layoutRatios = {
      topBottomViewportHeight: 0.6,
      leftRightViewportWidth: 0.6,
      fullscreen: 1.0
    };
    
    this.onResizeCallback = null;
    
    this.initEvents();
  }

  initEvents() {
    this.layoutNavButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        const layout = e.target.getAttribute('data-layout');
        this.setLayout(layout);
      });
    });

    window.addEventListener('resize', () => {
      this.resizeViewport();
    });
  }

  setRatios(ratios) {
    if (ratios) {
      this.layoutRatios = { ...this.layoutRatios, ...ratios };
      this.applyRatiosToCSS();
    }
  }

  applyRatiosToCSS() {
    // Top-Bottom
    const tbCanvasH = this.layoutRatios.topBottomViewportHeight * 100;
    const tbTextH = 100 - tbCanvasH;
    
    // Left-Right
    const lrCanvasW = this.layoutRatios.leftRightViewportWidth * 100;
    const lrTextW = 100 - lrCanvasW;

    // We can inject a style tag or just set custom properties
    this.body.style.setProperty('--tb-canvas-h', `${tbCanvasH}%`);
    this.body.style.setProperty('--tb-text-h', `${tbTextH}%`);
    this.body.style.setProperty('--lr-canvas-w', `${lrCanvasW}%`);
    this.body.style.setProperty('--lr-text-w', `${lrTextW}%`);

    // Let's directly update the style if needed, but since CSS is hardcoded we can manipulate inline styles
    // Instead of overriding classes entirely, we'll handle resize logic dynamically in JS
    this.resizeViewport();
  }

  setLayout(layout) {
    this.currentLayout = layout;
    
    // Update body class
    this.body.className = `layout-${layout}`;

    // Update buttons
    this.layoutNavButtons.forEach(btn => {
      if (btn.getAttribute('data-layout') === layout) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    this.resizeViewport();
  }

  updateText(title, body) {
    if (title) this.textTitle.textContent = title;
    if (body) this.textBody.textContent = body;
  }

  applyPageManifest(pageManifest) {
    if (pageManifest.layout) {
      this.setLayout(pageManifest.layout);
    }
    this.updateText(pageManifest.title, pageManifest.body);
  }

  resizeViewport() {
    // Read actual dimensions of the container
    const width = this.canvasContainer.clientWidth;
    const height = this.canvasContainer.clientHeight;

    if (this.onResizeCallback) {
      this.onResizeCallback(width, height);
    }
  }
}
