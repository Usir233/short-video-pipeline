# OpenFilm 特效与动态视觉设计规范（VFX & Motion Graphics Playbook）

本文件专门定义本工作区短视频的**「视觉特效、动态图形、光学调色、人像合成、转场、无框字幕与声画材质耦合」**全套工艺标准（共 **7 大类 · 42 项具体特效规则**），全部基于本工作区 OpenFilm `0.1` 协议（`node_modules/openfilm/SPEC.md`）原生能力实现，零外部全局依赖。

关于十大剪辑风格（`S01–S10`）、开篇钩子（`H1–H6`）、气口精剪（`D1–D5`）与镜头构图拓扑（`L1–L7`），请先阅读姊妹规范 [editing-styles.md](editing-styles.md)。

---

## 一、特效美学总纲：彻底消灭“AI 网页 Dashboard 感”四条铁律

1. **去容器化铁律（Boxless First）**：
   - **全面废除 `.stage-panel` 大圆角框套小框**：严禁绘制宽 `≥ 700px` 且带显式描边（CSS `border` 或 SVG `<rect stroke>`）的外围大面板框；
   - **单镜边框硬配额**：任意单个 `scenes/*.html` 内，带显式边框的矩形/多边形总数 **`≤ 2` 个**，边框容器嵌套深度 **`≤ 1` 层**；
   - **伪进度条清零令**：除非当句口播含真实可量化数值（具体 `%`、倍数 `×`、金额、起止年份）并在旁侧标出该数字，**一律严禁**绘制无刻度的水平圆角条充当装饰；
   - **严肃商业片清退卡通贴纸**：商业访谈、财经拆解、科技评测与电影独白主题下，`S01 / S03 / S04 / S05 / S06 / S07` **全面禁用**彩色扁平卡通贴纸（摇铃、卡通绿勾、卡通胖箭头），统一改用画布内极简矢量笔触。
2. **容器随内容共生铁律（Zero Empty Shell）**：
   - 严禁在 `t = 0` 先摆出一个空白背景框/空坐标框干等 3–4 秒才弹字！
   - `t = 0..0.35s` 首拍元素必须本身构成饱满视觉中心（如首句巨型核心词、基准比例色块或实景切片），后续分句随 `local_t = cue_start - clip_at` 通过**画布平移聚焦**与**前序元素主动退暗（`opacity: 0.35; filter: saturate(0.4)`）**自然生长，任意时刻截帧均无半成品空框。
3. **同屏唯一焦点与零字幕复读铁律（Single Focus, Zero Echo）**：
   - 手机竖屏同一时刻仅允许 **「1 个主视觉焦点 + 底部字幕」**；
   - 全屏口播段（底部已有同步字幕）时，`overlays` 轨**严禁弹出实底横盒把底部正在念的字幕抄第二遍**！前景文字仅限提炼 **`2–5` 字重音锚点词或反差数字**，与同期字幕二元组重合率必须 **`< 50%`**（超 `60%` 由 `qc_video.py` 硬阻断）。
4. **纯函数确定性与字体预载铁律（Pure `f(t)`）**：
   - 严守 OpenFilm `SPEC.md §3`：页面任何一帧仅由 `window.film.frame(t)` 纯函数决定，**严禁使用 CSS `transition`**，严禁跨帧累加状态变量；
   - 凡使用中文字体（`Noto Sans SC` / `Noto Serif SC`）或图片，必须在 `window.film.ready` 中显式 `await document.fonts.ready` 及全部 `img.decode()`。

---

## 二、`film.html` 标准 10 轨合成架构（从顶层到底层）

OpenFilm 按 `<section>` 出现顺序从上往下叠放图层（第一个 `<section>` 在最顶层）。所有项目统一遵循以下标准轨道层级（无片段的空轨道省略不写，严禁留空 `<section>`）：

