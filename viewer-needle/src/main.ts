/**
 * Viewer 唯一运行时启动脚本（Bootstrap）。
 *
 * 职责：
 *  1. 解析 URL 参数确定书籍路径。
 *  2. 加载书籍 Manifest。
 *  3. 调用 ReaderFactory 动态分发阅读器。
 *  4. 执行初始化并打开第一页。
 */
import { ProjectLoader, type Manifest } from "@core/ProjectLoader";
import type { ComicReader } from "@core/ComicReader";
import "@ui/common/common.css";

function resolveManifestUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const book = params.get("book");

  // 自动探测 base path，例如 /Comic-books/
  const base = window.location.pathname.substring(0, window.location.pathname.lastIndexOf('/') + 1);

  // 如果 book 参数以 '/' 开头，则视为绝对路径或相对于根的路径
  if (book && book.startsWith("/")) {
      return `${book}/book/manifest.json`;
  }

  if (book) {
    // 根据目录结构，书籍存放在根目录的 /books 文件夹下
    return `${base}books/${encodeURIComponent(book)}/book/manifest.json`;
  }

  return `${base}books/current/book/manifest.json`;
}

async function tryLoadManifest(url: string): Promise<Manifest | null> {
  try {
    return await ProjectLoader.loadManifest(url);
  } catch {
    return null;
  }
}

function dirname(url: string): string {
  const i = url.lastIndexOf("/");
  return i < 0 ? "." : url.slice(0, i);
}

let activeReader: ComicReader | null = null;

/**
 * 根据当前书籍模式控制 Viewer 根容器的可见性。
 *
 * Voice：
 *  - reading-root      显示
 *  - cinematic-root    隐藏
 *  - comic-ui-root     隐藏
 *
 * Cinematic：
 *  - reading-root      隐藏
 *  - cinematic-root    显示
 *  - comic-ui-root     显示
 *
 * 注意：
 * 这里只负责根容器 visibility，不参与 Reader 生命周期，
 * 不修改 ReaderFactory / ImageReader / CinematicReader。
 */
function applyModeVisibility(mode: Manifest["mode"]): void {
  const readingRoot = document.getElementById("reading-root");
  const cinematicRoot = document.getElementById("cinematic-root");
  const comicUiRoot = document.getElementById("comic-ui-root");

  const isVoice = mode === "voice";
  const isReading = mode === "reading";

  if (readingRoot) {
    readingRoot.style.display = (isVoice || isReading) ? "block" : "none";
  }

  if (cinematicRoot) {
    cinematicRoot.style.display = (isVoice || isReading) ? "none" : "block";
  }

  if (comicUiRoot) {
    comicUiRoot.style.display = (isVoice || isReading) ? "none" : "block";
  }
}

async function bootstrap(): Promise<void> {
  try {
    const params = new URLSearchParams(window.location.search);
    const manifestUrl = resolveManifestUrl();
    const manifest = await tryLoadManifest(manifestUrl);

    if (!manifest) {
      throw new Error(`[ProjectLoader] Manifest not found: ${manifestUrl}`);
    }

    // 允许 URL 参数覆盖 manifest 中的 mode
    const urlMode = params.get("mode") as any;
    if (urlMode && ["reading", "voice", "cinematic"].includes(urlMode)) {
      manifest.mode = urlMode;
    }

    const manifestBase = dirname(manifestUrl);

    console.log(
      "[bootstrap] manifestUrl=", manifestUrl,
      "manifestBase=", manifestBase,
      "bookTitle=", manifest.bookTitle,
      "mode=", manifest.mode,
      "pages=", manifest.pages.length
    );

    // Manifest 已经确定，先隔离当前模式对应的根容器。
    // Voice 不显示旧 Cinematic 全局 UI；
    // Cinematic 保持原有 UI。
    applyModeVisibility(manifest.mode);

    // 核心职责：通过 ReaderFactory 动态按需加载对应的 Reader
    const { ReaderFactory } = await import("@core/ReaderFactory");
    await ReaderFactory.init(manifest, { manifestBase });

    if (manifest.pages.length > 0) {
      const firstPageId = manifest.pages[0];
      await ReaderFactory.openPage(firstPageId);
    }
  } catch (err) {
    console.error("[bootstrap] startup failed:", err);
  }
}

/**
 * 暴露给全局或测试工具的内部接口
 */
export async function __internal_getActiveReader(): Promise<ComicReader | null> {
  const { ReaderFactory } = await import("@core/ReaderFactory");
  return ReaderFactory.getCurrentReader();
}

// 启动
bootstrap();