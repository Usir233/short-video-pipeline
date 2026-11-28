#!/usr/bin/env python3
"""Short-video pipeline broadcast audio conditioning & post-render V2 QC gate.

Uses ONLY Python stdlib + ffmpeg/ffprobe.

Subcommands:
  probe-audio     Measure raw BGM/SFX/voice loudness, LRA, true peak, first-6s drop,
                  and peak offset so film.html never guesses volume blindly.
  scan-compliance Scan ASR JSON / SRT / cue list for domestic platform policy & competitor
                  sensitive words (e.g. 抖音->某音) and output compliance-bleeps.json.
  prepare-voice   Pre-condition spoken voice with broadcast EQ + 3:1 compressor +
                  soft limiter + optional 1000Hz broadcast bleep masking (--bleeps).
  normalize-sfx  Peak-normalize short SFX (<10s) to -3.0 dBTP (optional 2.5kHz Foley
                 dip) and hard-reject broken/silent audio files (< -30 dBTP).
  build-bgm-bed   Parse film.html voice timeline and render an auto-ducked, LRA-tamed
                  BGM bed with Cold Open swell, Silence Drop windows, and outro fade.
  stabilize-broll Run 2-pass libvidstab optical stabilization on mild-shake B-roll clips
                  and hard-reject warped/timelapse clips that remain Tier C jittery.
  audit-render    Inspect rendered MP4 + optional film/, covers/, & publish.json:
                  - Broadcast acoustic gates (LUFS, LRA >= 3.6 LU, True Peak <= -1.0 dBTP,
                    brickwall limiter ceiling, first-3.5s warm-up drop, tail 0.35s cut,
                    all BGM sections ducking/hum/LRA/mood, SFX clusters/ghost/blacklist)
                  - EDL cutting gates (opening filler hard-ban, mid-sentence fake jump-cut,
                    unmasked non-contiguous speaker jump-cut)
                  - B-roll 5-point gates (YAVG < 18 dark leader, internal scdet >= 16,
                    64-bit center-crop dHash deduplication, aspect-ratio crop distortion,
                    vidstab high-frequency shake/jitter & double-motion scale clash)
                 - Boxless visual & optical gates (--of-lut presence, --of-cutout width
                   & homologous blurred video bed, nested dashboard panel ban, >=4 SVG
                   rect ban, fake progress bar without numbers, >1.0s blank skeleton wait,
                   subtitle echo banner ban, space-between missing-child hole, PiP face
                   framing, behind-person text occlusion, sticker head/style bans)
                 - Zero-pill subtitle gates (SUB1-SUB6 no .pill background box, >=40px,
                   <=15 net chars, no mid-cue comma, no punctuation in highlight, <=50% hl)
                 - Dual-track cover gates (contact-sheet.jpg, >=100/104px giant titles,
                   no >=3 small tag pills, no bare cutout on light bg, no coined phrases)
                 - Honest content_archetype copywriting & platform form gates
                 - Safe-zone & inspection sheets (safezone-grid/tail/cuts/broll/pip/cutouts.png)
  audit-matrix   Audit Entry E 4-slot orthogonal diversity (6D zero-pill subtitle
                 fingerprint, LUT diversity, PiP/layout anti-clone, cross-slot 64-bit
                 dHash B-roll uniqueness, pacing separation).
"""

from __future__ import annotations

import argparse
import concurrent.futures
from html.parser import HTMLParser
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import wave
import zipfile
from pathlib import Path
from typing import Any

ABSTRACT_JARGON_WORDS = {
    "底层", "逻辑", "生态", "赋能", "闭环", "抓手", "升维", "演进", "矩阵", "链路",
    "维度", "认知", "范式", "重构", "体系", "模型", "架构", "势能", "协同", "沉淀",
    "跃迁", "阶段", "核心", "关键", "本质", "趋势", "全面", "系统", "升级", "转型",
    "方向", "价值", "能力", "模式", "机制", "路径", "格局", "结构", "策略", "方法",
}

_SCRIPT_IGNORE_STR_RE = re.compile(
    r"^(?:Noto\s+Sans|Noto\s+Serif|PingFang|Microsoft\s+YaHei|Hiragino|SimHei|Songti|STZhongsong|"
    r"Bahnschrift|DIN\s+Alternate|Inter|JetBrains|SF\s+Pro|sans-serif|serif|monospace|"
    r"canvas|2d|div|span|svg|http|rgba?\(|#[0-9a-fA-F]{3,8}|translate|scale|opacity|px|%|none|block|flex)$",
    flags=re.IGNORECASE,
)


def _extract_script_text_literals(scripts: str) -> list[str]:
    """Extract human-visible CJK or quantitative string literals from <script> blocks (for <canvas> scenes)."""
    if not scripts:
        return []
    no_comments = re.sub(r"//[^\r\n]*|/\*[\s\S]*?\*/", " ", scripts)
    literals: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"""(['"`])((?:\\.|(?!\1)[^\\\r\n]){1,140})\1""", no_comments):
        val = re.sub(r"\s+", " ", m.group(2)).strip()
        if not val or _SCRIPT_IGNORE_STR_RE.match(val):
            continue
        has_cjk = bool(re.search(r"[\u4e00-\u9fff]", val))
        has_num_unit = bool(
            re.search(
                r"(?:[¥$]\s*\d+|\d+(?:\.\d+)?\s*(?:%|倍|万|亿|元|块|美金|美元|刀|年|月|天|L|kg|ms|x|X))",
                val,
            )
        )
        if (has_cjk or has_num_unit) and val not in seen:
            seen.add(val)
            literals.append(val)
    return literals


def _extract_scene_dual_text(html_txt: str) -> str:
    """Extract combined visible text from BOTH HTML/SVG DOM and <script> string literals."""
    body_m = re.search(r"<body\b[^>]*>([\s\S]*?)</body>", html_txt, flags=re.IGNORECASE)
    body_html = body_m.group(1) if body_m else html_txt
    dom_no_script = re.sub(r"<(script|style|defs|clipPath|mask)\b[\s\S]*?</\1>", " ", body_html, flags=re.IGNORECASE)
    dom_txt = strip_html(dom_no_script)
    scripts = "\n".join(re.findall(r"<script\b[^>]*>([\s\S]*?)</script>", html_txt, flags=re.IGNORECASE))
    js_lits = _extract_script_text_literals(scripts)
    if js_lits:
        return (dom_txt + " " + " ".join(js_lits)).strip()
    return dom_txt

SYNC_STOPWORDS = {
    "我们", "你们", "他们", "现在", "最近", "这个", "这些", "那个", "那些",
    "一个", "一些", "一件", "一种", "部分", "因为", "所以", "但是", "不过",
    "如果", "虽然", "而且", "或者", "还是", "以及", "已经", "开始", "正在",
    "可以", "可能", "觉得", "看到", "发现", "自己", "大家", "很多", "比较",
    "非常", "特别", "其实", "当时", "过去", "以前", "之后", "时候", "事情",
    "问题", "方面", "整个", "普遍", "慢慢", "几乎", "都是", "也是", "就是",
    "不是", "没有", "还有", "首先", "第一", "第二", "另外", "外加", "比如",
    "对于", "来讲", "跨境", "电商", "老板", "公司", "企业", "行业", "赛道",
}

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}

OPENING_FILLER_PATTERNS = [
    r"像我刚刚讲的",
    r"正如刚才",
    r"刚才说到",
    r"^反而是",
    r"^所以说",
    r"^那我们就把",
    r"^那这个",
    r"^在这个过程中[，,、\s]*$",
    r"^在这个过程中(?=AI|我们|大家|其实|就)",
    r"^在这样的?(?:一个)?(?:过程|背景|情况)下",
    r"^(?:然后)?最近(?:反正)?[你我他大]",
    r"应该是几几年",
    r"^我觉得(?:他们|大家|现在)?(?:现在)?都会有一个",
    r"^就是我们讲普遍性",
    r"^那另外我们发现一件事情",
    r"^[嗯呃啊哦唉]+[，,、\s]",
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

FALSE_PROMISE_DIAGNOSTIC_RE = re.compile(
    r"如何.{0,4}破局|怎么.{0,4}破局|破局(?:指南|方案|方向|方法|之道)|"
    r"(?:决策|自查|实操|对比|核查|避坑|落地)清单|避坑指南|实操步骤|三步解决|解决方案"
)

COINED_AMBIGUOUS_PHRASE_RE = re.compile(r"外遇行业|内忧外遇")

SHIPINHAO_FORBIDDEN_RE = re.compile(r"[,，.。!！、—\-()（）\[\]【】/\\|\s\r\n]")

SPEAKER_VID_NAME_RE = re.compile(
    r"(?:^clip|speaker|talking|master-clip|^00-|^01-|^02-|^03-|^04-)", re.IGNORECASE
)

MASKED_SENSITIVE_TOKEN_RE = re.compile(
    r"某(?:音|红书|频号|公号|信|手|站|宝|猫|多多|东|鱼|博|乎)|躺\*|稳\*不赔|短期暴\*|\*税不合规|违规补\*|侵\*品"
)

STYLE_ASL_THRESHOLDS = {
    "master": 7.5,  # G0 跨境AI十亿增长局 (S01 商业旗舰纪实)
    "v1": 3.5,      # G1 时奕聊AI经营 (S02 网感痛点快剪)
    "v2": 6.2,      # G2 辰奕AI经营实战 (S03/S10 白板推演与实战拆解)
    "v3": 5.5,      # G3 老郑AI经营实战 (S08/S07 误区证伪与实战避坑)
    "v4": 5.5,      # G4 老郑AI经营论 (S04 竖屏变形银幕散文电影)
    "default": 7.0,
}

STYLE_MAX_SPEAKER_SHOT_SEC = {
    "master": 8.8,
    "v1": 4.8,
    "v2": 6.5,
    "v3": 6.5,
    "v4": 6.5,
    "default": 8.5,
}

SLOT_ACCOUNT_MAP: dict[str, dict[str, str]] = {
    "master": {
        "group_id": "G0",
        "prefix": "00-master",
        "ip_name": "跨境AI十亿增长局",
        "default_style": "S01",
        "default_cover": "C1",
    },
    "v1": {
        "group_id": "G1",
        "prefix": "01-v1",
        "ip_name": "时奕聊AI经营",
        "default_style": "S02",
        "default_cover": "C2",
    },
    "v2": {
        "group_id": "G2",
        "prefix": "02-v2",
        "ip_name": "辰奕AI经营实战",
        "default_style": "S03",
        "default_cover": "C3",
    },
    "v3": {
        "group_id": "G3",
        "prefix": "03-v3",
        "ip_name": "老郑AI经营实战",
        "default_style": "S08",
        "default_cover": "C5",
    },
    "v4": {
        "group_id": "G4",
        "prefix": "04-v4",
        "ip_name": "老郑AI经营论",
        "default_style": "S04",
        "default_cover": "C4",
    },
}

# Domestic short-video platform (Douyin / XHS / Shipinhao) policy & cross-platform sensitive lexicon:
# (category, compiled_regex, masked_replacement)
PLATFORM_SENSITIVE_RULES: list[tuple[str, re.Pattern[str], str]] = [
    # 1. Off-platform traffic diversion triggers (checked BEFORE standalone platform names so '加微信'/'微信号' match whole phrase)
    (
        "off_platform_lead",
        re.compile(
            r"加我?(?:微信|威信|薇信|微)|私信我|后台私信|扫(?:一扫)?二维码|二维码|(?:微信|威信|薇信)号|拉你进群|免费领(?:取)?资料|评论区扣\s*1"
        ),
        "**",
    ),
    # 2. Cross-platform domestic social/e-commerce names
    ("cross_platform", re.compile(r"抖音"), "某音"),
    ("cross_platform", re.compile(r"小红书"), "某红书"),
    ("cross_platform", re.compile(r"视频号"), "某频号"),
    ("cross_platform", re.compile(r"微信公众号|公众号"), "某公号"),
    ("cross_platform", re.compile(r"微信|威信|薇信"), "某信"),
    ("cross_platform", re.compile(r"快手"), "某手"),
    ("cross_platform", re.compile(r"(?<![A-Za-z0-9])[Bb]站|哔哩哔哩"), "某站"),
    ("cross_platform", re.compile(r"淘宝"), "某宝"),
    ("cross_platform", re.compile(r"天猫"), "某猫"),
    ("cross_platform", re.compile(r"拼多多"), "某多多"),
    ("cross_platform", re.compile(r"京东"), "某东"),
    ("cross_platform", re.compile(r"闲鱼"), "某鱼"),
    ("cross_platform", re.compile(r"微博"), "某博"),
    ("cross_platform", re.compile(r"知乎"), "某乎"),
    # 3. Ad-law extreme claims & guaranteed-profit triggers
    ("ad_law_extreme", re.compile(r"躺赚"), "躺*"),
    ("ad_law_extreme", re.compile(r"稳赚不赔"), "稳*不赔"),
    ("ad_law_extreme", re.compile(r"一夜暴富"), "短期暴*"),
    ("ad_law_extreme", re.compile(r"日入过万"), "高额收益"),
    ("ad_law_extreme", re.compile(r"(?:行业|全网|全国|世界|全球|史上)第一"), "行业头部"),
    ("ad_law_extreme", re.compile(r"最顶级|国家级|史上最强|吊打全网|零风险包赚|100%包赚|100%有效"), "高标准"),
    # 4. Tax / gray-black-hat违规词
    ("gray_black_hat", re.compile(r"逃税|偷税|漏税|偷逃税"), "*税不合规"),
    ("gray_black_hat", re.compile(r"洗钱|地下钱庄"), "资金违规"),
    ("gray_black_hat", re.compile(r"灰色清关"), "灰清"),
    ("gray_black_hat", re.compile(r"刷单|刷好评|买水军"), "违规补*"),
    ("gray_black_hat", re.compile(r"假货|仿牌|高仿|盗版"), "侵*品"),
    ("gray_black_hat", re.compile(r"割韭菜"), "割**"),
    # 5. Platform high-risk trigger words
    ("platform_risk", re.compile(r"杀猪盘|电信诈骗|诈骗|传销|网赌|赌博"), "违规局"),
    ("platform_risk", re.compile(r"等死|找死|死路|逼死|卷死|搞死|弄死|猝死|自杀"), "出局"),
    ("platform_risk", re.compile(r"破产跑路|倒闭潮|裁员潮|暴雷跑路"), "经营出清"),
]


def find_policy_sensitive_hits(text: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    if not text:
        return hits
    occupied: list[tuple[int, int]] = []
    for cat, pat, masked in PLATFORM_SENSITIVE_RULES:
        for m in pat.finditer(text):
            s_i, e_i = m.start(), m.end()
            if any(not (e_i <= os_i or s_i >= oe_i) for os_i, oe_i in occupied):
                continue
            occupied.append((s_i, e_i))
            hits.append(
                {
                    "category": cat,
                    "raw_word": m.group(0),
                    "masked_text": masked,
                    "char_start": s_i,
                    "char_end": e_i,
                }
            )
    hits.sort(key=lambda x: x["char_start"])
    return hits


def mask_policy_sensitive_text(text: str) -> str:
    out = text
    for _, pat, masked in PLATFORM_SENSITIVE_RULES:
        out = pat.sub(masked, out)
    return out

VOICE_CONDITIONING_AF = (
    "highpass=f=85:poles=2,"
    "equalizer=f=260:t=q:w=1.4:g=-2.8,"
    "equalizer=f=3600:t=q:w=1.2:g=2.0,"
    "equalizer=f=6800:t=q:w=2.5:g=-2.2,"
    "treble=g=1.6:f=9500,"
    "acompressor=threshold=-21dB:ratio=3:attack=8:release=140:makeup=3.5dB:knee=4dB,"
    "alimiter=limit=0.84:attack=3:release=50:level=disabled"
)


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


def run_cmd_bytes(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


_CUDA_HWACCEL_AVAILABLE: bool | None = None


def has_cuda_hwaccel() -> bool:
    global _CUDA_HWACCEL_AVAILABLE
    if _CUDA_HWACCEL_AVAILABLE is not None:
        return _CUDA_HWACCEL_AVAILABLE
    if os.environ.get("SVP_DISABLE_PYTHON_GPU") == "1":
        _CUDA_HWACCEL_AVAILABLE = False
        return False
    try:
        proc = run_cmd(["ffmpeg", "-hide_banner", "-hwaccels"])
        accels = {line.strip().lower() for line in proc.stdout.splitlines() if line.strip()}
        _CUDA_HWACCEL_AVAILABLE = proc.returncode == 0 and "cuda" in accels
    except Exception:
        _CUDA_HWACCEL_AVAILABLE = False
    return _CUDA_HWACCEL_AVAILABLE


def run_ffmpeg_decode_cmd(build_cmd) -> subprocess.CompletedProcess[str]:
    if has_cuda_hwaccel():
        proc = run_cmd(build_cmd(["-hwaccel", "cuda"]))
        if proc.returncode == 0:
            return proc
    return run_cmd(build_cmd([]))


def ffprobe_json(path: Path) -> dict[str, Any]:
    proc = run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,format_name,bit_rate:format_tags=comment",
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


def compute_visual_dhash(path: Path, sample_t: float | None = None) -> int | None:
    """Compute center-cropped (72%x72%) 9x8 grayscale 64-bit horizontal gradient dHash."""
    if not path.is_file():
        return None
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if sample_t is not None and sample_t > 0:
        cmd += ["-ss", f"{sample_t:.2f}"]
    cmd += [
        "-i",
        str(path),
        "-vf",
        "crop=iw*0.72:ih*0.72,scale=9:8:flags=area,format=gray",
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-",
    ]
    proc = run_cmd_bytes(cmd)
    if proc.returncode != 0 or len(proc.stdout) < 72:
        return None
    buf = proc.stdout[:72]
    val = 0
    bit_idx = 0
    for r in range(8):
        row_off = r * 9
        for c in range(8):
            if buf[row_off + c] > buf[row_off + c + 1]:
                val |= 1 << bit_idx
            bit_idx += 1
    return val


def hamming_dist(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def measure_broll_stability(
    src_file: Path,
    t_in: float = 0.0,
    dur: float = 4.0,
    box_w: float = 1080.0,
    box_h: float = 1920.0,
) -> dict[str, Any]:
    """Measure inter-frame high-frequency shake & oscillation via FFmpeg vidstabdetect ASCII vectors."""
    out: dict[str, Any] = {
        "hf_jerk_px": 0.0,
        "reversals_per_sec": 0.0,
        "mean_speed_px": 0.0,
        "osc_span_px": 0.0,
        "stage_mag": 1.69,
        "stability_tier": "A_stable",
    }
    if not src_file.is_file() or dur <= 0.25:
        return out

    src_w, src_h, fps = 1920.0, 1080.0, 30.0
    try:
        pinfo = ffprobe_json(src_file)
        vs = next((s for s in pinfo.get("streams", []) if s.get("codec_type") == "video"), None)
        if vs:
            src_w = float(vs.get("width") or 1920.0)
            src_h = float(vs.get("height") or 1080.0)
            rfr = str(vs.get("r_frame_rate") or "30/1")
            if "/" in rfr:
                num_s, den_s = rfr.split("/", 1)
                if float(den_s) > 0:
                    fps = max(10.0, min(120.0, float(num_s) / float(den_s)))
            elif float(rfr) > 0:
                fps = float(rfr)
    except Exception:
        pass

    proxy_w = 640.0
    proxy_h = max(2.0, round((src_h * proxy_w / max(1.0, src_w)) / 2.0) * 2.0)
    stage_mag = max(box_w / proxy_w, box_h / proxy_h)
    out["stage_mag"] = round(stage_mag, 2)

    eval_dur = min(max(0.3, dur), 4.0)
    lm_re = re.compile(
        r"\(\s*LM\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+\d+\s+\d+\s+\d+\s+(\d+(?:\.\d+)?)"
    )

    def _trimmed_mean(vals: list[float]) -> float:
        if not vals:
            return 0.0
        sv = sorted(vals)
        k = int(len(sv) * 0.2)
        core = sv[k : len(sv) - k] if (len(sv) - 2 * k) >= 1 else sv
        return sum(core) / len(core)

    frame_vecs: list[tuple[float, float]] = []
    with tempfile.TemporaryDirectory(prefix="svp_vsd_") as tmpdir:
        trf_path = Path(tmpdir) / "transforms.trf"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, t_in):.3f}",
            "-t",
            f"{eval_dur:.3f}",
            "-i",
            str(src_file.resolve()),
            "-vf",
            "scale=640:-2,vidstabdetect=shakiness=7:accuracy=15:fileformat=ascii:result=transforms.trf",
            "-an",
            "-f",
            "null",
            "-",
        ]
        subprocess.run(
            cmd,
            cwd=tmpdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if not trf_path.is_file():
            return out
        for line in trf_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith("Frame "):
                continue
            hi_x: list[float] = []
            hi_y: list[float] = []
            all_x: list[float] = []
            all_y: list[float] = []
            for m in lm_re.finditer(line):
                dx_v = float(m.group(1))
                dy_v = float(m.group(2))
                ct_v = float(m.group(3))
                all_x.append(dx_v)
                all_y.append(dy_v)
                if ct_v >= 0.35:
                    hi_x.append(dx_v)
                    hi_y.append(dy_v)
            use_x = hi_x if len(hi_x) >= 3 else all_x
            use_y = hi_y if len(hi_y) >= 3 else all_y
            frame_vecs.append((_trimmed_mean(use_x) * stage_mag, _trimmed_mean(use_y) * stage_mag))

    # Drop frame 1 (vidstab reference frame with empty motion list)
    if len(frame_vecs) > 1:
        frame_vecs = frame_vecs[1:]
    if len(frame_vecs) < 4:
        return out

    speeds = [math.hypot(vx, vy) for vx, vy in frame_vecs]
    jerks = [
        math.hypot(frame_vecs[i][0] - frame_vecs[i - 1][0], frame_vecs[i][1] - frame_vecs[i - 1][1])
        for i in range(1, len(frame_vecs))
    ]

    def _count_reversals(seq: list[float], deadzone: float = 0.45) -> int:
        signs = [1 if v >= deadzone else (-1 if v <= -deadzone else 0) for v in seq]
        nz = [s for s in signs if s != 0]
        return sum(1 for a, b in zip(nz, nz[1:]) if a != b)

    rev_cnt = max(
        _count_reversals([v[0] for v in frame_vecs]),
        _count_reversals([v[1] for v in frame_vecs]),
    )
    analyzed_sec = max(0.35, len(frame_vecs) / fps)
    rev_per_sec = rev_cnt / analyzed_sec
    hf_jerk = sum(jerks) / len(jerks)
    mean_spd = sum(speeds) / len(speeds)

    # Detrended cumulative oscillation span
    n_f = len(frame_vecs)
    tot_x = sum(v[0] for v in frame_vecs)
    tot_y = sum(v[1] for v in frame_vecs)
    cx_list: list[float] = []
    cy_list: list[float] = []
    acc_x = 0.0
    acc_y = 0.0
    for idx, (vx, vy) in enumerate(frame_vecs, 1):
        acc_x += vx
        acc_y += vy
        cx_list.append(acc_x - tot_x * (idx / n_f))
        cy_list.append(acc_y - tot_y * (idx / n_f))
    osc_span = max(max(cx_list) - min(cx_list), max(cy_list) - min(cy_list))

    if hf_jerk > 2.40 or rev_per_sec > 2.50:
        tier = "C_severe_jitter"
    elif hf_jerk > 1.25 or rev_per_sec > 1.25:
        tier = "B_mild_shake"
    else:
        tier = "A_stable"

    out.update(
        {
            "hf_jerk_px": round(hf_jerk, 2),
            "reversals_per_sec": round(rev_per_sec, 2),
            "mean_speed_px": round(mean_spd, 2),
            "osc_span_px": round(osc_span, 2),
            "stability_tier": tier,
        }
    )
    return out


def inspect_video_broll_segment(
    src_file: Path,
    t_in: float,
    dur: float,
    box_w: float = 1080.0,
    box_h: float = 1920.0,
) -> dict[str, Any]:
    """Check a video B-roll segment for dark leader (YAVG < 18), internal cuts (scdet >= 16), and high-frequency shake."""
    res: dict[str, Any] = {
        "yavg_min": None,
        "dark_consecutive": 0,
        "dark_ratio": 0.0,
        "max_scdet_score": 0.0,
        "scdet_times": [],
    }
    if not src_file.is_file() or dur <= 0.15:
        return res
    cmd_y = [
        "ffmpeg",
        "-hide_banner",
        "-ss",
        f"{max(0.0, t_in):.3f}",
        "-t",
        f"{dur:.3f}",
        "-i",
        str(src_file),
        "-vf",
        "fps=4,scale=160:-2,signalstats,metadata=mode=print:file=-",
        "-an",
        "-f",
        "null",
        "-",
    ]
    py = run_cmd(cmd_y)
    combined_y = py.stdout + "\n" + py.stderr
    yavgs = [float(x) for x in re.findall(r"lavfi\.signalstats\.YAVG=(\d+(?:\.\d+)?)", combined_y)]
    if yavgs:
        res["yavg_min"] = round(min(yavgs), 2)
        dark_cnt = sum(1 for v in yavgs if v < 18.0)
        res["dark_ratio"] = round(dark_cnt / len(yavgs), 3)
        cur_run = 0
        max_run = 0
        for v in yavgs:
            if v < 18.0:
                cur_run += 1
                max_run = max(max_run, cur_run)
            else:
                cur_run = 0
        res["dark_consecutive"] = max_run

    if dur >= 0.85:
        inner_ss = max(0.0, t_in + 0.12)
        inner_dur = max(0.2, dur - 0.24)
        cmd_sc = [
            "ffmpeg",
            "-hide_banner",
            "-ss",
            f"{inner_ss:.3f}",
            "-t",
            f"{inner_dur:.3f}",
            "-i",
            str(src_file),
            "-vf",
            "scale=320:-2,scdet=threshold=14",
            "-an",
            "-f",
            "null",
            "-",
        ]
        psc = run_cmd(cmd_sc)
        combined_sc = psc.stdout + "\n" + psc.stderr
        scores: list[float] = []
        times: list[float] = []
        for sm in re.finditer(
            r"lavfi\.scd\.score\s*[:=]\s*(\d+(?:\.\d+)?)(?:.*?lavfi\.scd\.time\s*[:=]\s*(\d+(?:\.\d+)?))?",
            combined_sc,
        ):
            sc_v = float(sm.group(1))
            scores.append(sc_v)
            if sc_v >= 16.0 and sm.group(2):
                times.append(round(inner_ss + float(sm.group(2)), 2))
        if scores:
            res["max_scdet_score"] = round(max(scores), 2)
            res["scdet_times"] = times

    res.update(measure_broll_stability(src_file, t_in, dur, box_w=box_w, box_h=box_h))
    return res


def cmd_stabilize_broll(args: argparse.Namespace) -> int:
    in_path = Path(args.input)
    out_path = Path(args.out)
    if not in_path.is_file():
        print(f"error: input B-roll video not found: {in_path}", file=sys.stderr)
        return 1

    before = measure_broll_stability(
        in_path, t_in=args.ss, dur=args.dur or 5.0, box_w=args.box_w, box_h=args.box_h
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="svp_stab_") as tmpdir:
        ss_args = ["-ss", f"{args.ss:.3f}"] if args.ss > 0 else []
        dur_args = ["-t", f"{args.dur:.3f}"] if args.dur and args.dur > 0 else []
        det_opts = "shakiness=8:accuracy=15:result=transforms.trf" + (":tripod=1" if args.tripod else "")
        p1 = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                *ss_args,
                *dur_args,
                "-i",
                str(in_path.resolve()),
                "-vf",
                f"vidstabdetect={det_opts}",
                "-an",
                "-f",
                "null",
                "-",
            ],
            cwd=tmpdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if p1.returncode != 0 or not (Path(tmpdir) / "transforms.trf").is_file():
            print(f"error: vidstabdetect failed: {p1.stderr.strip()}", file=sys.stderr)
            return 2

        smooth_v = 0 if args.tripod else max(4, args.smoothing)
        tr_opts = (
            f"input=transforms.trf:smoothing={smooth_v}:optzoom=1:zoom=2.5:interpol=bicubic"
            + (":tripod=1" if args.tripod else "")
        )
        p2 = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                *ss_args,
                *dur_args,
                "-i",
                str(in_path.resolve()),
                "-vf",
                f"vidstabtransform={tr_opts},unsharp=5:5:0.4:3:3:0.0",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "17",
                "-g",
                "8",
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(out_path.resolve()),
            ],
            cwd=tmpdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if p2.returncode != 0 or not out_path.is_file():
            print(f"error: vidstabtransform failed: {p2.stderr.strip()}", file=sys.stderr)
            return 2

    after = measure_broll_stability(
        out_path, t_in=0.0, dur=args.dur or 5.0, box_w=args.box_w, box_h=args.box_h
    )
    still_severe = after["stability_tier"] == "C_severe_jitter"
    if still_severe and not args.keep_failed:
        out_path.unlink(missing_ok=True)

    report = {
        "status": "rejected_still_jittery" if still_severe else "ok",
        "input": rel_path(in_path),
        "output": None if (still_severe and not args.keep_failed) else rel_path(out_path),
        "before": before,
        "after": after,
        "passed": not still_severe,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if still_severe:
        print(
            "error: clip remains Tier C jittery after 2D stabilization (perspective warp / timelapse oscillation); discard and replace with a clean Pixabay tripod/gimbal clip.",
            file=sys.stderr,
        )
        return 2
    return 0


# ---------------------------------------------------------------------------
# Audio Subcommands: probe-audio / prepare-voice / normalize-sfx / build-bgm-bed
# ---------------------------------------------------------------------------


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
                    f"前6秒均值({first6['mean_volume_db']} dB)比全曲均值({stats['mean_volume_db']} dB)低>=10dB，严禁直接从#t=0起铺，建议跳过前奏或交由 build-bgm-bed 自动切入"
                )
            if stats["lra_lu"] is not None and stats["lra_lu"] > 11.5:
                warnings.append(
                    f"动态范围LRA={stats['lra_lu']} LU过高(>11.5 LU)，严禁裸铺，须经 build-bgm-bed 自动预压缩与侧链闪避处理"
                )
            rec["bgm_volume_under_voice_target_minus29lufs"] = recommend_gain(
                stats["integrated_lufs"], -29.0
            )
            rec["bgm_volume_hook_or_outro_target_minus24lufs"] = recommend_gain(
                stats["integrated_lufs"], -24.0
            )
        else:
            peak_ms = find_sfx_peak_offset_ms(f)
            stats["peak_offset_ms"] = peak_ms
            if stats["true_peak_dbtp"] is not None and stats["true_peak_dbtp"] < -30.0:
                warnings.append(
                    f"损坏/静音废件告警：真峰值仅 {stats['true_peak_dbtp']} dBTP (< -30 dBTP)，严禁入片！"
                )
            if stats["true_peak_dbtp"] is not None and stats["true_peak_dbtp"] >= -0.5:
                warnings.append(
                    f"原生峰值极热/削波({stats['true_peak_dbtp']} dBTP)，请运行 normalize-sfx 统一归一化至 -3.0 dBTP"
                )
            if peak_ms is not None and peak_ms > 500:
                warnings.append(
                    f"峰值延后至{peak_ms}ms(>500ms)，属慢爬坡音效(Riser)，须按峰值提前触发而非卡切镜点"
                )
            rec["sfx_after_normalize_foley"] = 0.18
            rec["sfx_after_normalize_transition"] = 0.28
            rec["sfx_after_normalize_impact"] = 0.38

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


def _parse_srt_segments(raw_srt: str) -> list[dict[str, Any]]:
    segs: list[dict[str, Any]] = []
    blocks = re.split(r"\r?\n\r?\n+", raw_srt.strip())
    ts_re = re.compile(
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
    )
    for blk in blocks:
        lines = [ln.strip() for ln in blk.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        m = ts_re.search(lines[0]) or (ts_re.search(lines[1]) if len(lines) >= 2 else None)
        if not m:
            continue
        txt_idx = 1 if ts_re.search(lines[0]) else 2
        txt = " ".join(lines[txt_idx:]).strip()
        s_sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000.0
        e_sec = int(m.group(5)) * 3600 + int(m.group(6)) * 60 + int(m.group(7)) + int(m.group(8)) / 1000.0
        if e_sec > s_sec and txt:
            segs.append({"start": round(s_sec, 3), "end": round(e_sec, 3), "text": txt})
    return segs


def cmd_scan_compliance(args: argparse.Namespace) -> int:
    in_p = Path(args.transcript)
    if not in_p.is_file():
        print(f"error: transcript file not found: {in_p}", file=sys.stderr)
        return 1
    raw = in_p.read_text(encoding="utf-8", errors="replace")
    segments: list[dict[str, Any]] = []
    if in_p.suffix.lower() == ".srt":
        segments = _parse_srt_segments(raw)
    else:
        data = json.loads(raw)
        raw_segs = (
            data.get("segments")
            if isinstance(data, dict) and isinstance(data.get("segments"), list)
            else (data if isinstance(data, list) else [])
        )
        for item in raw_segs:
            if isinstance(item, dict):
                segments.append(
                    {
                        "start": float(item.get("start") or 0.0),
                        "end": float(item.get("end") or 0.0),
                        "text": str(item.get("text") or ""),
                        "words": item.get("words") if isinstance(item.get("words"), list) else None,
                    }
                )
            elif isinstance(item, list) and len(item) >= 3:
                segments.append({"start": float(item[0]), "end": float(item[1]), "text": strip_html(str(item[2]))})

    bleeps: list[dict[str, Any]] = []
    masked_segments: list[dict[str, Any]] = []
    for seg in segments:
        txt = seg.get("text") or ""
        s_t = float(seg.get("start") or 0.0)
        e_t = max(s_t + 0.05, float(seg.get("end") or (s_t + 0.5)))
        hits = find_policy_sensitive_hits(txt)
        words = seg.get("words") or []
        # Build char-to-time map from word timestamps if available
        char_times: list[tuple[float, float]] = []
        if words:
            for w in words:
                wt = str(w.get("word") or "")
                ws = float(w.get("start") or s_t)
                we = max(ws + 0.04, float(w.get("end") or e_t))
                wlen = max(1, len(wt))
                for k in range(len(wt)):
                    c0 = ws + (we - ws) * (k / wlen)
                    c1 = ws + (we - ws) * ((k + 1) / wlen)
                    char_times.append((c0, c1))

        n_chars = max(1, len(txt))
        for h in hits:
            cs, ce = h["char_start"], h["char_end"]
            if len(char_times) == len(txt) and ce <= len(char_times):
                b0 = char_times[cs][0] - 0.02
                b1 = char_times[ce - 1][1] + 0.02
            else:
                b0 = s_t + (e_t - s_t) * (cs / n_chars) - 0.03
                b1 = s_t + (e_t - s_t) * (ce / n_chars) + 0.03
            b0 = max(0.0, round(b0, 3))
            b1 = round(max(b0 + 0.18, b1), 3)
            bleeps.append(
                {
                    "start": b0,
                    "end": b1,
                    "raw_word": h["raw_word"],
                    "masked_text": h["masked_text"],
                    "category": h["category"],
                    "segment_text": txt,
                }
            )
        masked_segments.append(
            {
                "start": round(s_t, 3),
                "end": round(e_t, 3),
                "raw_text": txt,
                "masked_text": mask_policy_sensitive_text(txt),
            }
        )

    out_obj = {
        "source_transcript": rel_path(in_p),
        "hit_count": len(bleeps),
        "bleeps": bleeps,
        "masked_segments": masked_segments,
    }
    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(out_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out_obj, ensure_ascii=False, indent=2))
    return 0


