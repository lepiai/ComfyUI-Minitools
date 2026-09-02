# -*- coding: utf-8 -*-
"""
MiniMax H3 Prompt Optimizer ComfyUI Node
基于 MiniMax H3 官方 skills 的提示词生成与优化节点
使用阿里百炼 API 进行大模型调用
内置素材上传 + 缩略图展示 + 点击插入参考标签
输出端口与官方 MiniMaxH3ImageToVideo / MiniMaxH3ReferenceToVideo 节点对齐
--@乐皮ai
"""

import os
import re
import json
import glob
import time
import shutil
import logging
import tempfile
import subprocess
import folder_paths
import numpy as np
from PIL import Image
import torch
import torchaudio
from openai import OpenAI

from .minimax_h3_presets import (
    H3_BASE_SYSTEM_PROMPT,
    MODE_TEMPLATES,
    STYLE_PRESETS,
    MODE_OPTIONS,
    MODE_KEY_MAP,
    STYLE_OPTIONS,
    STYLE_KEY_MAP,
    build_contextual_prompt,
)

# ====================== 配置常量 ======================
DEFAULT_BASE_URL = "https://llm-u7gau3h957ok5i0m.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.7-max-2026-05-20"
MAX_RETRIES = 2
MAX_TOKENS = 8192
THINK_BUDGET = 8192        # 思考模式推理 token 补偿预算（自动加在 max_tokens 上）
MAX_TOKENS_CEILING = 65536 # max_tokens 绝对上限（与 LLM Config 节点一致）
TIMEOUT = 180         # 流式读超时：慢模型（如 27B）推理停顿可能 >60s，给足余量
STREAM_TIMEOUT = 120  # 流式连接建立超时

OUTPUT_LANG_OPTIONS = ["English", "中文"]

# 视频参考处理参数
VIDEO_FPS = 24
VIDEO_MAX_SECONDS = 15
VIDEO_MAX_FRAMES = VIDEO_MAX_SECONDS * VIDEO_FPS  # 360
VIDEO_MAX_LONG_EDGE = 768
AUDIO_SAMPLE_RATE = 32000

logger = logging.getLogger("minimax_h3_prompt")


# ====================== 工具：文件定位 ======================
def resolve_input_file(filename, subfolder=""):
    input_dir = folder_paths.get_input_directory()
    candidates = []
    if subfolder:
        candidates.append(os.path.join(input_dir, subfolder, filename))
    candidates.append(os.path.join(input_dir, filename))
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


_FFMPEG_CANDIDATE = None
_FFMPEG_PROBED = False


def _ffmpeg_supports_image2(path):
    """探测 ffmpeg 是否支持 image2 muxer（精简版如 TRAE 自带的不支持）"""
    try:
        r = subprocess.run(
            [path, "-hide_banner", "-muxers"],
            capture_output=True, text=True, timeout=5,
        )
        return "image2" in (r.stdout or "")
    except Exception:
        return False


def get_ffmpeg_path():
    """
    返回支持 image2 输出的完整版 ffmpeg 路径。
    PATH 里可能同时存在精简版（如 TRAE 自带）和完整版，逐个探测取第一个可用的。
    """
    global _FFMPEG_CANDIDATE, _FFMPEG_PROBED
    if _FFMPEG_PROBED:
        return _FFMPEG_CANDIDATE
    _FFMPEG_PROBED = True

    candidates = []
    # 1. ComfyUI 自带（如果存在）
    try:
        from comfy.utils import ffmpeg_path as comfy_ffmpeg
        if comfy_ffmpeg and os.path.exists(comfy_ffmpeg):
            candidates.append(comfy_ffmpeg)
    except Exception:
        pass
    # 2. PATH 中的所有 ffmpeg（按顺序，过滤非法条目）
    for d in os.environ.get("PATH", "").split(os.pathsep):
        d = (d or "").strip().strip('"')
        if not d or not os.path.isabs(d):
            continue
        p = os.path.join(d, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if os.path.isfile(p):
            candidates.append(p)

    seen = set()
    for p in candidates:
        if p.lower() in seen:
            continue
        seen.add(p.lower())
        if _ffmpeg_supports_image2(p):
            _FFMPEG_CANDIDATE = p
            logger.info(f"H3 video decode using ffmpeg: {p}")
            return p

    logger.warning("No capable ffmpeg (with image2 muxer) found on PATH")
    return None


# ====================== 图片加载（保持原始尺寸） ======================
def load_image_from_input(filename, subfolder=""):
    filepath = resolve_input_file(filename, subfolder)
    if not filepath:
        raise FileNotFoundError(f"Image not found: {filename} (subfolder: {subfolder})")
    return Image.open(filepath)


def pil_to_tensor(img):
    img = img.convert("RGB")
    arr = np.array(img).astype(np.float32) / 255.0
    tensor = torch.from_numpy(arr)
    return tensor.unsqueeze(0)  # [1, H, W, C]


def load_single_images(images_list):
    """
    加载多张图片为独立 tensor 列表，不做任何 resize，保持原始尺寸。
    返回: [tensor [1,H,W,C] 或 None, ...]，加载失败的项为 None
    """
    tensors = []
    for img_info in images_list:
        try:
            pil_img = load_image_from_input(
                img_info.get("filename", ""),
                img_info.get("subfolder", "")
            )
            tensors.append(pil_to_tensor(pil_img))
        except Exception as e:
            logger.warning(f"Failed to load image {img_info}: {e}")
            tensors.append(None)
    return tensors


# ====================== 音频加载（PyAV，与官方 LoadAudio 一致） ======================
def _av_load_audio(filepath):
    """
    用 PyAV 解码音频流（与 ComfyUI 官方 LoadAudio 相同方案，torchcodec 在部分环境不可用）
    返回 {"waveform": [1,C,N] float32, "sample_rate": int} 或 None（无音频流）
    """
    import av
    with av.open(filepath) as af:
        if not af.streams.audio:
            return None
        stream = af.streams.audio[0]
        sr = stream.codec_context.sample_rate
        n_channels = stream.channels

        frames = []
        for frame in af.decode(streams=stream.index):
            buf = torch.from_numpy(frame.to_ndarray())
            if buf.shape[0] != n_channels:
                buf = buf.view(-1, n_channels).t()
            frames.append(buf)

        if not frames:
            return None
        wav = torch.cat(frames, dim=1)

        # PCM 整型 -> float32 归一化（与官方 f32_pcm 一致）
        if wav.dtype == torch.int16:
            wav = wav.float() / (2 ** 15)
        elif wav.dtype == torch.int32:
            wav = wav.float() / (2 ** 31)
        elif not wav.dtype.is_floating_point:
            wav = wav.float()

        return {"waveform": wav.unsqueeze(0), "sample_rate": sr}


def load_audio_file(filename, subfolder=""):
    """
    加载独立音频文件，返回 ComfyUI AUDIO dict {"waveform": [1,C,N], "sample_rate"}
    优先 PyAV，失败回退 torchaudio
    """
    filepath = resolve_input_file(filename, subfolder)
    if not filepath:
        logger.warning(f"Audio not found: {filename}")
        return None
    try:
        result = _av_load_audio(filepath)
        if result is not None:
            return result
    except ImportError:
        logger.warning("PyAV not available, fallback to torchaudio")
    except Exception as e:
        logger.warning(f"PyAV decode failed for {filename}: {e}, fallback to torchaudio")
    try:
        waveform, sr = torchaudio.load(filepath)  # [C, L]
        return {"waveform": waveform.unsqueeze(0), "sample_rate": sr}
    except Exception as e:
        logger.warning(f"Failed to load audio {filename}: {e}")
        return None


# ====================== 视频处理（ffmpeg 解码） ======================
def process_video_file(filename, subfolder=""):
    """
    用 ffmpeg 从视频文件提取帧和音轨。
    返回: (frames_tensor [T,H,W,C] 或 None, audio_dict 或 None)
    """
    filepath = resolve_input_file(filename, subfolder)
    if not filepath:
        logger.warning(f"Video not found: {filename}")
        return None, None

    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        logger.warning("ffmpeg not found, cannot decode video reference")
        return None, None

    tmp_dir = tempfile.mkdtemp(prefix="h3_ref_video_")
    try:
        # 1. 抽帧：24fps，限长 15s，PNG 序列
        frames_pattern = os.path.join(tmp_dir, "f_%06d.png")
        cmd_frames = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", filepath,
            "-vf", f"fps={VIDEO_FPS}",
            "-frames:v", str(VIDEO_MAX_FRAMES),
            "-f", "image2",
            frames_pattern,
        ]
        subprocess.run(cmd_frames, capture_output=True, timeout=120)

        frame_files = sorted(glob.glob(os.path.join(tmp_dir, "f_*.png")))
        if not frame_files:
            logger.warning(f"No frames decoded from {filename}")
            frames_tensor = None
        else:
            frames = []
            for fp in frame_files:
                img = Image.open(fp).convert("RGB")
                # 长边 > 768 时等比缩小（只缩不放）
                w, h = img.size
                if max(w, h) > VIDEO_MAX_LONG_EDGE:
                    scale = VIDEO_MAX_LONG_EDGE / max(w, h)
                    img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
                frames.append(pil_to_tensor(img)[0])  # [H,W,C]
            # 对齐官方 17k+5 帧网格（最少5帧）
            n = len(frames)
            if n >= 5:
                while n % 17 != 5:
                    n -= 1
                frames = frames[:n]
            frames_tensor = torch.stack(frames, dim=0)  # [T,H,W,C]

        # 2. 音轨：PyAV 直接从原视频解码（无音轨返回 None）
        audio_dict = None
        try:
            audio_dict = _av_load_audio(filepath)
        except Exception as e:
            logger.warning(f"Failed to extract audio from {filename}: {e}")

        return frames_tensor, audio_dict
    except Exception as e:
        logger.warning(f"Failed to process video {filename}: {e}")
        return None, None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ====================== @语法解析（含音频编号偏移） ======================