```html
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=1080, height=1920">
<style>
  /* 1. 实拍统一挂载离线 3D LUT + 克制自然人像精修（保护眼镜不畸变） */
  .spk-graded {
    object-fit: cover;
    --of-lut: url(looks/master-editorial.cube);
    --of-beauty-even: 0.22;
    --of-beauty-eye-bright: 0.24;
    --of-beauty-dark-circles: 0.18;
    --of-beauty-texture: 0.72;
    --of-beauty-protect-glasses: 1;
  }
  /* 注意：自身含运镜或微晃的动态 B-roll 严禁再叠加 .cam-c1-push / scale(...) 人工缩放动画！ */
  .broll-graded {
    object-fit: cover;
    --of-lut: url(looks/master-editorial.cube);
  }
  /* 2. 同源模糊底板（专供 PF3/PF4 抠像特写垫底，彻底吃掉发丝绿植溢色） */
  .bokeh-bed {
    object-fit: cover;
    --of-lut: url(looks/master-editorial.cube);
    scale: 1.08;
    filter: blur(18px) brightness(0.44) contrast(1.08) saturate(0.58);
  }
  /* 3. 高精度去溢色人物抠像（width 必须 >= 1080px 防半空切双肩） */
  .spk-cutout {
    object-fit: cover;
    --of-lut: url(looks/master-editorial.cube);
    --of-cutout: 1;
    --of-cutout-mode: 1;
    --of-cutout-edge: 0.22;
    --of-cutout-shrink: 0.08;
    --of-cutout-despill: 0.65;
  }
</style>
</head>
<body>
  <!-- Track 1: 顶层转场桥接层（TR3 沉黑 / TR4 闪白 / TR7 擦除 / TR9 故障） -->
  <section id="fx-transitions">...</section>
  <!-- Track 2: 全系零胶囊无框高级字幕层（SUB1–SUB6） -->
  <section id="subtitles"><iframe id="sub-all" src="scenes/subtitles.html#t=0,45.0"></iframe></section>
  <!-- Track 3: 全屏口播轻量无框重音锚点层（零复读字幕，单条 <= 6.0s） -->
  <section id="overlays">...</section>
  <!-- Track 4: 按需高潮抠像前景人物层（单段 <= 4.2s，底层必须有同源 bokeh-bed！） -->
  <section id="cutout-fg">...</section>
  <!-- Track 5: 全画幅光学控光暗角与胶片肌理层（PF5 + AT1） -->
  <section id="vignette-grade">...</section>
  <!-- Track 6: 开放式侧分栏人像小窗层（仅 L2/L5 拓扑使用，严守 v2>=75%，比下轨全屏同主体早 0.034s 收口） -->
  <section id="speaker-pip">...</section>
  <!-- Track 7: 主舞台层（主口播 muted <video>、调色 B-roll <video>、bokeh-bed <video>、无框动态舞台 <iframe>） -->
  <section id="main-stage">...</section>
  <!-- Track 8: 经 prepare-voice 美化的等长精剪人声轨 -->
  <section id="voice-track">...</section>
  <!-- Track 9: 经 build-bgm-bed 生成的稳压 + Silence Drop + 侧链呼吸配乐床 -->
  <section id="bgm-bed"><audio id="bgm-main" src="assets/bgm-bed.m4a" volume="1.0"></audio></section>
  <!-- Track 10+: 分层物理音效轨（sfx-impact 重锤转场 / sfx-foley 纸笔触感 / sfx-ambience 空间环境底） -->
  <section id="sfx-impact">...</section>
  <section id="sfx-foley">...</section>
  <section id="sfx-ambience">...</section>
</body>
</html>
```

---

## 三、七大类 · 42 项特效规则全词典（`storyboard.json` 直接按代号调用）

### 第一类：动态排印特效（Kinetic Typography · `KT1–KT8`）

字体栈约定：现代无衬线用 `"Noto Sans SC"`（500/700/900），人文纪实/电影衬线用 `"Noto Serif SC"`（600/700/900，Windows 本机已内置 `NotoSerifSC-VF.ttf`，亦可回退 `"STZhongsong", "Songti SC", serif`），几何大数字用 `"Bahnschrift", "DIN Alternate", "Inter", sans-serif`（开启 `font-variant-numeric: tabular-nums`）。

