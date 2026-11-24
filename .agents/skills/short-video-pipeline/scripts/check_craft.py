#!/usr/bin/env python3
"""
短视频导演级视听反违和自动质检脚本（零外部依赖，纯 Python 标准库）。

对照 references/video-craft.md 的 10 项导演审美门禁，直接解析 OpenFilm 工程
（film.html、captions.vtt 及各镜 *.html），在渲染前/渲染后自动拦截：
  1. 「顶部小窗人头 + 下半网页卡片墙」/ 右上角监控画中画模具（口播全屏占比不足）
  2. 纯人像呼吸留白段不足
  3. 单张静态 B-roll 照片停留过久（> 3.5s）
  4. 网页后台/PPT 视觉过载（常驻顶栏、英文代码眉标、单帧字数过多、小字号、多格细框卡片墙）
  5. 厚黑膏药方块底字幕、长句双行字幕、缺少关键词高亮、越过底部安全区
  6. 机械高频音效（超总数上限、volume 过高盖人声、每切必咻、短音效截尾）
  7. 死直线 BGM（无静音真空呼吸、底乐音量过高盖人声）

用法（先 source env.sh）：
  python3 .agents/skills/short-video-pipeline/scripts/check_craft.py \
    --film runs/<目录>/film \
    --mode talking_head \
    --json-out runs/<目录>/output/check/craft-lint.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


def rel_to_root(path: Path) -> str:
    env_root = os.environ.get("SVP_ROOT")
    roots = [Path(env_root)] if env_root else []
    cur = Path(__file__).resolve()
    for p in cur.parents:
        if (p / ".agents" / "skills" / "short-video-pipeline" / "SKILL.md").is_file():
            roots.append(p)
            break
    for r in roots:
        try:
            return str(path.resolve().relative_to(r.resolve()))
        except Exception:
            pass
    return path.name

# 通用「前端仪表盘 / 程序员装饰眉标」正则与词表（不绑定任何单期业务话题）
BANNED_DASHBOARD_PATTERNS = [
    re.compile(r"\bSTEP\s*0?[1-9]\b"),
    re.compile(r"\bACT\s+(?:I|II|III|IV|V|VI)\b"),
    re.compile(r"\bCASE\s*0?[1-9]\b"),
    re.compile(r"\bMODULE\s*0?[1-9]\b"),
    re.compile(r"\bSECTION\s*0?[1-9]\b"),
    re.compile(r"//\s*[A-Z][A-Z0-9 _-]{3,28}"),
    re.compile(r"[A-Z][A-Z0-9 _-]{3,24}\s*//"),
    re.compile(r"\b(?:LIVE SYNCING|USER PROFILE|SYSTEM STATUS|DATA STREAM|AUTO MATCH|DEBUG MODE|DASHBOARD)\b"),
]


def parse_frag_duration(src: str) -> tuple[float | None, float | None]:
    m = re.search(r"#t=([0-9.]+)(?:,([0-9.]+))?", src or "")
    if not m:
        return None, None
    t_in = float(m.group(1))
    t_out = float(m.group(2)) if m.group(2) is not None else None
    return t_in, t_out


def parse_inline_style(style: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (style or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def parse_px(val: str | None) -> float | None:
    if not val:
        return None
    m = re.match(r"^\s*([0-9.]+)\s*px\s*$", val)
    return float(m.group(1)) if m else None


class FilmHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.viewport = (1080, 1920)
        self.sections: list[dict[str, Any]] = []
        self._cur_section: dict[str, Any] | None = None
        self._in_style = False
        self.style_blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        amap = {k.lower(): (v or "") for k, v in attrs}
        t = tag.lower()
        if t == "meta" and amap.get("name", "").lower() == "viewport":
            c = amap.get("content", "")
            mw = re.search(r"width\s*=\s*(\d+)", c)
            mh = re.search(r"height\s*=\s*(\d+)", c)
            if mw and mh:
                self.viewport = (int(mw.group(1)), int(mh.group(1)))
        elif t == "style":
            self._in_style = True
        elif t == "section":
            self._cur_section = {
                "id": amap.get("id", f"track_{len(self.sections)+1}"),
                "attrs": amap,
                "clips": [],
            }
            self.sections.append(self._cur_section)
        elif t in ("video", "img", "iframe", "audio", "track") and self._cur_section is not None:
            self._cur_section["clips"].append({"tag": t, "attrs": amap})

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "style":
            self._in_style = False
        elif t == "section":
            self._cur_section = None

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.style_blocks.append(data)


def merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    clean = sorted((a, b) for a, b in intervals if b > a)
    if not clean:
        return []
    merged = [clean[0]]
    for a, b in clean[1:]:
        la, lb = merged[-1]
        if a <= lb + 0.05:
            merged[-1] = (la, max(lb, b))
        else:
            merged.append((a, b))
    return merged


def total_covered(intervals: list[tuple[float, float]]) -> float:
    return sum(b - a for a, b in merge_intervals(intervals))


def subtract_intervals(base: list[tuple[float, float]], subs: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result = merge_intervals(base)
    for sa, sb in merge_intervals(subs):
        nxt: list[tuple[float, float]] = []
        for a, b in result:
            if sb <= a or sa >= b:
                nxt.append((a, b))
            else:
                if a < sa:
                    nxt.append((a, sa))
                if sb < b:
                    nxt.append((sb, b))
        result = nxt
    return result


def classify_audio(section_id: str, clip_id: str, src: str, dur: float | None) -> str:
    joined = f"{section_id} {clip_id} {src}".lower()
    if any(k in joined for k in ("voice", "vocal", "speech", "narration", "aroll", "dialogue")):
        return "voice"
    if any(k in joined for k in ("bgm", "music", "pad", "loop", "groove", "bed", "ambient", "lofi", "theme")):
        return "bgm"
    if any(k in joined for k in ("sfx", "whoosh", "swipe", "pop", "blip", "chime", "tick", "hit", "boom", "trans", "accent", "click", "pencil", "glitch")):
        return "sfx"
    if dur is not None and dur >= 10.0:
        return "bgm"
    return "sfx"


def strip_html_to_text(html_text: str) -> tuple[str, str]:
    styles = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html_text, re.S | re.I))
    no_style = re.sub(r"<style[^>]*>.*?</style>", " ", html_text, flags=re.S | re.I)
    no_script = re.sub(r"<script[^>]*>.*?</script>", " ", no_style, flags=re.S | re.I)
    no_comment = re.sub(r"<!--.*?-->", " ", no_script, flags=re.S)
    # Remove source attribution lines so they don't count against focal copy budget
    no_source = re.sub(r"(?:来源|图源|架构参考|摄影|Photo|Source)\s*[:：][^\n<]{0,90}", " ", no_comment, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", no_source)
    text = re.sub(r"\s+", " ", text).strip()
    return text, styles


def count_readable_units(text: str) -> int:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z0-9]+", text))
    return cjk + words


def inspect_scene_page(page_path: Path) -> dict[str, Any]:
    raw = page_path.read_text(encoding="utf-8", errors="ignore")
    text, styles = strip_html_to_text(raw)
    # 仅扫描可见 DOM 文本中的英文仪表盘眉标（避免误伤 <script> 里的正常 JS 注释 // ...）
    banned_hits: list[str] = []
    for pat in BANNED_DASHBOARD_PATTERNS:
        for m in pat.finditer(text):
            tok = m.group(0).strip()
            if tok not in banned_hits:
                banned_hits.append(tok)
    units = count_readable_units(text)

    # Check tiny font sizes in CSS (< 22px), excluding source/credit/footer classes heuristically
    tiny_fonts: list[int] = []
    for m in re.finditer(r"font-size\s*:\s*([0-9.]+)\s*px", styles, re.I):
        sz = float(m.group(1))
        if sz < 22:
            # Look back 120 chars for context
            ctx = styles[max(0, m.start() - 120):m.start()].lower()
            if not any(k in ctx for k in ("source", "credit", "attrib", "caption-note", "footnote", "cite")):
                tiny_fonts.append(int(round(sz)))

    # Detect thin-bordered rounded card walls (SaaS dashboard signature)
    card_borders = len(re.findall(r"border\s*:\s*(?:1|1\.5|2)px\s+solid", styles, re.I))
    has_top_bar = bool(
        re.search(r"(?:topbar|top-bar|header-bar|nav-bar|brand-bar|progress-bar|chapter-bar|step-bar)", raw, re.I)
    )
    linear_ui_anims = len(re.findall(r"animation\s*:[^;]*\blinear\b", styles, re.I))

    return {
        "file": page_path.name,
        "readable_units": units,
        "banned_dashboard_terms": banned_hits,
        "tiny_font_sizes_px": sorted(set(tiny_fonts)),
        "thin_border_rules": card_borders,
        "has_top_bar": has_top_bar,
        "linear_ui_anims": linear_ui_anims,
    }


def inspect_vtt(vtt_path: Path) -> dict[str, Any]:
    raw = vtt_path.read_text(encoding="utf-8", errors="ignore")
    lines = raw.splitlines()

    # Extract STYLE block(s)
    style_text = ""
    in_style = False
    for ln in lines:
        if ln.strip().upper() == "STYLE":
            in_style = True
            continue
        if in_style:
            if not ln.strip():
                in_style = False
            else:
                style_text += ln + "\n"

    # Check opaque dark background box on ::cue
    opaque_cue_bg = False
    cue_bg_evidence = ""
    for m in re.finditer(r"background(?:-color)?\s*:\s*([^;}\n]+)", style_text, re.I):
        val = m.group(1).strip().lower()
        if "transparent" in val or val == "none":
            continue
        m_rgba = re.search(r"rgba\s*\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([0-9.]+)\s*\)", val)
        if m_rgba:
            alpha = float(m_rgba.group(1))
            if alpha >= 0.55:
                opaque_cue_bg = True
                cue_bg_evidence = val
        elif val.startswith("#") or val.startswith("rgb(") or val in ("black", "#000", "#000000"):
            opaque_cue_bg = True
            cue_bg_evidence = val

    # Parse cues
    cues: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        if "-->" in lines[i]:
            timing = lines[i]
            m_line = re.search(r"line\s*:\s*([0-9.]+)%", timing)
            line_pct = float(m_line.group(1)) if m_line else None
            j = i + 1
            text_lines: list[str] = []
            while j < len(lines) and lines[j].strip():
                text_lines.append(lines[j].strip())
                j += 1
            joined = "\n".join(text_lines)
            plain_lines = [re.sub(r"<[^>]+>", "", tl).strip() for tl in text_lines]
            plain_all = "".join(plain_lines)
            has_hi = bool(re.search(r"<c(?:\.[A-Za-z0-9_-]+)?>", joined))
            cues.append({
                "line_count": len(plain_lines),
                "char_len": len(re.sub(r"\s+", "", plain_all)),
                "line_pct": line_pct,
                "has_highlight": has_hi,
                "sample": plain_all[:24],
            })
            i = j
        else:
            i += 1

    total_cues = len(cues)
    multiline_cues = sum(1 for c in cues if c["line_count"] > 1)
    long_cues = [c["sample"] for c in cues if c["char_len"] > 14]
    hi_cues = sum(1 for c in cues if c["has_highlight"])
    unsafe_low_cues = sum(1 for c in cues if c["line_pct"] is not None and c["line_pct"] > 78.0)

    return {
        "file": vtt_path.name,
        "total_cues": total_cues,
        "opaque_cue_bg": opaque_cue_bg,
        "cue_bg_evidence": cue_bg_evidence,
        "multiline_cues": multiline_cues,
        "multiline_ratio": round(multiline_cues / total_cues, 3) if total_cues else 0.0,
        "long_cues_count": len(long_cues),
        "long_cues_samples": long_cues[:5],
        "highlight_cues_count": hi_cues,
        "unsafe_low_cues": unsafe_low_cues,
    }


def lint_film(film_dir: Path, mode: str) -> dict[str, Any]:
    film_html = film_dir / "film.html"
    if not film_html.is_file():
        raise FileNotFoundError(f"未找到 {film_html}")

    parser = FilmHTMLParser()
    parser.feed(film_html.read_text(encoding="utf-8"))

    errors: list[str] = []
    warnings: list[str] = []

    stage_w, stage_h = parser.viewport
    fullscreen_aroll: list[tuple[float, float]] = []
    small_window_speaker: list[tuple[float, float]] = []
    small_window_count = 0
    hud_overlays: list[tuple[float, float]] = []
    static_broll_long: list[dict[str, Any]] = []
    iframe_files: list[str] = []
    bgm_clips: list[dict[str, Any]] = []
    sfx_clips: list[dict[str, Any]] = []
    max_end = 0.0
    vtt_src: str | None = None
    cutout_used = False

    # Inspect clips across sections
    for sec in parser.sections:
        sec_id = sec["id"]
        for clip in sec["clips"]:
            tag = clip["tag"]
            attrs = clip["attrs"]
            src = attrs.get("src", "")
            cid = attrs.get("id", src)
            at = float(attrs.get("at", "0") or 0)
            t_in, t_out = parse_frag_duration(src)
            speed = float(attrs.get("speed", "1") or 1)
            dur = ((t_out - t_in) / speed) if (t_in is not None and t_out is not None and t_out > t_in) else None
            end = (at + dur) if dur is not None else at
            if end > max_end:
                max_end = end

            style_map = parse_inline_style(attrs.get("style", ""))
            w = parse_px(style_map.get("width"))
            h = parse_px(style_map.get("height"))
            if "--of-cutout" in style_map or "--of-cutout" in attrs.get("class", ""):
                cutout_used = True

            if tag == "track":
                vtt_src = src
            elif tag == "video":
                is_small_box = (w is not None and w < stage_w * 0.92) or (h is not None and h < stage_h * 0.65)
                if dur is not None:
                    if is_small_box:
                        small_window_speaker.append((at, at + dur))
                        small_window_count += 1
                    else:
                        fullscreen_aroll.append((at, at + dur))
            elif tag == "img":
                is_tiny_logo = (w is not None and w <= 260) or ("logo" in src.lower())
                if not is_tiny_logo and dur is not None and dur > 3.55:
                    static_broll_long.append({"id": cid, "src": src.split("#")[0], "duration_sec": round(dur, 2)})
            elif tag == "iframe":
                page_name = src.split("#")[0]
                if page_name:
                    iframe_files.append(page_name)
                if dur is not None and ("hud" in sec_id.lower() or "overlay" in sec_id.lower() or "hud" in cid.lower() or "hud" in page_name.lower()):
                    hud_overlays.append((at, at + dur))
            elif tag == "audio":
                kind = classify_audio(sec_id, cid, src, dur)
                vol = float(attrs.get("volume", "1.0") or 1.0)
                if kind == "bgm":
                    bgm_clips.append({
                        "id": cid,
                        "src": src.split("#")[0],
                        "at": at,
                        "dur": dur,
                        "end": end,
                        "volume": vol,
                        "overrides": attrs.get("overrides", ""),
                    })
                elif kind == "sfx":
                    sfx_clips.append({
                        "id": cid,
                        "src": src.split("#")[0],
                        "at": at,
                        "has_frag_trim": bool(re.search(r"#t=", src)),
                        "volume": vol,
                    })

    # Fallback total duration from voice track if needed
    total_dur = round(max_end, 2) if max_end > 0 else 1.0

    # --- Rule 1 & 4: Fullscreen A-roll & Clean Breathing Ratio ---
    aroll_sec = total_covered(fullscreen_aroll)
    small_win_sec = total_covered(small_window_speaker)
    clean_aroll_sec = total_covered(subtract_intervals(fullscreen_aroll, hud_overlays))

    aroll_ratio = round(aroll_sec / total_dur, 3)
    small_win_ratio = round(small_win_sec / total_dur, 3)
    clean_aroll_ratio = round(clean_aroll_sec / total_dur, 3)

    if mode == "talking_head":
        if aroll_ratio < 0.55:
            errors.append(
                f"[门禁1-全屏人像主舞台] 全屏真人出镜占比仅 {aroll_ratio*100:.1f}%（< 55% 硬线），"
                f"小窗/画中画口播占比达 {small_win_ratio*100:.1f}%（{small_window_count} 处），呈现网课小窗模板感。"
            )
        if small_window_count >= 3 or small_win_ratio > 0.20:
            errors.append(
                f"[门禁1-去网课小窗/监控画中画] 检测到 {small_window_count} 处小窗/PiP 口播盒（占全片 {small_win_ratio*100:.1f}%）；"
                "B-roll 应干脆全屏切走，禁止把「上小窗+下卡片」当默认模具反复套用。"
            )
        if clean_aroll_ratio < 0.20:
            errors.append(
                f"[门禁4-纯人像呼吸留白] 零叠层干净全屏人像占比仅 {clean_aroll_ratio*100:.1f}%（要求 ≥ 25%，底线 ≥ 20%），画面缺乏喘息留白。"
            )
        elif clean_aroll_ratio < 0.25:
            warnings.append(
                f"[门禁4-纯人像呼吸留白] 干净全屏人像占比 {clean_aroll_ratio*100:.1f}%，建议提升至 ≥ 25%。"
            )

    # --- Rule 5: Static B-roll Duration ---
    for sb in static_broll_long:
        errors.append(
            f"[门禁5-B-roll生命力] 静态图片 {sb['src']}（{sb['id']}）停留 {sb['duration_sec']}s（> 3.5s 硬上限），"
            "请替换为动态竖屏视频或拆分短镜。"
        )

    # --- Rule 2 & 3: Scene HTML Dashboard / Overload Check ---
    page_reports: list[dict[str, Any]] = []
    top_bar_pages = 0
    for pname in sorted(set(iframe_files)):
        pp = film_dir / pname
        if not pp.is_file():
            continue
        pr = inspect_scene_page(pp)
        page_reports.append(pr)
        if pr["banned_dashboard_terms"]:
            errors.append(
                f"[门禁2-去网页后台/英文眉标] 页面 {pname} 含禁用装饰英文眉标：{', '.join(pr['banned_dashboard_terms'][:5])}"
            )
        if pr["readable_units"] > 40:
            errors.append(
                f"[门禁3-单帧单焦点] 页面 {pname} 可见字数达 {pr['readable_units']} 字（> 40 字硬红线，建议 ≤ 20–25 字），信息严重过载像 PPT/网页。"
            )
        elif pr["readable_units"] > 25:
            warnings.append(
                f"[门禁3-单帧精简] 页面 {pname} 可见字数 {pr['readable_units']} 字（建议压缩至 ≤ 25 字）。"
            )
        if pr["tiny_font_sizes_px"]:
            errors.append(
                f"[门禁3-手机可读字号] 页面 {pname} 存在 <22px 蚂蚁字（{pr['tiny_font_sizes_px']}px），次级说明字号须 ≥ 32px。"
            )
        if pr["thin_border_rules"] >= 4:
            errors.append(
                f"[门禁2-去SaaS卡片墙] 页面 {pname} 含 {pr['thin_border_rules']} 条细实线边框规则，呈多格网页卡片墙风格。"
            )
        if pr["has_top_bar"]:
            top_bar_pages += 1

    if top_bar_pages >= 2:
        errors.append(
            f"[门禁2-去常驻网页顶栏] {top_bar_pages} 个分镜页面包含顶部常驻导航栏/进度条，易产生网课/营销号模板感。"
        )

    # --- Rule 6: Captions Integration & Short-Beat ---
    vtt_report: dict[str, Any] | None = None
    if vtt_src:
        vp = film_dir / vtt_src.split("#")[0]
        if vp.is_file():
            vtt_report = inspect_vtt(vp)
            if vtt_report["opaque_cue_bg"]:
                errors.append(
                    f"[门禁6-字幕去黑膏药] {vp.name} 的 ::cue 使用不透明深色背景块（{vtt_report['cue_bg_evidence']}），"
                    "请改为透明底 + 细腻描边/多层柔影（可用 scripts/format_captions.py 一键生成）。"
                )
            if vtt_report["multiline_ratio"] > 0.15:
                errors.append(
                    f"[门禁6-单行短句字幕] {vp.name} 有 {vtt_report['multiline_cues']}/{vtt_report['total_cues']} 条为多行字幕（{vtt_report['multiline_ratio']*100:.1f}% > 15%），"
                    "请拆分为 6–12 字单行短句节拍。"
                )
            if vtt_report["total_cues"] > 0 and (vtt_report["long_cues_count"] / vtt_report["total_cues"]) > 0.20:
                errors.append(
                    f"[门禁6-单行字数超限] {vp.name} 有 {vtt_report['long_cues_count']} 条字幕超过 14 字（示例：{vtt_report['long_cues_samples'][:3]}）。"
                )
            if total_dur >= 15.0 and vtt_report["highlight_cues_count"] == 0:
                warnings.append(
                    f"[门禁6-关键词高亮] {vp.name} 未使用 <c.hi> 关键词高亮，建议每 1–2 句高亮 1 个核心词。"
                )
            if vtt_report["unsafe_low_cues"] > 0:
                errors.append(
                    f"[门禁6-字幕安全区] {vp.name} 有 {vtt_report['unsafe_low_cues']} 条字幕 line > 78%，存在被平台底栏遮挡风险。"
                )

    # --- Rule 9: SFX Restraint ---
    sfx_budget = 4 if total_dur <= 35.0 else (7 if total_dur <= 75.0 else 12)
    sfx_count = len(sfx_clips)
    if sfx_count > sfx_budget:
        errors.append(
            f"[门禁9-音效克制上限] 全片 {total_dur:.1f}s 放置了 {sfx_count} 个 SFX（硬上限 ≤ {sfx_budget} 个），请削减非必要提示音。"
        )
    loud_sfx = [s for s in sfx_clips if s["volume"] > 0.35]
    if loud_sfx:
        errors.append(
            f"[门禁9-音效防抢人声] 检测到 {len(loud_sfx)} 个高音量 SFX（volume > 0.35，最高 {max(s['volume'] for s in loud_sfx)}），"
            "须压在人声下方 -18~-26 dB（通常 volume 0.10–0.28）。"
        )
    trimmed_sfx = [s["id"] for s in sfx_clips if s["has_frag_trim"]]
    if trimmed_sfx:
        warnings.append(f"[门禁9-短音效勿截尾] 以下 SFX 带 #t= 截尾可能触发 WebAudio 时长误差：{trimmed_sfx[:5]}")

    sfx_src_counts = Counter(s["src"] for s in sfx_clips)
    repeated_whoosh = [(src, cnt) for src, cnt in sfx_src_counts.items() if cnt >= 4 and any(k in src.lower() for k in ("whoosh", "swipe"))]
    if repeated_whoosh:
        errors.append(
            f"[门禁9-禁每切必咻] 同一转场音效被机械重复触发 ≥4 次：{repeated_whoosh}；普通景别跳切不要配转场音效。"
        )

    # --- Rule 10: BGM Breathing & Silence Drop ---
    bgm_intervals = [(b["at"], b["end"]) for b in bgm_clips if b["dur"] is not None]
    bgm_cov_ratio = round(total_covered(bgm_intervals) / total_dur, 3) if bgm_intervals else 0.0
    max_bgm_vol = max((b["volume"] for b in bgm_clips), default=0.0)
    has_low_dip = any(b["volume"] <= 0.05 for b in bgm_clips)
    # Check gaps >= 0.5s inside [2.0, total_dur - 2.0]
    merged_bgm = merge_intervals(bgm_intervals)
    silence_gaps = []
    for idx in range(len(merged_bgm) - 1):
        g_start, g_end = merged_bgm[idx][1], merged_bgm[idx + 1][0]
        if g_end - g_start >= 0.5:
            silence_gaps.append({"start": round(g_start, 2), "end": round(g_end, 2), "duration": round(g_end - g_start, 2)})

    if mode == "talking_head" and max_bgm_vol > 0.20:
        errors.append(f"[门禁10-BGM音量] BGM 最高 volume={max_bgm_vol}（> 0.20），口播底乐建议压在 0.07–0.13（-22~-26 dB）。")
    elif mode == "talking_head" and max_bgm_vol > 0.14:
        warnings.append(f"[门禁10-BGM偏响] BGM 最高 volume={max_bgm_vol}，请结合人声响度确认稳定低人声 22–26 dB。")

    if total_dur >= 25.0 and bgm_clips and bgm_cov_ratio >= 0.97 and not silence_gaps and not has_low_dip:
        errors.append(
            f"[门禁10-BGM静音呼吸] 全片 {total_dur:.1f}s BGM 连续覆盖 {bgm_cov_ratio*100:.1f}% 且零静音真空（≥0.5s），呈死直线铺底；"
            "请在核心反问/金句前增加至少 1 次 BGM 柔淡抽空停顿。"
        )

    # Compute aesthetic_checks summary aligned to video-craft.md §七
    def has_err(prefix: str) -> bool:
        return any(e.startswith(prefix) for e in errors)

    aesthetic_checks = [
        {"id": 1, "item": "全屏人像主舞台与去网课小窗/监控画中画", "passed": not has_err("[门禁1")},
        {"id": 2, "item": "去网页后台/常驻顶栏/英文代码眉标/SaaS卡片墙", "passed": not has_err("[门禁2")},
        {"id": 3, "item": "单帧单焦点、字数精简与手机可读字号", "passed": not has_err("[门禁3")},
        {"id": 4, "item": "纯人像呼吸留白段占比达标", "passed": not has_err("[门禁4")},
        {"id": 5, "item": "B-roll 动态生命力与静态兜底图 ≤3.5s", "passed": not has_err("[门禁5")},
        {"id": 6, "item": "透明描边单行短句高亮字幕与安全区", "passed": not has_err("[门禁6")},
        {"id": 7, "item": "文字零重复打架（需配合 openfilm look 目检确认）", "passed": True, "requires_visual_check": True},
        {"id": 8, "item": "物理阻尼缓动与语流语义卡点（需配合试看核验）", "passed": True, "requires_visual_check": True},
        {"id": 9, "item": "音效总数上限、低存在感与禁每切必咻", "passed": not has_err("[门禁9")},
        {"id": 10, "item": "BGM 压人声下且具静音真空呼吸感", "passed": not has_err("[门禁10")},
    ]

    score = max(0, 100 - len(errors) * 12 - len(warnings) * 3)
    return {
        "film_dir": rel_to_root(film_dir),
        "mode": mode,
        "passed": len(errors) == 0,
        "score": score,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "metrics": {
            "duration_sec": total_dur,
            "fullscreen_aroll_ratio": aroll_ratio,
            "small_window_speaker_ratio": small_win_ratio,
            "small_window_speaker_count": small_window_count,
            "clean_aroll_breathing_ratio": clean_aroll_ratio,
            "cutout_depth_used": cutout_used,
            "long_static_broll_count": len(static_broll_long),
            "scene_pages_checked": len(page_reports),
            "top_bar_pages": top_bar_pages,
            "sfx_count": sfx_count,
            "sfx_budget": sfx_budget,
            "bgm_coverage_ratio": bgm_cov_ratio,
            "bgm_max_volume": max_bgm_vol,
            "bgm_silence_gaps": silence_gaps,
        },
        "errors": errors,
        "warnings": warnings,
        "vtt_report": vtt_report,
        "scene_pages": page_reports,
        "aesthetic_checks": aesthetic_checks,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="短视频导演级视听反违和自动质检器（video-craft.md）")
    ap.add_argument("--film", required=True, help="OpenFilm 项目目录（含 film.html）")
    ap.add_argument("--mode", choices=["talking_head", "faceless"], default="talking_head", help="口播真人片或纯无出镜资讯片")
    ap.add_argument("--json-out", default="", help="可选：将完整报告写入 JSON 文件")
    args = ap.parse_args()

    report = lint_film(Path(args.film), args.mode)
    out_str = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        op = Path(args.json_out)
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(out_str + "\n", encoding="utf-8")
    print(out_str)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
