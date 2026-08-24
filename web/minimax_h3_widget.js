import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

/**
 * MiniMax H3 Prompt Optimizer - 一体化素材+提示词 Widget
 * 支持空状态简化、拖拽排序、删除修复
 */

console.log("[MiniMax H3] Loading integrated widget...");

const TARGET_NODES = ["LP-MiniMaxH3PromptOptimizer", "LP-MiniMaxH3Studio"];
const DATA_WIDGET = "h3_materials";
const DOM_WIDGET_NAME = "h3_materials_view";
const MODE_WIDGET = "mode";

const MODE_ASSET_RULES = {
    "T2VA": { image: 0, audio: 0, video: 0, label: "文生视频" },
    "I2VA": { image: 1, audio: 0, video: 0, label: "首帧生成" },
    "FL2VA": { image: 2, audio: 0, video: 0, label: "首尾帧生成" },
    "L2VA": { image: 1, audio: 0, video: 0, label: "尾帧生成" },
    // 对齐官方 MiniMaxH3ReferenceToVideo：ref_image ≤9 / ref_video ≤3 / ref_audio ≤3
    "Ref2VA": { image: 9, audio: 3, video: 3, label: "全能参考" },
};

// 统一素材卡尺寸（图片/音频/视频一致），不足部分黑底补齐
const CARD = 140;
const CARD_GAP = 8;
const GRID_COLS = 5;
// 节点默认宽度 = 5 卡 + 间隙 + 内边距（超出 5 个素材才换行）
const NODE_DEFAULT_W = GRID_COLS * CARD + (GRID_COLS - 1) * CARD_GAP + 88;
// 节点高度策略：内容全展开、节点自动增高，永不滚动、永不溢出
// 高度 = 上方控件区(由 last_y 决定，与节点高度无关) + 内容自然高度，单向计算无反馈循环
const NODE_DEFAULT_H = 440; // 空状态默认高度（兜底最小值）

function extractModeKey(modeText) {
    if (!modeText) return "T2VA";
    if (modeText.includes("T2VA") || modeText.includes("纯文本") || modeText.includes("文生")) return "T2VA";
    if (modeText.includes("I2VA") || modeText.includes("首帧")) return "I2VA";
    if (modeText.includes("FL2VA") || modeText.includes("首尾帧")) return "FL2VA";
    if (modeText.includes("L2VA") || modeText.includes("尾帧")) return "L2VA";
    if (modeText.includes("Ref2VA") || modeText.includes("全能") || modeText.includes("多参")) return "Ref2VA";
    return "T2VA";
}

function el(tag, className = "", text = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
}

function getThumbUrl(filename, subfolder = "") {
    let url = `/view?filename=${encodeURI(filename)}`;
    if (subfolder) url += `&subfolder=${encodeURI(subfolder)}`;
    url += `&type=input&t=${Date.now()}`;
    return api.apiURL(url);
}

async function uploadFile(file) {
    const formData = new FormData();
    formData.append("image", file);
    formData.append("type", "input");
    formData.append("overwrite", "true");
    const resp = await api.fetchApi("/upload/image", { method: "POST", body: formData });
    if (!resp.ok) throw new Error(`上传失败: ${resp.status}`);
    return await resp.json();
}

// 媒体文件（音频/视频）的 /view 访问 URL
function getMediaUrl(filename, subfolder = "") {
    let url = `/view?filename=${encodeURI(filename)}`;
    if (subfolder) url += `&subfolder=${encodeURI(subfolder)}`;
    url += `&type=input&t=${Date.now()}`;
    return api.apiURL(url);
}