def parse_mentions(text, video_audio_labels=None, standalone_offset=0):
    """
    解析 @语法为 H3 标签。
    官方标签顺序：图片 → 视频(音轨标签紧挨其视频前) → 独立音频
    即 <Audio N> 编号 = 带音轨的视频优先占用，独立音频从 N+偏移 开始。

    @图N/@N/@picN      -> <Picture N>
    @视频N/@videoN     -> <Video N>
    @视频N音频         -> <Audio video_audio_labels[N]>
    @音频N/@audioN     -> <Audio N + standalone_offset>
    """
    if not text:
        return text
    video_audio_labels = video_audio_labels or {}

    result = text

    # 1. 视频音轨引用（必须在视频引用之前处理）
    def va_replace(m):
        num = int(m.group(1))
        label = video_audio_labels.get(num)
        return f"<Audio {label}>" if label is not None else m.group(0)
    result = re.sub(r'@(?:视频|video|vid|Video|Vid)(\d+)\s*(?:的)?(?:音频|音轨|声音|audio|sound|Audio|Sound)', va_replace, result)

    # 2. 音频引用（独立音频，带偏移）
    def audio_replace(m):
        num = int(m.group(1)) + standalone_offset
        return f'<Audio {num}>'
    result = re.sub(r'@(?:音频|audio|Audio|声音|sound|Sound)\s*(\d+)', audio_replace, result)

    # 3. 视频引用
    def video_replace(m):
        return f'<Video {m.group(1)}>'
    result = re.sub(r'@(?:视频|video|Video|vid|Vid)(\d+)', video_replace, result)

    # 4. 图片引用（可选前缀）
    def pic_replace(m):
        return f'<Picture {m.group(1)}>'
    result = re.sub(r'@(?:图|图片|pic|picture|Picture|img|image|Image)\s*(\d+)', pic_replace, result)

    # 5. 裸数字引用 @N -> <Picture N>（兜底，必须在所有带前缀模式之后）
    result = re.sub(r'@\s*(\d+)', pic_replace, result)

    return result


# ====================== 显式音色绑定：解析 / 注入 / 强制执行 ======================
_SENT_SPLIT_RE = re.compile(r'[。；;！!？?\n]')
_PIC_TAG_RE = re.compile(r'<Picture\s+(\d+)>')
_AUD_TAG_RE = re.compile(r'<Audio\s+(\d+)>')
_SPEECH_HINT_RE = re.compile(r'说|唱|音色|配音|台词|旁白|口播|speak|says|saying|voice|timbre|vocal|sing|narrat|dialogue|line', re.IGNORECASE)


def parse_explicit_voice_bindings(parsed_prompt):
    """
    从已解析的提示词中提取用户显式声明的 图<->音频 音色绑定。
    规则：同一分句内出现一对 <Picture N> + <Audio M>（顺序不限），且该句含说话语义关键词，
    即视为一条绑定声明。返回 [(picture_num, audio_num), ...]
    """
    if not parsed_prompt:
        return []
    tags = []
    for m in _PIC_TAG_RE.finditer(parsed_prompt):
        tags.append((m.start(), 'P', int(m.group(1))))
    for m in _AUD_TAG_RE.finditer(parsed_prompt):
        tags.append((m.start(), 'A', int(m.group(1))))
    if not tags:
        return []
    tags.sort()
    bindings = []
    used_aud = set()
    for pos, kind, num in tags:
        if kind != 'P':
            continue
        best = None
        for pos2, kind2, num2 in tags:
            if kind2 != 'A' or num2 in used_aud:
                continue
            seg = parsed_prompt[min(pos, pos2):max(pos, pos2)]
            if _SENT_SPLIT_RE.search(seg):
                continue
            dist = abs(pos2 - pos)
            if best is None or dist < best[0]:
                best = (dist, num2, pos2)
        if best is None:
            continue
        sent_start = 0
        for sep in _SENT_SPLIT_RE.finditer(parsed_prompt[:best[2]]):
            sent_start = sep.end()
        sent_end = len(parsed_prompt)
        for sep in _SENT_SPLIT_RE.finditer(parsed_prompt, best[2]):
            sent_end = sep.start()
            break
        sentence = parsed_prompt[sent_start:sent_end]
        if not _SPEECH_HINT_RE.search(sentence):
            continue
        used_aud.add(best[1])
        if (num, best[1]) not in bindings:
            bindings.append((num, best[1]))
    return bindings


