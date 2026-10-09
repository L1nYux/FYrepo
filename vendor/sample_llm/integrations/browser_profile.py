"""Copy CNKI browser login state without Edge model downloads or disposable caches."""
from __future__ import annotations

import os
import shutil
from pathlib import Path


_DISPOSABLE_NAMES = {
    "cache", "code cache", "gpucache", "shadercache", "grshadercache",
    "dawncache", "dawnwebgpucache", "dawngraphitecache", "cachestorage",
    "browsermetrics", "crashpad", "crash reports", "devtoolsactiveport", "lock",
}
_DISPOSABLE_PREFIXES = (
    "edgeoptimizationguide", "optimizationguide", "optimization_guide",
    "ondevicemodel", "on_device_model", "singleton",
)


def _ignored_entries(directory, names):
    # Keep Cookies (+ WAL/journals), Local State, Preferences, Local Storage,
    # IndexedDB, Session Storage and other authentication state unchanged.
    # Match names before descending into potentially broken cache junctions.
    return [name for name in names
            if name.casefold() in _DISPOSABLE_NAMES
            or name.casefold().startswith(_DISPOSABLE_PREFIXES)]


def _extended_path(value: str, *, windows: bool | None = None) -> str:
    """Use extended absolute paths for filesystem IO on Windows (also UNC)."""
    if windows is None:
        windows = os.name == "nt"
    if not windows or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def _io_path(path: Path) -> str:
    return _extended_path(str(path))


def _copy_error_detail(exc: Exception) -> str:
    if isinstance(exc, shutil.Error) and exc.args and isinstance(exc.args[0], list):
        errors = exc.args[0]
        if errors and isinstance(errors[0], (tuple, list)) and len(errors[0]) >= 3:
            return str(errors[0][2])[:180]
    return str(exc)[:180]


def clone_browser_profile(source: Path, destination: Path) -> None:
    """Create an independent worker profile; never ignore failures in login state."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if (source == destination or source.is_relative_to(destination)
            or destination.is_relative_to(source)):
        raise RuntimeError("登录资料源目录与工作目录不能相同或相互包含。")
    if not os.path.isdir(_io_path(source)):
        raise RuntimeError("未找到本机知网登录资料，请先打开知网登录并点击“登录完成”。")
    try:
        if os.path.lexists(_io_path(destination)):
            shutil.rmtree(_io_path(destination))
        shutil.copytree(_io_path(source), _io_path(destination),
                        ignore=_ignored_entries, copy_function=shutil.copy2)
    except (OSError, shutil.Error) as exc:
        # A partial profile must never be used as a successful login clone.
        shutil.rmtree(_io_path(destination), ignore_errors=True)
        detail = _copy_error_detail(exc)
        raise RuntimeError(
            f"本机知网登录资料复制失败：{detail}。"
            "请点击“登录完成”关闭登录窗口，并关闭上一次采集浏览器后重试。"
            "若仍提示路径不存在，请将完整项目放到较短目录后重新启动。"
        ) from exc
