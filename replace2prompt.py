import random
import re


# 从上到下，1、原始字符串，2、需要替换的词，3、用这个框里的词来替换2
# 待优化项：不能替换中文，不能随机从3中取词来替换 -20251028

class SensitiveWordFilterNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True}),  # 输入的提示词
                "sensitive_words": ("STRING", {"multiline": True}),  # 敏感词列表，用逗号分隔
                "replacement_word_list": ("STRING", {"multiline": True, "default": "word1,word2,word3"}),  # 替代词库
            },
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "filter_sensitive_words"
    CATEGORY = "MiniTools"
    DESCRIPTION = """
    This node filters sensitive words from the given prompt and replaces them with random words from a provided list.

    Inputs:
    - `prompt`: The text prompt in which you want to filter words.
    - `sensitive_words`: A comma-separated list of sensitive words to be filtered.
    - `replacement_word_list`: A comma-separated list of words to replace the sensitive words. Each sensitive word is replaced with a random word from this list.

    Example:
    If the prompt is "I have a secret and it's cat", sensitive words are "cat,secret", and replacement words are "dog,fish", the output might be "I have a fish and it's dog".
    """

    def filter_sensitive_words(self, prompt, sensitive_words, replacement_word_list):
        # 将敏感词列表和替代词列表转换为数组
        sensitive_words_list = sensitive_words.split(",")
        replacement_words = replacement_word_list.split(",")
        
        # 用于存放已使用的替代词，避免重复
        used_replacements = []

        # 如果敏感词和替代词库为空，直接返回原始提示
        if not sensitive_words_list or not replacement_words:
            return (prompt,)

        # 逐个替换敏感词，确保精确匹配单词，并且每个敏感词替换的词不同
        for word in sensitive_words_list:
            word = word.strip()

            # 随机选择未使用的替代词
            available_replacements = [w for w in replacement_words if w not in used_replacements]
            if not available_replacements:
                # 如果没有可用替代词了，重新使用所有替代词
                used_replacements = []
                available_replacements = replacement_words
            
            replacement = random.choice(available_replacements).strip()
            used_replacements.append(replacement)

            # 使用正则表达式确保只替换完整的单词
            prompt = re.sub(rf'\b{re.escape(word)}\b', replacement, prompt)

        return (prompt,)
