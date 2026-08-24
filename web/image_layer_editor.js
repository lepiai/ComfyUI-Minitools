import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

class Layer {
    constructor(img, index) {
        this.img = img;
        this.index = index;
        this.x = 0;
        this.y = 0;
        this.scaleX = 1;
        this.scaleY = 1;
        this.rotation = 0;
        this.locked = index === 0;
    }
}

/* backend notify */
// 修复：使用官方 api 监听器和更稳健的 getNodeById 方法
api.addEventListener("image_layer_editor:images_ready", e => {
    const node = app.graph.getNodeById(e.detail.node_id);
    if (node && node.loadImages) {
        node.loadImages();
    }
});

app.registerExtension({
    name: "comfy.image_layer_editor.final.resize_safe",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "ImageLayerEditor") return;

        nodeType.prototype.onNodeCreated = function () {
            this.layers = [];
            this.activeLayer = -1;
            this.worldScale = 1;

            this.canvas = document.createElement("canvas");
            this.ctx = this.canvas.getContext("2d");

            const widget = this.addDOMWidget("editor", "canvas", this.canvas);
            widget.computeSize = () => [this.size[0] - 20, this.size[0] - 20];

            this.addWidget("button", "Reset", null, () => this.loadImages());
            this.addWidget("button", "Continue", null, () => this.send());

            this.bindEvents();
        };

        /* resize-safe canvas */
        nodeType.prototype.updateCanvasSize = function () {
            const size = Math.max(200, this.size[0] - 20);
            this.canvas.width = size;
            this.canvas.height = size;
        };

        nodeType.prototype.bindEvents = function () {
            let dragging = false;
            let rotating = false;
            let sx = 0, sy = 0, ox = 0, oy = 0, or = 0;

            this.canvas.onmousedown = e => {
                const hit = this.pickLayer(e.offsetX, e.offsetY);
                if (hit < 1) return;

                this.activeLayer = hit;
                if (e.button === 0) { // 左键拖动
                    dragging = true;
                    sx = e.offsetX;
                    sy = e.offsetY;
                    ox = this.layers[hit].x;
                    oy = this.layers[hit].y;
                } else if (e.button === 2) { // 右键旋转
                    rotating = true;
                    sx = e.offsetX;
                    sy = e.offsetY;
                    or = this.layers[hit].rotation;
                }
                this.draw();
            };

            this.canvas.onmousemove = e => {
                if (dragging && this.activeLayer >= 1) {
                    const l = this.layers[this.activeLayer];
                    l.x = ox + (e.offsetX - sx) / this.worldScale;
                    l.y = oy + (e.offsetY - sy) / this.worldScale;
                    this.draw();
                } else if (rotating && this.activeLayer >= 1) {
                    const l = this.layers[this.activeLayer];
                    const cx = this.canvas.width / 2;
                    const cy = this.canvas.height / 2;
                    const dx = sx - cx;
                    const dy = sy - cy;
                    const newDx = e.offsetX - cx;
                    const newDy = e.offsetY - cy;
                    const angle = Math.atan2(newDy, newDx) - Math.atan2(dy, dx);
                    l.rotation = or + angle * 180 / Math.PI;
                    this.draw();
                }
            };

            window.addEventListener("mouseup", () => {
                dragging = false;
                rotating = false;
            });

            this.canvas.onwheel = e => {
                if (this.activeLayer < 1) return;
                e.preventDefault();
                const l = this.layers[this.activeLayer];
                const s = e.deltaY < 0 ? 1.1 : 0.9;
                l.scaleX *= s;
                l.scaleY *= s;
                this.draw();
            };

            // 禁用右键菜单
            this.canvas.oncontextmenu = e => e.preventDefault();
        };

        nodeType.prototype.pickLayer = function (mx, my) {
            const cx = this.canvas.width / 2;
            const cy = this.canvas.height / 2;

            for (let i = this.layers.length - 1; i >= 1; i--) {
                const l = this.layers[i];
                const w = l.img.width * l.scaleX * this.worldScale;
                const h = l.img.height * l.scaleY * this.worldScale;
                const x = cx + l.x * this.worldScale - w / 2;
                const y = cy + l.y * this.worldScale - h / 2;

                if (mx >= x && mx <= x + w && my >= y && my <= y + h)
                    return i;
            }
            return -1;
        };

        nodeType.prototype.draw = function () {
            if (!this.layers.length) return;

            this.updateCanvasSize();

            const base = this.layers[0].img;
            this.worldScale = Math.min(
                this.canvas.width / base.width,
                this.canvas.height / base.height
            );

            const ctx = this.ctx;
            ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

            const cx = this.canvas.width / 2;
            const cy = this.canvas.height / 2;

            for (let i = 0; i < this.layers.length; i++) {
                const l = this.layers[i];
                ctx.save();
                ctx.translate(cx + l.x * this.worldScale, cy + l.y * this.worldScale);
                ctx.rotate(l.rotation * Math.PI / 180);
                ctx.scale(l.scaleX * this.worldScale, l.scaleY * this.worldScale);
                ctx.drawImage(l.img, -l.img.width / 2, -l.img.height / 2);

                if (i === this.activeLayer && i >= 1) {
                    ctx.strokeStyle = "#4caf50";
                    ctx.lineWidth = 2;
                    ctx.strokeRect(
                        -l.img.width / 2,
                        -l.img.height / 2,
                        l.img.width,
                        l.img.height
                    );
                    // 绘制旋转控制点
                    ctx.fillStyle = "#4caf50";
                    ctx.beginPath();
                    ctx.arc(l.img.width / 2, 0, 5, 0, Math.PI * 2);
                    ctx.fill();
                }
                ctx.restore();
            }
        };

        nodeType.prototype.loadImages = async function () {
            this.layers = [];

            const load = name => new Promise((res, rej) => {
                const img = new Image();
                // 添加随机参数以避免缓存
                img.src = api.apiURL(`/view?filename=${name}&type=temp&t=${Date.now()}`);
                img.onload = () => res(img);
                img.onerror = rej;
            });

            // 先尝试加载第0张图片（背景图）
            try {
                const img = await load(`input_layer_${this.id}_0.png`);
                this.layers.push(new Layer(img, 0));
            } catch {
                // 如果背景图加载失败，直接返回
                return;
            }

            // 尝试加载其他图层，但最多尝试5次
            for (let i = 1; i < 20; i++) {
                try {
                    const img = await load(`input_layer_${this.id}_${i}.png`);
                    this.layers.push(new Layer(img, i));
                } catch {
                    // 如果加载失败，停止尝试
                    break;
                }
            }

            this.activeLayer = this.layers.length > 1 ? 1 : -1;
            this.draw();
        };

        nodeType.prototype.send = async function () {
            await api.fetchApi(`/image_layer_editor/set_transforms/${this.id}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    transforms: JSON.stringify(
                        this.layers.map(l => ({
                            x: l.x,
                            y: l.y,
                            scaleX: l.scaleX,
                            scaleY: l.scaleY,
                            rotation: l.rotation
                        }))
                    )
                })
            });

            // 更新随机数（基于当前时间戳生成）
            const seedWidget = this.widgets.find(w => w.name === "random_seed");
            if (seedWidget) {
                // 获取当前时间的毫秒级时间戳（13位整数，如1740000000000）
                const timestamp = new Date().getTime();
                // 直接将时间戳赋值给种子（也可对时间戳做简单运算增加随机性）
                seedWidget.value = timestamp;
                this.onChange();
            }
        };
    }
});