#!/usr/bin/env python3
"""Short-video pipeline pre-flight audio probe & post-render QC helper.

Uses ONLY Python stdlib + ffmpeg/ffprobe. Strictly read-only on source assets/videos.

Subcommands:
  probe-audio   Measure raw BGM/SFX/voice loudness, LRA, true peak, first-6s drop,
                and peak offset so film.html never guesses volume blindly.
  audit-render  Inspect rendered MP4 + optional film/ & publish.json:
                - Acoustic check (LUFS, LRA, True Peak, limiter wall, tail 0.35s cut)
                - Safe-zone visual overlay sheets (safezone-grid.png, safezone-tail.png)
                  marking Top 180px, Bottom 360px, Right button bar x=930..1080 y=850..1500,
                  and chin reference line y=1120
                - Cut-point frame-burst verification (safezone-cuts.png: t-1f / t / t+1f)
                - Cutout & sticker occlusion sheet (safezone-cutouts.png: midpoint frames
                  of every --of-cutout:1 and sticker shot with head/face protection guide)
                - Editing & VFX craft checks: ASL/shot pacing, single-use visual asset
                  enforcement (count == 1 per video), visual information density
                  (text-only card ratio <= 25%, semantic SVG/Canvas motion >= 45%,
                  static B-roll SVG foreground check), cutout behind-person text occlusion
                  & sticker head/face overlap checks, cross-track floating-point
                  double-head overlap, continuous-shot scale snap-back, ghost-spoiler
                  opacity, static line-through, fake REC HUD, BGM hard splice, SFX density
                - Static subtitles.html lag-bug/opening/ending & publish.json gates
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}

OPENING_FILLER_PATTERNS = [
    r"像我刚刚讲的",
    r"正如刚才",
    r"刚才说到",
    r"^反而是",
    r"^所以说",
    r"^那我们就把",
    r"^那这个",
]

ENDING_DANGLING_PATTERNS = [
    r"(——|…|\.\.\.)\s*$",
    r"(但是|不过|可是|所以|比如|例如|而且|接下来|也就是说)[，,：:——…\s]*$",
]

DESC_SECONDS_PATTERNS = [
    re.compile(r"第\s*\d+\s*秒"),
    re.compile(r"最后\s*\d+\s*秒"),
    re.compile(r"片[头尾中]?\s*\d+\s*秒"),
    re.compile(r"\d+\s*秒[起处后内]"),
    re.compile(r"(这[支条份段个]|全片|视频|短片|片段)\s*\d+\s*秒"),
    re.compile(r"\d+\s*秒\s*(短片|片段|实证|拆解|视频|精讲|看完|看懂)"),
    re.compile(r"\d+\s*分\s*\d+\s*秒"),
    re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)"),
]

SHIPINHAO_FORBIDDEN_RE = re.compile(r"[,，.。!！、—\-()（）\[\]【】/\\|\s\r\n]")

STYLE_ASL_THRESHOLDS = {
    "master": 7.5,
    "v1": 4.0,
    "v2": 7.5,
    "v3": 8.0,
    "default": 7.5,
}


def rel_path(path: Path) -> str:
    svp = os.environ.get("SVP_ROOT")
    base = Path(svp).resolve() if svp else Path.cwd().resolve()
    try:
        return path.resolve().relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def ffprobe_json(path: Path) -> dict[str, Any]:
    proc = run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,format_name,bit_rate",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ]
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def parse_ebur128(stderr: str) -> dict[str, float | None]:
    result: dict[str, float | None] = {
        "integrated_lufs": None,
        "lra_lu": None,
        "true_peak_dbtp": None,
    }
    summary_idx = stderr.rfind("Summary:")
    tail = stderr[summary_idx:] if summary_idx != -1 else stderr
    m_i = re.search(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", tail)
    m_lra = re.search(r"LRA:\s*(-?\d+(?:\.\d+)?)\s*LU", tail)
    m_tp = re.search(r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", tail)
    if m_i:
        result["integrated_lufs"] = float(m_i.group(1))
    if m_lra:
        result["lra_lu"] = float(m_lra.group(1))
    if m_tp:
        result["true_peak_dbtp"] = float(m_tp.group(1))
    return result


def parse_volumedetect(stderr: str) -> dict[str, Any]:
    mean_m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", stderr)
    max_m = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", stderr)
    hist: dict[int, int] = {}
    for db_s, cnt_s in re.findall(r"histogram_(\d+)db:\s*(\d+)", stderr):
        hist[int(db_s)] = int(cnt_s)
    return {
        "mean_volume_db": float(mean_m.group(1)) if mean_m else None,
        "max_volume_db": float(max_m.group(1)) if max_m else None,
        "limiter_wall_samples_0_to_2db": hist.get(0, 0) + hist.get(1, 0) + hist.get(2, 0),
    }


def analyze_audio_segment(
    path: Path, ss: float | None = None, dur: float | None = None
) -> dict[str, Any]:
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if ss is not None and ss > 0:
        cmd += ["-ss", f"{ss:.3f}"]
    cmd += ["-i", str(path)]
    if dur is not None and dur > 0:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-vn", "-af", "ebur128=peak=true,volumedetect", "-f", "null", "-"]
    proc = run_cmd(cmd)
    out = parse_ebur128(proc.stderr)
    out.update(parse_volumedetect(proc.stderr))
    return out


def find_sfx_peak_offset_ms(path: Path) -> int | None:
    """Locate the first timestamp (ms) of peak momentary loudness via ebur128 frames."""
    proc = run_cmd(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-vn",
            "-af",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ]
    )
    best_t: float | None = None
    best_val = -999.0
    for m in re.finditer(
        r"t:\s*(\d+(?:\.\d+)?).*?FTPK:\s*(-?\d+(?:\.\d+)?)", proc.stderr
    ):
        t_val = float(m.group(1))
        pk_val = float(m.group(2))
        if pk_val > best_val:
            best_val = pk_val
            best_t = t_val
    if best_t is None:
        return None
    return int(round(best_t * 1000))


def recommend_gain(raw_lufs: float | None, target_lufs: float) -> float | None:
    if raw_lufs is None or raw_lufs <= -70:
        return None
    db_diff = target_lufs - raw_lufs
    vol = 10 ** (db_diff / 20.0)
    return round(min(max(vol, 0.02), 2.5), 3)


def cmd_probe_audio(args: argparse.Namespace) -> int:
    files: list[Path] = []
    for raw in args.targets:
        p = Path(raw)
        if p.is_dir():
            for f in sorted(p.iterdir()):
                if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
                    files.append(f)
        elif p.is_file():
            files.append(p)
        else:
            print(f"[warn] not found: {raw}", file=sys.stderr)

    results: list[dict[str, Any]] = []
    for f in files:
        info = ffprobe_json(f)
        dur = float(info.get("format", {}).get("duration", 0) or 0)
        stats = analyze_audio_segment(f)
        role_guess = "bgm_or_voice" if dur >= 10.0 else "sfx"
        warnings: list[str] = []
        rec: dict[str, Any] = {}

        if role_guess == "bgm_or_voice":
            first6 = analyze_audio_segment(f, ss=0.0, dur=min(6.0, dur))
            stats["first_6s_mean_db"] = first6["mean_volume_db"]
            if (
                stats["mean_volume_db"] is not None
                and first6["mean_volume_db"] is not None
                and (stats["mean_volume_db"] - first6["mean_volume_db"]) >= 10.0
            ):
                warnings.append(
                    f"前6秒均值({first6['mean_volume_db']} dB)比全曲均值({stats['mean_volume_db']} dB)低>=10dB，严禁直接从#t=0起铺，建议跳过前奏从起势段切入"
                )
            if stats["lra_lu"] is not None and stats["lra_lu"] > 12.0:
                warnings.append(
                    f"动态范围LRA={stats['lra_lu']} LU过高(>12 LU)，直接铺底易忽隐忽现，建议先轻压缩或换平稳曲目"
                )
            rec["bgm_volume_under_voice_target_minus31lufs"] = recommend_gain(
                stats["integrated_lufs"], -31.0
            )
            rec["bgm_volume_hook_or_outro_target_minus26lufs"] = recommend_gain(
                stats["integrated_lufs"], -26.0
            )
        else:
            peak_ms = find_sfx_peak_offset_ms(f)
            stats["peak_offset_ms"] = peak_ms
            if stats["true_peak_dbtp"] is not None and stats["true_peak_dbtp"] >= -0.5:
                warnings.append(
                    f"原生峰值极热/削波({stats['true_peak_dbtp']} dBTP)，务必大幅压低volume防气口刺耳"
                )
            if stats["integrated_lufs"] is not None and stats["integrated_lufs"] >= -10.0:
                warnings.append(
                    f"原生响度极高({stats['integrated_lufs']} LUFS)，作为点缀音效volume建议<=0.08"
                )
            if stats["integrated_lufs"] is not None and stats["integrated_lufs"] <= -26.0:
                warnings.append(
                    f"原生响度偏轻({stats['integrated_lufs']} LUFS)，常规0.15~0.25音量会几乎听不见"
                )
            if peak_ms is not None and peak_ms > 500:
                warnings.append(
                    f"峰值延后至{peak_ms}ms(>500ms)，属慢爬坡音效，不宜直接卡切镜点，建议改用短促音效或按峰值前移触发"
                )
            if dur > 0.65:
                warnings.append(
                    f"音效时长{dur:.2f}s(>0.65s)，做转场whoosh易拖尾压人声字头，建议换<=0.45s短音效或加尾淡出"
                )
            rec["sfx_subtle_accent_target_minus28lufs"] = recommend_gain(
                stats["integrated_lufs"], -28.0
            )
            rec["sfx_transition_target_minus24lufs"] = recommend_gain(
                stats["integrated_lufs"], -24.0
            )

        results.append(
            {
                "file": rel_path(f),
                "duration_sec": round(dur, 3),
                "role_guess": role_guess,
                "metrics": stats,
                "recommended_volume": rec,
                "warnings": warnings,
            }
        )

    print(json.dumps({"audio_probe": results}, ensure_ascii=False, indent=2))
    return 0


def parse_clips_in_section(section_html: str) -> list[dict[str, Any]]:
    clips: list[dict[str, Any]] = []
    for m in re.finditer(r"<(video|iframe|img)\b([^>]*)>", section_html, flags=re.IGNORECASE):
        tag = m.group(1).lower()
        attrs = m.group(2)
        src_m = re.search(r'src=["\']([^"\']+)["\']', attrs)
        at_m = re.search(r'\bat=["\'](\d+(?:\.\d+)?)["\']', attrs)
        dur_m = re.search(r'\bdur=["\'](\d+(?:\.\d+)?)["\']', attrs)
        id_m = re.search(r'\bid=["\']([^"\']+)["\']', attrs)
        cls_m = re.search(r'\bclass=["\']([^"\']+)["\']', attrs)
        style_m = re.search(r'style=["\']([^"\']+)["\']', attrs)
        if not src_m:
            continue
        raw_src = src_m.group(1)
        base_src = raw_src.split("#", 1)[0]
        at_val = float(at_m.group(1)) if at_m else 0.0
        t_in: float | None = None
        t_out: float | None = None
        tm = re.search(r"#t=(\d+(?:\.\d+)?)(?:,(\d+(?:\.\d+)?))?", raw_src)
        if tm:
            t_in = float(tm.group(1))
            t_out = float(tm.group(2)) if tm.group(2) else None
        dur = (t_out - t_in) if (t_in is not None and t_out is not None) else (
            float(dur_m.group(1)) if dur_m else None
        )
        end_val = (at_val + dur) if dur is not None else None
        anim_name = None
        if style_m:
            am = re.search(r"animation:\s*([A-Za-z0-9_-]+)", style_m.group(1))
            if am:
                anim_name = am.group(1)
        clips.append(
            {
                "tag": tag,
                "id": id_m.group(1) if id_m else base_src,
                "classes": cls_m.group(1).split() if cls_m else [],
                "base_src": base_src,
                "at": at_val,
                "t_in": t_in,
                "t_out": t_out,
                "dur": dur,
                "end": end_val,
                "anim": anim_name,
                "style": style_m.group(1) if style_m else "",
            }
        )
    return clips


def parse_css_px(style: str, prop: str, default: float | None = None) -> float | None:
    m = re.search(rf"(?:^|[;\s]){re.escape(prop)}\s*:\s*(-?\d+(?:\.\d+)?)px", style, flags=re.IGNORECASE)
    return float(m.group(1)) if m else default


def inspect_behind_person_scene(scene_path: Path) -> dict[str, Any]:
    """Analyze a scene HTML placed behind a --of-cutout: 1 speaker for occludable text/info."""
    info: dict[str, Any] = {
        "scene": scene_path.name,
        "svg_texts": [],
        "html_texts": [],
        "too_low_texts": [],
        "long_texts": [],
        "has_behind_text": False,
    }
    if not scene_path.is_file():
        return info
    txt = scene_path.read_text(encoding="utf-8", errors="replace")

    # Parse <style> CSS class rules inside the scene HTML
    cls_css: dict[str, str] = {}
    for sb in re.findall(r"<style\b[^>]*>([\s\S]*?)</style>", txt, flags=re.IGNORECASE):
        for cm in re.finditer(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}", sb):
            cls_css[cm.group(1)] = cls_css.get(cm.group(1), "") + ";" + cm.group(2)

    def resolve_css(attrs: str) -> str:
        parts: list[str] = []
        cm = re.search(r'\bclass=["\']([^"\']+)["\']', attrs, flags=re.IGNORECASE)
        if cm:
            for c in cm.group(1).split():
                if c in cls_css:
                    parts.append(cls_css[c])
        sm = re.search(r'\bstyle=["\']([^"\']+)["\']', attrs, flags=re.IGNORECASE)
        if sm:
            parts.append(sm.group(1))
        return ";".join(parts)

    # 1. Inspect SVG <text ... y="...">...</text>
    for m in re.finditer(r"<text\b([^>]*)>([\s\S]*?)</text>", txt, flags=re.IGNORECASE):
        attrs, inner = m.group(1), m.group(2)
        clean = strip_html(inner)
        if not clean:
            continue
        ym = re.search(r'\by=["\'](-?\d+(?:\.\d+)?)["\']', attrs)
        y_val = float(ym.group(1)) if ym else 500.0
        char_len = len(re.sub(r"\s+", "", clean))
        item = {"y": y_val, "text": clean, "chars": char_len}
        info["svg_texts"].append(item)
        if y_val > 540.0:
            info["too_low_texts"].append(item)
        if char_len > 6:
            info["long_texts"].append(item)

    # 2. Inspect non-pill HTML text blocks (supporting both inline style and CSS class top/font-size)
    body_m = re.search(r"<body\b[^>]*>([\s\S]*?)</body>", txt, flags=re.IGNORECASE)
    body_html = body_m.group(1) if body_m else txt
    body_no_noise = re.sub(r"<(script|style|svg)\b[\s\S]*?</\1>", "", body_html, flags=re.IGNORECASE)
    # Remove single-level top pill / eyebrow badges (top < 230px with small font <= 36px)
    pill_cls_re = re.compile(r"\b(?:pill|top-pill|top-tag|cap|eyebrow|badge)\b", flags=re.IGNORECASE)

    # Match positioned or text-bearing container elements (including nested .l1/.l2/.g1/.g2 lines)
    for m in re.finditer(
        r"<(div|h[1-6]|p)\b([^>]*)>([\s\S]*?)</\1>",
        body_no_noise,
        flags=re.IGNORECASE,
    ):
        attrs, inner = m.group(2), m.group(3)
        css = resolve_css(attrs)
        top_val = parse_css_px(css, "top")
        fs_val = parse_css_px(css, "font-size")
        cls_m = re.search(r'\bclass=["\']([^"\']+)["\']', attrs, flags=re.IGNORECASE)
        cls_str = cls_m.group(1) if cls_m else ""
        # Skip wrapper containers like .stage that have no top/font-size of their own
        if top_val is None and fs_val is None:
            continue
        # Skip small top eyebrow pills (top < 230px and font-size <= 38px)
        if (top_val is not None and top_val < 230.0) and (fs_val is None or fs_val <= 38.0):
            continue
        if pill_cls_re.search(cls_str) and (fs_val is None or fs_val <= 38.0):
            continue

        # Extract sub-lines if child divs exist (e.g. <div class="l1">...</div><div class="l2">...</div>)
        sub_divs = re.findall(r"<(div|span|p)\b([^>]*)>([\s\S]*?)</\1>", inner, flags=re.IGNORECASE)
        lines: list[tuple[float, str]] = []
        base_top = top_val if top_val is not None else 450.0
        if sub_divs:
            cur_y = base_top
            for _, s_attrs, s_inner in sub_divs:
                s_clean = strip_html(s_inner)
                if not s_clean:
                    continue
                s_css = resolve_css(s_attrs)
                s_fs = parse_css_px(s_css, "font-size", fs_val or 64.0) or 64.0
                lines.append((cur_y + s_fs * 0.85, s_clean))
                cur_y += s_fs * 1.15
        else:
            clean = strip_html(inner)
            if clean:
                eff_fs = fs_val or 48.0
                lines.append((base_top + eff_fs * 0.85, clean))

        for line_y, line_txt in lines:
            if any(x["text"] == line_txt for x in info["html_texts"]):
                continue
            char_len = len(re.sub(r"\s+", "", line_txt))
            item = {"y": round(line_y, 1), "text": line_txt[:40], "chars": char_len}
            info["html_texts"].append(item)
            if line_y > 540.0:
                info["too_low_texts"].append(item)
            if char_len > 6:
                info["long_texts"].append(item)

    all_behind = [x for x in info["svg_texts"] if x["y"] >= 240.0] + info["html_texts"]
    info["has_behind_text"] = len(all_behind) > 0
    info["behind_text_count"] = len(all_behind)
    return info


def detect_style_slot(video: Path, film_dir: Path | None, explicit: str | None) -> str:
    if explicit and explicit != "auto":
        return explicit
    hay = f"{video.as_posix()} {film_dir.as_posix() if film_dir else ''}".lower()
    if "01-v1" in hay or "/v1-" in hay:
        return "v1"
    if "02-v2" in hay or "/v2-" in hay:
        return "v2"
    if "03-v3" in hay or "/v3-" in hay:
        return "v3"
    if "00-master" in hay or "/master/" in hay:
        return "master"
    return "default"


def render_safezone_overlays(
    video: Path,
    duration: float,
    out_dir: Path,
    cut_points: list[float] | None = None,
    cutout_sticker_points: list[float] | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    # 1080x1920 3-platform UI forbidden zones:
    # - Top 180px (status bar / Dynamic Island / platform tabs)
    # - Bottom 360px (y=1560..1920 captions / account / nav)
    # - Right interactive button bar (x=930..1080, y=850..1500)
    # - Cyan horizontal guide at y=1120 (recommended chin clearance for fullscreen cards)
    box_filter = (
        "drawbox=x=0:y=0:w=1080:h=180:color=red@0.26:t=fill,"
        "drawbox=x=0:y=178:w=1080:h=3:color=red@0.90:t=fill,"
        "drawbox=x=0:y=1560:w=1080:h=360:color=red@0.26:t=fill,"
        "drawbox=x=0:y=1560:w=1080:h=3:color=red@0.90:t=fill,"
        "drawbox=x=930:y=850:w=150:h=650:color=orange@0.32:t=fill,"
        "drawbox=x=930:y=850:w=3:h=650:color=orange@0.95:t=fill,"
        "drawbox=x=930:y=850:w=150:h=3:color=orange@0.95:t=fill,"
        "drawbox=x=930:y=1497:w=150:h=3:color=orange@0.95:t=fill,"
        "drawbox=x=0:y=1120:w=1080:h=2:color=cyan@0.55:t=fill"
    )

    timestamps = [
        min(1.5, max(0.2, duration * 0.05)),
        duration * 0.22,
        duration * 0.45,
        duration * 0.68,
        max(0.2, duration - 2.0),
        max(0.2, duration - 0.2),
    ]
    timestamps = [round(min(max(t, 0.05), max(0.05, duration - 0.05)), 2) for t in timestamps]

    grid_path = out_dir / "safezone-grid.png"
    tail_path = out_dir / "safezone-tail.png"

    cmd_grid = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for t in timestamps:
        cmd_grid += ["-ss", f"{t:.2f}", "-i", str(video)]
    f_parts = []
    for idx in range(len(timestamps)):
        f_parts.append(
            f"[{idx}:v]scale=1080:1920,{box_filter},scale=540:960[v{idx}]"
        )
    f_parts.append("[v0][v1][v2]hstack=inputs=3[top]")
    f_parts.append("[v3][v4][v5]hstack=inputs=3[bot]")
    f_parts.append("[top][bot]vstack=inputs=2[out]")
    cmd_grid += [
        "-filter_complex",
        ";".join(f_parts),
        "-map",
        "[out]",
        "-frames:v",
        "1",
        str(grid_path),
    ]
    proc1 = run_cmd(cmd_grid)
    if proc1.returncode != 0:
        raise RuntimeError(f"safezone-grid render failed: {proc1.stderr.strip()}")

    tail_t = round(max(0.05, duration - 0.8), 2)
    proc2 = run_cmd(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{tail_t:.2f}",
            "-i",
            str(video),
            "-vf",
            f"scale=1080:1920,{box_filter}",
            "-frames:v",
            "1",
            str(tail_path),
        ]
    )
    if proc2.returncode != 0:
        raise RuntimeError(f"safezone-tail render failed: {proc2.stderr.strip()}")

    result: dict[str, Any] = {
        "safezone_grid": rel_path(grid_path),
        "safezone_tail": rel_path(tail_path),
        "grid_timestamps_sec": timestamps,
        "tail_timestamp_sec": tail_t,
    }

    # Cut-point frame-burst verification (t-1f / t / t+1f) for up to 3 cuts
    valid_cuts = [c for c in (cut_points or []) if 0.1 < c < (duration - 0.1)]
    if valid_cuts:
        # Pick up to 3 representative cuts (first, middle, last)
        if len(valid_cuts) <= 3:
            picked = valid_cuts
        else:
            picked = [valid_cuts[0], valid_cuts[len(valid_cuts) // 2], valid_cuts[-1]]
        cuts_path = out_dir / "safezone-cuts.png"
        cmd_cuts = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        f_cut_parts: list[str] = []
        row_labels: list[str] = []
        inp_idx = 0
        for row_i, ct in enumerate(picked):
            tri = [max(0.02, ct - 0.034), ct, min(duration - 0.02, ct + 0.034)]
            row_inps = []
            for tt in tri:
                cmd_cuts += ["-ss", f"{tt:.3f}", "-i", str(video)]
                lbl = f"c{inp_idx}"
                f_cut_parts.append(f"[{inp_idx}:v]scale=360:640[{lbl}]")
                row_inps.append(f"[{lbl}]")
                inp_idx += 1
            rlbl = f"row{row_i}"
            f_cut_parts.append(f"{''.join(row_inps)}hstack=inputs=3[{rlbl}]")
            row_labels.append(f"[{rlbl}]")
        if len(row_labels) == 1:
            final_map = row_labels[0]
        else:
            f_cut_parts.append(
                f"{''.join(row_labels)}vstack=inputs={len(row_labels)}[cuts_out]"
            )
            final_map = "[cuts_out]"
        cmd_cuts += [
            "-filter_complex",
            ";".join(f_cut_parts),
            "-map",
            final_map,
            "-frames:v",
            "1",
            str(cuts_path),
        ]
        proc3 = run_cmd(cmd_cuts)
        if proc3.returncode == 0:
            result["safezone_cuts"] = rel_path(cuts_path)
            result["cut_burst_timestamps_sec"] = [round(c, 3) for c in picked]

    # Cutout & sticker midpoint inspection sheet (safezone-cutouts.png) with magenta head-zone guide
    raw_cs = sorted({round(t, 2) for t in (cutout_sticker_points or []) if 0.05 < t < (duration - 0.05)})
    # Deduplicate timestamps within 1.2s (keeps the later timestamp so overlapping cutout+sticker show together)
    valid_cs: list[float] = []
    for t in raw_cs:
        if valid_cs and (t - valid_cs[-1]) < 1.2:
            valid_cs[-1] = t
        else:
            valid_cs.append(t)
    if valid_cs:
        if len(valid_cs) > 6:
            step = (len(valid_cs) - 1) / 5.0
            picked_cs = [valid_cs[int(round(i * step))] for i in range(6)]
        else:
            picked_cs = valid_cs
        cs_path = out_dir / "safezone-cutouts.png"
        head_box_filter = (
            box_filter
            + ",drawbox=x=220:y=280:w=640:h=740:color=magenta@0.80:t=4"
            + ",drawbox=x=0:y=640:w=1080:h=2:color=yellow@0.70:t=fill"
        )
        cmd_cs = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        f_cs_parts: list[str] = []
        for idx, tt in enumerate(picked_cs):
            cmd_cs += ["-ss", f"{tt:.2f}", "-i", str(video)]
            f_cs_parts.append(
                f"[{idx}:v]scale=1080:1920,{head_box_filter},scale=360:640[cs{idx}]"
            )
        n = len(picked_cs)
        if n <= 3:
            if n == 1:
                cs_map = "[cs0]"
            else:
                f_cs_parts.append(
                    f"{''.join(f'[cs{i}]' for i in range(n))}hstack=inputs={n}[cs_out]"
                )
                cs_map = "[cs_out]"
        else:
            cols = 3
            pad_n = (cols - (n % cols)) % cols
            for p_i in range(pad_n):
                f_cs_parts.append(f"color=c=black:s=360x640:d=1[csp{p_i}]")
            all_lbls = [f"[cs{i}]" for i in range(n)] + [f"[csp{p_i}]" for p_i in range(pad_n)]
            r1 = "".join(all_lbls[:3])
            r2 = "".join(all_lbls[3:6])
            f_cs_parts.append(f"{r1}hstack=inputs=3[csr1]")
            f_cs_parts.append(f"{r2}hstack=inputs=3[csr2]")
            f_cs_parts.append("[csr1][csr2]vstack=inputs=2[cs_out]")
            cs_map = "[cs_out]"
        cmd_cs += [
            "-filter_complex",
            ";".join(f_cs_parts),
            "-map",
            cs_map,
            "-frames:v",
            "1",
            str(cs_path),
        ]
        proc4 = run_cmd(cmd_cs)
        if proc4.returncode == 0:
            result["safezone_cutouts"] = rel_path(cs_path)
            result["cutout_sticker_timestamps_sec"] = picked_cs

    return result


def strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def audit_film_dir(
    film_dir: Path,
    duration: float,
    style_slot: str,
    hard_failures: list[str],
    warnings: list[str],
) -> tuple[dict[str, Any], list[float], list[float]]:
    details: dict[str, Any] = {"style_slot": style_slot}
    cut_points: list[float] = []
    cutout_sticker_points: list[float] = []
    film_html = film_dir / "film.html"
    if film_html.exists():
        html_txt = film_html.read_text(encoding="utf-8", errors="replace")

        # 1. Check multi-segment BGM without fade
        bgm_sec = re.search(
            r'<section[^>]*id=["\']bgm["\'][^>]*>(.*?)</section>',
            html_txt,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if bgm_sec:
            bgm_tags = re.findall(r"<audio\b[^>]*>", bgm_sec.group(1), flags=re.IGNORECASE)
            details["bgm_segments"] = len(bgm_tags)
            if len(bgm_tags) >= 2:
                missing_fade = [t for t in bgm_tags if "fade" not in t.lower()]
                if missing_fade:
                    hard_failures.append(
                        f"film.html 多段 BGM 拼接（共 {len(bgm_tags)} 段）存在 {len(missing_fade)} 段未配置 fade 交叉淡化，易产生硬切跳变"
                    )

        # 2. Count SFX density
        sfx_secs = re.findall(
            r'<section[^>]*id=["\'][^"\']*sfx[^"\']*["\'][^>]*>(.*?)</section>',
            html_txt,
            flags=re.IGNORECASE | re.DOTALL,
        )
        sfx_count = sum(
            len(re.findall(r"<audio\b", sec, flags=re.IGNORECASE)) for sec in sfx_secs
        )
        details["sfx_count"] = sfx_count
        if duration > 0 and sfx_count > max(3, math.ceil(duration / 5.0)):
            warnings.append(
                f"点缀/转场音效共 {sfx_count} 次（{duration:.1f}s 内平均每 {duration/sfx_count:.1f}s 一次），高于 <=1次/5s 建议红线，易显得嘈杂"
            )

        # 3. Parse main-stage, speaker-pip, cutout-fg, and stickers
        main_sec = re.search(
            r'<section[^>]*id=["\']main-stage["\'][^>]*>(.*?)</section>',
            html_txt,
            flags=re.IGNORECASE | re.DOTALL,
        )
        pip_sec = re.search(
            r'<section[^>]*id=["\']speaker-pip["\'][^>]*>(.*?)</section>',
            html_txt,
            flags=re.IGNORECASE | re.DOTALL,
        )
        main_clips = parse_clips_in_section(main_sec.group(1)) if main_sec else []
        pip_clips = parse_clips_in_section(pip_sec.group(1)) if pip_sec else []

        cutout_clips: list[dict[str, Any]] = []
        for cm in re.finditer(
            r'<section[^>]*id=["\'][^"\']*cutout[^"\']*["\'][^>]*>(.*?)</section>',
            html_txt,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            cutout_clips.extend(parse_clips_in_section(cm.group(1)))

        sticker_clips: list[dict[str, Any]] = []
        for sm in re.finditer(
            r'<section[^>]*id=["\'][^"\']*sticker[^"\']*["\'][^>]*>(.*?)</section>',
            html_txt,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            sticker_clips.extend(parse_clips_in_section(sm.group(1)))

        # Parse <style> CSS blocks so class-defined top/height/translateY/--of-cutout are respected
        css_class_rules: dict[str, str] = {}
        for style_blk in re.findall(r"<style\b[^>]*>([\s\S]*?)</style>", html_txt, flags=re.IGNORECASE):
            for cm in re.finditer(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}", style_blk):
                css_class_rules[cm.group(1)] = css_class_rules.get(cm.group(1), "") + ";" + cm.group(2)

        # Identify speaker source video basenames (dominant video + pip/cutout videos)
        all_video_refs = re.findall(
            r'<video\b[^>]*src=["\']([^"\']+\.(?:mp4|mov|webm|mkv))(?:#[^"\']*)?["\']',
            html_txt,
            flags=re.IGNORECASE,
        )
        vid_freq_early: dict[str, int] = {}
        for vr in all_video_refs:
            bn = Path(vr).name.lower()
            vid_freq_early[bn] = vid_freq_early.get(bn, 0) + 1
        speaker_vids_early: set[str] = set()
        if vid_freq_early:
            speaker_vids_early.add(max(vid_freq_early, key=vid_freq_early.get))
        for c in pip_clips + cutout_clips:
            if c["tag"] == "video":
                speaker_vids_early.add(Path(c["base_src"]).name.lower())

        if main_clips:
            main_clips.sort(key=lambda c: c["at"])
            shot_count = len(main_clips)
            asl = duration / shot_count if shot_count > 0 else 0.0
            max_shot = max((c["dur"] or 0.0) for c in main_clips)
            details["main_stage_shots"] = shot_count
            details["asl_sec"] = round(asl, 2)
            details["max_shot_sec"] = round(max_shot, 2)
            cut_points = [c["at"] for c in main_clips[1:] if c["at"] > 0]

            asl_limit = STYLE_ASL_THRESHOLDS.get(style_slot, 7.5)
            if asl > asl_limit:
                warnings.append(
                    f"剪辑节奏偏慢：main-stage 共 {shot_count} 镜，平均镜长 ASL={asl:.2f}s（{style_slot} 槽位建议 <= {asl_limit:.1f}s），最长单镜 {max_shot:.2f}s，建议拆镜/加4K跳切或全屏B-roll打破僵硬"
                )

            # Check adjacent continuous <video> clips reusing the exact same scale animation (snap-back bug!)
            for prev_c, next_c in zip(main_clips, main_clips[1:]):
                if (
                    prev_c["tag"] == "video"
                    and next_c["tag"] == "video"
                    and prev_c["base_src"] == next_c["base_src"]
                    and prev_c["t_out"] is not None
                    and next_c["t_in"] is not None
                    and abs(prev_c["t_out"] - next_c["t_in"]) < 0.05
                    and prev_c["anim"]
                    and prev_c["anim"] == next_c["anim"]
                ):
                    hard_failures.append(
                        f"film.html 连续同机位视频 `{prev_c['id']}` → `{next_c['id']}` 在 {next_c['at']:.2f}s 处切分并复用同一动画 `{prev_c['anim']}`，必然造成缩放倒退回弹穿帮，请合并为单条连续 <video>"
                    )

        # Check cross-track floating-point overlap: upper speaker-pip overlapping lower main-stage fullscreen <video>
        if pip_clips and main_clips:
            fs_videos = [c for c in main_clips if c["tag"] == "video"]
            for pc in pip_clips:
                if pc["end"] is None:
                    continue
                for fv in fs_videos:
                    # Overlap or IEEE-754 boundary hazard (within +1e-9..+0.05s or full overlap)
                    if pc["end"] > fv["at"] - 1e-6 and pc["at"] < (fv["end"] or duration):
                        overlap_ms = (pc["end"] - fv["at"]) * 1000.0
                        if overlap_ms >= -0.001:
                            hard_failures.append(
                                f"film.html 跨轨叠影穿帮风险：上轨 `{pc['id']}` 结束于 {pc['end']:.6f}s 与下轨全屏 `{fv['id']}` 起点 {fv['at']:.2f}s 重叠/浮点贴边（Δ={overlap_ms:+.2f}ms），易导致 1 帧双人头重影；请将上轨提前 >=0.034s 收口或改做显式转场"
                            )

        # 4. Check wide PiP with horizontal object-position & PiP height drift
        pip_heights: set[int] = set()
        for m in re.finditer(
            r"<video\b[^>]*pip[^>]*style=[\"']([^\"']+)[\"']",
            html_txt,
            flags=re.IGNORECASE,
        ):
            st = m.group(1)
            wm = re.search(r"width:\s*(\d+)px", st)
            hm = re.search(r"height:\s*(\d+)px", st)
            if wm and hm:
                w, h = int(wm.group(1)), int(hm.group(1))
                pip_heights.add(h)
                if h > 0 and (w / h) > 1.85 and "wide_pip_warned" not in details:
                    details["wide_pip_warned"] = True
                    warnings.append(
                        f"PiP 窗口 {w}x{h} (宽高比 {w/h:.2f} > 1.85) 套用 16:9 原片时横向 object-position 无效，易露出右侧大片空墙，建议内层容器 scale+translateX 居中"
                    )
        if len(pip_heights) >= 3:
            warnings.append(
                f"同一成片内 PiP 窗口出现 {len(pip_heights)} 种不同高度 ({sorted(pip_heights)}px)，易造成切镜框体抽搐跳动，建议锁定统一 PiP 基线尺寸"
            )

        # 4b. Check cutout-fg behind-person occlusion & collect inspection midpoints
        cutout_reports: list[dict[str, Any]] = []
        cutout_meta: list[dict[str, Any]] = []
        for cc in cutout_clips:
            merged_css = ";".join(
                [css_class_rules.get(cls, "") for cls in cc.get("classes", [])] + [cc.get("style", "")]
            )
            top_px = parse_css_px(merged_css, "top", 0.0)
            height_px = parse_css_px(merged_css, "height", 1920.0)
            ty_m = re.search(r"translateY\(\s*(-?\d+(?:\.\d+)?)px\s*\)", merged_css, flags=re.IGNORECASE)
            translate_y = float(ty_m.group(1)) if ty_m else 0.0
            is_unlowered = (
                (top_px is not None and top_px < 120.0)
                and (height_px is not None and height_px >= 1600.0)
                and translate_y < 240.0
            )
            cc_end = cc["end"] if cc["end"] is not None else min(duration, cc["at"] + 3.0)
            cutout_sticker_points.append(round((cc["at"] + cc_end) / 2.0, 2))
            cutout_meta.append(
                {
                    "clip": cc,
                    "end": cc_end,
                    "top_px": top_px,
                    "height_px": height_px,
                    "is_unlowered": is_unlowered,
                }
            )

            # Inspect overlapping main-stage <iframe> scenes behind this cutout
            for mc in main_clips:
                if mc["tag"] != "iframe":
                    continue
                mc_end = mc["end"] if mc["end"] is not None else duration
                if mc["at"] < cc_end - 0.05 and mc_end > cc["at"] + 0.05:
                    scene_info = inspect_behind_person_scene(film_dir / mc["base_src"])
                    reasons: list[str] = []
                    if scene_info["has_behind_text"]:
                        if is_unlowered:
                            sample = " / ".join(
                                x["text"] for x in (scene_info["svg_texts"] + scene_info["html_texts"])[:3]
                            )
                            reasons.append(
                                f"未缩小下沉特写构图(top={top_px:.0f}px,height={height_px:.0f}px)遮挡人后文字「{sample}」"
                            )
                        if scene_info["too_low_texts"]:
                            low_desc = ", ".join(
                                f"y={x['y']:.0f}px「{x['text']}」" for x in scene_info["too_low_texts"][:2]
                            )
                            reasons.append(f"人后文字低于 y=540px({low_desc})")
                        if scene_info["long_texts"] or scene_info["behind_text_count"] >= 2:
                            long_desc = ", ".join(
                                f"「{x['text']}」({x['chars']}字)"
                                for x in (
                                    scene_info["long_texts"]
                                    or (scene_info["svg_texts"] + scene_info["html_texts"])
                                )[:2]
                            )
                            reasons.append(f"人后出现多行或长句({scene_info['behind_text_count']}行: {long_desc})")
                    cutout_reports.append(
                        {
                            "cutout_id": cc["id"],
                            "at": cc["at"],
                            "top_px": top_px,
                            "height_px": height_px,
                            "is_unlowered": is_unlowered,
                            "behind_scene": scene_info["scene"],
                            "behind_text_count": scene_info.get("behind_text_count", 0),
                            "violations": reasons,
                        }
                    )
                    if reasons:
                        hard_failures.append(
                            f"前景抠像 `{cc['id']}` (at={cc['at']:.2f}s) 与人后场景 `{scene_info['scene']}` 违反防遮挡硬规：{'；'.join(reasons)}。请将信息文字/图解改为全屏切出、PiP分屏或前景避让层，或缩小下沉人物抠像保头顶 y>=640px 且人后仅放 y=260..540px 单行 2-4 字短词"
                        )
        if cutout_reports:
            details["cutout_layer_checks"] = cutout_reports

        # 4c. Check stickers head/face avoidance & right platform button zone
        sticker_reports: list[dict[str, Any]] = []
        for sc in sticker_clips:
            st = sc.get("style", "")
            left_px = parse_css_px(st, "left")
            top_px = parse_css_px(st, "top")
            w_px = parse_css_px(st, "width", 120.0)
            h_px = parse_css_px(st, "height", 120.0)
            sc_end = sc["end"] if sc["end"] is not None else min(duration, sc["at"] + 1.8)
            cutout_sticker_points.append(round((sc["at"] + sc_end) / 2.0, 2))
            if left_px is None or top_px is None or w_px is None or h_px is None:
                continue
            x1, y1, x2, y2 = left_px, top_px, left_px + w_px, top_px + h_px
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            stk_rec: dict[str, Any] = {
                "id": sc["id"],
                "at": sc["at"],
                "box": [round(x1), round(y1), round(x2), round(y2)],
                "center": [round(cx), round(cy)],
                "status": "ok",
            }

            # Right platform button forbidden zone (x>920, y=850..1500)
            if x2 > 920.0 and y2 > 850.0 and y1 < 1500.0:
                stk_rec["status"] = "right_zone_violation"
                hard_failures.append(
                    f"stickers 动态贴纸 `{sc['id']}` (at={sc['at']:.2f}s, x={x1:.0f}..{x2:.0f}, y={y1:.0f}..{y2:.0f}) 侵入右侧平台按钮禁区(x>920, y=850..1500)"
                )

            # Check if fullscreen talking head or cutout speaker is active during sticker
            active_unlowered = False
            active_lowered_cutout = False
            for cm in cutout_meta:
                if cm["clip"]["at"] < sc_end - 0.05 and cm["end"] > sc["at"] + 0.05:
                    if cm["is_unlowered"]:
                        active_unlowered = True
                    else:
                        active_lowered_cutout = True
            if not active_unlowered:
                for mc in main_clips:
                    if mc["tag"] != "video":
                        continue
                    mc_bn = Path(mc["base_src"]).name.lower()
                    if mc_bn not in speaker_vids_early and not re.search(
                        r"(^clip|speaker|talking|master-clip)", mc_bn
                    ):
                        continue
                    mc_end = mc["end"] if mc["end"] is not None else duration
                    if mc["at"] < sc_end - 0.05 and mc_end > sc["at"] + 0.05:
                        active_unlowered = True
                        break

            if active_unlowered or active_lowered_cutout:
                hx1, hy1, hx2, hy2 = (220.0, 280.0, 860.0, 1020.0) if active_unlowered else (220.0, 620.0, 860.0, 1360.0)
                if hx1 <= cx <= hx2 and hy1 <= cy <= hy2:
                    stk_rec["status"] = "head_overlap_hard"
                    hard_failures.append(
                        f"stickers 动态贴纸 `{sc['id']}` (at={sc['at']:.2f}s, 中心=({cx:.0f},{cy:.0f})) 落入人物头肩禁区(x={hx1:.0f}..{hx2:.0f}, y={hy1:.0f}..{hy2:.0f})，存在压头/压脸穿帮；请锚定具体载体并移出头肩区"
                    )
                else:
                    ix = max(0.0, min(x2, hx2) - max(x1, hx1))
                    iy = max(0.0, min(y2, hy2) - max(y1, hy1))
                    inter = ix * iy
                    area = max(1.0, w_px * h_px)
                    if (inter / area) > 0.15:
                        stk_rec["status"] = "head_overlap_warn"
                        warnings.append(
                            f"stickers 动态贴纸 `{sc['id']}` (at={sc['at']:.2f}s, box=[{x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f}]) 与人物头肩禁区存在 {inter/area:.0%} 交叠，请目检确认未压头发/肩膀"
                        )
            sticker_reports.append(stk_rec)
        if sticker_reports:
            details["sticker_checks"] = sticker_reports

    # 5. Check subtitles.html for forward-loop lag bug & dangling opening/ending cues
    sub_file = film_dir / "scenes" / "subtitles.html"
    if sub_file.exists():
        sub_txt = sub_file.read_text(encoding="utf-8", errors="replace")
        has_forward_tail_break = bool(
            re.search(
                r"for\s*\(\s*let\s+i\s*=\s*0[\s\S]{0,260}?c\[1\]\s*\+\s*0\.\d+[\s\S]{0,120}?break",
                sub_txt,
            )
        )
        has_next_clamp = bool(re.search(r"Math\.min|nextStart|CUES\[i\s*\+\s*1\]", sub_txt))
        if has_forward_tail_break and not has_next_clamp:
            hard_failures.append(
                "scenes/subtitles.html 存在正序循环 `c[1] + 0.xx` 直接 break 缺陷（未按下一句起点截断），会导致紧密衔接字幕晚切 3-4 帧并吞掉入场动画"
            )

        cues = re.findall(
            r"\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*([\"'])(.*?)\3",
            sub_txt,
        )
        details["subtitle_cue_count"] = len(cues)
        if cues:
            first_start = float(cues[0][0])
            first_text = strip_html(cues[0][3])
            last_end = float(cues[-1][1])
            last_text = strip_html(cues[-1][3])
            details["first_cue"] = {"start": first_start, "text": first_text}
            details["last_cue"] = {"end": last_end, "text": last_text}

            if first_start <= 1.2:
                for pat in OPENING_FILLER_PATTERNS:
                    if re.search(pat, first_text):
                        warnings.append(
                            f"首句字幕含无前文跨片指代/残句风险（{first_start:.2f}s:「{first_text}」），建议裁净废语或前置结论钩子"
                        )
                        break

            for pat in ENDING_DANGLING_PATTERNS:
                if re.search(pat, last_text):
                    hard_failures.append(
                        f"末句字幕疑似悬空半句/转折引子（结束于 {last_end:.2f}s:「{last_text}」），严禁截断在未说完句子上"
                    )
                    break

            if duration > 0 and (duration - last_end) < 0.35:
                warnings.append(
                    f"末句字幕结束于 {last_end:.2f}s，距全片结束({duration:.2f}s)仅余 {duration - last_end:.2f}s(<0.35s)，收尾偏仓促，建议留 0.6-1.2s 尾韵缓冲"
                )

    # 6. Scan scenes/*.html & *.css for bottom dead-zone traps, tiny fonts, ghost spoilers,
    #    static line-through, fake REC HUD, single-use visual assets (count == 1), and
    #    anti-PPT visual information density (text-only <= 25%, semantic SVG/Canvas >= 45%)
    visual_asset_counts: dict[str, int] = {}
    broll_video_count = 0

    if film_html.exists():
        # Count direct <img> stickers/stills and non-talking-head B-roll <video> clips in film.html
        html_txt_all = film_html.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(
            r'<img\b[^>]*src=["\']([^"\']+\.(?:jpg|jpeg|png|webp|gif))(?:#[^"\']*)?["\']',
            html_txt_all,
            flags=re.IGNORECASE,
        ):
            bn = Path(m.group(1)).name.lower()
            if bn != "logo.png":
                visual_asset_counts[bn] = visual_asset_counts.get(bn, 0) + 1

        # Identify source talking-head videos (used in speaker-pip / cutout-fg or dominant main-stage source)
        video_refs_all = re.findall(
            r'<video\b[^>]*src=["\']([^"\']+\.(?:mp4|mov|webm|mkv))(?:#[^"\']*)?["\']',
            html_txt_all,
            flags=re.IGNORECASE,
        )
        vid_freq: dict[str, int] = {}
        for vr in video_refs_all:
            bn = Path(vr).name.lower()
            vid_freq[bn] = vid_freq.get(bn, 0) + 1
        dominant_vid = max(vid_freq, key=vid_freq.get) if vid_freq else None
        speaker_vids: set[str] = set()
        if dominant_vid:
            speaker_vids.add(dominant_vid)
        for sec_id in ("speaker-pip", "cutout-fg"):
            sm = re.search(
                rf'<section[^>]*id=["\']{sec_id}["\'][^>]*>(.*?)</section>',
                html_txt_all,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if sm:
                for vr in re.findall(
                    r'<video\b[^>]*src=["\']([^"\']+\.(?:mp4|mov|webm|mkv))(?:#[^"\']*)?["\']',
                    sm.group(1),
                    flags=re.IGNORECASE,
                ):
                    speaker_vids.add(Path(vr).name.lower())
        for vr in video_refs_all:
            bn = Path(vr).name.lower()
            if bn in speaker_vids or re.search(r"(^clip|speaker|talking|master-clip)", bn):
                continue
            broll_video_count += 1
            visual_asset_counts[bn] = visual_asset_counts.get(bn, 0) + 1

    scenes_dir = film_dir / "scenes"
    if scenes_dir.exists():
        bottom_traps: list[str] = []
        tiny_fonts: list[str] = []
        ghost_files: list[str] = []
        static_strikes: list[str] = []
        fake_rec_files: list[str] = []
        content_scenes = 0
        motion_graphic_scenes = 0
        text_only_scenes: list[str] = []
        plain_static_jpg_scenes: list[str] = []
        helper_scene_re = re.compile(
            r"^(?:subtitles|base-bg|bridge|fx-.*|.*transition.*|.*glitch.*|.*wipe.*)\.html$",
            re.IGNORECASE,
        )
        asset_ref_re = re.compile(
            r"""(?:src\s*=\s*["']([^"']+\.(?:jpg|jpeg|png|webp|gif|mp4|webm|mov))(?:#[^"']*)?["']|url\(\s*["']?([^"')]+?\.(?:jpg|jpeg|png|webp|gif))["']?\s*\))""",
            re.IGNORECASE,
        )

        for sf in sorted(scenes_dir.iterdir()):
            if sf.suffix.lower() not in {".html", ".css"} or sf.name == "subtitles.html":
                continue
            txt = sf.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"top:\s*(\d+)px", txt):
                y_val = int(m.group(1))
                if 1540 <= y_val <= 1880:
                    bottom_traps.append(f"{sf.name}: top={y_val}px")
            for m in re.finditer(r"font-size:\s*(\d+)px", txt):
                fs = int(m.group(1))
                if fs < 18:
                    tiny_fonts.append(f"{sf.name}: {fs}px")
            # Detect ghost-spoiler opacity patterns like `0.2 + 0.8 *` or `0.18 + 0.82 *` or `0.36 + 0.64 *`
            if re.search(r"opacity\s*=\s*String\(\s*0\.[1-5]\d*\s*\+", txt):
                ghost_files.append(sf.name)
            if "text-decoration: line-through" in txt or "text-decoration:line-through" in txt:
                static_strikes.append(sf.name)
            if style_slot == "v3" and re.search(r"REC\s*[·•]|SPEAKER\s+CAM", txt):
                fake_rec_files.append(sf.name)

            if sf.suffix.lower() == ".html" and not helper_scene_re.match(sf.name):
                lower_txt = txt.lower()
                scene_assets: list[str] = []
                for a, b in asset_ref_re.findall(txt):
                    bn = Path(a or b).name.lower()
                    if bn == "logo.png":
                        continue
                    visual_asset_counts[bn] = visual_asset_counts.get(bn, 0) + 1
                    scene_assets.append(bn)

                # Exclude outro/ending slates from text-only card penalty, count regular narrative scenes
                if not re.search(r"(?:outro|ending)", sf.name, re.IGNORECASE):
                    content_scenes += 1
                    has_svg = "<svg" in lower_txt
                    has_canvas = "<canvas" in lower_txt
                    has_video_tag = "<video" in lower_txt
                    has_jpg = any(x.endswith((".jpg", ".jpeg")) for x in scene_assets)
                    has_other_media = bool(scene_assets) or has_video_tag
                    if has_svg or has_canvas:
                        motion_graphic_scenes += 1
                    if not (has_svg or has_canvas or has_other_media):
                        text_only_scenes.append(sf.name)
                    if has_jpg and not (has_svg or has_canvas):
                        plain_static_jpg_scenes.append(sf.name)

        reused_assets = {k: v for k, v in visual_asset_counts.items() if v > 1}
        details["single_use_visual_assets"] = {
            "counts": visual_asset_counts,
            "reused": reused_assets,
            "passed": len(reused_assets) == 0,
        }
        if reused_assets:
            reused_desc = ", ".join(f"{k}({v}次)" for k, v in sorted(reused_assets.items()))
            hard_failures.append(
                f"违反「单支视频内视觉素材仅用1次」红线，检测到重复使用素材: {reused_desc}"
            )

        denom = content_scenes + broll_video_count
        if denom > 0:
            text_only_ratio = len(text_only_scenes) / denom
            motion_ratio = (motion_graphic_scenes + broll_video_count) / denom
            details["visual_density"] = {
                "content_scenes": content_scenes,
                "broll_video_clips": broll_video_count,
                "motion_graphic_scenes": motion_graphic_scenes,
                "text_only_scenes": len(text_only_scenes),
                "text_only_ratio": round(text_only_ratio, 3),
                "motion_ratio": round(motion_ratio, 3),
                "plain_static_jpg_scenes": plain_static_jpg_scenes,
            }
            if denom >= 4 and text_only_ratio > 0.25:
                warnings.append(
                    f"纯文字圆角卡片占比偏高（{len(text_only_scenes)}/{denom} = {text_only_ratio:.0%} > 25% 上限，如 {', '.join(text_only_scenes[:4])}），易显静态 PPT 感，建议改用语义 SVG/Canvas 动画或动态素材（见 references/editing-vfx.md）"
                )
            if denom >= 4 and motion_ratio < 0.45:
                warnings.append(
                    f"语义级 SVG/Canvas 动画及运动视频占比偏低（{motion_graphic_scenes + broll_video_count}/{denom} = {motion_ratio:.0%} < 45% 基线），建议将流程/对比/对话/数据链路改写为动态图解或补充运动 B-roll"
                )
            if plain_static_jpg_scenes:
                warnings.append(
                    f"检测到 {len(plain_static_jpg_scenes)} 个静态 .jpg B-roll 场景未叠加 SVG/Canvas 矢量前景动效层（{', '.join(plain_static_jpg_scenes[:4])}），建议叠加流动光点/准星/连线避免纯静图慢推"
                )

        if bottom_traps:
            hard_failures.append(
                f"检测到界面元素定位于底部 360px 平台遮挡死区(y>=1540px): {', '.join(bottom_traps[:6])}"
            )
        if tiny_fonts:
            warnings.append(
                f"检测到极小字号(<18px，手机端难以辨认): {', '.join(sorted(set(tiny_fonts))[:6])}"
            )
        if ghost_files:
            warnings.append(
                f"检测到未出场卡片幽灵透明度预显（opacity 0.15~0.55 提前剧透，易显 PPT 灰脏感）: {', '.join(ghost_files[:6])}，建议改用 0->1 弹性入场（见 references/editing-vfx.md）"
            )
        if static_strikes:
            warnings.append(
                f"检测到静态 CSS `text-decoration: line-through`（{', '.join(static_strikes[:4])}），建议改用 SVG stroke-dashoffset 动态笔触划除"
            )
        if fake_rec_files:
            warnings.append(
                f"电影沉浸槽位(v3)检测到伪监视器套壳 HUD（REC/SPEAKER CAM: {', '.join(fake_rec_files[:4])}），建议移除并改用动态宽银幕遮幅与光学景深"
            )

    return details, cut_points, cutout_sticker_points


