#!/usr/bin/env python3
"""
头部口播短句高亮字幕生成器（SRT / transcript.json → OpenFilm 原生透明描边 WebVTT）。

解决自动化流水线字幕三大违和痛点：
  1. 彻底去除笨重纯黑方块底（改为透明底 + 细腻描边与多层柔影，自然长在画面里）
  2. 将原始 18–26 字长句按气口/语意自动切分为 6–12 字单行短句节拍，并去除行尾多余逗号句号
  3. 自动给核心关键词添加 OpenFilm 原生 <c.hi> 主题色高亮（每句最多 1 处，绝不花哨），
     并支持 --mute-ranges 在全屏大字金句出现时段自动让位，杜绝画面文字与字幕重复打架。

用法（先 source env.sh）：
  python3 .agents/skills/short-video-pipeline/scripts/format_captions.py \
    --in runs/<目录>/master-assets/clips/clip-01-transcript.json \
    --out runs/<目录>/variants/v1-<风格>/film/assets/captions.vtt \
    --start 0 --end 31.65 \
    --theme v1 \
    --highlight "<核心词1>,<核心词2>,<核心词3>" \
    --mute-ranges "27.5-30.2"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

THEMES: dict[str, str] = {
    # 00-master · 墨黑铜青（#0D1920 / #FFF8E6 / #8BE3D6）
    "dark": """STYLE
::cue {
  font-family: 'Noto Sans SC', 'PingFang SC', sans-serif;
  font-size: 46px;
  font-weight: 700;
  line-height: 1.32;
  color: #FFF8E6;
  background-color: transparent;
  -webkit-text-stroke: 1.5px rgba(0, 0, 0, 0.48);
  text-shadow: 0 2px 6px rgba(0, 0, 0, 0.88), 0 6px 20px rgba(0, 0, 0, 0.56);
}
::cue(c.hi) {
  color: #8BE3D6;
  font-weight: 900;
}""",
    # 01-v1 · 深蓝黑电光青 / 珊瑚橙（#060B14 / #FFFFFF / #00E5FF）
    "punch": """STYLE
@keyframes cuePop {
  0% { opacity: 0.72; }
  100% { opacity: 1; }
}
::cue {
  font-family: 'Noto Sans SC', 'PingFang SC', sans-serif;
  font-size: 50px;
  font-weight: 900;
  line-height: 1.28;
  color: #FFFFFF;
  background-color: transparent;
  -webkit-text-stroke: 1.8px rgba(0, 0, 0, 0.58);
  text-shadow: 0 3px 8px rgba(0, 0, 0, 0.92), 0 8px 24px rgba(0, 0, 0, 0.62);
  animation: cuePop 0.14s cubic-bezier(0.22, 1, 0.36, 1) both;
}
::cue(c.hi) {
  color: #00E5FF;
  font-weight: 900;
  text-shadow: 0 2px 10px rgba(0, 0, 0, 0.92), 0 0 18px rgba(0, 229, 255, 0.35);
}""",
    # 02-v2 · 暖白纸感深靛蓝 / 翡翠青（#F6F7F4 / #14212B / #0F766E）
    "light": """STYLE
::cue {
  font-family: 'Noto Sans SC', 'PingFang SC', sans-serif;
  font-size: 44px;
  font-weight: 700;
  line-height: 1.32;
  color: #14212B;
  background-color: transparent;
  -webkit-text-stroke: 0.6px rgba(246, 247, 244, 0.68);
  text-shadow: 0 1px 10px rgba(246, 247, 244, 0.95), 0 0 18px rgba(246, 247, 244, 0.88);
}
::cue(c.hi) {
  color: #0F766E;
  font-weight: 900;
}""",
    # 03-v3 · 黑曜石黑金 / 极光薄荷（#0A0A0C / #F2E5C6 / #5EEAD4）
    "cinema": """STYLE
