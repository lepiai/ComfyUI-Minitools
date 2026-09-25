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
        if (nodeData.name !== "LP-ImageLayerEditor") return;

        nodeType.prototype.onNodeCreated = function () {
            this.layers = [];
            this.activeLayer = -1;
            this.worldScale = 1;
            this.logicalW = 0;
            this.logicalH = 0;
            this.asp = 1;
            this.dpr = window.devicePixelRatio || 1;
            this.MARGIN = 24;
            this.originX = 0;
            this.originY = 0;
            this.outW = 1;
            this.outH = 1;
            this.drawX = 0;
            this.drawY = 0;

            this.canvas = document.createElement("canvas");
            this.ctx = this.canvas.getContext("2d");

            const widget = this.addDOMWidget("editor", "canvas", this.canvas);
            widget.computeSize = () => {
                const w = Math.max(200, this.size[0] - 20);
                // 固定正方形视口，整个输出画布等比例缩放容纳其中，避免被节点面板高度裁切
                return [w, Math.max(200, Math.round(w * 0.9))];
            };

            this.addWidget("button", "Reset", null, () => this.loadImages());
            this.addWidget("button", "Continue", null, () => this.send());

            this.bindEvents();
        };

        /* resize-safe, HiDPI-aware canvas；固定方形视口，整个输出画布缩放居中，绝不裁剪 */
        nodeType.prototype.updateCanvasSize = function () {
            const s = Math.max(200, this.size[0] - 20);
            this.logicalW = s;
            this.logicalH = Math.max(200, Math.round(s * 0.9));
            this.canvas.style.width = this.logicalW + "px";
            this.canvas.style.height = this.logicalH + "px";
            // 只有物理尺寸变化时才赋值 canvas.width/height——赋值会清空位图
            const pw = Math.max(1, Math.floor(this.logicalW * this.dpr));
            const ph = Math.max(1, Math.floor(this.logicalH * this.dpr));
            if (this.canvas.width !== pw) this.canvas.width = pw;
            if (this.canvas.height !== ph) this.canvas.height = ph;
            this.worldScale = Math.min(this.logicalW / this.outW, this.logicalH / this.outH);
            this.drawX = (this.logicalW - this.outW * this.worldScale) / 2;
            this.drawY = (this.logicalH - this.outH * this.worldScale) / 2;
        };

        /* 节点尺寸变化后重绘，避免画布内容停留在旧布局。
           注意：新版前端在构造阶段（onNodeCreated 之前）就会触发 setSize→onResize，
           此时 this.layers 尚未初始化，必须先判空，否则构造函数抛异常导致节点无法添加到画布 */
        nodeType.prototype.onResize = function () {
            if (!this.layers) return;
            this.draw();
        };

        /* 固定画布：尺寸=第0层图像（背景/透明画布）的尺寸，画布中心为世界原点。
           图层可自由移动/缩放/旋转，超出画布的部分输出时裁切（与后端一致） */
        nodeType.prototype.computeBounds = function () {
            const base = this.layers[0];
            this.outW = base ? base.img.width : 1;
            this.outH = base ? base.img.height : 1;
            this.originX = -this.outW / 2;
            this.originY = -this.outH / 2;
        };

        nodeType.prototype.bindEvents = function () {
            let dragging = false;
            let rotating = false;
            let sx = 0, sy = 0, ox = 0, oy = 0, or = 0;

            this.canvas.onmousedown = e => {
                const hit = this.pickLayer(e.offsetX, e.offsetY);
                if (hit < 1) {
                    // 未命中可编辑图层：取消选中并重绘（绝不能直接 return——
                    // 任何触碰过画布尺寸的路径之后都必须重绘，否则画布停留清空状态）
                    this.activeLayer = -1;
                    this.draw();
                    return;
                }

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
                    const cx = this.drawX + (this.outW * this.worldScale) / 2;
                    const cy = this.drawY + (this.outH * this.worldScale) / 2;
                    const dx = sx - cx;
                    const dy = sy - cy;
                    const newDx = e.offsetX - cx;
                    const newDy = e.offsetY - cy;
                    const angle = Math.atan2(newDy, newDx) - Math.atan2(dy, dx);
                    l.rotation = or + angle * 180 / Math.PI;
                    this.draw();
                } else {
                    // 悬停反馈：可编辑图层上显示移动光标，让"能点什么"一目了然
                    const hit = this.pickLayer(e.offsetX, e.offsetY);
                    this.canvas.style.cursor = hit >= 1 ? "move" : "default";
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
                // 交互缩放硬范围：5%–1000%，防止无限放大
                const MIN_S = 0.05, MAX_S = 10;
                l.scaleX = Math.min(MAX_S, Math.max(MIN_S, l.scaleX * s));
                l.scaleY = Math.min(MAX_S, Math.max(MIN_S, l.scaleY * s));
                this.draw();
            };

            // 禁用右键菜单
            this.canvas.oncontextmenu = e => e.preventDefault();
        };

        nodeType.prototype.pickLayer = function (mx, my) {
            // 纯只读命中检测：只用 draw() 缓存的布局值。
            // 绝不在此重设 canvas 尺寸——给 canvas.width 赋值会清空画布位图，
            // 若随后不重绘就会出现"点击后图像消失"的假死现象
            if (!this.layers || !this.layers.length) return -1;
            const ws = this.worldScale;
            if (!(ws > 0)) return -1;
            const ox = this.drawX, oy = this.drawY;

            for (let i = this.layers.length - 1; i >= 1; i--) {
                const l = this.layers[i];
                const w = l.img.width * l.scaleX * ws;
                const h = l.img.height * l.scaleY * ws;
                const x = ox + (l.x - this.originX) * ws - w / 2;
                const y = oy + (l.y - this.originY) * ws - h / 2;

                if (mx >= x && mx <= x + w && my >= y && my <= y + h)
                    return i;
            }
            return -1;
        };

        nodeType.prototype.draw = function () {
            if (!this.layers || !this.layers.length) return;

            this.computeBounds();
            this.updateCanvasSize();

            const w = this.logicalW;
            const h = this.logicalH;
            const ctx = this.ctx;

            // HiDPI：统一在 CSS 逻辑像素坐标下绘制，物理分辨率由 dpr 决定，避免高DPI屏幕发虚
            ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
            ctx.clearRect(0, 0, w, h);

            const ox = this.drawX, oy = this.drawY;
            const ow = this.outW * this.worldScale, oh = this.outH * this.worldScale;

            // 固定画布：内容裁切到画布矩形内显示——所见即所得，超出部分输出时被裁掉
            ctx.save();
            ctx.beginPath();
            ctx.rect(ox, oy, ow, oh);
            ctx.clip();

            const cell = Math.max(8, Math.floor(Math.min(ow, oh) / 20));
            for (let yy = oy; yy < oy + oh; yy += cell) {
                for (let xx = ox; xx < ox + ow; xx += cell) {
                    ctx.fillStyle = (((xx - ox) / cell + (yy - oy) / cell) % 2 === 0) ? "#e0e0e0" : "#ffffff";
                    ctx.fillRect(xx, yy, cell, cell);
                }
            }

            for (const l of this.layers) {
                ctx.save();
                ctx.translate(
                    ox + (l.x - this.originX) * this.worldScale,
                    oy + (l.y - this.originY) * this.worldScale
                );
                ctx.rotate(l.rotation * Math.PI / 180);
                ctx.scale(l.scaleX * this.worldScale, l.scaleY * this.worldScale);
                ctx.drawImage(l.img, -l.img.width / 2, -l.img.height / 2);
                ctx.restore();
            }
            ctx.restore(); // 结束裁切

            // 画布边框
            ctx.strokeStyle = "rgba(0,0,0,0.35)";
            ctx.lineWidth = 1;
            ctx.strokeRect(ox + 0.5, oy + 0.5, ow - 1, oh - 1);

            // 选中图层描边不裁切：完整显示其范围，画布边框外的部分即输出时会被裁掉的内容
            if (this.activeLayer >= 1 && this.activeLayer < this.layers.length) {
                const l = this.layers[this.activeLayer];
                ctx.save();
                ctx.translate(
                    ox + (l.x - this.originX) * this.worldScale,
                    oy + (l.y - this.originY) * this.worldScale
                );
                ctx.rotate(l.rotation * Math.PI / 180);
                ctx.scale(l.scaleX * this.worldScale, l.scaleY * this.worldScale);
                const sc = Math.max(1e-6, Math.max(l.scaleX, l.scaleY) * this.worldScale);
                ctx.strokeStyle = "#4caf50";
                ctx.lineWidth = 2 / sc;
                ctx.strokeRect(
                    -l.img.width / 2,
                    -l.img.height / 2,
                    l.img.width,
                    l.img.height
                );
                // 旋转控制点
                ctx.fillStyle = "#4caf50";
                ctx.beginPath();
                ctx.arc(l.img.width / 2, 0, 5 / sc, 0, Math.PI * 2);
                ctx.fill();
                ctx.restore();
            }

            // 画布尺寸读数（含图层数，便于确认前端实际加载了多少层）
            ctx.font = "12px sans-serif";
            ctx.textBaseline = "top";
            const label = `画布 ${this.outW}x${this.outH}px · 图层 ${this.layers.length} · 超出裁切`;
            const tw = ctx.measureText(label).width;
            ctx.fillStyle = "rgba(255,255,255,0.82)";
            ctx.fillRect(6, 6, tw + 10, 18);
            ctx.fillStyle = "rgba(0,0,0,0.65)";
            ctx.fillText(label, 11, 9);

            // 只有背景层时给出操作指引：此时没有任何可编辑对象
            if (this.layers.length <= 1) {
                const hint = "无可编辑图层：再连接一路图片，或开启「透明画布」";
                const hw = ctx.measureText(hint).width;
                const hx = Math.max(4, (this.logicalW - hw) / 2);
                const hy = this.logicalH - 26;
                ctx.fillStyle = "rgba(255,255,255,0.85)";
                ctx.fillRect(hx - 6, hy - 4, hw + 12, 20);
                ctx.fillStyle = "#d32f2f";
                ctx.fillText(hint, hx, hy);
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

            // 先尝试加载第0张图片（背景/画布），它的尺寸即固定画布尺寸
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
                this.onChange?.();
            }
        };
    }
});