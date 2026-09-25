import asyncio
from threading import Event
import torch
import numpy as np
from PIL import Image
import json
import os
import time
import math
from aiohttp import web

from server import PromptServer
from folder_paths import temp_directory
from comfy import model_management as mm

# =========================
# Cache
# =========================
def get_cache():
    if not hasattr(PromptServer.instance, "_image_layer_editor_cache"):
        PromptServer.instance._image_layer_editor_cache = {}
    return PromptServer.instance._image_layer_editor_cache

def cleanup(node_id):
    cache = get_cache()
    cache.pop(node_id, None)

# =========================
# API
# =========================
@PromptServer.instance.routes.post("/image_layer_editor/set_transforms/{node_id}")
async def image_layer_editor_set(req):
    node_id = req.match_info["node_id"]
    data = await req.json()

    cache = get_cache()
    if node_id not in cache:
        return web.json_response({"error": "invalid node"}, status=400)

    cache[node_id]["transforms"] = json.loads(data["transforms"])
    cache[node_id]["event"].set()

    return web.json_response({"ok": True})

# =========================
# Utils
# =========================
def tensor_to_pil(t):
    if t.ndim == 4:
        t = t[0]
    arr = (t.cpu().numpy() * 255).astype(np.uint8)
    if arr.shape[2] == 3:
        return Image.fromarray(arr, "RGB").convert("RGBA")
    return Image.fromarray(arr, "RGBA")

def pil_to_tensor(img):
    arr = np.array(img).astype(np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0)