def build_binding_directive(bindings):
    """将用户显式绑定声明转为不可忽视的英文强制指令"""
    if not bindings:
        return ""
    lines = [
        "MANDATORY VOICE BINDINGS (absolute user constraints — follow EXACTLY; swapping, reassigning, "
        "or binding these voices to any other subject is a HARD ERROR):"
    ]
    for p, a in bindings:
        lines.append(
            f"- The character defined from <Picture {p}> MUST speak using the voice timbre referenced "
            f"from <Audio {a}> — no other audio, no other subject."
        )
    lines.append(
        "In subject_definitions this means '<Audio {a}> is the voice-timbre reference for <Subject N> (Sx)' "
        "exactly as bound above; in dialogue lines the bound character cites 'referenced from <Audio {a}>' inline."
    )
    return "\n".join(lines)


_SUBJ_DEF_RE = re.compile(r'<Subject\s+(\d+)>[^\n]{0,200}?<Picture\s+(\d+)>')
_VOICE_DEF_RE = re.compile(r'<Audio\s+(\d+)>[^\n]{0,120}?voice-timbre reference for\s+<Subject\s+(\d+)>\s*\(S(\d+)\)')
_INLINE_AUDIO_RE = re.compile(r'(\(S(\d+)\)[^\n]{0,200}?referenced from\s+<Audio\s+)(\d+)(>)')


def enforce_voice_bindings(output, bindings):
    """
    确定性强制执行用户显式声明的音色绑定（不依赖 LLM 自觉）：
    1. 从 subject_definitions 解析 <Subject N> <-> <Picture P> 映射
    2. 解析当前 <Audio X> -> <Subject N> (Sx) 绑定
    3. 与用户声明 (Picture P, Audio A) 对照，构建音频编号置换并全局应用
    4. 逐条校正对话行内联 'referenced from <Audio X>' 的编号
    返回 (修正后文本, 修正说明 或 None)
    """
    if not output or not bindings:
        return output, None

    subj_pic = {}
    for m in _SUBJ_DEF_RE.finditer(output):
        subj_pic.setdefault(int(m.group(1)), int(m.group(2)))

    cur = {}
    for m in _VOICE_DEF_RE.finditer(output):
        a, s, spk = int(m.group(1)), int(m.group(2)), int(m.group(3))
        cur[a] = s

    if not subj_pic or not cur:
        return output, None

    want = {}
    for p, a in bindings:
        for s, sp in subj_pic.items():
            if sp == p:
                want[a] = s
                break
    if not want:
        return output, None

    perm = {}
    for want_a, s in want.items():
        cur_a = next((a for a, cs in cur.items() if cs == s), None)
        if cur_a is not None and cur_a != want_a:
            perm[cur_a] = want_a
    if not perm:
        return output, None

    for new in perm.values():
        if new in cur and new not in perm:
            return output, None
    if len(set(perm.values())) != len(perm):
        return output, None

    fixed = output
    for old, new in perm.items():
        fixed = fixed.replace(f'<Audio {old}>', f'<AudioTMP {new}>')
    fixed = re.sub(r'<AudioTMP (\d+)>', r'<Audio \1>', fixed)
    note = f"audio tags swapped per user bindings: {perm}"

    spk_audio = {}
    for m in _VOICE_DEF_RE.finditer(fixed):
        spk_audio[int(m.group(3))] = int(m.group(1))

    def fix_inline(m):
        spk = int(m.group(2))
        if spk in spk_audio and int(m.group(3)) != spk_audio[spk]:
            return f'{m.group(1)}{spk_audio[spk]}{m.group(4)}'
        return m.group(0)

    fixed = _INLINE_AUDIO_RE.sub(fix_inline, fixed)
    return fixed, note


# ====================== 参考角色描述处理 ======================
def parse_reference_roles(roles_text, image_count, audio_count, video_count,
                          video_audio_labels=None, standalone_offset=0):
    """
    解析用户输入的参考素材角色描述，转换为带 H3 标签的英文说明
    """
    if not roles_text or not roles_text.strip():
        return ""

    lines = roles_text.strip().split('\n')
    parsed_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parsed_lines.append(parse_mentions(line, video_audio_labels, standalone_offset))

    if not parsed_lines:
        return ""

    result = "Reference material roles (user's description of each material):\n"
    for line in parsed_lines:
        result += f"- {line}\n"
    return result


# ====================== 标签清单构建 ======================
def build_tag_inventory(image_count, video_infos, audio_count):
    """
    构建标签清单文本，明确告知 LLM 每个标签对应什么素材。
    video_infos: [{"has_audio": bool}, ...]
    """
    video_audio_labels = {}
    counter = 0
    for i, info in enumerate(video_infos):
        if info.get("has_audio"):
            counter += 1
            video_audio_labels[i + 1] = counter
    standalone_offset = counter

    if image_count + len(video_infos) + audio_count == 0:
        return (
            "STRICT CONSTRAINT: This generation has NO reference materials. "
            "Do NOT use any <Picture>, <Video>, or <Audio> tags anywhere in your output.",
            video_audio_labels,
            standalone_offset,
        )

    lines = ["Available reference tags and what each refers to (preserve these tags and numbering EXACTLY as-is in your output):"]
    for i in range(1, image_count + 1):
        lines.append(f"<Picture {i}>: uploaded reference image {i}")
    for i, info in enumerate(video_infos):
        v = i + 1
        if info.get("has_audio"):
            lines.append(f"<Audio {video_audio_labels[v]}>: the soundtrack of uploaded reference video {v} (speaks right before <Video {v}>)")
        lines.append(f"<Video {v}>: uploaded reference video {v}")
    for i in range(1, audio_count + 1):
        lines.append(f"<Audio {standalone_offset + i}>: standalone uploaded audio file {i}")
    if audio_count > 0:
        lines.append(
            "Voice-binding rule: when the user assigns an <Audio N> tag as a character's speaking voice, "
            "write in subject_definitions '<Audio N> is the voice-timbre reference for <Subject M> (Sx), "
            "containing a spoken [language] vocal layer', and cite it inline in that character's dialogue "
            "line as 'using the [voice adjectives] voice timbre referenced from <Audio N>'. "
            "Never bind voices by speaking order alone — audio numbering follows upload order while "
            "speaker IDs follow the order of vocal events, and the two may be deliberately different."
        )

    lines.append("")
    lines.append(
        "STRICT CONSTRAINT: every <Picture>/<Video>/<Audio> tag in your output must come from the list above "
        "with identical numbering — e.g. if only <Picture 1> and <Picture 2> are listed, writing <Picture 3> "
        "is FORBIDDEN. <Subject N> labels are the one exception: you create them yourself for characters, "
        "scenes, or styles abstracted from these assets (required for every speaking character), numbered in "
        "your own definition order."
    )

    return "\n".join(lines), video_audio_labels, standalone_offset


# ====================== 帧对齐指令生成 ======================
def generate_frame_alignment(mode_key, duration):
    template = MODE_TEMPLATES.get(mode_key, {})
    instruction = template.get("instruction", "")

    if mode_key == "FL2VA":
        instruction = instruction.replace("S.SS", f"{duration:.2f}")
    elif mode_key == "L2VA":
        instruction = instruction.replace("S.SS", f"{duration:.2f}")

    return instruction