| 代号 | 名称 | 触发语义 | 核心视觉与 `frame(t)` 实现规范 | 声效配对 |
|---|---|---|---|---|
| **`KT1`** | **瑞士十字标尺巨字** | 开篇立题、章节定调、核心反问 | 画布仅设 `1px` 低透十字基准线（`rgba(255,255,255,0.13)`），主词 **`96–148px`** 高字重宋/黑体紧字距（`-2px`）配 `24px` 宽字距眉标（**字号极差比 `≥ 3.2×`**），零圆角外框 | 首拍配 `Sub Thud`；句中 `0` 音效 |
| **`KT2`** | **逐字/逐词破土升起** | 金句揭示、核心概念点亮 | 行容器设 `overflow: hidden`，每个字/词在 `local_t + i * 0.035` 内按 `easeOutExpo` 从 `translateY(105%)` 升至 `0%`（或直接在 `film.html` 用原生 `overrides` `split: {"by":"char","stagger":0.035}`） | 纯排印 `0` 音效 |
| **`KT3`** | **光学散焦收拢显影** | 周期感喟、人物独白高潮 | `0.52s` `easeOutExpo` 插值：`opacity: k`、`filter: blur((1-k)*10px)`、`letterSpacing: (16 - 13*k)px`、`transform: scale(1.06 - 0.06*k)` | 静默留白或极轻 `Sub Swell` |
| **`KT4`** | **重力弹簧盖章砸字** | 痛点暴击、残酷结论落锤 | `spring(p)` 驱动主词从 `scale(1.68)` 砸落至 `1.00`，在 `p ∈ [0.35, 0.55]` 联动舞台容器 `3` 帧确定性阻尼微震 `translate(sin(t*90)*5px, cos(t*75)*4px)` | **必配**低频冲击锤 `Slam`（连砸必逐次配音） |
| **`KT5`** | **反差色块擦除显字** | 身份切换、新范式登场 | 高对比实心色块先 `0.18s` `scaleX(0→1)` 扫过文字区，紧接着 `transform-origin: right; scaleX(1→0)` 抽离露出下方巨字 | 轻脆短促空气擦声 |
| **`KT6`** | **动态荧光马克笔划词** | 政策重点、核心定性短语 | 文字下方 `z-index:-1` 垫高度 `42%` 半透明陶橙/翡翠青色带，在 `local_t` 后 `0.26s` 内 `scaleX(0 → 1)` 横向刷满字底 | 真实马克笔纸面摩擦声 |
| **`KT7`** | **极简流式搜索/对话推演** | 买家问 AI、搜索词重构 | 无外框大字号光标行：`n = Math.floor(clamp((t-t0)/dur) * text.length)` + `4Hz` 闪烁竖标 `▍`（**严禁画山寨浏览器红黄绿三圆点外框**） | 极轻柔机械微键音（`≤4` 声） |
| **`KT8`** | **聚光递进与前序退隐列** | 三重压力、多部门同频变化 | 最多 `3` 行无框大字；当第 `k` 行在 `T_k` 亮起 `opacity: 1; translateX(0)` 时，第 `0..k-1` 行平滑退隐至 **`opacity: 0.35; filter: saturate(0.35)`** 让出焦点 | 零叮当气泡音 |

---

### 第二类：无框数据与商业逻辑可视化特效（Boxless Data & Logic · `DV1–DV8`）