function formatDur(sec) {
    if (!sec || !isFinite(sec) || sec <= 0) return "";
    const s = Math.round(sec);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// 读取音频时长（mm:ss），失败返回空串
function fetchAudioDuration(url) {
    return new Promise((resolve) => {
        const a = new Audio();
        a.preload = "metadata";
        a.onloadedmetadata = () => resolve(formatDur(a.duration));
        a.onerror = () => resolve("");
        a.src = url;
    });
}

// ============ 音频试听：全局单例播放 ============
let _playing = null; // {audio, btn, prog}

function stopPlayback() {
    if (!_playing) return;
    try { _playing.audio.pause(); } catch {}
    _playing.btn.textContent = "▶";
    _playing.prog.style.width = "0";
    _playing = null;
}

// 生成唯一 ID
let _uid = 0;
function uid() { return ++_uid; }

// 状态管理
function defaultState() {
    return { images: [], audios: [], videos: [], prompt: "", roles: "" };
}

function parseState(value) {
    if (!value) return defaultState();
    try {
        const data = typeof value === "string" ? JSON.parse(value) : (value || {});
        // 给每个素材加 uid（用于删除和排序时定位）
        const withId = (arr) => (arr || []).map((item, i) => ({ ...item, _uid: uid() }));
        return {
            images: withId(data.images),
            audios: withId(data.audios),
            videos: withId(data.videos),
            prompt: typeof data.prompt === "string" ? data.prompt : "",
            roles: typeof data.roles === "string" ? data.roles : "",
        };
    } catch { return defaultState(); }
}

function serializeState(state) {
    // 序列化时仅保留后端需要的字段（丢弃 _uid/_localUrl/_dur 等内部字段）
    const clean = (arr) => (arr || []).map(({ filename, subfolder }) => ({ filename, subfolder }));
    return JSON.stringify({
        images: clean(state.images),
        audios: clean(state.audios),
        videos: clean(state.videos),
        prompt: state.prompt,
        roles: state.roles,
    });
}

function setDataWidget(node, state) {
    const w = node.widgets?.find(item => item.name === DATA_WIDGET);
    if (!w) return;
    w.value = serializeState(state);
    w.callback?.(w.value);
    node.graph?.setDirtyCanvas?.(true, true);
}

function getAssetRules(node) {
    const modeWidget = node.widgets?.find(w => w.name === MODE_WIDGET);
    const modeKey = extractModeKey(modeWidget?.value || "");
    return MODE_ASSET_RULES[modeKey] || MODE_ASSET_RULES["T2VA"];
}

// ============================================================
// 创建 DOM 界面
// ============================================================
function createWidgetDOM(node) {
    let state = parseState(node.widgets?.find(w => w.name === DATA_WIDGET)?.value);
    let rules = getAssetRules(node);

    // 拖拽状态
    let dragSrc = null; // {type, uid}

    // 容器
    const container = el("div", "h3-widget-root");
    container.style.cssText = `
        width: 100%;
        position: relative;
        background: linear-gradient(180deg, #1c333d 0%, #172f39 100%);
        border: 1px solid #2c4d58;
        border-radius: 10px;
        padding: 10px;
        box-sizing: border-box;
        font-family: system-ui, -apple-system, "Microsoft YaHei", sans-serif;
        color: #ddd;
        display: flex;
        flex-direction: column;
        gap: 10px;
        overflow: visible;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
    `;

    // 伪元素样式（占位符亮化 + 输入框聚焦光晕）
    const styleEl = document.createElement("style");
    styleEl.textContent = `
        .h3-widget-root textarea {
            outline: none;
            transition: border-color 0.15s, box-shadow 0.15s;
        }
        .h3-widget-root textarea::placeholder { color: #56788a; }
        .h3-widget-root textarea:focus {
            border-color: #3d8296;
            box-shadow: 0 0 0 2px rgba(61,130,150,0.25);
        }
        .h3-widget-root, .h3-thumbs-wrap {
            scrollbar-width: thin;
            scrollbar-color: #2c4d58 transparent;
        }
        .h3-widget-root::-webkit-scrollbar, .h3-thumbs-wrap::-webkit-scrollbar {
            width: 8px; height: 8px;
        }
        .h3-widget-root::-webkit-scrollbar-thumb, .h3-thumbs-wrap::-webkit-scrollbar-thumb {
            background: #2c4d58; border-radius: 4px;
        }
        .h3-widget-root::-webkit-scrollbar-track, .h3-thumbs-wrap::-webkit-scrollbar-track {
            background: transparent;
        }
        /* @ 素材补全弹层 */
        .h3-mention-pop {
            position: absolute;
            z-index: 100;
            min-width: 210px;
            max-height: 240px;
            overflow-y: auto;
            background: #10222b;
            border: 1px solid #2c4d58;
            border-radius: 8px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
            padding: 4px;
            scrollbar-width: thin;
            scrollbar-color: #2c4d58 transparent;
        }
        .h3-mention-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 5px 8px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            color: #cfe3ea;
        }
        .h3-mention-item:hover, .h3-mention-item.active {
            background: #1c3a46;
        }
        .h3-mention-item img {
            width: 26px; height: 26px;
            object-fit: cover;
            border-radius: 4px;
            background: #0a1a20;
            flex: 0 0 auto;
        }
        .h3-mention-icon {
            width: 26px; height: 26px;
            display: flex; align-items: center; justify-content: center;
            border-radius: 4px;
            background: #0a1a20;
            flex: 0 0 auto;
            font-size: 13px;
        }
        .h3-mention-tag {
            font-weight: 600;
            color: #7fd4e8;
            flex: 0 0 auto;
        }
        .h3-mention-name {
            color: #7a97a3;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
    `;
    container.appendChild(styleEl);

    // 通用小节标题（左侧色条 + 标题 + 弱化说明）
    function sectionHeader(accent, title, hint) {
        const h = el("div");
        h.style.cssText = `
            display: flex; align-items: center; gap: 6px;
            font-size: 12px; line-height: 18px;
        `;
        h.innerHTML = `
            <span style="display:inline-block;width:3px;height:12px;border-radius:2px;background:${accent};flex:0 0 auto;"></span>
            <span style="font-weight:600;color:#d8e8ec;letter-spacing:0.5px;">${title}</span>
            ${hint ? `<span style="font-weight:400;color:#6f8f99;font-size:11px;">${hint}</span>` : ""}
        `;
        return h;
    }

    // === 1. 资料库 ===
    const libSection = el("div");
    libSection.style.display = "flex";
    libSection.style.flexDirection = "column";
    libSection.style.gap = "6px";
    libSection.style.flex = "0 0 auto"; // 高度保持自然值，不随节点压缩

    // 标题栏（含右侧数量胶囊）
    const libHeader = el("div");
    libHeader.style.cssText = `
        display: flex;
        align-items: center;
        justify-content: space-between;
        font-size: 12px;
        line-height: 18px;
    `;
    libHeader.innerHTML = `
        <span style="display:flex;align-items:center;gap:6px;">
            <span style="display:inline-block;width:3px;height:12px;border-radius:2px;background:#4fd1c5;flex:0 0 auto;"></span>
            <span style="font-weight:600;color:#d8e8ec;letter-spacing:0.5px;">资料库</span>
            <span style="font-weight:400;color:#6f8f99;font-size:11px;">点击插入 @标签 · 拖拽排序</span>
        </span>
        <span class="h3-lib-count" style="font-size:11px;color:#9fc3cc;font-weight:500;background:rgba(79,209,197,0.12);border:1px solid rgba(79,209,197,0.25);padding:1px 8px;border-radius:99px;"></span>
    `;
    libSection.appendChild(libHeader);

    // 素材网格区域（自然展开，全部可见，不滚动）
    const thumbsWrap = el("div", "h3-thumbs-wrap");
    thumbsWrap.style.cssText = `
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        min-height: 54px;
        padding: 8px;
        background: #0e242c;
        border: 1px solid #27434d;
        border-radius: 8px;
        align-items: flex-start;
        align-content: flex-start;
        overflow: visible;
        box-sizing: border-box;
    `;
    libSection.appendChild(thumbsWrap);

    container.appendChild(libSection);

    // === 2. 提示词 ===
    const promptWrap = el("div");
    promptWrap.style.display = "flex";
    promptWrap.style.flexDirection = "column";
    promptWrap.style.gap = "4px";
    promptWrap.style.flex = "0 0 auto"; // 高度保持自然值，不随节点压缩

    promptWrap.appendChild(sectionHeader("#e9a45e", "提示词", "支持 @图N / @音N / @视N"));

    const promptTa = el("textarea");
    promptTa.style.cssText = `
        width: 100%;
        min-height: 84px;
        max-height: 220px;
        padding: 7px 10px;
        background: #0e242c;
        border: 1px solid #27434d;
        border-radius: 8px;
        color: #dce9ed;
        font-size: 13px;
        font-family: inherit;
        resize: vertical;
        box-sizing: border-box;
        line-height: 1.55;
    `;
    promptTa.placeholder = "描述你的视频创意，点击上方素材可插入参考标签...";
    promptWrap.appendChild(promptTa);
    container.appendChild(promptWrap);

    // === 3. 角色定义 ===
    const rolesWrap = el("div");
    rolesWrap.style.display = "flex";
    rolesWrap.style.flexDirection = "column";
    rolesWrap.style.gap = "4px";
    rolesWrap.style.flex = "0 0 auto"; // 高度保持自然值，不随节点压缩

    rolesWrap.appendChild(sectionHeader("#b48ce0", "素材角色定义", "仅全能参考模式生效"));

    const rolesTa = el("textarea");
    rolesTa.style.cssText = `
        width: 100%;
        min-height: 78px;
        max-height: 150px;
        padding: 7px 10px;
        background: #0e242c;
        border: 1px solid #27434d;
        border-radius: 8px;
        color: #dce9ed;
        font-size: 12px;
        font-family: inherit;
        resize: vertical;
        box-sizing: border-box;
        line-height: 1.5;
    `;
    rolesTa.placeholder = "如：\n图1：女主角，保留面部特征\n图2：白色连衣裙\n音频1：配音声线";
    rolesWrap.appendChild(rolesTa);
    container.appendChild(rolesWrap);

    // === 内部方法 ===

    function getArray(type) {
        if (type === "image") return state.images;
        if (type === "audio") return state.audios;
        if (type === "video") return state.videos;
        return [];
    }

    function getMax(type) { return rules[type] ?? 0; }

    function getLabelPrefix(type) {
        if (type === "image") return "图";
        if (type === "audio") return "音频";
        if (type === "video") return "视频";
        return "";
    }

    function getMentionTag(type, index) {
        return `@${getLabelPrefix(type)}${index}`;
    }

    function getTypeBg(type) {
        if (type === "audio") return "#3a2f1a";
        if (type === "video") return "#1a2f3a";
        return "#2a5560";
    }

    function getTypeHoverColor(type) {
        if (type === "audio") return "#e9a45e";
        if (type === "video") return "#7cc";
        return "#6a8aba";
    }

    function getTypeEmoji(type) {
        if (type === "image") return "🖼️";
        if (type === "audio") return "🎵";
        if (type === "video") return "🎬";
        return "📄";
    }

    // 检查当前是否有任何素材
    function hasAnyAssets() {
        return state.images.length + state.audios.length + state.videos.length > 0;
    }

    // 检查当前是否允许上传任何类型
    function canUploadAny() {
        return ["image", "audio", "video"].some(t => {
            const max = getMax(t);
            return max > 0 && (max >= 99 || getArray(t).length < max);
        });
    }

    function updateCount() {
        const el = libHeader.querySelector(".h3-lib-count");
        if (!el) return;

        const parts = [];
        if (getMax("image") > 0) {
            const n = state.images.length;
            const m = getMax("image");
            parts.push(m >= 99 ? `${n}图` : `${n}/${m}图`);
        }
        if (getMax("audio") > 0) {
            const n = state.audios.length;
            const m = getMax("audio");
            parts.push(m >= 99 ? `${n}音` : `${n}/${m}音`);
        }
        if (getMax("video") > 0) {
            const n = state.videos.length;
            const m = getMax("video");
            parts.push(m >= 99 ? `${n}视` : `${n}/${m}视`);
        }
        el.textContent = parts.join(" · ");
        el.style.display = parts.length ? "" : "none";
    }

    // 构建添加按钮
    // 构建空状态的单个"+"按钮
    function buildEmptyAddButton() {
        const btn = el("div");
        btn.className = "h3-empty-add";
        btn.style.cssText = `
            width: 100%;
            height: 40px;
            border: 1.5px dashed #35606d;
            border-radius: 8px;
            display: flex;
            flex-direction: row;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            color: #6f8f99;
            transition: all 0.15s;
            gap: 8px;
        `;
        btn.innerHTML = `
            <span style="font-size:17px;line-height:1;color:#4fd1c5;">+</span>
            <span style="font-size:11px;">点击或拖拽上传素材</span>
        `;

        // 文件选择（根据当前允许的类型设置 accept）
        const fi = el("input");
        fi.type = "file";
        const accepts = [];
        if (getMax("image") > 0) accepts.push("image/*");
        if (getMax("audio") > 0) accepts.push("audio/*");
        if (getMax("video") > 0) accepts.push("video/*");
        fi.accept = accepts.join(",");
        fi.multiple = true;
        fi.style.display = "none";
        btn.appendChild(fi);

        btn.onmouseenter = () => {
            btn.style.borderColor = "#4fd1c5";
            btn.style.background = "rgba(79,209,197,0.06)";
            btn.style.color = "#9fd8d2";
        };
        btn.onmouseleave = () => {
            btn.style.borderColor = "#35606d";
            btn.style.background = "transparent";
            btn.style.color = "#6f8f99";
        };

        btn.onclick = (e) => { e.stopPropagation(); fi.click(); };
        fi.onchange = async (e) => {
            const files = Array.from(e.target.files || []);
            for (const file of files) {
                let type = null;
                if (file.type.startsWith("image/")) type = "image";
                else if (file.type.startsWith("audio/")) type = "audio";
                else if (file.type.startsWith("video/")) type = "video";
                if (type) await doUpload(file, type);
            }
            fi.value = "";
        };

        return btn;
    }

    // 图片卡：统一尺寸，object-fit: contain 黑底补齐（不裁切构图）
    function createImageCard(item, index) {
        const card = el("div", "h3-thumb");
        card.draggable = true;
        card.dataset.type = "image";
        card.dataset.uid = item._uid;
        card.style.cssText = `
            position: relative;
            width: ${CARD}px;
            height: ${CARD}px;
            border-radius: 8px;
            overflow: hidden;
            cursor: grab;
            border: 2px solid transparent;
            transition: all 0.15s;
            flex: 0 0 auto;
            background: #000;
        `;
        card.title = `点击插入 ${getMentionTag("image", index)}\n${item.filename}\n拖拽可排序`;

        const imgEl = el("img");
        // 优先使用本地 blob URL（避免中文/特殊字符文件名的服务端编码问题）
        // _localUrl 失效时回退到远程 URL
        const remoteUrl = getThumbUrl(item.filename, item.subfolder || "");
        const localUrl = item._localUrl;
        imgEl.src = localUrl || remoteUrl;
        imgEl.style.cssText = "width:100%;height:100%;object-fit:contain;display:block;pointer-events:none;";
        imgEl.draggable = false;
        imgEl.onerror = () => {
            // 本地加载失败 → 尝试远程 URL
            if (localUrl && imgEl.src === localUrl && remoteUrl) {
                imgEl.src = remoteUrl;
            } else if (!localUrl && remoteUrl && imgEl.src !== remoteUrl) {
                // 无本地 URL 且当前不是远程 URL → 尝试远程 URL
                imgEl.src = remoteUrl;
            } else {
                imgEl.style.display = "none";
            }
        };
        card.appendChild(imgEl);

        const badge = el("div");
        badge.style.cssText = `
            position:absolute;bottom:4px;left:4px;
            background:rgba(0,0,0,0.8);color:#fff;
            font-size:13px;padding:2px 8px;border-radius:5px;
            font-weight:600;white-space:nowrap;pointer-events:none;
        `;
        badge.textContent = `图${index}`;
        card.appendChild(badge);

        const typeBadge = el("div");
        typeBadge.style.cssText = `
            position:absolute;top:5px;left:5px;
            font-size:14px;
            text-shadow: 0 1px 3px rgba(0,0,0,0.9);
            pointer-events: none;z-index: 5;
        `;
        typeBadge.textContent = getTypeEmoji("image");
        card.appendChild(typeBadge);

        const del = buildDeleteBtn(item._uid, "image");
        del.style.cssText += "position:absolute;top:5px;right:5px;";
        card.appendChild(del);

        card.onmouseenter = () => {
            card.style.borderColor = getTypeHoverColor("image");
            del.style.display = "flex";
        };
        card.onmouseleave = () => {
            card.style.borderColor = "transparent";
            del.style.display = "none";
        };

        attachCardEvents(card, "image", item, index);
        return card;
    }
    function buildDeleteBtn(uid, type) {
        const del = el("div", "h3-del-btn");
        del.style.cssText = `
            width:26px;height:26px;flex:0 0 auto;
            background:rgba(231,76,60,0.92);color:#fff;
            border-radius:50%;display:none;align-items:center;justify-content:center;
            font-size:16px;font-weight:bold;line-height:1;
            cursor:pointer;z-index:10;
            border:2px solid rgba(0,0,0,0.4);box-sizing:border-box;
            box-shadow:0 2px 4px rgba(0,0,0,0.3);
        `;
        del.textContent = "×";
        del.title = "删除";
        del.onmousedown = (e) => { e.stopPropagation(); e.preventDefault(); };
        del.onclick = (e) => {
            e.stopPropagation();
            e.preventDefault();
            handleDelete(type, uid);
        };
        return del;
    }

    // 通用卡片交互：点击插入标签 + 同类型拖拽排序
    function attachCardEvents(card, type, item, index) {
        card.addEventListener("click", () => {
            if (card.dataset.justDragged === "1") {
                card.dataset.justDragged = "";
                return;
            }
            // 插入到最近激活的输入框（提示词 / 角色定义），默认提示词
            insertAtCursor(lastActiveTa, getMentionTag(type, index));
        });

        card.addEventListener("dragstart", (e) => {
            dragSrc = { type, uid: item._uid };
            card.style.opacity = "0.4";
            card.dataset.justDragged = "1";
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", `${type}:${item._uid}`);
            const v = card.querySelector("video");
            if (v) v.pause();
            setTimeout(() => { card.dataset.justDragged = ""; }, 50);
        });

        card.addEventListener("dragend", () => {
            card.style.opacity = "1";
            dragSrc = null;
            Array.from(thumbsWrap.querySelectorAll(".h3-drop-indicator")).forEach(n => n.remove());
        });

        card.addEventListener("dragover", (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            if (!dragSrc || dragSrc.type !== type) return;

            const rect = card.getBoundingClientRect();
            const midX = rect.left + rect.width / 2;
            const isAfter = e.clientX > midX;

            Array.from(thumbsWrap.querySelectorAll(".h3-drop-indicator")).forEach(n => n.remove());

            const indicator = el("div", "h3-drop-indicator");
            indicator.style.cssText = `
                width: 3px;
                height: ${card.offsetHeight}px;
                background: #6a8aba;
                border-radius: 2px;
                flex: 0 0 auto;
                margin: 0 -1px;
            `;
            if (isAfter) {
                card.parentNode.insertBefore(indicator, card.nextSibling);
            } else {
                card.parentNode.insertBefore(indicator, card);
            }
        });

        card.addEventListener("dragleave", (e) => {
            if (!thumbsWrap.contains(e.relatedTarget)) {
                Array.from(thumbsWrap.querySelectorAll(".h3-drop-indicator")).forEach(n => n.remove());
            }
        });

        card.addEventListener("drop", (e) => {
            e.preventDefault();
            e.stopPropagation();
            Array.from(thumbsWrap.querySelectorAll(".h3-drop-indicator")).forEach(n => n.remove());

            if (!dragSrc || dragSrc.type !== type) return;
            if (dragSrc.uid === item._uid) return;

            const rect = card.getBoundingClientRect();
            const midX = rect.left + rect.width / 2;
            const insertAfter = e.clientX > midX;

            handleReorder(dragSrc.type, dragSrc.uid, item._uid, insertAfter);
        });
    }

    // 音频卡：统一尺寸黑底，可试听 + 文件名 + 时长
    function createAudioCard(item, index) {
        const localUrl = item._localUrl;
        const remoteUrl = getMediaUrl(item.filename, item.subfolder || "");
        const url = localUrl || remoteUrl;

        const card = el("div", "h3-thumb");
        card.draggable = true;
        card.dataset.type = "audio";
        card.dataset.uid = item._uid;
        card.style.cssText = `
            position: relative;
            width: ${CARD}px;
            height: ${CARD}px;
            display: flex; flex-direction: column;
            align-items: center; justify-content: center; gap: 4px;
            padding: 6px 6px 10px;
            background: #0d0d0d;
            border: 2px solid transparent;
            border-radius: 8px;
            cursor: grab;
            transition: all 0.15s;
            flex: 0 0 auto;
            overflow: hidden;
            box-sizing: border-box;
        `;
        card.title = `点击插入 ${getMentionTag("audio", index)}\n${item.filename}\n▶ 试听 · 拖拽排序`;

        const playBtn = el("div");
        playBtn.style.cssText = `
            width:30px;height:30px;flex:0 0 auto;border-radius:50%;
            background:#255C69;color:#fff;
            display:flex;align-items:center;justify-content:center;
            font-size:12px;cursor:pointer;border:1px solid #3d8296;
        `;
        playBtn.textContent = "▶";

        const badge = el("span");
        badge.style.cssText = "font-weight:600;font-size:12px;color:#e9a45e;";
        badge.textContent = `🎵 音${index}`;

        const name = el("span", "", item.filename);
        name.style.cssText = "font-size:10px;color:#bbb;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";

        const dur = el("span", "", item._dur || "");
        dur.style.cssText = "font-size:10px;color:#8a7a5a;";

        card.appendChild(playBtn);
        card.appendChild(badge);
        card.appendChild(name);
        card.appendChild(dur);

        // 播放进度条
        const prog = el("div");
        prog.style.cssText = "position:absolute;left:0;bottom:0;height:2px;background:#e9a45e;width:0;pointer-events:none;";
        card.appendChild(prog);

        const del = buildDeleteBtn(item._uid, "audio");
        del.style.cssText += "position:absolute;top:5px;right:5px;";
        card.appendChild(del);

        // 异步读取时长（结果缓存在内存）
        if (!item._dur) {
            fetchAudioDuration(url).then(d => {
                if (d) {
                    item._dur = d;
                    if (dur.isConnected) dur.textContent = d;
                }
            });
        }

        // 试听（全局单例：切歌自动停上一首）
        playBtn.onclick = (e) => {
            e.stopPropagation();
            if (_playing && _playing.btn === playBtn) {
                stopPlayback();
                return;
            }
            stopPlayback();
            const audio = new Audio(url);
            _playing = { audio, btn: playBtn, prog };
            playBtn.textContent = "⏸";
            audio.ontimeupdate = () => {
                if (audio.duration > 0) {
                    prog.style.width = (audio.currentTime / audio.duration * 100) + "%";
                }
            };
            audio.onended = () => stopPlayback();
            audio.onerror = () => stopPlayback();
            audio.play().catch(() => stopPlayback());
        };

        card.onmouseenter = () => {
            card.style.borderColor = getTypeHoverColor("audio");
            del.style.display = "flex";
        };
        card.onmouseleave = () => {
            card.style.borderColor = "transparent";
            del.style.display = "none";
        };

        attachCardEvents(card, "audio", item, index);
        return card;
    }

    // 视频卡：统一尺寸，首帧画面 contain 黑底 + hover 播放预览 + 名称时长
    function createVideoCard(item, index) {
        const card = el("div", "h3-thumb");
        card.draggable = true;
        card.dataset.type = "video";
        card.dataset.uid = item._uid;
        card.style.cssText = `
            position: relative;
            width: ${CARD}px;
            height: ${CARD}px;
            border-radius: 8px;
            cursor: grab;
            border: 2px solid transparent;
            transition: all 0.15s;
            flex: 0 0 auto;
            background: #000;
            overflow: hidden;
        `;
        card.title = `点击插入 ${getMentionTag("video", index)}\n${item.filename}\n悬停预览 · 拖拽排序`;

        // 首帧画面（contain 黑底补齐，hover 时静音播放）
        const vid = el("video");
        vid.muted = true;
        vid.playsInline = true;
        vid.preload = "metadata";
        vid.draggable = false;
        vid.style.cssText = "width:100%;height:100%;object-fit:contain;display:block;background:#000;pointer-events:none;";
        const localUrl = item._localUrl;
        const remoteUrl = getMediaUrl(item.filename, item.subfolder || "");
        vid.src = localUrl || remoteUrl;
        vid.onerror = () => {
            if (localUrl && vid.src === localUrl && remoteUrl) {
                vid.src = remoteUrl;
            } else if (!localUrl && remoteUrl && vid.src !== remoteUrl) {
                vid.src = remoteUrl;
            }
        };
        card.appendChild(vid);

        // 底部信息浮层
        const overlay = el("div");
        overlay.style.cssText = `
            position:absolute;left:0;right:0;bottom:0;
            background:linear-gradient(transparent, rgba(0,0,0,0.88));
            padding:14px 6px 4px;
            pointer-events:none;
        `;
        const l1 = el("div");
        l1.style.cssText = "font-size:11px;font-weight:600;color:#7cc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
        l1.textContent = `🎬 视频${index}${item._dur ? " · " + item._dur : ""}`;
        const name = el("div", "", item.filename);
        name.style.cssText = "font-size:10px;color:#aaa;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
        overlay.appendChild(l1);
        overlay.appendChild(name);
        card.appendChild(overlay);

        const del = buildDeleteBtn(item._uid, "video");
        del.style.cssText += "position:absolute;top:5px;right:5px;";
        card.appendChild(del);

        // 首帧 + 时长
        vid.onloadedmetadata = () => {
            try { vid.currentTime = 0.01; } catch {}
            if (!item._dur && vid.duration && isFinite(vid.duration)) {
                item._dur = formatDur(vid.duration);
                if (l1.isConnected) l1.textContent = `🎬 视频${index} · ${item._dur}`;
            }
        };

        card.onmouseenter = () => {
            card.style.borderColor = getTypeHoverColor("video");
            del.style.display = "flex";
            vid.play().catch(() => {});
        };
        card.onmouseleave = () => {
            card.style.borderColor = "transparent";
            del.style.display = "none";
            vid.pause();
            try { vid.currentTime = 0.01; } catch {}
        };

        attachCardEvents(card, "video", item, index);
        return card;
    }

    // 创建单个素材卡片（按类型分发）
    function createThumb(type, item, index) {
        if (type === "image") return createImageCard(item, index);
        if (type === "audio") return createAudioCard(item, index);
        return createVideoCard(item, index);
    }

    // 删除素材（通过 uid 定位，避免索引问题）
    function handleDelete(type, uid) {
        const arr = getArray(type);
        const idx = arr.findIndex(i => i._uid === uid);
        if (idx >= 0) {
            const removed = arr.splice(idx, 1)[0];
            if (removed?._localUrl) {
                try { URL.revokeObjectURL(removed._localUrl); } catch {}
            }
        }
        renderThumbs();
        syncValue();
    }

    // 重新排序
    function handleReorder(type, srcUid, targetUid, insertAfter) {
        const arr = getArray(type);
        const srcIdx = arr.findIndex(i => i._uid === srcUid);
        const tgtIdx = arr.findIndex(i => i._uid === targetUid);

        if (srcIdx < 0 || tgtIdx < 0 || srcIdx === tgtIdx) return;

        const [srcItem] = arr.splice(srcIdx, 1);
        // 重新计算目标位置（因为删除了源，索引可能变化）
        let newTgtIdx = arr.findIndex(i => i._uid === targetUid);
        if (insertAfter) newTgtIdx += 1;
        arr.splice(newTgtIdx, 0, srcItem);

        renderThumbs();
        syncValue();
    }

    // 构建统一的小尺寸"+"添加按钮（有素材时使用，与素材卡同尺寸）
    function buildSmallAddButton() {
        const btn = el("div");
        btn.className = "h3-small-add";
        btn.style.cssText = `
            width: ${CARD}px;
            height: ${CARD}px;
            border: 1.5px dashed #35606d;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            color: #6f8f99;
            transition: all 0.15s;
            flex: 0 0 auto;
            font-size: 34px;
            line-height: 1;
            box-sizing: border-box;
            background: rgba(79,209,197,0.03);
        `;
        btn.textContent = "+";
        btn.title = "上传素材（图片/音频/视频）";

        const fi = el("input");
        fi.type = "file";
        const accepts = [];
        if (getMax("image") > 0) accepts.push("image/*");
        if (getMax("audio") > 0) accepts.push("audio/*");
        if (getMax("video") > 0) accepts.push("video/*");
        fi.accept = accepts.join(",");
        fi.multiple = true;
        fi.style.display = "none";
        btn.appendChild(fi);

        btn.onmouseenter = () => {
            btn.style.borderColor = "#4fd1c5";
            btn.style.color = "#9fd8d2";
            btn.style.background = "rgba(79,209,197,0.06)";
        };
        btn.onmouseleave = () => {
            btn.style.borderColor = "#35606d";
            btn.style.color = "#6f8f99";
            btn.style.background = "rgba(79,209,197,0.03)";
        };

        btn.onclick = (e) => { e.stopPropagation(); fi.click(); };
        fi.onchange = async (e) => {
            const files = Array.from(e.target.files || []);
            for (const file of files) {
                let type = null;
                if (file.type.startsWith("image/")) type = "image";
                else if (file.type.startsWith("audio/")) type = "audio";
                else if (file.type.startsWith("video/")) type = "video";
                if (type) await doUpload(file, type);
            }
            fi.value = "";
        };

        return btn;
    }

    // 检查是否还能上传任何类型
    function canStillUpload() {
        return ["image", "audio", "video"].some(t => {
            const max = getMax(t);
            return max > 0 && (max >= 99 || getArray(t).length < max);
        });
    }

    // 按内容自动调整节点高度：全部内容直接展开显示，不滚动、不裁切
    // 高度 = 上方控件区(last_y，与节点高度无关) + 内容自然高度
    // 三个区块均为 flex-shrink:0，其高度不受节点尺寸影响 → 计算是单向的，无反馈循环
    function autoSizeNode() {
        try {
            if (!node.setSize) return;
            // 内容自然高度 = 三个区块 + 区块间隙(2×10) + 容器内边距(2×10)
            const contentH =
                (libSection.offsetHeight || 0) +
                (promptWrap.offsetHeight || 0) +
                (rolesWrap.offsetHeight || 0) + 40;
            if (contentH <= 40) return; // 未挂载/隐藏时不处理
            // 上方控件区底边（常规 widget 的累计高度，与节点高度无关）
            const domW = node.widgets?.find(w => w.name === DOM_WIDGET_NAME);
            const aboveH = domW?.last_y ?? 0;
            // +20 = DOM widget 的上下 margin（ComfyUI domWidget.js draw 用 margin=10）
            const target = Math.max(NODE_DEFAULT_H, aboveH + contentH + 20);
            if (node.size && Math.abs(node.size[1] - target) > 2) {
                const oldH = node.size[1];
                node.setSize([Math.max(node.size[0], NODE_DEFAULT_W), target]);
                console.log("[MiniMax H3] autoSize:", oldH, "->", target, "(above:", aboveH, "content:", contentH, ")");
            }
        } catch {}
    }

    // 渲染所有素材卡片（单容器混排：图→音→视，flex 自动换行）
    function renderThumbs() {
        stopPlayback();
        thumbsWrap.innerHTML = "";

        const total = state.images.length + state.audios.length + state.videos.length;

        if (total === 0) {
            // 空状态：一个大"+"按钮
            if (canUploadAny()) {
                const emptyBtn = buildEmptyAddButton();
                thumbsWrap.appendChild(emptyBtn);
            }
        } else {
            const types = [];
            if (getMax("image") > 0) types.push("image");
            if (getMax("audio") > 0) types.push("audio");
            if (getMax("video") > 0) types.push("video");

            types.forEach(type => {
                const arr = getArray(type);
                arr.forEach((item, idx) => {
                    const thumb = createThumb(type, item, idx + 1);
                    thumbsWrap.appendChild(thumb);
                });
            });

            // 末尾一个统一的小"+"按钮（只要还有任何类型能上传就显示）
            if (canStillUpload()) {
                const addBtn = buildSmallAddButton();
                thumbsWrap.appendChild(addBtn);
            }
        }

        updateCount();
        // 素材数量变化后按内容自动调整节点高度（全展开，不滚动）
        autoSizeNode();
    }

    function insertAtCursor(textarea, text) {
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const val = textarea.value;
        const before = val.substring(0, start);
        const after = val.substring(end);
        const prefix = (before.length > 0 && !/\s/.test(before[before.length - 1])) ? " " : "";
        const newText = before + prefix + text + " " + after;
        textarea.value = newText;
        const pos = before.length + prefix.length + text.length + 1;
        textarea.selectionStart = textarea.selectionEnd = pos;
        textarea.focus();
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        textarea.dispatchEvent(new Event("change", { bubbles: true }));
        syncValue();
    }

    async function doUpload(file, type) {
        const max = getMax(type);
        const arr = getArray(type);

        if (max <= 0) return;
        if (max < 99 && arr.length >= max) {
            const typeName = type === "image" ? "图片" : type === "audio" ? "音频" : "视频";
            alert(`${typeName}最多只能上传 ${max} 个`);
            return;
        }

        const item = {
            _uid: uid(),
            filename: file.name,
            subfolder: "",
        };

        // 本地预览（图片缩略图 / 音频试听 / 视频预览零延迟）
        item._localUrl = URL.createObjectURL(file);

        arr.push(item);
        renderThumbs();
        syncValue();

        try {
            const result = await uploadFile(file);
            item.filename = result.name;
            item.subfolder = result.subfolder || "";
            renderThumbs();
            syncValue();
        } catch (e) {
            console.error("[MiniMax H3] Upload error:", e);
            const idx = arr.findIndex(i => i._uid === item._uid);
            if (idx >= 0) {
                const [removed] = arr.splice(idx, 1);
                if (removed?._localUrl) { try { URL.revokeObjectURL(removed._localUrl); } catch {} }
            }
            renderThumbs();
            syncValue();
            alert("上传失败: " + e.message);
        }
    }

    function syncValue() {
        state.prompt = promptTa.value;
        state.roles = rolesTa.value;
        setDataWidget(node, state);
    }

    promptTa.addEventListener("input", syncValue);
    promptTa.addEventListener("change", syncValue);
    rolesTa.addEventListener("input", syncValue);
    rolesTa.addEventListener("change", syncValue);

    // === @ 素材补全：两个输入框中输入 @ 即弹出已上传素材候选 ===
    let lastActiveTa = promptTa; // 素材卡片点击插入的目标框（A 功能）
    let mentionActive = false;
    let mentionStart = -1;   // '@' 在输入框中的位置
    let mentionItems = [];   // 当前候选列表
    let mentionIdx = 0;      // 键盘高亮项
    let composing = false;   // 中文输入法组合状态（组合期间不弹层）
    const mentionPop = el("div", "h3-mention-pop");
    mentionPop.style.display = "none";
    container.appendChild(mentionPop);

    const MENTION_ALIAS = {
        image: ["图", "图片", "pic", "picture", "img", "image"],
        audio: ["音", "音频", "audio", "sound"],
        video: ["视", "视频", "video", "vid"],
    };

    // 候选列表：图→音→视，与后端编号一致
    function buildMentionItems() {
        const items = [];
        state.images.forEach((it, i) => items.push({ type: "image", index: i + 1, item: it }));
        state.audios.forEach((it, i) => items.push({ type: "audio", index: i + 1, item: it }));
        state.videos.forEach((it, i) => items.push({ type: "video", index: i + 1, item: it }));
        return items;
    }

    function mentionIcon(type) {
        return type === "audio" ? "🎵" : type === "video" ? "🎬" : "🖼";
    }

    function renderMentionList() {
        mentionPop.innerHTML = "";
        mentionItems.forEach((m, i) => {
            const row = el("div", "h3-mention-item" + (i === mentionIdx ? " active" : ""));
            if (m.type === "image") {
                const img = document.createElement("img");
                img.src = m.item._localUrl || getThumbUrl(m.item.filename, m.item.subfolder || "");
                img.onerror = () => { img.src = getThumbUrl(m.item.filename, m.item.subfolder || ""); };
                row.appendChild(img);
            } else {
                row.appendChild(el("span", "h3-mention-icon", mentionIcon(m.type)));
            }
            row.appendChild(el("span", "h3-mention-tag", getMentionTag(m.type, m.index)));
            row.appendChild(el("span", "h3-mention-name", m.item.filename));
            row.addEventListener("mousedown", (e) => {
                e.preventDefault(); // 不抢输入框焦点
                applyMention(m);
            });
            row.addEventListener("mouseenter", () => {
                if (mentionIdx !== i) { mentionIdx = i; updateMentionHighlight(); }
            });
            mentionPop.appendChild(row);
        });
    }

    function updateMentionHighlight() {
        Array.from(mentionPop.children).forEach((row, i) => {
            row.classList.toggle("active", i === mentionIdx);
        });
        mentionPop.children[mentionIdx]?.scrollIntoView({ block: "nearest" });
    }

    // 弹层锚定在激活输入框正下方
    function positionMentionPop(ta) {
        mentionPop.style.left = ta.offsetLeft + "px";
        mentionPop.style.top = (ta.offsetTop + ta.offsetHeight + 4) + "px";
        mentionPop.style.width = Math.max(240, Math.round(ta.offsetWidth * 0.55)) + "px";
    }

    function closeMention() {
        mentionActive = false;
        mentionPop.style.display = "none";
    }

    // 用完整标签替换光标前的 @部分输入
    function applyMention(m) {
        const ta = lastActiveTa;
        const tag = getMentionTag(m.type, m.index);
        const caret = ta.selectionStart;
        const val = ta.value;
        const before = val.substring(0, mentionStart);
        const after = val.substring(caret);
        const needSpace = after.length > 0 && !/\s/.test(after[0]);
        ta.value = before + tag + (needSpace ? " " : "") + after;
        const pos = before.length + tag.length + (needSpace ? 1 : 0);
        ta.selectionStart = ta.selectionEnd = pos;
        ta.focus();
        ta.dispatchEvent(new Event("input", { bubbles: true }));
        syncValue();
        closeMention();
    }

    // 根据光标前内容更新弹层（与后端 parse_mentions 的别名保持一致）
    function updateMention(ta) {
        if (composing) return; // 拼音组合期间不弹
        const caret = ta.selectionStart;
        const before = ta.value.substring(0, caret);
        const m = before.match(/@([^\s@]{0,10})$/);
        if (!m) { closeMention(); return; }
        const all = buildMentionItems();
        if (all.length === 0) { closeMention(); return; }
        const q = m[1].toLowerCase();
        const mm = q.match(/^([a-z一-鿿]*)(\d*)$/);
        if (!mm) { closeMention(); return; }
        const p = mm[1], n = mm[2];
        mentionItems = all.filter(it => {
            const okP = !p || MENTION_ALIAS[it.type].some(a => a.startsWith(p));
            const okN = !n || String(it.index).startsWith(n);
            return okP && okN;
        });
        if (mentionItems.length === 0) { closeMention(); return; }
        mentionStart = caret - m[1].length - 1;
        mentionIdx = 0;
        mentionActive = true;
        renderMentionList();
        positionMentionPop(ta);
        mentionPop.style.display = "block";
    }

    function onTaKeydown(e) {
        if (!mentionActive) return;
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            e.stopPropagation();
            mentionIdx = (mentionIdx + (e.key === "ArrowDown" ? 1 : -1) + mentionItems.length) % mentionItems.length;
            updateMentionHighlight();
        } else if (e.key === "Enter" || e.key === "Tab") {
            e.preventDefault();
            e.stopPropagation();
            applyMention(mentionItems[mentionIdx]);
        } else if (e.key === "Escape") {
            e.preventDefault();
            e.stopPropagation();
            closeMention();
        }
    }

    [promptTa, rolesTa].forEach(ta => {
        ta.addEventListener("focus", () => { lastActiveTa = ta; });
        ta.addEventListener("compositionstart", () => { composing = true; });
        ta.addEventListener("compositionend", () => { composing = false; updateMention(ta); });
        ta.addEventListener("input", () => updateMention(ta));
        ta.addEventListener("click", () => updateMention(ta)); // 光标移动也刷新
        ta.addEventListener("keydown", onTaKeydown, true);    // 捕获阶段拦截，先于 ComfyUI
        ta.addEventListener("blur", () => setTimeout(closeMention, 120));
    });

    // 监听 mode 变化
    function onModeChanged() {
        rules = getAssetRules(node);

        // 截断超出限制的素材
        let truncated = false;
        ["image", "audio", "video"].forEach(type => {
            const max = getMax(type);
            const arr = getArray(type);
            if (max < 99 && arr.length > max) {
                // 释放多余图片的本地 URL
                for (let i = max; i < arr.length; i++) {
                    if (arr[i]._localUrl) { try { URL.revokeObjectURL(arr[i]._localUrl); } catch {} }
                }
                arr.length = max;
                truncated = true;
            }
        });

        if (truncated) syncValue();
        renderThumbs();
    }

    const modeWidget = node.widgets?.find(w => w.name === MODE_WIDGET);
    if (modeWidget) {
        const origCallback = modeWidget.callback;
        modeWidget.callback = function () {
            const result = origCallback?.apply(this, arguments);
            onModeChanged();
            return result;
        };
    }

    // 拖拽到整个区域也支持
    thumbsWrap.addEventListener("dragover", (e) => {
        // 如果是文件拖拽（不是内部排序）
        if (e.dataTransfer?.types?.includes("Files")) {
            e.preventDefault();
            thumbsWrap.style.borderColor = "#4fd1c5";
            thumbsWrap.style.background = "#123039";
        }
    });
    thumbsWrap.addEventListener("dragleave", (e) => {
        if (e.dataTransfer?.types?.includes("Files")) {
            thumbsWrap.style.borderColor = "#27434d";
            thumbsWrap.style.background = "#0e242c";
        }
    });
    thumbsWrap.addEventListener("drop", async (e) => {
        if (e.dataTransfer?.files?.length > 0) {
            e.preventDefault();
            e.stopPropagation();
            thumbsWrap.style.borderColor = "#27434d";
            thumbsWrap.style.background = "#0e242c";
            const files = Array.from(e.dataTransfer.files);
            for (const file of files) {
                let type = null;
                if (file.type.startsWith("image/")) type = "image";
                else if (file.type.startsWith("audio/")) type = "audio";
                else if (file.type.startsWith("video/")) type = "video";
                if (type) await doUpload(file, type);
            }
        }
    });

    // 初始
    promptTa.value = state.prompt;
    rolesTa.value = state.roles;
    renderThumbs();

    return {
        element: container,
        autoSize: autoSizeNode,
        refresh: () => {
            const s = parseState(node.widgets?.find(w => w.name === DATA_WIDGET)?.value);
            state = s;
            rules = getAssetRules(node);
            promptTa.value = s.prompt;
            rolesTa.value = s.roles;
            renderThumbs();
        },
    };
}

