# comfyui-minitools
comfyui小工具集，避免节点冗余，看有没时间持续更新吧~

安装方法：

git clone命令克隆本项目，即可完成所有节点的安装。

1、color2rgb 用于配合[comfyui layer style](https://github.com/chflame163/ComfyUI_LayerStyle)中颜色选择器节点，转换成RGB，且分别输出R、G、B值
![image](https://github.com/vxinhao/comfyui-minitools/assets/50534209/87b18e32-b7f8-4c5a-a4d5-f8166943e68e)

2、promptsTranslateEN 提示词翻译节点，将输入的内容转换成英文，用的百度翻译api，所以需要实现准备好appid（可在百度翻译官方免费申请）
节点演示：
![image](https://github.com/vxinhao/comfyui-minitool/assets/50534209/d3f08259-a2ef-4b0b-85df-fb5ef9f32e01)

3、RGB or HEX Convert to DEC 将十六进制颜色码和RBG转换成十进制
![image](https://github.com/user-attachments/assets/92b7a954-3c91-44d0-aa21-6eecea840aad)

4、CropTransparentEdges 按透明区域裁剪
![微信截图_20250522224212](https://github.com/user-attachments/assets/22ad3e94-2ce2-425d-996d-43098dd04b8a)

5、ImageToMaskWithAlpha 将图片转换成带有alpha通道的遮罩
![微信截图_20250522223903](https://github.com/user-attachments/assets/e0244459-bf0e-44dd-8cac-f35ea527bdcc)

6、NumericSlider数字滑块，包含浮点数和整数
![微信截图_20250522223929](https://github.com/user-attachments/assets/08de6738-945b-4c56-9747-cc829d047124)
