# 剪辑方式与 OpenFilm 特效工艺规范（Editing & VFX Craft）

本文件沉淀本工作区从「静态网页卡片 PPT 感」升维至「商业成片级剪辑与动态视觉（Motion Graphics & VFX）」的硬性工艺规范与可复用 OpenFilm 原语库，适用于全入口原创/复刻视频及入口 E 全部 4 个槽位（`00-master` / `01-v1` / `02-v2` / `03-v3`）。

所有特效原语均严格基于本工作区 OpenFilm 0.1 协议（`node_modules/openfilm/SPEC.md`）原生能力与确定性 `window.film.frame(t)`，不依赖额外全局包。

---

## 一、分风格剪辑节奏与反死镜量化红线

**核心原则：禁止用单一「大头全屏 ↔ 顶部静止 PiP + 底部圆角网页卡」二元模板套所有风格。** 源片为 4K（`3840×2160`）时拥有 `≥2×` 无损裁切与跳切空间，必须真正用出景别语言。

| 槽位 / 风格 | 目标有效 ASL（平均镜长） | 固定 PiP 连续滞留上限 | 单镜零视觉变化空窗上限 | 全屏 B-roll / 全屏图形占比 | 4K 景别与运镜硬要求 |
|---|---:|---:|---:|---:|---|
| **`00-master`（商业旗舰长口播 >60s）** | **≤ 6.5s** | ≤ 25s（≤2 镜） | **≤ 3.5s** | ≥ 15% | 单镜口播 `>6s` 须配锁眼缓推（`--fx-ax/--fx-ay`）或 4K 景别跳切；后段禁止 20s+ 无变化长死镜 |
| **`01-v1`（高节奏实证网感风）** | **≤ 3.5s** | ≤ 8s（禁止连续 2 镜锁死同位 PiP） | **≤ 2.2s** | ≥ 20% | 口播 `>4.5s` 必须按意群做 `≥12%` 阶梯跳切（如 `1.00 → 1.15 → 1.28`）；严禁 `<8%` 匀速微推假装快节奏 |
| **`02-v2`（暖白结构化清单风）** | **≤ 6.5s**（镜内步进 `1.2–2.2s`） | 同高度锁定（如 `384px`），切章须有视觉纸面滑动 | **≤ 3.0s** | ≥ 15%（含全幅图解或终局展开） | 严禁 PiP 高度无动机漂移（如 `400→342→376`）；每条清单项须逐条渐进揭示并配完整组音效 |
| **`03-v3`（黑曜石电影金句沉浸风）** | **5.0–7.5s**（允许克制留白） | ≤ 14s（须穿插全宽空镜呼吸切出） | **≤ 4.0s**（除刻意纯黑屏息外） | ≥ 20%（`2.39:1` 宽幅电影空镜/双轨浅景深） | 禁止把连续口播切碎并复用同套 `scale` 动画造成缩放回弹；高潮段用单条连续 `<video>` 单调推近 |

### 强制剪辑禁令
1. **零句中硬切版式**：切镜点必须落在字幕停顿缝隙并与 `subtitles.html` 边界严格对齐，禁止在完整分句的定语与宾语中间突然把全屏口播缩进 PiP。
2. **跨轨防浮点叠影（防双人头 1 帧穿帮）**：当上轨 `<section id="speaker-pip">` 切换到下轨 `<section id="main-stage">` 全屏同主体 `<video>` 时，因 IEEE-754 浮点累加误差（如 `33.2 + (130.65 - 118.05) = 45.80000000000001`），上轨 `#t=in,out` 结束时间**必须比下轨起点提前至少 `1 帧（≥ 0.034s）`**，或采用显式跨轨形变转场无缝交接。
3. **连续同机位防缩放回弹**：同一连续源片段跨场景更换前景贴片时，**禁止**将底层 `<video>` 拆成两段并挂同一套 `@keyframes` 缩放（必然在交界帧发生 `1.04 → 1.01` 倒退抽搐）；必须保持单条连续 `<video>` 承载贯穿推镜，或显式衔接首尾 `scale` 值。
4. **声画转场必须成对**：禁止“空放 `whoosh` 音效 + 画面 1 帧干硬切”；任何动势转场声必须匹配 `0.25–0.50s` 视觉过渡（叠化、沉黑、遮罩擦除、空间归位或动感模糊甩切）。当相邻镜头亮度跳变 `|ΔYAVG| > 60`（如暖白纸底切暗色全屏实拍）或人脸倍率跳变 `> 2.0×` 时，**严禁零帧硬切**，必须配置 `0.30–0.45s` 视觉桥接。

---

## 二、特效质量四条红线（终结“网页 PPT 感”与“伪特效”）

1. **零幽灵剧透（No Ghost Spoilers）**
   - 凡尚未讲到的卡片、清单项、结论条、删除线或金句，触发前**必须设为 `opacity: 0`**（或极轻虚线空槽占位），**严禁使用 `opacity: 0.15–0.55` 半透明灰块提前挂屏剧透**。
   - **焦点退隐（Spotlight & Dimming）**：新观点或正解登场时，被否定的旧方案或已讲完的前序条目应主动**降透明度至 `0.40–0.55` + 降饱和度 `saturate(0.35–0.6)`**，让出视觉重心（严禁划错旧卡后反而变亮抢戏）。
