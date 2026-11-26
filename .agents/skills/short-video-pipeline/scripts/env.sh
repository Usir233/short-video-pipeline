# 把配套仓库的设置、缓存、模型、浏览器内核都指到工作区里。
#
# 用法（bash、zsh、sh 都可以，在工作区内任意目录）：
#   . <到工作区根目录的相对路径>/.agents/skills/short-video-pipeline/scripts/env.sh
#
# 安装、更新、运行配套仓库的任何命令之前都要先 source 它。
# 每个新开的 shell 都要重新 source 一次。
# Windows 下用 Git Bash 执行，或按同样的变量名自行设置。

# 从当前目录往上找工作区根目录，不写死绝对路径。
_svp_dir="$PWD"
while [ "$_svp_dir" != "/" ] && [ ! -f "$_svp_dir/.agents/skills/short-video-pipeline/SKILL.md" ]; do
  _svp_dir="$(dirname "$_svp_dir")"
done

if [ ! -f "$_svp_dir/.agents/skills/short-video-pipeline/SKILL.md" ]; then
  echo "env.sh：当前目录不在短视频工作区里，没有设置任何变量" >&2
  unset _svp_dir
  return 1 2>/dev/null || exit 1
fi

export SVP_ROOT="$_svp_dir"
unset _svp_dir

# OpenFilm：设置、服务连接、日志、库缓存
export OPENFILM_HOME="$SVP_ROOT/.local/openfilm"
# OpenFilm：没指定位置时的项目目录、导出目录、「保存」的片段、用户自己的 skill
# （不设的话会落到 ~/Movies/OpenFilm 和桌面）
export OPENFILM_LIBRARY="$SVP_ROOT/runs"
export OPENFILM_EXPORTS="$SVP_ROOT/runs"
export OPENFILM_SAVED="$SVP_ROOT/.local/openfilm-user/saved"
export OPENFILM_SKILLS="$SVP_ROOT/.local/openfilm-user/skills"

# rea-video：模型、它自己的记忆文件
export REA_VIDEO_MODELS="$SVP_ROOT/.local/rea-video/models"
export REA_VIDEO_HOME="$SVP_ROOT/.local/rea-video/home"

# 浏览器内核：OpenFilm 渲染和 CreatorHub 共用这一个目录
export PLAYWRIGHT_BROWSERS_PATH="$SVP_ROOT/browsers/ms-playwright"

# 包管理器的下载缓存
export npm_config_cache="$SVP_ROOT/.local/npm-cache"
export PIP_CACHE_DIR="$SVP_ROOT/.local/pip-cache"

# Python 自动 GPU 推理钩子（自动预加载虚拟环境内 CUDA/cuDNN 并将 ONNX Runtime 提升至 CUDA/DirectML，不改动配套仓库源码）
_svp_py_gpu="$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/py_gpu_site"
case ":${PYTHONPATH:-}:" in
  *":$_svp_py_gpu:"*) ;;
  *) export PYTHONPATH="$_svp_py_gpu${PYTHONPATH:+:$PYTHONPATH}" ;;
esac
unset _svp_py_gpu

# 仅在当前 shell 会话中把工作区的 node_modules/.bin 放到 PATH 最前，
# 避免直接执行 openfilm 时误命中工作区外的全局版本（不改动任何 shell 配置文件）。
case ":$PATH:" in
  *":$SVP_ROOT/node_modules/.bin:"*) ;;
  *) export PATH="$SVP_ROOT/node_modules/.bin:$PATH" ;;
esac

mkdir -p "$OPENFILM_HOME" "$OPENFILM_SAVED" "$OPENFILM_SKILLS" \
  "$REA_VIDEO_MODELS" "$REA_VIDEO_HOME" \
  "$PLAYWRIGHT_BROWSERS_PATH" "$npm_config_cache" "$PIP_CACHE_DIR" "$SVP_ROOT/runs"
