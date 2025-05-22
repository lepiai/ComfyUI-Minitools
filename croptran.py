import numpy as np
from PIL import Image
import torch

class CropTransparentEdges:
    # 按透明部分裁剪

    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "crop_transparent"

    CATEGORY = "MiniTools"

    def crop_transparent(self, image):
        # 输入 image 是 torch.Tensor: [B, H, W, 4]
        if isinstance(image, torch.Tensor):
            image_np = image[0].cpu().numpy()  # [H, W, 4] float32, range [0,1]
        else:
            raise Exception("Unsupported image format.")

        # 转为 [0,255] uint8
        img = (image_np * 255).astype(np.uint8)

        # 创建 PIL 图像
        if img.shape[2] == 4:
            pil_image = Image.fromarray(img, mode="RGBA")
        else:
            raise Exception("Image must have 4 channels (RGBA).")

        # 计算非透明区域的边界框
        bbox = pil_image.getbbox()
        if bbox:
            cropped_image = pil_image.crop(bbox)
        else:
            cropped_image = pil_image

        # 转为 numpy 格式，归一化回 [0,1]
        np_cropped = np.array(cropped_image).astype(np.float32) / 255.0

        # 返回 shape: [1, H, W, 4]
        return (torch.from_numpy(np_cropped).unsqueeze(0),)


class ImageToMaskWithAlpha:
    # 将图片转换成带有alpha通道的遮罩

    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "alpha": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "round": 0.001,
                    "display": "slider"
                }),
            }
        }

    RETURN_TYPES = ("MASK",)
    FUNCTION = "convert"

    CATEGORY = "MiniTools"

    def convert(self, image, alpha):
        if isinstance(image, torch.Tensor):
            img_tensor = image[0]  # shape: [H, W, C]
        else:
            raise Exception("Unsupported image format.")

        h, w, c = img_tensor.shape

        if c == 1:
            gray = img_tensor[:, :, 0]
        elif c == 3 or c == 4:
            rgb = img_tensor[:, :, :3]
            # 转为灰度值
            gray = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
        else:
            raise Exception("Unsupported number of channels in input image.")

        # 应用透明度系数
        mask = torch.clamp(gray * alpha, 0.0, 1.0)

        return (mask.unsqueeze(0),)  # shape: [1, H, W]




class NumericSlider:
    # 数字滑块

    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "float_value": ("FLOAT", {
                    "default": 0.5,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "round": 0.01,
                    "display": "slider"
                }),
                "int_value": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 999,
                    "step": 1,
                    "display": "slider"
                }),
            }
        }

    RETURN_TYPES = ("FLOAT", "INT")
    RETURN_NAMES = ("float_output", "int_output")
    FUNCTION = "output"

    CATEGORY = "MiniTools"

    def output(self, float_value, int_value):

        return (float_value, int_value)