2. **名实相符（WYSIWYG VFX）**
   - 分镜脚本或音效中出现下列关键词时，场景代码必须实装对应真实算法，严禁挂羊头卖狗肉：
     - **「故障 / 倒带」**：实装 3–5 帧确定性 RGB 切片错位（`clip-path: inset` + `mix-blend-mode: screen`）与短闪白/倒滚时间码，且音效峰点误差 `≤ ±50ms`；
     - **「3D 矩阵 / 空间升维」**：实装真透视投影 `k = fov / (fov + rz)`、`z` 深度差 `≥ ±120`、节点按 `rz` Painter's Z-Sort 排序并按 `k` 缩放字号/尺寸；升维前先 `0.25s` 清场收起旧 2D 标签，**严禁多卡叠字撞车**；
     - **「划除 / 否定 / 勾选」**：禁止静态 CSS `text-decoration: line-through` 或超出文字宽度的硬直条 `div`，必须使用贴合字宽的 **SVG `<path>` + `stroke-dashoffset` 笔触描边** 配合微震/回弹；
     - **「锁靶 / 数据流 / AI 对话」**：必须实装 Canvas/SVG 动态准星收缩、沿路径流动发光点（`getPointAtLength`）或确定性流式打字机（`Math.floor(p * text.length)` + 闪烁光标）。
3. **风格纯度红线**
   - **电影感/金句沉浸风（如 `03-v3`）**：**严禁使用静止 `REC` 红点、四角监视器取景框、`SPEAKER CAM · 4K` 等数码录播套壳**；必须以动态宽银幕遮幅、OpenFilm 原生 `--of-lut` / `--of-cutout: 1` 浅景深分离、24fps 确定性胶片颗粒与**真溶黑收尾（终帧黑幕 `opacity: 1.0`）**建立高级光学质感。
   - **科技霓虹风（如 `01-v1`）**：避免满屏套用「`border-radius: 16px` 厚蓝黑盒 + 均匀 `box-shadow`」初代模板；优先工业切角 `clip-path: polygon(...)`、细刻度 HUD、与实拍视频轻冷调统一。
   - **实拍与文字防穿帮**：激光/遮罩擦除两张 B-roll 时，**标题栏必须抽离出被裁切的图像层**防止标题被拦腰切字；CC0 免版权通用 B-roll 登记在 `credits.json` 即可，勿在画面角落贴大块灰色 `Wikimedia CC...` 贴纸破坏质感。
4. **告别单一 `cubic-out` + 0 帧 `className` 跳变**
   - 禁止全片所有元素复制同一段 `1 - (1-x)^3` 位移，也禁止进度条、卡片高亮、打勾盒用 1 帧 `className` 硬跳变；按语义选用下方标准物理缓动与连续插值。

---

## 三、OpenFilm 0.1 可复用 `motion-kit` 原语库（直接套用）

### 1. 四类标准缓动函数（写入 `frame(t)`，严禁依赖 CSS `transition`）

```js
const clamp = (v, a = 0, b = 1) => (v < a ? a : v > b ? b : v);
// 1. 电影急停（卡片/文字高速滑入、丝滑收刹）
const easeOutExpo = (x) => { const c = clamp(x); return c === 1 ? 1 : 1 - Math.pow(2, -10 * c); };
// 2. 弹性过冲（勾选盖章、结论爆点、徽章弹出）
const easeOutBack = (x) => { const c = clamp(x) - 1; return 1 + 2.70158 * c * c * c + 1.70158 * c * c; };
// 3. 物理阻尼弹簧（强节奏弹窗、撞击落位）
const spring = (x) => { const c = clamp(x); return c === 0 ? 0 : c === 1 ? 1 : 1 - Math.exp(-8 * c) * Math.cos(10 * c); };
// 4. 柔和呼吸（电影推镜、暗角/光斑流转）
const easeInOutSine = (x) => -(Math.cos(Math.PI * clamp(x)) - 1) / 2;
```

### 2. OpenFilm 原生 CSS / 合成 VFX 能力（已按 `SPEC.md` 核验）

- **锁眼推镜与甩切动感模糊（`film.html`）**：
  ```css
  /* 锁眼锚点：--fx-ax / --fx-ay（相对画面中心，人物双眉约 -220px） */
  .eye-push { --fx-ax: 0px; --fx-ay: -220px; animation: eyePush var(--clip-length) cubic-bezier(0.16,1,0.3,1) both; }
  /* 甩切/倒带高能过渡：--fx-blur / --fx-brightness */
  @keyframes whipOut {
    0%, 92% { --fx-blur: 0px; --fx-brightness: 100%; }
    100%    { --fx-blur: 14px; --fx-brightness: 160%; scale: 1.22; }
  }
  .whip-vid { filter: blur(var(--fx-blur, 0px)) brightness(var(--fx-brightness, 100%)); }
  ```