# ====================== 构建 System Prompt ======================
def build_system_prompt(mode_key, style_key, has_images=False, has_videos=False, has_audios=False, output_language="English"):
    # 动态注入：基础提示词 + 专业参考文档（按素材类型选择）+ 风格预设
    contextual = build_contextual_prompt(mode_key, style_key, has_images, has_videos, has_audios)

    mode_template = MODE_TEMPLATES.get(mode_key, MODE_TEMPLATES["T2VA"])
    parts = [contextual, mode_template.get("format", "")]

    if output_language == "中文":
        parts.append(
            "OUTPUT LANGUAGE: Write ALL descriptive content (integrated_multimodal_description, "
            "detailed_description, overall_soundscape, non_diegetic_music, subject_definitions, summary, "
            "retention_analysis, etc.) in natural Simplified Chinese. "
            "However, keep the following in English unchanged: field names (e.g. integrated_multimodal_description:), "
            "section headers, reference tags (<Picture 1>, <Video 2>, <Audio 3>), shot markers ([Shot 1]), "
            "and timestamp formats (At 00:03.500). "
            "The user will write their description in Chinese — produce the final prompt in Chinese directly."
        )

    return "\n\n".join(p for p in parts if p)


# ====================== 构建 User Prompt ======================
def build_user_prompt(raw_prompt, mode_key, duration, image_count, audio_count, video_count,
                      reference_roles_text, tag_inventory, binding_directive=""):
    parts = []

    parts.append(f"Target video duration: {duration:.2f} seconds (1-15 second range).")
    parts.append(f"Generation mode: {mode_key}")
    parts.append("")

    if tag_inventory:
        parts.append(tag_inventory)
        parts.append("")

    parts.append(f"Reference counts: {image_count} image(s), {video_count} video(s), {audio_count} standalone audio(s).")
    parts.append("")

    if reference_roles_text:
        parts.append(reference_roles_text)
        parts.append("")

    parts.append("User's video description:")
    parts.append(raw_prompt)
    parts.append("")

    if binding_directive:
        parts.append(binding_directive)
        parts.append("")

    parts.append("Please rewrite this description into a properly structured MiniMax H3 prompt following the format rules.")
    parts.append("The user's words are a creative seed: preserve their subject, action, reference intents and any exact "
                 "text verbatim, but DESIGN every professional dimension they did not mention (emotional expression, "
                 "camera angle, lighting, camera movement, narrative arc, rhythm, sound, music) according to the style "
                 "guidelines — do not merely paraphrase their words. Expansion never covers reference-derived visible "
                 "content: everything shown inside uploaded images — character clothing, body features, colors, identity, "
                 "scene environments, props, and style features — comes only from the user's own words; if not described, "
                 "keep it neutral ('preserving its appearance and interior as shown in the reference') instead of "
                 "inventing details.")
    parts.append(f"Description length budget: scale to the {duration:.0f}-second duration, roughly "
                 f"{int(duration * 23)}-{int(duration * 33)} English words for the main description field. "
                 "User-provided dialogue lines are EXEMPT from this budget — always keep every line verbatim and "
                 "never trim or condense dialogue to fit; compress only non-dialogue prose.")
    parts.append("All reference tags that appear in the user's description MUST appear in your output unchanged.")

    return "\n".join(parts)


# ====================== 调用阿里百炼（流式输出 + 进度反馈） ======================
def _check_interrupt():
    """检查 ComfyUI 是否发出了中断信号"""
    try:
        import comfy.model_management as mm
        if mm.processing_interrupted():
            return True
    except Exception:
        pass
    return False


def _extract_unsupported_param(err_text):
    """
    错误自愈：从 API 400 报错中解析"不支持的参数名"。
    兼容多种平台报错格式：
    - 百炼:   Parameter 'temperature'=0.7 is not supported for kimi-k3 model.
    - OpenAI: Unrecognized request argument supplied: temperature
    - 通用:   temperature is not supported / Unknown parameter: temperature
    返回参数名（如 "temperature"），无法识别时返回 None。
    """
    if not err_text:
        return None
    lowered = err_text.lower()
    if not any(k in lowered for k in (
        "not supported", "unsupported", "unrecognized", "unknown parameter",
        "unknown argument", "invalid_parameter",
    )):
        return None
    for pat in (
        r"[Pp]arameter\s*'([^']+)'",
        r"[Uu]nrecognized request argument supplied:\s*(\S+)",
        r"[Uu]nknown (?:request )?(?:argument|parameter)[:\s]*'?([A-Za-z_][A-Za-z0-9_]*)",
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s+is not supported",
    ):
        m = re.search(pat, err_text)
        if m:
            return m.group(1)
    return None


def call_bailian(api_key, base_url, model, system_prompt, user_prompt, max_tokens=None, label="H3 Studio", enable_thinking=False, temperature=0.7):
    """
    流式调用百炼 API，实时输出进度到控制台。
    - stream=True：逐 chunk 接收，有数据流就不会超时
    - 每 200 tokens 打印一次进度
    - chunk 间隙检查 ComfyUI 中断信号
    - enable_thinking=False 时通过 extra_body 关闭思考模式（Qwen3 系列）
    - temperature < 0 时不发送 temperature 参数
    - 错误自愈：模型不支持某个参数（如 kimi-k3 不支持 temperature）时，
      自动移除该参数并立即重试，不消耗重试次数
    - 返回完整拼接结果（与之前非流式一致）
    """
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=STREAM_TIMEOUT)

    if max_tokens is None:
        max_tokens = MAX_TOKENS

    # 思考模式的推理 token 会挤占 max_tokens 预算，自动补偿额外空间，避免正文被截断
    if enable_thinking:
        max_tokens = min(max_tokens + THINK_BUDGET, MAX_TOKENS_CEILING)

    # 可自愈参数：False 表示不发送该参数
    send_flags = {
        "max_tokens": True,
        "temperature": temperature is not None and temperature >= 0,
        "enable_thinking": True,
    }

    last_err = None
    attempt = 0
    while attempt < MAX_RETRIES:
        start_time = time.time()
        try:
            parts = [f"max_tokens={max_tokens}" if send_flags["max_tokens"] else "max_tokens=默认"]
            parts.append("思考模式" if enable_thinking else "直出模式")
            parts.append(f"temp={temperature}" if send_flags["temperature"] else "temp=不发送")
            print(f"[{label}] 开始调用 {model} ({', '.join(parts)})...")

            kwargs = dict(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
                timeout=TIMEOUT,
            )
            if send_flags["max_tokens"]:
                kwargs["max_tokens"] = max_tokens
            if send_flags["enable_thinking"]:
                kwargs["extra_body"] = {"enable_thinking": enable_thinking}
            if send_flags["temperature"]:
                kwargs["temperature"] = temperature

            stream = client.chat.completions.create(**kwargs)

            chunks = []
            token_count = 0
            next_milestone = 200
            think_count = 0
            next_think_milestone = 200

            for chunk in stream:
                # 检查中断
                if _check_interrupt():
                    print(f"[{label}] 用户中断，停止生成")
                    stream.close()
                    return None

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                # 思考内容在 reasoning_content 字段，不计入正文，仅显示进度
                reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                if reasoning:
                    think_count += 1
                    if think_count >= next_think_milestone:
                        elapsed = time.time() - start_time
                        print(f"[{label}] 思考中... {think_count} tokens ({elapsed:.0f}s)")
                        next_think_milestone += 200
                if delta and delta.content:
                    chunks.append(delta.content)
                    token_count += 1
                    if token_count >= next_milestone:
                        elapsed = time.time() - start_time
                        print(f"[{label}] 生成中... {token_count} tokens ({elapsed:.0f}s)")
                        next_milestone += 200

            content = "".join(chunks).strip()
            elapsed = time.time() - start_time

            if content:
                think_note = f"，思考 {think_count} tokens" if think_count else ""
                print(f"[{label}] 生成完成：{len(content)} 字符，约 {token_count} tokens{think_note}，耗时 {elapsed:.0f}s")
                return content
            last_err = "API 返回空内容"
            print(f"[{label}] 第 {attempt + 1}/{MAX_RETRIES} 次失败（{elapsed:.0f}s）: {last_err}")

        except Exception as e:
            last_err = str(e)
            # 错误自愈：解析"参数不支持"类 400 错误，移除后立即重试（不消耗重试次数）
            bad_param = _extract_unsupported_param(last_err)
            if bad_param and bad_param in send_flags and send_flags[bad_param]:
                send_flags[bad_param] = False
                print(f"[{label}] 错误自愈：模型 {model} 不支持参数 '{bad_param}'，已自动移除并重试")
                continue
            elapsed = time.time() - start_time
            print(f"[{label}] 第 {attempt + 1}/{MAX_RETRIES} 次失败（{elapsed:.0f}s）: {str(e)[:200]}")
            logger.warning(f"API attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")

        attempt += 1
        if attempt < MAX_RETRIES:
            wait = 2 * attempt
            print(f"[{label}] {wait}s 后重试...")
            time.sleep(wait)

    print(f"[{label}] 全部重试失败: {str(last_err)[:200]}")
    logger.error(f"【全部重试失败】{last_err}")
    return None


