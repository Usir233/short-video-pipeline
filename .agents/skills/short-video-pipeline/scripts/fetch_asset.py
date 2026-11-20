#!/usr/bin/env python3
"""
素材寻源与落盘工具（纯 Python 标准库 + 复用工作区已有 playwright-core / yt-dlp / ffmpeg，零新增依赖）。

子命令（先 source env.sh）：
  1) news-page    抓官方新闻稿/博客正文事实 + 自动提取高清配图 + 可选网页干净截图
  2) stock        免 Key 搜索/下载公开免版权素材（Wikimedia Commons / NASA / Internet Archive / Openverse）
  3) video-search 用工作区 yt-dlp 搜索官方发布会 / 产品 Demo（YouTube 等）
  4) video-clip   用工作区 yt-dlp + ffmpeg 按起止秒精准截取官方视频短片段（≤6s 推荐）
  5) register     将筛选好的素材从 materials/ 放入 film/assets/（可选同步到 .local/openfilm-user/saved/）并登记 credits.json
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
        return str(p.resolve().relative_to(svp_root().resolve()))
    except Exception:
        return str(p)


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

    const container = document.querySelector('article, main, .post_content, .article-content, #paragraph') || document.body;
    const text = (container?.innerText || '').replace(/\s+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim().slice(0, 4000);

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

    proc = subprocess.run(["node", "-e", node_script], env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"抓页失败：{proc.stderr.strip()}", file=sys.stderr)
        return 1

    info = json.loads(proc.stdout.strip().splitlines()[-1])
    downloaded: list[dict[str, Any]] = []
    for idx, im in enumerate(info.get("imgs") or [], 1):
        try:
            saved = download_file(im["src"], out_dir, f"{slug}-img{idx}", default_ext=".jpg")
            if saved.stat().st_size < 8192:
                saved.unlink(missing_ok=True)
                continue
            rec = {
                "path": str(saved),
                "url": im["src"],
                "width": im.get("width", 0),
                "height": im.get("height", 0),
                "alt": im.get("alt", ""),
                "size_bytes": saved.stat().st_size,
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

    # 若指定 --assets，将截图和前几张图一并登记到 OpenFilm 项目素材区（供挑选）
    if args.assets:
        assets_dir = Path(args.assets)
        if screenshot_path and Path(screenshot_path).is_file():
            copy_to_openfilm_areas(
                Path(screenshot_path), assets_dir, None, False,
                {"type": "news_screenshot", "source": info.get("title") or args.url, "url": args.url, "license": "新闻报道合理引用（须标注来源）"},
            )
        for rec in downloaded:
            copy_to_openfilm_areas(
                Path(rec["path"]), assets_dir, None, False,
                {"type": "news_image", "source": info.get("title") or args.url, "url": rec["url"], "page_url": args.url, "license": "新闻/官方发布配图（须标注来源）"},
            )

    print(json.dumps({
        "article_json": str(article_json),
        "title": manifest["title"],
        "screenshot": manifest["screenshot"],
        "downloaded_images": [d["path"] for d in downloaded],
    }, ensure_ascii=False, indent=2))
    return 0


# -------------------- 2. stock (zero-key public APIs) --------------------

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
    sources = [args.source] if args.source != "auto" else (
        ["wikimedia", "nasa", "archive"] if args.kind == "video" else ["wikimedia", "openverse", "nasa"]
    )
    hits: list[dict[str, Any]] = []
    for src in sources:
        try:
            if src == "wikimedia":
                hits.extend(search_wikimedia(args.query, args.kind, args.limit))
            elif src == "nasa":
                hits.extend(search_nasa(args.query, args.kind, args.limit))
            elif src == "archive":
                hits.extend(search_archive(args.query, args.kind, args.limit))
            elif src == "openverse":
                hits.extend(search_openverse(args.query, args.kind, args.limit))
        except Exception as exc:
            print(f"[warn] {src} 查询失败：{exc}", file=sys.stderr)
        if args.source == "auto" and len(hits) >= args.limit:
            break

    hits = hits[: args.limit]
    downloaded: list[dict[str, Any]] = []
    if args.download > 0 and args.out:
        out_dir = Path(args.out)
        slug = slugify(args.query)
        def_ext = ".mp4" if args.kind == "video" else (".mp3" if args.kind == "audio" else ".jpg")
        for idx, h in enumerate(hits[: args.download], 1):
            try:
                saved = download_file(h["url"], out_dir, f"{h['source']}-{slug}-{idx}", default_ext=def_ext, timeout=35.0)
                copied = copy_to_openfilm_areas(
                    saved,
                    Path(args.assets) if args.assets else None,
                    None,
                    args.save_reusable,
                    {
                        "type": f"stock_{args.kind}",
                        "source": h["source"],
                        "title": h["title"],
                        "author": h["author"],
                        "license": h["license"],
                        "url": h["url"],
                        "page_url": h["page_url"],
                        "query": args.query,
                    },
                )
                downloaded.append({"file": str(saved), **copied, "meta": h})
            except Exception as exc:
                print(f"[warn] 下载失败 {h['url']}: {exc}", file=sys.stderr)

    print(json.dumps({"query": args.query, "kind": args.kind, "hits": hits, "downloaded": downloaded}, ensure_ascii=False, indent=2))
    return 0


# -------------------- 3 & 4. video-search / video-clip (reuse creatorhub yt-dlp) --------------------

def ytdlp_bin() -> Path:
    cand = svp_root() / "creatorhub" / ".venv" / "bin" / "yt-dlp"
    if cand.is_file():
        return cand
    found = shutil.which("yt-dlp")
    if found:
        return Path(found)
    raise FileNotFoundError("未找到工作区 creatorhub/.venv/bin/yt-dlp")


def cmd_video_search(args: argparse.Namespace) -> int:
    exe = ytdlp_bin()
    proc = subprocess.run(
        [str(exe), "--flat-playlist", "--dump-json", f"ytsearch{args.limit}:{args.query}"],
        capture_output=True,
        text=True,
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
    proc = subprocess.run(cmd, capture_output=True, text=True)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    if proc.returncode != 0 or not out_file.is_file():
        print(f"切片下载失败：{proc.stderr.strip()}", file=sys.stderr)
        return 1

    if args.mute:
        muted_tmp = out_file.with_suffix(".muted.mp4")
        subprocess.run(["ffmpeg", "-y", "-i", str(out_file), "-c:v", "copy", "-an", str(muted_tmp)], check=True, capture_output=True)
        muted_tmp.replace(out_file)

    copied = copy_to_openfilm_areas(
        out_file,
        Path(args.assets) if args.assets else None,
        args.asset_name,
        False,
        {
            "type": "official_video_clip",
            "source": args.source or "官方视频切片（须标注来源）",
            "url": args.url,
            "section": f"{args.start}-{args.end}",
            "muted": bool(args.mute),
            "license": "新闻报道/官方发布短切片合理引用",
        },
    )
    print(json.dumps({"file": str(out_file), **copied}, ensure_ascii=False, indent=2))
    return 0


# -------------------- 5. register --------------------

def cmd_register(args: argparse.Namespace) -> int:
    src = Path(args.file)
    if not src.is_file():
        print(f"错误：文件不存在 {src}", file=sys.stderr)
        return 1
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
        },
    )
    print(json.dumps(copied, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="工作区素材搜索、抓取与 OpenFilm 归档登记工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_news = sub.add_parser("news-page", help="抓取官方新闻稿/博客正文摘要、高清配图与可选网页截图")
    p_news.add_argument("--url", required=True)
    p_news.add_argument("--out", required=True, help="原件保存目录（如 runs/<目录>/materials）")
    p_news.add_argument("--assets", default="", help="可选：同时复制到 OpenFilm film/assets/ 并记入 credits.json")
    p_news.add_argument("--slug", default="")
    p_news.add_argument("--screenshot", action="store_true", help="保存 1080px 宽干净首屏截图")
    p_news.add_argument("--max-images", type=int, default=6)
    p_news.set_defaults(func=cmd_news_page)

    p_stock = sub.add_parser("stock", help="免 Key 搜索/下载公开免版权素材（Wikimedia/NASA/Archive/Openverse）")
    p_stock.add_argument("--query", required=True, help="建议用英文视觉关键词")
    p_stock.add_argument("--kind", choices=["image", "video", "audio"], default="image")
    p_stock.add_argument("--source", choices=["auto", "wikimedia", "nasa", "archive", "openverse"], default="auto")
    p_stock.add_argument("--limit", type=int, default=5)
    p_stock.add_argument("--download", type=int, default=0, help="下载前 N 条到 --out（默认 0 仅列出候选）")
    p_stock.add_argument("--out", default="", help="原件目录（如 runs/<目录>/materials）")
    p_stock.add_argument("--assets", default="", help="可选：同时复制到 film/assets/ 并记入 credits.json")
    p_stock.add_argument("--save-reusable", action="store_true", help="同步复制进 .local/openfilm-user/saved/ 供 my-media 复用")
    p_stock.set_defaults(func=cmd_stock)

    p_vs = sub.add_parser("video-search", help="用工作区 yt-dlp 搜索官方发布会 / 产品 Demo")
    p_vs.add_argument("--query", required=True)
    p_vs.add_argument("--limit", type=int, default=5)
    p_vs.set_defaults(func=cmd_video_search)

    p_vc = sub.add_parser("video-clip", help="用工作区 yt-dlp 精准截取指定时间段视频")
    p_vc.add_argument("--url", required=True)
    p_vc.add_argument("--start", required=True, help="如 00:10")
    p_vc.add_argument("--end", required=True, help="如 00:16")
    p_vc.add_argument("--out", required=True, help="输出 MP4 路径（如 runs/<目录>/materials/demo.mp4）")
    p_vc.add_argument("--assets", default="", help="可选：复制到 film/assets/ 目录并记入 credits.json")
    p_vc.add_argument("--asset-name", default=None)
    p_vc.add_argument("--mute", action="store_true", help="去掉原声（用于纯 B-roll 画面）")
    p_vc.add_argument("--source", default="")
    p_vc.set_defaults(func=cmd_video_clip)

    p_reg = sub.add_parser("register", help="将筛选好的素材落盘到 film/assets/（可选 saved/）并更新 credits.json")
    p_reg.add_argument("--file", required=True)
    p_reg.add_argument("--assets", required=True)
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
