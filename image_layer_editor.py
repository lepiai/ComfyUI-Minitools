import asyncio
from threading import Event
import torch
import numpy as np
from PIL import Image
import json
import os
import time
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

def apply_transform(img, t):
    img = img.convert("RGBA")

    w, h = img.size
    img = img.resize(
        (int(w * t["scaleX"]), int(h * t["scaleY"])),
        Image.Resampling.LANCZOS
    )

    if t["rotation"] != 0:
        img = img.rotate(-t["rotation"], expand=True, resample=Image.Resampling.BICUBIC)

    return img

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
                "filter_layer": ("BOOLEAN", {
                    "default": False,
                    "label_on": "过滤第一层",
                    "label_off": "不过滤",
                    "description": "开启：过滤掉第一张图片；关闭：展示所有图层，默认第一张为背景不可编辑"
                }),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("IMAGE", "IMAGE")
    RETURN_NAMES = ("ImageMerged", "ImageLayers")
    FUNCTION = "process"
    OUTPUT_NODE = True
    CATEGORY = "image/layer"
    IS_ASYNC = True

    async def process(self, images, random_seed, filter_layer, unique_id):
        # 清理旧文件
        for i in range(20):
            try:
                os.remove(os.path.join(temp_directory, f"input_layer_{unique_id}_{i}.png"))
            except:
                pass

        # 1. 预处理所有输入图片（保留原始数据，输出完整保留）
        pil_imgs = [tensor_to_pil(t) for t in images]
        total_layers = len(pil_imgs)
        default_transform = {"x":0, "y":0, "scaleX":1, "scaleY":1, "rotation":0}
        all_transforms = [default_transform for _ in range(total_layers)]  # 初始化所有图层的变换

        # 2. 确定背景索引和前端展示逻辑（核心修正：支持任意数量可编辑图层）
        if filter_layer and total_layers >= 2:
            base_index = 1  # 开启：背景为b（索引1）
            # 前端展示图层：b(背景) + 所有索引≥2的图层（c/d/...），隐藏a（索引0）
            display_imgs = [pil_imgs[base_index]]  # 先加背景b
            display_imgs += pil_imgs[2:]  # 加c/d/...（所有≥2的图层）
            # 保存前端展示的图层（b + c/d/...）
            for display_idx, img in enumerate(display_imgs):
                img.save(os.path.join(temp_directory, f"input_layer_{unique_id}_{display_idx}.png"))
            # 通知前端展示的图层数量（1个背景 + n个可编辑）
            PromptServer.instance.send_sync(
                "image_layer_editor:images_ready",
                {"node_id": unique_id, "count": len(display_imgs)}
            )
        else:
            base_index = 0  # 关闭：背景为a（索引0）
            # 前端展示所有图层（原逻辑）
            display_imgs = pil_imgs.copy()
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
            "total_layers": total_layers
        }

        while not event.is_set():
            await asyncio.sleep(0.1)

        # 4. 解析前端transforms，映射到原始图层索引（核心修正：支持多可编辑图层）
        cache_data = cache[unique_id]
        frontend_transforms = cache_data["transforms"] or []
        use_second = cache_data["filter_layer"]
        base_idx = cache_data["base_index"]
        total = cache_data["total_layers"]
        cleanup(unique_id)

        if use_second and total >= 2:
            # 开启状态：前端transforms映射规则
            # 前端索引0 → 背景b（原始1，无变换）；前端索引≥1 → 原始索引=1+前端索引（如前端1→原始2，前端2→原始3）
            for display_idx in range(len(frontend_transforms)):
                if display_idx == 0:
                    continue  # 背景b无需变换
                original_idx = 1 + display_idx  # 前端1→原始2（c），前端2→原始3（d）
                if original_idx < total:
                    all_transforms[original_idx] = frontend_transforms[display_idx]
        else:
            # 关闭状态：前端transforms直接映射原始索引（原逻辑）
            for display_idx in range(len(frontend_transforms)):
                if display_idx < total:
                    all_transforms[display_idx] = frontend_transforms[display_idx]

        # 5. 合成合并图（ImageMerged）：背景 + 所有可编辑图层（c/d/...）
        base = pil_imgs[base_idx]
        W, H = base.size
        bg = (0, 0, 0, 0)
        canvas = Image.new("RGBA", (W, H), bg)
        canvas.paste(base, (0, 0), base)
        cx, cy = W // 2, H // 2

        # 确定需要叠加的图层：开启→索引≥2（c/d/...）；关闭→索引≠0（b/c/d/...）
        if use_second and total >= 2:
            overlay_layers = list(range(2, total))  # 开启：叠加c/d/...
        else:
            overlay_layers = [i for i in range(total) if i != base_idx]  # 关闭：叠加除a外的所有

        # 叠加所有可编辑图层（支持c/d/...）
        for layer_idx in overlay_layers:
            t = all_transforms[layer_idx]
            img = apply_transform(pil_imgs[layer_idx], t)
            px = int(cx + t["x"] - img.width / 2)
            py = int(cy + t["y"] - img.height / 2)
            canvas.paste(img, (px, py), img)

        # 6. 生成输出的ImageLayers（完整保留所有输入图层，含编辑状态）
        modified_imgs = []
        for i in range(total):
            if i == base_idx:
                # 背景图层：保留原始状态（无变换）
                modified_imgs.append(pil_to_tensor(pil_imgs[i]))
            elif i in overlay_layers:
                # 可编辑图层：应用变换后生成透明背景的单独图层
                t = all_transforms[i]
                img = apply_transform(pil_imgs[i], t)
                modified_layer = Image.new("RGBA", (W, H), (0,0,0,0))
                px = int(cx + t["x"] - img.width / 2)
                py = int(cy + t["y"] - img.height / 2)
                modified_layer.paste(img, (px, py), img)
                modified_imgs.append(pil_to_tensor(modified_layer))
            else:
                # 未编辑图层（如开启状态的a）：保留原始状态
                modified_imgs.append(pil_to_tensor(pil_imgs[i]))

        # 合并所有图层张量（输出数量=输入数量，始终完整）
        modified_images = torch.cat(modified_imgs, dim=0)

        # 7. 返回结果（合并图+完整图层）
        return (pil_to_tensor(canvas), modified_images)