def cmd_prepare_voice(args: argparse.Namespace) -> int:
    in_path = Path(args.input)
    out_path = Path(args.out)
    if not in_path.is_file():
        print(f"error: input file not found: {in_path}", file=sys.stderr)
        return 1

    bleep_windows: list[tuple[float, float, str, str]] = []
    if getattr(args, "bleeps", None):
        bp = Path(args.bleeps)
        if not bp.is_file():
            print(f"error: bleeps JSON not found: {bp}", file=sys.stderr)
            return 1
        bdata = json.loads(bp.read_text(encoding="utf-8"))
        raw_list = bdata.get("bleeps") if isinstance(bdata, dict) else bdata
        for item in raw_list or []:
            b0 = max(0.0, float(item.get("start") or 0.0))
            b1 = float(item.get("end") or 0.0)
            if b1 > b0:
                bleep_windows.append(
                    (round(b0, 3), round(b1, 3), str(item.get("raw_word") or ""), str(item.get("masked_text") or "**"))
                )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    in_info = ffprobe_json(in_path)
    dur_in = float(in_info.get("format", {}).get("duration", 0) or 0)
    before_stats = analyze_audio_segment(in_path)

    af_chain = f"aresample={args.sr}:async=1:first_pts=0,{VOICE_CONDITIONING_AF}"
    meta_comment = f"svp_voice_treated;bleeps={len(bleep_windows)}"
    if not bleep_windows:
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(in_path),
            "-vn",
            "-af",
            af_chain,
            "-c:a",
            "aac",
            "-b:a",
            args.bitrate,
            "-ar",
            str(args.sr),
            "-metadata",
            f"comment={meta_comment}",
            str(out_path),
        ]
    else:
        vo_mute_parts = [af_chain]
        beep_gate_terms: list[str] = []
        for b0, b1, _, _ in bleep_windows:
            vo_mute_parts.append(f"volume=0:enable='between(t,{b0:.3f},{b1:.3f})'")
            ramp = min(0.015, max(0.005, (b1 - b0) * 0.15))
            beep_gate_terms.append(
                f"if(between(t,{b0:.3f},{b1:.3f}),min(1,min((t-{b0:.3f})/{ramp:.3f},({b1:.3f}-t)/{ramp:.3f})),0)"
            )
        beep_expr = f"min(1,{'+'.join(beep_gate_terms)})"
        fc = (
            f"[0:a]{','.join(vo_mute_parts)},aformat=sample_fmts=fltp:sample_rates={args.sr}:channel_layouts=stereo[vo_m];"
            f"sine=frequency={args.bleep_freq}:sample_rate={args.sr}:duration={max(0.5, dur_in):.4f},"
            f"volume={args.bleep_db:+.1f}dB,volume='{beep_expr}':eval=frame,"
            f"aformat=sample_fmts=fltp:sample_rates={args.sr}:channel_layouts=stereo[bp];"
            f"[vo_m][bp]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[outa]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(in_path),
            "-vn",
            "-filter_complex",
            fc,
            "-map",
            "[outa]",
            "-c:a",
            "aac",
            "-b:a",
            args.bitrate,
            "-ar",
            str(args.sr),
            "-metadata",
            f"comment={meta_comment}",
            str(out_path),
        ]
    proc = run_cmd(cmd)
    if proc.returncode != 0 or not out_path.is_file():
        print(f"error: prepare-voice ffmpeg failed: {proc.stderr.strip()}", file=sys.stderr)
        return 2

    out_info = ffprobe_json(out_path)
    dur_out = float(out_info.get("format", {}).get("duration", 0) or 0)
    drift = abs(dur_out - dur_in)
    if drift > 0.08:
        print(
            f"error: duration drift {drift:.4f}s exceeds 0.08s safety bound ({dur_in:.3f}s -> {dur_out:.3f}s)",
            file=sys.stderr,
        )
        return 2

    after_stats = analyze_audio_segment(out_path)
    report = {
        "status": "ok",
        "input": rel_path(in_path),
        "output": rel_path(out_path),
        "duration_in_sec": round(dur_in, 4),
        "duration_out_sec": round(dur_out, 4),
        "drift_sec": round(drift, 4),
        "bleeps_applied": [
            {"start": b0, "end": b1, "raw_word": rw, "masked_text": mt}
            for b0, b1, rw, mt in bleep_windows
        ],
        "before": before_stats,
        "after": after_stats,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _audio_codec_args_for_ext(ext: str) -> list[str]:
    e = ext.lower()
    if e == ".mp3":
        return ["-c:a", "libmp3lame", "-q:a", "2"]
    if e == ".wav":
        return ["-c:a", "pcm_s16le"]
    if e in {".ogg", ".opus"}:
        return ["-c:a", "libopus", "-b:a", "128k"]
    if e == ".flac":
        return ["-c:a", "flac"]
    return ["-c:a", "aac", "-b:a", "192k"]


def cmd_normalize_sfx(args: argparse.Namespace) -> int:
    candidates: list[Path] = []
    skip_re = re.compile(r"(?:voice-treated|vocals|bgm|music|bed|master-voice)", re.IGNORECASE)
    for raw in args.targets:
        p = Path(raw)
        if p.is_dir():
            for f in sorted(p.iterdir()):
                if f.is_file() and f.suffix.lower() in AUDIO_EXTS and not skip_re.search(f.stem):
                    candidates.append(f)
        elif p.is_file():
            candidates.append(p)
        else:
            print(f"[warn] not found: {raw}", file=sys.stderr)

    foley_name_re = re.compile(r"(?:paper|pen|pencil|tick|click|shutter|type|foley|page)", re.IGNORECASE)
    processed: list[dict[str, Any]] = []
    broken_files: list[str] = []

    for f in candidates:
        info = ffprobe_json(f)
        dur = float(info.get("format", {}).get("duration", 0) or 0)
        if dur <= 0.0 or dur > args.max_dur:
            continue
        before = analyze_audio_segment(f)
        tp = before["true_peak_dbtp"]
        lufs = before["integrated_lufs"]
        max_v = before.get("max_volume_db")
        # Note: EBU R128 uses a 400ms gating window, so <0.4s crisp SFX report I=-70 LUFS; rely on true_peak/max_volume for short clips.
        if (
            tp is None
            or tp < -35.0
            or (max_v is not None and max_v < -35.0)
            or (dur >= 0.8 and lufs is not None and lufs < -50.0)
        ):
            broken_files.append(f"{rel_path(f)} (TP={tp} dBTP, max={max_v} dB, I={lufs} LUFS)")
            continue

        apply_dip = bool(args.foley_dip or foley_name_re.search(f.stem))
        gain_db = args.target_dbtp - tp
        if abs(gain_db) <= 0.35 and not apply_dip:
            processed.append(
                {
                    "file": rel_path(f),
                    "action": "already_normalized",
                    "before_dbtp": tp,
                    "after_dbtp": tp,
                }
            )
            continue

        filters: list[str] = []
        if apply_dip:
            filters.append("equalizer=f=2500:t=q:w=1.2:g=-2.5")
        filters.append(f"volume={gain_db:+.2f}dB")
        limit_lin = round(min(0.95, 10 ** ((args.target_dbtp + 0.15) / 20.0)), 4)
        filters.append(f"alimiter=limit={limit_lin}:attack=1:release=20:level=disabled")

        tmp_out = f.with_name(f"{f.stem}.__norm_tmp__{f.suffix}")
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(f),
            "-vn",
            "-af",
            ",".join(filters),
            *_audio_codec_args_for_ext(f.suffix),
            str(tmp_out),
        ]
        proc = run_cmd(cmd)
        if proc.returncode != 0 or not tmp_out.is_file():
            if tmp_out.exists():
                tmp_out.unlink(missing_ok=True)
            print(f"error: normalize-sfx failed on {f}: {proc.stderr.strip()}", file=sys.stderr)
            return 2
        os.replace(tmp_out, f)
        after = analyze_audio_segment(f)
        processed.append(
            {
                "file": rel_path(f),
                "action": "normalized_with_foley_dip" if apply_dip else "normalized",
                "gain_applied_db": round(gain_db, 2),
                "before_dbtp": tp,
                "after_dbtp": after["true_peak_dbtp"],
                "after_lufs": after["integrated_lufs"],
            }
        )

    out_obj = {
        "normalized_count": len(processed),
        "target_dbtp": args.target_dbtp,
        "items": processed,
        "broken_silent_sfx": broken_files,
    }
    print(json.dumps(out_obj, ensure_ascii=False, indent=2))
    if broken_files:
        return 2
    return 0


