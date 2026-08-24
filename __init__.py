from . import promptsTranslateEN, color2rgb, hex2dec, croptran, PromptOptimizer
from . import image_layer_editor, prompt_for_bernini, qwenas, replace2prompt, toen
from . import minimax_h3_prompt

# 前端资源目录
WEB_DIRECTORY = "web"


# 菜单名
NODE_CLASS_MAPPINGS = {
    "LP-TranslateToEN": promptsTranslateEN.translatetoen,
    "LP-color2RGB"    : color2rgb.color2RGB,
    "LP-hex2dec"      : hex2dec.hex2dec,
    "LP-CropTransparentEdges": croptran.CropTransparentEdges,
    "LP-ImageToMaskWithAlpha": croptran.ImageToMaskWithAlpha,
    "NumericSlider": croptran.NumericSlider,
    "BerniniPromptEnhancerBailian": PromptOptimizer.BerniniPromptEnhancerBailian,
    "LP-ImageLayerEditor": image_layer_editor.ImageLayerEditor,
    "LP-TaskSystemPromptSelector": prompt_for_bernini.TaskSystemPromptSelector,
    "LP-AspectRatioSelectorWithLatent": qwenas.AspectRatioSelectorWithLatent,
    "LP-SensitiveWordFilter": replace2prompt.SensitiveWordFilterNode,
    "LP-ChineseEnglishTranslate": toen.ChineseEnglishTranslate,
    "LP-MiniMaxH3PromptOptimizer": minimax_h3_prompt.MiniMaxH3PromptOptimizer,
    "LP-MiniMaxH3OutputUnpacker": minimax_h3_prompt.MiniMaxH3OutputUnpacker,
    "LP-MiniMaxH3Studio": minimax_h3_prompt.MiniMaxH3Studio,
    "LP-OpenAIClientConfig": minimax_h3_prompt.OpenAIClientConfig,
}
 
# 节点标题或描述
NODE_DISPLAY_NAME_MAPPINGS = {
    "LP-TranslateToEN": "Translate to English 👻",
    "LP-color2RGB"    : "Color to RGB 👻",
    "LP-hex2dec"      : "RGB or HEX Convert to DEC 👻",
    "LP-CropTransparentEdges": "Crop Transparent Edges 👻",
    "LP-ImageToMaskWithAlpha": "Image to Mask (With Alpha) 👻",
    "NumericSlider": "Numeric Slider 👻",
    "BerniniPromptEnhancerBailian": "Prompt Optimizer v1.2 👻",
    "LP-ImageLayerEditor": "Image Layer Editor 👻",
    "LP-TaskSystemPromptSelector": "Task System Prompt Selector 👻",
    "LP-AspectRatioSelectorWithLatent": "Aspect Ratio Selector 👻",
    "LP-SensitiveWordFilter": "Sensitive Word Filter 👻",
    "LP-ChineseEnglishTranslate": "Chinese English Translate 👻",
    "LP-MiniMaxH3PromptOptimizer": "MiniMax H3 Prompt Optimizer 👻",
    "LP-MiniMaxH3OutputUnpacker": "MiniMax H3 Output Unpacker 👻",
    "LP-MiniMaxH3Studio": "MiniMax H3 Studio 👻",
    "LP-OpenAIClientConfig": "MiniMax H3 LLM Config 👻",
}
