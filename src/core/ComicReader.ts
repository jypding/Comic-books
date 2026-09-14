import type { UnifiedPage } from "./ProjectLoader";

export interface ComicReader {
    /** 初始化运行时环境（Canvas, DOM 挂载等） */
    init(): Promise<void>;
    
    /** 加载并渲染具体页面数据 */
    loadPage(page: UnifiedPage, pagePath: string): Promise<void>;
    
    /** 卸载当前页面资源，停止播放 */
    unloadPage(): Promise<void>;
    
    /** 播放当前页音频/动画 */
    play(): void;
    
    /** 暂停当前页音频/动画 */
    pause(): void;
    
    /** 彻底销毁实例，清理所有资源与 DOM */
    dispose(): void;
}
