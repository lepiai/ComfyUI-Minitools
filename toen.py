import requests
import random
import logging
from hashlib import md5
from time import sleep

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 百度翻译api 免费申请地址：https://api.fanyi.baidu.com/

# ----------需要修改成自己的appid和密钥------------
appid = '20230822001789253'  # appid
secretKey = '2QNvFYLX1JdcuomtdrGs'  # 密钥 
#------------------------------------------------

def make_md5(s, encoding='utf-8'):
    """生成MD5哈希值"""
    return md5(s.encode(encoding)).hexdigest()


def translate(text, from_lang, to_lang, appid, secretkey, max_retries=2):
    """
    通用翻译函数
    :param text: 待翻译文本
    :param from_lang: 源语言
    :param to_lang: 目标语言
    :param max_retries: 最大重试次数
    :return: 翻译结果或None
    """
    if not text.strip():
        return ""
        
    fanyiser = 'https://api.fanyi.baidu.com'
    apiurl = '/api/trans/vip/translate'
    url = fanyiser + apiurl
    salt = random.randint(32768, 65536)
    
    # 保存原始换行符位置，使用特殊标记替换以便后续恢复
    line_breaks = []
    text_processed = []
    for i, line in enumerate(text.split("\n")):
        if i > 0:
            line_breaks.append(len(" ".join(text_processed)) + 1)  # 记录换行位置
        text_processed.append(line.strip())
    
    text_processed = " ".join(text_processed)
    
    for attempt in range(max_retries + 1):
        try:
            sign = make_md5(appid + text_processed + str(salt) + secretkey)
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            payload = {
                'appid': appid,
                'q': text_processed,
                'from': from_lang,
                'to': to_lang,
                'salt': salt,
                'sign': sign
            }
            
            response = requests.post(url, params=payload, headers=headers, timeout=10)
            result = response.json()
            
            # 检查API返回是否有错误
            if 'error_code' in result:
                logger.error(f"翻译API错误: {result.get('error_msg', '未知错误')}")
                if attempt < max_retries:
                    sleep(0.5)  # 等待0.5秒后重试
                    continue
                return None
            
            if 'trans_result' in result and len(result['trans_result']) > 0:
                translated = result['trans_result'][0]['dst']
                
                # 恢复原始换行符位置
                if line_breaks and translated:
                    # 从后往前插入换行符，避免位置偏移
                    for pos in reversed(line_breaks):
                        if pos < len(translated):
                            translated = translated[:pos] + "\n" + translated[pos:]
                
                return translated
            else:
                logger.warning("翻译结果为空")
                return None
                
        except Exception as e:
            logger.error(f"翻译请求失败 (尝试 {attempt+1}/{max_retries+1}): {str(e)}")
            if attempt < max_retries:
                sleep(0.5)  # 等待0.5秒后重试
                continue
            return None
    
    return None


class ChineseEnglishTranslate:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "prompt_text": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "杰作，高清画质"
                    }
                ),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("en", "cn")
    FUNCTION = "translate_text"
    CATEGORY = "MiniTools"

    def detect_language(self, text):
        """简单检测文本语言类型"""
        # 检查是否包含中文字符
        for char in text:
            if '\u4e00' <= char <= '\u9fff':
                return 'zh'
        return 'en'

    def translate_text(self, prompt_text, appid=appid, secretkey=secretKey):
        """翻译文本并返回中英文结果"""
        original_text = prompt_text.strip()
        
        # 如果输入为空，直接返回空
        if not original_text:
            return ("", "")
            
        # 检测输入语言
        input_lang = self.detect_language(original_text)
        logger.info(f"检测到输入语言: {input_lang}")
        
        try:
            if input_lang == 'zh':
                # 中文 -> 英文
                en_translation = translate(original_text, 'zh', 'en', appid, secretkey)
                cn_translation = original_text
            else:
                # 英文 -> 中文
                cn_translation = translate(original_text, 'en', 'zh', appid, secretkey)
                en_translation = original_text
            
            # 处理翻译失败的情况
            if en_translation is None:
                en_translation = ""
                logger.warning("英文翻译失败")
                
            if cn_translation is None:
                cn_translation = ""
                logger.warning("中文翻译失败")
                
            return (en_translation, cn_translation)
            
        except Exception as e:
            logger.error(f"翻译处理失败: {str(e)}")
            return ("", "")
    