def translate_to_chinese(api_key, base_url, model, h3_prompt, max_tokens=None):
    """
    将 H3 提示词翻译为中文（标签/时间码保持不变），供检查用
    """
    system = (
        "You are a professional translator. Translate the following MiniMax H3 video generation prompt "
        "into natural Simplified Chinese for review purposes. "
        "RULES: Keep every tag such as <Picture 1>, <Video 2>, <Audio 3> EXACTLY unchanged. "
        "Keep shot markers and cut timestamps like [Shot 1] or [Shot 2] At 00:03.500 unchanged. "
        "Keep section headers (e.g. integrated_multimodal_description:, overall_soundscape:, non_diegetic_music:, "
        "subject_definitions:, summary:, retention_analysis:, detailed_description:) in English unchanged. "
        "Output ONLY the translated text, no explanations."
    )
    try:
        trans_max = min(max_tokens or 4096, 4096)
        return call_bailian(api_key, base_url, model, system, h3_prompt, max_tokens=trans_max, label="H3 翻译") or ""
    except Exception as e:
        logger.warning(f"Translation failed: {e}")
        return ""


# ====================== 输出净化（移除幻觉标签） ======================
TAG_RE = re.compile(r'<(Picture|Video|Audio)\s+(\d+)>', re.IGNORECASE)
DEF_LINE_RE = re.compile(r'^\s*[-•*]\s*<(?:Picture|Video|Audio)\s+\d+>\s*:.*$', re.IGNORECASE | re.MULTILINE)


def _tag_is_valid(kind, num, image_count, video_count, audio_total):
    if kind == "Picture":
        return 1 <= num <= image_count
    if kind == "Video":
        return 1 <= num <= video_count
    if kind == "Audio":
        return 1 <= num <= audio_total
    return True


