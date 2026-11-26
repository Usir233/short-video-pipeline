"""Workspace-local automatic GPU acceleration hook for Python ONNX Runtime workloads.

Loaded automatically via PYTHONPATH (set by scripts/env.sh) or .venv site-packages .pth,
without modifying third-party repository source files (e.g. rea-video/).

Behavior:
1. Zero overhead for scripts that never import `onnxruntime` (uses a post-import meta_path watcher).
2. When `onnxruntime` is imported (by rea-video UVR/BandIt stems, RapidOCR, rembg, etc.):
   - Preloads pip-installed CUDA/cuDNN DLLs inside the active virtualenv (`ort.preload_dlls`).
   - Automatically promotes `InferenceSession` calls that default to or hardcode
     `["CPUExecutionProvider"]` onto `CUDAExecutionProvider` (or `DmlExecutionProvider`),
     with safe fallback to `CPUExecutionProvider` if any model/op is unsupported on GPU.
3. Set `SVP_DISABLE_PYTHON_GPU=1` to force CPU execution.
"""

from __future__ import annotations

import importlib.abc
import os
import sys


def _patch_onnxruntime(ort: object) -> None:
    if getattr(ort, "_svp_gpu_patched", False):
        return
    setattr(ort, "_svp_gpu_patched", True)

    if os.environ.get("SVP_DISABLE_PYTHON_GPU") == "1":
        return

    preload = getattr(ort, "preload_dlls", None)
    if callable(preload):
        try:
            preload(cuda=True, cudnn=True, directory="")
        except Exception:
            try:
                preload()
            except Exception:
                pass

    get_avail = getattr(ort, "get_available_providers", None)
    if not callable(get_avail):
        return
    try:
        available = list(get_avail())
    except Exception:
        return

    gpu_provider: str | None = None
    for cand in ("CUDAExecutionProvider", "DmlExecutionProvider"):
        if cand in available:
            gpu_provider = cand
            break
    if not gpu_provider:
        return

    orig_session = getattr(ort, "InferenceSession", None)
    if orig_session is None:
        return

    class _GpuFirstInferenceSession(orig_session):  # type: ignore[misc, valid-type]
        def __init__(self, path_or_bytes, sess_options=None, providers=None, **kwargs):
            want_upgrade = False
            if providers is None:
                want_upgrade = True
                base_providers = ["CPUExecutionProvider"]
            else:
                prov_list = list(providers)
                base_providers = prov_list
                has_gpu = any(
                    (p[0] if isinstance(p, tuple) else p)
                    in ("CUDAExecutionProvider", "TensorrtExecutionProvider", "DmlExecutionProvider")
                    for p in prov_list
                )
                if not has_gpu:
                    want_upgrade = True

            if want_upgrade:
                upgraded = [gpu_provider] + [
                    p for p in base_providers if (p[0] if isinstance(p, tuple) else p) != gpu_provider
                ]
                try:
                    super().__init__(
                        path_or_bytes,
                        sess_options=sess_options,
                        providers=upgraded,
                        **kwargs,
                    )
                    return
                except Exception:
                    pass

            super().__init__(
                path_or_bytes,
                sess_options=sess_options,
                providers=providers,
                **kwargs,
            )

    setattr(ort, "InferenceSession", _GpuFirstInferenceSession)


class _OnnxRuntimePostImportWatcher(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path=None, target=None):
        if fullname != "onnxruntime":
            return None
        # Remove self while delegating to standard finders, then wrap loader.exec_module
        for finder in sys.meta_path:
            if finder is self:
                continue
            find_spec = getattr(finder, "find_spec", None)
            if not callable(find_spec):
                continue
            spec = find_spec(fullname, path, target)
            if spec is not None and spec.loader is not None:
                orig_exec = spec.loader.exec_module

                def _exec_and_patch(module):
                    orig_exec(module)
                    _patch_onnxruntime(module)

                spec.loader.exec_module = _exec_and_patch  # type: ignore[method-assign]
                try:
                    sys.meta_path.remove(self)
                except ValueError:
                    pass
                return spec
        return None


if os.environ.get("SVP_DISABLE_PYTHON_GPU") != "1":
    if "onnxruntime" in sys.modules:
        _patch_onnxruntime(sys.modules["onnxruntime"])
    elif not any(
        type(f).__name__ == "_OnnxRuntimePostImportWatcher" for f in sys.meta_path
    ):
        sys.meta_path.insert(0, _OnnxRuntimePostImportWatcher())
