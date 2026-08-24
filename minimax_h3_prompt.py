# -*- coding: utf-8 -*-
"""
MiniMax H3 Prompt Optimizer ComfyUI Node
基于 MiniMax H3 官方 skills 的提示词生成与优化节点
使用阿里百炼 API 进行大模型调用
内置素材上传 + 缩略图展示 + 点击插入参考标签
输出端口与官方 MiniMaxH3ImageToVideo / MiniMaxH3ReferenceToVideo 节点对齐
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
MAX_RETRIES = 3
MAX_TOKENS = 8192
TIMEOUT = 120

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

    lines.append("")
    lines.append(
        "STRICT CONSTRAINT: The tags listed above are the ONLY reference tags that exist. "
        "NEVER invent or reference any tag outside this list — e.g. if only <Picture 1> and <Picture 2> "
        "are listed, writing <Picture 3> is FORBIDDEN. Every <Picture>/<Video>/<Audio> tag in your "
        "entire output must come from this exact list, with identical numbering."
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
def build_system_prompt(mode_key, style_key, has_images=False, has_videos=False, has_audios=False):
    # 动态注入：基础提示词 + 专业参考文档（按素材类型选择）+ 风格预设
    contextual = build_contextual_prompt(mode_key, style_key, has_images, has_videos, has_audios)

    mode_template = MODE_TEMPLATES.get(mode_key, MODE_TEMPLATES["T2VA"])
    parts = [contextual, mode_template.get("format", "")]

    return "\n\n".join(p for p in parts if p)


# ====================== 构建 User Prompt ======================
def build_user_prompt(raw_prompt, mode_key, duration, image_count, audio_count, video_count,
                      reference_roles_text, tag_inventory):
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

    parts.append("Please rewrite this description into a properly structured MiniMax H3 prompt following the format rules.")
    parts.append("Make the description detailed, vivid, and professionally written for video generation.")
    parts.append("All reference tags that appear in the user's description MUST appear in your output unchanged.")

    return "\n".join(parts)


# ====================== 调用阿里百炼 ======================
def call_bailian(api_key, base_url, model, system_prompt, user_prompt, max_tokens=None):
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=TIMEOUT)

    if max_tokens is None:
        max_tokens = MAX_TOKENS

    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.7,
            )
            content = resp.choices[0].message.content
            if content:
                return content.strip()
            last_err = "Empty response"
        except Exception as e:
            last_err = str(e)
            logger.warning(f"API attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 * (attempt + 1))

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
        return call_bailian(api_key, base_url, model, system, h3_prompt, max_tokens=max_tokens) or ""
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
    """从独立配置节点（OpenAIClientConfig）解析 api_key / model / base_url / max_tokens。
    未连接配置节点时返回 (None, 默认model, 默认base_url, 默认max_tokens)。"""
    if isinstance(llm_config, dict):
        return (llm_config.get("api_key") or "",
                llm_config.get("model") or DEFAULT_MODEL,
                llm_config.get("base_url") or DEFAULT_BASE_URL,
                llm_config.get("max_tokens") or MAX_TOKENS)
    return "", DEFAULT_MODEL, DEFAULT_BASE_URL, MAX_TOKENS


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
            }
        }

    RETURN_TYPES = ("H3_LLM_CONFIG",)
    RETURN_NAMES = ("llm_config",)
    FUNCTION = "run"
    CATEGORY = "MiniTools"
    OUTPUT_NODE = False
    DESCRIPTION = "独立 LLM 连接配置：api_key / base_url / model / max_tokens。base_url 遵循 OpenAI 兼容协议，可接入百炼、DeepSeek、OpenRouter、Ollama 等任何 OpenAI 兼容平台。"

    def run(self, api_key, base_url, model, max_tokens):
        base_url = base_url.strip() or DEFAULT_BASE_URL
        model = model.strip() or DEFAULT_MODEL
        return ({"api_key": api_key, "base_url": base_url, "model": model, "max_tokens": max_tokens},)


class MiniMaxH3PromptOptimizer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "h3_materials": ("STRING", {"default": "", "multiline": False}),
                "mode": (MODE_OPTIONS,),
                "style_preset": (STYLE_OPTIONS,),
                "duration": ("FLOAT", {"default": 5.0, "min": 1.0, "max": 15.0, "step": 0.1}),
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

    def run(self, h3_materials, mode, style_preset, duration, llm_config=None):
        api_key, model, base_url, max_tokens = _resolve_llm_config(llm_config)
        result = _run_prompt_pipeline(h3_materials, mode, style_preset, duration, api_key, model, base_url, max_tokens)

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
            result["prompt"], result["prompt_zh"], result["description"],
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


def _run_prompt_pipeline(h3_materials, mode, style_preset, duration, api_key, model, base_url, max_tokens=None):
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
            "prompt": passthrough, "prompt_zh": "",
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
    system_prompt = build_system_prompt(mode_key, style_key, has_images, has_videos, has_audios)
    user_prompt = build_user_prompt(
        raw_prompt, mode_key, duration,
        image_count, audio_count, video_count,
        parsed_roles, tag_inventory
    )

    output = call_bailian(api_key, base_url, model, system_prompt, user_prompt, max_tokens=max_tokens)

    if output is None:
        logger.warning("API 调用失败，返回原始 prompt")
        passthrough = _merge_passthrough(raw_prompt, parsed_roles)
        result.update({
            "prompt": passthrough, "prompt_zh": "",
            "description": passthrough, "soundscape": "", "music": "",
        })
        return result

    # 6.5 净化幻觉标签（只允许引用实际存在的素材）
    audio_total = standalone_offset + audio_count
    output, removed_tags = sanitize_output_tags(
        output, image_count, video_count, audio_total
    )

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

    # 10. 翻译为中文（供检查）
    prompt_zh = translate_to_chinese(api_key, base_url, model, h3_prompt, max_tokens=max_tokens) if h3_prompt else ""

    result.update({
        "prompt": h3_prompt, "prompt_zh": prompt_zh,
        "description": description, "soundscape": soundscape, "music": music,
    })
    return result


def _pack_output(h3_prompt, prompt_zh, description, soundscape, music,
                 first_frame, last_frame, ref_images,
                 pick_video, pick_video_audio, pick_audio):
    """将所有输出打包为 H3_OUTPUT dict"""
    return ({
        "prompt": h3_prompt,
        "prompt_zh": prompt_zh,
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
        "STRING", "STRING",
        "IMAGE", "IMAGE",
        "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE",
        "IMAGE", "IMAGE", "IMAGE", "IMAGE",
        "IMAGE", "IMAGE", "IMAGE",
        "AUDIO", "AUDIO", "AUDIO",
        "AUDIO", "AUDIO", "AUDIO",
    )
    RETURN_NAMES = (
        "prompt", "prompt_zh",
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
            h3_output.get("prompt_zh", ""),
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
            },
            "optional": {
                "audio_vae": ("VAE", {"tooltip": "Ref2VA 模式包含音频素材时必填"}),
                "ref_image_size": (["match", "max"], {"default": "match", "tooltip": "仅 Ref2VA 模式生效：match=适配生成分辨率，max=2048短边最佳保真"}),
                "llm_config": ("H3_LLM_CONFIG",),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "LATENT", "STRING", "STRING")
    RETURN_NAMES = ("positive", "latent", "prompt", "prompt_zh")
    FUNCTION = "run"
    CATEGORY = "MiniTools"
    OUTPUT_NODE = False
    DESCRIPTION = """
    MiniMax H3 一体化生成节点
    素材上传 + 提示词优化 + 官方 H3 conditioning/latent 生成
    一个节点替代 Optimizer + Unpacker + 官方 Image/Reference to Video
    duration（秒）自动换算为官方 length（帧，17k+5 网格）
    """

    def run(self, clip, vae, h3_materials, mode, style_preset, duration, width, height,
            audio_vae=None, ref_image_size="match", llm_config=None):
        # 1. 共享管线：素材加载 + 百炼优化 + 组装 H3 提示词
        api_key, model, base_url, max_tokens = _resolve_llm_config(llm_config)
        result = _run_prompt_pipeline(h3_materials, mode, style_preset, duration, api_key, model, base_url, max_tokens)

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
        return (cond, latent, h3_prompt, result.get("prompt_zh", ""))