- **人后巨字 / 电影浅景深背景分离（`--of-cutout: 1`）**：
  - **人后巨字（终局/金句爆点）**：底层 `<section>` 放全屏超大金句 `<iframe>`，上层 `<section>` 放同源 `<video style="--of-cutout: 1; --of-cutout-mode: 1; --of-cutout-edge: 0.25; --of-cutout-despill: 0.35">`，人物自然压在巨字前面形成真实 Z 轴纵深；
  - **电影浅景深（去平亮办公墙）**：底层放同源 `<video style="filter: blur(7px) brightness(0.60) saturate(0.75)">`，上层叠 `--of-cutout: 1` 清晰前景人物；可叠加 `--of-lut: url(looks/cinema.cube)` 做冷暗部/暖肤色分离（如戴眼镜开启美颜须加 `--of-beauty-protect-glasses: 1`）。
- **跨轨空间形变转场（全屏 ↔ PiP `clip-path` Morph）与叠化**：
  - 全屏缩入 PiP / PiP 展开全屏：对 `<video>` 用 `@keyframes` 在 `0.40s` 内平滑插值 `clip-path: inset(256px 66px 1280px 66px round 20px) ↔ inset(0px 0px 0px 0px round 0px)`，同步让背景看板反向滑动退场；
  - 电影叠化（Cross-Dissolve）：两镜分置相邻 `<section>` 重叠 `0.45s`，分别加 `overrides='[{"fade":[0,0.45]}]'` 与 `overrides='[{"fade":[0.45,0]}]'`；高潮前可在 `0.50s` 气口加顶层 **Dip-to-Black（沉黑屏息页）**。

### 3. 四类高复用语义微特效代码范式（写入 `scenes/*.html`）

1. **SVG 笔触划除 / 勾选 / 流动连线**：
   ```js
   // 划除/勾选：len = path.getTotalLength()，初始化 strokeDasharray = len
   const p = easeOutExpo((t - t0) / 0.28);
   path.style.strokeDashoffset = String(len * (1 - p));
   // 持续数据流光点：pt = path.getPointAtLength(((t * 0.6) % 1) * len)
   dot.setAttribute('cx', pt.x.toFixed(1)); dot.setAttribute('cy', pt.y.toFixed(1));
   ```
2. **确定性流式打字机（AI 对话/搜索框）**：
   ```js
   const n = Math.floor(clamp((t - t0) / dur) * fullText.length);
   const cursorOn = Math.floor(t * 4) % 2 === 0 && n < fullText.length;
   el.textContent = fullText.slice(0, n) + (cursorOn ? '▍' : '');
   ```
3. **光学去焦显影（电影金句高潮）**：
   ```js
   const k = easeOutExpo((t - t0) / 0.55);
   el.style.opacity = String(k);
   el.style.letterSpacing = `${(14 - 11 * k).toFixed(2)}px`;
   el.style.filter = `blur(${((1 - k) * 9).toFixed(2)}px)`;
   el.style.transform = `scale(${(1.06 - 0.06 * k).toFixed(4)})`;
   ```
4. **24fps 确定性胶片颗粒（严禁 `Math.random()` 破坏 OpenFilm 确定性）**：
   ```js
   // 用 24fps 步进整数驱动固定噪点贴图偏移，相同 t 永远产出完全相同画面
   const step = Math.floor(t * 24);
   grain.style.transform = `translate(${-((step * 73) % 192)}px, ${-((step * 137) % 192)}px)`;
   ```
5. **5 帧确定性倒带/RGB 故障转场页（放顶层 `<section id="fx-transitions">`）**：
   - 在切点前后 `0.40s` 内，用 `Math.sin(Math.floor(t * 30) * 12.9898)` 生成确定性切片 `clip-path: inset(y1% 0 y2% 0)` + 红青双层 `±10px` 错位（`mix-blend-mode: screen`）+ 切点中心 2–3 帧青白曝光闪白，彻底掩盖倒叙同机位跳切或闭眼帧。

---

## 四、与 `qc_video.py` 自动化门禁的对应关系

运行 `python3 "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" audit-render` 时，脚本已自动覆盖以下剪辑与特效检查：
- **跨轨浮点叠影硬拦截**：扫描 `speaker-pip` 与 `main-stage` `<video>` 区间重叠（拦截 `f=1374` 类 1 帧双人头穿帮）；
- **连续镜缩放回弹硬拦截**：检测 `main-stage` 相邻连续源 `<video>` 复用同套缩放动画（拦截 `32.7s` 类回弹抽搐）；
- **切点逐帧对比图 `safezone-cuts.png`**：自动抽取最多 3 个关键切点的 `切点-1帧 / 切点 / 切点+1帧`，一眼核验双头闪帧、闭眼帧与亮度断崖；
- **ASL 与节奏预警 + 幽灵预显/静态删除线/伪 REC 套壳扫描**：按风格槽位（`master/v1/v2/v3`）核查平均镜长、最长单镜时长，并标出 `opacity: 0.15..0.55` 幽灵预占位、`text-decoration: line-through` 与电影槽位 `REC` 套壳。