def audit_publish_json(
    pub_path: Path, hard_failures: list[str], warnings: list[str]
) -> dict[str, Any]:
    data = json.loads(pub_path.read_text(encoding="utf-8"))
    platforms = data.get("platforms", {})
    checked: dict[str, Any] = {}
    for plat, cfg in platforms.items():
        desc = str(cfg.get("desc", "") or "")
        title = str(cfg.get("title", "") or "")
        topics = str(cfg.get("topics", "") or "")
        hits: list[str] = []
        for pat in DESC_SECONDS_PATTERNS:
            for m in pat.finditer(desc):
                hits.append(m.group(0))
        if hits:
            hard_failures.append(
                f"publish.json [{plat}] 视频描述违规提及秒数/时间点/片长: {', '.join(dict.fromkeys(hits))}"
            )
        if plat == "shipinhao":
            if not (6 <= len(title) <= 16):
                hard_failures.append(
                    f"publish.json [shipinhao] 短标题长度={len(title)} 不在 6-16 范围:「{title}」"
                )
            if SHIPINHAO_FORBIDDEN_RE.search(title):
                hard_failures.append(
                    f"publish.json [shipinhao] 短标题含空格或禁用符号:「{title}」"
                )
        elif plat == "xhs":
            if len(title) > 20:
                hard_failures.append(
                    f"publish.json [xhs] 标题长度={len(title)} 超过 20 字硬上限"
                )
            elif len(title) > 18:
                warnings.append(f"publish.json [xhs] 标题长度={len(title)} 超过 18 字保守建议")
        elif plat == "douyin":
            if len(title) > 30:
                hard_failures.append(
                    f"publish.json [douyin] 标题长度={len(title)} 超过 30 字硬上限"
                )
            topic_list = [t.strip() for t in topics.split(",") if t.strip()]
            if len(topic_list) > 5:
                hard_failures.append(
                    f"publish.json [douyin] 话题数={len(topic_list)} 超过 5 个硬上限"
                )
        checked[plat] = {"title_len": len(title), "desc_len": len(desc), "seconds_hits": hits}
    return checked