| 代号 | 名称 | 触发语义 | 几何构成与 `frame(t)` 算法规范（零外层圆角套娃框） | 淘汰的劣质写法 |
|---|---|---|---|---|
| **`DV1`** | **等宽里程表巨数跳动** | 利润率、增长率、年份跨度、金额 | `124–168px` `Bahnschrift`/`Inter` 等宽巨数按 `easeOutExpo` 从初值滚至终值，右上角悬 `28px` 单位标与涨跌三角 | 小圆角胶囊里塞 `32px` 数字 |
| **`DV2`** | **物理面积逐级挤压栈** | 金税合规+税务成本压薄净利、份额蚕食 | 画布中央立起高 `760px` 明亮毛利实心块；随每项成本 `local_t` 到达，上方深琥珀红实心重块按 `spring` 逐级向下物理吞噬高度，将底部净利压成窄亮线，侧标实时数字 | 无数值无刻度的水平 Loading 伪进度条 |
| **`DV3`** | **无框地平线渐变趋势面** | 2017 起飞 → 2021 顶峰 → 当下放缓 | **零外围方框**！仅 `1px` 底轴 + `2` 条虚线参考格；SVG 平滑三次贝塞尔路径 `stroke-dashoffset` 生长，曲线下铺 `<linearGradient>` `0.32→0` 光幕，`getPointAtLength` 发光圆点带动年份锚点 | `812×660` 大白框/大黑框里画一根孤线 |
| **`DV4`** | **手绘双笔划除与弹性打勾** | 证伪旧经验 / 锁定正确动作 | 匹配文字像素宽度的微弧 SVG `<path>`：否定用珊瑚红双斜笔 `0.22s` 疾速划除并将原字降暗至 `0.38`；肯定用翡翠青笔触 `easeOutBack` 打勾 | CSS `text-decoration: line-through` 或卡通贴纸 |
| **`DV5`** | **动态杠杆失衡倾侧** | 投入重金 vs 回报缩水、供需失衡 | 单根 `2px` 极简金属支点横梁在 `local_t` 从 `0deg` 阻尼倾斜至 `-15deg`，两端直接托起无框大字与量感色块 | 简笔画卡通天平 |
| **`DV6`** | **比例漏斗坍缩动效** | 大浪淘沙、新品牌不敢入局 | Canvas/SVG 三级流光梯形带，下级出口宽度随口播按真实比例骤缩至极窄通道，未通过粒子在闸口消散 | 四个等宽圆角按钮竖排 |
| **`DV7`** | **横向纪年标尺巡航** | 多阶段历史演进、时间线复盘 | 贯穿全宽的 `1px` 刻度时间尺，随 `local_t` 驱动标尺横向平移，当前焦点年份放大至 `112px` 居中，过去年份柔焦滑向左侧暗部 | 一屏硬塞 4 个年份小方盒 |
| **`DV8`** | **单核脉冲无框拓扑** | 核心变量波及供应链/PMC/全公司 | 中心单核发光字，向外仅引出 `3–4` 根柔和弧线（`stroke-dasharray` 光脉冲流动），终点直接落无框文字锚点（**无矩形外框包裹**） | Word SmartArt 四方框中间画大叉 `X` |

---

### 第三类：实拍增强与 AI 人像光学合成特效（Portrait & Footage VFX · `PF1–PF7`）

1. **`PF1` 五套工作区离线 `.cube` 3D LUT 色彩分级（实拍必挂，入口 E 五槽位一一正交绑定）**：
   建项时从 `.agents/skills/short-video-pipeline/assets/luts/` 复制对应 `.cube` 至项目 `film/looks/`，所有口播与 B-roll `<video>` 必须挂载 `--of-lut: url(looks/<name>.cube)`（`qc_video.py` 硬拦截零调色裸奔实拍与跨槽重复 LUT）：
   - `master-editorial.cube`（`S01 / S06 / S07` · `00-master` 默认）：压降室内绿植/黄木墙杂色饱和度 `-34%`，暗部微偏冷青墨，精准保护亚洲肤色自然暖感；
   - `v1-crisp-contrast.cube`（`S02` · `01-v1` 默认）：高反差 S 曲线（`+16%`），冷峻青蓝暗部配锐利暖高光；
   - `v2-warm-paper.cube`（`S03 / S10` · `02-v2` 默认）：柔和提亮死黑至暖炭灰（`0.022` 暗部托底），消除室内绿黄偏色，与 `#F2EFE9` 暖纸画布无缝衔接；
   - `v3-obsidian-film.cube`（`S04 / S07` · `03-v3` 默认）：环境降饱和 `-26%`，深沉黑曜石暗部 + 高光暖象牙胶片滚降；
   - `tech-keynote.cube`（`S08 / S05 / S09` · **`04-v4` 专属槽位绑定**）：清冽影棚中性高净度白平衡，净除室内暖黄浊气，精准凸显双域交锋分屏与红笔划除证伪反差。
