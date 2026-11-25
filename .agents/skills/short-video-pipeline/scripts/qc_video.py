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
                - Static film.html / subtitles.html / scenes CSS / publish.json gates
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


def render_safezone_overlays(
    video: Path, duration: float, out_dir: Path
) -> dict[str, str]:
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

    # Build 3x2 high-res safe-zone contact sheet (1620x1920)
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

    # Full-res 1080x1920 ending frame at duration - 0.8s
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

    return {
        "safezone_grid": rel_path(grid_path),
        "safezone_tail": rel_path(tail_path),
        "grid_timestamps_sec": timestamps,
        "tail_timestamp_sec": tail_t,
    }


def strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def audit_film_dir(
    film_dir: Path, duration: float, hard_failures: list[str], warnings: list[str]
) -> dict[str, Any]:
    details: dict[str, Any] = {}
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

        # 3. Check wide PiP with horizontal object-position
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
                if h > 0 and (w / h) > 1.85:
                    warnings.append(
                        f"PiP 窗口 {w}x{h} (宽高比 {w/h:.2f} > 1.85) 套用 16:9 原片时横向 object-position 无效，易露出右侧大片空墙，建议内层容器 scale+translateX 居中"
                    )
                    break

    # 4. Check subtitles.html for forward-loop lag bug & dangling opening/ending cues
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
                    f"末句字幕结束于 {last_end:.2f}s，距全片结束({duration:.2f}s)仅余 {duration - last_end:.2f}s(<0.35s)，收尾偏仓促，建议留 0.4-1.0s 尾韵缓冲"
                )

    # 5. Scan scenes/*.html & *.css for cards dropping into bottom 360px dead zone (top >= 1540px)
    scenes_dir = film_dir / "scenes"
    if scenes_dir.exists():
        bottom_traps: list[str] = []
        tiny_fonts: list[str] = []
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
        if bottom_traps:
            hard_failures.append(
                f"检测到界面元素定位于底部 360px 平台遮挡死区(y>=1540px): {', '.join(bottom_traps[:6])}"
            )
        if tiny_fonts:
            warnings.append(
                f"检测到极小字号(<18px，手机端难以辨认): {', '.join(sorted(set(tiny_fonts))[:6])}"
            )

    return details


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

    overlays: dict[str, Any] = {}
    if args.out_dir:
        overlays = render_safezone_overlays(video, duration, Path(args.out_dir))

    film_checks: dict[str, Any] = {}
    if args.film_dir:
        film_checks = audit_film_dir(Path(args.film_dir), duration, hard_failures, warnings)

    pub_checks: dict[str, Any] = {}
    if args.publish_json:
        pub_checks = audit_publish_json(Path(args.publish_json), hard_failures, warnings)

    report = {
        "video": rel_path(video),
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
        help="Run acoustic, safe-zone overlay, film HTML/subtitle, and publish.json QC.",
    )
    p_render.add_argument("--video", required=True, help="Rendered MP4 path")
    p_render.add_argument("--film-dir", help="OpenFilm project film/ directory")
    p_render.add_argument("--publish-json", help="publish/publish.json path")
    p_render.add_argument(
        "--out-dir",
        help="Output directory for safezone-grid.png, safezone-tail.png, and qc-report.json",
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