::cue {
  font-family: 'Noto Sans SC', 'PingFang SC', sans-serif;
  font-size: 42px;
  font-weight: 700;
  line-height: 1.36;
  color: #F2E5C6;
  background-color: transparent;
  -webkit-text-stroke: 1px rgba(0, 0, 0, 0.42);
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.90), 0 6px 22px rgba(0, 0, 0, 0.58);
}
::cue(c.hi) {
  color: #5EEAD4;
  font-weight: 900;
}""",
}

THEME_ALIASES: dict[str, str] = {
    "master": "dark",
    "v1": "punch",
    "v2": "light",
    "v3": "cinema",
}

SPLIT_BEFORE_TOKENS = [
    "但是", "所以", "而且", "如果", "甚至", "或者", "然后", "因为", "不是", "而是",
    "不仅", "还能", "以及", "包括", "其实", "比如", "就是", "就会", "可以", "变成",
    "同时", "另外", "结果", "反而", "于是", "因此", "并且", "不过", "只是", "需要",
]

LEADING_FILLERS = re.compile(r"^(?:呃+|嗯+|啊+|那个|然后呢|就是说)[，,、\s]*")


def parse_ts(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(ts)


def fmt_vtt_ts(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def load_segments(path: Path) -> list[dict[str, Any]]:
    ext = path.suffix.lower()
    raw = path.read_text(encoding="utf-8")
    if ext == ".json":
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("segments") or data.get("cues") or data.get("items") or []
        segs = []
        for item in data:
            st = float(item.get("start", item.get("start_sec", 0)))
            ed = float(item.get("end", item.get("end_sec", 0)))
            tx = str(item.get("text", "")).strip()
            if ed > st and tx:
                segs.append({"start": st, "end": ed, "text": tx})
        return segs

    # SRT or VTT
    segs = []
    blocks = re.split(r"\r?\n\r?\n+", raw.strip())
    for blk in blocks:
        lines = [ln.strip() for ln in blk.splitlines() if ln.strip()]
        t_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if t_idx is None:
            continue
        m = re.match(r"([0-9:.,]+)\s*-->\s*([0-9:.,]+)", lines[t_idx])
        if not m:
            continue
        st, ed = parse_ts(m.group(1)), parse_ts(m.group(2))
        tx = " ".join(re.sub(r"<[^>]+>", "", ln) for ln in lines[t_idx + 1:]).strip()
        if ed > st and tx:
            segs.append({"start": st, "end": ed, "text": tx})
    return segs


def visual_len(s: str) -> float:
    """Estimate Chinese-equivalent visual width (CJK=1.0, ASCII=0.6)."""
    total = 0.0
    for ch in s:
        if ch.isspace():
            total += 0.25
        elif ord(ch) < 128:
            total += 0.6
        else:
            total += 1.0
    return total


def clean_clause(text: str, trim_fillers: bool) -> str:
    s = re.sub(r"\s+", " ", text).strip()
    if trim_fillers:
        s = LEADING_FILLERS.sub("", s).strip()
    # Modern short-video subtitles strip trailing weak punctuation (keep ? / !)
    s = re.sub(r"[，,。、；;：:]+$", "", s).strip()
    s = re.sub(r"^[，,。、；;：:]+", "", s).strip()
    return s


def split_long_clause(clause: str, max_chars: int) -> list[str]:
    if visual_len(clause) <= max_chars and len(clause) <= max_chars + 2:
        return [clause]

    # Try natural Chinese discourse boundary near the middle
    n = len(clause)
    mid = n // 2
    best_pos: int | None = None
    best_dist = 999

    for tok in SPLIT_BEFORE_TOKENS:
        start = 0
        while True:
            idx = clause.find(tok, start)
            if idx == -1:
                break
            if 3 <= idx <= n - 3:
                dist = abs(idx - mid)
                if dist < best_dist:
                    best_dist = dist
                    best_pos = idx
            start = idx + 1

    # Also allow splitting on internal space if near middle
    if best_pos is None:
        for m in re.finditer(r"\s+", clause):
            idx = m.start()
            if 3 <= idx <= n - 3 and abs(idx - mid) < best_dist:
                best_dist = abs(idx - mid)
                best_pos = idx

    # Fallback: split cleanly near midpoint without cutting inside ASCII word
    if best_pos is None:
        best_pos = mid
        while 3 < best_pos < n - 2 and clause[best_pos - 1].isascii() and clause[best_pos - 1].isalnum() and clause[best_pos].isascii() and clause[best_pos].isalnum():
            best_pos += 1

    left = clean_clause(clause[:best_pos], False)
    right = clean_clause(clause[best_pos:], False)
    if not left or not right:
        return [clause]
    return split_long_clause(left, max_chars) + split_long_clause(right, max_chars)


def split_into_beats(text: str, max_chars: int, trim_fillers: bool) -> list[str]:
    # First break on natural punctuation
    raw_parts = re.split(r"[，,。、；;\n]+|(?<=[！？!?])\s*", text)
    beats: list[str] = []
    for p in raw_parts:
        c = clean_clause(p, trim_fillers)
        if not c:
            continue
        beats.extend(split_long_clause(c, max_chars))

    # Merge ultra-tiny orphan fragments (<= 3 chars) into neighbor if combined <= max_chars
    merged: list[str] = []
    for b in beats:
        if merged and (len(b) <= 3 or len(merged[-1]) <= 3) and visual_len(merged[-1] + b) <= max_chars:
            joiner = " " if (merged[-1][-1].isascii() and b[0].isascii()) else ""
            merged[-1] = merged[-1] + joiner + b
        else:
            merged.append(b)
    return merged or [clean_clause(text, trim_fillers)]


def apply_highlight(text: str, keywords: list[str]) -> str:
    # Highlight at most ONE highest-priority keyword per cue
    for kw in sorted(keywords, key=len, reverse=True):
        if not kw:
            continue
        idx = text.find(kw)
        if idx != -1:
            return f"{text[:idx]}<c.hi>{kw}</c>{text[idx + len(kw):]}"
    return text


def parse_mute_ranges(spec: str) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for part in (spec or "").split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.append((float(a), float(b)))
    return out


def is_muted(st: float, ed: float, mutes: list[tuple[float, float]]) -> bool:
    mid = (st + ed) / 2.0
    return any(ma <= mid <= mb for ma, mb in mutes)


def main() -> int:
    ap = argparse.ArgumentParser(description="将原始 SRT / transcript.json 转换为高质感透明短句高亮 OpenFilm WebVTT")
    ap.add_argument("--in", dest="inp", required=True, help="输入 .srt / .vtt / transcript.json")
    ap.add_argument("--out", required=True, help="输出 WebVTT 文件路径（如 film/assets/captions.vtt）")
    ap.add_argument("--start", type=float, default=0.0, help="切片起点秒（自动偏移归零）")
    ap.add_argument("--end", type=float, default=None, help="切片终点秒（不填则到末尾）")
    ap.add_argument("--max-chars", type=int, default=12, help="单行最大等效字数（建议 8–12）")
    ap.add_argument("--theme", choices=[*THEMES.keys(), *THEME_ALIASES.keys()], default="dark", help="视觉风格主题（支持 master/v1/v2/v3 槽位别名）")
    ap.add_argument("--line", type=int, default=74, help="WebVTT 纵向位置百分比（建议 71–75 避开平台底栏）")
    ap.add_argument("--highlight", default="", help="英文逗号分隔的高亮关键词列表（每句最多亮 1 词）")
    ap.add_argument("--mute-ranges", default="", help="全屏大字金句时段隐藏字幕，如 12.5-15.0,28.0-30.5")
    ap.add_argument("--trim-fillers", action="store_true", help="清理句首无意义口癖（呃/嗯/那个/然后呢）")
    args = ap.parse_args()

    segs = load_segments(Path(args.inp))
    keywords = [k.strip() for k in args.highlight.split(",") if k.strip()]
    mutes = parse_mute_ranges(args.mute_ranges)

    cues: list[dict[str, Any]] = []
    for seg in segs:
        st, ed = seg["start"], seg["end"]
        if ed <= args.start:
            continue
        if args.end is not None and st >= args.end:
            continue
        rel_st = max(0.0, st - args.start)
        rel_ed = (min(ed, args.end) - args.start) if args.end is not None else (ed - args.start)
        if rel_ed - rel_st < 0.12:
            continue

        beats = split_into_beats(seg["text"], args.max_chars, args.trim_fillers)
        weights = [max(1.0, visual_len(b)) for b in beats]
        total_w = sum(weights)
        cur = rel_st
        for idx, (b, w) in enumerate(zip(beats, weights)):
            nxt = rel_ed if idx == len(beats) - 1 else cur + (rel_ed - rel_st) * (w / total_w)
            if not is_muted(cur, nxt, mutes):
                styled = apply_highlight(b, keywords)
                cues.append({"start": cur, "end": nxt, "text": styled, "plain": b})
            cur = nxt

    resolved_theme = THEME_ALIASES.get(args.theme, args.theme)
    out_lines = ["WEBVTT", "", THEMES[resolved_theme], ""]
    for idx, c in enumerate(cues, 1):
        out_lines.append(f"c{idx}")
        out_lines.append(f"{fmt_vtt_ts(c['start'])} --> {fmt_vtt_ts(c['end'])} line:{args.line}% position:50% size:88% align:center")
        out_lines.append(c["text"])
        out_lines.append("")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out_lines), encoding="utf-8")

    hi_count = sum(1 for c in cues if "<c.hi>" in c["text"])
    max_len = max((len(c["plain"]) for c in cues), default=0)
    print(json.dumps({
        "status": "ok",
        "output": str(out_path),
        "theme": args.theme,
        "cue_count": len(cues),
        "highlighted_cues": hi_count,
        "max_plain_chars": max_len,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
