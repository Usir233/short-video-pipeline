#!/usr/bin/env python3
"""
素材寻源与落盘工具（纯 Python 标准库 + 复用工作区已有 playwright-core / yt-dlp / ffmpeg，零新增依赖）。

子命令（先 source env.sh）：
  1) news-page          抓官方新闻稿/博客正文事实 + 提取配图落暂存区并生成候选检视拼图（严禁未验直入 assets）
  2) stock              搜索免版权素材候选落入 materials/ 并自动生成候选检视拼图（优先本地 Pixabay 竖屏无延时实拍）
  3) video-search       用工作区 yt-dlp 搜索官方发布会 / 产品 Demo（YouTube 等）
  4) video-clip         用工作区 yt-dlp + ffmpeg 按起止秒精准截取官方视频短片段至 materials/ 并生成检视帧
  5) inspect-candidates 对候选视频/图片（含 openfilm get 下载件）生成 4 帧检视拼图 candidate-sheet.jpg 与技术规格表
  6) register           经人工/Agent 看图试听完成「六维制作要求核验」后，签收进 film/assets/ 并写入 credits.json（必带 --shot 与 --fit-reason）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UA = "ShortVideoPipeline/1.0 (local-video-workspace; https://github.com/openfilm/openfilm)"


def rel_to_root(path: Path | str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    try:
        return p.resolve().relative_to(svp_root().resolve()).as_posix()
    except Exception:
        return p.as_posix()


def svp_root() -> Path:
    env_root = os.environ.get("SVP_ROOT")
    if env_root:
        return Path(env_root)
    cur = Path(__file__).resolve()
    for p in cur.parents:
        if (p / ".agents" / "skills" / "short-video-pipeline" / "SKILL.md").is_file():
            return p
    return Path.cwd()


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text.strip()).strip("-_")
    return (s[:max_len] or "asset").lower()


def http_get(url: str, timeout: float = 15.0) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        return resp.read(), ctype


def guess_ext(url: str, ctype: str = "", default: str = ".bin") -> str:
    ct = ctype.lower().split(";")[0].strip()
    ct_map = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/svg+xml": ".svg",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/ogg": ".ogv",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/ogg": ".ogg",
        "audio/mp4": ".m4a",
    }
    if ct in ct_map:
        return ct_map[ct]
    path = urllib.parse.urlparse(url).path
    ext = Path(path).suffix.lower()
    if ext and len(ext) <= 5:
        return ext
    return default


def download_file(url: str, dest_dir: Path, stem: str, default_ext: str = ".bin", timeout: float = 25.0) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    data, ctype = http_get(url, timeout=timeout)
    ext = guess_ext(url, ctype, default_ext)
    out = dest_dir / f"{stem}{ext}"
    out.write_bytes(data)
    return out


def append_credit(assets_dir: Path, entry: dict[str, Any]) -> Path:
    assets_dir.mkdir(parents=True, exist_ok=True)
    credits_path = assets_dir / "credits.json"
    items: list[dict[str, Any]] = []
    if credits_path.is_file():
        try:
            loaded = json.loads(credits_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                items = loaded
            elif isinstance(loaded, dict) and isinstance(loaded.get("items"), list):
                items = loaded["items"]
        except Exception:
            items = []

    entry = {
        "recorded_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        **entry,
    }
    # 按 file 字段去重更新
    items = [it for it in items if it.get("file") != entry.get("file")]
    items.append(entry)
    credits_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return credits_path


LAZY_FIT_REASON_RE = re.compile(
    r"^(?:ok|pass|yes|good|fit|matched|verified|符合|符合要求|合格|通过|没问题|可以|合适|匹配|测试|默认|自动下载)[\s!！.。]*$",
    flags=re.IGNORECASE,
)

VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".ogv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def probe_visual_candidate(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "file": rel_to_root(path),
        "name": path.name,
        "kind": "video" if path.suffix.lower() in VIDEO_EXTS else "image",
        "width": 0,
        "height": 0,
        "aspect_ratio": None,
        "orientation": "unknown",
        "duration_sec": None,
        "yavg_min": None,
    }
    if not path.is_file():
        return info
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode == 0:
        try:
            pj = json.loads(proc.stdout)
            vs = next((s for s in (pj.get("streams") or []) if s.get("codec_type") == "video"), None)
            if vs:
                w = int(vs.get("width") or 0)
                h = int(vs.get("height") or 0)
                info["width"] = w
                info["height"] = h
                if w > 0 and h > 0:
                    info["aspect_ratio"] = round(w / h, 3)
                    info["orientation"] = "portrait" if h > w else ("square" if h == w else "landscape")
            if info["kind"] == "video":
                dur = float((pj.get("format") or {}).get("duration") or 0.0)
                info["duration_sec"] = round(dur, 2)
        except Exception:
            pass

    if info["kind"] == "video" and (info["duration_sec"] or 0) > 0.2:
        eval_d = min(float(info["duration_sec"]), 5.0)
        py = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-t",
                f"{eval_d:.2f}",
                "-i",
                str(path),
                "-vf",
                "fps=2,scale=160:-2,signalstats,metadata=mode=print:file=-",
                "-an",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        yavgs = [float(x) for x in re.findall(r"lavfi\.signalstats\.YAVG=(\d+(?:\.\d+)?)", py.stdout + "\n" + py.stderr)]
        if yavgs:
            info["yavg_min"] = round(min(yavgs), 2)
    return info


def build_candidate_sheet(files: list[Path], out_sheet: Path) -> tuple[str | None, list[dict[str, Any]]]:
    """Render up to 8 visual candidates into a 1080px-wide contact sheet (4 timepoints per video, aspect-padded)."""
    valid = [
        f
        for f in files
        if f.is_file() and (f.suffix.lower() in VIDEO_EXTS or f.suffix.lower() in IMAGE_EXTS)
    ][:8]
    probes = [probe_visual_candidate(f) for f in valid]
    if not valid:
        return None, probes

    out_sheet.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    fc_parts: list[str] = []
    row_labels: list[str] = []
    inp_idx = 0

    for r_idx, (f, pr) in enumerate(zip(valid, probes)):
        pr["sheet_row"] = r_idx + 1
        if pr["kind"] == "video":
            dur = max(0.4, min(float(pr.get("duration_sec") or 4.0), 8.0))
            t_pts = [round(dur * r, 2) for r in (0.12, 0.38, 0.62, 0.88)]
            cell_lbls: list[str] = []
            for t_val in t_pts:
                cmd += ["-ss", f"{t_val:.2f}", "-i", str(f)]
                cl = f"c{inp_idx}"
                fc_parts.append(
                    f"[{inp_idx}:v]scale=270:420:force_original_aspect_ratio=decrease,"
                    f"pad=270:420:(ow-iw)/2:(oh-ih)/2:color=#141414,setsar=1[{cl}]"
                )
                cell_lbls.append(f"[{cl}]")
                inp_idx += 1
            rl = f"row{r_idx}"
            fc_parts.append(f"{''.join(cell_lbls)}hstack=inputs=4[{rl}]")
            row_labels.append(f"[{rl}]")
        else:
            cmd += ["-i", str(f)]
            rl = f"row{r_idx}"
            fc_parts.append(
                f"[{inp_idx}:v]scale=1080:420:force_original_aspect_ratio=decrease,"
                f"pad=1080:420:(ow-iw)/2:(oh-ih)/2:color=#141414,setsar=1[{rl}]"
            )
            row_labels.append(f"[{rl}]")
            inp_idx += 1

    if len(row_labels) == 1:
        final_map = row_labels[0]
    else:
        fc_parts.append(f"{''.join(row_labels)}vstack=inputs={len(row_labels)}[sheet_out]")
        final_map = "[sheet_out]"

    cmd += ["-filter_complex", ";".join(fc_parts), "-map", final_map, "-frames:v", "1", str(out_sheet)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not out_sheet.is_file():
        return None, probes
    return rel_to_root(out_sheet), probes


def copy_to_openfilm_areas(
    src_file: Path,
    assets_dir: Path | None,
    target_name: str | None,
    save_reusable: bool,
    credit_meta: dict[str, Any],
) -> dict[str, str | None]:
    result: dict[str, str | None] = {"asset_path": None, "saved_path": None}
    fname = target_name or src_file.name
    if assets_dir:
        assets_dir.mkdir(parents=True, exist_ok=True)
        dst = assets_dir / fname
        if src_file.resolve() != dst.resolve():
            shutil.copy2(src_file, dst)
        result["asset_path"] = str(dst)

    if save_reusable:
        saved_root = Path(os.environ.get("OPENFILM_SAVED") or (svp_root() / ".local" / "openfilm-user" / "saved"))
        saved_root.mkdir(parents=True, exist_ok=True)
        sdst = saved_root / fname
        if src_file.resolve() != sdst.resolve():
            shutil.copy2(src_file, sdst)
        result["saved_path"] = str(sdst)

    if assets_dir:
        append_credit(
            assets_dir,
            {
                "file": fname,
                "material_origin": rel_to_root(src_file),
                "reusable_saved": rel_to_root(result["saved_path"]),
                **credit_meta,
            },
        )
    return {
        "asset_path": rel_to_root(result["asset_path"]),
        "saved_path": rel_to_root(result["saved_path"]),
    }


# -------------------- 1. news-page --------------------

def cmd_news_page(args: argparse.Namespace) -> int:
    if args.assets:
        print(
            "错误：禁止在 news-page 抓页时使用 --assets 将未核验网页配图盲目直入 film/assets/！"
            "请先抓入 --out runs/<目录>/materials，打开自动生成的 candidate-sheet-*.jpg 核验无媒体水印、构图与叙事吻合后，"
            "仅对选定图片执行 fetch_asset.py register --shot <镜号> --fit-reason '<具体核验说明>'。",
            file=sys.stderr,
        )
        return 2
    root = svp_root()
    pw_mod = root / "node_modules" / "playwright-core"
    if not pw_mod.exists():
        print("错误：未找到工作区 node_modules/playwright-core，请先安装 OpenFilm。", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = args.slug or slugify(urllib.parse.urlparse(args.url).netloc + "-" + hashlib.sha1(args.url.encode()).hexdigest()[:6])
    screenshot_path = str((out_dir / f"{slug}-page.png").resolve()) if args.screenshot else ""

    node_script = r"""
