/**
 * UI 控制器：负责 Cinematic 模式下的状态展示与字幕。
 * 
 * 职责：
 *  - 字幕 DOM 管理。
 *  - 状态信息展示。
 *  - 不再负责全局导航按钮（btn-prev/next/play）的绑定，该职责已移交 ReaderFactory。
 */
export class UiController {
  private subtitleEl: HTMLElement | null;
  private statusEl: HTMLElement | null;

  constructor() {
    this.subtitleEl = document.getElementById('subtitle');
    this.statusEl = document.getElementById('status');
  }

  dispose(): void {
    this.showSubtitle("");
    this.setStatus("");
  }

  showSubtitle(text: string): void {
    if (!this.subtitleEl) return;
    this.subtitleEl.textContent = text;
    this.subtitleEl.style.display = text ? 'block' : 'none';
  }

  setStatus(msg: string): void {
    if (!this.statusEl) return;
    this.statusEl.textContent = msg;
  }
}