def parse_audio_tags_in_section(section_html: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for m in re.finditer(r"<audio\b([^>]*)>", section_html, flags=re.IGNORECASE):
        attrs = m.group(1)
        src_m = re.search(r'src=["\']([^"\']+)["\']', attrs)
        if not src_m:
            continue
        raw_src = src_m.group(1)
        base_src = raw_src.split("#", 1)[0]
        at_m = re.search(r'\bat=["\'](\d+(?:\.\d+)?)["\']', attrs)
        dur_m = re.search(r'\bdur=["\'](\d+(?:\.\d+)?)["\']', attrs)
        vol_m = re.search(r'\bvolume=["\'](\d+(?:\.\d+)?)["\']', attrs)
        fade_m = re.search(r'\bfade=["\']([^"\']+)["\']', attrs)
        has_override_fade = bool(re.search(r'"fade"\s*:', attrs, flags=re.IGNORECASE))
        id_m = re.search(r'\bid=["\']([^"\']+)["\']', attrs)
        at_val = float(at_m.group(1)) if at_m else 0.0
        vol_val = float(vol_m.group(1)) if vol_m else 1.0
        t_in: float | None = None
        t_out: float | None = None
        tm = re.search(r"#t=(\d+(?:\.\d+)?)(?:,(\d+(?:\.\d+)?))?", raw_src)
        if tm:
            t_in = float(tm.group(1))
            t_out = float(tm.group(2)) if tm.group(2) else None
        dur_val = (
            (t_out - t_in)
            if (t_in is not None and t_out is not None)
            else (float(dur_m.group(1)) if dur_m else None)
        )
        items.append(
            {
                "id": id_m.group(1) if id_m else Path(base_src).stem,
                "base_src": base_src,
                "at": at_val,
                "t_in": t_in or 0.0,
                "t_out": t_out,
                "dur": dur_val,
                "volume": vol_val,
                "fade": fade_m.group(1) if fade_m else ("overrides_fade" if has_override_fade else None),
            }
        )
    return items


def _parse_drops_spec(spec: str | None) -> list[tuple[float, float]]:
    drops: list[tuple[float, float]] = []
    if not spec:
        return drops
    for part in re.split(r"[,;\s]+", spec.strip()):
        if not part:
            continue
        m = re.match(r"^(\d+(?:\.\d+)?)\s*[:\-]\s*(\d+(?:\.\d+)?)$", part)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            if b > a:
                drops.append((round(a, 3), round(b, 3)))
    return drops


def cmd_build_bgm_bed(args: argparse.Namespace) -> int:
    film_dir = Path(args.film_dir)
    bgm_path = Path(args.bgm)
    out_path = Path(args.out)
    film_html = film_dir / "film.html"
    if not film_html.is_file():
        print(f"error: film.html not found in {film_dir}", file=sys.stderr)
        return 1
    if not bgm_path.is_file():
        print(f"error: bgm file not found: {bgm_path}", file=sys.stderr)
        return 1

    html_txt = film_html.read_text(encoding="utf-8", errors="replace")
    # Infer timeline duration if not provided
    total_dur = float(args.duration) if args.duration else 0.0
    voice_slices: list[tuple[float, Path, float, float]] = []

    vt_sec = re.search(
        r'<section[^>]*id=["\']voice-track["\'][^>]*>(.*?)</section>',
        html_txt,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if vt_sec:
        for ac in parse_audio_tags_in_section(vt_sec.group(1)):
            if ac["volume"] <= 0.01:
                continue
            src_f = film_dir / ac["base_src"]
            if not src_f.is_file():
                continue
            c_dur = ac["dur"]
            if c_dur is None:
                c_dur = max(0.0, float(ffprobe_json(src_f).get("format", {}).get("duration", 0) or 0) - ac["t_in"])
            voice_slices.append((ac["at"], src_f, ac["t_in"], c_dur))
            total_dur = max(total_dur, ac["at"] + c_dur)

    # Also scan visual sections for total_dur (and fallback voice if no voice-track)
    for sec_m in re.finditer(r"<section\b([^>]*)>(.*?)</section>", html_txt, flags=re.IGNORECASE | re.DOTALL):
        s_attrs, s_body = sec_m.group(1), sec_m.group(2)
        for vc in parse_clips_in_section(s_body):
            if vc["end"] is not None:
                total_dur = max(total_dur, vc["end"])
            if not voice_slices and vc["tag"] == "video":
                # Check if video is not muted
                raw_tag_m = re.search(
                    rf'<video\b[^>]*src=["\']{re.escape(vc["base_src"])}[^"\']*["\'][^>]*>',
                    s_body,
                    flags=re.IGNORECASE,
                )
                vol_zero = bool(
                    raw_tag_m and re.search(r'\bvolume=["\']0(?:\.0+)?["\']', raw_tag_m.group(0))
                )
                if not vol_zero:
                    src_f = film_dir / vc["base_src"]
                    if src_f.is_file():
                        c_dur = vc["dur"]
                        t_in = vc["t_in"] or 0.0
                        if c_dur is None:
                            c_dur = max(
                                0.0,
                                float(ffprobe_json(src_f).get("format", {}).get("duration", 0) or 0) - t_in,
                            )
                        voice_slices.append((vc["at"], src_f, t_in, c_dur))
                        total_dur = max(total_dur, vc["at"] + c_dur)

    if total_dur <= 0.5:
        print("error: could not infer positive timeline duration from film.html; pass --duration", file=sys.stderr)
        return 1

    # Collect Silence Drop windows from CLI or data-drops attribute in film.html
    drops = _parse_drops_spec(args.drops)
    if not drops:
        dm = re.search(r'data-drops=["\']([^"\']+)["\']', html_txt, flags=re.IGNORECASE)
        if dm:
            drops = _parse_drops_spec(dm.group(1))

    # Probe BGM
    bgm_info = ffprobe_json(bgm_path)
    bgm_dur = float(bgm_info.get("format", {}).get("duration", 0) or 0)
    bgm_stats = analyze_audio_segment(bgm_path)
    first6 = analyze_audio_segment(bgm_path, ss=0.0, dur=min(6.0, bgm_dur))
    bgm_offset = float(args.bgm_offset) if args.bgm_offset is not None else 0.0
    if (
        args.bgm_offset is None
        and bgm_dur > 14.0
        and bgm_stats["mean_volume_db"] is not None
        and first6["mean_volume_db"] is not None
        and (bgm_stats["mean_volume_db"] - first6["mean_volume_db"]) >= 9.0
    ):
        bgm_offset = 6.0

    raw_lufs = bgm_stats["integrated_lufs"] if bgm_stats["integrated_lufs"] is not None else -20.0
    raw_lra = bgm_stats["lra_lu"] or 5.0
    pre_compress = raw_lra > 9.0

    # Target open (non-ducked) BGM level = under_lufs + swell_db (sidechain ducks ~5dB under voice)
    open_target_lufs = args.under_lufs + args.swell_db
    base_gain_db = round(max(-30.0, min(12.0, open_target_lufs - raw_lufs - (2.0 if pre_compress else 0.0))), 2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    guide_wav = out_path.with_name(f"{out_path.stem}.__vo_guide__.wav")

    try:
        sr_guide = 16000
        total_samples = max(1, int(round(total_dur * sr_guide)))
        pcm_buf = bytearray(total_samples * 2)
        decoded_cache: dict[Path, bytes] = {}
        for at_s, src_f, t_in_s, dur_s in voice_slices:
            if src_f not in decoded_cache:
                p_dec = run_cmd_bytes(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        str(src_f),
                        "-vn",
                        "-ac",
                        "1",
                        "-ar",
                        str(sr_guide),
                        "-f",
                        "s16le",
                        "-",
                    ]
                )
                decoded_cache[src_f] = p_dec.stdout if p_dec.returncode == 0 else b""
            raw_pcm = decoded_cache[src_f]
            if not raw_pcm:
                continue
            s_start = max(0, int(round(t_in_s * sr_guide))) * 2
            s_len = max(0, int(round(dur_s * sr_guide))) * 2
            chunk = raw_pcm[s_start : s_start + s_len]
            dst_start = max(0, int(round(at_s * sr_guide))) * 2
            avail = min(len(chunk), len(pcm_buf) - dst_start)
            if avail > 0:
                pcm_buf[dst_start : dst_start + avail] = chunk[:avail]

        with wave.open(str(guide_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr_guide)
            wf.writeframes(bytes(pcm_buf))

        bgm_chain: list[str] = [f"atrim=0:{total_dur:.3f}", "asetpts=PTS-STARTPTS"]
        if pre_compress:
            bgm_chain.append("acompressor=threshold=-22dB:ratio=2.5:attack=15:release=250:makeup=2dB")
        bgm_chain.append(f"volume={base_gain_db:+.2f}dB")
        bgm_chain.append("afade=t=in:st=0:d=0.25")
        outro_st = max(0.0, total_dur - 1.15)
        bgm_chain.append(f"afade=t=out:st={outro_st:.3f}:d={min(1.15, total_dur):.3f}")

        for d0, d1 in drops:
            r0 = max(0.0, d0 - 0.07)
            r1 = min(total_dur, d1 + 0.09)
            expr = (
                f"if(between(t,{r0:.3f},{d0:.3f}),({d0:.3f}-t)/{max(0.01, d0-r0):.3f},"
                f"if(between(t,{d0:.3f},{d1:.3f}),0,"
                f"if(between(t,{d1:.3f},{r1:.3f}),(t-{d1:.3f})/{max(0.01, r1-d1):.3f},1)))"
            )
            bgm_chain.append(f"volume='{expr}':eval=frame")

        bgm_chain.append("aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo")
        vo_chain = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"

        if voice_slices:
            fc = (
                f"[0:a]{','.join(bgm_chain)}[bgm_pre];"
                f"[1:a]{vo_chain}[vo_sc];"
                f"[bgm_pre][vo_sc]sidechaincompress=threshold=0.022:ratio=4.5:attack=18:release=380:makeup=1[outa]"
            )
        else:
            fc = f"[0:a]{','.join(bgm_chain)}[outa]"

        drops_tag = ",".join(f"{a}-{b}" for a, b in drops) if drops else "none"
        meta_comment = f"svp_bgm_bed:ducked;drops={drops_tag};precomp={int(pre_compress)}"
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-stream_loop",
            "-1",
            "-ss",
            f"{bgm_offset:.3f}",
            "-i",
            str(bgm_path),
            "-i",
            str(guide_wav),
            "-filter_complex",
            fc,
            "-map",
            "[outa]",
            "-t",
            f"{total_dur:.3f}",
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            "-ar",
            "48000",
            "-metadata",
            f"comment={meta_comment}",
            str(out_path),
        ]
        proc = run_cmd(cmd)
        if proc.returncode != 0 or not out_path.is_file():
            print(f"error: build-bgm-bed ffmpeg failed: {proc.stderr.strip()}", file=sys.stderr)
            return 2
    finally:
        if guide_wav.exists():
            guide_wav.unlink(missing_ok=True)

    bed_stats = analyze_audio_segment(out_path)
    print(
        json.dumps(
            {
                "status": "ok",
                "bgm_source": rel_path(bgm_path),
                "bgm_bed": rel_path(out_path),
                "duration_sec": round(total_dur, 3),
                "auto_bgm_offset_sec": round(bgm_offset, 2),
                "pre_compressed_high_lra": pre_compress,
                "voice_segments_used": len(voice_slices),
                "silence_drops": drops,
                "metrics": bed_stats,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


# ---------------------------------------------------------------------------
# HTML / CSS / Scene Parsing Helpers
# ---------------------------------------------------------------------------


def parse_clips_in_section(section_html: str) -> list[dict[str, Any]]:
    clips: list[dict[str, Any]] = []
    for m in re.finditer(r"<(video|iframe|img)\b([^>]*)>", section_html, flags=re.IGNORECASE):
        tag = m.group(1).lower()
        attrs = m.group(2)
        src_m = re.search(r'src=["\']([^"\']+)["\']', attrs)
        at_m = re.search(r'\bat=["\'](\d+(?:\.\d+)?)["\']', attrs)
        dur_m = re.search(r'\bdur=["\'](\d+(?:\.\d+)?)["\']', attrs)
        spd_m = re.search(r'\bspeed=["\'](\d+(?:\.\d+)?)["\']', attrs)
        id_m = re.search(r'\bid=["\']([^"\']+)["\']', attrs)
        cls_m = re.search(r'\bclass=["\']([^"\']+)["\']', attrs)
        style_m = re.search(r'style=["\']([^"\']+)["\']', attrs)
        ovr_m = re.search(r"\boverrides=(['\"])([\s\S]*?)\1", attrs)
        if not src_m:
            continue
        raw_src = src_m.group(1)
        base_src = raw_src.split("#", 1)[0]
        at_val = round(float(at_m.group(1)), 3) if at_m else 0.0
        speed_val = max(0.05, float(spd_m.group(1))) if spd_m else 1.0
        t_in: float | None = None
        t_out: float | None = None
        tm = re.search(r"#t=(\d+(?:\.\d+)?)(?:,(\d+(?:\.\d+)?))?", raw_src)
        if tm:
            t_in = round(float(tm.group(1)), 3)
            t_out = round(float(tm.group(2)), 3) if tm.group(2) else None
        dur = (
            round((t_out - t_in) / speed_val, 3)
            if (t_in is not None and t_out is not None)
            else (round(float(dur_m.group(1)), 3) if dur_m else None)
        )
        end_val = round(at_val + dur, 3) if dur is not None else None
        fade_in = 0.0
        fade_out = 0.0
        if ovr_m:
            try:
                ovr_data = json.loads(ovr_m.group(2))
                ovr_items = ovr_data if isinstance(ovr_data, list) else [ovr_data]
                for ov_it in ovr_items:
                    if isinstance(ov_it, dict) and isinstance(ov_it.get("fade"), list) and len(ov_it["fade"]) >= 2:
                        fade_in = max(fade_in, float(ov_it["fade"][0] or 0.0))
                        fade_out = max(fade_out, float(ov_it["fade"][1] or 0.0))
            except Exception:
                pass
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
                "speed": speed_val,
                "dur": dur,
                "end": end_val,
                "fade_in": fade_in,
                "fade_out": fade_out,
                "anim": anim_name,
                "style": style_m.group(1) if style_m else "",
            }
        )
    return clips


def parse_css_px(style: str, prop: str, default: float | None = None) -> float | None:
    m = re.search(
        rf"(?:^|[;\s]){re.escape(prop)}\s*:\s*(-?\d+(?:\.\d+)?)px", style, flags=re.IGNORECASE
    )
    return float(m.group(1)) if m else default


def extract_keyframes_blocks(css_text: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    for m in re.finditer(r"@keyframes\s+([A-Za-z0-9_-]+)\s*\{", css_text, flags=re.IGNORECASE):
        name = m.group(1)
        depth = 1
        i = m.end()
        n = len(css_text)
        while i < n and depth > 0:
            if css_text[i] == "{":
                depth += 1
            elif css_text[i] == "}":
                depth -= 1
            i += 1
        blocks[name] = css_text[m.end() : max(m.end(), i - 1)]
    return blocks


def parse_css_inset(expr: str, box_w: float, box_h: float) -> tuple[float, float, float, float] | None:
    core = re.split(r"\bround\b", expr, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    tokens = [t for t in re.split(r"\s+", core) if t]
    if not tokens or len(tokens) > 4:
        return None

    def val_px(tok: str, ref: float) -> float | None:
        m_px = re.match(r"^(-?\d+(?:\.\d+)?)px$", tok, flags=re.IGNORECASE)
        if m_px:
            return float(m_px.group(1))
        m_pct = re.match(r"^(-?\d+(?:\.\d+)?)%$", tok)
        if m_pct:
            return ref * float(m_pct.group(1)) / 100.0
        if tok in {"0", "0.0"}:
            return 0.0
        return None

    if len(tokens) == 1:
        t_raw, r_raw, b_raw, l_raw = tokens[0], tokens[0], tokens[0], tokens[0]
    elif len(tokens) == 2:
        t_raw, r_raw, b_raw, l_raw = tokens[0], tokens[1], tokens[0], tokens[1]
    elif len(tokens) == 3:
        t_raw, r_raw, b_raw, l_raw = tokens[0], tokens[1], tokens[2], tokens[1]
    else:
        t_raw, r_raw, b_raw, l_raw = tokens[0], tokens[1], tokens[2], tokens[3]

    tv = val_px(t_raw, box_h)
    rv = val_px(r_raw, box_w)
    bv = val_px(b_raw, box_h)
    lv = val_px(l_raw, box_w)
    if tv is None or rv is None or bv is None or lv is None:
        return None
    return (tv, rv, bv, lv)


def resolve_pip_steady_inset(
    merged_css: str, keyframes_map: dict[str, str], box_w: float, box_h: float
) -> tuple[float, float, float, float]:
    candidates: list[tuple[float, float, float, float]] = []
    for m in re.finditer(r"clip-path\s*:\s*inset\(([^)]+)\)", merged_css, flags=re.IGNORECASE):
        ins = parse_css_inset(m.group(1), box_w, box_h)
        if ins:
            candidates.append(ins)
    for am in re.finditer(r"animation(?:-name)?\s*:\s*([A-Za-z0-9_-]+)", merged_css, flags=re.IGNORECASE):
        kf_body = keyframes_map.get(am.group(1), "")
        if kf_body:
            for m in re.finditer(r"clip-path\s*:\s*inset\(([^)]+)\)", kf_body, flags=re.IGNORECASE):
                ins = parse_css_inset(m.group(1), box_w, box_h)
                if ins:
                    candidates.append(ins)
    if not candidates:
        return (0.0, 0.0, 0.0, 0.0)
    return max(candidates, key=lambda x: x[0] + x[2])


def resolve_max_scale_in_css(merged_css: str, keyframes_map: dict[str, str]) -> float:
    scales = [1.0]
    scale_pat = re.compile(
        r"(?:scale\(\s*(\d+(?:\.\d+)?)|(?:^|[;{\s])scale\s*:\s*(\d+(?:\.\d+)?))",
        flags=re.IGNORECASE,
    )
    for sm in scale_pat.finditer(merged_css):
        scales.append(float(sm.group(1) or sm.group(2)))
    for am in re.finditer(r"animation(?:-name)?\s*:\s*([A-Za-z0-9_-]+)", merged_css, flags=re.IGNORECASE):
        kf_body = keyframes_map.get(am.group(1), "")
        for sm in scale_pat.finditer(kf_body):
            scales.append(float(sm.group(1) or sm.group(2)))
    return max(scales, key=lambda v: abs(v - 1.0))


def strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_cjk_bigrams(text: str) -> set[str]:
    clean = re.sub(r"[^\u4e00-\u9fff]+", " ", text)
    grams: set[str] = set()
    for chunk in clean.split():
        for i in range(len(chunk) - 1):
            bg = chunk[i : i + 2]
            if bg not in SYNC_STOPWORDS:
                grams.add(bg)
    return grams


def cjk_only(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text))


def longest_common_substring_len(a: str, b: str) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ca in a:
        curr = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                curr[j] = prev[j - 1] + 1
                if curr[j] > best:
                    best = curr[j]
        prev = curr
    return best


class _SceneSyncDOMParser(HTMLParser):
    """Walk scene HTML/SVG DOM to separate t=0 upfront text, deferred text, and space-between child counts."""

    def __init__(
        self,
        cls_zero_opacity: set[str],
        id_zero_opacity: set[str],
        delayed_id_prefixes: set[str],
        space_between_classes: set[str] | None = None,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.cls_zero = cls_zero_opacity
        self.id_zero = id_zero_opacity
        self.delayed_prefixes = delayed_id_prefixes
        self.sb_classes = space_between_classes or set()
        self.stack: list[dict[str, Any]] = []
        self.upfront_texts: list[str] = []
        self.deferred_texts: list[str] = []
        self.all_texts: list[str] = []
        self.sb_child_counts: dict[str, list[int]] = {}

    def _is_hidden_node(self, tag: str, attrs_dict: dict[str, str]) -> tuple[bool, str]:
        el_id = attrs_dict.get("id", "")
        classes = attrs_dict.get("class", "").split()
        style = attrs_dict.get("style", "")
        op_attr = attrs_dict.get("opacity", "").strip()
        hidden = False
        if op_attr in {"0", "0.0", "0.00"}:
            hidden = True
        if re.search(r"(?:^|[;\s])opacity\s*:\s*0(?:\.0+)?(?:\s*;|\s*$)", style, flags=re.IGNORECASE):
            hidden = True
        if re.search(r"(?:^|[;\s])display\s*:\s*none", style, flags=re.IGNORECASE):
            hidden = True
        if el_id and el_id in self.id_zero:
            hidden = True
        if any(c in self.cls_zero for c in classes):
            hidden = True
        return hidden, el_id

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t_low = tag.lower()
        if t_low in {"br", "hr", "img", "meta", "link", "input", "source", "path", "line", "circle"}:
            if self.stack and t_low == "img":
                self.stack[-1]["child_count"] += 1
            return
        if self.stack:
            self.stack[-1]["child_count"] += 1
        ad = {k.lower(): (v or "") for k, v in attrs}
        classes = ad.get("class", "").split()
        own_hidden, el_id = self._is_hidden_node(t_low, ad)
        parent_hidden = self.stack[-1]["hidden"] if self.stack else False
        parent_delayed = self.stack[-1]["delayed"] if self.stack else False
        own_delayed = bool(
            el_id
            and any(
                el_id == p or (len(p) >= 1 and el_id.startswith(p) and el_id[len(p) :].isdigit())
                for p in self.delayed_prefixes
            )
        )
        matched_sb = [c for c in classes if c in self.sb_classes]
        self.stack.append(
            {
                "tag": t_low,
                "id": el_id,
                "sb_classes": matched_sb,
                "child_count": 0,
                "hidden": parent_hidden or own_hidden,
                "delayed": parent_delayed or (own_hidden and (own_delayed or not self.delayed_prefixes)),
                "buf": [],
            }
        )

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        node = self.stack.pop()
        for sbc in node.get("sb_classes", []):
            self.sb_child_counts.setdefault(sbc, []).append(node["child_count"])
        if node["tag"] in {"script", "style", "head", "title"}:
            return
        txt = re.sub(r"\s+", " ", "".join(node["buf"])).strip()
        if not txt:
            return
        self.all_texts.append(txt)
        if node["hidden"] and node["delayed"]:
            self.deferred_texts.append(txt)
        else:
            self.upfront_texts.append(txt)

    def handle_data(self, data: str) -> None:
        if not self.stack:
            return
        if self.stack[-1]["tag"] in {"script", "style", "head", "title"}:
            return
        if data.strip():
            self.stack[-1]["buf"].append(data)


def analyze_scene_sync(
    scene_path: Path,
    clip_id: str,
    track: str,
    at: float,
    dur: float,
    all_cues: list[tuple[float, float, str]],
) -> dict[str, Any]:
    end = at + dur
    shot_cues = [c for c in all_cues if c[1] > at + 0.18 and c[0] < end - 0.18]
    next_cues = [c for c in all_cues if end - 0.05 <= c[0] <= end + 6.5]
    txt = scene_path.read_text(encoding="utf-8", errors="replace")

    cls_zero: set[str] = set()
    id_zero: set[str] = set()
    for sb in re.findall(r"<style\b[^>]*>([\s\S]*?)</style>", txt, flags=re.IGNORECASE):
        for cm in re.finditer(r"([.#][A-Za-z0-9_-]+)\s*\{([^}]*)\}", sb):
            sel, body = cm.group(1), cm.group(2)
            if re.search(r"(?:^|[;\s])opacity\s*:\s*0(?:\.0+)?(?:\s*;|\s*$)", body, flags=re.IGNORECASE):
                if sel.startswith("."):
                    cls_zero.add(sel[1:])
                else:
                    id_zero.add(sel[1:])

    scripts = "\n".join(re.findall(r"<script\b[^>]*>([\s\S]*?)</script>", txt, flags=re.IGNORECASE))
    triggers: list[float] = []
    for m in re.finditer(r"\bt\s*-\s*(\d+(?:\.\d+)?)", scripts):
        v = float(m.group(1))
        if 0.0 < v <= dur + 0.5:
            triggers.append(v)
    for m in re.finditer(
        r"(?:delays|starts|steps|times|T_\w+)\s*=\s*\[([^\]]+)\]", scripts, flags=re.IGNORECASE
    ):
        for nm in re.findall(r"\d+(?:\.\d+)?", m.group(1)):
            v = float(nm)
            if 0.0 < v <= dur + 0.5:
                triggers.append(v)
    for m in re.finditer(r"\bconst\s+T[A-Za-z0-9_]*\s*=\s*(\d+(?:\.\d+)?)", scripts):
        v = float(m.group(1))
        if 0.0 < v <= dur + 0.5:
            triggers.append(v)

    loop_counts: list[int] = [int(x) for x in re.findall(r"<\s*(\d+)\s*;", scripts) if 1 < int(x) <= 12]
    for arr_m in re.finditer(r"\[([^\]]+)\]\.forEach", scripts):
        items = [x.strip() for x in arr_m.group(1).split(",") if x.strip()]
        if 1 < len(items) <= 12:
            loop_counts.append(len(items))
    max_n = max(loop_counts) if loop_counts else 0
    if max_n >= 2:
        for lm in re.finditer(
            r"(?:(\d+(?:\.\d+)?)\s*[+-]\s*)?[A-Za-z_]\w*\s*\*\s*(\d+(?:\.\d+)?)", scripts
        ):
            base = float(lm.group(1)) if lm.group(1) else 0.0
            step = float(lm.group(2))
            cand = base + (max_n - 1) * step
            if 0.0 < cand <= dur + 1.0:
                triggers.append(round(cand, 3))

    max_trigger = max(triggers) if triggers else 0.0
    min_trigger = min(triggers) if triggers else 0.0

    delayed_prefixes: set[str] = set()
    if max_trigger >= 0.45:
        for gm in re.finditer(r"getElementById\(\s*['\"]([A-Za-z0-9_-]+)['\"]\s*(?:\+)?", scripts):
            delayed_prefixes.add(gm.group(1))
        for arr_m in re.finditer(r"\[((?:\s*['\"][A-Za-z0-9_-]+['\"]\s*,?)+)\]\.forEach", scripts):
            for s_id in re.findall(r"['\"]([A-Za-z0-9_-]+)['\"]", arr_m.group(1)):
                delayed_prefixes.add(s_id)
        if min_trigger < 0.45:
            delayed_prefixes = {p for p in delayed_prefixes if not p.endswith("0")}

    parser = _SceneSyncDOMParser(cls_zero, id_zero, delayed_prefixes)
    try:
        parser.feed(txt)
    except Exception:
        pass

    script_lits = _extract_script_text_literals(scripts)
    has_canvas = bool(re.search(r"<canvas\b", txt, flags=re.IGNORECASE))
    dual_texts = list(parser.all_texts)
    if script_lits and (has_canvas or len(cjk_only("".join(parser.all_texts))) < 12):
        for sl in script_lits:
            if sl not in dual_texts:
                dual_texts.append(sl)

    upfront_cjk = len(cjk_only("".join(parser.upfront_texts)))
    total_cjk = len(cjk_only("".join(dual_texts)))
    last_cue_local = round(shot_cues[-1][0] - at, 2) if shot_cues else 0.0

    curr_grams = extract_cjk_bigrams(" ".join(c[2] for c in shot_cues))
    next_only_grams = extract_cjk_bigrams(" ".join(c[2] for c in next_cues)) - curr_grams
    scene_grams = extract_cjk_bigrams(" ".join(dual_texts))
    leaked_next_grams = sorted(scene_grams & next_only_grams)

    hard_issues: list[str] = []
    warn_issues: list[str] = []

    has_media = bool(re.search(r"<(?:img|video)\b", txt, flags=re.IGNORECASE))

    # Rule 1: Ultra-long unsegmented overlay (>7.5s)
    if track == "overlays" and dur > 7.5 and max_trigger < dur * 0.45:
        hard_issues.append(
            f"超长覆盖层挂屏 {dur:.2f}s(>7.5s) 且最大动画触发点仅 {max_trigger:.2f}s，提前剧透后续台词"
        )

    # Rule 2: Frame-0 static multi-item text dump on multi-cue shots
    if dur >= 4.0 and len(shot_cues) >= 2:
        if len(parser.upfront_texts) >= 5 and upfront_cjk > 32:
            sample = " / ".join(x[:14] for x in parser.upfront_texts[:4])
            hard_issues.append(
                f"t=0 静态裸露文本过多（首 0.4s 即摊牌 {len(parser.upfront_texts)} 处共 {upfront_cjk} 字:「{sample}」），未随口播渐进揭示"
            )

    # Rule 3: Empty skeleton box waiting > 1.0s before any meaningful text/media appears
    if (
        track == "main-stage"
        and dur >= 3.8
        and not has_media
        and not has_canvas
        and upfront_cjk < 4
        and total_cjk >= 6
        and min_trigger > 1.0
    ):
        hard_issues.append(
            f"首帧空黑框死等缺陷：前 {min_trigger:.2f}s(>1.0s) 画面几乎无文字/无媒体(仅 {upfront_cjk} 字)，冷等延迟后才出字"
        )

    # Rule 4: Premature animation freeze
    if (
        track == "main-stage"
        and dur >= 4.8
        and len(shot_cues) >= 2
        and last_cue_local >= 3.0
        and not has_canvas
        and (not has_media or len(parser.all_texts) >= 5)
    ):
        threshold = min(last_cue_local - 1.3, dur * 0.42)
        if max_trigger < threshold:
            hard_issues.append(
                f"动画前半程抢跑死镜（镜长 {dur:.2f}s，末句在 local_t={last_cue_local:.2f}s，但最大触发仅 {max_trigger:.2f}s < {threshold:.2f}s）"
            )

    # Rule 5: Cross-shot spoiler
    if len(leaked_next_grams) >= 3:
        hard_issues.append(
            f"跨镜台词错配：提前出现了下一镜才说的专属词组({', '.join(leaked_next_grams[:5])})"
        )

    # Rule 6: Zero-Echo Subtitle Duplication on overlays (banner copying bottom subtitle)
    if track == "overlays" and shot_cues:
        echo_hits: list[str] = []
        cue_cjk_list = [cjk_only(c[2]) for c in shot_cues if len(cjk_only(c[2])) >= 6]
        for raw_blk in parser.all_texts:
            blk_c = cjk_only(raw_blk)
            if len(blk_c) < 6:
                continue
            for cc in cue_cjk_list:
                lcs = longest_common_substring_len(blk_c, cc)
                if lcs >= 6 and (lcs / len(blk_c)) >= 0.72:
                    echo_hits.append(raw_blk[:18])
                    break
        if echo_hits:
            hard_issues.append(
                f"前景花字/横幅复读底部字幕回声冗余（「{' / '.join(dict.fromkeys(echo_hits))}」与同期字幕高度重合 >=72%），须提炼 <=5 字核心锚点词"
            )

    # Rule 7: Concrete Business Entity Semantic Grounding Gate (dual-channel DOM + <script> Canvas)
    if track == "main-stage" and not has_media and dur >= 3.0 and shot_cues:
        ctx_cues = [c for c in all_cues if c[1] >= max(0.0, at - 2.2) and c[0] <= end + 2.2]
        spoken_ctx_str = " ".join(c[2] for c in (ctx_cues or shot_cues))
        concrete_spoken_grams = {
            g for g in extract_cjk_bigrams(spoken_ctx_str) if g not in ABSTRACT_JARGON_WORDS
        }
        spoken_alnum = {
            t.lower()
            for t in re.findall(r"[A-Za-z]{2,}\d*|\d+(?:\.\d+)?%?", spoken_ctx_str)
            if len(t) >= 2
        }
        dual_joined = " ".join(dual_texts)
        concrete_scene_grams = {
            g for g in extract_cjk_bigrams(dual_joined) if g not in ABSTRACT_JARGON_WORDS
        }
        scene_alnum = {
            t.lower()
            for t in re.findall(r"[A-Za-z]{2,}\d*|\d+(?:\.\d+)?%?", dual_joined)
            if len(t) >= 2
        }
        has_concrete_overlap = bool(
            (concrete_spoken_grams & concrete_scene_grams) or (spoken_alnum & scene_alnum)
        )
        if len(concrete_spoken_grams) >= 3 and not has_concrete_overlap:
            if len(concrete_scene_grams) <= 2:
                hard_issues.append(
                    "脱离口播语境的抽象废线/空话页：双通道(DOM+Canvas脚本)未命中本镜口播任何具体业务名词或数字，严禁画无关几何线条或空洞大词充数"
                )
            else:
                warn_issues.append(
                    "场景具象词与当前口播原词零直接重合，请确认是否为同一业务案例的异构图解转译"
                )

    return {
        "clip_id": clip_id,
        "scene": scene_path.name,
        "track": track,
        "at": round(at, 2),
        "dur": round(dur, 2),
        "cue_count": len(shot_cues),
        "last_cue_local_t": last_cue_local,
        "min_trigger_t": round(min_trigger, 2),
        "max_trigger_t": round(max_trigger, 2),
        "upfront_text_nodes": len(parser.upfront_texts),
        "upfront_chars": upfront_cjk,
        "deferred_text_nodes": len(parser.deferred_texts),
        "total_chars": total_cjk,
        "leaked_next_grams": leaked_next_grams,
        "hard_issues": hard_issues,
        "warnings": warn_issues,
    }


def inspect_boxless_scene(scene_path: Path, film_dir: Path) -> dict[str, Any]:
    """Check pure frame(t) determinism, fake progress bars, image aspect crop distortion, and space-between classes."""
    txt = scene_path.read_text(encoding="utf-8", errors="replace")
    hard: list[str] = []
    sb_classes_tall: dict[str, float] = {}
    cls_css: dict[str, str] = {}

    for sb in re.findall(r"<style\b[^>]*>([\s\S]*?)</style>", txt, flags=re.IGNORECASE):
        sb_no_comments = re.sub(r"/\*[\s\S]*?\*/", "", sb)
        if re.search(r"(?:^|[;{\s])transition\s*:\s*(?!none\b)[^;}]+", sb_no_comments, flags=re.IGNORECASE):
            hard.append(
                "违反 OpenFilm 纯函数确定性铁律(SPEC.md §3)：检测到 CSS `transition`，多 worker 乱序跳帧渲染必引发闪烁错位，必须剥离并改写为纯 `window.film.frame(t)` 数学插值"
            )
        sb_no_kf = re.sub(
            r"@keyframes\s+[A-Za-z0-9_-]+\s*\{(?:[^{}]|\{[^{}]*\})*\}", "", sb_no_comments, flags=re.IGNORECASE
        )
        for cm in re.finditer(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}", sb_no_kf):
            cname, cbody = cm.group(1), cm.group(2)
            cls_css[cname] = cls_css.get(cname, "") + ";" + cbody
            if re.search(r"justify-content\s*:\s*space-between", cbody, flags=re.IGNORECASE):
                h_px = parse_css_px(cbody, "height")
                if h_px is not None and h_px >= 380.0:
                    sb_classes_tall[cname] = h_px

    scripts_raw = "\n".join(re.findall(r"<script\b[^>]*>([\s\S]*?)</script>", txt, flags=re.IGNORECASE))
    scripts_no_comments = re.sub(r"//[^\r\n]*|/\*[\s\S]*?\*/", "", scripts_raw)
    if re.search(r"\b(?:setTimeout|setInterval)\s*\(", scripts_no_comments):
        hard.append(
            "违反 OpenFilm 纯函数确定性铁律：`<script>` 含 `setTimeout/setInterval` 异步定时器，并行跳帧渲染时无法触发或状态错乱，必须重构为基于 `t` 的纯函数"
        )

    body_m = re.search(r"<body\b[^>]*>([\s\S]*?)</body>", txt, flags=re.IGNORECASE)
    body_html = body_m.group(1) if body_m else txt
    body_no_script = re.sub(r"<(script|style)\b[\s\S]*?</\1>", "", body_html, flags=re.IGNORECASE)
    body_no_defs = re.sub(r"<(defs|clipPath|mask)\b[\s\S]*?</\1>", "", body_no_script, flags=re.IGNORECASE)

    # 1. Count SVG horizontal bar rects (concrete UI cards/bubbles/tables are allowed in master & v1-v3!)
    content_rects = 0
    bar_rects = 0
    for rm in re.finditer(r"<rect\b([^>]*)>", body_no_defs, flags=re.IGNORECASE):
        rattrs = rm.group(1)
        wm = re.search(r'\bwidth=["\'](\d+(?:\.\d+)?)["\']', rattrs)
        hm = re.search(r'\bheight=["\'](\d+(?:\.\d+)?)["\']', rattrs)
        rw = float(wm.group(1)) if wm else 100.0
        rh = float(hm.group(1)) if hm else 100.0
        if rw <= 12.0 or rh <= 10.0:
            continue
        if rw >= 1000.0 and rh >= 1800.0:
            continue
        content_rects += 1
        if 12.0 <= rh <= 42.0 and rw >= 360.0 and (rw / max(1.0, rh)) >= 9.0:
            bar_rects += 1

    # 2. Fake progress/loading bar without real quantitative numbers (dual-channel DOM + <script> check)
    clean_visible_txt = _extract_scene_dual_text(txt)
    has_quant_num = bool(
        re.search(
            r"(?:[¥$]\s*\d+|\d+(?:\.\d+)?\s*(?:%|倍|万|亿|元|块|美金|美元|刀|年|月|天|小时|分钟|秒|人|家|单|款|个|L|kg|ms|x|X)|20[12]\d)",
            clean_visible_txt,
        )
    )
    has_css_progress = bool(
        re.search(r'class=["\'][^"\']*\b(?:progress(?:-bar|-fill)?|bar-fill|meter-fill)\b', body_no_script, re.I)
    )
    if (bar_rects >= 1 or has_css_progress) and not has_quant_num:
        hard.append(
            "违反数据真实性铁律：画面无任何真实量化数值(%/倍数/金额/年份)，却强行绘制伪进度条/假柱状图充数"
        )

    # 4. Image aspect-ratio crop distortion (e.g. 9:16 portrait image cropped into >2.2:1 wide strip)
    for im in re.finditer(r"<img\b([^>]*)>", body_no_script, flags=re.IGNORECASE):
        iattrs = im.group(1)
        src_m = re.search(r'src=["\']([^"\']+)["\']', iattrs)
        if not src_m:
            continue
        raw_src = src_m.group(1).split("#", 1)[0]
        img_file = (scene_path.parent / raw_src).resolve()
        if not img_file.is_file():
            img_file = (film_dir / raw_src).resolve()
        if not img_file.is_file() or img_file.name.lower() == "logo.png":
            continue

        icls_m = re.search(r'\bclass=["\']([^"\']+)["\']', iattrs)
        istyle_m = re.search(r'\bstyle=["\']([^"\']+)["\']', iattrs)
        merged_icss = ";".join(
            ([cls_css.get(c, "") for c in icls_m.group(1).split()] if icls_m else [])
            + ([istyle_m.group(1)] if istyle_m else [])
        )
        iw_px = parse_css_px(merged_icss, "width")
        ih_px = parse_css_px(merged_icss, "height")
        is_cover = "object-fit" not in merged_icss.lower() or "cover" in merged_icss.lower()
        if iw_px and ih_px and ih_px > 0 and is_cover:
            try:
                iprobe = ffprobe_json(img_file)
                vs = next((s for s in iprobe.get("streams", []) if s.get("codec_type") == "video"), None)
                if vs and int(vs.get("width", 0)) > 0 and int(vs.get("height", 0)) > 0:
                    ar_src = int(vs["width"]) / int(vs["height"])
                    ar_box = iw_px / ih_px
                    ratio_mismatch = max(ar_box / ar_src, ar_src / ar_box)
                    if ratio_mismatch > 2.2:
                        hard.append(
                            f"图片画幅硬塞畸变：`{img_file.name}`(源宽高比 {ar_src:.2f}) 被 cover 强塞入 {iw_px:.0f}x{ih_px:.0f}(宽高比 {ar_box:.2f}，畸变倍数 {ratio_mismatch:.1f}x > 2.2x)"
                        )
            except Exception:
                pass

    # 5. Parse space-between direct child counts
    dom_p = _SceneSyncDOMParser(set(), set(), set(), set(sb_classes_tall.keys()))
    try:
        dom_p.feed(txt)
    except Exception:
        pass

    return {
        "scene": scene_path.name,
        "hard_issues": hard,
        "content_rects": content_rects,
        "sb_child_counts": dom_p.sb_child_counts,
        "sb_heights": sb_classes_tall,
    }


def inspect_behind_person_scene(scene_path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "scene": scene_path.name,
        "svg_texts": [],
        "html_texts": [],
        "too_low_texts": [],
        "long_texts": [],
        "has_behind_text": False,
        "has_video_tag": False,
    }
    if not scene_path.is_file():
        return info
    txt = scene_path.read_text(encoding="utf-8", errors="replace")
    info["has_video_tag"] = bool(re.search(r"<video\b", txt, flags=re.IGNORECASE))

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

    body_m = re.search(r"<body\b[^>]*>([\s\S]*?)</body>", txt, flags=re.IGNORECASE)
    body_html = body_m.group(1) if body_m else txt
    body_no_noise = re.sub(r"<(script|style|svg)\b[\s\S]*?</\1>", "", body_html, flags=re.IGNORECASE)
    pill_cls_re = re.compile(r"\b(?:pill|top-pill|top-tag|cap|eyebrow|badge)\b", flags=re.IGNORECASE)

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
        if top_val is None and fs_val is None:
            continue
        if (top_val is not None and top_val < 230.0) and (fs_val is None or fs_val <= 38.0):
            continue
        if pill_cls_re.search(cls_str) and (fs_val is None or fs_val <= 38.0):
            continue

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
    if "04-v4" in hay or "/v4-" in hay:
        return "v4"
    if "00-master" in hay or "/master/" in hay:
        return "master"
    return "default"


# ---------------------------------------------------------------------------
# Visual Safezone & B-roll Contact Sheet Rendering
# ---------------------------------------------------------------------------


def render_safezone_overlays(
    video: Path,
    duration: float,
    out_dir: Path,
    cut_points: list[float] | None = None,
    cutout_sticker_points: list[float] | None = None,
    pip_points: list[float] | None = None,
    broll_samples: list[tuple[Path, float | None]] | None = None,
    is_landscape: bool = False,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    full_scale = "1920:1080" if is_landscape else "1080:1920"
    grid_scale = "960:540" if is_landscape else "540:960"
    thumb_scale = "640:360" if is_landscape else "360:640"
    thumb_size = "640x360" if is_landscape else "360x640"
    if is_landscape:
        box_filter = (
            "drawbox=x=0:y=0:w=1920:h=90:color=red@0.24:t=fill,"
            "drawbox=x=0:y=88:w=1920:h=3:color=red@0.90:t=fill,"
            "drawbox=x=0:y=900:w=1920:h=180:color=red@0.24:t=fill,"
            "drawbox=x=0:y=900:w=1920:h=3:color=red@0.90:t=fill,"
            "drawbox=x=1760:y=360:w=160:h=540:color=orange@0.30:t=fill,"
            "drawbox=x=1760:y=360:w=3:h=540:color=orange@0.95:t=fill"
        )
    else:
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

    def _build_grid_cmd(hw_flags: list[str]) -> list[str]:
        c = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        for t in timestamps:
            c += [*hw_flags, "-ss", f"{t:.2f}", "-i", str(video)]
        f_parts = []
        for idx in range(len(timestamps)):
            f_parts.append(f"[{idx}:v]scale={full_scale},{box_filter},scale={grid_scale}[v{idx}]")
        f_parts.append("[v0][v1][v2]hstack=inputs=3[top]")
        f_parts.append("[v3][v4][v5]hstack=inputs=3[bot]")
        f_parts.append("[top][bot]vstack=inputs=2[out]")
        c += ["-filter_complex", ";".join(f_parts), "-map", "[out]", "-frames:v", "1", str(grid_path)]
        return c

    proc1 = run_ffmpeg_decode_cmd(_build_grid_cmd)
    if proc1.returncode != 0:
        raise RuntimeError(f"safezone-grid render failed: {proc1.stderr.strip()}")

    tail_t = round(max(0.05, duration - 0.8), 2)
    proc2 = run_ffmpeg_decode_cmd(
        lambda hw_flags: [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            *hw_flags,
            "-ss",
            f"{tail_t:.2f}",
            "-i",
            str(video),
            "-vf",
            f"scale={full_scale},{box_filter}",
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

    valid_cuts = [c for c in (cut_points or []) if 0.1 < c < (duration - 0.1)]
    if valid_cuts:
        picked = (
            valid_cuts
            if len(valid_cuts) <= 3
            else [valid_cuts[0], valid_cuts[len(valid_cuts) // 2], valid_cuts[-1]]
        )
        cuts_path = out_dir / "safezone-cuts.png"

        def _build_cuts_cmd(hw_flags: list[str]) -> list[str]:
            c = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
            f_cut_parts: list[str] = []
            row_labels: list[str] = []
            inp_idx = 0
            for row_i, ct in enumerate(picked):
                tri = [max(0.02, ct - 0.034), ct, min(duration - 0.02, ct + 0.034)]
                row_inps = []
                for tt in tri:
                    c += [*hw_flags, "-ss", f"{tt:.3f}", "-i", str(video)]
                    lbl = f"c{inp_idx}"
                    f_cut_parts.append(f"[{inp_idx}:v]scale={thumb_scale}[{lbl}]")
                    row_inps.append(f"[{lbl}]")
                    inp_idx += 1
                rlbl = f"row{row_i}"
                f_cut_parts.append(f"{''.join(row_inps)}hstack=inputs=3[{rlbl}]")
                row_labels.append(f"[{rlbl}]")
            if len(row_labels) == 1:
                final_map = row_labels[0]
            else:
                f_cut_parts.append(f"{''.join(row_labels)}vstack=inputs={len(row_labels)}[cuts_out]")
                final_map = "[cuts_out]"
            c += ["-filter_complex", ";".join(f_cut_parts), "-map", final_map, "-frames:v", "1", str(cuts_path)]
            return c

        if run_ffmpeg_decode_cmd(_build_cuts_cmd).returncode == 0:
            result["safezone_cuts"] = rel_path(cuts_path)
            result["cut_burst_timestamps_sec"] = [round(c, 3) for c in picked]

    raw_cs = sorted({round(t, 2) for t in (cutout_sticker_points or []) if 0.05 < t < (duration - 0.05)})
    valid_cs: list[float] = []
    for t in raw_cs:
        if valid_cs and (t - valid_cs[-1]) < 1.2:
            valid_cs[-1] = t
        else:
            valid_cs.append(t)
    if valid_cs:
        picked_cs = (
            [valid_cs[int(round(i * (len(valid_cs) - 1) / 5.0))] for i in range(6)]
            if len(valid_cs) > 6
            else valid_cs
        )
        cs_path = out_dir / "safezone-cutouts.png"
        head_box_filter = (
            box_filter
            if is_landscape
            else (
                box_filter
                + ",drawbox=x=220:y=280:w=640:h=740:color=magenta@0.80:t=4"
                + ",drawbox=x=0:y=640:w=1080:h=2:color=yellow@0.70:t=fill"
            )
        )

        def _build_cs_cmd(hw_flags: list[str]) -> list[str]:
            c = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
            f_cs_parts: list[str] = []
            for idx, tt in enumerate(picked_cs):
                c += [*hw_flags, "-ss", f"{tt:.2f}", "-i", str(video)]
                f_cs_parts.append(f"[{idx}:v]scale={full_scale},{head_box_filter},scale={thumb_scale}[cs{idx}]")
            n = len(picked_cs)
            if n <= 3:
                cs_map = "[cs0]" if n == 1 else "[cs_out]"
                if n > 1:
                    f_cs_parts.append(f"{''.join(f'[cs{i}]' for i in range(n))}hstack=inputs={n}[cs_out]")
            else:
                cols = 3
                pad_n = (cols - (n % cols)) % cols
                for p_i in range(pad_n):
                    f_cs_parts.append(f"color=c=black:s={thumb_size}:d=1[csp{p_i}]")
                all_lbls = [f"[cs{i}]" for i in range(n)] + [f"[csp{p_i}]" for p_i in range(pad_n)]
                f_cs_parts.append(f"{''.join(all_lbls[:3])}hstack=inputs=3[csr1]")
                f_cs_parts.append(f"{''.join(all_lbls[3:6])}hstack=inputs=3[csr2]")
                f_cs_parts.append("[csr1][csr2]vstack=inputs=2[cs_out]")
                cs_map = "[cs_out]"
            c += ["-filter_complex", ";".join(f_cs_parts), "-map", cs_map, "-frames:v", "1", str(cs_path)]
            return c

        if run_ffmpeg_decode_cmd(_build_cs_cmd).returncode == 0:
            result["safezone_cutouts"] = rel_path(cs_path)
            result["cutout_sticker_timestamps_sec"] = picked_cs

    raw_pip = sorted({round(t, 2) for t in (pip_points or []) if 0.05 < t < (duration - 0.05)})
    if raw_pip:
        picked_pip = (
            [raw_pip[int(round(i * (len(raw_pip) - 1) / 5.0))] for i in range(6)]
            if len(raw_pip) > 6
            else raw_pip
        )
        pip_path = out_dir / "safezone-pip.png"

        def _build_pip_cmd(hw_flags: list[str]) -> list[str]:
            c = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
            f_pip_parts: list[str] = []
            for idx, tt in enumerate(picked_pip):
                c += [*hw_flags, "-ss", f"{tt:.2f}", "-i", str(video)]
                f_pip_parts.append(
                    f"[{idx}:v]scale=1080:1920,crop=1080:560:0:130,"
                    f"drawbox=x=0:y=50:w=1080:h=2:color=red@0.85:t=fill,"
                    f"scale=720:374[pp{idx}]"
                )
            npip = len(picked_pip)
            if npip == 1:
                pip_map = "[pp0]"
            elif npip == 2:
                f_pip_parts.append("[pp0][pp1]hstack=inputs=2[pip_out]")
                pip_map = "[pip_out]"
            else:
                cols = 2
                pad_n = (cols - (npip % cols)) % cols
                for p_i in range(pad_n):
                    f_pip_parts.append(f"color=c=black:s=720x374:d=1[ppp{p_i}]")
                all_pp = [f"[pp{i}]" for i in range(npip)] + [f"[ppp{p_i}]" for p_i in range(pad_n)]
                rows = []
                for r_i in range(0, len(all_pp), 2):
                    rlbl = f"ppr{r_i // 2}"
                    f_pip_parts.append(f"{all_pp[r_i]}{all_pp[r_i + 1]}hstack=inputs=2[{rlbl}]")
                    rows.append(f"[{rlbl}]")
                f_pip_parts.append(f"{''.join(rows)}vstack=inputs={len(rows)}[pip_out]")
                pip_map = "[pip_out]"
            c += ["-filter_complex", ";".join(f_pip_parts), "-map", pip_map, "-frames:v", "1", str(pip_path)]
            return c

        if run_ffmpeg_decode_cmd(_build_pip_cmd).returncode == 0:
            result["safezone_pip"] = rel_path(pip_path)
            result["pip_timestamps_sec"] = picked_pip

    # Supplemental B-roll start/mid/end contact sheet (safezone-broll.png)
    valid_broll = [(p, t) for (p, t) in (broll_samples or []) if p.is_file()][:12]
    if valid_broll:
        broll_path = out_dir / "safezone-broll.png"
        c_br = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        f_br_parts: list[str] = []
        for idx, (bp, bt) in enumerate(valid_broll):
            if bt is not None and bt > 0:
                c_br += ["-ss", f"{bt:.2f}"]
            c_br += ["-i", str(bp)]
            f_br_parts.append(
                f"[{idx}:v]scale=360:480:force_original_aspect_ratio=decrease,"
                f"pad=360:480:(ow-iw)/2:(oh-ih)/2:color=#111111,setsar=1[br{idx}]"
            )
        nb = len(valid_broll)
        cols = min(3, nb)
        pad_n = (cols - (nb % cols)) % cols
        for p_i in range(pad_n):
            f_br_parts.append(f"color=c=#111111:s=360x480:d=1[brp{p_i}]")
        all_br = [f"[br{i}]" for i in range(nb)] + [f"[brp{p_i}]" for p_i in range(pad_n)]
        if len(all_br) == 1:
            br_map = "[br0]"
        elif len(all_br) <= cols:
            f_br_parts.append(f"{''.join(all_br)}hstack=inputs={len(all_br)}[br_out]")
            br_map = "[br_out]"
        else:
            b_rows: list[str] = []
            for r_i in range(0, len(all_br), cols):
                rlbl = f"brr{r_i // cols}"
                f_br_parts.append(f"{''.join(all_br[r_i : r_i + cols])}hstack=inputs={cols}[{rlbl}]")
                b_rows.append(f"[{rlbl}]")
            f_br_parts.append(f"{''.join(b_rows)}vstack=inputs={len(b_rows)}[br_out]")
            br_map = "[br_out]"
        c_br += ["-filter_complex", ";".join(f_br_parts), "-map", br_map, "-frames:v", "1", str(broll_path)]
        if run_cmd(c_br).returncode == 0:
            result["safezone_broll"] = rel_path(broll_path)
            result["broll_sample_count"] = nb

    return result


_SPEAKER_FOCUS_CACHE: dict[Path, dict[str, Any]] = {}


def probe_speaker_horizontal_focus(video_path: Path, samples: int = 6) -> dict[str, Any]:
    """Measure speaker horizontal face center (`face_cx_pct`) and vertical head span from source video."""
    rp = video_path.resolve()
    if rp in _SPEAKER_FOCUS_CACHE:
        return _SPEAKER_FOCUS_CACHE[rp]

    probe = ffprobe_json(video_path)
    dur = float((probe.get("format") or {}).get("duration") or 0.0)
    vs = next((s for s in (probe.get("streams") or []) if s.get("codec_type") == "video"), None)
    vw = int((vs or {}).get("width") or 1920)
    vh = int((vs or {}).get("height") or 1080)
    ar = round(vw / max(1, vh), 4)

    t_list = (
        [round(dur * r, 2) for r in (0.14, 0.28, 0.44, 0.60, 0.76, 0.88)[: max(1, samples)]]
        if dur > 1.2
        else [0.2]
    )
    out_w, out_h = 320, max(180, int(round(320 / max(0.5, ar))))
    if out_h % 2 == 1:
        out_h += 1

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    for t_s in t_list:
        cmd += ["-ss", f"{t_s:.2f}", "-i", str(video_path)]
    vf_parts = [f"[{i}:v]scale={out_w}:{out_h},format=rgb24[f{i}]" for i in range(len(t_list))]
    if len(t_list) == 1:
        f_map = "[f0]"
    else:
        vf_parts.append(f"{''.join(f'[f{i}]' for i in range(len(t_list)))}vstack=inputs={len(t_list)}[stacked]")
        f_map = "[stacked]"
    cmd += ["-filter_complex", ";".join(vf_parts), "-map", f_map, "-frames:v", "1", "-f", "rawvideo", "-"]
    proc = run_cmd_bytes(cmd)
    frame_bytes = out_w * out_h * 3

    cx_vals: list[float] = []
    top_v_vals: list[float] = []
    chin_v_vals: list[float] = []
    method = "default_center"

    if proc.returncode == 0 and len(proc.stdout) >= frame_bytes:
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore

            cascade_p = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
            clf = cv2.CascadeClassifier(str(cascade_p)) if cascade_p.is_file() else None
            n_frames = min(len(t_list), len(proc.stdout) // frame_bytes)
            frames_gray = []
            for idx in range(n_frames):
                arr = np.frombuffer(
                    proc.stdout[idx * frame_bytes : (idx + 1) * frame_bytes], dtype=np.uint8
                ).reshape((out_h, out_w, 3))
                gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
                frames_gray.append(gray)
                if clf is not None:
                    faces = clf.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(26, 26))
                    if len(faces) > 0:
                        fx, fy, fw, fh = max(faces, key=lambda b: int(b[2]) * int(b[3]))
                        cx_vals.append(((fx + fw * 0.5) / out_w) * 100.0)
                        top_v_vals.append(max(0.02, (fy - fh * 0.22) / out_h))
                        chin_v_vals.append(min(0.95, (fy + fh * 1.05) / out_h))
                        method = "opencv_haar_face"

            if not cx_vals and len(frames_gray) >= 2:
                # Temporal motion centroid in upper 70% of frame (talking head moves while wall stays still!)
                diffs = [
                    np.abs(frames_gray[i + 1].astype(np.float32) - frames_gray[i].astype(np.float32))
                    for i in range(len(frames_gray) - 1)
                ]
                mean_diff = np.mean(diffs, axis=0)[: int(out_h * 0.72), :]
                col_w = np.sum(mean_diff, axis=0)
                if float(np.sum(col_w)) > 50.0:
                    xs = np.arange(out_w, dtype=np.float32) + 0.5
                    cx_vals.append(float(np.sum(xs * col_w) / np.sum(col_w)) / out_w * 100.0)
                    method = "temporal_motion_centroid"
        except Exception:
            pass

    cx_vals.sort()
    face_cx = round(float(cx_vals[len(cx_vals) // 2]), 1) if cx_vals else 50.0
    head_top_v = round(float(sum(top_v_vals) / len(top_v_vals)), 3) if top_v_vals else 0.14
    chin_v = round(float(sum(chin_v_vals) / len(chin_v_vals)), 3) if chin_v_vals else 0.54
    span_v = round(float(max(0.1, chin_v - head_top_v)), 3)
    # Exact CSS object-position-x% to place face_cx at x=540px on a 1080x1920 cover canvas:
    rw_1920 = 1920.0 * ar
    if rw_1920 > 1085.0:
        opt_pos_x = round(max(0.0, min(100.0, (((face_cx / 100.0) * rw_1920 - 540.0) / (rw_1920 - 1080.0)) * 100.0)), 1)
    else:
        opt_pos_x = round(face_cx, 1)

    res = {
        "video": rel_path(video_path),
        "source_size": [int(vw), int(vh)],
        "aspect_ratio": float(ar),
        "detector": method,
        "face_cx_pct": float(face_cx),
        "head_top_v": float(head_top_v),
        "chin_v": float(chin_v),
        "span_v": float(span_v),
        "recommended_object_position": f"{opt_pos_x:.1f}% 38%",
    }
    _SPEAKER_FOCUS_CACHE[rp] = res
    return res


def _load_declared_face_cx(film_dir: Path) -> float | None:
    cand_jsons = [
        film_dir.parent / "script" / "storyboard.json",
        film_dir.parent / "script" / "master-plan.json",
        film_dir.parent.parent / "master" / "script" / "master-plan.json",
        film_dir.parent.parent.parent / "master" / "script" / "master-plan.json",
    ]
    for cj in cand_jsons:
        if not cj.is_file():
            continue
        try:
            jd = json.loads(cj.read_text(encoding="utf-8"))
            for key in ("speaker_focus", "speaker_framing"):
                sub = jd.get(key)
                if isinstance(sub, dict) and sub.get("face_cx_pct") is not None:
                    return float(sub["face_cx_pct"])
            if jd.get("face_cx_pct") is not None:
                return float(jd["face_cx_pct"])
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Film Directory, Covers & Publish JSON V2 Audits
# ---------------------------------------------------------------------------


def audit_film_dir(
    film_dir: Path,
    duration: float,
    style_slot: str,
    hard_failures: list[str],
    warnings: list[str],
) -> tuple[dict[str, Any], list[float], list[float], list[float], list[tuple[Path, float | None]]]:
    details: dict[str, Any] = {"style_slot": style_slot}
    cut_points: list[float] = []
    cutout_sticker_points: list[float] = []
    pip_points: list[float] = []
    broll_samples: list[tuple[Path, float | None]] = []

    film_html = film_dir / "film.html"
    sub_file = film_dir / "scenes" / "subtitles.html"

    # Pre-parse subtitle cues so EDL cutting, zero-pill subtitle, and scene sync checks share them
    parsed_cues_sync: list[tuple[float, float, str]] = []
    raw_cues_html: list[tuple[float, float, str]] = []
    if sub_file.exists():
        sub_raw_pre = sub_file.read_text(encoding="utf-8", errors="replace")
        for cm in re.findall(
            r"\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*([\"'])(.*?)\3",
            sub_raw_pre,
        ):
            s_t, e_t, h_txt = float(cm[0]), float(cm[1]), cm[3]
            raw_cues_html.append((s_t, e_t, h_txt))
            parsed_cues_sync.append((s_t, e_t, strip_html(h_txt)))

    main_clips: list[dict[str, Any]] = []
    pip_clips: list[dict[str, Any]] = []
    overlay_clips: list[dict[str, Any]] = []
    cutout_clips: list[dict[str, Any]] = []
    sticker_clips: list[dict[str, Any]] = []
    fx_trans_clips: list[dict[str, Any]] = []
    speaker_vids_early: set[str] = set()
    audio_stats_cache: dict[Path, dict[str, Any]] = {}

    def cached_audio_stats(p: Path) -> dict[str, Any]:
        rp = p.resolve()
        if rp not in audio_stats_cache:
            audio_stats_cache[rp] = analyze_audio_segment(rp)
        return audio_stats_cache[rp]

    if film_html.exists():
        html_txt = film_html.read_text(encoding="utf-8", errors="replace")

        # Parse <style> CSS blocks & @keyframes
        css_class_rules: dict[str, str] = {}
        keyframes_map: dict[str, str] = {}
        for style_blk in re.findall(r"<style\b[^>]*>([\s\S]*?)</style>", html_txt, flags=re.IGNORECASE):
            keyframes_map.update(extract_keyframes_blocks(style_blk))
            style_no_kf = re.sub(
                r"@keyframes\s+[A-Za-z0-9_-]+\s*\{(?:[^{}]|\{[^{}]*\})*\}",
                "",
                style_blk,
                flags=re.IGNORECASE,
            )
            for cm in re.finditer(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}", style_no_kf):
                css_class_rules[cm.group(1)] = css_class_rules.get(cm.group(1), "") + ";" + cm.group(2)

        def merged_clip_css(c: dict[str, Any]) -> str:
            return ";".join([css_class_rules.get(cls, "") for cls in c.get("classes", [])] + [c.get("style", "")])

        # 0. Check voice-track conditioning & 1000Hz compliance bleep verification
        vt_m = re.search(
            r'<section[^>]*id=["\']voice-track["\'][^>]*>(.*?)</section>',
            html_txt,
            flags=re.IGNORECASE | re.DOTALL,
        )
        voice_track_files: list[Path] = []
        voice_bleeps_by_file: dict[str, int] = {}
        if vt_m:
            unconditioned_vo: list[str] = []
            for vc in parse_audio_tags_in_section(vt_m.group(1)):
                vf = film_dir / vc["base_src"]
                if not vf.is_file():
                    continue
                voice_track_files.append(vf)
                v_probe = ffprobe_json(vf)
                v_comment = str(v_probe.get("format", {}).get("tags", {}).get("comment", "") or "")
                is_treated = v_comment.startswith("svp_voice_treated")
                if not is_treated:
                    unconditioned_vo.append(vf.name)
                else:
                    m_bl = re.search(r"bleeps=(\d+)", v_comment)
                    voice_bleeps_by_file[vf.name] = int(m_bl.group(1)) if m_bl else 0
            if unconditioned_vo:
                hard_failures.append(
                    f"人声未做前置母带润色：`voice-track` 未通过 `qc_video.py prepare-voice` 生成带 `svp_voice_treated` 元数据的润色母带({', '.join(dict.fromkeys(unconditioned_vo))})，严禁直接挂原始干声或仅改文件名绕过检查"
                )

            # Cross-check compliance-bleeps.json & masked subtitle tokens against actual audio bleep count
            total_applied_bleeps = sum(voice_bleeps_by_file.values())
            expected_bleep_hits = 0
            cand_bleep_dirs = [
                film_dir.parent / "materials",
                film_dir.parent.parent / "master-assets" / "clips",
                film_dir.parent.parent.parent / "master-assets" / "clips",
            ]
            vo_stems = [
                re.sub(r"-voice-treated$|-treated$", "", vf.stem, flags=re.I)
                for vf in voice_track_files
            ]
            for bdir in cand_bleep_dirs:
                if not bdir.is_dir():
                    continue
                for bf in sorted(bdir.glob("*compliance*bleep*.json")):
                    if vo_stems and bf.name != "compliance-bleeps.json":
                        if not any(st and bf.name.startswith(st) for st in vo_stems):
                            continue
                    try:
                        bj = json.loads(bf.read_text(encoding="utf-8"))
                        hc = int(bj.get("hit_count") or len(bj.get("bleeps") or []))
                        expected_bleep_hits = max(expected_bleep_hits, hc)
                    except Exception:
                        pass
            details["voice_bleeps_applied"] = total_applied_bleeps
            details["compliance_bleeps_expected"] = expected_bleep_hits
            if voice_track_files and expected_bleep_hits > 0 and total_applied_bleeps == 0:
                hard_failures.append(
                    f"人声敏感词漏做 1000Hz 哔声消音：`compliance-bleeps.json` 检出 {expected_bleep_hits} 处平台违规词，但 `voice-track` 音轨元数据 `bleeps=0`，必须运行 `qc_video.py prepare-voice --bleeps <compliance-bleeps.json>` 重新生成消音人声母带"
                )
            elif voice_track_files and total_applied_bleeps == 0 and parsed_cues_sync:
                masked_in_subs = [
                    m.group(0)
                    for _, _, ct_p in parsed_cues_sync
                    for m in MASKED_SENSITIVE_TOKEN_RE.finditer(ct_p)
                ]
                if masked_in_subs:
                    hard_failures.append(
                        f"人声敏感词疑似漏做 1000Hz 哔声消音：字幕已出现脱敏词({', '.join(dict.fromkeys(masked_in_subs[:4]))})，但 `voice-track` 音轨元数据 `bleeps=0`，必须传入 `--bleeps` 对原声同步做 1000Hz 哔声屏蔽"
                    )

        # 1. Inspect ALL BGM sections (closing id="bgm-tail" loophole)
        all_bgm_clips: list[dict[str, Any]] = []
        for bm in re.finditer(
            r'<section[^>]*id=["\']([^"\']*(?:bgm|music|bed)[^"\']*)["\'][^>]*>(.*?)</section>',
            html_txt,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            sec_clips = parse_audio_tags_in_section(bm.group(2))
            for sc in sec_clips:
                sc["section_id"] = bm.group(1)
            all_bgm_clips.extend(sec_clips)

        details["bgm_segments"] = len(all_bgm_clips)
        if len(all_bgm_clips) >= 2:
            missing_fade = [c["id"] for c in all_bgm_clips if not c.get("fade")]
            if missing_fade:
                hard_failures.append(
                    f"film.html 多段 BGM 拼接（共 {len(all_bgm_clips)} 段）存在未配置 fade 交叉淡化段({', '.join(missing_fade[:4])})，易产生硬切跳变"
                )

        bgm_reports: list[dict[str, Any]] = []
        has_bgm_bed_or_drop = len(all_bgm_clips) >= 2
        for bc in all_bgm_clips:
            bf = film_dir / bc["base_src"]
            if not bf.is_file():
                continue
            bn_low = bf.name.lower()
            b_probe = ffprobe_json(bf)
            comment_tag = str(b_probe.get("format", {}).get("tags", {}).get("comment", "") or "")
            is_bed = ("bgm-bed" in bn_low) or comment_tag.startswith("svp_bgm_bed:")
            if is_bed:
                has_bgm_bed_or_drop = True
            b_stats = cached_audio_stats(bf)
            raw_i = b_stats["integrated_lufs"]
            raw_lra = b_stats["lra_lu"]
            vol = max(1e-4, bc["volume"])
            eff_lufs = round(raw_i + 20.0 * math.log10(vol), 2) if raw_i is not None else None
            bgm_reports.append(
                {
                    "id": bc["id"],
                    "file": bf.name,
                    "is_bgm_bed": is_bed,
                    "volume": bc["volume"],
                    "raw_lufs": raw_i,
                    "raw_lra": raw_lra,
                    "effective_lufs": eff_lufs,
                }
            )
            if eff_lufs is not None and eff_lufs < -34.0:
                hard_failures.append(
                    f"BGM 蚊子哼缺陷：`{bf.name}` 混音等效响度仅 {eff_lufs} LUFS(< -34.0 LUFS)，手机外放完全听不见情绪铺底"
                )
            if not is_bed and eff_lufs is not None and eff_lufs > -19.5:
                hard_failures.append(
                    f"裸 BGM 过响掩蔽人声：`{bf.name}` 未做侧链闪避且等效响度达 {eff_lufs} LUFS(> -19.5 LUFS)"
                )
            if not is_bed and raw_lra is not None and raw_lra > 11.5:
                hard_failures.append(
                    f"高动态裸 BGM 违规：`{bf.name}` 原生 LRA={raw_lra} LU(> 11.5 LU) 且未经 `build-bgm-bed` 预稳压闪避，铺底必然忽隐忽现"
                )
            if style_slot == "v4" and re.search(
                r"hopeful|upbeat|happy|cheerful|ukulele|corporate-pop", bn_low
            ):
                hard_failures.append(
                    f"v4(G4老郑AI经营论·宽银幕电影独白流) 配乐情绪严重错配：深沉独白违规挂载轻快暖调曲目 `{bf.name}`"
                )
        if duration >= 32.0 and len(all_bgm_clips) == 1 and not has_bgm_bed_or_drop:
            hard_failures.append(
                f"长片({duration:.1f}s >= 32s) BGM 缺乏侧链闪避与抽空留白：仅挂单条裸 BGM `{all_bgm_clips[0]['base_src']}`，须运行 `qc_video.py build-bgm-bed` 构建自动闪避与 Silence Drop 铺底床"
            )
        if bgm_reports:
            details["bgm_checks"] = bgm_reports

        # 2. SFX Event-Cluster Density, Ghost SFX & Timbre Blacklist checks
        transient_sfx: list[dict[str, Any]] = []
        for sm in re.finditer(
            r'<section[^>]*id=["\']([^"\']*(?:sfx|foley|ambience)[^"\']*)["\'][^>]*>(.*?)</section>',
            html_txt,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            sec_id = sm.group(1)
            for ac in parse_audio_tags_in_section(sm.group(2)):
                ac["section_id"] = sec_id
                sf = film_dir / ac["base_src"]
                s_dur = ac["dur"]
                if s_dur is None and sf.is_file():
                    s_dur = float(ffprobe_json(sf).get("format", {}).get("duration", 0) or 0)
                ac["resolved_dur"] = s_dur or 0.5
                if "ambience" in sec_id.lower() or ac["resolved_dur"] >= 2.5:
                    continue
                transient_sfx.append(ac)

        transient_sfx.sort(key=lambda x: x["at"])
        clusters: list[list[dict[str, Any]]] = []
        for item in transient_sfx:
            if clusters and (item["at"] - clusters[-1][0]["at"]) <= 0.35:
                clusters[-1].append(item)
            else:
                clusters.append([item])

        details["sfx_tag_count"] = len(transient_sfx)
        details["sfx_event_clusters"] = len(clusters)
        if duration > 0 and len(clusters) > max(4, math.ceil(duration / 2.2)):
            warnings.append(
                f"音效事件簇密度偏高：共 {len(clusters)} 簇（平均每 {duration/len(clusters):.1f}s 一簇），注意留出人声呼吸空间"
            )

        ghost_sfx: list[str] = []
        blacklist_sfx: list[str] = []
        for item in transient_sfx:
            sf = film_dir / item["base_src"]
            sn_low = sf.name.lower()
            if style_slot in {"master", "v3", "v4"} and re.search(
                r"ui-pop|bubble|cartoon|boing|ding-dong|coin|game-jump", sn_low
            ):
                blacklist_sfx.append(f"{sf.name}@{item['at']:.2f}s")
            elif style_slot == "v2" and re.search(r"glitch|cyber|laser|sci-fi|modem", sn_low):
                blacklist_sfx.append(f"{sf.name}@{item['at']:.2f}s")
            elif style_slot == "v4" and re.search(r"tech-launch|ui-click|mouse-click|arcade", sn_low):
                blacklist_sfx.append(f"{sf.name}@{item['at']:.2f}s")

            if sf.is_file():
                s_stats = cached_audio_stats(sf)
                raw_i = s_stats["integrated_lufs"]
                raw_tp = s_stats["true_peak_dbtp"]
                raw_mean = s_stats.get("mean_volume_db")
                vol = max(1e-4, item["volume"])
                db_gain = 20.0 * math.log10(vol)
                eff_i = (raw_i + db_gain) if (raw_i is not None and raw_i > -69.0) else None
                eff_tp = (raw_tp + db_gain) if raw_tp is not None else None
                eff_mean = (raw_mean + db_gain) if raw_mean is not None else None
                is_ghost = (
                    (eff_i is not None and eff_i < -36.0 and (eff_tp is None or eff_tp < -26.0))
                    or (eff_i is None and eff_tp is not None and eff_tp < -28.0 and (eff_mean is None or eff_mean < -40.0))
                )
                if is_ghost:
                    lbl_metric = f"{eff_i:.1f} LUFS" if eff_i is not None else f"TP={eff_tp:.1f} dBTP"
                    ghost_sfx.append(f"{sf.name}@{item['at']:.2f}s(等效 {lbl_metric})")

        if ghost_sfx:
            hard_failures.append(
                f"幽灵静音音效缺陷：检测到混音后完全听不见的无效音效({', '.join(ghost_sfx[:5])})，请先跑 `normalize-sfx` 并配 0.14~0.45 合理音量"
            )
        if blacklist_sfx:
            hard_failures.append(
                f"音效音色与槽位气质严重违和 [{style_slot}]：违规使用黑名单音效({', '.join(dict.fromkeys(blacklist_sfx))})"
            )
        if style_slot == "v1" and duration >= 10.0:
            hook_sfx = [x for x in transient_sfx if 0.0 <= x["at"] <= 3.0]
            if not hook_sfx:
                hard_failures.append("v1(高冲快剪流) 黄金前 3 秒零钩子冲击音效，冷开听觉抓耳力不足")

        # 3. Parse visual tracks
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
        overlay_sec = re.search(
            r'<section[^>]*id=["\']overlays["\'][^>]*>(.*?)</section>',
            html_txt,
            flags=re.IGNORECASE | re.DOTALL,
        )
        main_clips = parse_clips_in_section(main_sec.group(1)) if main_sec else []
        pip_clips = parse_clips_in_section(pip_sec.group(1)) if pip_sec else []
        overlay_clips = parse_clips_in_section(overlay_sec.group(1)) if overlay_sec else []

        for cm in re.finditer(
            r'<section[^>]*id=["\'][^"\']*cutout[^"\']*["\'][^>]*>(.*?)</section>',
            html_txt,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            cutout_clips.extend(parse_clips_in_section(cm.group(1)))

        for sm in re.finditer(
            r'<section[^>]*id=["\'][^"\']*sticker[^"\']*["\'][^>]*>(.*?)</section>',
            html_txt,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            sticker_clips.extend(parse_clips_in_section(sm.group(1)))

        for tm in re.finditer(
            r'<section[^>]*id=["\'][^"\']*(?:transition|fx-trans)[^"\']*["\'][^>]*>(.*?)</section>',
            html_txt,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            fx_trans_clips.extend(parse_clips_in_section(tm.group(1)))

        aux_visual_clips: list[dict[str, Any]] = []
        triptych_clips: list[dict[str, Any]] = []
        known_sec_re = re.compile(
            r"^(?:main-stage|speaker-pip|overlays|subtitles|vignette-grade|paper-backdrop|voice-track|.*cutout.*|.*sticker.*|.*transition.*|.*fx-trans.*|.*bgm.*|.*music.*|.*bed.*|.*sfx.*|.*foley.*|.*ambience.*)$",
            flags=re.IGNORECASE,
        )
        for ax_m in re.finditer(
            r'<section[^>]*id=["\']([^"\']+)["\'][^>]*>(.*?)</section>',
            html_txt,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            ax_id = ax_m.group(1)
            if known_sec_re.match(ax_id):
                continue
            ax_parsed = parse_clips_in_section(ax_m.group(2))
            for ax_c in ax_parsed:
                ax_c["section_id"] = ax_id
            aux_visual_clips.extend(ax_parsed)
            if "triptych" in ax_id.lower():
                triptych_clips.extend(ax_parsed)

        # Identify speaker source video basenames
        all_video_refs = re.findall(
            r'<video\b[^>]*src=["\']([^"\']+\.(?:mp4|mov|webm|mkv))(?:#[^"\']*)?["\']',
            html_txt,
            flags=re.IGNORECASE,
        )
        vid_freq_early: dict[str, int] = {}
        for vr in all_video_refs:
            bn = Path(vr).name.lower()
            vid_freq_early[bn] = vid_freq_early.get(bn, 0) + 1
        if vid_freq_early:
            dom_bn = max(vid_freq_early, key=vid_freq_early.get)
            if vid_freq_early[dom_bn] >= 2 or SPEAKER_VID_NAME_RE.search(dom_bn):
                speaker_vids_early.add(dom_bn)
        for c in pip_clips + cutout_clips:
            if c["tag"] == "video":
                speaker_vids_early.add(Path(c["base_src"]).name.lower())

        def is_speaker_vid_clip(c: dict[str, Any]) -> bool:
            if c["tag"] != "video":
                return False
            bn = Path(c["base_src"]).name.lower()
            return bn in speaker_vids_early or bool(SPEAKER_VID_NAME_RE.search(bn))

        # 3b. Optical Color Grading (--of-lut) check on speaker <video> clips (including auxiliary tracks)
        all_speaker_clips = [
            c for c in (main_clips + pip_clips + cutout_clips + aux_visual_clips) if is_speaker_vid_clip(c)
        ]
        if all_speaker_clips:
            ungraded_ids: list[str] = []
            missing_lut_files: list[str] = []
            used_luts: set[str] = set()
            for sc in all_speaker_clips:
                m_css = merged_clip_css(sc)
                lm = re.search(r"--of-lut\s*:\s*url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", m_css, re.I)
                if not lm:
                    ungraded_ids.append(sc["id"])
                else:
                    lut_rel = lm.group(1).strip()
                    used_luts.add(Path(lut_rel).name)
                    if not (film_dir / lut_rel).is_file():
                        missing_lut_files.append(lut_rel)
            details["color_luts_used"] = sorted(used_luts)
            if ungraded_ids:
                hard_failures.append(
                    f"光学调色缺失：共 {len(ungraded_ids)}/{len(all_speaker_clips)} 段出镜 `<video>`(如 `{ungraded_ids[0]}`) 未挂载 `--of-lut: url(looks/*.cube)`，原片灰平直出无商业调色质感"
                )
            if missing_lut_files:
                hard_failures.append(
                    f"LUT 文件缺失：`--of-lut` 引用的调色文件不存在({', '.join(sorted(set(missing_lut_files)))})"
                )

            # 3b-2. Fullscreen / Zoomed Speaker Horizontal Centering Gate (prevents face drifting into x>930px)
            decl_cx = _load_declared_face_cx(film_dir)
            offcenter_faces: list[str] = []
            speaker_focus_reports: list[dict[str, Any]] = []
            for mc in main_clips:
                if not is_speaker_vid_clip(mc):
                    continue
                vf_sp = film_dir / mc["base_src"]
                sp_ar = 16.0 / 9.0
                sp_span_v = 0.38
                eff_cx = decl_cx
                if vf_sp.is_file():
                    focus_meta = probe_speaker_horizontal_focus(vf_sp, samples=4)
                    sp_ar = float(focus_meta.get("aspect_ratio") or sp_ar)
                    sp_span_v = float(focus_meta.get("span_v") or sp_span_v)
                    if eff_cx is None:
                        eff_cx = float(focus_meta.get("face_cx_pct") or 50.0)
                if eff_cx is None:
                    eff_cx = 50.0

                m_css = merged_clip_css(mc)
                box_l = parse_css_px(m_css, "left", 0.0) or 0.0
                box_w = parse_css_px(m_css, "width", 1080.0) or 1080.0
                box_h = parse_css_px(m_css, "height", 1920.0) or 1920.0
                it_s, ir_s, ib_s, il_s = resolve_pip_steady_inset(m_css, keyframes_map, box_w, box_h)
                vis_w_s = box_w - il_s - ir_s
                if vis_w_s < 860.0:
                    continue  # Side-column / PiP cropped window, not fullscreen L1 speaker

                pos_m_s = re.search(
                    r"object-position\s*:\s*(-?\d+(?:\.\d+)?)%\s+(-?\d+(?:\.\d+)?)%",
                    m_css,
                    flags=re.IGNORECASE,
                )
                pos_x_s = float(pos_m_s.group(1)) if pos_m_s else 50.0
                if (box_w / max(1.0, box_h)) >= sp_ar:
                    rw_s = box_w
                    ox_s = 0.0
                else:
                    rw_s = box_h * sp_ar
                    ox_s = (rw_s - box_w) * (pos_x_s / 100.0)

                x_unscaled = box_l + ((eff_cx / 100.0) * rw_s - ox_s)
                tx_px = 0.0
                tx_m = re.search(r"translateX\(\s*(-?\d+(?:\.\d+)?)px\s*\)", m_css, flags=re.I)
                if tx_m:
                    tx_px += float(tx_m.group(1))
                tx_pct_m = re.search(r"translateX\(\s*(-?\d+(?:\.\d+)?)%\s*\)", m_css, flags=re.I)
                if tx_pct_m:
                    tx_px += box_w * (float(tx_pct_m.group(1)) / 100.0)
                tr2_m = re.search(r"(?<![A-Za-z-])translate\s*:\s*(-?\d+(?:\.\d+)?)px", m_css, flags=re.I)
                if tr2_m:
                    tx_px += float(tr2_m.group(1))

                ax_px = parse_css_px(m_css, "--fx-ax", 0.0) or 0.0
                max_sc_s = resolve_max_scale_in_css(m_css, keyframes_map)
                pivot_x = box_l + box_w * 0.5 + ax_px
                face_x_canvas = pivot_x + ((x_unscaled + tx_px) - pivot_x) * max_sc_s
                head_half_w = max(145.0, min(250.0, sp_span_v * box_h * 0.17 * max_sc_s))
                face_right_x = face_x_canvas + head_half_w
                face_left_x = face_x_canvas - head_half_w
                speaker_focus_reports.append(
                    {
                        "id": mc["id"],
                        "at": mc["at"],
                        "face_cx_pct": round(eff_cx, 1),
                        "object_pos_x_pct": round(pos_x_s, 1),
                        "max_scale": round(max_sc_s, 3),
                        "face_x_canvas_px": round(face_x_canvas, 1),
                        "face_span_x_px": [round(face_left_x), round(face_right_x)],
                    }
                )
                if face_x_canvas > 650.0 or face_right_x > 915.0 or face_x_canvas < 320.0 or face_left_x < 60.0:
                    offcenter_faces.append(
                        f"{mc['id']}@{mc['at']:.1f}s(脸心 x={face_x_canvas:.0f}px, 右缘 x={face_right_x:.0f}px, object-position-x={pos_x_s:.0f}%, scale={max_sc_s:.2f})"
                    )
            if speaker_focus_reports:
                details["speaker_horizontal_focus"] = speaker_focus_reports
            if offcenter_faces:
                hard_failures.append(
                    f"主讲人近景水平跑偏出框：{', '.join(offcenter_faces[:4])} —— 人脸中心偏离安全居中带(脸心 x=320..650px 且右缘 <=915px)，易导致半张脸/眼镜撞入右侧点赞禁区(x>930px)或左缘裁切！请按 `probe-speaker-focus` 输出的 `recommended_object_position` 对齐居中"
                )

        # 3c. Main-stage pacing, effective shot merger, mid-sentence fake jump-cut & S04 topology craft
        if main_clips:
            main_clips.sort(key=lambda c: c["at"])
            shot_count = len(main_clips)

            def _clip_vis_height(mc_item: dict[str, Any]) -> float:
                m_css_v = merged_clip_css(mc_item)
                bw_v = parse_css_px(m_css_v, "width", 1080.0) or 1080.0
                bh_v = parse_css_px(m_css_v, "height", 1920.0) or 1920.0
                it_v, _, ib_v, _ = resolve_pip_steady_inset(m_css_v, keyframes_map, bw_v, bh_v)
                return max(1.0, bh_v - it_v - ib_v)

            # Merge contiguous same-source speaker clips with near-identical framing/scale (anti-fake-shot gaming)
            effective_shots: list[dict[str, Any]] = []
            for mc_it in main_clips:
                mc_dur = mc_it["dur"] if mc_it["dur"] is not None else max(0.0, (mc_it["end"] or duration) - mc_it["at"])
                mc_vh = _clip_vis_height(mc_it)
                mc_sc = resolve_max_scale_in_css(merged_clip_css(mc_it), keyframes_map)
                if (
                    effective_shots
                    and is_speaker_vid_clip(effective_shots[-1]["last_clip"])
                    and is_speaker_vid_clip(mc_it)
                    and effective_shots[-1]["last_clip"]["base_src"] == mc_it["base_src"]
                    and effective_shots[-1]["last_clip"]["t_out"] is not None
                    and mc_it["t_in"] is not None
                    and abs(mc_it["t_in"] - effective_shots[-1]["last_clip"]["t_out"]) < 0.12
                    and abs(mc_vh - effective_shots[-1]["vis_h"]) < 120.0
                    and abs(mc_sc - effective_shots[-1]["max_sc"]) < 0.05
                ):
                    effective_shots[-1]["dur"] += mc_dur
                    effective_shots[-1]["end"] = mc_it["end"] or (mc_it["at"] + mc_dur)
                    effective_shots[-1]["last_clip"] = mc_it
                else:
                    effective_shots.append(
                        {
                            "id": mc_it["id"],
                            "at": mc_it["at"],
                            "dur": mc_dur,
                            "end": mc_it["end"] or (mc_it["at"] + mc_dur),
                            "vis_h": mc_vh,
                            "max_sc": mc_sc,
                            "first_clip": mc_it,
                            "last_clip": mc_it,
                        }
                    )

            eff_shot_count = len(effective_shots)
            asl = duration / eff_shot_count if eff_shot_count > 0 else 0.0
            max_shot = max((s["dur"] or 0.0) for s in effective_shots) if effective_shots else 0.0
            speaker_eff_shots = [s for s in effective_shots if is_speaker_vid_clip(s["first_clip"])]
            max_spk_shot = max((s["dur"] or 0.0) for s in speaker_eff_shots) if speaker_eff_shots else 0.0
            details["main_stage_shots"] = shot_count
            details["effective_shots"] = eff_shot_count
            details["asl_sec"] = round(asl, 2)
            details["max_shot_sec"] = round(max_shot, 2)
            details["max_speaker_shot_sec"] = round(max_spk_shot, 2)
            cut_points = [c["at"] for c in main_clips[1:] if c["at"] > 0]

            asl_limit = STYLE_ASL_THRESHOLDS.get(style_slot, 7.0)
            if asl > asl_limit:
                hard_failures.append(
                    f"剪辑节奏过慢：有效镜数 {eff_shot_count} 镜(原始 {shot_count} 镜)，有效 ASL={asl:.2f}s > {style_slot} 硬上限 {asl_limit:.1f}s（最长有效单镜 {max_shot:.2f}s）"
                )
            max_spk_limit = STYLE_MAX_SPEAKER_SHOT_SEC.get(style_slot, 8.5)
            if max_spk_shot > max_spk_limit:
                hard_failures.append(
                    f"单镜口播拖沓超限 [{style_slot}]：最长连续同景别口播达 {max_spk_shot:.2f}s(> {max_spk_limit:.1f}s 硬上限)，须插入 B-roll/动态视觉舞台或做 >=1.12x 阶梯景别切换"
                )
            if style_slot == "v4":
                if max_shot > 6.5:
                    hard_failures.append(
                        f"v4(S04 竖屏银幕散文电影) 单镜时长超限：最长有效镜头 {max_shot:.2f}s > 6.5s 硬上限"
                    )
                if duration >= 30.0 and eff_shot_count < 8:
                    hard_failures.append(
                        f"v4(S04 竖屏银幕散文电影) 镜头密度不足：全长 {duration:.1f}s 仅 {eff_shot_count} 个有效镜头(< 8 镜下限)"
                    )

            fake_mid_cuts: list[str] = []
            unmasked_jump_cuts: list[str] = []
            for prev_c, next_c in zip(main_clips, main_clips[1:]):
                if is_speaker_vid_clip(prev_c) and is_speaker_vid_clip(next_c):
                    # Continuous same-anim scale snap-back
                    if (
                        prev_c["base_src"] == next_c["base_src"]
                        and prev_c["t_out"] is not None
                        and next_c["t_in"] is not None
                        and abs(prev_c["t_out"] - next_c["t_in"]) < 0.05
                        and prev_c["anim"]
                        and prev_c["anim"] == next_c["anim"]
                    ):
                        hard_failures.append(
                            f"连续同机位视频 `{prev_c['id']}` -> `{next_c['id']}` 在 {next_c['at']:.2f}s 切分并复用同一动画 `{prev_c['anim']}`，造成缩放倒退回弹穿帮"
                        )

                    # Mid-sentence fake jump-cut check
                    cut_t = next_c["at"]
                    if len(parsed_cues_sync) >= 3:
                        mid_cue = next(
                            (
                                c
                                for c in parsed_cues_sync
                                if (c[0] + 0.28) < cut_t < (c[1] - 0.28)
                            ),
                            None,
                        )
                        if mid_cue is not None:
                            fake_mid_cuts.append(f"{cut_t:.2f}s(切碎台词「{mid_cue[2][:12]}」)")

                    # Non-contiguous speaker jump-cut without transition or >=10% step zoom
                    if (
                        prev_c["base_src"] == next_c["base_src"]
                        and prev_c["t_out"] is not None
                        and next_c["t_in"] is not None
                        and abs(next_c["t_in"] - prev_c["t_out"]) > 0.12
                    ):
                        has_tr_cover = any(
                            tc["at"] <= cut_t + 0.08 and (tc["end"] or (tc["at"] + 0.4)) >= cut_t - 0.08
                            for tc in fx_trans_clips
                        )
                        sc1 = resolve_max_scale_in_css(merged_clip_css(prev_c), keyframes_map)
                        sc2 = resolve_max_scale_in_css(merged_clip_css(next_c), keyframes_map)
                        if not has_tr_cover and abs(sc2 - sc1) < 0.10:
                            unmasked_jump_cuts.append(
                                f"{cut_t:.2f}s(源片跳变 {prev_c['t_out']:.2f}s->{next_c['t_in']:.2f}s)"
                            )

            if fake_mid_cuts:
                hard_failures.append(
                    f"句中假跳切违规：在完整句子中途硬切口播视频伪造快节奏({', '.join(fake_mid_cuts[:4])})，切点必须严格落在句界气口处"
                )
            if unmasked_jump_cuts:
                hard_failures.append(
                    f"同机位删句硬蹦脸违规：非连续跳切点未加 B-roll 遮切(JL3)、视觉转场或 >=1.12x 阶梯景别差({', '.join(unmasked_jump_cuts[:4])})"
                )

            # Topology sequence, anti-monotony run & S04 (v4) multi-topology essay-film gates
            shot_topologies: list[tuple[str, str, float]] = []
            l6_total_sec = 0.0
            l6_speaker_sec = 0.0
            consec_l6: list[str] = []
            for mc_it in main_clips:
                mc_s = mc_it["at"]
                mc_e = mc_it["end"] if mc_it["end"] is not None else min(duration, mc_s + (mc_it["dur"] or 3.0))
                mc_d = max(0.0, mc_e - mc_s)
                if re.search(r"(?:outro|ending)", Path(mc_it["base_src"]).name, re.I):
                    continue
                has_trip = any(
                    tc["at"] < mc_e - 0.15 and (tc["end"] or (tc["at"] + 3.0)) > mc_s + 0.15
                    for tc in triptych_clips
                )
                has_cut = any(
                    cc["at"] < mc_e - 0.15 and (cc["end"] or (cc["at"] + 3.0)) > mc_s + 0.15
                    for cc in cutout_clips
                ) or (
                    mc_it["tag"] == "video" and bool(re.search(r"--of-cutout\s*:\s*1\b", merged_clip_css(mc_it)))
                )
                if has_trip:
                    topo = "L4_TRIPTYCH"
                elif has_cut:
                    topo = "PF3_CUTOUT"
                elif mc_it["tag"] == "iframe":
                    sf_n = Path(mc_it["base_src"]).name.lower()
                    topo = "L4_TRIPTYCH" if "triptych" in sf_n else "L5_STAGE"
                else:
                    vh_cur = _clip_vis_height(mc_it)
                    if vh_cur <= 620.0:
                        topo = "L6_LETTERBOX"
                        l6_total_sec += mc_d
                        if is_speaker_vid_clip(mc_it):
                            l6_speaker_sec += mc_d
                    elif vh_cur <= 1280.0:
                        topo = "L3_SPLIT"
                    else:
                        topo = "L1_FULL_SPEAKER" if is_speaker_vid_clip(mc_it) else "L1_FULL_BROLL"
                if topo == "L6_LETTERBOX" and shot_topologies and shot_topologies[-1][1] == "L6_LETTERBOX":
                    consec_l6.append(f"{shot_topologies[-1][0]}->{mc_it['id']}@{mc_s:.1f}s")
                shot_topologies.append((mc_it["id"], topo, round(mc_d, 2)))

            distinct_topos = sorted({tp for _, tp, _ in shot_topologies})
            details["shot_topologies"] = {
                "sequence": shot_topologies,
                "distinct": distinct_topos,
                "l6_ratio": round(l6_total_sec / max(1.0, duration), 3),
                "l6_speaker_sec": round(l6_speaker_sec, 2),
            }

            # Check vignette-grade for full-film static black letterbox masks (>8.0s)
            vig_m = re.search(r'<section[^>]*id=["\']vignette-grade["\'][^>]*>(.*?)</section>', html_txt, re.I | re.S)
            if vig_m:
                for vc_it in parse_clips_in_section(vig_m.group(1)):
                    vc_d = vc_it["dur"] or ((vc_it["end"] or duration) - vc_it["at"])
                    if vc_d > 8.0 and vc_it["tag"] == "iframe":
                        vp_f = film_dir / vc_it["base_src"]
                        if vp_f.is_file():
                            vp_txt = vp_f.read_text(encoding="utf-8", errors="replace")
                            if "letterbox" in vp_f.name.lower() or re.search(
                                r"height\s*:\s*(?:3[89]\d|[4-9]\d\d)px[^}]*background(?:-color)?\s*:\s*#0[0-9a-fA-F]{5}",
                                vp_txt,
                                re.I,
                            ):
                                hard_failures.append(
                                    f"严禁跨镜常驻死黑遮幅框：`vignette-grade` 挂载 `{vp_f.name}` 长达 {vc_d:.1f}s(>8.0s)，把竖屏永久焊死成上下死黑窄条！宽银幕 `L6` 仅限单镜按需使用"
                                )

            if style_slot == "v4" and duration >= 24.0:
                if len(distinct_topos) < 3:
                    hard_failures.append(
                        f"v4(S04 竖屏银幕散文电影) 构图单一简陋：全片仅使用 {len(distinct_topos)} 种构图({distinct_topos})，必须组合 >=3 种空间构图(L1/PF3满屏浅景深 + L4三轨胶片三联画 + L5纯Canvas暗金光影隐喻场 + L6动态遮幅)"
                    )
                if "L4_TRIPTYCH" not in distinct_topos:
                    hard_failures.append(
                        "v4(S04 竖屏银幕散文电影) 缺失标志性 `L4` 三联画胶片格构图：全片必须包含 >=1 幕三格同步胶片三联画(如 triptych-top / main-stage / triptych-bot 三轨并置)"
                    )
                if duration >= 30.0 and "PF3_CUTOUT" not in distinct_topos:
                    hard_failures.append(
                        "v4(S04 竖屏银幕散文电影) 缺失 `PF3` 同源虚化底光学浅景深人像高潮镜"
                    )
                if duration >= 30.0 and "L5_STAGE" not in distinct_topos:
                    hard_failures.append(
                        "v4(S04 竖屏银幕散文电影) 缺失 `L5-LightField` 黑曜石纯 `<canvas>` 空间光影隐喻动效镜：严禁全片仅靠窄条视频加小字充数"
                    )
                if (l6_total_sec / max(1.0, duration)) > 0.32:
                    hard_failures.append(
                        f"v4(S04) `2.39:1` 单窄遮幅占比过高：{l6_total_sec:.1f}s/{duration:.1f}s = {l6_total_sec/duration:.0%}(> 32% 硬上限)，必须释放竖屏空间给满幅浅景深、三联画与光影场"
                    )
                if consec_l6:
                    hard_failures.append(
                        f"v4(S04) 违规连续使用单窄遮幅 `L6`({', '.join(consec_l6[:3])})：相邻两镜严禁连挂窄条黑边"
                    )
                if l6_speaker_sec > 4.5:
                    hard_failures.append(
                        f"v4(S04) 违规把常规口播长期关进 `452px` 窄条黑缝(累计 {l6_speaker_sec:.1f}s > 4.5s)：主讲人独白请改用 `L1` 满屏暗角或 `L4` 三联画中格特写"
                    )

        # Cross-track double-head overlap & atomic speaker-pip sync gates
        if pip_clips and main_clips:
            fs_speaker_videos = [c for c in main_clips if is_speaker_vid_clip(c)]
            non_spk_iframes = sorted(
                [
                    c
                    for c in main_clips
                    if c["tag"] == "iframe" and not re.search(r"(?:outro|ending)", Path(c["base_src"]).name, re.I)
                ],
                key=lambda x: x["at"],
            )
            # Merge contiguous main-stage non-speaker iframes into continuous host chains
            host_chains: list[tuple[float, float, list[dict[str, Any]]]] = []
            for ic in non_spk_iframes:
                ic_s = ic["at"]
                ic_e = ic["end"] if ic["end"] is not None else min(duration, ic_s + (ic["dur"] or 4.0))
                if host_chains and abs(ic_s - host_chains[-1][1]) <= 0.06:
                    host_chains[-1] = (host_chains[-1][0], ic_e, [*host_chains[-1][2], ic])
                else:
                    host_chains.append((ic_s, ic_e, [ic]))

            for pc in pip_clips:
                pc_end_chk = pc["end"] if pc["end"] is not None else min(duration, pc["at"] + 4.0)
                if pc.get("fade_in", 0.0) > 0.005 or pc.get("fade_out", 0.0) > 0.005:
                    hard_failures.append(
                        f"speaker-pip 原子同步违规：`{pc['id']}` (at={pc['at']:.2f}s) 挂载了独立 `fade=[{pc.get('fade_in',0):.2f},{pc.get('fade_out',0):.2f}]`，必然造成人物头像先于白板页面提前消失或滞后浮现！请删掉 speaker-pip 的 `overrides` `fade`，跨场叠化统一由顶层 `fx-transitions` 整幅同步控制"
                    )
                for fv in fs_speaker_videos:
                    fv_end = fv["end"] if fv["end"] is not None else duration
                    ov_sec = min(pc_end_chk, fv_end) - max(pc["at"], fv["at"])
                    if ov_sec > 1e-4:
                        hard_failures.append(
                            f"跨轨双头叠影穿帮：上轨 `{pc['id']}` [{pc['at']:.3f}s, {pc_end_chk:.3f}s) 与下轨同主体口播 `{fv['id']}` [{fv['at']:.3f}s, {fv_end:.3f}s) 真实重叠 {ov_sec*1000:.1f}ms，请将上轨结束时间精确设为 `{fv['at'] - 0.001:.3f}s`（切点减 1ms 消除浮点尾差，严禁提前 >=0.1s 收口留空框）"
                        )

                # Host-scene atomic start/end lock check (<= 0.030s tolerance)
                matched_chain = next(
                    (
                        ch
                        for ch in host_chains
                        if min(pc_end_chk, ch[1]) - max(pc["at"], ch[0]) > 0.15
                    ),
                    None,
                )
                if matched_chain is None:
                    hard_failures.append(
                        f"speaker-pip 无效悬空：`{pc['id']}` [{pc['at']:.2f}s..{pc_end_chk:.2f}s] 未对齐任何底层 `main-stage` 图解/白板场景"
                    )
                else:
                    ch_s, ch_e, ch_clips = matched_chain
                    # Allow matching either the full contiguous host chain OR an exact contiguous sub-slice of scenes in the chain
                    valid_starts = [ch_s] + [sc_i["at"] for sc_i in ch_clips]
                    valid_ends = [ch_e] + [
                        (sc_i["end"] if sc_i["end"] is not None else ch_e) for sc_i in ch_clips
                    ]
                    ds_min = min(abs(pc["at"] - vs) for vs in valid_starts)
                    de_min = min(abs(pc_end_chk - ve) for ve in valid_ends)
                    if ds_min > 0.030 or de_min > 0.030:
                        hard_failures.append(
                            f"speaker-pip 起止脱节早退/晚出：`{pc['id']}` [{pc['at']:.3f}s, {pc_end_chk:.3f}s) 与底层宿主场景边界(起点候选 {[round(v,2) for v in valid_starts]}, 终点候选 {[round(v,2) for v in valid_ends]}) 偏差 Δstart={ds_min:.3f}s / Δend={de_min:.3f}s (> 0.030s)！挂件必须与宿主页面 100% 同帧进退(连续白板页建议一条连续 `<video>` 贯通，切出点填 `host_end - 0.001`)"
                        )

        # 4. Speaker-PiP framing checks
        pip_heights: set[int] = set()
        pip_reports: list[dict[str, Any]] = []
        src_ar_cache: dict[str, float] = {}
        for pc in pip_clips:
            pc_end = pc["end"] if pc["end"] is not None else min(duration, pc["at"] + 4.0)
            for pt_cand in (pc["at"] + 0.05, (pc["at"] + pc_end) * 0.5, pc_end - 0.05):
                if 0.05 < pt_cand < (duration - 0.05):
                    pip_points.append(round(pt_cand, 2))
            merged_pip_css = merged_clip_css(pc)
            box_l = parse_css_px(merged_pip_css, "left", 0.0) or 0.0
            box_t = parse_css_px(merged_pip_css, "top", 0.0) or 0.0
            box_w = parse_css_px(merged_pip_css, "width", 1080.0) or 1080.0
            box_h = parse_css_px(merged_pip_css, "height", 1920.0) or 1920.0
            ins_t, ins_r, ins_b, ins_l = resolve_pip_steady_inset(merged_pip_css, keyframes_map, box_w, box_h)
            vis_l = box_l + ins_l
            vis_t = box_t + ins_t
            vis_w = max(1.0, box_w - ins_l - ins_r)
            vis_h = max(1.0, box_h - ins_t - ins_b)
            pip_heights.add(int(round(vis_h)))

            src_rel = pc["base_src"]
            if src_rel not in src_ar_cache:
                src_file = film_dir / src_rel
                ar_val = 16.0 / 9.0
                if src_file.is_file():
                    try:
                        sp_info = ffprobe_json(src_file)
                        vs = next(
                            (s for s in sp_info.get("streams", []) if s.get("codec_type") == "video"),
                            None,
                        )
                        if vs and int(vs.get("height", 0)) > 0:
                            ar_val = int(vs["width"]) / int(vs["height"])
                    except Exception:
                        pass
                src_ar_cache[src_rel] = ar_val
            src_ar = src_ar_cache[src_rel]

            pos_m = re.search(
                r"object-position\s*:\s*(\d+(?:\.\d+)?)%\s+(\d+(?:\.\d+)?)%",
                merged_pip_css,
                flags=re.IGNORECASE,
            )
            pos_x = float(pos_m.group(1)) if pos_m else 50.0
            pos_y = float(pos_m.group(2)) if pos_m else 50.0
            if (box_w / box_h) >= src_ar:
                rw, rh = box_w, box_w / src_ar
                ox, oy = 0.0, (rh - box_h) * (pos_y / 100.0)
            else:
                rh, rw = box_h, box_h * src_ar
                ox, oy = (rw - box_w) * (pos_x / 100.0), 0.0

            u1 = max(0.0, min(1.0, (ox + ins_l) / max(1.0, rw)))
            u2 = max(0.0, min(1.0, (ox + box_w - ins_r) / max(1.0, rw)))
            v1 = max(0.0, min(1.0, (oy + ins_t) / max(1.0, rh)))
            v2 = max(0.0, min(1.0, (oy + box_h - ins_b) / max(1.0, rh)))

            pip_issues: list[str] = []
            if v2 < 0.72:
                pip_issues.append(f"纵向底部裁切过重(v2={v2:.1%} < 72%)，严重截断嘴巴/下巴")
            if v1 > 0.22:
                pip_issues.append(f"纵向顶部裁切过重(v1={v1:.1%} > 22%)，削发顶风险")
            if vis_h < 320.0 and not (style_slot == "v2" and vis_w <= 260.0):
                pip_issues.append(f"可见窗口净高过矮({vis_h:.0f}px < 320px)")

            for mc in main_clips:
                if mc["tag"] != "iframe":
                    continue
                mc_end = mc["end"] if mc["end"] is not None else duration
                if mc["at"] < pc_end - 0.05 and mc_end > pc["at"] + 0.05:
                    sf_path = film_dir / mc["base_src"]
                    if sf_path.is_file():
                        sf_txt = sf_path.read_text(encoding="utf-8", errors="replace")
                        sf_body = sf_txt[sf_txt.lower().find("<body") :] if "<body" in sf_txt.lower() else sf_txt
                        orphan_shell_m = re.search(
                            r'class=["\'][^"\']*\b(badge-ring|pip-ring|pip-frame|avatar-ring|pip-border|speaker-ring)\b',
                            sf_body,
                            flags=re.IGNORECASE,
                        )
                        if orphan_shell_m:
                            pip_issues.append(
                                f"底层 `{sf_path.name}` 违规绘制静态外框 `.{orphan_shell_m.group(1)}`(运镜平移必框人分离且切场易留空圈)，边框/圆角/投影必须 100% 写在 `film.html` 的 `<video>` 自身上"
                            )

            if (vis_w / vis_h) > 1.85 and u2 > 0.64 and "wide_pip_warned" not in details:
                details["wide_pip_warned"] = True
                warnings.append(
                    f"speaker-pip `{pc['id']}` 宽高比 {vis_w/vis_h:.2f} > 1.85 且保留右侧 u2={u2:.1%}(>64%)，易漏杂墙"
                )

            if pip_issues:
                hard_failures.append(
                    f"speaker-pip `{pc['id']}` (at={pc['at']:.2f}s) 违反五官完整保留硬规：{'；'.join(pip_issues)}"
                )
            pip_reports.append(
                {
                    "id": pc["id"],
                    "at": pc["at"],
                    "visible_box": [round(vis_l), round(vis_t), round(vis_w), round(vis_h)],
                    "source_uv": [round(u1, 3), round(u2, 3), round(v1, 3), round(v2, 3)],
                    "violations": pip_issues,
                }
            )
        if pip_reports:
            details["pip_framing_checks"] = pip_reports
        if len(pip_heights) >= 3:
            warnings.append(f"PiP 可见窗口出现 {len(pip_heights)} 种不同高度 ({sorted(pip_heights)}px)")

        # 4b. Cutout optical homologous bed, shoulder width & behind-person occlusion checks
        # Also catch any main-stage <video> carrying --of-cutout: 1 directly!
        extra_main_cutouts = [
            mc
            for mc in main_clips
            if mc["tag"] == "video" and re.search(r"--of-cutout\s*:\s*1\b", merged_clip_css(mc))
        ]
        all_cutout_vids = cutout_clips + extra_main_cutouts
        cutout_reports: list[dict[str, Any]] = []
        cutout_meta: list[dict[str, Any]] = []
        for cc in all_cutout_vids:
            merged_css = merged_clip_css(cc)
            top_px = parse_css_px(merged_css, "top", 0.0)
            width_px = parse_css_px(merged_css, "width", 1080.0)
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
                    "width_px": width_px,
                    "height_px": height_px,
                    "is_unlowered": is_unlowered,
                }
            )

            if width_px is not None and width_px < 1040.0:
                hard_failures.append(
                    f"前景抠像断肩缺陷：`{cc['id']}` (at={cc['at']:.2f}s) 容器宽度仅 {width_px:.0f}px(< 1080px 标准)，导致人物双肩在半空被硬生生斩断"
                )

            # Check whether overlapping main-stage has an optical <video> bed behind cutout
            has_video_bed_behind = False
            for mc in main_clips:
                if mc is cc:
                    continue
                mc_end = mc["end"] if mc["end"] is not None else duration
                if mc["at"] < cc_end - 0.05 and mc_end > cc["at"] + 0.05:
                    if mc["tag"] == "video":
                        has_video_bed_behind = True
                    elif mc["tag"] == "iframe":
                        scene_info = inspect_behind_person_scene(film_dir / mc["base_src"])
                        if scene_info["has_video_tag"]:
                            has_video_bed_behind = True
                        reasons: list[str] = []
                        if scene_info["has_behind_text"]:
                            if is_unlowered:
                                sample = " / ".join(
                                    x["text"] for x in (scene_info["svg_texts"] + scene_info["html_texts"])[:3]
                                )
                                reasons.append(f"未缩小下沉特写遮挡人后文字「{sample}」")
                            if scene_info["too_low_texts"]:
                                reasons.append("人后文字低于 y=540px")
                            if scene_info["long_texts"] or scene_info["behind_text_count"] >= 2:
                                reasons.append(f"人后出现多行或长句({scene_info['behind_text_count']}行)")
                        cutout_reports.append(
                            {
                                "cutout_id": cc["id"],
                                "at": cc["at"],
                                "behind_scene": scene_info["scene"],
                                "violations": reasons,
                            }
                        )
                        if reasons:
                            hard_failures.append(
                                f"前景抠像 `{cc['id']}` (at={cc['at']:.2f}s) 与人后场景 `{scene_info['scene']}` 违反防遮挡硬规：{'；'.join(reasons)}"
                            )
            if not has_video_bed_behind:
                hard_failures.append(
                    f"裸抠像绿边光晕缺陷：`{cc['id']}` (at={cc['at']:.2f}s) 开启 `--of-cutout: 1` 但底层 main-stage 未垫同源虚化 `<video>` 光学背景(仅纯 CSS 渐变/空底)，必然产生发丝溢绿与纸片贴图感"
                )
        if cutout_reports:
            details["cutout_layer_checks"] = cutout_reports

        # 4c. Stickers checks (commercial slot ban + head/right-zone avoidance)
        if sticker_clips and style_slot in {"master", "v2", "v3", "v4"}:
            hard_failures.append(
                f"商业视觉纯净度违规：`{style_slot}` 槽位严禁挂载动态贴纸(共 {len(sticker_clips)} 枚)，贴纸仅限高冲网感/轻量科普风点缀"
            )

        sticker_reports: list[dict[str, Any]] = []
        for sc in sticker_clips:
            st = merged_clip_css(sc)
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
                "status": "ok",
            }
            if x2 > 920.0 and y2 > 850.0 and y1 < 1500.0:
                stk_rec["status"] = "right_zone_violation"
                hard_failures.append(
                    f"stickers `{sc['id']}` (at={sc['at']:.2f}s) 侵入右侧平台按钮禁区(x>920, y=850..1500)"
                )
            active_unlowered = any(
                cm["clip"]["at"] < sc_end - 0.05 and cm["end"] > sc["at"] + 0.05 and cm["is_unlowered"]
                for cm in cutout_meta
            ) or any(
                is_speaker_vid_clip(mc)
                and mc["at"] < sc_end - 0.05
                and (mc["end"] or duration) > sc["at"] + 0.05
                for mc in main_clips
            )
            if active_unlowered and 220.0 <= cx <= 860.0 and 280.0 <= cy <= 1020.0:
                stk_rec["status"] = "head_overlap_hard"
                hard_failures.append(
                    f"stickers `{sc['id']}` (at={sc['at']:.2f}s) 压入人物头肩禁区(x=220..860, y=280..1020)"
                )
            sticker_reports.append(stk_rec)
        if sticker_reports:
            details["sticker_checks"] = sticker_reports

    # 5. Subtitles V2 Zero-Pill, Typography, Length, Mid-Comma & Opening/Ending Gates
    sub_has_pill_box = False
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
                "scenes/subtitles.html 存在正序循环 `c[1] + 0.xx` 直接 break 延迟缺陷"
            )

        sub_font_sizes: list[float] = []
        for sb in re.findall(r"<style\b[^>]*>([\s\S]*?)</style>", sub_txt, flags=re.IGNORECASE):
            for cm in re.finditer(
                r"(?:\.pill|#sub|\.sub-box|\.sub-line|\.sub-text)\s*\{([^}]*)\}", sb, flags=re.IGNORECASE
            ):
                cbody = cm.group(1)
                if re.search(
                    r"background(?:-color)?\s*:\s*(?:rgba?\(|#[0-9a-fA-F]{3,8}|linear-gradient)",
                    cbody,
                    flags=re.IGNORECASE,
                ):
                    sub_has_pill_box = True
                fs = parse_css_px(cbody, "font-size")
                if fs:
                    sub_font_sizes.append(fs)
            for fm in re.findall(r"font-size\s*:\s*(\d+(?:\.\d+)?)px", sb, flags=re.IGNORECASE):
                sub_font_sizes.append(float(fm))

        if sub_has_pill_box:
            hard_failures.append(
                "违反零胶囊框字幕铁律(SUB1-SUB6)：`scenes/subtitles.html` 仍使用 `.pill / #sub` 实色或半透明背景底框，全风格一律改用无底框排印字幕"
            )
        max_sub_fs = max(sub_font_sizes) if sub_font_sizes else None
        details["subtitle_max_font_px"] = max_sub_fs
        if max_sub_fs is not None:
            min_req_fs = 48.0 if style_slot == "v1" else 40.0
            if max_sub_fs < min_req_fs:
                hard_failures.append(
                    f"字幕字号偏小：`subtitles.html` 最大字号仅 {max_sub_fs:.0f}px(< {min_req_fs:.0f}px 手机竖屏下限)"
                )

        details["subtitle_cue_count"] = len(raw_cues_html)
        if raw_cues_html:
            first_start, _, first_raw = raw_cues_html[0]
            first_text = strip_html(first_raw)
            _, last_end, last_raw = raw_cues_html[-1]
            last_text = strip_html(last_raw)
            details["first_cue"] = {"start": first_start, "text": first_text}
            details["last_cue"] = {"end": last_end, "text": last_text}

            if first_start <= 3.5:
                for pat in OPENING_FILLER_PATTERNS:
                    if re.search(pat, first_text):
                        hard_failures.append(
                            f"黄金前3秒精剪违规：首句字幕保留暖场废话/无前文指代（{first_start:.2f}s:「{first_text}」），必须按 H1-H6 冷开并裁净废语"
                        )
                        break

            for pat in ENDING_DANGLING_PATTERNS:
                if re.search(pat, last_text):
                    hard_failures.append(
                        f"末句字幕悬空半句/转折引子（结束于 {last_end:.2f}s:「{last_text}」）"
                    )
                    break

            if duration > 0 and (duration - last_end) < 0.35:
                warnings.append(
                    f"末句字幕距片尾仅余 {duration - last_end:.2f}s(<0.35s)，建议留 0.6-1.2s 尾韵"
                )

            overlong_cues: list[str] = []
            comma_cues: list[str] = []
            punct_in_hl: list[str] = []
            hl_cue_cnt = 0
            for cs, ce, ch in raw_cues_html:
                ct = strip_html(ch)
                net_len = len(cjk_only(ct))
                if net_len > 15:
                    overlong_cues.append(f"{cs:.1f}s「{ct}」({net_len}字)")
                if net_len > 10 and re.search(r"[\u4e00-\u9fffA-Za-z0-9][，,][\u4e00-\u9fffA-Za-z0-9]", ct):
                    comma_cues.append(f"{cs:.1f}s「{ct}」")
                if re.search(r"<(?:em|b|strong|mark)\b|class=['\"][^'\"]*\bhl\b", ch, flags=re.IGNORECASE):
                    hl_cue_cnt += 1
                if re.search(
                    r"<(?:em|b|strong|mark)\b[^>]*>[^<]*[，,。！？；：、]", ch, flags=re.IGNORECASE
                ):
                    punct_in_hl.append(f"{cs:.1f}s「{ct}」")

            if overlong_cues:
                hard_failures.append(
                    f"单屏字幕超长(>15净字，易折两行): {', '.join(overlong_cues[:4])}"
                )
            if comma_cues:
                hard_failures.append(
                    f"单屏字幕含句中逗号拼合两句话(须拆为两屏): {', '.join(comma_cues[:4])}"
                )
            if punct_in_hl:
                hard_failures.append(
                    f"字幕高亮标签内违规包裹标点符号: {', '.join(punct_in_hl[:4])}"
                )
            if len(raw_cues_html) >= 6 and (hl_cue_cnt / len(raw_cues_html)) > 0.50:
                hard_failures.append(
                    f"全片高亮词字幕泛滥：{hl_cue_cnt}/{len(raw_cues_html)} ({hl_cue_cnt/len(raw_cues_html):.0%} > 50%)，须精选 25%-40% 核心重音词"
                )

    # 6. Supplemental B-roll 5-point inspection (single-use, YAVG, scdet, 64-bit dHash, aspect ratio, vidstab shake & double-motion)
    visual_asset_counts: dict[str, int] = {}
    # bn -> (path, kind, t_in, dur, box_w, box_h, max_scale)
    supplemental_files: dict[str, tuple[Path, str, float, float, float, float, float]] = {}
    broll_video_count = 0

    if film_html.exists():
        html_txt_all = film_html.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(
            r'<img\b[^>]*src=["\']([^"\']+\.(?:jpg|jpeg|png|webp|gif))(?:#[^"\']*)?["\']',
            html_txt_all,
            flags=re.IGNORECASE,
        ):
            rel_s = m.group(1).split("#", 1)[0]
            bn = Path(rel_s).name.lower()
            if bn != "logo.png":
                visual_asset_counts[bn] = visual_asset_counts.get(bn, 0) + 1
                fp_img = film_dir / rel_s
                if fp_img.is_file() and bn not in supplemental_files:
                    supplemental_files[bn] = (fp_img, "image", 0.0, 0.0, 1080.0, 1920.0, 1.0)

        for vc in (main_clips + aux_visual_clips):
            if vc["tag"] != "video":
                continue
            bn = Path(vc["base_src"]).name.lower()
            if bn in speaker_vids_early or SPEAKER_VID_NAME_RE.search(bn):
                continue
            broll_video_count += 1
            visual_asset_counts[bn] = visual_asset_counts.get(bn, 0) + 1
            vf = film_dir / vc["base_src"]
            t_in = vc["t_in"] or 0.0
            v_dur = vc["dur"]
            if v_dur is None and vf.is_file():
                v_dur = max(0.0, float(ffprobe_json(vf).get("format", {}).get("duration", 0) or 0) - t_in)
            v_dur = v_dur or 3.0
            v_css = merged_clip_css(vc)
            bw = parse_css_px(v_css, "width", 1080.0) or 1080.0
            bh = parse_css_px(v_css, "height", 1920.0) or 1920.0
            it, ir, ib, il = resolve_pip_steady_inset(v_css, keyframes_map, bw, bh)
            vis_bw = max(160.0, bw - il - ir)
            vis_bh = max(160.0, bh - it - ib)
            max_sc = resolve_max_scale_in_css(v_css, keyframes_map)
            if vf.is_file():
                supplemental_files[bn] = (vf, "video", t_in, v_dur, vis_bw, vis_bh, max_sc)
                broll_samples.extend(
                    [
                        (vf, round(t_in + min(0.12, v_dur * 0.1), 2)),
                        (vf, round(t_in + v_dur * 0.5, 2)),
                        (vf, round(t_in + max(0.05, v_dur - 0.12), 2)),
                    ]
                )

    scenes_dir = film_dir / "scenes"
    helper_scene_re = re.compile(
        r"^(?:subtitles|base-bg|bridge|fx-.*|.*transition.*|.*glitch.*|.*wipe.*)\.html$",
        re.IGNORECASE,
    )
    main_stage_scene_names = {
        Path(c["base_src"]).name for c in main_clips if c["tag"] == "iframe"
    }

    if scenes_dir.exists():
        bottom_traps: list[str] = []
        tiny_fonts: list[str] = []
        ghost_files: list[str] = []
        static_strikes: list[str] = []
        fake_rec_files: list[str] = []
        content_scenes = 0
        dynamic_visual_scenes = 0
        text_only_scenes: list[str] = []
        sb_global_counts: dict[str, list[tuple[str, int]]] = {}

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
                if fs < 22:
                    tiny_fonts.append(f"{sf.name}: {fs}px")
            if re.search(r"opacity\s*=\s*String\(\s*0\.[1-5]\d*\s*\+", txt):
                ghost_files.append(sf.name)
            if "text-decoration: line-through" in txt or "text-decoration:line-through" in txt:
                static_strikes.append(sf.name)
            if style_slot == "v4" and re.search(r"REC\s*[·•]|SPEAKER\s+CAM", txt):
                fake_rec_files.append(sf.name)

            if sf.suffix.lower() == ".html" and not helper_scene_re.match(sf.name):
                scene_assets: list[str] = []
                for a, b in asset_ref_re.findall(txt):
                    raw_ref = (a or b).split("#", 1)[0]
                    bn = Path(raw_ref).name.lower()
                    if bn == "logo.png" or bn in speaker_vids_early:
                        continue
                    visual_asset_counts[bn] = visual_asset_counts.get(bn, 0) + 1
                    scene_assets.append(bn)
                    cand_p = (sf.parent / raw_ref).resolve()
                    if not cand_p.is_file():
                        cand_p = (film_dir / raw_ref).resolve()
                    if cand_p.is_file() and bn not in supplemental_files:
                        is_vid = cand_p.suffix.lower() in {".mp4", ".webm", ".mov"}
                        sc_bw, sc_bh, sc_max = 1080.0, 1920.0, 1.0
                        if is_vid:
                            sf_kf: dict[str, str] = {}
                            sf_cls: dict[str, str] = {}
                            for s_blk in re.findall(r"<style\b[^>]*>([\s\S]*?)</style>", txt, re.I):
                                sf_kf.update(extract_keyframes_blocks(s_blk))
                                s_clean = re.sub(
                                    r"@keyframes\s+[A-Za-z0-9_-]+\s*\{(?:[^{}]|\{[^{}]*\})*\}",
                                    "",
                                    s_blk,
                                    flags=re.I,
                                )
                                for cm_v in re.finditer(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}", s_clean):
                                    sf_cls[cm_v.group(1)] = sf_cls.get(cm_v.group(1), "") + ";" + cm_v.group(2)
                            vm = re.search(
                                rf'<video\b([^>]*src=["\'][^"\']*{re.escape(Path(raw_ref).name)}[^"\']*["\'][^>]*)>',
                                txt,
                                re.I,
                            )
                            if vm:
                                v_at = vm.group(1)
                                vc_m = re.search(r'\bclass=["\']([^"\']+)["\']', v_at, re.I)
                                vs_m = re.search(r'\bstyle=["\']([^"\']+)["\']', v_at, re.I)
                                v_mcss = ";".join(
                                    ([sf_cls.get(c, "") for c in vc_m.group(1).split()] if vc_m else [])
                                    + ([vs_m.group(1)] if vs_m else [])
                                )
                                sc_bw = parse_css_px(v_mcss, "width", 1080.0) or 1080.0
                                sc_bh = parse_css_px(v_mcss, "height", 1920.0) or 1080.0
                                sc_max = resolve_max_scale_in_css(v_mcss, sf_kf)
                        supplemental_files[bn] = (
                            cand_p,
                            "video" if is_vid else "image",
                            0.0,
                            3.0,
                            sc_bw,
                            sc_bh,
                            sc_max,
                        )
                        broll_samples.append((cand_p, 0.5 if is_vid else None))

                # Boxless, fake progress bar, image crop distortion & space-between child counts
                bx = inspect_boxless_scene(sf, film_dir)
                for hi in bx["hard_issues"]:
                    hard_failures.append(f"场景视觉规范违规 `{sf.name}`: {hi}")
                for cls_n, cnts in bx["sb_child_counts"].items():
                    for c_val in cnts:
                        sb_global_counts.setdefault(cls_n, []).append((sf.name, c_val))
                        if c_val <= 1:
                            hard_failures.append(
                                f"版面结构塌陷 `{sf.name}`: 固定高 `space-between` 容器 `.{cls_n}` 仅含 {c_val} 个子元素，产生大面积空洞"
                            )

                # Evaluate visual density ONLY on main-stage non-outro scenes (fixes #L1703 overlay distortion)
                is_main_scene = (not main_stage_scene_names) or (sf.name in main_stage_scene_names)
                if is_main_scene and not re.search(r"(?:outro|ending)", sf.name, re.IGNORECASE):
                    content_scenes += 1
                    lower_txt = txt.lower()
                    has_svg = "<svg" in lower_txt
                    has_canvas = "<canvas" in lower_txt
                    has_media = bool(scene_assets) or ("<video" in lower_txt)
                    max_fs_scene = max(
                        [int(x) for x in re.findall(r"font-size:\s*(\d+)px", txt)] or [0]
                    )
                    has_kinetic_typo = max_fs_scene >= 84 and ("window.film" in txt or "@keyframes" in txt)
                    if has_svg or has_canvas or has_media or has_kinetic_typo:
                        dynamic_visual_scenes += 1
                    else:
                        text_only_scenes.append(sf.name)

        # Cross-scene space-between child-count consistency check (catches s09 missing .chap-num hole)
        for cls_n, pairs in sb_global_counts.items():
            distinct_cnts = {c for _, c in pairs}
            if len(distinct_cnts) >= 2:
                max_c = max(distinct_cnts)
                hole_scenes = [sn for sn, c in pairs if c < max_c]
                hard_failures.append(
                    f"固定高 `space-between` 漏块塌陷：`.{cls_n}` 在同片多镜中子块数不一致(标准 {max_c} 块，但 `{', '.join(hole_scenes[:3])}` 漏写子块导致间距异常撑大留洞)"
                )

        reused_assets = {k: v for k, v in visual_asset_counts.items() if v > 1}
        details["single_use_visual_assets"] = {
            "counts": visual_asset_counts,
            "reused": reused_assets,
            "passed": len(reused_assets) == 0,
        }
        if reused_assets:
            reused_desc = ", ".join(f"{k}({v}次)" for k, v in sorted(reused_assets.items()))
            hard_failures.append(f"违反单支视频视觉素材仅用1次红线: {reused_desc}")

        # Verify every supplemental visual asset has passed API/external 6D production-fit sign-off in credits.json
        credits_path = film_dir / "assets" / "credits.json"
        credits_by_bn: dict[str, dict[str, Any]] = {}
        if credits_path.is_file():
            try:
                raw_cred = json.loads(credits_path.read_text(encoding="utf-8"))
                cred_list = (
                    raw_cred
                    if isinstance(raw_cred, list)
                    else (raw_cred.get("items") if isinstance(raw_cred, dict) else [])
                )
                for entry in cred_list or []:
                    if isinstance(entry, dict) and entry.get("file"):
                        credits_by_bn[Path(str(entry["file"])).name.lower()] = entry
            except Exception:
                pass

        lazy_fit_re = re.compile(
            r"^(?:ok|pass|yes|good|fit|matched|verified|符合|符合要求|合格|通过|没问题|可以|合适|匹配|测试|默认|自动下载)[\s!！.。]*$",
            flags=re.IGNORECASE,
        )
        unverified_broll: list[str] = []
        for bn in sorted(supplemental_files.keys()):
            c_ent = credits_by_bn.get(bn)
            if not c_ent:
                unverified_broll.append(f"{bn}(未登记 credits.json)")
                continue
            shot_v = str(c_ent.get("shot_id") or "").strip()
            fit_ok = c_ent.get("fit_verified") is True
            reason_v = str(c_ent.get("fit_reason") or "").strip()
            net_r = len(re.sub(r"\s+", "", reason_v))
            if not fit_ok or not shot_v or net_r < 12 or lazy_fit_re.match(reason_v):
                unverified_broll.append(f"{bn}(缺 fit_verified/shot_id 或具体 fit_reason>=12字)")

        details["asset_fit_signoff"] = {
            "supplemental_count": len(supplemental_files),
            "unverified": unverified_broll,
            "passed": len(unverified_broll) == 0,
        }
        if unverified_broll:
            hard_failures.append(
                f"API/外部素材未经制作要求核验签收：{', '.join(unverified_broll[:5])} —— 严禁 API 搜到随便拿一个直入成片！"
                "必须先经 `fetch_asset.py inspect-candidates` 生成候选检视拼图亲自看图核验六维要求（台词语义咬合/地域零穿帮/竖屏构图避让/影调统一/稳像清晰），"
                "再用 `fetch_asset.py register --shot <镜号> --fit-reason '<具体实看核验结论>'` 签收入 `film/assets/credits.json`"
            )

        # Run B-roll video YAVG/scdet/stability/double-motion & 64-bit dHash checks in parallel (4 threads)
        broll_qc: list[dict[str, Any]] = []
        dhash_map: list[tuple[str, int]] = []
        supp_items = sorted(supplemental_files.items())

        def _probe_supp_item(
            item: tuple[str, tuple[Path, str, float, float, float, float, float]],
        ) -> tuple[str, Path, str, float, float, float, float, float, int | None, dict[str, Any] | None]:
            bn_k, (fp_p, knd, tin_v, dur_v, vbw, vbh, msc) = item
            dh_v = compute_visual_dhash(fp_p, sample_t=(tin_v + dur_v * 0.5) if knd == "video" else None)
            vqc_res: dict[str, Any] | None = None
            if knd == "video":
                vqc_res = inspect_video_broll_segment(fp_p, tin_v, dur_v, box_w=vbw, box_h=vbh)
            return (bn_k, fp_p, knd, tin_v, dur_v, vbw, vbh, msc, dh_v, vqc_res)

        probed_supp: list[tuple[str, Path, str, float, float, float, float, float, int | None, dict[str, Any] | None]] = []
        if supp_items:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(supp_items))) as pool:
                probed_supp = list(pool.map(_probe_supp_item, supp_items))

        for bn, fpath, kind, t_in, v_dur, vis_bw, vis_bh, max_sc, dh, v_qc in probed_supp:
            if dh is not None:
                dhash_map.append((bn, dh))
            if kind == "image" and (fpath, None) not in broll_samples:
                broll_samples.append((fpath, None))
            if kind == "video" and v_qc is not None:
                v_qc["file"] = bn
                v_qc["segment"] = [round(t_in, 2), round(t_in + v_dur, 2)]
                v_qc["render_box"] = [round(vis_bw), round(vis_bh)]
                v_qc["css_max_scale"] = round(max_sc, 3)
                broll_qc.append(v_qc)
                if v_qc["dark_consecutive"] >= 2 or v_qc["dark_ratio"] > 0.25:
                    hard_failures.append(
                        f"B-roll 未曝光暗黑片头缺陷：`{bn}` 选用区间 [{t_in:.2f}s..{t_in+v_dur:.2f}s] 含黑场/极暗帧(最低 YAVG={v_qc['yavg_min']} < 18)"
                    )
                if v_qc["max_scdet_score"] >= 16.0:
                    hard_failures.append(
                        f"B-roll 镜头内未切分硬切穿帮：`{bn}` 在 {v_qc['scdet_times']}s 存在内部机位硬切(scdet={v_qc['max_scdet_score']} >= 16.0)"
                    )
                if v_qc.get("stability_tier") == "C_severe_jitter":
                    hard_failures.append(
                        f"B-roll 背景高频往复晃动/抖动穿帮：`{bn}` 选用区间 [{t_in:.2f}s..{t_in+v_dur:.2f}s] 折算舞台高频急动度 hf_jerk={v_qc['hf_jerk_px']}px(>2.40px) 或往复反向率={v_qc['reversals_per_sec']}/s(>2.50/s)，严禁使用手持剧烈晃动/天桥快放延时/颠簸船拍素材，请更换 Pixabay 竖屏三脚架/云台稳像素材或运行 `qc_video.py stabilize-broll`"
                    )
                elif v_qc.get("stability_tier") == "B_mild_shake":
                    warnings.append(
                        f"B-roll 存在轻微手持微晃：`{bn}` (hf_jerk={v_qc['hf_jerk_px']}px, 往复反向率={v_qc['reversals_per_sec']}/s)，建议运行 `qc_video.py stabilize-broll` 稳像或改用 L3/L6 横屏视窗构图"
                    )
                if abs(max_sc - 1.0) > 0.015 and (
                    v_qc.get("mean_speed_px", 0.0) > 0.45 or v_qc.get("hf_jerk_px", 0.0) > 0.40
                ):
                    hard_failures.append(
                        f"B-roll 双重运镜打架：`{bn}` 自身含原生运镜或微晃(均速={v_qc['mean_speed_px']}px/f, hf_jerk={v_qc['hf_jerk_px']}px) 却违规叠加 CSS 缩放动画(scale={max_sc:.2f})，放大背景抖动并引发视觉眩晕，仅锁死三脚架绝对静止镜头可叠加人工 scale 推镜"
                    )
        for i in range(len(dhash_map)):
            for j in range(i + 1, len(dhash_map)):
                n1, h1 = dhash_map[i]
                n2, h2 = dhash_map[j]
                dist = hamming_dist(h1, h2)
                if dist <= 10:
                    hard_failures.append(
                        f"B-roll 改名克隆违规：`{n1}` 与 `{n2}` 中心视觉指纹高度雷同(64-bit dHash 距离={dist} <= 10)"
                    )
        if broll_qc:
            details["broll_video_checks"] = broll_qc

        denom = content_scenes + broll_video_count
        if denom > 0:
            text_only_ratio = len(text_only_scenes) / denom
            motion_ratio = (dynamic_visual_scenes + broll_video_count) / denom
            details["visual_density"] = {
                "main_stage_content_scenes": content_scenes,
                "broll_video_clips": broll_video_count,
                "dynamic_visual_scenes": dynamic_visual_scenes,
                "text_only_scenes": len(text_only_scenes),
                "text_only_ratio": round(text_only_ratio, 3),
                "motion_ratio": round(motion_ratio, 3),
            }
            if denom >= 4 and text_only_ratio > 0.25:
                warnings.append(
                    f"静态纯文字场景占比偏高（{len(text_only_scenes)}/{denom} = {text_only_ratio:.0%} > 25%）"
                )

        if style_slot == "v4" and scenes_dir.exists():
            v4_max_fs = 0
            v4_card_scenes: list[str] = []
            for sf_v4 in sorted(scenes_dir.glob("*.html")):
                if sf_v4.name == "subtitles.html" or helper_scene_re.match(sf_v4.name):
                    continue
                t_v4 = sf_v4.read_text(encoding="utf-8", errors="replace")
                fs_v4 = [int(x) for x in re.findall(r"font-size\s*:\s*(\d+)px", t_v4)]
                if fs_v4:
                    v4_max_fs = max(v4_max_fs, max(fs_v4))
                bx_v4 = inspect_boxless_scene(sf_v4, film_dir)
                b_v4 = t_v4[t_v4.lower().find("<body") :] if "<body" in t_v4.lower() else t_v4
                bordered_cards = len(
                    re.findall(r"border-radius\s*:\s*(?:[89]|[1-3]\d)px", t_v4, re.I)
                )
                if bx_v4["content_rects"] >= 3 or bordered_cards >= 3:
                    v4_card_scenes.append(sf_v4.name)
            details["v4_max_scene_font_px"] = v4_max_fs
            if duration >= 24.0 and v4_max_fs < 68:
                hard_failures.append(
                    f"v4(S04 竖屏银幕散文电影) 排印字号过小：场景最大字号仅 {v4_max_fs}px(< 68px 银幕主标题下限)，严禁全片用 40-48px 小字飘在黑边里，须构建三层极差胶片暗房光晕(KT3 Halation 68-104px)主论断"
                )
            if v4_card_scenes:
                hard_failures.append(
                    f"v4(G4老郑AI经营论·S04) 违规混入圆角 UI 卡片/SVG 方框图表(`{', '.join(v4_card_scenes[:3])}`)：S04 仅允许纯 `<canvas>` 光影粒子空间场与无框衬线排印"
                )

        if bottom_traps:
            hard_failures.append(
                f"界面元素掉入底部 360px 平台遮挡死区(y>=1540px): {', '.join(bottom_traps[:6])}"
            )
        if tiny_fonts:
            warnings.append(f"检测到偏小字号(<22px): {', '.join(sorted(set(tiny_fonts))[:6])}")
        if ghost_files:
            hard_failures.append(
                f"未出场元素幽灵半透明预显提前剧透: {', '.join(ghost_files[:6])}"
            )
        if static_strikes:
            warnings.append(f"检测到静态 CSS line-through: {', '.join(static_strikes[:4])}")
        if fake_rec_files:
            hard_failures.append(f"v4(G4老郑AI经营论) 违规使用伪监视器 REC 套壳: {', '.join(fake_rec_files[:4])}")

        # 6b. Platform policy sensitive-word leak & cross-slot IP confusion audit on subtitles & scenes
        policy_leaks: list[str] = []
        for cs, _, ct_plain in parsed_cues_sync:
            for ph in find_policy_sensitive_hits(ct_plain):
                policy_leaks.append(f"subtitles@{cs:.1f}s「{ph['raw_word']}->应脱敏为:{ph['masked_text']}」")
        if scenes_dir.exists():
            for sf in sorted(scenes_dir.glob("*.html")):
                if sf.name == "subtitles.html":
                    continue
                s_raw = sf.read_text(encoding="utf-8", errors="replace")
                s_vis = _extract_scene_dual_text(s_raw)
                for ph in find_policy_sensitive_hits(s_vis):
                    policy_leaks.append(f"{sf.name}「{ph['raw_word']}->应脱敏为:{ph['masked_text']}」")
                if style_slot in SLOT_ACCOUNT_MAP:
                    for k_slot, s_meta in SLOT_ACCOUNT_MAP.items():
                        if k_slot != style_slot and s_meta["ip_name"] in s_vis:
                            hard_failures.append(
                                f"片内账号 IP 名串台违规 [{style_slot}->{SLOT_ACCOUNT_MAP[style_slot]['ip_name']}]：`{sf.name}` 误出现了其他号组 IP 名「{s_meta['ip_name']}」"
                            )
        details["policy_compliance_checks"] = {
            "unmasked_hits": policy_leaks,
            "passed": len(policy_leaks) == 0,
        }
        if policy_leaks:
            hard_failures.append(
                f"平台政策敏感词未屏蔽脱敏违规：{', '.join(dict.fromkeys(policy_leaks[:6]))} —— 须对字幕/画面敏感词脱敏(如抖音->某音)，并对人声母带执行 `qc_video.py prepare-voice --bleeps` 1000Hz 哔声屏蔽"
            )

        # 7. Audio-visual & spoken-text synchronization audit
        if parsed_cues_sync and film_html.exists():
            sync_reports: list[dict[str, Any]] = []
            all_timed_iframes = [
                ("main-stage", c) for c in main_clips if c["tag"] == "iframe"
            ] + [("overlays", c) for c in overlay_clips if c["tag"] == "iframe"]
            for trk_name, ic in all_timed_iframes:
                sf_path = film_dir / ic["base_src"]
                if not sf_path.is_file():
                    continue
                if helper_scene_re.match(sf_path.name) or re.search(
                    r"(?:outro|ending)", sf_path.name, flags=re.IGNORECASE
                ):
                    continue
                c_dur = ic["dur"] if ic["dur"] is not None else max(0.0, duration - ic["at"])
                if c_dur < 2.2:
                    continue
                rep = analyze_scene_sync(
                    sf_path, ic["id"], trk_name, ic["at"], c_dur, parsed_cues_sync
                )
                sync_reports.append(rep)
                for hi in rep["hard_issues"]:
                    hard_failures.append(
                        f"音画同步/零复读违规 `{ic['id']}` ({sf_path.name}, at={ic['at']:.2f}s): {hi}"
                    )
                for wi in rep["warnings"]:
                    warnings.append(
                        f"音画可读性提示 `{ic['id']}` ({sf_path.name}, at={ic['at']:.2f}s): {wi}"
                    )
            if sync_reports:
                details["sync_checks"] = {
                    "scenes_audited": len(sync_reports),
                    "violating_scenes": [r["scene"] for r in sync_reports if r["hard_issues"]],
                    "reports": sync_reports,
                }

        # 8. Per-slot editing paradigm purity checks (G0=S01, G1/v1=S02, G2/v2=S03, G3/v3=S08, G4/v4=S04)
        paradigm_violations: list[str] = []
        if style_slot == "v1":
            wide_v1_pips = [p for p in details.get("pip_framing_checks", []) if p["visible_box"][2] > 380]
            if wide_v1_pips:
                paradigm_violations.append(
                    f"v1(G1时奕聊AI经营·网感快剪流) 违规使用顶部大矩形讲座 PiP `{wide_v1_pips[0]['id']}`(宽 {wide_v1_pips[0]['visible_box'][2]}px > 380px)"
                )
        elif style_slot == "v2":
            wide_v2_pips = [p for p in details.get("pip_framing_checks", []) if p["visible_box"][2] > 320]
            if wide_v2_pips:
                paradigm_violations.append(
                    f"v2(G2辰奕AI经营实战·白板推演流) 违规使用宽 {wide_v2_pips[0]['visible_box'][2]}px(>320px) 大矩形 PiP 挤占画布"
                )
        elif style_slot == "v4":
            v4_boxed_scenes: list[str] = []
            for sf in sorted(scenes_dir.iterdir()):
                if sf.suffix.lower() != ".html" or sf.name == "subtitles.html":
                    continue
                if helper_scene_re.match(sf.name) or re.search(r"(?:outro|ending)", sf.name, re.IGNORECASE):
                    continue
                stxt = sf.read_text(encoding="utf-8", errors="replace")
                body_part = stxt[stxt.lower().find("<body") :] if "<body" in stxt.lower() else stxt
                has_slash_hud = bool(re.search(r"[A-Z]{3,}[A-Z0-9 _-]*//", body_part))
                rect_cnt = len(re.findall(r"<rect\b", body_part, flags=re.IGNORECASE))
                has_wide_box = bool(
                    re.search(
                        r'class=["\'][^"\']*(?:cine-box|hud-box|paper-card|hud)\b', body_part, re.IGNORECASE
                    )
                )
                if has_slash_hud or rect_cnt >= 2 or has_wide_box:
                    v4_boxed_scenes.append(sf.name)
            if v4_boxed_scenes:
                paradigm_violations.append(
                    f"v4(G4老郑AI经营论·宽银幕电影独白流) 违规出现方盒卡片/多框图表或双斜杠顶标({', '.join(v4_boxed_scenes[:4])})"
                )

        if paradigm_violations:
            details["paradigm_violations"] = paradigm_violations
            for pv in paradigm_violations:
                hard_failures.append(f"剪辑范式同质化违规 [{style_slot}]: {pv}")

    return details, cut_points, cutout_sticker_points, pip_points, broll_samples


def _parse_rgb_avg(color_expr: str) -> float | None:
    hex_m = re.search(r"#([0-9a-fA-F]{6})\b", color_expr)
    if hex_m:
        hx = hex_m.group(1)
        return (int(hx[0:2], 16) + int(hx[2:4], 16) + int(hx[4:6], 16)) / 3.0
    rgb_m = re.search(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", color_expr, flags=re.IGNORECASE)
    if rgb_m:
        return (int(rgb_m.group(1)) + int(rgb_m.group(2)) + int(rgb_m.group(3))) / 3.0
    return None


_FACE_MODELS_SINGLETON: tuple[Any, Any] | None = None


def _get_face_models() -> tuple[Any, Any] | None:
    """Lazy-load offline YuNet + OpenFilm 478-point 3D FaceMesh TFLite without external downloads."""
    global _FACE_MODELS_SINGLETON
    if _FACE_MODELS_SINGLETON is not None:
        return _FACE_MODELS_SINGLETON
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        svp_root = Path(os.environ.get("SVP_ROOT", Path(__file__).resolve().parents[4]))
        yunet_p = svp_root / ".local" / "rea-video" / "models" / "face_detection_yunet_2023mar.onnx"
        task_p = svp_root / "node_modules" / "openfilm" / "models" / "vision" / "face.task"
        if not yunet_p.is_file() or not task_p.is_file():
            return None
        yunet = cv2.FaceDetectorYN.create(str(yunet_p), "", (640, 360), 0.52, 0.3, 5000)
        with zipfile.ZipFile(task_p, "r") as zf:
            buf = zf.read("face_landmarks_detector.tflite")
        mesh_net = cv2.dnn.readNetFromTFLite(np.frombuffer(buf, dtype=np.uint8))
        _FACE_MODELS_SINGLETON = (yunet, mesh_net)
        return _FACE_MODELS_SINGLETON
    except Exception:
        return None


def evaluate_portrait_bgr(bgr: Any, min_sym_override: float | None = None) -> dict[str, Any] | None:
    """Evaluate 3D facial pose (yaw/roll/pitch), iris gaze, eye openness, and lip naturalness on a BGR image."""
    models = _get_face_models()
    if models is None or bgr is None:
        return None
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    yunet, mesh_net = models
    h, w = bgr.shape[:2]
    if h < 80 or w < 80:
        return None
    det_w = min(960, w)
    det_h = max(120, int(round(h * det_w / max(1, w))))
    small = cv2.resize(bgr, (det_w, det_h)) if (det_w, det_h) != (w, h) else bgr
    yunet.setInputSize((det_w, det_h))
    _, faces = yunet.detect(small)
    if faces is None or len(faces) == 0:
        return {"has_face": False}

    f = max(faces, key=lambda r: float(r[2]) * float(r[3]))
    sx, sy = w / float(det_w), h / float(det_h)
    fx, fy, fw, fh = float(f[0]) * sx, float(f[1]) * sy, float(f[2]) * sx, float(f[3]) * sy
    re_x, re_y, le_x, le_y = float(f[4]) * sx, float(f[5]) * sy, float(f[6]) * sx, float(f[7]) * sy
    coarse_roll = float(np.degrees(np.arctan2(le_y - re_y, le_x - re_x)))
    cx, cy = fx + fw * 0.5, fy + fh * 0.5
    box = max(fw, fh) * 1.45
    # OpenCV getRotationMatrix2D(angle > 0) rotates CCW (upward in y-down coords).
    # When le_y > re_y (coarse_roll > 0), rotating CCW by +coarse_roll levels the eyes!
    rot_m = cv2.getRotationMatrix2D((cx, cy), coarse_roll, 256.0 / max(1.0, box))
    rot_m[0, 2] += 128.0 - cx
    rot_m[1, 2] += 128.0 - cy
    aligned = cv2.warpAffine(bgr, rot_m, (256, 256), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    rgb = cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    mesh_net.setInput(np.transpose(rgb, (2, 0, 1))[None, ...])
    presence = float(mesh_net.forward("Identity_1").ravel()[0])
    pts = mesh_net.forward("Identity").reshape(-1, 3)

    # Map key landmarks back to original image pixels for true unwarped roll & crop box
    inv_m = cv2.invertAffineTransform(rot_m)
    ones = np.ones((pts.shape[0], 1), dtype=np.float32)
    pts_orig = (np.hstack([pts[:, :2], ones]) @ inv_m.T)
    true_roll = float(
        np.degrees(np.arctan2(pts_orig[263, 1] - pts_orig[33, 1], pts_orig[263, 0] - pts_orig[33, 0]))
    )

    # Re-level 2D landmarks by any residual roll in aligned space so symmetry is 100% roll-invariant
    res_rad = -float(np.arctan2(pts[263, 1] - pts[33, 1], pts[263, 0] - pts[33, 0]))
    cos_r, sin_r = math.cos(res_rad), math.sin(res_rad)
    p2 = pts[:, :2] - 128.0
    p_lvl = np.stack([p2[:, 0] * cos_r - p2[:, 1] * sin_r, p2[:, 0] * sin_r + p2[:, 1] * cos_r], axis=1) + 128.0

    wl = float(p_lvl[168, 0] - p_lvl[234, 0])
    wr = float(p_lvl[454, 0] - p_lvl[168, 0])
    cheek_sym = (min(wl, wr) / max(wl, wr)) if (wl > 2.0 and wr > 2.0) else 0.0
    pitch_ratio = float(
        (p_lvl[1, 1] - 0.5 * (p_lvl[33, 1] + p_lvl[263, 1])) / max(1e-4, p_lvl[152, 1] - p_lvl[10, 1])
    )

    def _ear(po: int, pi: int, u1: int, l1: int, u2: int, l2: int) -> float:
        hz = float(np.linalg.norm(p_lvl[po] - p_lvl[pi]))
        vt = 0.5 * (
            float(np.linalg.norm(p_lvl[u1] - p_lvl[l1])) + float(np.linalg.norm(p_lvl[u2] - p_lvl[l2]))
        )
        return vt / max(1e-4, hz)

    ear_r = _ear(33, 133, 159, 145, 158, 153)
    ear_l = _ear(263, 362, 386, 374, 385, 380)
    min_ear = min(ear_r, ear_l)
    ear_asym = abs(ear_r - ear_l) / max(1e-4, max(ear_r, ear_l))

    # Iris gaze horizontal & vertical ratios (anatomical direct-camera center is ~0.525 due to medial tear duct)
    gx_r = (p_lvl[468, 0] - p_lvl[33, 0]) / max(1e-4, p_lvl[133, 0] - p_lvl[33, 0])
    gx_l = (p_lvl[473, 0] - p_lvl[362, 0]) / max(1e-4, p_lvl[263, 0] - p_lvl[362, 0])
    gaze_x = float(0.5 * (gx_r + gx_l))
    gy_r = (p_lvl[468, 1] - 0.5 * (p_lvl[159, 1] + p_lvl[158, 1])) / max(
        1e-4, 0.5 * (p_lvl[145, 1] + p_lvl[153, 1]) - 0.5 * (p_lvl[159, 1] + p_lvl[158, 1])
    )
    gy_l = (p_lvl[473, 1] - 0.5 * (p_lvl[386, 1] + p_lvl[385, 1])) / max(
        1e-4, 0.5 * (p_lvl[374, 1] + p_lvl[380, 1]) - 0.5 * (p_lvl[386, 1] + p_lvl[385, 1])
    )
    gaze_y = float(0.5 * (gy_r + gy_l))

    # Glasses glare check inside eye boxes on aligned gray
    gray_al = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
    glare_ratios: list[float] = []
    for e_idxs in ([33, 133, 159, 145], [362, 263, 386, 374]):
        ex1 = max(0, int(np.min(pts[e_idxs, 0])) - 2)
        ex2 = min(255, int(np.max(pts[e_idxs, 0])) + 2)
        ey1 = max(0, int(np.min(pts[e_idxs, 1])) - 2)
        ey2 = min(255, int(np.max(pts[e_idxs, 1])) + 2)
        epatch = gray_al[ey1 : ey2 + 1, ex1 : ex2 + 1]
        if epatch.size > 0:
            glare_ratios.append(float(np.mean(epatch > 245)))
    glare_ratio = max(glare_ratios) if glare_ratios else 0.0

    # Mouth comfort-zone metrics (catches both wide-open lower teeth AND swallowed/pursed/pouted grimaces)
    mw = float(np.linalg.norm(p_lvl[291] - p_lvl[61]))
    iod = float(np.linalg.norm(p_lvl[263] - p_lvl[33]))
    mar_inner = float(np.linalg.norm(p_lvl[14] - p_lvl[13]) / max(1e-4, mw))
    lip_fullness = float(np.linalg.norm(p_lvl[17] - p_lvl[0]) / max(1e-4, mw))
    mouth_width_ratio = float(mw / max(1e-4, iod))
    corner_asym = float(abs((p_lvl[61, 1] - p_lvl[0, 1]) - (p_lvl[291, 1] - p_lvl[0, 1])) / max(1e-4, mw))

    # Sharpness on central face oval
    f_patch = cv2.resize(gray_al[40:216, 48:208], (128, 128))
    sharpness = float(cv2.Laplacian(f_patch, cv2.CV_64F).var())

    # Chin/lower-cheek hand occlusion check via YCrCb skin intrusion below chin line
    ycrcb = cv2.cvtColor(aligned, cv2.COLOR_BGR2YCrCb)
    nose_patch = ycrcb[116:142, 116:142]
    y_med = float(np.median(nose_patch[:, :, 0]))
    cr_med = float(np.median(nose_patch[:, :, 1]))
    cb_med = float(np.median(nose_patch[:, :, 2]))
    chin_y = min(236, max(170, int(round(pts[152, 1]))))
    guard_band = ycrcb[min(250, chin_y + 8) : 254, 24:232]
    hand_intrusion = 0.0
    if guard_band.size > 0:
        skin_mask = (np.abs(guard_band[:, :, 1].astype(np.float32) - cr_med) < 14.0) & (
            np.abs(guard_band[:, :, 2].astype(np.float32) - cb_med) < 14.0
        )
        # Neck sits in central x=88..168; raised hand enters outer left/right lower corners x<78 or x>178!
        outer_skin = np.concatenate([skin_mask[:, :54], skin_mask[:, -54:]], axis=1)
        hand_intrusion = float(np.mean(outer_skin))
    # Also detect foreground raised hand outside the ears (offset 28px past zygomatic cheek landmarks 234/454)
    rc_lim = max(0, int(round(pts[234, 0])) - 28)
    lc_lim = min(256, int(round(pts[454, 0])) + 28)
    for cx1, cx2 in ((0, rc_lim), (lc_lim, 256)):
        if cx2 - cx1 >= 28:
            cband = ycrcb[84:174, cx1:cx2]
            if cband.size > 0:
                c_sk = (
                    (np.abs(cband[:, :, 0].astype(np.float32) - y_med) < 30.0)
                    & (np.abs(cband[:, :, 1].astype(np.float32) - cr_med) < 11.5)
                    & (np.abs(cband[:, :, 2].astype(np.float32) - cb_med) < 11.5)
                )
                hand_intrusion = max(hand_intrusion, float(np.mean(c_sk)))

    req_sym = min_sym_override if min_sym_override is not None else 0.56
    vetoes: list[str] = []
    if cheek_sym < req_sym:
        vetoes.append(f"侧脸偏转未正对镜头(cheek_sym={cheek_sym:.3f} < {req_sym:.2f})")
    if abs(true_roll) > 10.0:
        vetoes.append(f"歪头倾角过大(roll={true_roll:+.1f}° > ±10.0°)")
    if not (0.185 <= pitch_ratio <= 0.285):
        vetoes.append(f"俯仰角异常(pitch={pitch_ratio:.3f})")
    if min_ear < 0.180:
        vetoes.append(f"半闭眼/眨眼瞬间(min_ear={min_ear:.3f} < 0.180)")
    if ear_asym > 0.260:
        vetoes.append(f"大小眼/斜睨抽动(ear_asym={ear_asym:.2f} > 0.260)")
    if abs(gaze_x - 0.530) > 0.075:
        vetoes.append(f"眼神斜瞟场外未看镜头(gaze_x={gaze_x:.3f} 偏离正视带[0.455..0.605])")
    if not (0.28 <= gaze_y <= 0.58):
        vetoes.append(f"眼球下垂念稿或上翻(gaze_y={gaze_y:.3f})")
    if glare_ratio > 0.09:
        vetoes.append(f"镜片强反光遮瞳(glare={glare_ratio:.1%})")
    if mar_inner > 0.180:
        vetoes.append(f"张嘴过大露齿过渡态(mar={mar_inner:.3f} > 0.180)")
    if lip_fullness < 0.44:
        vetoes.append(f"句间吞咽内卷抿嘴/憋笑瘪嘴(lip_fullness={lip_fullness:.3f} < 0.44)")
    if mouth_width_ratio < 0.40:
        vetoes.append(f"辅音前撅吹哨嘟嘴(mouth_width={mouth_width_ratio:.3f} < 0.40)")
    if corner_asym > 0.085:
        vetoes.append(f"单侧歪嘴抽动(corner_asym={corner_asym:.3f} > 0.085)")
    if hand_intrusion > 0.24:
        vetoes.append(f"下巴两侧挥手残影入镜(hand_intrusion={hand_intrusion:.2f})")

    # Composite portrait aesthetics score [0..100]
    s_pose = (
        max(0.0, min(1.0, (cheek_sym - 0.35) / 0.55)) * 0.65
        + max(0.0, 1.0 - abs(true_roll) / 10.0) * 0.25
        + max(0.0, 1.0 - abs(pitch_ratio - 0.235) / 0.055) * 0.10
    )
    s_eye = (
        max(0.0, min(1.0, (min_ear - 0.16) / 0.08)) * 0.40
        + max(0.0, 1.0 - abs(gaze_x - 0.525) / 0.085) * 0.40
        + max(0.0, 1.0 - ear_asym / 0.28) * 0.20
    )
    # Ideal mouth: relaxed closed or gentle micro-smile (mar 0.00..0.09, lip_fullness ~0.53)
    s_mar = 1.0 if mar_inner <= 0.075 else max(0.0, 1.0 - (mar_inner - 0.075) / 0.095)
    s_lip = max(0.0, 1.0 - abs(lip_fullness - 0.535) / 0.14)
    s_mouth = s_mar * 0.45 + s_lip * 0.35 + max(0.0, 1.0 - corner_asym / 0.09) * 0.20
    s_clean = max(0.0, min(1.0, sharpness / 95.0)) * 0.70 + max(0.0, 1.0 - hand_intrusion / 0.25) * 0.30
    total_score = round((0.36 * s_pose + 0.26 * s_eye + 0.25 * s_mouth + 0.13 * s_clean) * 100.0, 2)

    return {
        "has_face": True,
        "presence": round(presence, 2),
        "face_box_px": [round(fx), round(fy), round(fw), round(fh)],
        "cheek_sym": round(cheek_sym, 3),
        "roll_deg": round(true_roll, 2),
        "pitch_ratio": round(pitch_ratio, 3),
        "min_ear": round(min_ear, 3),
        "ear_asym": round(ear_asym, 3),
        "gaze_x": round(gaze_x, 3),
        "gaze_y": round(gaze_y, 3),
        "glare_ratio": round(glare_ratio, 3),
        "mar_inner": round(mar_inner, 3),
        "lip_fullness": round(lip_fullness, 3),
        "mouth_width_ratio": round(mouth_width_ratio, 3),
        "corner_asym": round(corner_asym, 3),
        "sharpness_lap": round(sharpness, 1),
        "hand_intrusion": round(hand_intrusion, 3),
        "score": total_score,
        "vetoes": vetoes,
        "passed": len(vetoes) == 0,
    }


def _crop_face_zoom_tile(bgr: Any, meta: dict[str, Any], label: str, tile_w: int = 420, tile_h: int = 480) -> Any:
    """Render a 1:1 / 1.65x head-and-shoulders inspection tile with metric overlay."""
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    h, w = bgr.shape[:2]
    if meta.get("has_face") and meta.get("face_box_px"):
        fx, fy, fw, fh = meta["face_box_px"]
        cx = fx + fw * 0.5
        cy = fy + fh * 0.48
        crop_h = max(160.0, fh * 1.85)
        crop_w = crop_h * (tile_w / float(tile_h))
        x1 = int(round(max(0.0, min(w - crop_w, cx - crop_w * 0.5))))
        y1 = int(round(max(0.0, min(h - crop_h, cy - crop_h * 0.46))))
        x2 = min(w, int(round(x1 + crop_w)))
        y2 = min(h, int(round(y1 + crop_h)))
        patch = bgr[y1:y2, x1:x2]
    else:
        patch = bgr
    tile = cv2.resize(patch, (tile_w, tile_h), interpolation=cv2.INTER_AREA) if patch.size > 0 else np.zeros((tile_h, tile_w, 3), dtype=np.uint8)
    # Draw semi-transparent bottom HUD bar
    bar = tile[tile_h - 86 : tile_h, :].astype(np.float32) * 0.26
    tile[tile_h - 86 : tile_h, :] = bar.astype(np.uint8)
    ok_col = (90, 235, 130) if meta.get("passed") else (70, 90, 255)
    cv2.rectangle(tile, (2, 2), (tile_w - 3, tile_h - 3), ok_col, 3)
    cv2.putText(tile, label[:30], (12, tile_h - 54), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (255, 255, 255), 2, cv2.LINE_AA)
    if meta.get("has_face"):
        m1 = f"S={meta['score']:.1f} sym={meta['cheek_sym']:.2f} roll={meta['roll_deg']:+.1f}d"
        m2 = f"ear={meta['min_ear']:.2f} gx={meta['gaze_x']:.2f} mar={meta['mar_inner']:.2f} lip={meta['lip_fullness']:.2f}"
        cv2.putText(tile, m1, (12, tile_h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.46, ok_col, 1, cv2.LINE_AA)
        cv2.putText(tile, m2, (12, tile_h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (220, 230, 240), 1, cv2.LINE_AA)
    return tile


def _resolve_adaptive_cover_min_sym(slot_root: Path) -> float:
    """Read adaptive min_sym from E0/slot cover-frame-pool.json if available; default 0.56."""
    cands = [
        slot_root / "materials" / "covers" / "cover-frame-pool.json",
        slot_root.parent / "master-assets" / "cover-candidates" / "cover-frame-pool.json",
        slot_root.parent.parent / "master-assets" / "cover-candidates" / "cover-frame-pool.json",
        slot_root.parent / "master-assets" / "cover-frame-pool.json",
        slot_root.parent.parent / "master-assets" / "cover-frame-pool.json",
    ]
    for cp in cands:
        if cp.is_file():
            try:
                jd = json.loads(cp.read_text(encoding="utf-8"))
                if jd.get("audit_min_cheek_sym") is not None:
                    return float(jd["audit_min_cheek_sym"])
            except Exception:
                pass
    return 0.56


def audit_covers(
    covers_dir: Path,
    slot_root: Path,
    hard_failures: list[str],
    warnings: list[str],
    style_slot: str = "default",
    face_sheet_out: Path | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "covers_dir": rel_path(covers_dir),
        "video_orientation": "portrait",
        "pngs": {},
    }
    png_files = sorted(covers_dir.glob("*.png"))
    if not png_files:
        return report

    # Locked portrait-only platform cover pixel dimensions:
    # douyin = 1080x1920, xhs = 1242x1660, shipinhao = 1080x1440
    expected_cover_dims = {
        "douyin.png": (1080, 1920),
        "xhs.png": (1242, 1660),
        "shipinhao.png": (1080, 1440),
    }

    for pf in png_files:
        try:
            pinfo = ffprobe_json(pf)
            vs = next((s for s in pinfo.get("streams", []) if s.get("codec_type") == "video"), None)
            w, h = (int(vs.get("width", 0)), int(vs.get("height", 0))) if vs else (0, 0)
            report["pngs"][pf.name] = f"{w}x{h}"
            for suffix, exp_wh in expected_cover_dims.items():
                if pf.name.endswith(suffix) and (w, h) != exp_wh:
                    plat_cn = {"douyin.png": "抖音", "xhs.png": "小红书", "shipinhao.png": "视频号"}[suffix]
                    hard_failures.append(
                        f"竖版封面尺寸错误({plat_cn})：`{pf.name}` 为 {w}x{h}，必须严格为 {exp_wh[0]}x{exp_wh[1]}"
                    )
        except Exception as exc:
            hard_failures.append(f"封面读取失败 `{pf.name}`: {exc}")

    expected_ip = SLOT_ACCOUNT_MAP[style_slot]["ip_name"] if style_slot in SLOT_ACCOUNT_MAP else None
    other_ips = (
        [v["ip_name"] for k, v in SLOT_ACCOUNT_MAP.items() if k != style_slot]
        if style_slot in SLOT_ACCOUNT_MAP
        else []
    )
    if expected_ip:
        report["expected_ip_name"] = expected_ip

    spec_path = covers_dir / "cover-spec.json"
    has_contact_sheet = False
    if spec_path.is_file():
        spec_raw = spec_path.read_text(encoding="utf-8", errors="replace")
        if COINED_AMBIGUOUS_PHRASE_RE.search(spec_raw):
            hard_failures.append(
                f"封面文案含生造双关歧义词(`{spec_path.name}` 命中「{COINED_AMBIGUOUS_PHRASE_RE.search(spec_raw).group(0)}」)"
            )
        for wrong_ip in other_ips:
            if wrong_ip in spec_raw:
                hard_failures.append(
                    f"封面账号 IP 名串台违规 [{style_slot}->{expected_ip}]：`{spec_path.name}` 误写入其他号组名「{wrong_ip}」"
                )
        try:
            spec_data = json.loads(spec_raw)
            cs_rel = spec_data.get("contact_sheet")
            if cs_rel:
                svp = Path(os.environ.get("SVP_ROOT", Path.cwd()))
                if (svp / str(cs_rel)).is_file() or (slot_root / str(cs_rel)).is_file():
                    has_contact_sheet = True
        except Exception:
            pass

    # Search candidate materials/covers & master-assets/cover-candidates for contact-sheet / face-zoom-sheet
    mat_dirs = [
        slot_root / "materials" / "covers",
        slot_root.parent / "materials" / "covers",
        slot_root.parent / "master-assets" / "cover-candidates",
        slot_root.parent.parent / "master-assets" / "cover-candidates",
        slot_root.parent.parent / "master" / "materials" / "covers",
        slot_root.parent.parent / "materials" / "covers",
    ]
    for md in mat_dirs:
        if md.is_dir() and (list(md.glob("*contact*sheet*.*")) or list(md.glob("*face-zoom-sheet*.*"))):
            has_contact_sheet = True

    report["has_contact_sheet"] = has_contact_sheet
    if not has_contact_sheet:
        hard_failures.append(
            f"封面选帧流程缺失 [{rel_path(covers_dir)}]：未生成选片表 `materials/covers/contact-sheet.jpg`，严禁盲抽垂眼/露下齿废帧"
        )

    slot_mat_covers = slot_root / "materials" / "covers"
    html_files = sorted(slot_mat_covers.glob("*.html")) if slot_mat_covers.is_dir() else []
    for hf in html_files:
        htxt = hf.read_text(encoding="utf-8", errors="replace")
        h_body_m = re.search(r"<body\b[^>]*>([\s\S]*?)</body>", htxt, re.I)
        vis_txt = strip_html(
            re.sub(r"<(script|style)\b[\s\S]*?</\1>", "", h_body_m.group(1) if h_body_m else htxt, flags=re.I)
        )
        m_amb = COINED_AMBIGUOUS_PHRASE_RE.search(vis_txt)
        if m_amb:
            hard_failures.append(f"封面 HTML `{hf.name}` 含生造歧义词「{m_amb.group(0)}」")
        pol_hits = find_policy_sensitive_hits(vis_txt)
        if pol_hits:
            hard_failures.append(
                f"封面 HTML `{hf.name}` 含未屏蔽平台敏感词({', '.join(x['raw_word'] for x in pol_hits)})"
            )
        for wrong_ip in other_ips:
            if wrong_ip in vis_txt:
                hard_failures.append(
                    f"封面账号 IP 名混乱违规 `{hf.name}`：当前槽位应为「{expected_ip}」，却误印了其他号组 IP 名「{wrong_ip}」"
                )
        if expected_ip and expected_ip not in vis_txt:
            hard_failures.append(
                f"封面缺失对应账号 IP 名 `{hf.name}`：顶部居中刊头微标必须印本槽位精确账号 IP 名「{expected_ip}」，严禁自编泛栏目名或漏印"
            )

        # Overhead & horizontally centered cover title check (applies to ALL covers!)
        hf_low = hf.name.lower()
        max_overhead_top = 520.0 if "xhs" in hf_low else (440.0 if "shipinhao" in hf_low else 620.0)
        if not re.search(r"text-align\s*:\s*center", htxt, re.I):
            hard_failures.append(
                f"封面字幕未水平居中 `{hf.name}`：未检测到 `text-align: center`，封面字幕必须置于人物头顶上方且水平居中"
            )
        if re.search(r"justify-content\s*:\s*(?:flex-)?end", htxt, re.I):
            hard_failures.append(
                f"封面字幕 Flex 沉底违规 `{hf.name}`：检测到 `justify-content: flex-end`，封面字幕必须置于人物头顶上方水平居中"
            )
        for blk_m in re.finditer(r"([.#A-Za-z0-9_,\s-]+)\{([^}]*)\}", htxt):
            sel, css_b = blk_m.group(1), blk_m.group(2)
            bfs = parse_css_px(css_b, "font-size")
            is_hero_title = (bfs is not None and bfs >= 84.0) or bool(
                re.search(r"(?:main-?|cover-?|hero-?)title|headline", sel, re.I)
            )
            if is_hero_title:
                if re.search(r"(?<![A-Za-z-])bottom\s*:\s*\d+(?:\.\d+)?px", css_b, re.I):
                    hard_failures.append(
                        f"封面字幕沉底违规 `{hf.name}`(`{sel.strip()}`)：检测到 `bottom` 定位，封面字幕必须添加到人物头顶上方水平居中"
                    )
                for prop_n in ("top", "margin-top", "padding-top"):
                    btop = parse_css_px(css_b, prop_n)
                    if btop is not None and btop > max_overhead_top:
                        hard_failures.append(
                            f"封面字幕位置过低 `{hf.name}`(`{sel.strip()}`)：`{prop_n}={btop:.0f}px` 落在中下半屏(> {max_overhead_top:.0f}px)，必须置于人物头顶上方水平居中"
                        )
                ty_m = re.search(
                    r"translate(?:Y\(\s*(\d+(?:\.\d+)?)px|(?:3d)?\([^,)]+,\s*(\d+(?:\.\d+)?)px)",
                    css_b,
                    re.I,
                )
                if ty_m and float(ty_m.group(1) or ty_m.group(2)) > max_overhead_top:
                    hard_failures.append(
                        f"封面字幕 translateY 下移违规 `{hf.name}`(`{sel.strip()}`)：大字标题被下推至中下半屏，必须置于人物头顶上方水平居中"
                    )
        for inl_m in re.finditer(r'style=["\']([^"\']*)["\']', htxt, re.I):
            inl_css = inl_m.group(1)
            ifs = parse_css_px(inl_css, "font-size")
            if ifs is not None and ifs >= 84.0:
                if re.search(r"(?<![A-Za-z-])bottom\s*:\s*\d+(?:\.\d+)?px", inl_css, re.I):
                    hard_failures.append(
                        f"封面字幕行内样式沉底违规 `{hf.name}`：大字标题使用了 `bottom` 定位，必须置于人物头顶上方水平居中"
                    )
                for prop_n in ("top", "margin-top", "padding-top"):
                    itop = parse_css_px(inl_css, prop_n)
                    if itop is not None and itop > max_overhead_top:
                        hard_failures.append(
                            f"封面字幕行内样式位置过低 `{hf.name}`：`{prop_n}={itop:.0f}px` 落在中下半屏(> {max_overhead_top:.0f}px)，必须置于人物头顶上方水平居中"
                        )
                ity_m = re.search(
                    r"translate(?:Y\(\s*(\d+(?:\.\d+)?)px|(?:3d)?\([^,)]+,\s*(\d+(?:\.\d+)?)px)",
                    inl_css,
                    re.I,
                )
                if ity_m and float(ity_m.group(1) or ity_m.group(2)) > max_overhead_top:
                    hard_failures.append(
                        f"封面字幕行内 translateY 下移违规 `{hf.name}`：大字标题被下推至中下半屏，必须置于人物头顶上方水平居中"
                    )

        font_pxs = [float(x) for x in re.findall(r"font-size\s*:\s*(\d+(?:\.\d+)?)px", htxt, re.I)]
        max_fs = max(font_pxs) if font_pxs else 0.0
        req_fs = 110.0 if "xhs" in hf_low else (100.0 if "shipinhao" in hf_low else 104.0)
        if max_fs < req_fs:
            hard_failures.append(
                f"封面主标题字号过小 `{hf.name}`：最大字号仅 {max_fs:.0f}px(< {req_fs:.0f}px 商业杂志视觉锤下限)"
            )

        # Detect >=3 small bordered/filled tag pills
        small_pill_classes: set[str] = set()
        body_bg_avg: float | None = None
        has_photo_frame_crop = False
        for sb in re.findall(r"<style\b[^>]*>([\s\S]*?)</style>", htxt, re.I):
            bm = re.search(r"(?:body|\.canvas|\.page)\s*\{([^}]*)\}", sb, re.I)
            if bm and body_bg_avg is None:
                body_bg_avg = _parse_rgb_avg(bm.group(1))
            for cm in re.finditer(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}", sb):
                cn, cb = cm.group(1), cm.group(2)
                cfs = parse_css_px(cb, "font-size")
                if (
                    cfs is not None
                    and cfs <= 38.0
                    and re.search(r"border|background", cb, re.I)
                    and re.search(r"tag|pill|chip|badge|label", cn, re.I)
                ):
                    small_pill_classes.add(cn)
                if re.search(r"photo-frame|portrait-frame", cn, re.I) and "overflow: hidden" in cb.lower():
                    has_photo_frame_crop = True

        body_part = htxt[htxt.lower().find("<body") :] if "<body" in htxt.lower() else htxt
        pill_occurrences = 0
        for cn in small_pill_classes:
            pill_occurrences += len(
                re.findall(rf'class=["\'][^"\']*\b{re.escape(cn)}\b', body_part)
            )
        if pill_occurrences >= 3:
            hard_failures.append(
                f"封面网页卡片感违规 `{hf.name}`：堆砌了 {pill_occurrences} 个 `<=38px` 小胶囊标签(严禁 >=3 个小签对称排布)"
            )

        # Detect bare cutout PNG pasted on light background (RGB > 185)
        has_cutout_img = bool(
            re.search(r'<img\b[^>]*src=["\'][^"\']*(?:cutout|rembg|nobg|matting)[^"\']*\.png', body_part, re.I)
        )
        if body_bg_avg is not None and body_bg_avg > 185.0 and has_cutout_img and not has_photo_frame_crop:
            hard_failures.append(
                f"亮底裸抠像脏边缺陷 `{hf.name}`：浅色背景(RGB均值 {body_bg_avg:.0f} > 185)违规直接贴透明抠像 PNG，须改用矩形胶片相框实拍裁切"
            )

    # 3D FaceMesh CV Portrait Aesthetics Gate on rendered cover PNGs + 1:1 closeup sheet
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        min_sym_req = _resolve_adaptive_cover_min_sym(slot_root)
        portrait_checks: dict[str, Any] = {}
        zoom_tiles: list[Any] = []
        for pf in png_files:
            bgr_cov = cv2.imread(str(pf))
            if bgr_cov is None:
                continue
            f_meta = evaluate_portrait_bgr(bgr_cov, min_sym_override=min_sym_req)
            if f_meta is None:
                continue
            portrait_checks[pf.name] = f_meta
            if f_meta.get("has_face"):
                zoom_tiles.append(_crop_face_zoom_tile(bgr_cov, f_meta, pf.stem))
                if not f_meta["passed"]:
                    hard_failures.append(
                        f"封面人物面庞神态违规 `{pf.name}`(得分 {f_meta['score']:.1f})：{'；'.join(f_meta['vetoes'])} —— 必须运行 `qc_video.py select-cover-frames` 选用正对镜头、端正平视、口唇自然舒展的高分帧"
                    )
        if portrait_checks:
            report["portrait_cv_checks"] = portrait_checks
        if zoom_tiles and face_sheet_out is not None:
            face_sheet_out.parent.mkdir(parents=True, exist_ok=True)
            sheet_img = np.hstack(zoom_tiles) if len(zoom_tiles) > 1 else zoom_tiles[0]
            cv2.imwrite(str(face_sheet_out), sheet_img)
            report["cover_faces_sheet"] = rel_path(face_sheet_out)
    except Exception:
        pass

    return report


def _infer_content_archetype(pub_path: Path, data: dict[str, Any]) -> str:
    explicit = str(data.get("content_archetype", "") or "").strip()
    if explicit:
        return explicit
    # Check sibling script/storyboard.json or master-plan.json
    slot_root = pub_path.parent.parent
    for cand in [
        slot_root / "script" / "storyboard.json",
        slot_root / "script" / "master-plan.json",
        slot_root.parent.parent / "master" / "script" / "master-plan.json",
        slot_root / "topic" / "topic.json",
    ]:
        if cand.is_file():
            try:
                cd = json.loads(cand.read_text(encoding="utf-8"))
                if cd.get("content_archetype"):
                    return str(cd["content_archetype"])
            except Exception:
                pass
    # Infer from subtitles.html spoken transcript if present
    sub_f = slot_root / "film" / "scenes" / "subtitles.html"
    if sub_f.is_file():
        st = strip_html(sub_f.read_text(encoding="utf-8", errors="replace"))
        if not re.search(r"第一步|第二步|第三步|具体怎么做|解决方法|破局方法|这三招|操作步骤|清单", st):
            return "diagnostic_resonance"
    return "actionable_method"


def audit_publish_json(
    pub_path: Path, hard_failures: list[str], warnings: list[str], style_slot: str = "default"
) -> dict[str, Any]:
    data = json.loads(pub_path.read_text(encoding="utf-8"))
    archetype = _infer_content_archetype(pub_path, data)
    platforms = data.get("platforms", {})
    checked: dict[str, Any] = {"content_archetype": archetype}

    expected_meta = SLOT_ACCOUNT_MAP.get(style_slot)
    other_ips = (
        [v["ip_name"] for k, v in SLOT_ACCOUNT_MAP.items() if k != style_slot]
        if expected_meta
        else []
    )
    if expected_meta:
        decl_ip = str(data.get("account_ip_name") or "").strip()
        decl_grp = str(data.get("account_group") or "").strip()
        if decl_ip and decl_ip != expected_meta["ip_name"]:
            hard_failures.append(
                f"publish.json 账号 IP 名映射错误：槽位 `{style_slot}` 应绑定「{expected_meta['ip_name']}」，实际填为「{decl_ip}」"
            )
        if decl_grp and not decl_grp.upper().startswith(expected_meta["group_id"]):
            hard_failures.append(
                f"publish.json 账号组 ID 映射错误：槽位 `{style_slot}` 应绑定 `{expected_meta['group_id']}`，实际填为 `{decl_grp}`"
            )

    for plat, cfg in platforms.items():
        desc = str(cfg.get("desc", "") or "")
        title = str(cfg.get("title", "") or "")
        short_title = str(cfg.get("short_title", "") or "")
        cover_title = cfg.get("cover_title", "")
        if isinstance(cover_title, list):
            cover_title_str = " ".join(str(x) for x in cover_title)
        else:
            cover_title_str = str(cover_title or "")
        topics = str(cfg.get("topics", "") or "")
        topics_disp = str(cfg.get("topics_display", "") or "")

        all_copy = f"{title} {short_title} {cover_title_str} {desc}"
        for wrong_ip in other_ips:
            if wrong_ip in all_copy or wrong_ip in topics or wrong_ip in topics_disp:
                hard_failures.append(
                    f"publish.json [{plat}] 账号 IP 名串台违规：槽位 `{style_slot}`({expected_meta['ip_name']}) 文案/话题误出现「{wrong_ip}」"
                )
        pol_copy_hits = find_policy_sensitive_hits(f"{all_copy} {topics} {topics_disp}")
        if pol_copy_hits:
            hard_failures.append(
                f"publish.json [{plat}] 文案或话题标签含平台违规/跨站敏感词: {', '.join(dict.fromkeys(x['raw_word'] for x in pol_copy_hits))}"
            )
        hits: list[str] = []
        for pat in DESC_SECONDS_PATTERNS:
            for m in pat.finditer(desc):
                hits.append(m.group(0))
        if hits:
            hard_failures.append(
                f"publish.json [{plat}] 视频描述违规提及秒数/时间点/片长: {', '.join(dict.fromkeys(hits))}"
            )

        if archetype == "diagnostic_resonance":
            fp_hits = FALSE_PROMISE_DIAGNOSTIC_RE.findall(all_copy)
            if fp_hits:
                hard_failures.append(
                    f"违反诚实钩子契约 [{plat}]：成片属纯诊断共鸣(`diagnostic_resonance`)，文案却伪造片中不存在的方法/清单承诺({', '.join(dict.fromkeys(fp_hits))})"
                )

        amb_hits = COINED_AMBIGUOUS_PHRASE_RE.findall(all_copy)
        if amb_hits:
            hard_failures.append(
                f"publish.json [{plat}] 含生造双关歧义词: {', '.join(dict.fromkeys(amb_hits))}"
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
                hard_failures.append(f"publish.json [xhs] 标题长度={len(title)} 超过 20 字硬上限")
            elif len(title) > 18:
                warnings.append(f"publish.json [xhs] 标题长度={len(title)} 超过 18 字保守建议")
        elif plat == "douyin":
            if len(title) > 30:
                hard_failures.append(f"publish.json [douyin] 标题长度={len(title)} 超过 30 字硬上限")
            topic_list = [t.strip() for t in topics.split(",") if t.strip()]
            if len(topic_list) > 5:
                hard_failures.append(f"publish.json [douyin] 话题数={len(topic_list)} 超过 5 个硬上限")
        checked[plat] = {"title_len": len(title), "desc_len": len(desc), "seconds_hits": hits}
    return checked


def audit_rendered_frames_pixels(
    video: Path,
    duration: float,
    style_slot: str,
    film_dir: Path | None,
    hard_failures: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    """Full-film 1fps streaming pixel scan (including v4!) + L3 void/topbar + PiP 50ms head/tail pixel liveness."""
    if duration < 3.0:
        return {"skipped": True, "reason": "too_short"}

    tr_windows: list[tuple[float, float]] = []
    l3_midpoints: list[float] = []
    pip_liveness_targets: list[tuple[str, float, list[int]]] = []
    if film_dir and (film_dir / "film.html").is_file():
        ht = (film_dir / "film.html").read_text(encoding="utf-8", errors="replace")
        css_rules_p: dict[str, str] = {}
        kf_map_p: dict[str, str] = {}
        for sb_p in re.findall(r"<style\b[^>]*>([\s\S]*?)</style>", ht, flags=re.I):
            kf_map_p.update(extract_keyframes_blocks(sb_p))
            sb_cl = re.sub(r"@keyframes\s+[A-Za-z0-9_-]+\s*\{(?:[^{}]|\{[^{}]*\})*\}", "", sb_p, flags=re.I)
            for cm_p in re.finditer(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}", sb_cl):
                css_rules_p[cm_p.group(1)] = css_rules_p.get(cm_p.group(1), "") + ";" + cm_p.group(2)

        for tm in re.finditer(
            r'<section[^>]*id=["\'][^"\']*(?:transition|fx-trans)[^"\']*["\'][^>]*>(.*?)</section>',
            ht,
            flags=re.I | re.S,
        ):
            for tc in parse_clips_in_section(tm.group(1)):
                t_s = tc["at"]
                t_e = tc["end"] if tc["end"] is not None else (t_s + 0.6)
                tr_windows.append((t_s - 0.12, t_e + 0.12))
        ms_m = re.search(r'<section[^>]*id=["\']main-stage["\'][^>]*>(.*?)</section>', ht, flags=re.I | re.S)
        if ms_m:
            for mc in parse_clips_in_section(ms_m.group(1)):
                if mc["tag"] == "video":
                    vh_px = parse_css_px(mc.get("style", ""), "height")
                    if vh_px is not None and vh_px <= 960.0:
                        mc_e = mc["end"] if mc["end"] is not None else (mc["at"] + (mc["dur"] or 2.5))
                        l3_midpoints.append(round((mc["at"] + mc_e) * 0.5, 2))
        pip_m_p = re.search(r'<section[^>]*id=["\']speaker-pip["\'][^>]*>(.*?)</section>', ht, flags=re.I | re.S)
        if pip_m_p:
            for pc_p in parse_clips_in_section(pip_m_p.group(1)):
                pc_e = pc_p["end"] if pc_p["end"] is not None else min(duration, pc_p["at"] + 3.0)
                m_css_p = ";".join([css_rules_p.get(c, "") for c in pc_p.get("classes", [])] + [pc_p.get("style", "")])
                bl = parse_css_px(m_css_p, "left", 0.0) or 0.0
                bt = parse_css_px(m_css_p, "top", 0.0) or 0.0
                bw = parse_css_px(m_css_p, "width", 1080.0) or 1080.0
                bh = parse_css_px(m_css_p, "height", 1920.0) or 1920.0
                it, ir, ib, il = resolve_pip_steady_inset(m_css_p, kf_map_p, bw, bh)
                vbox = [int(round(bl + il)), int(round(bt + it)), int(round(max(24.0, bw - il - ir))), int(round(max(24.0, bh - it - ib)))]
                for t_edge, lbl_edge in ((pc_p["at"] + 0.05, "head+50ms"), (pc_e - 0.05, "tail-50ms")):
                    if 0.06 < t_edge < (duration - 0.06) and not any(ws <= t_edge <= we for ws, we in tr_windows):
                        pip_liveness_targets.append((f"{pc_p['id']}({lbl_edge})", round(t_edge, 3), vbox))

    # 1) Single-pass 1fps streaming grayscale scan at 180x320 across ALL slots (including v4!)
    sw, sh = 180, 320
    f_sz = sw * sh
    stream_cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-vf",
        f"fps=1,scale={sw}:{sh},format=gray",
        "-f",
        "rawvideo",
        "-",
    ]
    proc = run_cmd_bytes(stream_cmd)
    if proc.returncode != 0 or len(proc.stdout) < f_sz:
        return {"skipped": True, "reason": "decode_failed"}

    n_secs = max(1, min(int(math.ceil(duration)), len(proc.stdout) // f_sz))
    effective_n = max(1, n_secs - 2)  # Exclude last 2s outro fade-to-black
    void_hits: list[str] = []
    topbar_hits: list[str] = []
    letterbox_secs: list[int] = []
    black_ratios: list[float] = []
    cur_lb_run = 0
    max_lb_run = 0

    for sec_i in range(effective_n):
        t_val = sec_i + 0.5
        if any(ws <= t_val <= we for ws, we in tr_windows):
            cur_lb_run = 0
            continue
        buf = proc.stdout[sec_i * f_sz : (sec_i + 1) * f_sz]
        # At 180x320 (1 row = 6px on 1080x1920):
        # top_bar y=0..138px -> rows 0..23
        # lb_top_matte y=0..420px -> rows 0..70
        # lb_mid_strip y=468..900px -> rows 78..150
        # upper_stage y=186..840px -> rows 31..140
        # lower_stage y=882..1302px -> rows 147..217
        # lb_bot_matte y=936..1440px -> rows 156..240
        top_px = buf[0 : 23 * sw]
        lb_top = buf[0 : 70 * sw]
        lb_mid = buf[78 * sw : 150 * sw]
        upper_px = buf[31 * sw : 140 * sw]
        lower_px = buf[147 * sw : 217 * sw]
        lb_bot = buf[156 * sw : 240 * sw]

        frame_black_ratio = sum(1 for p in buf if p < 16) / float(f_sz)
        black_ratios.append(frame_black_ratio)

        lb_top_dark = sum(1 for p in lb_top if p < 18) / max(1, len(lb_top))
        lb_bot_dark = sum(1 for p in lb_bot if p < 20) / max(1, len(lb_bot))
        lb_mid_mean = sum(lb_mid) / max(1, len(lb_mid))
        lb_mid_std = math.sqrt(sum((p - lb_mid_mean) ** 2 for p in lb_mid) / max(1, len(lb_mid)))

        is_narrow_lb = lb_top_dark > 0.90 and lb_bot_dark > 0.84 and lb_mid_std > 14.0
        if is_narrow_lb:
            letterbox_secs.append(sec_i)
            cur_lb_run += 1
            max_lb_run = max(max_lb_run, cur_lb_run)
        else:
            cur_lb_run = 0

        top_mean = sum(top_px) / max(1, len(top_px))
        top_std = math.sqrt(sum((p - top_mean) ** 2 for p in top_px) / max(1, len(top_px)))
        upper_mean = sum(upper_px) / max(1, len(upper_px))
        upper_std = math.sqrt(sum((p - upper_mean) ** 2 for p in upper_px) / max(1, len(upper_px)))
        lower_mean = sum(lower_px) / max(1, len(lower_px))
        lower_dark_ratio = sum(1 for p in lower_px if p < 20) / max(1, len(lower_px))
        lower_bright_ratio = sum(1 for p in lower_px if p > 52) / max(1, len(lower_px))

        if style_slot != "v4":
            if (
                not is_narrow_lb
                and upper_mean > 40.0
                and upper_std > 18.0
                and lower_dark_ratio > 0.90
                and lower_bright_ratio < 0.042
            ):
                void_hits.append(
                    f"t={t_val:.1f}s(上半屏亮度={upper_mean:.0f}, 下半屏 y=880..1300px 死黑占比={lower_dark_ratio:.0%}, 有效高亮={lower_bright_ratio:.1%})"
                )

        if lower_mean < 28.0 and lower_dark_ratio > 0.72 and top_mean > 58.0 and top_std > 16.0:
            topbar_hits.append(f"t={t_val:.1f}s(顶栏 y<136px 亮度={top_mean:.0f}, 下半屏暗底={lower_mean:.0f})")

    lb_ratio = len(letterbox_secs) / max(1, effective_n)
    mean_black_ratio = sum(black_ratios) / max(1, len(black_ratios))
    lb_run_limit = 7 if style_slot == "v4" else 5
    lb_ratio_limit = 0.36 if style_slot == "v4" else 0.25

    if max_lb_run > lb_run_limit or lb_ratio > lb_ratio_limit:
        hard_failures.append(
            f"成片像素级「单窄条黑边霸屏」缺陷 [{style_slot}]：2.39:1 窄带遮幅占全片 {lb_ratio:.0%}(上限 {lb_ratio_limit:.0%})，最长连续窄黑带 {max_lb_run}s(上限 {lb_run_limit}s) —— 严禁一条小横带配上下超 70% 死黑从头挂到尾！"
        )
    if style_slot == "v4" and mean_black_ratio > 0.62:
        hard_failures.append(
            f"v4(S04) 成片像素级全片死黑空旷缺陷：全片平均纯黑像素占比高达 {mean_black_ratio:.0%}(> 62% 上限)，须引入 L1/PF3 满幅暗角人像、L4 三联画胶片格与暗金光影空间场充实竖屏画幅"
        )
    if void_hits:
        hard_failures.append(
            f"成片像素级「半屏死黑空洞」缺陷：{'; '.join(void_hits[:3])} —— 上半屏放横屏画面但下半屏主叙事区大面积纯黑留空，必须填充具象业务卡片/对照图解或改用竖屏满幅构图"
        )
    if topbar_hits:
        hard_failures.append(
            f"成片分屏视频侵入顶部状态栏禁区：{'; '.join(topbar_hits[:3])} —— L3 上分屏视频未下移避让顶部 y<180px 状态栏/灵动岛禁区"
        )

    # 2) Speaker-PiP 50ms head/tail pixel liveness check (catches premature avatar vanish leaving empty ring!)
    pip_dead_hits: list[str] = []
    if pip_liveness_targets:
        p_cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
        for _, pt_s, _ in pip_liveness_targets[:12]:
            p_cmd += ["-ss", f"{pt_s:.3f}", "-i", str(video)]
        n_pt = min(12, len(pip_liveness_targets))
        p_vf = [f"[{i}:v]scale=540:960,format=gray[pg{i}]" for i in range(n_pt)]
        if n_pt == 1:
            p_map = "[pg0]"
        else:
            p_vf.append(f"{''.join(f'[pg{i}]' for i in range(n_pt))}vstack=inputs={n_pt}[pgout]")
            p_map = "[pgout]"
        p_cmd += ["-filter_complex", ";".join(p_vf), "-map", p_map, "-frames:v", "1", "-f", "rawvideo", "-"]
        p_proc = run_cmd_bytes(p_cmd)
        pf_sz = 540 * 960
        if p_proc.returncode == 0 and len(p_proc.stdout) >= pf_sz:
            avail_pt = min(n_pt, len(p_proc.stdout) // pf_sz)
            for idx_p in range(avail_pt):
                lbl_p, pt_s, vbox_p = pip_liveness_targets[idx_p]
                fbuf = p_proc.stdout[idx_p * pf_sz : (idx_p + 1) * pf_sz]
                # Sample inner 60% core of PiP box at 1/2 scale (540x960)
                bx, by, bw_p, bh_p = [v // 2 for v in vbox_p]
                ix1 = max(0, bx + int(bw_p * 0.20))
                ix2 = min(539, bx + int(bw_p * 0.80))
                iy1 = max(0, by + int(bh_p * 0.20))
                iy2 = min(959, by + int(bh_p * 0.80))
                patch_vals = [
                    fbuf[ry * 540 + rx] for ry in range(iy1, max(iy1 + 1, iy2)) for rx in range(ix1, max(ix1 + 1, ix2))
                ]
                if patch_vals:
                    p_mean = sum(patch_vals) / len(patch_vals)
                    p_std = math.sqrt(sum((v - p_mean) ** 2 for v in patch_vals) / len(patch_vals))
                    if p_std < 12.0:
                        pip_dead_hits.append(f"{lbl_p}@{pt_s:.2f}s(框内纹理std={p_std:.1f}<12，退化为空底板/空圈)")
    if pip_dead_hits:
        hard_failures.append(
            f"成片像素级「PiP 人物头像早退/空框穿帮」缺陷：{'; '.join(pip_dead_hits[:4])} —— 挂件首尾 50ms 框内无人物纹理！"
        )

    return {
        "scanned_seconds": effective_n,
        "letterbox_frame_ratio": round(lb_ratio, 3),
        "max_letterbox_run_sec": max_lb_run,
        "mean_frame_black_ratio": round(mean_black_ratio, 3),
        "void_hits": void_hits,
        "topbar_hits": topbar_hits,
        "pip_dead_hits": pip_dead_hits,
    }


def _infer_film_timeline_duration(film_dir: Path) -> float:
    film_html = film_dir / "film.html"
    max_t = 0.0
    if film_html.is_file():
        ht = film_html.read_text(encoding="utf-8", errors="replace")
        for tag_sec in ("main-stage", "subtitles", "voice-track"):
            sm = re.search(rf'<section[^>]*id=["\']{tag_sec}["\'][^>]*>(.*?)</section>', ht, flags=re.I | re.S)
            if not sm:
                continue
            if tag_sec == "voice-track":
                for ac in parse_audio_tags_in_section(sm.group(1)):
                    if ac.get("end") is not None:
                        max_t = max(max_t, float(ac["end"]))
                    elif ac.get("dur") is not None:
                        max_t = max(max_t, float(ac.get("at") or 0.0) + float(ac["dur"]))
                    else:
                        af = film_dir / ac["base_src"]
                        if af.is_file():
                            adur = float(ffprobe_json(af).get("format", {}).get("duration", 0) or 0)
                            max_t = max(max_t, float(ac.get("at") or 0.0) + max(0.0, adur - float(ac.get("t_in") or 0.0)))
            else:
                for cc in parse_clips_in_section(sm.group(1)):
                    if cc.get("end") is not None:
                        max_t = max(max_t, float(cc["end"]))
                    elif cc.get("dur") is not None:
                        max_t = max(max_t, float(cc.get("at") or 0.0) + float(cc["dur"]))
    if max_t <= 0.0:
        sub_f = film_dir / "scenes" / "subtitles.html"
        if sub_f.is_file():
            ends = [
                float(m[1])
                for m in re.findall(r"\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,", sub_f.read_text(encoding="utf-8", errors="replace"))
            ]
            if ends:
                max_t = max(ends) + 1.0
    return max_t if max_t > 0 else 30.0


def cmd_select_cover_frames(args: argparse.Namespace) -> int:
    """Scan source speaker video with offline YuNet + 478-pt 3D FaceMesh and export camera-facing natural portrait pool."""
    video_p = Path(args.video)
    if not video_p.is_file():
        print(f"error: video not found: {video_p}", file=sys.stderr)
        return 1
    models = _get_face_models()
    if models is None:
        print("error: offline YuNet or OpenFilm face.task model missing in workspace", file=sys.stderr)
        return 1

    import cv2  # type: ignore
    import numpy as np  # type: ignore

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fps_scan = max(2.0, min(10.0, float(args.fps)))
    probe = ffprobe_json(video_p)
    dur = float((probe.get("format") or {}).get("duration") or 0.0)
    vs = next((s for s in (probe.get("streams") or []) if s.get("codec_type") == "video"), None)
    vw = int((vs or {}).get("width") or 1920)
    vh = int((vs or {}).get("height") or 1080)
    scan_w = min(960, vw)
    scan_h = max(180, int(round(vh * scan_w / max(1, vw))))
    if scan_h % 2 == 1:
        scan_h += 1

    def _build_scan(hw_flags: list[str]) -> list[str]:
        return [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            *hw_flags,
            "-i",
            str(video_p),
            "-vf",
            f"fps={fps_scan:.2f},scale={scan_w}:{scan_h}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-",
        ]

    proc = run_cmd_bytes(_build_scan(["-hwaccel", "cuda"]) if has_cuda_hwaccel() else _build_scan([]))
    if proc.returncode != 0 or len(proc.stdout) < scan_w * scan_h * 3:
        proc = run_cmd_bytes(_build_scan([]))
    frame_sz = scan_w * scan_h * 3
    n_frames = len(proc.stdout) // max(1, frame_sz)
    if n_frames == 0:
        print("error: failed to decode frames from source video", file=sys.stderr)
        return 1

    raw_evals: list[dict[str, Any]] = []
    prev_face_gray: Any = None
    for idx in range(n_frames):
        t_s = round(idx / fps_scan, 2)
        if t_s < 0.25 or (dur > 2.0 and t_s > dur - 0.35):
            continue
        bgr = np.frombuffer(proc.stdout[idx * frame_sz : (idx + 1) * frame_sz], dtype=np.uint8).reshape(
            (scan_h, scan_w, 3)
        )
        ev = evaluate_portrait_bgr(bgr, min_sym_override=0.0)
        if not ev or not ev.get("has_face"):
            prev_face_gray = None
            continue
        fx, fy, fw, fh = ev["face_box_px"]
        x1, y1 = max(0, fx), max(0, fy)
        x2, y2 = min(scan_w, fx + fw), min(scan_h, fy + fh)
        cur_gray = cv2.resize(cv2.cvtColor(bgr[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY), (64, 64)) if (x2 > x1 and y2 > y1) else None
        motion_diff = 0.0
        if cur_gray is not None and prev_face_gray is not None:
            motion_diff = float(np.mean(np.abs(cur_gray.astype(np.float32) - prev_face_gray.astype(np.float32))))
        prev_face_gray = cur_gray
        ev["t"] = t_s
        ev["frame_idx"] = idx
        ev["motion_diff"] = round(motion_diff, 2)
        raw_evals.append(ev)

    if not raw_evals:
        print("error: no speaker faces detected in video", file=sys.stderr)
        return 1

    syms = np.array([e["cheek_sym"] for e in raw_evals], dtype=np.float32)
    ears = np.array([e["min_ear"] for e in raw_evals], dtype=np.float32)
    lips = np.array([e["lip_fullness"] for e in raw_evals], dtype=np.float32)
    p90_sym = float(np.percentile(syms, 90))
    p75_sym = float(np.percentile(syms, 75))
    has_frontal_turns = p90_sym >= 0.65
    select_min_sym = max(0.58, min(0.68, p75_sym)) if has_frontal_turns else max(0.42, float(np.percentile(syms, 72)))
    audit_min_sym = 0.56 if has_frontal_turns else round(max(0.40, select_min_sym - 0.04), 2)
    min_ear_adapt = max(0.185, min(0.212, float(np.percentile(ears, 40))))
    min_lip_adapt = max(0.45, min(0.485, float(np.percentile(lips, 14))))

    qualified: list[dict[str, Any]] = []
    for ev in raw_evals:
        if (
            ev["cheek_sym"] >= select_min_sym
            and abs(ev["roll_deg"]) <= 9.2
            and 0.188 <= ev["pitch_ratio"] <= 0.280
            and ev["min_ear"] >= max(0.196, min_ear_adapt)
            and ev["ear_asym"] <= 0.228
            and abs(ev["gaze_x"] - 0.528) <= 0.060
            and 0.29 <= ev["gaze_y"] <= 0.56
            and ev["glare_ratio"] <= 0.08
            and ev["mar_inner"] <= 0.156
            and min_lip_adapt <= ev["lip_fullness"] <= 0.68
            and ev["mouth_width_ratio"] >= 0.415
            and ev["corner_asym"] <= 0.075
            and ev["hand_intrusion"] <= 0.20
        ):
            steady_bonus = max(0.0, 4.5 * (1.0 - min(1.0, ev["motion_diff"] / 9.0)))
            ev["rank_score"] = round(ev["score"] + steady_bonus, 2)
            qualified.append(ev)

    if len(qualified) < 18:
        relax_sym = max(0.565 if has_frontal_turns else 0.40, select_min_sym - 0.04)
        qualified = []
        for ev in raw_evals:
            if (
                ev["cheek_sym"] >= relax_sym
                and abs(ev["roll_deg"]) <= 9.5
                and 0.185 <= ev["pitch_ratio"] <= 0.285
                and ev["min_ear"] >= 0.195
                and ev["ear_asym"] <= 0.235
                and abs(ev["gaze_x"] - 0.525) <= 0.060
                and 0.28 <= ev["gaze_y"] <= 0.57
                and ev["glare_ratio"] <= 0.09
                and ev["mar_inner"] <= 0.160
                and 0.448 <= ev["lip_fullness"] <= 0.69
                and ev["mouth_width_ratio"] >= 0.408
                and ev["corner_asym"] <= 0.080
                and ev["hand_intrusion"] <= 0.22
            ):
                steady_bonus = max(0.0, 4.0 * (1.0 - min(1.0, ev["motion_diff"] / 9.0)))
                ev["rank_score"] = round(ev["score"] + steady_bonus, 2)
                qualified.append(ev)

    qualified.sort(key=lambda x: -x["rank_score"])
    want_n = max(6, int(args.count))
    picked: list[dict[str, Any]] = []
    for min_gap in (1.4, 0.9, 0.55):
        for cand in qualified:
            if len(picked) >= want_n:
                break
            if any(abs(cand["t"] - p["t"]) < min_gap for p in picked):
                continue
            picked.append(cand)
        if len(picked) >= min(want_n, 18):
            break

    # Clean old cand-*.jpg files before single-pass exact-frame extraction (zero -ss GOP seek drift!)
    for old_c in out_dir.glob("cand-*.jpg"):
        old_c.unlink(missing_ok=True)
    picked_by_time = sorted(picked, key=lambda x: x["frame_idx"])
    verified_cands: list[dict[str, Any]] = []
    zoom_tiles: list[Any] = []

    if picked_by_time:
        sel_expr = "+".join(f"eq(n\\,{c['frame_idx']})" for c in picked_by_time)
        tmp_pat = str(out_dir / "_exact_%03d.jpg")

        def _build_exact_ext(hw_flags: list[str]) -> list[str]:
            return [
                "ffmpeg",
                "-nostdin",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                *hw_flags,
                "-i",
                str(video_p),
                "-vf",
                f"fps={fps_scan:.2f},select='{sel_expr}'",
                "-fps_mode",
                "passthrough",
                "-q:v",
                "2",
                tmp_pat,
            ]

        ext_p = run_cmd(_build_exact_ext(["-hwaccel", "cuda"]) if has_cuda_hwaccel() else _build_exact_ext([]))
        if ext_p.returncode != 0:
            run_cmd(_build_exact_ext([]))

        tmp_jpgs = sorted(out_dir.glob("_exact_*.jpg"))
        # Rank order mapping
        rank_order_map = {id(c): r_i for r_i, c in enumerate(picked, start=1)}
        paired_items: list[tuple[int, dict[str, Any], Path]] = []
        for cand_c, tmp_f in zip(picked_by_time, tmp_jpgs):
            paired_items.append((rank_order_map[id(cand_c)], cand_c, tmp_f))
        paired_items.sort(key=lambda x: x[0])

        for _, cand, tmp_f in paired_items:
            t_val = cand["t"]
            full_bgr = cv2.imread(str(tmp_f))
            full_ev = evaluate_portrait_bgr(full_bgr, min_sym_override=audit_min_sym) if full_bgr is not None else None
            if not full_ev or not full_ev.get("has_face"):
                tmp_f.unlink(missing_ok=True)
                continue
            new_rank = len(verified_cands) + 1
            fname = f"cand-{new_rank:02d}-{t_val:06.2f}s.jpg"
            fpath = out_dir / fname
            tmp_f.replace(fpath)
            full_ev["rank"] = new_rank
            full_ev["t"] = t_val
            full_ev["file"] = rel_path(fpath)
            full_ev["rank_score"] = round(0.5 * cand["rank_score"] + 0.5 * full_ev["score"], 2)
            dh_full = compute_visual_dhash(fpath)
            full_ev["dhash"] = f"{dh_full:016x}" if dh_full is not None else None
            verified_cands.append(full_ev)
        for leftover in out_dir.glob("_exact_*.jpg"):
            leftover.unlink(missing_ok=True)

    verified_cands.sort(key=lambda x: (-int(bool(x["passed"])), -x["rank_score"]))
    for idx_v, vc_it in enumerate(verified_cands, start=1):
        vc_it["rank"] = idx_v
        fbgr_v = cv2.imread(str(Path(vc_it["file"])))
        if fbgr_v is not None:
            zoom_tiles.append(_crop_face_zoom_tile(fbgr_v, vc_it, f"#{idx_v:02d} t={vc_it['t']:.2f}s"))

    # Write 420x480 closeup face-zoom-sheet.jpg AND contact-sheet.jpg alias
    zoom_sheet_p = out_dir / "face-zoom-sheet.jpg"
    contact_sheet_p = out_dir / "contact-sheet.jpg"
    if zoom_tiles:
        cols = min(4, len(zoom_tiles))
        pad_n = (cols - (len(zoom_tiles) % cols)) % cols
        for _ in range(pad_n):
            zoom_tiles.append(np.zeros((480, 420, 3), dtype=np.uint8))
        rows_img = [np.hstack(zoom_tiles[r : r + cols]) for r in range(0, len(zoom_tiles), cols)]
        grid_img = np.vstack(rows_img) if len(rows_img) > 1 else rows_img[0]
        cv2.imwrite(str(zoom_sheet_p), grid_img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        cv2.imwrite(str(contact_sheet_p), grid_img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

    # Pre-allocate orthogonal non-overlapping frames across slots/platforms
    passed_pool = [c for c in verified_cands if c["passed"]] or verified_cands
    allocations: dict[str, dict[str, Any]] = {}
    plats = ["douyin", "xhs", "shipinhao"]
    if args.mode == "matrix":
        slots_order = ["master", "v1", "v2", "v3", "v4"]
        used_ts: list[float] = []
        # Round-robin across slots so all 5 slots get top-tier frontal faces!
        for p_idx, plat in enumerate(plats):
            for s_name in slots_order:
                slot_dict = allocations.setdefault(s_name, {})
                slot_ts = [v["t"] for v in slot_dict.values()]
                chosen = next(
                    (
                        c
                        for c in passed_pool
                        if all(abs(c["t"] - ut) >= 1.1 for ut in used_ts)
                        and all(abs(c["t"] - st) >= 2.4 for st in slot_ts)
                    ),
                    None,
                )
                if chosen is None:
                    chosen = next((c for c in passed_pool if c["t"] not in used_ts), passed_pool[p_idx % len(passed_pool)])
                slot_dict[plat] = chosen
                used_ts.append(chosen["t"])
    else:
        slot_dict = {}
        used_ts_s: list[float] = []
        for idx_p, plat in enumerate(plats):
            chosen = next(
                (c for c in passed_pool if all(abs(c["t"] - ut) >= 2.5 for ut in used_ts_s)),
                passed_pool[min(idx_p, len(passed_pool) - 1)],
            )
            slot_dict[plat] = chosen
            used_ts_s.append(chosen["t"])
        allocations["single"] = slot_dict

    pool_report = {
        "video": rel_path(video_p),
        "duration_sec": round(dur, 2),
        "scanned_frames": len(raw_evals),
        "has_frontal_turns": has_frontal_turns,
        "cheek_sym_p75": round(p75_sym, 3),
        "cheek_sym_p90": round(p90_sym, 3),
        "select_min_cheek_sym": round(select_min_sym, 3),
        "audit_min_cheek_sym": round(audit_min_sym, 3),
        "face_zoom_sheet": rel_path(zoom_sheet_p),
        "contact_sheet": rel_path(contact_sheet_p),
        "candidate_count": len(verified_cands),
        "recommended_allocations": allocations,
        "candidates": verified_cands,
    }
    pool_json_p = out_dir / "cover-frame-pool.json"
    pool_json_p.write_text(json.dumps(pool_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "video": pool_report["video"],
                "scanned_frames": pool_report["scanned_frames"],
                "has_frontal_turns": has_frontal_turns,
                "audit_min_cheek_sym": pool_report["audit_min_cheek_sym"],
                "candidate_count": len(verified_cands),
                "face_zoom_sheet": pool_report["face_zoom_sheet"],
                "pool_json": rel_path(pool_json_p),
                "recommended_allocations": {
                    k: {pk: {"t": pv["t"], "file": pv["file"], "score": pv["rank_score"], "cheek_sym": pv["cheek_sym"], "roll_deg": pv["roll_deg"]} for pk, pv in v.items()}
                    for k, v in allocations.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_probe_speaker_focus(args: argparse.Namespace) -> int:
    vid = Path(args.video)
    if not vid.is_file():
        print(f"error: video not found: {vid}", file=sys.stderr)
        return 1
    res = probe_speaker_horizontal_focus(vid, samples=args.samples)
    if args.update_plan:
        plan_p = Path(args.update_plan)
        plan_data: dict[str, Any] = {}
        if plan_p.is_file():
            try:
                plan_data = json.loads(plan_p.read_text(encoding="utf-8"))
            except Exception:
                plan_data = {}
        plan_data["speaker_focus"] = {
            "face_cx_pct": res["face_cx_pct"],
            "head_top_v": res["head_top_v"],
            "chin_v": res["chin_v"],
            "span_v": res["span_v"],
            "recommended_object_position": res["recommended_object_position"],
        }
        plan_p.parent.mkdir(parents=True, exist_ok=True)
        plan_p.write_text(json.dumps(plan_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        res["updated_plan"] = rel_path(plan_p)
    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def cmd_preflight_film(args: argparse.Namespace) -> int:
    film_dir = Path(args.film_dir)
    if not (film_dir / "film.html").is_file():
        print(f"error: film.html not found in {film_dir}", file=sys.stderr)
        return 1
    duration = args.duration if args.duration else _infer_film_timeline_duration(film_dir)
    style_slot = detect_style_slot(film_dir / "preflight.mp4", film_dir, args.style)
    hard_failures: list[str] = []
    warnings: list[str] = []
    film_checks, _, _, _, _ = audit_film_dir(film_dir, duration, style_slot, hard_failures, warnings)
    report = {
        "mode": "preflight-film",
        "film_dir": rel_path(film_dir),
        "style_slot": style_slot,
        "estimated_duration_sec": round(duration, 2),
        "film_checks": film_checks,
        "hard_failures": hard_failures,
        "warnings": warnings,
        "passed": len(hard_failures) == 0,
    }
    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if hard_failures and not args.no_fail:
        return 2
    return 0


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
            hard_failures.append(
                f"成片分辨率为 {w}x{h}，本工作区统一只制作竖版 1080x1920(9:16)，不制作横版视频"
            )

    film_dir = Path(args.film_dir) if args.film_dir else None
    style_slot = detect_style_slot(video, film_dir, args.style)

    full_audio = analyze_audio_segment(video)
    lufs = full_audio["integrated_lufs"]
    lra = full_audio["lra_lu"]
    tp = full_audio["true_peak_dbtp"]
    wall_samples = full_audio["limiter_wall_samples_0_to_2db"]
    wall_per_sec = wall_samples / max(1.0, duration)

    if lufs is not None and not (-16.5 <= lufs <= -12.0):
        warnings.append(f"成片综合响度 {lufs} LUFS 偏离 -14 LUFS 目标区间(-16.5..-12.0)")
    if tp is not None and tp > -1.0:
        hard_failures.append(f"成片真峰值 {tp} dBTP 超过 -1.0 dBTP 安全红线（削波失真风险）")

    # Note: EBU R128 LRA uses 3s short-term windows (clips <30s or steady broadcast-leveled speech naturally measure 1.8~4.0 LU with 0 wall samples);
    # brickwall crush happens when unconditioned voice slams the ceiling (wall_per_sec > 85 or >=30s clip with both low LRA and >40/s ceiling hits).
    lra_min = 3.3 if style_slot == "v1" else 3.6
    if duration >= 30.0 and lra is not None and lra < lra_min and wall_per_sec > 40.0:
        hard_failures.append(
            f"人声动态被砖墙限幅器压死：成片 LRA={lra} LU(< {lra_min} LU) 且伴随高频限幅贴顶({wall_per_sec:.0f}/s)，请先对原声执行 `qc_video.py prepare-voice` 前置 3:1 压缩润色"
        )
    if duration >= 10.0 and wall_per_sec > 85.0:
        hard_failures.append(
            f"砖墙限幅贴顶过载：0~-2dB 贴墙采样达 {wall_samples} 个({wall_per_sec:.0f}/s > 85/s 红线)，听感紧绷轰头"
        )

    # First-3.5s quiet warm-up chatter check
    if duration >= 12.0 and style_slot != "v4":
        head_audio = analyze_audio_segment(video, ss=0.0, dur=3.5)
        head_mean = head_audio.get("mean_volume_db")
        full_mean = full_audio.get("mean_volume_db")
        if head_mean is not None and full_mean is not None and (full_mean - head_mean) > 7.5:
            hard_failures.append(
                f"前 3.5 秒低音量冷场/场外搭话未裁净：首 3.5s 均值({head_mean} dB)比全片({full_mean} dB)低 {full_mean - head_mean:.1f} dB(> 7.5 dB)"
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
            f"片尾最后 0.35s 音频未自然落音/淡出（mean={tail_mean} dB, max={tail_max} dB）"
        )

    film_checks: dict[str, Any] = {}
    cut_points: list[float] = []
    cutout_sticker_points: list[float] = []
    pip_points: list[float] = []
    broll_samples: list[tuple[Path, float | None]] = []
    if film_dir:
        film_checks, cut_points, cutout_sticker_points, pip_points, broll_samples = audit_film_dir(
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
            pip_points=pip_points,
            broll_samples=broll_samples,
        )

    pixel_checks = audit_rendered_frames_pixels(
        video, duration, style_slot, film_dir, hard_failures, warnings
    )

    cover_checks: dict[str, Any] = {}
    if not args.skip_covers:
        slot_root = film_dir.parent if film_dir else video.parent.parent
        covers_dir = (
            Path(args.covers_dir)
            if args.covers_dir
            else (slot_root / "covers" if (slot_root / "covers").is_dir() else None)
        )
        if covers_dir and covers_dir.is_dir():
            face_sheet_p = (Path(args.out_dir) / "safezone-cover-faces.png") if args.out_dir else None
            cover_checks = audit_covers(
                covers_dir,
                slot_root,
                hard_failures,
                warnings,
                style_slot=style_slot,
                face_sheet_out=face_sheet_p,
            )

    pub_checks: dict[str, Any] = {}
    if args.publish_json:
        pub_checks = audit_publish_json(
            Path(args.publish_json), hard_failures, warnings, style_slot=style_slot
        )

    report = {
        "video": rel_path(video),
        "style_slot": style_slot,
        "duration_sec": round(duration, 3),
        "size_bytes": size_bytes,
        "resolution": f"{v_stream.get('width')}x{v_stream.get('height')}" if v_stream else None,
        "audio_full": full_audio,
        "audio_tail_0_35s": tail_audio,
        "safezone_overlays": overlays,
        "pixel_frame_checks": pixel_checks,
        "film_checks": film_checks,
        "cover_checks": cover_checks,
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


def extract_slot_fingerprint(slot_name: str, slot_dir: Path) -> dict[str, Any]:
    film_dir = slot_dir / "film"
    film_html = film_dir / "film.html"
    sub_html = film_dir / "scenes" / "subtitles.html"
    out_dir = slot_dir / "output"
    mp4s = sorted(out_dir.glob("*.mp4")) if out_dir.exists() else []
    dur = 0.0
    if mp4s:
        try:
            dur = float(ffprobe_json(mp4s[0]).get("format", {}).get("duration", 0) or 0)
        except Exception:
            pass

    canon_slot = detect_style_slot(slot_dir / f"{slot_name}.mp4", film_dir, None)
    fp: dict[str, Any] = {
        "slot": slot_name,
        "canonical_slot": canon_slot,
        "account_group": SLOT_ACCOUNT_MAP[canon_slot]["group_id"] if canon_slot in SLOT_ACCOUNT_MAP else None,
        "expected_ip_name": SLOT_ACCOUNT_MAP[canon_slot]["ip_name"] if canon_slot in SLOT_ACCOUNT_MAP else None,
        "dir": rel_path(slot_dir),
        "duration_sec": round(dur, 2),
        "subtitle_has_pill_box": False,
        "subtitle_top_px": None,
        "subtitle_font_px": None,
        "luts": [],
        "pip_boxes": [],
        "lower_third_850_boxes": 0,
        "double_slash_headers": 0,
        "asl_sec": None,
        "fullscreen_speaker_ratio": 0.0,
        "pip_ratio": 0.0,
        "broll_dhashes": {},
    }

    if sub_html.is_file():
        stxt = sub_html.read_text(encoding="utf-8", errors="replace")
        for sb in re.findall(r"<style\b[^>]*>([\s\S]*?)</style>", stxt, flags=re.IGNORECASE):
            wm = re.search(r"(?:\.wrap|#wrap|\.sub-wrap)\s*\{([^}]*)\}", sb, flags=re.IGNORECASE)
            if wm:
                fp["subtitle_top_px"] = parse_css_px(wm.group(1), "top")
            if fp["subtitle_top_px"] is None:
                fp["subtitle_top_px"] = parse_css_px(sb, "top")
            fps = [float(x) for x in re.findall(r"font-size\s*:\s*(\d+(?:\.\d+)?)px", sb, re.I)]
            if fps:
                fp["subtitle_font_px"] = max(fps)
            for cm in re.finditer(
                r"(?:\.pill|#sub|\.sub-box|\.sub-line|\.sub-text)\s*\{([^}]*)\}", sb, flags=re.IGNORECASE
            ):
                if re.search(
                    r"background(?:-color)?\s*:\s*(?:rgba?\(|#[0-9a-fA-F]{3,8}|linear-gradient)",
                    cm.group(1),
                    flags=re.IGNORECASE,
                ):
                    fp["subtitle_has_pill_box"] = True

    speaker_vids: set[str] = set()
    if film_html.is_file():
        htxt = film_html.read_text(encoding="utf-8", errors="replace")
        for lm in re.findall(r"--of-lut\s*:\s*url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", htxt, re.I):
            ln = Path(lm.strip()).name
            if ln not in fp["luts"]:
                fp["luts"].append(ln)

        css_rules: dict[str, str] = {}
        kf_map: dict[str, str] = {}
        for sb in re.findall(r"<style\b[^>]*>([\s\S]*?)</style>", htxt, flags=re.IGNORECASE):
            kf_map.update(extract_keyframes_blocks(sb))
            sb_clean = re.sub(
                r"@keyframes\s+[A-Za-z0-9_-]+\s*\{(?:[^{}]|\{[^{}]*\})*\}", "", sb, flags=re.IGNORECASE
            )
            for cm in re.finditer(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}", sb_clean):
                css_rules[cm.group(1)] = css_rules.get(cm.group(1), "") + ";" + cm.group(2)

        main_m = re.search(r'<section[^>]*id=["\']main-stage["\'][^>]*>(.*?)</section>', htxt, re.I | re.S)
        pip_m = re.search(r'<section[^>]*id=["\']speaker-pip["\'][^>]*>(.*?)</section>', htxt, re.I | re.S)
        main_c = parse_clips_in_section(main_m.group(1)) if main_m else []
        pip_c = parse_clips_in_section(pip_m.group(1)) if pip_m else []

        vrefs = re.findall(
            r'<video\b[^>]*src=["\']([^"\']+\.(?:mp4|mov|webm|mkv))(?:#[^"\']*)?["\']', htxt, re.I
        )
        vfreq: dict[str, int] = {}
        for vr in vrefs:
            bn = Path(vr).name.lower()
            vfreq[bn] = vfreq.get(bn, 0) + 1
        if vfreq:
            speaker_vids.add(max(vfreq, key=vfreq.get))
        for pc in pip_c:
            if pc["tag"] == "video":
                speaker_vids.add(Path(pc["base_src"]).name.lower())

        if main_c and dur > 0:
            fp["asl_sec"] = round(dur / len(main_c), 2)
            fs_sec = 0.0
            for c in main_c:
                if c["tag"] == "video" and (
                    Path(c["base_src"]).name.lower() in speaker_vids
                    or SPEAKER_VID_NAME_RE.search(Path(c["base_src"]).name)
                ):
                    m_css_s = ";".join([css_rules.get(cls, "") for cls in c.get("classes", [])] + [c.get("style", "")])
                    bw_s = parse_css_px(m_css_s, "width", 1080.0) or 1080.0
                    bh_s = parse_css_px(m_css_s, "height", 1920.0) or 1920.0
                    it_s, _, ib_s, _ = resolve_pip_steady_inset(m_css_s, kf_map, bw_s, bh_s)
                    if (bh_s - it_s - ib_s) >= 1200.0:
                        fs_sec += c["dur"] or 0.0
            fp["fullscreen_speaker_ratio"] = round(min(1.0, fs_sec / dur), 3)

            aux_broll_c: list[dict[str, Any]] = []
            for ax_m_fp in re.finditer(r'<section[^>]*id=["\']([^"\']+)["\'][^>]*>(.*?)</section>', htxt, re.I | re.S):
                if "triptych" in ax_m_fp.group(1).lower():
                    aux_broll_c.extend(parse_clips_in_section(ax_m_fp.group(2)))

            for mc in (main_c + aux_broll_c):
                if mc["tag"] == "video":
                    bn = Path(mc["base_src"]).name.lower()
                    if bn not in speaker_vids and not SPEAKER_VID_NAME_RE.search(bn):
                        vf = film_dir / mc["base_src"]
                        # Sample standardized file offset (0.5s) AND clip midpoint so trimmed clones always match
                        hashes: list[str] = []
                        for st_cand in (0.5, (mc["t_in"] or 0.0) + (mc["dur"] or 2.0) * 0.5):
                            dh = compute_visual_dhash(vf, sample_t=st_cand)
                            if dh is not None:
                                hashes.append(f"{dh:016x}")
                        if hashes:
                            fp["broll_dhashes"][bn] = hashes

        if pip_c and dur > 0:
            pip_sec = sum((c["dur"] or 0.0) for c in pip_c)
            fp["pip_ratio"] = round(min(1.0, pip_sec / dur), 3)
            for pc in pip_c:
                m_css = ";".join([css_rules.get(cls, "") for cls in pc.get("classes", [])] + [pc.get("style", "")])
                bl = parse_css_px(m_css, "left", 0.0) or 0.0
                bt = parse_css_px(m_css, "top", 0.0) or 0.0
                bw = parse_css_px(m_css, "width", 1080.0) or 1080.0
                bh = parse_css_px(m_css, "height", 1920.0) or 1920.0
                it, ir, ib, il = resolve_pip_steady_inset(m_css, kf_map, bw, bh)
                vbox = [round(bl + il), round(bt + it), round(bw - il - ir), round(bh - it - ib)]
                if vbox not in fp["pip_boxes"]:
                    fp["pip_boxes"].append(vbox)

    scenes_dir = film_dir / "scenes"
    if scenes_dir.is_dir():
        for sf in sorted(scenes_dir.glob("*.html")):
            if sf.name == "subtitles.html":
                continue
            st = sf.read_text(encoding="utf-8", errors="replace")
            body = st[st.lower().find("<body") :] if "<body" in st.lower() else st
            if re.search(r"[A-Z]{3,}[A-Z0-9 _-]*//", body):
                fp["double_slash_headers"] += 1
            if re.search(r"top\s*:\s*11[2-9]\dpx", st) and re.search(r"width\s*:\s*8[4-7]\dpx", st):
                fp["lower_third_850_boxes"] += 1
            asset_refs = [
                a or b
                for a, b in re.findall(
                    r"""(?:src\s*=\s*["']([^"']+\.(?:jpg|jpeg|png|webp|mp4|webm|mov))(?:#[^"']*)?["']|url\(\s*["']?([^"')]+?\.(?:jpg|jpeg|png|webp))["']?\s*\))""",
                    st,
                    re.I,
                )
            ]
            for mm in asset_refs:
                raw_mm = mm.split("#", 1)[0]
                bn = Path(raw_mm).name.lower()
                if bn == "logo.png" or bn in speaker_vids or SPEAKER_VID_NAME_RE.search(bn):
                    continue
                ip = (sf.parent / raw_mm).resolve()
                if not ip.is_file():
                    ip = (film_dir / raw_mm).resolve()
                is_v = ip.suffix.lower() in {".mp4", ".webm", ".mov"}
                dh = compute_visual_dhash(ip, sample_t=0.5 if is_v else None)
                if dh is not None:
                    fp["broll_dhashes"][bn] = [f"{dh:016x}"]

    return fp


def cmd_audit_matrix(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"error: run directory not found: {run_dir}", file=sys.stderr)
        return 1

    slot_dirs: list[tuple[str, Path]] = []
    if (run_dir / "master").is_dir():
        slot_dirs.append(("00-master", run_dir / "master"))
    var_root = run_dir / "variants"
    if var_root.is_dir():
        for vd in sorted(var_root.iterdir()):
            if vd.is_dir():
                slot_dirs.append((vd.name, vd))

    hard_failures: list[str] = []
    warnings: list[str] = []
    fingerprints = [extract_slot_fingerprint(name, sdir) for name, sdir in slot_dirs]

    # 0. Fixed 5-slot (G0-G4: master, v1, v2, v3, v4) exact completeness check
    required_slots = {"master", "v1", "v2", "v3", "v4"}
    present_canon = [f["canonical_slot"] for f in fingerprints]
    missing_canon = sorted(required_slots - set(present_canon))
    if len(fingerprints) != 5 or missing_canon:
        hard_failures.append(
            f"入口 E 五号组矩阵槽位不完整或含多余目录：当前检测到 {len(fingerprints)} 片({[f['slot'] for f in fingerprints]}，缺失槽位={missing_canon})，必须严格对应 00-master(G0) + v1..v4(G1-G4) 共 5 个独立槽位"
        )

    # 1. Zero-pill & 5-slot vertical coordinate spread check across slots
    pill_slots = [f["slot"] for f in fingerprints if f["subtitle_has_pill_box"]]
    if pill_slots:
        hard_failures.append(
            f"跨片字幕胶囊框违规：{len(pill_slots)}/{len(fingerprints)} 片({', '.join(pill_slots)})仍使用 `.pill` 背景胶囊框，全槽位均须采用零胶囊排印字幕(SUB1-SUB6)"
        )
    sub_tops = sorted(
        [(f["slot"], f["subtitle_top_px"]) for f in fingerprints if f["subtitle_top_px"] is not None],
        key=lambda x: x[1],
    )
    if len(sub_tops) >= 3:
        vals = [v for _, v in sub_tops]
        span = max(vals) - min(vals)
        min_span = 150.0 if len(sub_tops) >= 5 else 110.0
        if span < min_span:
            desc = ", ".join(f"{s}:{v:.0f}px" for s, v in sub_tops)
            hard_failures.append(
                f"跨 5 片字幕坐标克隆：纵向 top 总跨度仅 {span:.0f}px(< {min_span:.0f}px 正交下限: {desc})"
            )
        for (s1, v1), (s2, v2) in zip(sub_tops, sub_tops[1:]):
            if abs(v2 - v1) < 28.0:
                hard_failures.append(
                    f"跨片字幕高度撞车：`{s1}`(top={v1:.0f}px) 与 `{s2}`(top={v2:.0f}px) 间距仅 {abs(v2-v1):.0f}px(< 28px)"
                )

    # 2. Color LUT diversity check across all 5 slots
    lut_map = [(f["slot"], f["luts"][0]) for f in fingerprints if f["luts"]]
    if len(fingerprints) >= 3 and len(lut_map) < len(fingerprints):
        missing_lut_slots = [f["slot"] for f in fingerprints if not f["luts"]]
        hard_failures.append(f"跨片调色缺失：{', '.join(missing_lut_slots)} 未挂载 `--of-lut` 调色 LUT")
    if len(lut_map) >= 3 and len({l for _, l in lut_map}) < len(lut_map):
        hard_failures.append(
            f"跨片调色 LUT 克隆：多片重复挂载同一 `.cube` 文件({lut_map})，5 个槽位必须各自挂载独立 `.cube` LUT"
        )

    # 3. Speaker-PiP geometry & lower-third / double-slash header clone checks
    pip_slots = [(f["slot"], f["pip_boxes"][0]) for f in fingerprints if f["pip_boxes"]]
    for i in range(len(pip_slots)):
        for j in range(i + 1, len(pip_slots)):
            s1, b1 = pip_slots[i]
            s2, b2 = pip_slots[j]
            if abs(b1[2] - b2[2]) <= 35 and abs(b1[3] - b2[3]) <= 35 and abs(b1[1] - b2[1]) <= 30:
                hard_failures.append(
                    f"跨片画中画(PiP)版式克隆：`{s1}`({b1}) 与 `{s2}`({b2}) 复用相同顶部矩形分屏构图"
                )

    lt_slots = [f["slot"] for f in fingerprints if f["lower_third_850_boxes"] >= 1]
    if len(lt_slots) >= 3:
        hard_failures.append(
            f"跨片全屏底部横盒套壳克隆：{len(lt_slots)} 片({', '.join(lt_slots)})均套用 top≈1160px + width≈852px 底部信息盒"
        )
    slash_slots = [f["slot"] for f in fingerprints if f["double_slash_headers"] >= 1]
    if len(slash_slots) >= 2:
        hard_failures.append(
            f"跨片顶标套壳克隆：{len(slash_slots)} 片({', '.join(slash_slots)})重复套用 `ENGLISH // 中文` 双斜杠顶标"
        )

    # 4. Cross-slot 64-bit dHash B-roll asset cloning check (catches renamed identical videos/stills!)
    cross_broll_clones: list[str] = []
    for i in range(len(fingerprints)):
        for j in range(i + 1, len(fingerprints)):
            f1, f2 = fingerprints[i], fingerprints[j]
            for n1, hlist1 in f1["broll_dhashes"].items():
                l1 = hlist1 if isinstance(hlist1, list) else [hlist1]
                for n2, hlist2 in f2["broll_dhashes"].items():
                    l2 = hlist2 if isinstance(hlist2, list) else [hlist2]
                    min_dist = min(hamming_dist(int(a, 16), int(b, 16)) for a in l1 for b in l2)
                    if min_dist <= 10:
                        cross_broll_clones.append(
                            f"{f1['slot']}/{n1} <-> {f2['slot']}/{n2}(dHash距离={min_dist})"
                        )
    if cross_broll_clones:
        hard_failures.append(
            f"跨片补充素材改名克隆违规：检测到多片共用相同/同源 B-roll 画面({'; '.join(cross_broll_clones[:5])})"
        )

    # 5. Pacing & visual-mode separation check
    v1_fp = next((f for f in fingerprints if f["canonical_slot"] == "v1"), None)
    v2_fp = next((f for f in fingerprints if f["canonical_slot"] == "v2"), None)
    v3_fp = next((f for f in fingerprints if f["canonical_slot"] == "v3"), None)
    if v1_fp and v1_fp["asl_sec"] and v1_fp["asl_sec"] > 3.5:
        hard_failures.append(f"v1(G1时奕聊AI经营) 剪辑节奏未拉开差距：ASL={v1_fp['asl_sec']}s > 3.5s 快剪红线")
    if v2_fp and v2_fp["fullscreen_speaker_ratio"] > 0.35:
        warnings.append(
            f"v2(G2辰奕AI经营实战) 全屏口播占比偏高({v2_fp['fullscreen_speaker_ratio']:.0%} > 35%)，建议释放 75%+ 给全画幅白板"
        )
    if v3_fp and v3_fp["asl_sec"] and v3_fp["asl_sec"] > 5.5:
        warnings.append(
            f"v3(G3老郑AI经营实战·双域交锋流) 镜头节奏偏缓(ASL={v3_fp['asl_sec']}s > 5.5s)"
        )

    # 6. Cross-slot covers, publish.json uniqueness/IP binding & delivery/ sync verification
    covers_enabled = True
    target_platforms = ["douyin", "xhs", "shipinhao"]
    run_json_p = run_dir / "run.json"
    if run_json_p.is_file():
        try:
            rj = json.loads(run_json_p.read_text(encoding="utf-8"))
            if rj.get("covers_enabled") is False:
                covers_enabled = False
            if isinstance(rj.get("target_platforms"), list) and rj["target_platforms"]:
                target_platforms = [str(x) for x in rj["target_platforms"]]
        except Exception:
            pass

    any_covers_present = any((sdir / "covers").is_dir() and list((sdir / "covers").glob("*.png")) for _, sdir in slot_dirs)
    cover_dhashes_by_plat: dict[str, list[tuple[str, int]]] = {}
    seen_titles_by_plat: dict[str, dict[str, str]] = {}
    matrix_face_rows: list[Any] = []

    for (sname, sdir), fp in zip(slot_dirs, fingerprints):
        cslot = fp["canonical_slot"]
        cdir = sdir / "covers"
        if covers_enabled and any_covers_present:
            if not cdir.is_dir() or not list(cdir.glob("*.png")):
                hard_failures.append(f"入口 E 封面缺失：槽位 `{sname}` 未生成 `covers/*.png`")
            else:
                slot_face_sheet = sdir / "output" / "check" / "safezone-cover-faces.png"
                audit_covers(
                    cdir,
                    sdir,
                    hard_failures,
                    warnings,
                    style_slot=cslot,
                    face_sheet_out=slot_face_sheet,
                )
                if slot_face_sheet.is_file():
                    try:
                        import cv2  # type: ignore

                        r_img = cv2.imread(str(slot_face_sheet))
                        if r_img is not None:
                            matrix_face_rows.append(r_img)
                    except Exception:
                        pass
                for plat in target_platforms:
                    matches = sorted(cdir.glob(f"*{plat}.png"))
                    if not matches:
                        hard_failures.append(f"入口 E 封面缺失：槽位 `{sname}` 缺少 `*{plat}.png`")
                    else:
                        dh = compute_visual_dhash(matches[0])
                        if dh is not None:
                            cover_dhashes_by_plat.setdefault(plat, []).append((sname, dh))

        pub_p = sdir / "publish" / "publish.json"
        if pub_p.is_file():
            try:
                audit_publish_json(pub_p, hard_failures, warnings, style_slot=cslot)
                pdata = json.loads(pub_p.read_text(encoding="utf-8"))
                for plat, pcfg in (pdata.get("platforms") or {}).items():
                    t_str = re.sub(r"\s+", "", str(pcfg.get("title") or "")).lower()
                    if len(t_str) >= 4:
                        prev_slot = seen_titles_by_plat.setdefault(plat, {}).get(t_str)
                        if prev_slot and prev_slot != sname:
                            hard_failures.append(
                                f"跨 5 片文案标题克隆 [{plat}]：`{prev_slot}` 与 `{sname}` 重复使用完全相同的标题「{pcfg.get('title')}」"
                            )
                        else:
                            seen_titles_by_plat[plat][t_str] = sname
            except Exception as exc:
                hard_failures.append(f"publish.json 读取/校验失败 `{rel_path(pub_p)}`: {exc}")

    for plat, sh_list in cover_dhashes_by_plat.items():
        for i in range(len(sh_list)):
            for j in range(i + 1, len(sh_list)):
                s1, h1 = sh_list[i]
                s2, h2 = sh_list[j]
                cdist = hamming_dist(h1, h2)
                if cdist <= 6:
                    hard_failures.append(
                        f"跨片封面撞图克隆 [{plat}]：`{s1}` 与 `{s2}` 封面视觉指纹高度雷同(dHash距离={cdist} <= 6)，违反五槽异构拓扑与 15 张封面神态零重复铁律"
                    )

    deliv_dir = run_dir / "delivery"
    if deliv_dir.is_dir():
        if not (deliv_dir / "INDEX.md").is_file():
            hard_failures.append("delivery/ 交付包缺少总索引 `delivery/INDEX.md`")
        src_size_by_name: dict[str, int] = {}
        for _, sdir in slot_dirs:
            for mp4_f in (sdir / "output").glob("*.mp4") if (sdir / "output").is_dir() else []:
                src_size_by_name[mp4_f.name] = mp4_f.stat().st_size
            for png_f in (sdir / "covers").glob("*.png") if (sdir / "covers").is_dir() else []:
                src_size_by_name[png_f.name] = png_f.stat().st_size
        for dsub in sorted(deliv_dir.iterdir()):
            if not dsub.is_dir():
                continue
            for df in sorted(dsub.iterdir()):
                if df.is_file() and df.name in src_size_by_name:
                    if df.stat().st_size != src_size_by_name[df.name] or df.stat().st_size == 0:
                        hard_failures.append(
                            f"delivery/ 陈旧副本不一致：`{rel_path(df)}`({df.stat().st_size}B) 与源目录产物({src_size_by_name[df.name]}B)不一致，返工后必须整包重建 delivery/"
                        )

    matrix_faces_rel: str | None = None
    if matrix_face_rows:
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore

            max_w_row = max(r.shape[1] for r in matrix_face_rows)
            padded_rows = [
                r
                if r.shape[1] == max_w_row
                else np.hstack([r, np.zeros((r.shape[0], max_w_row - r.shape[1], 3), dtype=np.uint8)])
                for r in matrix_face_rows
            ]
            m_sheet_p = run_dir / "master" / "output" / "check" / "matrix-cover-faces.png"
            m_sheet_p.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(m_sheet_p), np.vstack(padded_rows))
            matrix_faces_rel = rel_path(m_sheet_p)
        except Exception:
            pass

    report = {
        "run_dir": rel_path(run_dir),
        "slot_count": len(fingerprints),
        "matrix_cover_faces_sheet": matrix_faces_rel,
        "fingerprints": fingerprints,
        "hard_failures": hard_failures,
        "warnings": warnings,
        "passed": len(hard_failures) == 0,
    }
    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if hard_failures and not args.no_fail:
        return 2
    return 0


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    parser = argparse.ArgumentParser(
        description="Short-video pipeline broadcast audio conditioning & post-render V2 QC gate."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_audio = sub.add_parser(
        "probe-audio",
        help="Measure BGM/SFX/voice loudness, LRA, true peak, first-6s drop, and peak offset.",
    )
    p_audio.add_argument("targets", nargs="+", help="Audio file(s) or directory")

    p_scan = sub.add_parser(
        "scan-compliance",
        help="Scan ASR JSON / SRT / cue list for platform-sensitive words and output compliance-bleeps.json.",
    )
    p_scan.add_argument("--transcript", required=True, help="ASR transcript JSON, .srt, or cues JSON path")
    p_scan.add_argument("--out", help="Output compliance-bleeps.json path")

    p_voice = sub.add_parser(
        "prepare-voice",
        help="Condition spoken voice with broadcast EQ + 3:1 compressor + optional 1000Hz policy bleep masking.",
    )
    p_voice.add_argument("--in", dest="input", required=True, help="Source video or vocals audio file")
    p_voice.add_argument("--out", required=True, help="Output treated M4A path")
    p_voice.add_argument("--bleeps", help="Optional compliance-bleeps.json path for 1000Hz bleep masking")
    p_voice.add_argument("--bleep-freq", type=int, default=1000, help="Censor bleep sine Hz (default: 1000)")
    p_voice.add_argument("--bleep-db", type=float, default=-18.0, help="Censor bleep level dBFS (default: -18.0)")
    p_voice.add_argument("--sr", type=int, default=48000, help="Output sample rate (default: 48000)")
    p_voice.add_argument("--bitrate", default="256k", help="AAC bitrate (default: 256k)")

    p_sfx = sub.add_parser(
        "normalize-sfx",
        help="Peak-normalize short SFX (<10s) to -3.0 dBTP and reject broken silent audio (< -30 dBTP).",
    )
    p_sfx.add_argument("targets", nargs="+", help="SFX file(s) or assets directory")
    p_sfx.add_argument("--target-dbtp", type=float, default=-3.0, help="Target peak in dBTP (default: -3.0)")
    p_sfx.add_argument("--max-dur", type=float, default=10.0, help="Max duration in seconds treated as SFX")
    p_sfx.add_argument("--foley-dip", action="store_true", help="Force -2.5dB @ 2.5kHz vocal-clarity dip")

    p_bed = sub.add_parser(
        "build-bgm-bed",
        help="Build auto-ducked, LRA-tamed BGM bed with Cold Open swell, Silence Drop windows & outro fade.",
    )
    p_bed.add_argument("--film-dir", required=True, help="OpenFilm project film/ directory")
    p_bed.add_argument("--bgm", required=True, help="Source BGM audio path")
    p_bed.add_argument("--out", required=True, help="Output bgm-bed.m4a path")
    p_bed.add_argument("--drops", help="Comma-separated Silence Drop windows, e.g. '28.4:29.1,52.0:52.8'")
    p_bed.add_argument("--duration", type=float, help="Explicit timeline duration override (seconds)")
    p_bed.add_argument("--under-lufs", type=float, default=-28.5, help="Target BGM LUFS under voice (default: -28.5)")
    p_bed.add_argument("--swell-db", type=float, default=4.5, help="Swell boost in dB during pauses/hook (default: 4.5)")
    p_bed.add_argument("--bgm-offset", type=float, help="Start offset into source BGM (seconds; auto-skips dead intro if omitted)")

    p_stab = sub.add_parser(
        "stabilize-broll",
        help="Run 2-pass libvidstab optical stabilization on mild-shake B-roll and reject Tier C warped clips.",
    )
    p_stab.add_argument("--in", dest="input", required=True, help="Raw input B-roll MP4/WebM path")
    p_stab.add_argument("--out", required=True, help="Output stabilized MP4 path")
    p_stab.add_argument("--ss", type=float, default=0.0, help="Optional trim start seconds (default: 0)")
    p_stab.add_argument("--dur", type=float, help="Optional trim duration seconds")
    p_stab.add_argument("--smoothing", type=int, default=22, help="vidstab smoothing frames (default: 22)")
    p_stab.add_argument("--tripod", action="store_true", help="Lock virtual tripod mode (zero pan/tilt)")
    p_stab.add_argument("--box-w", type=float, default=1080.0, help="Target stage box width (default: 1080)")
    p_stab.add_argument("--box-h", type=float, default=1920.0, help="Target stage box height (default: 1920)")
    p_stab.add_argument("--keep-failed", action="store_true", help="Keep output file even if still Tier C jittery")

    p_focus = sub.add_parser(
        "probe-speaker-focus",
        help="Measure speaker horizontal face center (face_cx_pct) and vertical head span for E0 master-plan.json.",
    )
    p_focus.add_argument("--video", required=True, help="Speaker source video path")
    p_focus.add_argument("--samples", type=int, default=6, help="Sample frame count (default: 6)")
    p_focus.add_argument("--update-plan", help="Optional storyboard.json or master-plan.json to write speaker_focus")
    p_focus.add_argument("--out", help="Optional JSON output path")

    p_cframes = sub.add_parser(
        "select-cover-frames",
        help="Scan speaker video with offline YuNet + 478-pt 3D FaceMesh to export camera-facing natural portrait pool.",
    )
    p_cframes.add_argument("--video", required=True, help="Clean speaker source video path")
    p_cframes.add_argument("--out-dir", required=True, help="Output directory for cand-*.jpg, face-zoom-sheet.jpg & cover-frame-pool.json")
    p_cframes.add_argument("--mode", choices=["single", "matrix"], default="matrix", help="Allocation mode (default: matrix)")
    p_cframes.add_argument("--fps", type=float, default=5.0, help="Scan frame rate (default: 5.0)")
    p_cframes.add_argument("--count", type=int, default=24, help="Max top candidate frames to export (default: 24)")

    p_pre = sub.add_parser(
        "preflight-film",
        help="Run fast 3-second pre-render static & parallel B-roll QC gate BEFORE acquiring GPU render lock.",
    )
    p_pre.add_argument("--film-dir", required=True, help="OpenFilm project film/ directory")
    p_pre.add_argument("--duration", type=float, help="Optional timeline duration override")
    p_pre.add_argument(
        "--style",
        choices=["auto", "master", "v1", "v2", "v3", "v4", "default"],
        default="auto",
        help="Style slot (default: auto-detect from path)",
    )
    p_pre.add_argument("--out", help="Optional output preflight JSON report path")
    p_pre.add_argument("--no-fail", action="store_true", help="Exit 0 even when hard_failures exist")

    p_render = sub.add_parser(
        "audit-render",
        help="Run V2 acoustic, EDL, B-roll, Boxless visual, optical LUT/cutout, subtitle, cover, and publish.json QC.",
    )
    p_render.add_argument("--video", required=True, help="Rendered MP4 path")
    p_render.add_argument("--film-dir", help="OpenFilm project film/ directory")
    p_render.add_argument("--covers-dir", help="Optional covers/ directory override")
    p_render.add_argument("--skip-covers", action="store_true", help="Skip automatic covers/ audit")
    p_render.add_argument("--publish-json", help="publish/publish.json path")
    p_render.add_argument(
        "--style",
        choices=["auto", "master", "v1", "v2", "v3", "v4", "default"],
        default="auto",
        help="Style slot for ASL, IP binding, and VFX craft thresholds (default: auto-detect from path)",
    )
    p_render.add_argument(
        "--out-dir",
        help="Output directory for safezone-grid/tail/cuts/broll/pip/cutouts.png and qc-report.json",
    )
    p_render.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0 even when hard_failures exist (report-only mode)",
    )

    p_matrix = sub.add_parser(
        "audit-matrix",
        help="Audit Entry E fixed 5-slot (G0-G4) structural, IP binding, subtitle, LUT, and B-roll diversity.",
    )
    p_matrix.add_argument("--run-dir", required=True, help="Entry E run directory path")
    p_matrix.add_argument("--out", help="Optional output JSON report path")
    p_matrix.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0 even when hard_failures exist (report-only mode)",
    )

    args = parser.parse_args()
    if args.cmd == "probe-audio":
        return cmd_probe_audio(args)
    if args.cmd == "scan-compliance":
        return cmd_scan_compliance(args)
    if args.cmd == "prepare-voice":
        return cmd_prepare_voice(args)
    if args.cmd == "normalize-sfx":
        return cmd_normalize_sfx(args)
    if args.cmd == "build-bgm-bed":
        return cmd_build_bgm_bed(args)
    if args.cmd == "stabilize-broll":
        return cmd_stabilize_broll(args)
    if args.cmd == "probe-speaker-focus":
        return cmd_probe_speaker_focus(args)
    if args.cmd == "select-cover-frames":
        return cmd_select_cover_frames(args)
    if args.cmd == "preflight-film":
        return cmd_preflight_film(args)
    if args.cmd == "audit-render":
        return cmd_audit_render(args)
    if args.cmd == "audit-matrix":
        return cmd_audit_matrix(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