def cmd_audit_render(args: argparse.Namespace) -> int:
    video = Path(args.video)
    if not video.is_file():
        print(f"error: video not found: {video}", file=sys.stderr)
        return 1

    hard_failures: list[str] = []
    warnings: list[str] = []

    probe = ffprobe_json(video)
    fmt = probe.get("format", {})
    streams = probe.get("streams", [])
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(fmt.get("duration", 0) or 0)
    size_bytes = int(fmt.get("size", 0) or 0)

    if not v_stream or not a_stream:
        hard_failures.append("成片缺少视频流或音频流")
    else:
        w, h = int(v_stream.get("width", 0)), int(v_stream.get("height", 0))
        if (w, h) != (1080, 1920):
            hard_failures.append(f"成片分辨率为 {w}x{h}，不符合 1080x1920 竖屏标准")

    full_audio = analyze_audio_segment(video)
    lufs = full_audio["integrated_lufs"]
    lra = full_audio["lra_lu"]
    tp = full_audio["true_peak_dbtp"]
    if lufs is not None and not (-16.5 <= lufs <= -12.0):
        warnings.append(f"成片综合响度 {lufs} LUFS 偏离 -14 LUFS 目标区间(-16.5..-12.0)")
    if tp is not None and tp > -1.0:
        hard_failures.append(f"成片真峰值 {tp} dBTP 超过 -1.0 dBTP 安全红线（存在削波失真风险）")
    if duration >= 60.0 and lra is not None and lra < 4.0:
        warnings.append(
            f"长片({duration:.1f}s)响度范围 LRA={lra} LU 偏扁(<4.0 LU)，可能存在过度砖墙限幅听觉疲劳"
        )

    # Tail 0.35s cut check
    tail_dur = min(0.35, duration)
    tail_ss = max(0.0, duration - tail_dur)
    tail_audio = analyze_audio_segment(video, ss=tail_ss, dur=tail_dur)
    tail_mean = tail_audio.get("mean_volume_db")
    tail_max = tail_audio.get("max_volume_db")
    if (tail_mean is not None and tail_mean > -25.0) or (
        tail_max is not None and tail_max > -8.0
    ):
        hard_failures.append(
            f"片尾最后 0.35s 音频未自然落音/淡出（mean={tail_mean} dB, max={tail_max} dB），疑似半句硬截断或切入下句起音"
        )

    film_dir = Path(args.film_dir) if args.film_dir else None
    style_slot = detect_style_slot(video, film_dir, args.style)
    film_checks: dict[str, Any] = {}
    cut_points: list[float] = []
    cutout_sticker_points: list[float] = []
    if film_dir:
        film_checks, cut_points, cutout_sticker_points = audit_film_dir(
            film_dir, duration, style_slot, hard_failures, warnings
        )

    overlays: dict[str, Any] = {}
    if args.out_dir:
        overlays = render_safezone_overlays(
            video,
            duration,
            Path(args.out_dir),
            cut_points=cut_points,
            cutout_sticker_points=cutout_sticker_points,
        )

    pub_checks: dict[str, Any] = {}
    if args.publish_json:
        pub_checks = audit_publish_json(Path(args.publish_json), hard_failures, warnings)

    report = {
        "video": rel_path(video),
        "style_slot": style_slot,
        "duration_sec": round(duration, 3),
        "size_bytes": size_bytes,
        "resolution": (
            f"{v_stream.get('width')}x{v_stream.get('height')}" if v_stream else None
        ),
        "audio_full": full_audio,
        "audio_tail_0_35s": tail_audio,
        "safezone_overlays": overlays,
        "film_checks": film_checks,
        "publish_checks": pub_checks,
        "hard_failures": hard_failures,
        "warnings": warnings,
        "passed": len(hard_failures) == 0,
    }

    if args.out_dir:
        out_json = Path(args.out_dir) / "qc-report.json"
        out_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if hard_failures and not args.no_fail:
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Short-video pipeline pre-flight audio probe & post-render QC gate."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_audio = sub.add_parser(
        "probe-audio",
        help="Measure BGM/SFX loudness, LRA, true peak, first-6s drop, and peak offset.",
    )
    p_audio.add_argument("targets", nargs="+", help="Audio file(s) or directory")

    p_render = sub.add_parser(
        "audit-render",
        help="Run acoustic, safe-zone overlay, cut-point, editing/VFX, and publish.json QC.",
    )
    p_render.add_argument("--video", required=True, help="Rendered MP4 path")
    p_render.add_argument("--film-dir", help="OpenFilm project film/ directory")
    p_render.add_argument("--publish-json", help="publish/publish.json path")
    p_render.add_argument(
        "--style",
        choices=["auto", "master", "v1", "v2", "v3", "default"],
        default="auto",
        help="Style slot for ASL and VFX craft thresholds (default: auto-detect from path)",
    )
    p_render.add_argument(
        "--out-dir",
        help="Output directory for safezone-grid.png, safezone-tail.png, safezone-cuts.png, safezone-cutouts.png, and qc-report.json",
    )
    p_render.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0 even when hard_failures exist (report-only mode)",
    )

    args = parser.parse_args()
    if args.cmd == "probe-audio":
        return cmd_probe_audio(args)
    if args.cmd == "audit-render":
        return cmd_audit_render(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