// ============================================================
// 附加 widget 到节点
// ============================================================
function attachWidget(node) {
    const dataWidget = node.widgets?.find(w => w.name === DATA_WIDGET);
    if (!dataWidget) {
        console.warn("[MiniMax H3] Data widget not found:", DATA_WIDGET);
        return;
    }

    dataWidget.hidden = true;
    dataWidget.computeSize = () => [0, -4];

    if (node.widgets?.some(w => w.name === DOM_WIDGET_NAME)) return;

    const dom = createWidgetDOM(node);
    const domWidget = node.addDOMWidget(
        "h3_materials_view",
        DOM_WIDGET_NAME,
        dom.element,
        {
            serialize: false,
            hideOnZoom: false,
            // VNCCS Emotion Studio 同款策略：
            // 不传 getHeight → ComfyUI 将 DOM widget 视为 canGrow，
            // 自动填满节点剩余空间；节点高度由 autoSizeNode/用户拖拽决定，
            // 内容超出时素材网格内部滚动，节点永不溢出。
            getMinHeight: () => 340,
        }
    );

    if (domWidget) {
        domWidget._h3_dom = dom;

        // rAF 节流的自动调高（每帧最多一次）
        let _rafPending = false;
        const scheduleAutoSize = () => {
            if (_rafPending) return;
            _rafPending = true;
            requestAnimationFrame(() => {
                _rafPending = false;
                dom.autoSize();
            });
        };

        // 挂载后等首帧绘制（last_y 就绪）再按内容精确调高
        scheduleAutoSize();
        setTimeout(scheduleAutoSize, 100);
        setTimeout(scheduleAutoSize, 350);

        // 每帧绘制后校正（VNCCS applySize 同款兜底）：
        // 无论哪条路径重置/漏设了节点高度，下一帧都会补正并收敛
        const origDraw = node.onDrawBackground;
        node.onDrawBackground = function (ctx) {
            scheduleAutoSize();
            return origDraw ? origDraw.apply(this, arguments) : undefined;
        };

        // 内容自然高度变化时（textarea 拖高、素材换行等）同步增高节点。
        // 区块为 flex-shrink:0，其高度不受节点尺寸影响，因此不会形成反馈循环。
        if (window.ResizeObserver) {
            const ro = new ResizeObserver(scheduleAutoSize);
            ro.observe(dom.element);
            for (const sec of dom.element.children) {
                if (sec instanceof HTMLElement && sec.tagName !== "STYLE") ro.observe(sec);
            }
        }
    }

    console.log("[MiniMax H3] Widget attached successfully");
}