2. **`PF2` 商业人像自然精修（OpenFilm 原生语义美颜）**：
   统一推荐克制配方：`--of-beauty-even: 0.22; --of-beauty-eye-bright: 0.24; --of-beauty-dark-circles: 0.18; --of-beauty-texture: 0.72; --of-beauty-protect-glasses: 1`（提亮眼神光、匀净肤色、保留 `72%` 真实毛孔质感且绝不拉歪眼镜框；严禁开启 `slim / jaw / eyes > 0.1` 造成网红脸形变）。
3. **`PF3` 同源模糊底光学浅景深分离（根治抠像绿毛边死命令）**：
   - **硬性合成律**：凡启用 `--of-cutout: 1`，**严禁底层放纯黑/纯色 CSS 渐变页**！必须在 `main-stage` 同一时间区间垫入同源 `<video class="bokeh-bed">`（放大 `1.08×` + `blur(18px) brightness(0.44) saturate(0.58)` + 同一 LUT），上层 `cutout-fg` 挂 `--of-cutout-edge: 0.22; --of-cutout-shrink: 0.08; --of-cutout-despill: 0.65` 且 **`width >= 1080px`**，单段时长控在 `≤ 4.2s`。
4. **`PF4` 远中景人后纵深巨字（近景机位自动熔断令）**：
   - 准入前提：源片实测五官跨度 **`chin_v - head_top_v ≤ 0.42`**（中景，双肩完整在画内）且 `<video>` `width >= 1080px`；人后仅允许在 `y = 250..520px` 放 **单行 `2–4` 字超短巨词**（发梢轻压 `≤15%`）。
   - **熔断条件**：若 `chin_v - head_top_v > 0.42`（近景大头，强行下沉必截胸或缩窄必切双肩成无臂纸片人），**硬性禁用人后字**，一律改走 `PF3` 浅景深 + 前景下方无框巨字！
5. **`PF5` 全画幅光学控光暗角（Optical Vignette）**：
   废除擦除人物下半身的生硬 `mask-image`，改在 `vignette-grade` 轨铺柔和径向暗角：
   `background: radial-gradient(ellipse 86% 60% at 50% 35%, transparent 42%, rgba(6,11,15,0.46) 76%, rgba(6,11,15,0.92) 100%);`
6. **`PF6` 3D 透视聚光证据切片（Spotlight Document Slice）**：
   将真实高清新闻/政策/官方界面截图放入局部容器，外挂 `--fx-rx: 7deg; --fx-ry: -9deg; --fx-z: 36px` 空间微倾与多层柔影，非重点区域压暗 `55%`，仅用高光框聚焦核心数字行（彻底取代 LLM 手画山寨 App 外框）。
7. **`PF7` 静态原图 2.5D 景深视差与光轨合成**：
   静态高清图入片时，底层原图缓慢推近 `1.00→1.08`，前景以 `1.14×` 差速叠合 `1px` 极细坐标引线与动态数据锚点，制造双层空间视差。

---

### 第四类：镜头转场特效 10 级词典（Transitions · `TR1–TR10`）

