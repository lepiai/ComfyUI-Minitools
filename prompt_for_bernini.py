# ComfyUI Custom Node: Task System Prompt Selector for Bernini
TASK_CONFIG = [
    {
        "task_type": "default",
        "system_prompt": "You are a helpful assistant.",
        "entocn": "你是一名乐于助人的助手。",
        "pname": "默认通用任务"
    },
    {
        "task_type": "t2i",
        "system_prompt": "You are a helpful assistant specialized in text-to-image generation.",
        "entocn": "你是专注于文生图生成的智能助手。",
        "pname": "文生图"
    },
    {
        "task_type": "t2v",
        "system_prompt": "You are a helpful assistant specialized in text-to-video generation.",
        "entocn": "你是专注于文生视频生成的智能助手。",
        "pname": "文生视频"
    },
    {
        "task_type": "i2i",
        "system_prompt": "You are a helpful assistant specialized in image editing.",
        "entocn": "你是专注于图片编辑的智能助手。",
        "pname": "图生图/图片编辑"
    },
    {
        "task_type": "r2i",
        "system_prompt": "You are a helpful assistant specialized in subject-to-image generation.",
        "entocn": "你是专注于参考主体生成图片的智能助手。",
        "pname": "参考图生图"
    },
    {
        "task_type": "i2v",
        "system_prompt": "You are a helpful assistant specialized in image-to-video generation.",
        "entocn": "你是专注于图生视频生成的智能助手。",
        "pname": "图生视频"
    },
    {
        "task_type": "v2v",
        "system_prompt": "You are a helpful assistant specialized in video editing.",
        "entocn": "你是专注于视频编辑的智能助手。",
        "pname": "视频转视频"
    },
    {
        "task_type": "r2v",
        "system_prompt": "You are a helpful assistant specialized in subject-to-video generation.",
        "entocn": "你是专注于参考主体生成视频的智能助手。",
        "pname": "参考主体生视频"
    },
    {
        "task_type": "vi2v",
        "system_prompt": "You are a helpful assistant specialized in video editing on content propagation.",
        "entocn": "你是专注于内容延展类视频编辑的智能助手。",
        "pname": "内容延展视频编辑"
    },
    {
        "task_type": "rv2v",
        "system_prompt": "You are a helpful assistant specialized in video editing with reference.",
        "entocn": "你是专注于依托参考素材进行视频编辑的智能助手。",
        "pname": "参考素材视频编辑"
    },
    {
        "task_type": "ads2v",
        "system_prompt": "You are a helpful assistant specialized in ads insertion.",
        "entocn": "你是专注于广告植入的智能助手。",
        "pname": "广告插片"
    },
    {
        "task_type": "vrc2v",
        "system_prompt": "You are a helpful assistant for editing. You may need to adjust the subject's action or position.",
        "entocn": "你是一名编辑助手，需要调整画面主体的动作或位置。",
        "pname": "主体动作位置修改"
    },
    {
        "task_type": "mv2v",
        "system_prompt": "You are a helpful assistant for editing. You might need to adjust the video's style, lighting, colors, textures, and the subject's pose or action.",
        "entocn": "你是一名编辑助手，负责调整视频风格、光影、色彩、材质以及人物姿态和动作。",
        "pname": "全维度视频风格修改"
    }
]

SELECT_OPTIONS = [f"[{item['task_type']}]{item['entocn']}" for item in TASK_CONFIG]
OPTION_MAP = {f"[{item['task_type']}]{item['entocn']}": item["system_prompt"] for item in TASK_CONFIG}


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
                        "tooltip": "多行输入用户提示词，最终拼接格式：system_prompt,user_prompt"
                    }
                ),
                "task_select": (
                    SELECT_OPTIONS,
                    {
                        "default": SELECT_OPTIONS[0],
                        "tooltip": "下拉选择任务类型，格式【task_type】entocn，自动读取对应预设System Prompt"
                    }
                )
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("system prompt", "prompts")
    FUNCTION = "fetch_prompt"
    CATEGORY = "MiniTools"
    DESCRIPTION = """
系统提示词选择器｜支持选择预设系统词 + 自定义用户词拼接
1. task_select：下拉选取内置任务对应的SystemPrompt
2. user_prompt：多行文本框输入用户提示
输出：
- system_prompt：单独输出选中的系统提示词
- prompts：合并结果，规则：system_prompt,user_prompt（逗号分隔）
    适用场景：主要应用于Bernini模型完成各类不同任务。如：图生图、图生视频、视频编辑工作流统一配置系统角色设定等
"""

    def fetch_prompt(self, task_select, user_prompt):
        sys_prompt = OPTION_MAP[task_select]
        # 按规则拼接：系统词在前，逗号分隔+用户词
        full_prompt = f"{sys_prompt},{user_prompt}"
        return (sys_prompt, full_prompt)