def sanitize_output_tags(text, image_count, video_count, audio_total):
    """
    移除 LLM 幻觉出的无效参考标签引用（如只有2张图却写了 <Picture 3>）。
    - subject_definitions 里的定义行：整行删除
    - 行内引用：连同前面的介词一起删除
    返回 (净化后文本, 被移除的标签列表)
    """
    if not text:
        return text, []

    removed = []

    # 1. 删除无效标签的整行定义
    def remove_def_line(m):
        inner = TAG_RE.search(m.group(0))
        if inner and not _tag_is_valid(inner.group(1), int(inner.group(2)), image_count, video_count, audio_total):
            removed.append(inner.group(0))
            return ""
        return m.group(0)
    text = DEF_LINE_RE.sub(remove_def_line, text)

    # 2. 删除行内无效引用（优先吃掉前面的介词，避免残留 "the dress from"）
    def remove_inline(m):
        kind, num = m.group(1), int(m.group(2))
        if _tag_is_valid(kind, num, image_count, video_count, audio_total):
            return m.group(0)
        removed.append(m.group(0))
        return ""
    text = re.sub(
        r'\s+(?:from|in|on|of|with|at|inside|as|wearing)\s+<(?:Picture|Video|Audio)\s+\d+>',
        lambda m: (lambda inner: m.group(0) if (inner and _tag_is_valid(inner.group(1), int(inner.group(2)), image_count, video_count, audio_total)) else "")(TAG_RE.search(m.group(0))),
        text,
        flags=re.IGNORECASE,
    )
    text = TAG_RE.sub(remove_inline, text)

    # 3. 清理残留：多余空格、标点前空格、连续空行
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\s+([,.;:!?)])', r'\1', text)
    text = re.sub(r'\(\s+', '(', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    if removed:
        logger.warning(f"已移除 LLM 幻觉出的无效参考标签: {sorted(set(removed))}")

    return text, removed


# ====================== 结果解析 ======================
def parse_h3_output(output_text, mode_key):
    result = {}
    if not output_text:
        return result

    mode_template = MODE_TEMPLATES.get(mode_key, MODE_TEMPLATES["T2VA"])
    fields = mode_template.get("fields", [])
    text = output_text.strip()

    for i, field in enumerate(fields):
        pattern = re.compile(
            rf'^{re.escape(field)}\s*[:：]\s*',
            re.IGNORECASE | re.MULTILINE
        )
        match = pattern.search(text)

        if match:
            start = match.end()
            end = len(text)
            for next_field in fields[i+1:]:
                next_pattern = re.compile(
                    rf'\n{re.escape(next_field)}\s*[:：]\s*',
                    re.IGNORECASE
                )
                next_match = next_pattern.search(text, start)
                if next_match:
                    end = min(end, next_match.start())
                    break
            result[field] = text[start:end].strip()
        else:
            result[field] = ""

    if not any(result.values()):
        first_field = fields[0] if fields else "integrated_multimodal_description"
        result[first_field] = text

    return result


# ====================== 解析 h3_materials widget ======================
def parse_h3_materials(value):
    """
    解析 h3_materials widget 的 JSON 值
    返回 dict: {images, audios, videos, prompt, roles}
    """
    if not value:
        return {"images": [], "audios": [], "videos": [], "prompt": "", "roles": ""}

    try:
        if isinstance(value, str):
            data = json.loads(value)
        elif isinstance(value, dict):
            data = value
        else:
            data = {"images": [], "audios": [], "videos": [], "prompt": str(value), "roles": ""}
    except (json.JSONDecodeError, TypeError):
        return {"images": [], "audios": [], "videos": [], "prompt": str(value) if value else "", "roles": ""}

    return {
        "images": data.get("images", []) or [],
        "audios": data.get("audios", []) or [],
        "videos": data.get("videos", []) or [],
        "prompt": data.get("prompt", "") or "",
        "roles": data.get("roles", "") or "",
    }


# ====================== 节点定义 ======================
def _resolve_llm_config(llm_config=None):
    """从独立配置节点（OpenAIClientConfig）解析 api_key / model / base_url / max_tokens / enable_thinking / temperature。
    未连接配置节点时返回 (None, 默认model, 默认base_url, 默认max_tokens, False, 0.7)。"""
    if isinstance(llm_config, dict):
        return (llm_config.get("api_key") or "",
                llm_config.get("model") or DEFAULT_MODEL,
                llm_config.get("base_url") or DEFAULT_BASE_URL,
                llm_config.get("max_tokens") or MAX_TOKENS,
                llm_config.get("enable_thinking", False),
                llm_config.get("temperature", 0.7))
    return "", DEFAULT_MODEL, DEFAULT_BASE_URL, MAX_TOKENS, False, 0.7


class OpenAIClientConfig:
    """
    独立 LLM 连接配置节点
    抽离 api_key / base_url / model 三项，供多个提示词节点共享
    base_url 遵循 OpenAI 兼容协议，可替换为任意 OpenAI 兼容平台
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key": ("STRING", {"default": "", "multiline": False}),
                "base_url": ("STRING", {"default": DEFAULT_BASE_URL}),
                "model": ("STRING", {"default": DEFAULT_MODEL}),
                "max_tokens": ("INT", {"default": 8192, "min": 256, "max": 65536, "step": 256, "tooltip": "LLM 输出 token 上限。百炼/云端大模型建议 8192+；本地 ollama 小模型可按实际上下文窗口设置"}),
                "enable_thinking": ("BOOLEAN", {"default": False, "tooltip": "思考模式开关。关闭可提速 40-60%（Qwen3 系列）；开启则模型先推理再输出，质量更高但更慢。百炼和 Ollama 均支持"}),
                "temperature": ("FLOAT", {"default": 0.7, "min": -1.0, "max": 2.0, "step": 0.1, "tooltip": "生成随机性。0=确定性输出，1=较多变化。设为 -1 则不发送此参数；若模型不支持（如 kimi-k3）会自动移除并重试，无需手动处理"}),
            }
        }

    RETURN_TYPES = ("H3_LLM_CONFIG",)
    RETURN_NAMES = ("llm_config",)
    FUNCTION = "run"
    CATEGORY = "MiniTools"
    OUTPUT_NODE = False
    DESCRIPTION = "独立 LLM 连接配置：api_key / base_url / model / max_tokens。base_url 遵循 OpenAI 兼容协议，可接入百炼、DeepSeek、OpenRouter、Ollama 等任何 OpenAI 兼容平台。"

    def run(self, api_key, base_url, model, max_tokens, enable_thinking=False, temperature=0.7):
        base_url = base_url.strip() or DEFAULT_BASE_URL
        model = model.strip() or DEFAULT_MODEL
        return ({"api_key": api_key, "base_url": base_url, "model": model, "max_tokens": max_tokens, "enable_thinking": enable_thinking, "temperature": temperature},)


class MiniMaxH3PromptOptimizer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "h3_materials": ("STRING", {"default": "", "multiline": False}),
                "mode": (MODE_OPTIONS,),
                "style_preset": (STYLE_OPTIONS,),
                "duration": ("FLOAT", {"default": 5.0, "min": 1.0, "max": 15.0, "step": 0.1}),
                "output_language": (OUTPUT_LANG_OPTIONS, {"default": "English", "tooltip": "LLM 直出语言：English=英文提示词，中文=中文提示词（省去翻译步骤）"}),
            },
            "optional": {
                "llm_config": ("H3_LLM_CONFIG",),
            }
        }

    RETURN_TYPES = ("H3_OUTPUT",)
    RETURN_NAMES = ("h3_output",)
    FUNCTION = "run"
    CATEGORY = "MiniTools"
    OUTPUT_NODE = False
    DESCRIPTION = """
    MiniMax H3 提示词生成与优化节点
    内置素材上传 + 缩略图展示 + 点击插入参考标签
    支持 T2VA/I2VA/FL2VA/L2VA/Ref2VA 五种生成模式
    所有输出打包为 H3_OUTPUT 管道，使用 MiniMax H3 Output Unpacker 节点拆包
    """

    def run(self, h3_materials, mode, style_preset, duration, output_language="English", llm_config=None):
        api_key, model, base_url, max_tokens, enable_thinking, temperature = _resolve_llm_config(llm_config)
        result = _run_prompt_pipeline(h3_materials, mode, style_preset, duration, api_key, model, base_url, max_tokens, output_language, enable_thinking, temperature, label="H3 Optimizer")

        mode_key = result["mode_key"]
        img_tensors = result["img_tensors"]
        video_frames = result["video_frames"]
        video_audios = result["video_audios"]
        standalone_audios = result["standalone_audios"]

        # 组装输出端口（图片/视频/音频不受 API 影响，始终输出）
        def pick(idx):
            return img_tensors[idx] if idx < len(img_tensors) else None

        first_frame = None
        last_frame = None
        ref_images = [None] * 9
        if mode_key == "I2VA":
            first_frame = pick(0)
        elif mode_key == "FL2VA":
            first_frame = pick(0)
            last_frame = pick(1)
        elif mode_key == "L2VA":
            last_frame = pick(0)
        elif mode_key == "Ref2VA":
            ref_images = [pick(i) for i in range(9)]

        def pick_video(idx):
            return video_frames[idx] if idx < len(video_frames) else None

        def pick_video_audio(idx):
            return video_audios[idx] if idx < len(video_audios) else None

        def pick_audio(idx):
            return standalone_audios[idx] if idx < len(standalone_audios) else None

        return _pack_output(
            result["prompt"], result["description"],
            result["soundscape"], result["music"],
            first_frame, last_frame, ref_images,
            pick_video, pick_video_audio, pick_audio,
        )


def _merge_passthrough(raw_prompt, parsed_roles):
    """无 LLM 透传时，将用户提示词与素材角色定义合并为最终提示词。
    parsed_roles 可能为空字符串，此时只返回提示词本身。"""
    parts = []
    if raw_prompt:
        parts.append(raw_prompt)
    if parsed_roles and parsed_roles.strip():
        parts.append(parsed_roles.strip())
    return "\n\n".join(parts)


def _run_prompt_pipeline(h3_materials, mode, style_preset, duration, api_key, model, base_url, max_tokens=None, output_language="English", enable_thinking=False, temperature=0.7, label="H3 Studio"):
    """
    共享执行管线：素材加载 + @语法解析 + 百炼优化 + 幻觉标签净化 + 组装
    供 MiniMaxH3PromptOptimizer 与 MiniMaxH3Studio 共用
    """
    # 1. 解析一体化 widget 数据
    materials = parse_h3_materials(h3_materials)
    images_list = materials["images"]
    audios_list = materials["audios"]
    videos_list = materials["videos"]
    raw_prompt_text = materials["prompt"]
    roles_text = materials["roles"]

    image_count = len(images_list)
    audio_count = len(audios_list)
    video_count = len(videos_list)

    mode_key = MODE_KEY_MAP.get(mode, "T2VA")
    style_key = STYLE_KEY_MAP.get(style_preset, "general")

    # 2. 加载素材（图片保持原始尺寸）
    img_tensors = load_single_images(images_list)          # list[[1,H,W,C] or None]

    video_frames = []   # [tensor or None]
    video_audios = []   # [audio_dict or None]
    for v in videos_list:
        frames, audio = process_video_file(v.get("filename", ""), v.get("subfolder", ""))
        video_frames.append(frames)
        video_audios.append(audio)

    standalone_audios = [load_audio_file(a.get("filename", ""), a.get("subfolder", "")) for a in audios_list]

    result = {
        "mode_key": mode_key,
        "img_tensors": img_tensors,
        "video_frames": video_frames,
        "video_audios": video_audios,
        "standalone_audios": standalone_audios,
    }

    # 3. 构建标签清单（计算音频编号偏移）
    video_infos = [{"has_audio": a is not None} for a in video_audios]
    tag_inventory, video_audio_labels, standalone_offset = build_tag_inventory(
        image_count, video_infos, audio_count
    )

    # 4. 解析 @语法（带偏移）
    parsed_prompt = parse_mentions(raw_prompt_text, video_audio_labels, standalone_offset)
    parsed_roles = parse_reference_roles(
        roles_text, image_count, audio_count, video_count,
        video_audio_labels, standalone_offset
    )

    raw_prompt = parsed_prompt.strip()

    # 5. 没有 API Key 或提示词为空：直接透传（拼入素材角色定义，保证无 LLM 时信息不丢失）
    if not api_key or not api_key.strip():
        passthrough = _merge_passthrough(raw_prompt, parsed_roles)
        result.update({
            "prompt": passthrough,
            "description": passthrough, "soundscape": "", "music": "",
        })
        return result

    api_key = api_key.strip()
    model = model.strip() or DEFAULT_MODEL
    base_url = base_url.strip() or DEFAULT_BASE_URL

    # 6. 构建 prompts 并调用 API（根据素材类型动态注入专业参考文档）
    has_images = image_count > 0
    has_videos = video_count > 0
    has_audios = audio_count > 0 or any(a is not None for a in video_audios)
    system_prompt = build_system_prompt(mode_key, style_key, has_images, has_videos, has_audios, output_language)

    # 6.0 解析用户显式声明的音色绑定，注入强制指令
    explicit_bindings = parse_explicit_voice_bindings(raw_prompt)
    binding_directive = build_binding_directive(explicit_bindings)
    user_prompt = build_user_prompt(
        raw_prompt, mode_key, duration,
        image_count, audio_count, video_count,
        parsed_roles, tag_inventory, binding_directive
    )

    output = call_bailian(api_key, base_url, model, system_prompt, user_prompt, max_tokens=max_tokens, label=label, enable_thinking=enable_thinking, temperature=temperature)

    if output is None:
        logger.warning("API 调用失败，返回原始 prompt")
        passthrough = _merge_passthrough(raw_prompt, parsed_roles)
        result.update({
            "prompt": passthrough,
            "description": passthrough, "soundscape": "", "music": "",
        })
        return result

    # 6.5 净化幻觉标签（只允许引用实际存在的素材）
    audio_total = standalone_offset + audio_count
    output, removed_tags = sanitize_output_tags(
        output, image_count, video_count, audio_total
    )

    # 6.6 确定性强制音色绑定（用户显式声明优先于 LLM 输出）
    if explicit_bindings:
        output, binding_fix = enforce_voice_bindings(output, explicit_bindings)
        if binding_fix:
            print(f"[{label}] 音色绑定校正: {binding_fix}")

    # 7. 解析输出
    parsed = parse_h3_output(output, mode_key)

    # 8. 帧对齐指令（FL2VA 只有1张图时降级为首帧指令，避免引用不存在的 Picture 2）
    alignment_instruction = ""
    if mode_key in ("I2VA", "FL2VA", "L2VA") and image_count > 0:
        effective_mode = "I2VA" if (mode_key == "FL2VA" and image_count < 2) else mode_key
        alignment_instruction = generate_frame_alignment(effective_mode, duration)

    # 9. 组装完整 h3_prompt
    mode_template = MODE_TEMPLATES.get(mode_key, MODE_TEMPLATES["T2VA"])
    fields = mode_template.get("fields", [])

    h3_prompt_parts = []
    if alignment_instruction:
        h3_prompt_parts.append(alignment_instruction)
        h3_prompt_parts.append("")
    for field in fields:
        content = parsed.get(field, "")
        if content:
            h3_prompt_parts.append(f"{field}:")
            h3_prompt_parts.append(content)
            h3_prompt_parts.append("")
    h3_prompt = "\n".join(h3_prompt_parts).strip()

    desc_field = "detailed_description" if mode_key == "Ref2VA" else "integrated_multimodal_description"
    description = parsed.get(desc_field, "")
    soundscape = parsed.get("overall_soundscape", "")
    music = parsed.get("non_diegetic_music", "")

    if not h3_prompt and output:
        h3_prompt = output
        description = output

    result.update({
        "prompt": h3_prompt,
        "description": description, "soundscape": soundscape, "music": music,
    })
    return result


def _pack_output(h3_prompt, description, soundscape, music,
                 first_frame, last_frame, ref_images,
                 pick_video, pick_video_audio, pick_audio):
    """将所有输出打包为 H3_OUTPUT dict"""
    return ({
        "prompt": h3_prompt,
        "description": description,
        "soundscape": soundscape,
        "music": music,
        "first_frame": first_frame,
        "last_frame": last_frame,
        "ref_image_1": ref_images[0], "ref_image_2": ref_images[1], "ref_image_3": ref_images[2],
        "ref_image_4": ref_images[3], "ref_image_5": ref_images[4], "ref_image_6": ref_images[5],
        "ref_image_7": ref_images[6], "ref_image_8": ref_images[7], "ref_image_9": ref_images[8],
        "ref_video_1": pick_video(0), "ref_video_2": pick_video(1), "ref_video_3": pick_video(2),
        "ref_video_audio_1": pick_video_audio(0), "ref_video_audio_2": pick_video_audio(1), "ref_video_audio_3": pick_video_audio(2),
        "ref_audio_1": pick_audio(0), "ref_audio_2": pick_audio(1), "ref_audio_3": pick_audio(2),
    },)


# ====================== 输出拆包节点 ======================
class MiniMaxH3OutputUnpacker:
    """将 H3_OUTPUT 管道拆包为各个独立输出端口"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "h3_output": ("H3_OUTPUT",),
            }
        }

    RETURN_TYPES = (
        "STRING",
        "IMAGE", "IMAGE",
        "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE",
        "IMAGE", "IMAGE", "IMAGE", "IMAGE",
        "IMAGE", "IMAGE", "IMAGE",
        "AUDIO", "AUDIO", "AUDIO",
        "AUDIO", "AUDIO", "AUDIO",
    )
    RETURN_NAMES = (
        "prompt",
        "first_frame", "last_frame",
        "ref_image_1", "ref_image_2", "ref_image_3", "ref_image_4", "ref_image_5",
        "ref_image_6", "ref_image_7", "ref_image_8", "ref_image_9",
        "ref_video_1", "ref_video_2", "ref_video_3",
        "ref_video_audio_1", "ref_video_audio_2", "ref_video_audio_3",
        "ref_audio_1", "ref_audio_2", "ref_audio_3",
    )
    FUNCTION = "unpack"
    CATEGORY = "MiniTools"
    OUTPUT_NODE = False
    DESCRIPTION = """
    MiniMax H3 输出拆包节点
    将 H3_OUTPUT 管道拆分为各个独立输出端口
    输出端口与官方 MiniMaxH3ImageToVideo / MiniMaxH3ReferenceToVideo 节点对齐
    """

    def unpack(self, h3_output):
        if not h3_output or not isinstance(h3_output, dict):
            h3_output = {}

        return (
            h3_output.get("prompt", ""),
            h3_output.get("first_frame"),
            h3_output.get("last_frame"),
            h3_output.get("ref_image_1"), h3_output.get("ref_image_2"), h3_output.get("ref_image_3"),
            h3_output.get("ref_image_4"), h3_output.get("ref_image_5"), h3_output.get("ref_image_6"),
            h3_output.get("ref_image_7"), h3_output.get("ref_image_8"), h3_output.get("ref_image_9"),
            h3_output.get("ref_video_1"), h3_output.get("ref_video_2"), h3_output.get("ref_video_3"),
            h3_output.get("ref_video_audio_1"), h3_output.get("ref_video_audio_2"), h3_output.get("ref_video_audio_3"),
            h3_output.get("ref_audio_1"), h3_output.get("ref_audio_2"), h3_output.get("ref_audio_3"),
        )


