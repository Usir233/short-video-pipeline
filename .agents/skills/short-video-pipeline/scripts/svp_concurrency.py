#!/usr/bin/env python3
"""Workspace-local concurrency semaphore, Windows zombie-lock healer & atomic asset-claim ledger.

Designed specifically for local Windows / macOS / Linux execution with ZERO third-party dependencies:
1) Dual-pool Chromium / GPU token bucket (`.local/locks/`):
   - `render` pool (default 2 slots): wraps `openfilm render` (including LUT `gradedCopies` pre-bake),
     auto-caps `--workers` (3 when dual-running, up to 4 when solo with ample RAM), and enforces
     Windows physical free-RAM circuit breaker (>= 3.5 GB before launching a new render).
   - `preview` pool (default 2 slots): wraps `openfilm look`, Playwright `news-page`, and cover
     screenshots so total Chromium processes across the entire machine stay <= 8 (`2*3 + 2 = 8`).
2) Dead-PID & heartbeat self-healing locks:
   - Uses atomic directory creation (`os.mkdir`) + `owner.json` storing `(pid, create_time, heartbeat_at)`.
   - Verifies both PID liveness and OS process creation timestamp (`OpenProcess` + `GetProcessTimes` on
     Windows) so crashed/timed-out subagent locks are reclaimed automatically without PID-reuse hazards.
3) Cross-slot & multi-episode atomic asset anti-collision ledger (`.local/locks/asset-claims.json`):
   - Atomically claims stock media IDs, URLs, cover frame timestamps, and 64-bit visual `dHash` values
     per `batch_id` so parallel subagents never pick duplicate B-roll or cover frames.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Iterator

POOL_DEFAULTS: dict[str, int] = {
    "render": int(os.environ.get("SVP_MAX_RENDER_SLOTS", "2")),
    "preview": int(os.environ.get("SVP_MAX_PREVIEW_SLOTS", "2")),
}
DEFAULT_MIN_FREE_RAM_MB = float(os.environ.get("SVP_MIN_FREE_RAM_MB", "3584"))
HEARTBEAT_INTERVAL_SEC = 8.0
STALE_HEARTBEAT_TTL_SEC = 180.0


def svp_root() -> Path:
    env_root = os.environ.get("SVP_ROOT")
    if env_root:
        return Path(env_root).resolve()
    cur = Path(__file__).resolve()
    for p in cur.parents:
        if (p / ".agents" / "skills" / "short-video-pipeline" / "SKILL.md").is_file():
            return p
    return Path.cwd().resolve()


def locks_dir() -> Path:
    d = svp_root() / ".local" / "locks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def rel_to_root(path: Path | str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    try:
        return p.resolve().relative_to(svp_root()).as_posix()
    except Exception:
        return p.as_posix()


def infer_batch_and_slot(path_hint: Path | str | None, explicit_batch: str = "", explicit_slot: str = "") -> tuple[str, str]:
    """Infer `(batch_id, slot_id)` from `runs/<run_id>/(master|variants/vN-...)` when not explicitly passed."""
    batch_id = explicit_batch.strip()
    slot_id = explicit_slot.strip()
    if path_hint:
        norm = Path(path_hint).resolve().as_posix()
        m_run = re.search(r"/runs/([^/]+)(?:/|$)", norm)
        if m_run and not batch_id:
            batch_id = m_run.group(1)
        if not slot_id:
            if "/master/" in norm or norm.endswith("/master"):
                slot_id = "master"
            else:
                m_var = re.search(r"/variants/(v\d+[^/]*)", norm)
                if m_var:
                    slot_id = m_var.group(1).split("-", 1)[0].lower()
    return (batch_id or "default-batch", slot_id or f"pid-{os.getpid()}")


# ---------------------------------------------------------------------------
# Cross-platform Process Liveness & Available Physical Memory Inspection
# ---------------------------------------------------------------------------

if sys.platform == "win32":

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_uint32),
            ("dwMemoryLoad", ctypes.c_uint32),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]


def get_process_identity(pid: int) -> tuple[bool, int | None]:
    """Return `(is_alive, create_time_token)` for `pid`."""
    if pid <= 0:
        return False, None
    if sys.platform == "win32":
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        ERROR_ACCESS_DENIED = 5
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            err = ctypes.get_last_error()
            if err == ERROR_ACCESS_DENIED:
                return True, None
            return False, None
        try:
            exit_code = ctypes.c_uint32(0)
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                if exit_code.value != STILL_ACTIVE:
                    return False, None
            ct, et, kt, ut = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
            if kernel32.GetProcessTimes(
                handle, ctypes.byref(ct), ctypes.byref(et), ctypes.byref(kt), ctypes.byref(ut)
            ):
                token = (int(ct.dwHighDateTime) << 32) | int(ct.dwLowDateTime)
                return True, token
            return True, None
        finally:
            kernel32.CloseHandle(handle)

    # POSIX (Linux / macOS)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False, None
    except PermissionError:
        return True, None
    except OSError:
        return False, None

    stat_p = Path(f"/proc/{pid}/stat")
    if stat_p.is_file():
        try:
            raw = stat_p.read_text(encoding="utf-8", errors="replace")
            after_comm = raw.rsplit(")", 1)[-1].split()
            if len(after_comm) >= 20:
                return True, int(after_comm[19])
        except Exception:
            pass
    return True, None


def get_available_ram_mb() -> float | None:
    """Return currently available physical RAM in MiB, or None if unavailable."""
    if sys.platform == "win32":
        try:
            ms = _MEMORYSTATUSEX()
            ms.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                return round(float(ms.ullAvailPhys) / (1024.0 * 1024.0), 1)
        except Exception:
            return None
        return None

    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        try:
            txt = meminfo.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^MemAvailable:\s*(\d+)\s*kB", txt, flags=re.MULTILINE)
            if m:
                return round(float(m.group(1)) / 1024.0, 1)
        except Exception:
            pass
    if sys.platform == "darwin":
        try:
            proc = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3)
            if proc.returncode == 0:
                ps_m = re.search(r"page size of (\d+) bytes", proc.stdout)
                page_sz = int(ps_m.group(1)) if ps_m else 4096
                free_pages = 0
                for key in ("Pages free", "Pages inactive", "Pages speculative"):
                    km = re.search(rf"{key}:\s+(\d+)\.", proc.stdout)
                    if km:
                        free_pages += int(km.group(1))
                if free_pages > 0:
                    return round((free_pages * page_sz) / (1024.0 * 1024.0), 1)
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Self-Healing Atomic Directory Lease Semaphore
# ---------------------------------------------------------------------------

def _slot_dir(pool: str, idx: int) -> Path:
    return locks_dir() / f"{pool}-slot-{idx}.lockdir"


def _read_owner(slot_path: Path) -> dict[str, Any] | None:
    owner_file = slot_path / "owner.json"
    if not owner_file.is_file():
        return None
    try:
        data = json.loads(owner_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_owner_atomic(slot_path: Path, payload: dict[str, Any]) -> None:
    tmp = slot_path / f"owner.{os.getpid()}.{threading.get_ident()}.tmp"
    final = slot_path / "owner.json"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(final)


def _is_slot_stale(slot_path: Path, stale_ttl_sec: float = STALE_HEARTBEAT_TTL_SEC) -> tuple[bool, str]:
    if not slot_path.exists():
        return False, "free"
    meta = _read_owner(slot_path)
    now = time.time()
    if meta is None:
        try:
            age = now - slot_path.stat().st_mtime
        except OSError:
            return False, "vanished"
        if age > 8.0:
            return True, f"missing_owner_json(age={age:.1f}s)"
        return False, "initializing"

    pid = int(meta.get("pid") or 0)
    expected_ct = meta.get("create_time")
    alive, actual_ct = get_process_identity(pid)
    if not alive:
        return True, f"dead_pid({pid})"
    if expected_ct is not None and actual_ct is not None and int(expected_ct) != int(actual_ct):
        return True, f"reused_pid({pid})"

    hb = float(meta.get("heartbeat_at") or meta.get("acquired_at_epoch") or 0.0)
    if hb > 0 and (now - hb) > stale_ttl_sec:
        return True, f"heartbeat_expired({now - hb:.0f}s>{stale_ttl_sec:.0f}s)"
    return False, "active"


def _try_reclaim_stale_slot(slot_path: Path, stale_ttl_sec: float = STALE_HEARTBEAT_TTL_SEC) -> bool:
    stale, _ = _is_slot_stale(slot_path, stale_ttl_sec=stale_ttl_sec)
    if not stale:
        return False
    trash = slot_path.parent / f".reclaim-{slot_path.name}-{os.getpid()}-{int(time.time() * 1000)}"
    try:
        slot_path.rename(trash)
    except OSError:
        return False
    shutil.rmtree(trash, ignore_errors=True)
    return True


def inspect_pool_status(pool: str, max_slots: int | None = None) -> list[dict[str, Any]]:
    slots_n = max_slots if max_slots is not None else POOL_DEFAULTS.get(pool, 2)
    out: list[dict[str, Any]] = []
    for idx in range(slots_n):
        sp = _slot_dir(pool, idx)
        if sp.exists():
            reclaimed = _try_reclaim_stale_slot(sp)
            if reclaimed or not sp.exists():
                out.append({"slot": idx, "state": "free", "reclaimed_zombie": reclaimed})
                continue
            meta = _read_owner(sp) or {}
            out.append({"slot": idx, "state": "busy", **meta})
        else:
            out.append({"slot": idx, "state": "free"})
    return out


@contextmanager
def acquire_lease(
    pool: str,
    owner: str = "",
    max_slots: int | None = None,
    timeout_sec: float = 1800.0,
    min_free_ram_mb: float | None = None,
    cmd_desc: str = "",
) -> Iterator[dict[str, Any]]:
    """Acquire a self-healing slot in `pool` (`render` or `preview`) with optional free-RAM guard."""
    slots_n = max(1, max_slots if max_slots is not None else POOL_DEFAULTS.get(pool, 2))
    ram_floor = (
        DEFAULT_MIN_FREE_RAM_MB
        if (min_free_ram_mb is None and pool == "render")
        else (min_free_ram_mb or 0.0)
    )
    start_ts = time.time()
    _, my_ct = get_process_identity(os.getpid())
    chosen_slot: Path | None = None
    chosen_idx = -1
    low_ram_warned = False

    while True:
        elapsed = time.time() - start_ts
        if elapsed > timeout_sec:
            raise TimeoutError(
                f"等待 `{pool}` 并发锁超时({timeout_sec:.0f}s)：请运行 `svp_concurrency.py status` 检查槽位占用"
            )

        # Sweep stale zombie locks first
        busy_count = 0
        for idx in range(slots_n):
            sp = _slot_dir(pool, idx)
            if sp.exists() and not _try_reclaim_stale_slot(sp):
                busy_count += 1

        # Windows physical free-RAM circuit breaker before starting a heavy render
        avail_mb = get_available_ram_mb()
        ram_blocked = False
        if ram_floor > 0 and avail_mb is not None and avail_mb < ram_floor:
            # Allow solo emergency pass after 45s wait if 0 other render slots are running so machine never livelocks
            if busy_count > 0 or elapsed < 45.0:
                ram_blocked = True
                if not low_ram_warned:
                    print(
                        f"[svp-lock] 可用物理内存 {avail_mb:.0f} MB < 熔断线 {ram_floor:.0f} MB，"
                        f"`{pool}` 任务({owner or os.getpid()})自动排队等待内存释放...",
                        file=sys.stderr,
                    )
                    low_ram_warned = True

        if not ram_blocked:
            for idx in range(slots_n):
                sp = _slot_dir(pool, idx)
                try:
                    os.mkdir(sp)
                except FileExistsError:
                    continue
                now_ep = time.time()
                payload = {
                    "pool": pool,
                    "slot": idx,
                    "pid": os.getpid(),
                    "create_time": my_ct,
                    "owner": owner or f"pid-{os.getpid()}",
                    "cmd": cmd_desc[:200],
                    "acquired_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                    "acquired_at_epoch": round(now_ep, 3),
                    "heartbeat_at": round(now_ep, 3),
                }
                _write_owner_atomic(sp, payload)
                chosen_slot = sp
                chosen_idx = idx
                break

        if chosen_slot is not None:
            break
        time.sleep(1.2)

    stop_evt = threading.Event()

    def _heartbeat_worker() -> None:
        while not stop_evt.wait(HEARTBEAT_INTERVAL_SEC):
            if chosen_slot is None or not chosen_slot.exists():
                break
            try:
                cur_meta = _read_owner(chosen_slot)
                if not cur_meta or int(cur_meta.get("pid") or 0) != os.getpid():
                    break
                cur_meta["heartbeat_at"] = round(time.time(), 3)
                _write_owner_atomic(chosen_slot, cur_meta)
            except Exception:
                pass

    hb_thread = threading.Thread(target=_heartbeat_worker, name=f"svp-hb-{pool}-{chosen_idx}", daemon=True)
    hb_thread.start()

    other_busy = sum(
        1
        for idx in range(slots_n)
        if idx != chosen_idx and _slot_dir(pool, idx).exists() and not _is_slot_stale(_slot_dir(pool, idx))[0]
    )
    lease_info = {
        "pool": pool,
        "slot": chosen_idx,
        "max_slots": slots_n,
        "other_busy_slots": other_busy,
        "available_ram_mb": get_available_ram_mb(),
    }
    try:
        yield lease_info
    finally:
        stop_evt.set()
        if chosen_slot is not None and chosen_slot.exists():
            cur = _read_owner(chosen_slot)
            if cur is None or int(cur.get("pid") or 0) == os.getpid():
                shutil.rmtree(chosen_slot, ignore_errors=True)


# ---------------------------------------------------------------------------
# Atomic Asset Anti-Collision Ledger (`asset-claims.json`)
# ---------------------------------------------------------------------------

def _claims_file() -> Path:
    return locks_dir() / "asset-claims.json"


@contextmanager
def _claims_mutex(timeout_sec: float = 30.0) -> Iterator[None]:
    with acquire_lease("claims-mutex", owner=f"claims-{os.getpid()}", max_slots=1, timeout_sec=timeout_sec):
        yield


def compute_fast_dhash(media_path: Path, sample_t: float | None = None) -> str | None:
    """Compute 64-bit center-cropped dHash hex string using ffmpeg raw grayscale pipe."""
    if not media_path.is_file():
        return None
    vf_chain = "crop=iw*0.72:ih*0.72:iw*0.14:ih*0.14,scale=9:8:flags=area,format=gray"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if sample_t is not None and sample_t > 0:
        cmd += ["-ss", f"{sample_t:.2f}"]
    cmd += ["-i", str(media_path), "-frames:v", "1", "-vf", vf_chain, "-f", "rawvideo", "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or len(proc.stdout) < 72:
        return None
    px = proc.stdout[:72]
    bits = 0
    for r in range(8):
        row_off = r * 9
        for c in range(8):
            bits = (bits << 1) | (1 if px[row_off + c] > px[row_off + c + 1] else 0)
    return f"{bits:016x}"


def _hamming_hex(a_hex: str, b_hex: str) -> int:
    return (int(a_hex, 16) ^ int(b_hex, 16)).bit_count()


def _normalize_asset_key(asset_id: str = "", url: str = "", title: str = "") -> str:
    if asset_id.strip():
        return asset_id.strip().lower()
    for text in (title, url):
        m_px = re.search(r"pixabay-(\d+)", text, flags=re.IGNORECASE)
        if m_px:
            return f"pixabay:{m_px.group(1)}"
    if url.strip():
        parsed = re.sub(r"[?#].*$", "", url.strip().lower())
        return f"url:{hashlib.sha1(parsed.encode('utf-8')).hexdigest()[:16]}"
    if title.strip():
        return f"title:{title.strip().lower()}"
    return ""


def _load_claims_unlocked() -> dict[str, list[dict[str, Any]]]:
    cf = _claims_file()
    if not cf.is_file():
        return {}
    try:
        raw = json.loads(cf.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("batches"), dict):
            return raw["batches"]
    except Exception:
        pass
    return {}


def _save_claims_unlocked(batches: dict[str, list[dict[str, Any]]]) -> None:
    cf = _claims_file()
    tmp = cf.with_suffix(f".{os.getpid()}.tmp")
    payload = {
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "batches": batches,
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(cf)


def is_asset_claimed(
    batch_id: str,
    slot_id: str = "",
    asset_id: str = "",
    url: str = "",
    title: str = "",
) -> dict[str, Any] | None:
    """Return conflicting claim dict if `asset_id`/`url`/`title` is already claimed in `batch_id`."""
    key = _normalize_asset_key(asset_id=asset_id, url=url, title=title)
    if not key or not batch_id:
        return None
    batches = _load_claims_unlocked()
    for entry in batches.get(batch_id, []):
        if entry.get("key") == key:
            if slot_id and entry.get("slot") == slot_id:
                continue
            return entry
    return None


def claim_asset_entry(
    batch_id: str,
    slot_id: str,
    shot_id: str = "",
    asset_id: str = "",
    url: str = "",
    title: str = "",
    media_file: Path | None = None,
    sample_t: float | None = None,
    max_hamming: int = 10,
) -> dict[str, Any]:
    """Atomically check and register a visual asset or cover frame in `asset-claims.json`."""
    key = _normalize_asset_key(asset_id=asset_id, url=url, title=title)
    if not key and media_file is not None:
        key = f"file:{media_file.name.lower()}"

    dhash_hex: str | None = None
    if media_file is not None and media_file.is_file():
        is_vid = media_file.suffix.lower() in {".mp4", ".webm", ".mov", ".mkv", ".ogv"}
        eff_t = sample_t if sample_t is not None else (0.5 if is_vid else None)
        dhash_hex = compute_fast_dhash(media_file, sample_t=eff_t)

    with _claims_mutex():
        batches = _load_claims_unlocked()
        items = batches.setdefault(batch_id, [])

        for existing in items:
            same_slot_shot = (
                existing.get("slot") == slot_id
                and shot_id
                and existing.get("shot_id") == shot_id
            )
            if same_slot_shot:
                continue
            if key and existing.get("key") == key:
                return {
                    "claimed": False,
                    "reason": "key_collision",
                    "key": key,
                    "dhash": dhash_hex,
                    "conflict_with": existing,
                }
            ex_dh = existing.get("dhash")
            if dhash_hex and ex_dh:
                dist = _hamming_hex(dhash_hex, str(ex_dh))
                if dist <= max_hamming:
                    return {
                        "claimed": False,
                        "reason": f"dhash_collision(dist={dist}<={max_hamming})",
                        "key": key,
                        "dhash": dhash_hex,
                        "hamming_dist": dist,
                        "conflict_with": existing,
                    }

        # Remove prior entry for exact same (slot, shot_id) if re-registering a replacement
        if shot_id:
            items[:] = [
                it for it in items if not (it.get("slot") == slot_id and it.get("shot_id") == shot_id)
            ]

        rec = {
            "claimed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "batch_id": batch_id,
            "slot": slot_id,
            "shot_id": shot_id,
            "key": key,
            "url": url,
            "file": rel_to_root(media_file) if media_file else None,
            "dhash": dhash_hex,
        }
        items.append(rec)
        _save_claims_unlocked(batches)
        return {"claimed": True, "entry": rec}


# ---------------------------------------------------------------------------
# OpenFilm & CLI Commands
# ---------------------------------------------------------------------------

def _openfilm_bin() -> str:
    root = svp_root()
    candidates = [
        root / "node_modules" / ".bin" / ("openfilm.cmd" if sys.platform == "win32" else "openfilm"),
        root / "node_modules" / ".bin" / "openfilm",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    found = shutil.which("openfilm")
    if found:
        return found
    raise FileNotFoundError("未找到工作区 node_modules/.bin/openfilm，请先按 references/setup.md 安装")


def _build_workspace_env() -> dict[str, str]:
    root = svp_root()
    env = os.environ.copy()
    env["SVP_ROOT"] = str(root)
    env.setdefault("OPENFILM_HOME", str(root / ".local" / "openfilm"))
    env.setdefault("OPENFILM_LIBRARY", str(root / "runs"))
    env.setdefault("OPENFILM_EXPORTS", str(root / "runs"))
    env.setdefault("OPENFILM_SAVED", str(root / ".local" / "openfilm-user" / "saved"))
    env.setdefault("OPENFILM_SKILLS", str(root / ".local" / "openfilm-user" / "skills"))
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(root / "browsers" / "ms-playwright"))
    env["OPENFILM_NO_BROWSER"] = "1"
    env["PYTHONUTF8"] = "1"
    return env


def cmd_status(_args: argparse.Namespace) -> int:
    batches = _load_claims_unlocked()
    summary = {
        "available_ram_mb": get_available_ram_mb(),
        "min_free_ram_mb_floor": DEFAULT_MIN_FREE_RAM_MB,
        "render_pool": inspect_pool_status("render"),
        "preview_pool": inspect_pool_status("preview"),
        "claimed_batches": {k: len(v) for k, v in batches.items()},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    film_dir = Path(args.film_dir).resolve()
    if not (film_dir / "film.html").is_file():
        print(f"错误：未找到 OpenFilm 项目文件 {film_dir / 'film.html'}", file=sys.stderr)
        return 1

    out_raw = Path(args.out)
    out_abs = (film_dir / out_raw).resolve() if not out_raw.is_absolute() else out_raw.resolve()
    out_abs.parent.mkdir(parents=True, exist_ok=True)
    env = _build_workspace_env()

    # Step 1: 3-second preflight gate BEFORE touching the GPU semaphore!
    if not args.skip_preflight:
        qc_script = svp_root() / ".agents" / "skills" / "short-video-pipeline" / "scripts" / "qc_video.py"
        pre_cmd = [sys.executable, str(qc_script), "preflight-film", "--film-dir", str(film_dir)]
        if args.style and args.style != "auto":
            pre_cmd += ["--style", args.style]
        pre_proc = subprocess.run(pre_cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if pre_proc.returncode != 0:
            print(
                "[svp-render] 渲染前 3 秒预检(preflight-film)未通过，已拦截显卡白跑！请先修复以下问题：",
                file=sys.stderr,
            )
            if pre_proc.stdout.strip():
                print(pre_proc.stdout.strip(), file=sys.stderr)
            if pre_proc.stderr.strip():
                print(pre_proc.stderr.strip(), file=sys.stderr)
            return pre_proc.returncode

    _, slot_id = infer_batch_and_slot(film_dir)
    owner = args.owner or f"render:{slot_id}"
    of_bin = _openfilm_bin()

    with acquire_lease("render", owner=owner, timeout_sec=args.timeout, cmd_desc=f"openfilm render -> {out_abs.name}") as lease:
        if args.workers == "auto":
            avail = lease.get("available_ram_mb")
            if lease["other_busy_slots"] == 0 and (avail is None or avail >= 7500.0):
                workers = 4
            elif avail is not None and avail < 4200.0:
                workers = 2
            else:
                workers = 3
        else:
            workers = max(1, min(6, int(args.workers)))

        render_cmd = [
            of_bin,
            "render",
            "--fps",
            str(args.fps),
            f"--loudness={args.loudness}",
            "--workers",
            str(workers),
            "--out",
            str(out_abs),
        ]
        if args.extra_args:
            render_cmd.extend(args.extra_args)

        print(
            f"[svp-render] 已获取渲染槽位 #{lease['slot']} (并发它槽={lease['other_busy_slots']}, "
            f"可用内存={lease['available_ram_mb']}MB, workers={workers}) -> {rel_to_root(out_abs)}",
            file=sys.stderr,
        )
        proc = subprocess.run(render_cmd, cwd=str(film_dir), env=env)
        return proc.returncode


def cmd_look(args: argparse.Namespace) -> int:
    film_dir = Path(args.film_dir).resolve()
    _, slot_id = infer_batch_and_slot(film_dir)
    owner = args.owner or f"look:{slot_id}"
    of_bin = _openfilm_bin()
    env = _build_workspace_env()
    look_args = [a for a in (args.look_args or []) if a != "--"]
    cmd = [of_bin, "look", *look_args]
    with acquire_lease("preview", owner=owner, timeout_sec=args.timeout, cmd_desc=" ".join(cmd[:6])):
        proc = subprocess.run(cmd, cwd=str(film_dir), env=env)
        return proc.returncode


def cmd_exec(args: argparse.Namespace) -> int:
    exec_args = [a for a in (args.exec_args or []) if a != "--"]
    if not exec_args:
        print("错误：exec 子命令必须在 `--` 后提供待执行命令", file=sys.stderr)
        return 2
    cwd = str(Path(args.cwd).resolve()) if args.cwd else None
    env = _build_workspace_env()
    with acquire_lease(args.pool, owner=args.owner or f"exec:{exec_args[0]}", timeout_sec=args.timeout, cmd_desc=" ".join(exec_args[:5])):
        proc = subprocess.run(exec_args, cwd=cwd, env=env)
        return proc.returncode


def cmd_claim_asset(args: argparse.Namespace) -> int:
    media_p = Path(args.file) if args.file else None
    batch_id, slot_id = infer_batch_and_slot(media_p, explicit_batch=args.batch_id, explicit_slot=args.slot)
    res = claim_asset_entry(
        batch_id=batch_id,
        slot_id=slot_id,
        shot_id=args.shot,
        asset_id=args.asset_id,
        url=args.url,
        title=args.title,
        media_file=media_p,
        sample_t=args.sample_t,
        max_hamming=args.max_hamming,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("claimed") else 3


def cmd_clear_claims(args: argparse.Namespace) -> int:
    with _claims_mutex():
        batches = _load_claims_unlocked()
        if args.batch_id:
            removed = len(batches.pop(args.batch_id, []))
        else:
            removed = sum(len(v) for v in batches.values())
            batches.clear()
        _save_claims_unlocked(batches)
    print(json.dumps({"cleared": removed, "batch_id": args.batch_id or "*"}, ensure_ascii=False))
    return 0


def main() -> int:
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    p = argparse.ArgumentParser(description="短视频工作区本机并发信号量、僵尸锁自愈与素材防撞账本")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_st = sub.add_parser("status", help="查看重渲染池/预览池锁状态、剩余物理内存与素材认领概况")
    p_st.set_defaults(func=cmd_status)

    p_ren = sub.add_parser("render", help="先跑 3s preflight-film 预检，再申领双路 GPU 渲染锁执行 openfilm render")
    p_ren.add_argument("--film-dir", default=".", help="OpenFilm 项目 film/ 目录")
    p_ren.add_argument("--out", required=True, help="输出 MP4 路径（相对 film-dir 或工作区）")
    p_ren.add_argument("--fps", type=int, default=30)
    p_ren.add_argument("--loudness", default="-15", help="默认 -15 LUFS 留足 -3dBTP 余量，防单遍 loudnorm 贴墙限幅")
    p_ren.add_argument("--workers", default="auto", help="auto(默认双跑=3/独占=4) 或显式整数 1..6")
    p_ren.add_argument("--style", default="auto", help="传给 preflight-film 的槽位风格")
    p_ren.add_argument("--skip-preflight", action="store_true", help="跳过前置 preflight-film 静态预检")
    p_ren.add_argument("--owner", default="")
    p_ren.add_argument("--timeout", type=float, default=1800.0)
    p_ren.add_argument("extra_args", nargs=argparse.REMAINDER, help="附加透传给 openfilm render 的参数")
    p_ren.set_defaults(func=cmd_render)

    p_look = sub.add_parser("look", help="在轻量预览池(<=2 槽)配额内执行 openfilm look 抽帧")
    p_look.add_argument("--film-dir", default=".", help="OpenFilm 项目 film/ 目录")
    p_look.add_argument("--owner", default="")
    p_look.add_argument("--timeout", type=float, default=300.0)
    p_look.add_argument("look_args", nargs=argparse.REMAINDER, help="`--` 后接 openfilm look 参数")
    p_look.set_defaults(func=cmd_look)

    p_ex = sub.add_parser("exec", help="在指定浏览器池(render/preview)配额内执行任意命令（如 Playwright 截封面）")
    p_ex.add_argument("--pool", choices=["render", "preview"], default="preview")
    p_ex.add_argument("--cwd", default="")
    p_ex.add_argument("--owner", default="")
    p_ex.add_argument("--timeout", type=float, default=600.0)
    p_ex.add_argument("exec_args", nargs=argparse.REMAINDER, help="`--` 后接完整命令与参数")
    p_ex.set_defaults(func=cmd_exec)

    p_cl = sub.add_parser("claim-asset", help="原子校验并认领素材 ID / URL / 64-bit dHash，撞车返回退出码 3")
    p_cl.add_argument("--batch-id", default="")
    p_cl.add_argument("--slot", default="")
    p_cl.add_argument("--shot", default="")
    p_cl.add_argument("--asset-id", default="")
    p_cl.add_argument("--url", default="")
    p_cl.add_argument("--title", default="")
    p_cl.add_argument("--file", default="")
    p_cl.add_argument("--sample-t", type=float, default=None)
    p_cl.add_argument("--max-hamming", type=int, default=10)
    p_cl.set_defaults(func=cmd_claim_asset)

    p_clr = sub.add_parser("clear-claims", help="清空指定批次或全部素材认领记录")
    p_clr.add_argument("--batch-id", default="")
    p_clr.set_defaults(func=cmd_clear_claims)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
