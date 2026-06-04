# ComfyUI Custom Node: Bernini Prompt Selector (refer bytedance/Bernini prompt_enhancer.py)
# @乐皮ai 2026.06.04

TASK_CONFIG = [
    {
        "task_type": "default",
        "system_prompt": "You are a helpful assistant.",
        "tocn": "你是一名乐于助人的助手。",
        "desc": "通用兜底，无特定生成编辑任务时使用"
    },
    {
        "task_type": "t2i",
        "system_prompt": "You are a helpful assistant specialized in text-to-image generation.",
        "tocn": "你是专注于文生图生成的智能助手。",
        "desc": "文本描述生成单张图像，文生图生成场景"
    },
    {
        "task_type": "t2v",
        "system_prompt": "You are a helpful assistant specialized in text-to-video generation.",
        "tocn": "你是专注于文生视频生成的智能助手。",
        "desc": "纯文本指令从零生成短视频，文生视频主任务"
    },
    {
        "task_type": "i2i",
        "system_prompt": "You are a helpful assistant specialized in image editing.",
        "tocn": "你是专注于图片编辑的智能助手。",
        "desc": "依托原图参考进行图像重绘、画风修改，图生图编辑"
    },
    {
        "task_type": "r2i",
        "system_prompt": "You are a helpful assistant specialized in subject-to-image generation.",
        "tocn": "你是专注于参考主体生成图片的智能助手。",
        "desc": "参考指定主体参考图，保留主体特征生成新图"
    },
    {
        "task_type": "i2v",
        "system_prompt": "You are a helpful assistant specialized in image-to-video generation.",
        "tocn": "你是专注于图生视频生成的智能助手。",
        "desc": "输入单张静态参考图，驱动生成动态视频"
    },
    {
        "task_type": "v2v",
        "system_prompt": "You are a helpful assistant specialized in video editing.",
        "tocn": "你是专注于视频编辑的智能助手。",
        "desc": "基于原视频+文本提示进行全域视频风格重绘，无参考图"
    },
    {
        "task_type": "r2v",
        "system_prompt": "You are a helpful assistant specialized in subject-to-video generation.",
        "tocn": "你是专注于参考主体生成视频的智能助手。",
        "desc": "多张主体参考图，复刻主体形象生成全新原创视频"
    },
    {
        "task_type": "vi2v",
        "system_prompt": "You are a helpful assistant specialized in video editing on content propagation.",
        "tocn": "你是专注于内容延展类视频编辑的智能助手。",
        "desc": "视频画面拓展、画幅延伸、前后帧内容延展扩帧编辑"
    },
    {
        "task_type": "rv2v",
        "system_prompt": "You are a helpful assistant specialized in video editing with reference.",
        "tocn": "你是专注于依托参考素材进行视频编辑的智能助手。",
        "desc": "使用参考图片，修改原视频人物、物体、背景内容（参考式V2V）"
    },
    {
        "task_type": "ads2v",
        "system_prompt": "You are a helpful assistant specialized in ads insertion.",
        "tocn": "你是专注于广告植入的智能助手。",
        "desc": "将指定产品/广告素材自然嵌入目标视频画面"
    },
    {
        "task_type": "vrc2v",
        "system_prompt": "You are a helpful assistant for editing. You may need to adjust the subject's action or position.",
        "tocn": "你是一名编辑助手，需要调整画面主体的动作或位置。",
        "desc": "局部修改视频中人物/物体的动作、空间位置"
    },
    {
        "task_type": "mv2v",
        "system_prompt": "You are a helpful assistant for editing. You might need to adjust the video's style, lighting, colors, textures, and the subject's pose or action.",
        "tocn": "你是一名编辑助手，负责调整视频风格、光影、色彩、材质以及人物姿态和动作。",
        "desc": "精细化全量修改视频光影、色调、材质、画风、角色姿态"
    }
]

SELECT_OPTIONS = [f"[{item['task_type']}]{item['desc']}" for item in TASK_CONFIG]
OPTION_MAP = {f"[{item['task_type']}]{item['desc']}": item["system_prompt"] for item in TASK_CONFIG}


class TaskSystemPromptSelector:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "user_prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "多行输入用户自定义编辑/生成指令，拼接规则：system_prompt,user_prompt"
                    }
                ),
                "task_select": (
                    SELECT_OPTIONS,
                    {
                        "default": SELECT_OPTIONS[0],
                        "tooltip": "适配ByteDance Bernini框架，下拉选择对应任务场景，自动加载配套系统提示词"
                    }
                )
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("system prompt", "prompts")
    FUNCTION = "fetch_prompt"
    CATEGORY = "MiniTools"
    DESCRIPTION = """
    Bernini官方规范提示词选择器 | 对标bytedance/Bernini prompt_enhancer任务分类
    1. task_select：下拉=【任务标识+实际业务场景】，严格对齐Bernini各任务范式
    2. user_prompt：多行文本输入用户指令
    输出：
    - system_prompt：单独输出选中的任务系统角色Prompt
    - prompts：拼接结果，system在前，user在后，英文逗号分隔
    适配全系列T2I/T2V/I2V/V2V/RV2V/广告植入等Bernini原生任务工作流
    """


    def fetch_prompt(self, task_select, user_prompt):
        sys_prompt = OPTION_MAP[task_select]
        full_prompt = f"{sys_prompt},{user_prompt}"
        return (sys_prompt, full_prompt)