# =========================
# Node
# =========================
class ImageLayerEditor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "random_seed": ("INT", {"default": 0, "min": 0}),
                # filter_layer：专用于 qwen 分层(image layer)模型的原生 batch 输出——
                # 该模型输出的第一张往往是透明底图，开启后将其过滤（输出保留空层占位），
                # 第二张图成为锁定背景。比用 image_2/3/4 省去前置拆分 batch 的节点。
                # 注意：与 transparent_canvas 同时开启时不生效（transparent_canvas 优先）。
                "filter_layer": ("BOOLEAN", {
                    "default": False,
                    "label_on": "过滤第一层",
                    "label_off": "不过滤",
                    "description": "开启：过滤掉第一张图片（适用qwen分层模型原生输出，首张为透明底图），第二张成为锁定背景；关闭：第一张为锁定背景。注意：透明画布开启时本项不生效"
                }),
                # transparent_canvas：第0层替换为全透明画布（画布尺寸仍取第一张输入图），
                # 所有输入图片均为可编辑图层，适合透明贴纸/抠图素材的自由拼贴。
                # 与 filter_layer 同时开启时，filter_layer 被忽略（本分支优先判断）。
                "transparent_canvas": ("BOOLEAN", {
                    "default": False,
                    "label_on": "透明画布",
                    "label_off": "关闭",
                    "description": "开启：第0层设为全透明画布，所有输入图片作为可编辑图层叠加其上（适合单张透明背景图片直接移动/旋转/缩放）；关闭：使用图片作为背景"
                }),
                "max_output_size": ("INT", {
                    "default": 4096, "min": 256, "max": 16384, "step": 64,
                    "tooltip": "输出画布最长边上限（像素）。画布固定为第一张图尺寸，若超过此上限则画布等比缩小。图层超出画布的部分将在输出时裁切"
                }),
            },
            "optional": {
                "image_2": ("IMAGE", {"tooltip": "第二路独立图片输入，可与其他输入尺寸不同（推荐用本输入代替上游batch合并节点）"}),
                "image_3": ("IMAGE", {"tooltip": "第三路独立图片输入，可与其他输入尺寸不同"}),
                "image_4": ("IMAGE", {"tooltip": "第四路独立图片输入，可与其他输入尺寸不同"}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("IMAGE", "IMAGE")
    RETURN_NAMES = ("ImageMerged", "ImageLayers")
    FUNCTION = "process"
    OUTPUT_NODE = True
    CATEGORY = "image/layer"
    IS_ASYNC = True

    async def process(self, images, random_seed, filter_layer, transparent_canvas, unique_id,
                      max_output_size=4096, image_2=None, image_3=None, image_4=None):
        # 清理旧文件
        for i in range(20):
            try:
                os.remove(os.path.join(temp_directory, f"input_layer_{unique_id}_{i}.png"))
            except:
                pass

        # 1. 预处理所有输入图片（保留原始数据，输出完整保留）。
        # 多路独立输入按顺序拼接为图层，各路尺寸可不同，避免上游batch节点强行对齐尺寸造成裁剪
        pil_imgs = [tensor_to_pil(t) for t in images]
        for extra in (image_2, image_3, image_4):
            if extra is not None:
                pil_imgs += [tensor_to_pil(t) for t in extra]
        total_layers = len(pil_imgs)
        default_transform = {"x":0, "y":0, "scaleX":1, "scaleY":1, "rotation":0}
        all_transforms = [default_transform for _ in range(total_layers)]  # 初始化所有图层的变换
        # 画布以第一张图为基准尺寸，其余图层等比例缩放（保持宽高比）到能装进画布，避免裁剪与变形
        canvas_w, canvas_h = pil_imgs[0].size
        fit_imgs = []
        for im in pil_imgs:
            f = min(canvas_w / im.width, canvas_h / im.height)
            nw, nh = max(1, int(round(im.width * f))), max(1, int(round(im.height * f)))
            fit_imgs.append(im if (nw, nh) == (im.width, im.height) else im.resize((nw, nh), Image.LANCZOS))

        # 2. 确定背景索引和前端展示逻辑（支持透明画布 / 多可编辑图层两套模式）
        # 分支优先级：transparent_canvas > filter_layer > 默认。
        # 即两者同时开启时走透明画布分支，filter_layer 被忽略（第一张透明底图会保留为可编辑图层）。
        if transparent_canvas:
            # 透明画布模式：第0层=全透明画布(锁定背景)，输入图片全部作为可编辑图层(前端索引i+1)
            base_index = -1  # 无输入图层充当背景
            canvas_img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            canvas_img.save(os.path.join(temp_directory, f"input_layer_{unique_id}_0.png"))
            for i in range(total_layers):
                fit_imgs[i].save(os.path.join(temp_directory, f"input_layer_{unique_id}_{i+1}.png"))
            PromptServer.instance.send_sync(
                "image_layer_editor:images_ready",
                {"node_id": unique_id, "count": total_layers + 1}
            )
        elif filter_layer and total_layers >= 2:
            base_index = 1  # 开启：背景为b（索引1）
            # 前端展示图层：b(背景) + 所有索引≥2的图层（c/d/...），隐藏a（索引0）
            display_imgs = [fit_imgs[base_index]]  # 先加背景b
            display_imgs += fit_imgs[2:]  # 加c/d/...（所有≥2的图层）
            for display_idx, img in enumerate(display_imgs):
                img.save(os.path.join(temp_directory, f"input_layer_{unique_id}_{display_idx}.png"))
            PromptServer.instance.send_sync(
                "image_layer_editor:images_ready",
                {"node_id": unique_id, "count": len(display_imgs)}
            )
        else:
            base_index = 0  # 关闭：背景为a（索引0）
            display_imgs = fit_imgs.copy()
            for display_idx, img in enumerate(display_imgs):
                img.save(os.path.join(temp_directory, f"input_layer_{unique_id}_{display_idx}.png"))
            PromptServer.instance.send_sync(
                "image_layer_editor:images_ready",
                {"node_id": unique_id, "count": len(display_imgs)}
            )

        # 3. 挂起等待前端操作
        cache = get_cache()
        event = Event()
        cache[unique_id] = {
            "event": event,
            "transforms": None,
            "base_index": base_index,
            "filter_layer": filter_layer,
            "transparent_canvas": transparent_canvas,
            "total_layers": total_layers
        }

        while not event.is_set():
            await asyncio.sleep(0.1)

        # 4. 解析前端transforms，映射到原始图层索引
        cache_data = cache[unique_id]
        frontend_transforms = cache_data["transforms"] or []
        use_second = cache_data["filter_layer"]
        use_tc = cache_data["transparent_canvas"]
        base_idx = cache_data["base_index"]
        total = cache_data["total_layers"]
        cleanup(unique_id)

        if use_tc:
            # 透明画布模式：前端索引0=画布(无变换)，前端索引i+1 → 原始索引i
            for i in range(total):
                if i + 1 < len(frontend_transforms):
                    all_transforms[i] = frontend_transforms[i + 1]
        elif use_second and total >= 2:
            # 开启状态：前端索引0 → 背景b（原始1，无变换）；前端索引≥1 → 原始索引=1+前端索引
            for display_idx in range(len(frontend_transforms)):
                if display_idx == 0:
                    continue  # 背景b无需变换
                original_idx = 1 + display_idx
                if original_idx < total:
                    all_transforms[original_idx] = frontend_transforms[display_idx]
        else:
            # 关闭状态：前端transforms直接映射原始索引
            for display_idx in range(len(frontend_transforms)):
                if display_idx < total:
                    all_transforms[display_idx] = frontend_transforms[display_idx]

        # 5. 清洗前端变换（never trust the client）：非法值/超大缩放一律钳制，防止撑爆内存
        def _num(v, d):
            try:
                v = float(v)
                return v if math.isfinite(v) else d
            except Exception:
                return d

        for i in range(total):
            t = all_transforms[i] or {}
            all_transforms[i] = {
                "x": _num(t.get("x", 0), 0.0),
                "y": _num(t.get("y", 0), 0.0),
                "scaleX": min(100.0, max(0.01, _num(t.get("scaleX", 1), 1.0))),
                "scaleY": min(100.0, max(0.01, _num(t.get("scaleY", 1), 1.0))),
                "rotation": _num(t.get("rotation", 0), 0.0),
            }

        # 6. 固定画布 = 第一张图尺寸（可选上限钳制）；图层超出画布的部分输出时裁切
        W, H = canvas_w, canvas_h
        max_side = int(min(16384, max(256, _num(max_output_size, 4096))))
        HARD_MAX_PIXELS = 64_000_000
        kc = min(1.0, max_side / W, max_side / H, math.sqrt(HARD_MAX_PIXELS / (W * H)))
        if kc < 1.0:
            print(f"[ImageLayerEditor] 画布 {W}x{H} 超过上限 {max_side}px，已等比缩小至 "
                  f"{int(math.ceil(W * kc))}x{int(math.ceil(H * kc))}")
            W = max(1, int(math.ceil(W * kc)))
            H = max(1, int(math.ceil(H * kc)))

        if use_tc:
            overlay_layers = list(range(total))  # 所有输入图片均为可编辑图层
        else:
            if use_second and total >= 2:
                overlay_layers = list(range(2, total))  # 开启：叠加c/d/...
            else:
                overlay_layers = [i for i in range(total) if i != base_idx]  # 叠加除背景外的所有

        # 仿射渲染：把图层的 缩放/旋转/位移 一次性映射到固定画布坐标系。
        # 逐像素反向采样，输出恒为画布尺寸——超出画布自然裁切，
        # 且中间内存与缩放倍数无关（放大100倍也不会产生巨大中间图）
        def render_layer(src, t):
            w, h = src.size
            th = math.radians(t["rotation"])
            c, s = math.cos(th), math.sin(th)
            sx = max(1e-6, t["scaleX"] * kc)
            sy = max(1e-6, t["scaleY"] * kc)
            px = W / 2.0 + t["x"] * kc  # 图层中心在画布上的位置
            py = H / 2.0 + t["y"] * kc
            a = c / sx
            b = s / sx
            d = -s / sy
            e = c / sy
            off1 = w / 2.0 - (px * c + py * s) / sx
            off2 = h / 2.0 + (s * px - c * py) / sy
            return src.transform(
                (W, H), Image.AFFINE, (a, b, off1, d, e, off2),
                resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0)
            )

        # 7. 合成：背景铺底，可编辑图层按索引顺序叠加（超出画布已裁切）
        merged = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if not use_tc:
            base_img = fit_imgs[base_idx]
            if base_img.size != (W, H):
                base_img = base_img.resize((W, H), Image.Resampling.LANCZOS)
            merged.paste(base_img, (0, 0))

        # 8. 生成ImageLayers（每层独立画布尺寸透明层，含编辑状态，超出部分裁切）
        layer_renders = []
        for i in range(total):
            if (not use_tc) and i == base_idx:
                layer_renders.append(merged.copy())  # 背景层自身
                continue
            if i not in overlay_layers:
                layer_renders.append(Image.new("RGBA", (W, H), (0, 0, 0, 0)))  # 被过滤的隐藏层
                continue
            lay = render_layer(fit_imgs[i], all_transforms[i])
            merged.alpha_composite(lay)
            layer_renders.append(lay)

        modified_images = torch.cat([pil_to_tensor(x) for x in layer_renders], dim=0)

        return (pil_to_tensor(merged), modified_images)