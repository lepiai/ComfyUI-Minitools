from . import promptsTranslateEN, color2rgb,hex2dec,croptran,Bernini_Prompt_Enhance


# 菜单名
NODE_CLASS_MAPPINGS = {
    "LP-TranslateToEN": promptsTranslateEN.translatetoen,
    "LP-color2RGB"    : color2rgb.color2RGB,
    "LP-hex2dec"      : hex2dec.hex2dec,
    "LP-CropTransparentEdges":croptran.CropTransparentEdges,
    "LP-ImageToMaskWithAlpha":croptran.ImageToMaskWithAlpha,
    "NumericSlider": croptran.NumericSlider,
    "BerniniPromptEnhancerBailian": Bernini_Prompt_Enhance.BerniniPromptEnhancerBailian
}
 
# 节点标题或描述
NODE_DISPLAY_NAME_MAPPINGS = {
    "LP-TranslateToEN": "Translate to English 👻",
    "LP-color2RGB"    : "Color to RGB 👻",
    "LP-hex2dec"      : "RGB or HEX Convert to DEC 👻",
    "LP-CropTransparentEdges": "Crop Transparent Edges 👻",
    "LP-ImageToMaskWithAlpha": "Image to Mask (With Alpha) 👻",
    "NumericSlider": "Numeric Slider 👻",
    "BerniniPromptEnhancerBailian": "Bernini Prompt Enhance v1.2 👻"
}