1. **`TR1` J/L-Cut 声画错位硬切**（占全片 `65%+`）：画面硬切但声音错开 `0.20–0.35s`；**严禁在 1 帧干硬切上空放 `whoosh` 音效**。
2. **`TR2` 跨轨光学交叉叠化**：上下两轨重叠 `0.35–0.45s`，分别配 `overrides='[{"fade":[0,0.4]}]'` 与 `'[{"fade":[0.4,0]}]'`；**当相邻镜头明度跳变 `|ΔYAVG| > 60`（如实拍切 `S03` 暖白纸面）时强制使用**。同轨紧接的 `<iframe>` 严禁写 `opacity: 0→1`（切点首帧必露黑底报错）。
3. **`TR3` 沉黑屏息过渡（Dip-to-Black）**：`fx-transitions` 轨放置 `0.45–0.60s` 纯黑 `#000000` 页（`0→1→0` 曲线，峰值必须达 `1.0` 真纯黑），用于章节大转折与 `S04` 终帧落幕。
4. **`TR4` 胶片曝光微闪白**：切点前后各 `2–3` 帧驱动 `--fx-brightness: 100% → 180% → 100%`，用于闪回昔日黄金期或揭晓瞬间（全片 `≤ 2` 次）。
5. **`TR5` 动感模糊甩镜切（Whip-Pan）**：出镜尾 `0.18s` `translate: -45vw 0; --fx-blur: 16px` 紧接下一镜从 `+45vw` 刹停清焦，配短促干净气流声（`S02/S05/S06` 专用）。
6. **`TR6` 空间圆角遮罩平滑收放（Clip-Path Morph）**：`<video>` 在 `0.36s` 内平滑插值 `clip-path: inset(54px 410px 110px 60px round 22px)` 实现 `L1` 全屏与 `L2` 侧分栏无缝变形（终态严守 `v2 ≥ 0.75`，跨轨交接时上轨提前 `≥ 0.034s` 收口防 1 帧双头叠影）。
7. **`TR7` 硬边几何拉幕擦除（Directional Wipe）**：新画布以 `clip-path: inset(0 100% 0 0 → 0 0% 0 0)` `0.32s` `easeOutExpo` 划入（标题须独立于被裁图像层防腰斩字）。
8. **`TR8` 光学失焦呼吸换景（Rack-Focus）**：切点两侧 `0.26s` `--fx-blur: 0px → 14px → 0px` 叠轻 `fade`。
9. **`TR9` 5帧确定性 RGB 通道分离故障切**：在 `fx-transitions` 用 `Math.sin(Math.floor(t*30)*12.9898)` 生成确定性水平切片错位 + 红青 `mix-blend-mode: screen` 偏移 `±10px`，**仅限 `S02/S05/S08` 强冲突反转且全片 `≤ 2` 次**。
10. **`TR10` 巨字笔画穿透放大转场**：章节巨字在末尾 `0.30s` 极速放大 `scale(1 → 14)` 让笔画填满画幅顺势切入实景（全片 `≤ 1` 次）。

---

### 第五类：画面肌理与空间氛围特效（Atmospheric Textures · `AT1–AT5`）

- **`AT1` 24fps 确定性胶片银盐颗粒**：固定噪点贴图按 `step = Math.floor(t * 24)` 整数跳移 `translate(-((step*73)%192)px, -((step*137)%192)px)`，`opacity: 0.05; mix-blend-mode: overlay`，彻底消除纯色背景廉价塑料感。
- **`AT2` 暖琥珀边缘呼吸柔光**：画布角落 `700px` 径向暖光斑随 `easeInOutSine(t * 0.4)` 微幅呼吸（`opacity: 0.08–0.14`）。
- **`AT3` 社论暖棉纸纤维底纹**：`#F2EFE9` 画布叠 `3%` 不透明度 SVG `<feTurbulence type="fractalNoise" baseFrequency="0.8">` 纸纹，柔和护眼不刺白。
- **`AT4` Canvas 浅景深失焦微尘**：仅限暗场高潮镜，`≤ 18` 颗大半径低透明度（`0.06–0.15`）柔光圆斑按 `t` 纯函数缓慢上浮。
- **`AT5` 极低对比度十字微标**：`rgba(255,255,255,0.045)` 稀疏十字锚点（间距 `≥ 180px`，严禁画高对比 `60×60` 铁丝网）。

---

### 第六类：全系零胶囊无框高级字幕矩阵（`SUB1–SUB6`）