const { chromium } = require(process.env.SVP_PW_MOD);
(async () => {
  const url = process.env.TARGET_URL;
  const shot = process.env.SHOT_PATH;
  const maxImgs = parseInt(process.env.MAX_IMGS || '6', 10);
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1080, height: 1440 },
    deviceScaleFactor: 2,
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
  });
  const page = await ctx.newPage();
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 25000 });
  await page.waitForTimeout(2000);

  // 尝试关闭常见 cookie/订阅遮罩（不影响正文）
  await page.evaluate(() => {
    const selectors = ['[class*="cookie"]', '[id*="cookie"]', '[class*="consent"]', '[class*="modal-backdrop"]'];
    for (const sel of selectors) {
      document.querySelectorAll(sel).forEach(el => {
        const st = getComputedStyle(el);
        if (st.position === 'fixed' || st.position === 'sticky') el.style.display = 'none';
      });
    }
  });

  if (shot) {
    await page.screenshot({ path: shot, fullPage: false });
  }

  const info = await page.evaluate((maxN) => {
    const title = document.title || '';
    const ogImage = document.querySelector('meta[property="og:image"]')?.content || '';
    const ogDesc = document.querySelector('meta[property="og:description"]')?.content
      || document.querySelector('meta[name="description"]')?.content || '';
    const pubTime = document.querySelector('meta[property="article:published_time"]')?.content
      || document.querySelector('time')?.getAttribute('datetime')
      || document.querySelector('time')?.textContent?.trim() || '';

    const container = document.querySelector('article, main, .post_content, .article-content, #paragraph');
    const cText = (container?.innerText || '').trim();
    const rawText = cText.length >= 200 ? cText : (document.body?.innerText || '');
    const text = rawText.replace(/\s+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim().slice(0, 4000);

    const seen = new Set();
    const imgs = [];
    if (ogImage && ogImage.startsWith('http')) {
      seen.add(ogImage);
      imgs.push({ src: ogImage, width: 0, height: 0, alt: 'og:image', is_og: true });
    }
    const candidates = [...document.querySelectorAll('article img, main img, .post_content img, .article-content img, figure img, img')];
    for (const img of candidates) {
      const src = img.currentSrc || img.src || img.dataset?.original || img.dataset?.src || '';
      if (!src || !src.startsWith('http') || seen.has(src)) continue;
      if (/avatar|icon|logo|badge|emoji|tracking|pixel|1x1|alicdn\.com|360buyimg\.com|doubleclick|googlesyndication/i.test(src)) continue;
      const w = img.naturalWidth || img.width || 0;
      const h = img.naturalHeight || img.height || 0;
      if (w > 0 && w < 420) continue;
      if (h > 0 && h < 220) continue;
      seen.add(src);
      imgs.push({ src, width: w, height: h, alt: (img.alt || '').trim(), is_og: false });
      if (imgs.length >= maxN) break;
    }
    return { title, ogDesc, pubTime, text, imgs };
  }, maxImgs);

  await browser.close();
  console.log(JSON.stringify(info));
})().catch(e => { console.error(e.message || e); process.exit(1); });
"""

    env = os.environ.copy()
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(root / "browsers" / "ms-playwright"))
    env["SVP_PW_MOD"] = str(pw_mod)
    env["TARGET_URL"] = args.url
    env["SHOT_PATH"] = screenshot_path
    env["MAX_IMGS"] = str(args.max_images)

    proc = subprocess.run(
        ["node", "-e", node_script],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        print(f"抓页失败：{proc.stderr.strip()}", file=sys.stderr)
        return 1

    info = json.loads(proc.stdout.strip().splitlines()[-1])
    downloaded: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    img_idx = 0
    for im in (info.get("imgs") or []):
        try:
            saved = download_file(im["src"], out_dir, f"{slug}-tmp", default_ext=".jpg")
            data_bytes = saved.read_bytes()
            digest = hashlib.sha1(data_bytes).hexdigest()
            if len(data_bytes) < 8192 or digest in seen_hashes:
                saved.unlink(missing_ok=True)
                continue
            seen_hashes.add(digest)
            img_idx += 1
            final_path = out_dir / f"{slug}-img{img_idx}{saved.suffix}"
            saved.replace(final_path)
            rec = {
                "path": str(final_path),
                "url": im["src"],
                "width": im.get("width", 0),
                "height": im.get("height", 0),
                "alt": im.get("alt", ""),
                "size_bytes": len(data_bytes),
            }
            downloaded.append(rec)
        except Exception:
            continue

    manifest = {
        "url": args.url,
        "title": info.get("title", ""),
        "published": info.get("pubTime", ""),
        "description": info.get("ogDesc", ""),
        "screenshot": rel_to_root(screenshot_path) if screenshot_path else None,
        "images": [{**d, "path": rel_to_root(d["path"])} for d in downloaded],
        "text_excerpt": (info.get("text") or "")[:2000],
    }
    article_json = out_dir / f"{slug}-article.json"
    article_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    cand_paths: list[Path] = []
    if screenshot_path and Path(screenshot_path).is_file():
        cand_paths.append(Path(screenshot_path))
    cand_paths.extend(Path(d["path"]) for d in downloaded if Path(d["path"]).is_file())
    sheet_rel, probes = build_candidate_sheet(cand_paths, out_dir / f"candidate-sheet-{slug}.jpg")

    print(json.dumps({
        "article_json": str(article_json),
        "title": manifest["title"],
        "screenshot": manifest["screenshot"],
        "downloaded_images": [d["path"] for d in downloaded],
        "candidate_sheet": sheet_rel,
        "candidates_probe": probes,
        "verification_required": "必须先看图打开 candidate_sheet 核验无水印且契合分镜，再用 register --shot <镜号> --fit-reason <说明> 入库",
    }, ensure_ascii=False, indent=2))
    return 0


# -------------------- 2. stock (Pixabay local key priority + zero-key public APIs) --------------------

def _load_pixabay_key() -> str:
    """Read Pixabay API key silently from env or local gitignored OpenFilm providers.json (never log or persist it)."""
    env_k = os.environ.get("PIXABAY_API_KEY", "").strip()
    if env_k:
        return env_k
    of_home = Path(os.environ.get("OPENFILM_HOME") or (svp_root() / ".local" / "openfilm"))
    prov_file = of_home / "providers.json"
    if prov_file.is_file():
        try:
            data = json.loads(prov_file.read_text(encoding="utf-8"))
            return str(((data.get("keys") or {}).get("pixabay")) or "").strip()
        except Exception:
            return ""
    return ""


def search_pixabay(query: str, kind: str, limit: int) -> list[dict[str, Any]]:
    if kind == "audio":
        return []
    api_key = _load_pixabay_key()
    if not api_key:
        return []
    per_page = min(100, max(50, limit * 12))
    allow_timelapse = bool(re.search(r"timelapse|hyperlapse|time-lapse|time\s+lapse", query, flags=re.IGNORECASE))
    timelapse_tag_re = re.compile(r"\b(?:timelapse|hyperlapse|time-lapse|time\s+lapse)\b", flags=re.IGNORECASE)
    junk_tag_re = re.compile(
        r"\b(?:cartoon|3d\s*render|illustration|anime|animation|green\s*screen|chroma\s*key|subscribe|template|background\s*loop|vj\s*loop|emoji)\b",
        flags=re.IGNORECASE,
    )

    if kind == "video":
        params = urllib.parse.urlencode({
            "key": api_key,
            "q": query,
            "video_type": "film",
            "safesearch": "true",
            "per_page": per_page,
        })
        raw, _ = http_get(f"https://pixabay.com/api/videos/?{params}", timeout=15.0)
        j = json.loads(raw.decode("utf-8", "replace"))
        ranked: list[dict[str, Any]] = []
        for it in (j.get("hits") or []):
            tags = str(it.get("tags") or "")
            dur_s = float(it.get("duration") or 0.0)
            if dur_s > 0 and dur_s < 2.0:
                continue
            if not allow_timelapse and timelapse_tag_re.search(tags):
                continue
            if junk_tag_re.search(tags) and not junk_tag_re.search(query):
                continue
            vids = it.get("videos") or {}
            chosen_v = None
            for tier in ("large", "medium", "small"):
                cand = vids.get(tier) or {}
                cw = int(cand.get("width") or 0)
                ch = int(cand.get("height") or 0)
                if cand.get("url") and max(cw, ch) <= 2560 and max(cw, ch) >= 1080:
                    chosen_v = cand
                    break
            if not chosen_v:
                for tier in ("medium", "large", "small"):
                    cand = vids.get(tier) or {}
                    if cand.get("url") and max(int(cand.get("width") or 0), int(cand.get("height") or 0)) >= 720:
                        chosen_v = cand
                        break
            if not chosen_v:
                continue
            vw = int(chosen_v.get("width") or 0)
            vh = int(chosen_v.get("height") or 0)
            ranked.append({
                "source": "pixabay",
                "title": f"pixabay-{it.get('id', '')}-{slugify(tags, 32)}",
                "url": chosen_v["url"],
                "page_url": it.get("pageURL") or "",
                "width": vw,
                "height": vh,
                "orientation": "portrait" if vh > vw else "landscape",
                "duration_sec": it.get("duration") or 0,
                "tags": tags,
                "mime": "video/mp4",
                "license": "Pixabay Content License (Free commercial use)",
                "author": str(it.get("user") or "Pixabay")[:80],
                "_pop": int(it.get("downloads") or 0) + int(it.get("likes") or 0) * 10,
            })
        # Prioritize native 9:16 portrait clips first, then >=1080p clean film clips
        ranked.sort(
            key=lambda x: (
                1 if x["height"] > x["width"] else 0,
                1 if min(x["width"], x["height"]) >= 1080 else 0,
                x["_pop"],
            ),
            reverse=True,
        )
        out_hits: list[dict[str, Any]] = []
        for item in ranked[:limit]:
            item.pop("_pop", None)
            out_hits.append(item)
        return out_hits

    params = urllib.parse.urlencode({
        "key": api_key,
        "q": query,
        "image_type": "photo",
        "safesearch": "true",
        "per_page": per_page,
    })
    raw, _ = http_get(f"https://pixabay.com/api/?{params}", timeout=15.0)
    j = json.loads(raw.decode("utf-8", "replace"))
    img_ranked: list[dict[str, Any]] = []
    for it in (j.get("hits") or []):
        img_url = it.get("largeImageURL") or it.get("webformatURL")
        if not img_url:
            continue
        iw = int(it.get("imageWidth") or 0)
        ih = int(it.get("imageHeight") or 0)
        tags = str(it.get("tags") or "")
        img_ranked.append({
            "source": "pixabay",
            "title": f"pixabay-{it.get('id', '')}-{slugify(tags, 32)}",
            "url": img_url,
            "page_url": it.get("pageURL") or "",
            "width": iw,
            "height": ih,
            "orientation": "portrait" if ih > iw else "landscape",
            "mime": "image/jpeg",
            "license": "Pixabay Content License (Free commercial use)",
            "author": str(it.get("user") or "Pixabay")[:80],
            "_pop": int(it.get("downloads") or 0) + int(it.get("likes") or 0) * 10,
        })
    img_ranked.sort(
        key=lambda x: (1 if x["height"] > x["width"] else 0, x["_pop"]),
        reverse=True,
    )
    out_imgs: list[dict[str, Any]] = []
    for item in img_ranked[:limit]:
        item.pop("_pop", None)
        out_imgs.append(item)
    return out_imgs


def search_wikimedia(query: str, kind: str, limit: int) -> list[dict[str, Any]]:
    ftype = "video" if kind == "video" else ("audio" if kind == "audio" else "bitmap")
    params_dict: dict[str, Any] = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"filetype:{ftype} {query}",
        "gsrnamespace": 6,
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "format": "json",
    }
    if kind == "image":
        params_dict["iiurlwidth"] = 1920
    params = urllib.parse.urlencode(params_dict)
    raw, _ = http_get(f"https://commons.wikimedia.org/w/api.php?{params}", timeout=12.0)
    j = json.loads(raw.decode("utf-8", "replace"))
    pages = (j.get("query") or {}).get("pages") or {}
    hits = []
    for p in pages.values():
        ii = (p.get("imageinfo") or [{}])[0]
        url = (ii.get("thumburl") if kind == "image" and ii.get("thumburl") else ii.get("url"))
        if not url:
            continue
        meta = ii.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value") or "Wikimedia Commons"
        author = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value") or "").strip()
        hits.append({
            "source": "wikimedia",
            "title": p.get("title", "").replace("File:", ""),
            "url": url,
            "page_url": ii.get("descriptionurl") or "",
            "width": ii.get("width", 0),
            "height": ii.get("height", 0),
            "mime": ii.get("mime", ""),
            "license": lic,
            "author": author[:80],
        })
    return hits


def search_nasa(query: str, kind: str, limit: int) -> list[dict[str, Any]]:
    mtype = "video" if kind == "video" else ("audio" if kind == "audio" else "image")
    params = urllib.parse.urlencode({"q": query, "media_type": mtype, "page_size": limit})
    raw, _ = http_get(f"https://images-api.nasa.gov/search?{params}", timeout=12.0)
    j = json.loads(raw.decode("utf-8", "replace"))
    hits = []
    for it in ((j.get("collection") or {}).get("items") or [])[:limit]:
        data = (it.get("data") or [{}])[0]
        href = it.get("href")
        media_url = ""
        if href:
            try:
                mraw, _ = http_get(href, timeout=10.0)
                urls = json.loads(mraw.decode("utf-8", "replace"))
                if kind == "video":
                    media_url = next((u for u in urls if u.endswith("~medium.mp4") or u.endswith("~orig.mp4") or u.endswith(".mp4")), "")
                elif kind == "image":
                    media_url = next((u for u in urls if u.endswith("~large.jpg") or u.endswith("~orig.jpg") or u.endswith(".jpg")), "")
                else:
                    media_url = next((u for u in urls if u.endswith(".mp3") or u.endswith(".wav")), "")
            except Exception:
                pass
        if not media_url:
            continue
        hits.append({
            "source": "nasa",
            "title": data.get("title", ""),
            "url": media_url,
            "page_url": f"https://images.nasa.gov/details/{data.get('nasa_id', '')}",
            "width": 0,
            "height": 0,
            "mime": "",
            "license": "Public Domain (NASA)",
            "author": data.get("center") or "NASA",
        })
    return hits


def search_archive(query: str, kind: str, limit: int) -> list[dict[str, Any]]:
    mtype = "movies" if kind == "video" else ("audio" if kind == "audio" else "image")
    params = urllib.parse.urlencode({
        "q": f"mediatype:{mtype} AND ({query})",
        "fl[]": ["identifier", "title", "licenseurl"],
        "rows": limit,
        "output": "json",
    }, doseq=True)
    raw, _ = http_get(f"https://archive.org/advancedsearch.php?{params}", timeout=12.0)
    j = json.loads(raw.decode("utf-8", "replace"))
    hits = []
    for doc in ((j.get("response") or {}).get("docs") or [])[:limit]:
        ident = doc.get("identifier")
        if not ident:
            continue
        try:
            mraw, _ = http_get(f"https://archive.org/metadata/{ident}/files", timeout=10.0)
            files = json.loads(mraw.decode("utf-8", "replace")).get("result") or []
            exts = (".mp4",) if kind == "video" else ((".mp3", ".ogg") if kind == "audio" else (".jpg", ".png"))
            chosen = next((f["name"] for f in files if str(f.get("name", "")).lower().endswith(exts)), None)
            if not chosen:
                continue
            hits.append({
                "source": "archive",
                "title": doc.get("title") or ident,
                "url": f"https://archive.org/download/{ident}/{urllib.parse.quote(chosen)}",
                "page_url": f"https://archive.org/details/{ident}",
                "width": 0,
                "height": 0,
                "mime": "",
                "license": doc.get("licenseurl") or "Internet Archive (check page)",
                "author": "Internet Archive",
            })
        except Exception:
            continue
    return hits


def search_openverse(query: str, kind: str, limit: int) -> list[dict[str, Any]]:
    if kind == "video":
        return []
    ep = "audio" if kind == "audio" else "images"
    params = urllib.parse.urlencode({"q": query, "page_size": limit})
    raw, _ = http_get(f"https://api.openverse.org/v1/{ep}/?{params}", timeout=16.0)
    j = json.loads(raw.decode("utf-8", "replace"))
    hits = []
    for it in (j.get("results") or [])[:limit]:
        url = it.get("url")
        if not url:
            continue
        hits.append({
            "source": "openverse",
            "title": it.get("title") or "",
            "url": url,
            "page_url": it.get("foreign_landing_url") or "",
            "width": it.get("width") or 0,
            "height": it.get("height") or 0,
            "mime": "",
            "license": f"{it.get('license', '')} {it.get('license_version', '')}".strip(),
            "author": it.get("creator") or it.get("provider") or "",
        })
    return hits


def cmd_stock(args: argparse.Namespace) -> int:
    if args.assets:
        print(
            "错误：严禁在 stock 搜索时使用 --assets 将未经核验的 API 素材直接塞入 film/assets/！\n"
            "正确流程：1) 用 --download 3 --out runs/<目录>/materials 下载多个候选；"
            "2) 亲自看图打开自动生成的 candidate-sheet-*.jpg（音频跑 qc_video.py probe-audio）逐项核对六维制作要求；"
            "3) 仅对核验达标的那 1 条执行 fetch_asset.py register --shot <镜号> --fit-reason '<具体实看核验结论>' 入库。",
            file=sys.stderr,
        )
        return 2
    has_pixabay = bool(_load_pixabay_key())
    if args.source != "auto":
        sources = [args.source]
    elif args.kind == "video":
        sources = (["pixabay"] if has_pixabay else []) + ["wikimedia", "nasa", "archive"]
    elif args.kind == "image":
        sources = (["pixabay"] if has_pixabay else []) + ["wikimedia", "openverse", "nasa"]
    else:
        sources = ["wikimedia", "openverse", "nasa"]
    hits: list[dict[str, Any]] = []
    for src in sources:
        try:
            if src == "pixabay":
                hits.extend(search_pixabay(args.query, args.kind, args.limit))
            elif src == "wikimedia":
                hits.extend(search_wikimedia(args.query, args.kind, args.limit))
            elif src == "nasa":
                hits.extend(search_nasa(args.query, args.kind, args.limit))
            elif src == "archive":
                hits.extend(search_archive(args.query, args.kind, args.limit))
            elif src == "openverse":
                hits.extend(search_openverse(args.query, args.kind, args.limit))
        except Exception as exc:
            safe_err = re.sub(r"key=[^&\s]+", "key=***", str(exc))
            print(f"[warn] {src} 查询失败：{safe_err}", file=sys.stderr)
        if args.source == "auto" and len(hits) >= args.limit:
            break

    hits = hits[: args.limit]
    downloaded: list[dict[str, Any]] = []
    saved_paths: list[Path] = []
    sheet_rel: str | None = None
    probes: list[dict[str, Any]] = []
    if args.download > 0 and args.out:
        out_dir = Path(args.out)
        slug = slugify(args.query)
        def_ext = ".mp4" if args.kind == "video" else (".mp3" if args.kind == "audio" else ".jpg")
        for idx, h in enumerate(hits[: args.download], 1):
            try:
                saved = download_file(h["url"], out_dir, f"{h['source']}-{slug}-{idx}", default_ext=def_ext, timeout=35.0)
                saved_paths.append(saved)
                downloaded.append({"file": rel_to_root(saved), "meta": h})
            except Exception as exc:
                safe_dl_err = re.sub(r"key=[^&\s]+", "key=***", str(exc))
                print(f"[warn] 下载失败 {h['url']}: {safe_dl_err}", file=sys.stderr)
        if args.kind in {"video", "image"} and saved_paths:
            sheet_rel, probes = build_candidate_sheet(saved_paths, out_dir / f"candidate-sheet-{slug}.jpg")

    print(
        json.dumps(
            {
                "query": args.query,
                "kind": args.kind,
                "hits": hits,
                "downloaded_candidates": downloaded,
                "candidate_sheet": sheet_rel,
                "candidates_probe": probes,
                "verification_required": (
                    "严禁盲选第1条！必须先看图打开 candidate_sheet（音频跑 probe-audio）逐项核对六维制作要求，"
                    "再对唯一入选件执行 fetch_asset.py register --shot <镜号> --fit-reason '<具体实看核验说明>'"
                    if downloaded
                    else "候选列表仅作初筛，请挑选 2-4 条下载至 materials/ 抽帧验货后再 register 入库"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


# -------------------- 3 & 4. video-search / video-clip (reuse workspace yt-dlp) --------------------

def ytdlp_bin() -> Path:
    root = svp_root()
    candidates = [
        root / "rea-video" / ".venv" / "Scripts" / "yt-dlp.exe",
        root / "rea-video" / ".venv" / "bin" / "yt-dlp",
        root / "creatorhub" / ".venv" / "Scripts" / "yt-dlp.exe",
        root / "creatorhub" / ".venv" / "bin" / "yt-dlp",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    found = shutil.which("yt-dlp")
    if found:
        return Path(found)
    raise FileNotFoundError(
        "未找到工作区 yt-dlp（rea-video/.venv 或 creatorhub/.venv），请在工作区虚拟环境执行 pip install yt-dlp yt-dlp-ejs"
    )


def cmd_video_search(args: argparse.Namespace) -> int:
    exe = ytdlp_bin()
    proc = subprocess.run(
        [str(exe), "--flat-playlist", "--dump-json", f"ytsearch{args.limit}:{args.query}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
        return 1
    hits = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            j = json.loads(line)
            hits.append({
                "title": j.get("title"),
                "channel": j.get("channel") or j.get("uploader"),
                "duration_sec": j.get("duration"),
                "url": j.get("webpage_url") or j.get("url"),
                "view_count": j.get("view_count"),
            })
        except Exception:
            continue
    print(json.dumps({"query": args.query, "hits": hits}, ensure_ascii=False, indent=2))
    return 0


def cmd_video_clip(args: argparse.Namespace) -> int:
    exe = ytdlp_bin()
    out_file = Path(args.out)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_file.parent / ".ytdlp-tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(exe),
        "--no-playlist",
        "--paths", f"temp:{tmp_dir}",
        "--download-sections", f"*{args.start}-{args.end}",
        "--force-keyframes-at-cuts",
        "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b",
        "--merge-output-format", "mp4",
        "-o", str(out_file),
        args.url,
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    shutil.rmtree(tmp_dir, ignore_errors=True)
    if proc.returncode != 0 or not out_file.is_file():
        print(f"切片下载失败：{proc.stderr.strip()}", file=sys.stderr)
        return 1

    if args.mute:
        muted_tmp = out_file.with_suffix(".muted.mp4")
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-i", str(out_file), "-c:v", "copy", "-an", str(muted_tmp)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        muted_tmp.replace(out_file)

    if args.assets:
        print(
            "错误：video-clip 切片须先落盘至 materials/ 并查看自动生成的 candidate-sheet 核验画面无硬切/无硬字幕后，"
            "再用 fetch_asset.py register --shot <镜号> --fit-reason '<具体核验说明>' 签收入 film/assets/。",
            file=sys.stderr,
        )
        return 2

    sheet_rel, probes = build_candidate_sheet([out_file], out_file.parent / f"candidate-sheet-{out_file.stem}.jpg")
    print(
        json.dumps(
            {
                "file": rel_to_root(out_file),
                "candidate_sheet": sheet_rel,
                "candidates_probe": probes,
                "verification_required": "请先打开 candidate_sheet 核验切片起止帧干净且契合台词，再用 register --shot <镜号> --fit-reason <说明> 入库",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


# -------------------- 5. inspect-candidates & 6. register --------------------

def cmd_inspect_candidates(args: argparse.Namespace) -> int:
    targets: list[Path] = []
    for f_raw in (args.files or []):
        p = Path(f_raw)
        if p.is_file():
            targets.append(p)
        elif p.is_dir():
            targets.extend(
                sorted(
                    x
                    for x in p.iterdir()
                    if x.is_file() and (x.suffix.lower() in VIDEO_EXTS or x.suffix.lower() in IMAGE_EXTS)
                )
            )
    if args.dir:
        d = Path(args.dir)
        if d.is_dir():
            targets.extend(
                sorted(
                    x
                    for x in d.iterdir()
                    if x.is_file()
                    and not x.name.startswith("candidate-sheet")
                    and x.name.lower() != "logo.png"
                    and (x.suffix.lower() in VIDEO_EXTS or x.suffix.lower() in IMAGE_EXTS)
                )
            )
    dedup: list[Path] = []
    seen_r: set[Path] = set()
    for t in targets:
        rp = t.resolve()
        if rp not in seen_r:
            seen_r.add(rp)
            dedup.append(t)
    if not dedup:
        print("错误：未找到待检视的候选视频或图片文件", file=sys.stderr)
        return 1

    out_sheet = Path(args.out)
    sheet_rel, probes = build_candidate_sheet(dedup, out_sheet)
    print(
        json.dumps(
            {
                "candidate_count": len(dedup),
                "candidate_sheet": sheet_rel,
                "candidates": probes,
                "next_step": "请亲自看图打开 candidate_sheet 逐行核对六维制作要求；剔除不符项后，对入选素材执行 register --shot <镜号> --fit-reason '<具体实看核验说明>'",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    src = Path(args.file)
    if not src.is_file():
        print(f"错误：文件不存在 {src}", file=sys.stderr)
        return 1
    shot_id = (args.shot or "").strip()
    fit_reason = re.sub(r"\s+", " ", (args.fit_reason or "").strip())
    net_reason_len = len(re.sub(r"\s+", "", fit_reason))
    if not shot_id:
        print("错误：register 必须指定 --shot <对应分镜号或音轨槽位，如 s03 / ms-br-02 / bgm>！", file=sys.stderr)
        return 2
    if net_reason_len < 12 or LAZY_FIT_REASON_RE.match(fit_reason):
        print(
            "错误：register 必须提供真实具体的 --fit-reason（>=12字，严禁填“符合要求/OK”等敷衍套话）！\n"
            "必须写明实看/实听核验结论：具体画面/声音内容 + 对应哪句台词需求 + 构图/地域/影调/稳像为何达标。",
            file=sys.stderr,
        )
        return 2
    copied = copy_to_openfilm_areas(
        src,
        Path(args.assets),
        args.name,
        args.save_reusable,
        {
            "type": args.type,
            "source": args.source,
            "url": args.url,
            "license": args.license,
            "prompt": args.prompt,
            "shot_id": shot_id,
            "fit_verified": True,
            "fit_reason": fit_reason,
        },
    )
    print(json.dumps({"shot_id": shot_id, "fit_verified": True, **copied}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    p = argparse.ArgumentParser(description="工作区素材搜索、抓取与 OpenFilm 归档登记工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_news = sub.add_parser("news-page", help="抓取官方新闻稿/博客正文摘要、高清配图与可选网页截图")
    p_news.add_argument("--url", required=True)
    p_news.add_argument("--out", required=True, help="原件保存目录（如 runs/<目录>/materials）")
    p_news.add_argument("--assets", default="", help="已禁用直塞：请先落盘 --out materials 检视后再用 register 签收")
    p_news.add_argument("--slug", default="")
    p_news.add_argument("--screenshot", action="store_true", help="保存 1080px 宽干净首屏截图")
    p_news.add_argument("--max-images", type=int, default=6)
    p_news.set_defaults(func=cmd_news_page)

    p_stock = sub.add_parser("stock", help="搜索免版权高清素材候选落入 materials/ 并生成检视拼图（本地已配 Pixabay 时优先竖屏稳像实拍）")
    p_stock.add_argument("--query", required=True, help="建议用英文具象视觉动作关键词，勿搜宽泛概念词")
    p_stock.add_argument("--kind", choices=["image", "video", "audio"], default="image")
    p_stock.add_argument("--source", choices=["auto", "pixabay", "wikimedia", "nasa", "archive", "openverse"], default="auto")
    p_stock.add_argument("--limit", type=int, default=5)
    p_stock.add_argument("--download", type=int, default=0, help="下载前 N 条候选到 --out 并自动生成检视拼图（默认 0 仅列出候选）")
    p_stock.add_argument("--out", default="", help="候选暂存目录（如 runs/<目录>/materials）")
    p_stock.add_argument("--assets", default="", help="已禁用直塞：必须先看 candidate-sheet 核验后用 register --shot --fit-reason 签收")
    p_stock.add_argument("--save-reusable", action="store_true", help="仅在 register 阶段生效")
    p_stock.set_defaults(func=cmd_stock)

    p_vs = sub.add_parser("video-search", help="用工作区 yt-dlp 搜索官方发布会 / 产品 Demo")
    p_vs.add_argument("--query", required=True)
    p_vs.add_argument("--limit", type=int, default=5)
    p_vs.set_defaults(func=cmd_video_search)

    p_vc = sub.add_parser("video-clip", help="用工作区 yt-dlp 精准截取指定时间段视频至 materials/ 并生成检视拼图")
    p_vc.add_argument("--url", required=True)
    p_vc.add_argument("--start", required=True, help="如 00:10")
    p_vc.add_argument("--end", required=True, help="如 00:16")
    p_vc.add_argument("--out", required=True, help="候选输出 MP4 路径（如 runs/<目录>/materials/demo.mp4）")
    p_vc.add_argument("--assets", default="", help="已禁用直塞：请先看 candidate-sheet 核验后用 register 签收")
    p_vc.add_argument("--asset-name", default=None)
    p_vc.add_argument("--mute", action="store_true", help="去掉原声（用于纯 B-roll 画面）")
    p_vc.add_argument("--source", default="")
    p_vc.set_defaults(func=cmd_video_clip)

    p_insp = sub.add_parser("inspect-candidates", help="为候选视频/图片生成 4 帧检视拼图 candidate-sheet.jpg 与技术规格表")
    p_insp.add_argument("--files", nargs="*", default=[], help="待检视的候选文件路径列表")
    p_insp.add_argument("--dir", default="", help="可选：扫描指定目录（如 materials/ 或 film/assets/）内的候选媒体")
    p_insp.add_argument("--out", required=True, help="输出的检视拼图路径（如 runs/<目录>/materials/candidate-sheet.jpg）")
    p_insp.set_defaults(func=cmd_inspect_candidates)

    p_reg = sub.add_parser("register", help="经六维制作要求核验通过后，签收素材入 film/assets/ 并写入 credits.json")
    p_reg.add_argument("--file", required=True, help="已核验通过的素材路径（materials/ 原件或 openfilm get 已拉取的 film/assets/ 文件）")
    p_reg.add_argument("--assets", required=True, help="目标 film/assets 目录")
    p_reg.add_argument("--shot", required=True, help="绑定的分镜 ID 或音轨槽位（如 s03 / ms-br-02 / bgm / sfx-hit）")
    p_reg.add_argument("--fit-reason", required=True, help="具体核验通过说明（>=12字：实看内容 + 台词语义对应 + 地域/构图/影调/稳像核验结论）")
    p_reg.add_argument("--name", default=None)
    p_reg.add_argument("--save-reusable", action="store_true")
    p_reg.add_argument("--type", default="media")
    p_reg.add_argument("--source", required=True)
    p_reg.add_argument("--url", default="")
    p_reg.add_argument("--license", default="")
    p_reg.add_argument("--prompt", default="")
    p_reg.set_defaults(func=cmd_register)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
