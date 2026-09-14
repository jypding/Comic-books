export type BookMode = "reading" | "voice" | "cinematic";

export interface Manifest {
    mode: BookMode;
    bookTitle: string;
    pages: string[];
    audioDir?: string;
    imagesDir?: string;
    autoNextOnEnded?: boolean;
    bgm?: string;
    transition?: string;
}

export interface UnifiedPage {
    page_id: string;
    mode?: BookMode;
    title?: string;
    chapterTitle?: string;
    
    // Reading 专属
    image?: string;
    longText?: string;
    style?: string; // 样式块
    
    // Cinematic 专属
    model?: { glb?: string; splat?: string | null };
    camera?: { 
        blender_camera_name?: string;
        position?: { x: number; y: number; z: number };
        rotation?: { x: number; y: number; z: number };
        fov?: number;
    };
    animations?: { active_actions?: string[] };

    // 通用与兼容字段
    dialogue?: { text?: string; speaker?: string; audio?: string | null };
    dialogues?: Array<{ speaker?: string; text?: string; audio?: string | null }>;
    narration?: string; // 旁白文本
    narrationAudio?: string;
    audioFile?: string;
    effects?: Array<{ type: string; [key: string]: any }>; // 互动特效
    
    next?: string | null;
    prev?: string | null;
    autoNextOnEnded?: boolean;
    pageDuration?: number;
    
    // 兼容旧版字段
    pageId?: string;
    thumbnail?: string;
    width?: number;
    height?: number;
    media?: unknown[];
}

export interface VoiceStyle {
    style_id: string;
    mode: "voice";
    name: string;
    size: {
        panelWidth: string;
        mobilePadding: string;
        desktopPadding: string;
        borderWidth: string;
    };
    theme: {
        light: { paper: string; ink: string; gray: string; accent: string };
        dark: { paper: string; ink: string; gray: string; accent: string };
        fontFamily: string;
    };
    layout: {
        columnRatio: string;
        stackBreakpoint: string;
    };
    pagination: {
        showPageCard: boolean;
        pageCardHoldMs: number;
        pageCardTop: string;
    };
    controls: {
        buttonRadius: string;
        toolbarButtonSize: string;
        blurEffect: string;
    };
    audio: {
        defaultVolume: number;
        highlightColor: string;
        autoAdvance: boolean;
    };
}

export interface VoiceStylePackage {
    style: any;
    layout: any;
    timeline: any;
    interaction: any;
    audio: any;
    ui: any;
}

export class ProjectLoader {
    public static async loadManifest(path:string):Promise<Manifest>{
        const res = await fetch(path);
        if (!res.ok) {
            const text = await res.text();
            console.error(`[ProjectLoader] Failed to load manifest from ${path}. Status: ${res.status}. Response: ${text.substring(0, 100)}`);
            throw new Error(`Failed to load manifest: ${res.status}`);
        }
        return await res.json();
    }

    public static async loadStyle(path: string): Promise<VoiceStyle | VoiceStylePackage> {
        const res = await fetch(path);
        if (!res.ok) throw new Error(`Failed to load style: ${path}`);
        const data = await res.json();
        
        // 如果是目录形式的 package (由 .json 指向或检测路径)
        if (data.isPackage || path.endsWith('/package.json')) {
            const base = path.substring(0, path.lastIndexOf('/') + 1);
            return {
                style: data.style ? await (await fetch(base + data.style)).json() : null,
                layout: data.layout ? await (await fetch(base + data.layout)).json() : null,
                timeline: data.timeline ? await (await fetch(base + data.timeline)).json() : null,
                interaction: data.interaction ? await (await fetch(base + data.interaction)).json() : null,
                audio: data.audio ? await (await fetch(base + data.audio)).json() : null,
                ui: data.ui ? await (await fetch(base + data.ui)).json() : null
            };
        }
        return data;
    }
}