**通用字幕硬红线**：
1. **全槽位（含 `00-master`）100% 禁用 `.pill / #sub` 四边封闭实底/半透明胶囊外框**（`qc_video.py` 全槽硬阻断）；
2. **字号与断句**：主字号 **`≥ 40px`**；单屏净字数 **`4–12` 字（硬上限 `≤ 13` 字）**，长句必拆且去除句中逗号；
3. **无延迟匹配器**：统一采用 `const end = i + 1 < CUES.length ? Math.min(c[1] + 0.12, CUES[i+1][0] - 0.001) : c[1] + 0.12;` 防止前句尾延吞掉下句入场；
4. **克制高亮**：全片带 `<em>` 高亮的 `cue` 占比 **`15%–38%`**，单个 `<em>` 词长 **`≤ 5` 字且严禁包含任何标点符号**。

| 预设代号 | 对应风格 | `.wrap top`（五槽 `46px` 等距阶梯） | 对齐与标志性结构 | 正文字体/字号/字距/颜色 | 描边/底影与 `<em>` 重点词特效 |
|---|---|---:|---|---|---|
| **`SUB1`** | `S01 / S07`<br>（`00-master` 默认） | `1412px` | `left: 72px; right: 96px; text-align: left` + 左侧 `4px` 铜青竖向标尺线 | `Noto Sans SC` 700, `46px`, `-0.5px`, `#FFF8E6` | 多层光学柔影 `0 3px 14px rgba(0,0,0,0.92)`；`<em>` 切 **`Noto Serif SC` 900 `50px` 暖金 `#FFC21A`** |
| **`SUB2`** | `S02`<br>（`01-v1` 默认） | `1320px` | `text-align: center` | `Noto Sans SC` 900, `52px`, `-1.0px`, `#FFFFFF` | `paint-order: stroke fill; -webkit-text-stroke: 9px #050811` 厚黑边；`<em>` `60px` `#FFE600`/`#FF5A26` 弹簧上跳 `-4px` |
| **`SUB3`** | `S03`<br>（`02-v2` 默认） | `1458px` | `text-align: center` | `Noto Sans SC` 900, `46px`, `-0.3px`, 纸底 `#111C24`（实拍段切 `#FFF8E6`） | 无描边油墨印刷质感；`<em>` 底部铺 `42%` 高陶橙/翡翠青动态横向刷出荧光马克笔带 |
| **`SUB4`** | `S04`<br>（`03-v3` 默认） | `1504px` | `text-align: center` | **全句 `Noto Serif SC` 700**, `42px`, **`+2.5px` 宽字距**, `#F2E5C6` | 电影院细柔暗影 `0 2px 16px rgba(0,0,0,0.95)`；`≤25%` `<em>` 同字号微染陶金 `#E29578` 柔焦淡入 |
| **`SUB5`** | `S08 / S05 / S06 / S09`<br>（**`04-v4` 默认**） | `1366px` | `text-align: center` | `Noto Sans SC` 700 + `Bahnschrift`, `46px`, `0px`, `#F4F7FA` | 干净暗影 `0 4px 18px rgba(0,0,0,0.88)`；`<em>` 电光青 `#38BDF8` 底配 `2px` 极细刻度下划线 |
| **`SUB6`** | `S10` 实操笔记<br>（`04-v4` 切 `S10` 时用） | `1366px` | `text-align: center` | `Noto Sans SC` 700, `45px`, `-0.4px`, `#18222B` / `#FFF8E6` | 清晰柔和底影；`<em>` 翡翠青动作词加粗强调 |

---

### 第七类：五类物理缓动原语与声画材质耦合规范

#### 1. 标准物理缓动函数（写入 `scenes/*.html`，禁止全片单一 `cubic-out`）
```js
const clamp = (v, a = 0, b = 1) => (v < a ? a : v > b ? b : v);
const easeOutExpo = (x) => { const c = clamp(x); return c === 1 ? 1 : 1 - Math.pow(2, -10 * c); };
const easeOutBack = (x) => { const c = clamp(x) - 1; return 1 + 2.70158 * c * c * c + 1.70158 * c * c; };
const spring = (x) => { const c = clamp(x); return c === 0 ? 0 : c === 1 ? 1 : 1 - Math.exp(-8 * c) * Math.cos(10 * c); };
const easeInOutSine = (x) => -(Math.cos(Math.PI * clamp(x)) - 1) / 2;
```