// ============================================================
// 注册扩展
// ============================================================
app.registerExtension({
    name: "comfy.minimax_h3_prompt.widget",

    init() {
        // 给 H3_OUTPUT 管道类型添加连线颜色
        if (LiteGraph.link_type_colors) {
            LiteGraph.link_type_colors["H3_OUTPUT"] = "#c084fc";
        }
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        const nodeName = nodeData.name || "";
        if (!TARGET_NODES.includes(nodeName)) return;

        console.log("[MiniMax H3] Target node found:", nodeName);

        const origOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = origOnNodeCreated?.apply(this, arguments);
            try {
                attachWidget(this);
                // 兜底默认尺寸（attachWidget 内部的 autoSizeNode 会按素材行数精调高度）
                if (this.size && this.size[0] < NODE_DEFAULT_W) {
                    this.setSize([NODE_DEFAULT_W, this.size[1] || NODE_DEFAULT_H]);
                }
            } catch (e) {
                console.error("[MiniMax H3] attachWidget failed:", e);
            }
            return result;
        };

        // 任何自动尺寸计算都不会把宽度缩到 5 张素材卡以下
        // （加载已保存工作流时 onConfigure 直接恢复保存的尺寸，不走此路径）
        const origComputeSize = nodeType.prototype.computeSize;
        nodeType.prototype.computeSize = function (...args) {
            const s = origComputeSize.apply(this, args);
            if (s && s.length >= 1 && s[0] < NODE_DEFAULT_W) s[0] = NODE_DEFAULT_W;
            return s;
        };

        const origOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const result = origOnConfigure?.apply(this, arguments);
            try {
                if (!this.widgets?.some(w => w.name === DOM_WIDGET_NAME)) {
                    attachWidget(this);
                }
                const domW = this.widgets?.find(w => w.name === DOM_WIDGET_NAME);
                // refresh → renderThumbs → autoSizeNode：加载时按内容校正为全展开高度
                if (domW?._h3_dom) domW._h3_dom.refresh();
            } catch (e) {
                console.error("[MiniMax H3] onConfigure refresh failed:", e);
            }
            return result;
        };
    },
});