# ====================== 一体化生成节点 ======================
def _get_official_h3_node(node_id):
    """动态获取 ComfyUI 内置 MiniMax H3 节点类（V3 节点注册于 NODE_CLASS_MAPPINGS）"""
    import nodes as comfy_nodes
    cls = comfy_nodes.NODE_CLASS_MAPPINGS.get(node_id)
    if cls is None or not hasattr(cls, "execute"):
        raise RuntimeError(
            f"未找到 ComfyUI 内置节点 {node_id}，"
            f"请升级到包含 MiniMax H3 官方节点的 ComfyUI 版本"
        )
    return cls


def duration_to_length(duration):
    """秒 -> 帧数（24fps，向上对齐官方 17k+5 帧网格）"""
    n = max(5, int(round(duration * VIDEO_FPS)))
    while n % 17 != 5:
        n += 1
    return n


class MiniMaxH3Studio:
    """
    一体化节点：素材上传 + 提示词优化 + 官方 H3 conditioning/latent 生成
    内部调用官方 MiniMaxH3ImageToVideo / MiniMaxH3ReferenceToVideo
    替代 Optimizer + Unpacker + 官方节点 三件套
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "vae": ("VAE",),
                "h3_materials": ("STRING", {"default": "", "multiline": False}),
                "mode": (MODE_OPTIONS,),
                "style_preset": (STYLE_OPTIONS,),
                "duration": ("FLOAT", {"default": 5.0, "min": 1.0, "max": 15.0, "step": 0.1}),
                "width": ("INT", {"default": 1344, "min": 32, "max": 16384, "step": 32}),
                "height": ("INT", {"default": 768, "min": 32, "max": 16384, "step": 32}),
                "output_language": (OUTPUT_LANG_OPTIONS, {"default": "English", "tooltip": "LLM 直出语言：English=英文提示词，中文=中文提示词（省去翻译步骤）"}),
            },
            "optional": {
                "audio_vae": ("VAE", {"tooltip": "Ref2VA 模式包含音频素材时必填"}),
                "ref_image_size": (["match", "max"], {"default": "match", "tooltip": "仅 Ref2VA 模式生效：match=适配生成分辨率，max=2048短边最佳保真"}),
                "llm_config": ("H3_LLM_CONFIG",),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "LATENT", "STRING")
    RETURN_NAMES = ("positive", "latent", "prompt")
    FUNCTION = "run"
    CATEGORY = "MiniTools"
    OUTPUT_NODE = False
    DESCRIPTION = """
    MiniMax H3 一体化生成节点
    素材上传 + 提示词优化 + 官方 H3 conditioning/latent 生成
    一个节点替代 Optimizer + Unpacker + 官方 Image/Reference to Video
    duration（秒）自动换算为官方 length（帧，17k+5 网格）
    """

    def run(self, clip, vae, h3_materials, mode, style_preset, duration, width, height, output_language="English",
            audio_vae=None, ref_image_size="match", llm_config=None):
        # 1. 共享管线：素材加载 + 百炼优化 + 组装 H3 提示词
        api_key, model, base_url, max_tokens, enable_thinking, temperature = _resolve_llm_config(llm_config)
        result = _run_prompt_pipeline(h3_materials, mode, style_preset, duration, api_key, model, base_url, max_tokens, output_language, enable_thinking, temperature)

        h3_prompt = (result.get("prompt") or "").strip()
        if not h3_prompt:
            raise RuntimeError("提示词为空：请在提示词输入框中描述视频创意")

        mode_key = result["mode_key"]
        length = duration_to_length(duration)
        logger.info(f"[H3 Studio] mode={mode_key} length={length} frames ({length / VIDEO_FPS:.2f}s)")

        # 2. 按 mode 路由到官方节点
        if mode_key == "Ref2VA":
            has_audio = any(a is not None for a in result["video_audios"]) or \
                        any(a is not None for a in result["standalone_audios"])
            if has_audio and audio_vae is None:
                raise RuntimeError(
                    "Ref2VA 模式包含音频素材，需要连接 audio_vae 输入"
                )

            ref_images = {f"ref_image_{i + 1}": t for i, t in enumerate(result["img_tensors"]) if t is not None}
            ref_videos = {}
            ref_video_audios = {}
            for i, frames in enumerate(result["video_frames"]):
                if frames is None:
                    continue
                ref_videos[f"ref_video_{i + 1}"] = frames
                audio = result["video_audios"][i]
                if audio is not None:
                    ref_video_audios[f"ref_video_audio_{i + 1}"] = audio
            ref_audios = {f"ref_audio_{i + 1}": a for i, a in enumerate(result["standalone_audios"]) if a is not None}

            cls = _get_official_h3_node("MiniMaxH3ReferenceToVideo")
            out = cls.execute(
                clip=clip, vae=vae, audio_vae=audio_vae, prompt=h3_prompt,
                width=width, height=height, length=length, ref_image_size=ref_image_size,
                ref_images=ref_images or None, ref_videos=ref_videos or None,
                ref_video_audios=ref_video_audios or None, ref_audios=ref_audios or None,
            )
        else:
            tensors = result["img_tensors"]

            def pick(idx):
                return tensors[idx] if idx < len(tensors) else None

            first_frame = last_frame = None
            if mode_key == "I2VA":
                first_frame = pick(0)
            elif mode_key == "FL2VA":
                first_frame = pick(0)
                last_frame = pick(1)
            elif mode_key == "L2VA":
                last_frame = pick(0)

            cls = _get_official_h3_node("MiniMaxH3ImageToVideo")
            out = cls.execute(
                clip=clip, vae=vae, prompt=h3_prompt,
                width=width, height=height, length=length,
                first_frame=first_frame, last_frame=last_frame,
            )

        # 3. 解包官方 NodeOutput（.args = (conditioning, latent)）
        cond, latent = out.args
        return (cond, latent, h3_prompt)