#### 2. 两阶段确定性音频工程与声画配对铁律
1. **前级人声母带化（必跑 `qc_video.py prepare-voice`）**：`85Hz` 高通 + `260Hz` 去胸闷 + `3.6kHz/9.5kHz` 磁性空气激励 + `6.8kHz` 抑齿音 + `3:1` 柔顺压缩与 `-1.5dB` 限幅，确保成片 `LRA ≥ 3.6 LU`（告别干声撞砖墙限幅）。
2. **SFX 入库归一化（必跑 `qc_video.py normalize-sfx`）**：淘汰 `< -50 LUFS` 静音坏件，合格音效峰值统一归至 `-3.0 dBTP`。
3. **自动侧链呼吸配乐床（必跑 `qc_video.py build-bgm-bed`）**：自动稳压 `LRA > 9 LU` 曲目、注入 Cold Open/Outro 推升、`Silence Drop` 金句真空窗与 `sidechaincompress` 人声开口自动退让 `4 dB`。
4. **「无物理动量不配音」与槽位音色黑名单**：
   - 纯排版文字淡入、去焦显影、常规字幕切换 **一律 `0` 音效**；
   - 重力砸字/面积挤压配低频 `Sub Thud / Slam`；甩镜配短促 `Clean Whoosh`；纸面推演配 `Paper Slide / Marker Stroke`；实景夜雨/港口叠 `-35 LUFS` `Ambience`；
   - **硬性封杀黑名单**：`S01/S04/S07` 严禁出现 `pop / bubble / bell / boing / cartoon`；`S03` 严禁出现 `glitch / laser`；`S04` 严禁出现 `hopeful / upbeat / launch / click` 欢快曲或点击声。

---

## 四、与 `qc_video.py` 自动化门禁的精确映射

执行 `qc_video.py audit-render` 与 `audit-matrix` 时，脚本自动对本规范执行以下硬拦截（`hard_failures`，Exit Code `2`）：
1. **反 Dashboard 套娃与伪进度条**：单镜显式描边矩形 `> 3`、宽 `≥ 700px` 描边大外框套子框、或无真实数值的水平进度条 `<rect>`；
2. **反预摆空壳框与反字幕复读**：`main-stage` 首 `2.2s` 空壳框等待（`min_trigger > 1.0s` 且首拍有效字 `<6`），或前景文字与同期字幕重合率 `≥ 60%`；
3. **光学调色、抠像防穿帮与 B-roll 防抖/运镜解耦**：实拍口播 `<video>` 未挂 `--of-lut`；`--of-cutout: 1` 宽度 `< 1040px`（切双肩）或底层缺失同源模糊 `<video>`（纯色 CSS 底裸贴炸绿毛边）；`speaker-pip` `v2 < 72%` 切嘴下巴；动态 B-roll 舞台折算高频急动度 `hf_jerk > 2.40px` 或往复反向率 `> 2.50/s`（`Tier C` 背景来回晃动穿帮，轻微微晃须先经 `qc_video.py stabilize-broll` 稳像），或非静止 B-roll 违规叠加 CSS `scale` 缩放引发双重运镜打架；
4. **字幕与声学硬门禁**：任意槽位使用封闭胶囊底框 `.pill`、主字号 `< 40px`、单屏净长 `> 15` 字、`<em>` 含标点；成片 `LRA < 3.6 LU`（`v1 < 3.3 LU`）砖墙拍扁、BGM 有效差值越界或原生 `LRA > 11.5 LU` 未稳压、长于 `32s` 成片无 `Silence Drop`/侧链配乐床、幽灵弱音效 `< -36 LUFS` 及槽位黑名单音色。
