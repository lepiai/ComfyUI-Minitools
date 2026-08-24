import torch
import comfy.model_management

class AspectRatioSelectorWithLatent:

    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        """
        Returns input configuration with aspect ratio dropdown and batch size.
        """
        return {
            "required": {
                "aspect_ratio": (
                    ["1:1(1328, 1328)", "16:9(1664, 928)", "9:16(928, 1664)", "4:3(1472, 1140)", "3:4(1140, 1472)", "3:2(1584, 1056)", "2:3(1056, 1584)"],
                    {
                        "default": "1:1(1328, 1328)",  # 修正默认值与选项匹配
                        "tooltip": "Select an aspect ratio to get corresponding dimensions and latent"
                    }
                ),
                "batch_size": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 4096,
                        "step": 1,
                        "tooltip": "Number of samples in the latent batch (controls execution count)"
                    }
                )
            }
        }

    RETURN_TYPES = ("LATENT", "INT", "INT")
    RETURN_NAMES = ("latent","width", "height")
    FUNCTION = "get_dimensions_and_latent"
    CATEGORY = "MiniTools"

    def get_dimensions_and_latent(self, aspect_ratio, batch_size):
        # 提取宽高比的核心部分（冒号分隔的部分）
        # 例如从"16:9(1664, 928)"中提取"16:9"
        ratio_key = aspect_ratio.split('(')[0].strip()
       
        # 定义宽高比与尺寸的映射（使用提取后的核心键）
        ratio_mapping = {
            "1:1": (1328, 1328),
            "16:9": (1664, 928),
            "9:16": (928, 1664),
            "4:3": (1472, 1140),
            "3:4": (1140, 1472),
            "3:2": (1584, 1056),
            "2:3": (1056, 1584),
        }
        
        # 获取宽度和高度
        width, height = ratio_mapping[ratio_key]
        
        # 计算潜在空间尺寸（按典型VAE缩放比例除以8）
        latent_height = height // 8
        latent_width = width // 8
        
        # 创建空的潜在张量（兼容大多数Stable Diffusion模型的4通道）
        latent = torch.zeros(
            [batch_size, 4, latent_height, latent_width],
            device=comfy.model_management.intermediate_device()
        )
        
        return ({"samples": latent}, width, height)