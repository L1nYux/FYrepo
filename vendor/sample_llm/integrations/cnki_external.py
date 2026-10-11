from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import hashlib
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from .component_integrity import ComponentIntegrityError, validate_bundled_component

PACKAGE_NAME = "cnki-metadata-exporter"
PACKAGE_VERSION = "0.2.0"
PINNED_COMMIT = "4bdf8e108c81c4d1a0590377aec1238f534e1a18"
SOURCE_URL = "https://github.com/JYao-Chen/cnki-metadata-exporter"
ROOT = Path(__file__).resolve().parents[1]
SOURCE_ARCHIVE = ROOT / "third_party" / "cnki-metadata-exporter-0.2.0-4bdf8e1.zip"
SOURCE_WHEEL = ROOT / "third_party" / "cnki_metadata_exporter-0.2.0-py3-none-any.whl"
RUNNER = ROOT / "integrations" / "collector_runner.py"
LOGIN_RUNNER = ROOT / "integrations" / "login_runner.py"
MASTER_PROFILE = ROOT / "runtime_outputs" / "cnki_master_profile"
LOGIN_STOP_FLAG = ROOT / "runtime_outputs" / ".stop_cnki_login"

_LOCK = threading.RLock()
_ACTIVE_PROCESSES: list[subprocess.Popen] = []
_LOGIN_PROCESS: subprocess.Popen | None = None
_STOP_REQUESTED = threading.Event()


class CollectionStopped(RuntimeError):
    pass


def _no_proxy_env() -> dict:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    no_proxy = env.get("NO_PROXY", env.get("no_proxy", ""))
    parts = [x.strip() for x in no_proxy.split(",") if x.strip()]
    for host in ("localhost", "127.0.0.1"):
        if host not in parts:
            parts.append(host)
    env["NO_PROXY"] = env["no_proxy"] = ",".join(parts)
    return env


def _system_browser() -> tuple[str, str]:
    if os.name == "nt":
        roots = [
            os.environ.get("PROGRAMFILES(X86)", ""),
            os.environ.get("PROGRAMFILES", ""),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        for channel, rel in (
            ("msedge", ("Microsoft", "Edge", "Application", "msedge.exe")),
            ("chrome", ("Google", "Chrome", "Application", "chrome.exe")),
        ):
            for root in roots:
                if not root:
                    continue
                p = Path(root).joinpath(*rel)
                if p.exists():
                    return channel, str(p)
    return "", ""


def _playwright_browser_ready() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


def login_profile_ready() -> bool:
    if not MASTER_PROFILE.exists():
        return False
    markers = list(MASTER_PROFILE.rglob("Cookies")) + list(MASTER_PROFILE.rglob("Login Data"))
    return any(p.is_file() and p.stat().st_size > 0 for p in markers) or any(MASTER_PROFILE.iterdir())


def login_running() -> bool:
    global _LOGIN_PROCESS
    return _LOGIN_PROCESS is not None and _LOGIN_PROCESS.poll() is None


def package_status() -> dict:
    importlib.invalidate_caches()
    spec = importlib.util.find_spec("cnki_metadata_exporter")
    integrity_error = ""
    installed_error = ""
    verified = None
    try:
        verified = validate_bundled_component(ROOT)
    except ComponentIntegrityError as exc:
        integrity_error = str(exc)
    installed = False
    version = ""
    location = ""
    if spec is not None:
        try:
            version = importlib.metadata.version(PACKAGE_NAME)
            package_dir = Path(spec.origin).resolve().parent
            location = str(package_dir / "__init__.py")
            installed = bool(verified and version == PACKAGE_VERSION and all(
                hashlib.sha256((package_dir / name).read_bytes()).hexdigest() == digest
                for name, digest in verified["module_sha256"].items()
            ))
            if not installed:
                installed_error = "已安装组件的版本或源码不匹配，请安装 / 修复采集组件。"
        except (OSError, TypeError, importlib.metadata.PackageNotFoundError) as exc:
            installed_error = f"已安装组件无法核验：{exc}"
    channel, browser_path = _system_browser()
    pw_browser = _playwright_browser_ready() if importlib.util.find_spec("playwright") else False
    return {
        "archive_present": SOURCE_ARCHIVE.exists(),
        "wheel_present": SOURCE_WHEEL.exists(),
        "integrity_ok": verified is not None,
        "integrity_error": integrity_error,
        "installed": installed,
        "installed_error": installed_error,
        "component_commit": PINNED_COMMIT,
        "version": version,
        "location": location,
        "browser_ready": bool(channel or pw_browser),
        "browser_channel": channel or ("playwright-chromium" if pw_browser else ""),
        "browser_path": browser_path,
        "running": is_running(),
        "login_running": login_running(),
        "login_profile_ready": login_profile_ready(),
        "master_profile": str(MASTER_PROFILE),
    }


def _popen(cmd, cwd=None) -> subprocess.Popen:
    kwargs = dict(
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=_no_proxy_env(),
    )
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def _terminate_tree(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def is_running() -> bool:
    with _LOCK:
        return any(p.poll() is None for p in _ACTIVE_PROCESSES)


def request_stop() -> str:
    _STOP_REQUESTED.set()
    with _LOCK:
        procs = list(_ACTIVE_PROCESSES)
    alive = [p for p in procs if p.poll() is None]
    for proc in alive:
        _terminate_tree(proc)
    if alive:
        return f"已发送结束指令：正在关闭 {len(alive)} 个采集进程及其浏览器。已完成批次会保留。"
    return "当前没有正在运行的 CNKI 采集任务。"


def _stream(cmd, cwd=None):
    proc = _popen(cmd, cwd=cwd)
    with _LOCK:
        _ACTIVE_PROCESSES.append(proc)
    lines: list[str] = []
    try:
        assert proc.stdout is not None
        while True:
            line = proc.stdout.readline()
            if line:
                line = line.rstrip()
                if line:
                    lines.append(line)
                    yield line, list(lines)
            if proc.poll() is not None:
                break
            if _STOP_REQUESTED.is_set():
                _terminate_tree(proc)
                raise CollectionStopped("用户结束了 CNKI 采集")
        code = proc.wait()
        if _STOP_REQUESTED.is_set():
            raise CollectionStopped("用户结束了 CNKI 采集")
        if code != 0:
            tail = "\n".join(lines[-40:])
            raise RuntimeError(
                f"命令失败({code}): {' '.join(map(str, cmd))}" + (f"\n\n最后日志：\n{tail}" if tail else "")
            )
    finally:
        with _LOCK:
            if proc in _ACTIVE_PROCESSES:
                _ACTIVE_PROCESSES.remove(proc)


def install_package(*, install_browser=True):
    verified = validate_bundled_component(ROOT)
    log: list[str] = []
    yield {"message": f"采集安装包已通过 SHA256、ZIP/CRC、wheel RECORD 与源码一致性校验（{verified['checked_files']} 个文件）。", "log": ""}
    cmd = [
        sys.executable,
        "-m", "pip", "install",
        "--upgrade", "--force-reinstall", "--no-deps", "--no-index", "--disable-pip-version-check",
        str(SOURCE_WHEEL),
    ]
    yield {"message": "正在安装固定 GitHub 源码版本的 CNKI Metadata Exporter…", "log": ""}
    for line, lines in _stream(cmd):
        log.append(line)
        yield {"message": line or "安装中…", "log": "\n".join(log[-120:])}
    importlib.invalidate_caches()
    st = package_status()
    if not st["installed"]:
        raise RuntimeError(st["integrity_error"] or st["installed_error"] or "安装完成，但没有检测到 cnki-metadata-exporter 0.2.0。")
    # Real subprocess imports catch missing modules/dependencies before login or collection.
    for probe in ([sys.executable, str(RUNNER), "--help"],
                  [sys.executable, "-m", "cnki_metadata_exporter.merge_metadata", "--help"]):
        for line, _ in _stream(probe):
            log.append(line)
    yield {"message": "采集与合并入口已通过实际启动检查。", "log": "\n".join(log[-120:])}
    if install_browser and not st["browser_ready"]:
        bcmd = [sys.executable, "-m", "playwright", "install", "chromium"]
        yield {"message": "未检测到 Edge/Chrome，尝试安装 Playwright Chromium…", "log": "\n".join(log[-120:])}
        try:
            for line, lines in _stream(bcmd):
                log.append(line)
                yield {"message": line or "浏览器安装中…", "log": "\n".join(log[-120:])}
        except Exception as exc:
            log.append(str(exc))
            yield {"message": "CNKI 包已安装，但浏览器自动安装失败。", "log": "\n".join(log[-120:])}
    st = package_status()
    yield {
        "message": f"CNKI Metadata Exporter 已安装：{st['version']} · 浏览器：{st.get('browser_channel') or '待配置'}",
        "log": "\n".join(log[-120:]),
    }


def start_login() -> str:
    global _LOGIN_PROCESS
    st = package_status()
    if not st["installed"]:
        raise RuntimeError(st["integrity_error"] or st["installed_error"] or "请先安装 / 修复 CNKI 采集组件，再打开登录窗口。")
    if not st["browser_ready"]:
        raise RuntimeError("未检测到可用浏览器，请安装 / 修复采集组件或安装系统 Edge/Chrome。")
    if login_running():
        return "CNKI 登录窗口已经打开。请在该窗口中完成登录，然后点击“登录完成”。"
    if is_running():
        raise RuntimeError("正在采集时不能打开登录窗口，请先停止采集。")
    MASTER_PROFILE.parent.mkdir(parents=True, exist_ok=True)
    LOGIN_STOP_FLAG.unlink(missing_ok=True)
    cmd = [sys.executable, str(LOGIN_RUNNER), "--profile", str(MASTER_PROFILE), "--stop-flag", str(LOGIN_STOP_FLAG)]
    _LOGIN_PROCESS = _popen(cmd, cwd=ROOT)
    return "已打开 CNKI 登录窗口。请完成机构/个人登录与必要验证；完成后回到这里点击“登录完成”。"


def finish_login() -> str:
    global _LOGIN_PROCESS
    if not login_running():
        if login_profile_ready():
            return "当前没有打开的登录窗口，但已检测到已保存的登录资料。"
        return "当前没有打开的登录窗口。"
    LOGIN_STOP_FLAG.parent.mkdir(parents=True, exist_ok=True)
    LOGIN_STOP_FLAG.write_text("stop", encoding="utf-8")
    try:
        _LOGIN_PROCESS.wait(timeout=15)
    except Exception:
        _terminate_tree(_LOGIN_PROCESS)
    _LOGIN_PROCESS = None
    if login_profile_ready():
        return "登录窗口已关闭，登录资料已保存。现在可以开始信息采集。"
    return "登录窗口已关闭，但没有检测到浏览器资料；如果采集时仍要求登录，请重新打开登录窗口。"


def _escape(s: str) -> str:
    return str(s).replace("'", "''")


def build_queries(frame, year_chunk_size: int = 2):
    """Build disjoint journal×year-chunk collection tasks for parallel export.

    The search expression uses current KNS8 LY=文献来源. Years are applied through the
    publication-date controls by collector_runner. Splitting by year chunks keeps each task
    smaller and makes even one journal/one period parallelizable.
    """
    if frame is None or len(frame) == 0:
        return []
    chunk = max(1, int(year_chunk_size or 1))
    source = frame.sort_values("frame_order") if "frame_order" in frame.columns else frame
    groups: dict[tuple[str, str], list[dict]] = {}
    for rec in source.to_dict("records"):
        key = (str(rec["journal_family_name"]), str(rec["journal_query_names"]))
        groups.setdefault(key, []).append(rec)
    queries = []
    for (family, query_names), rows in groups.items():
        names = [x.strip() for x in str(query_names).split("|") if x.strip()]
        jexpr = " OR ".join([f"LY='{_escape(x)}'" for x in names])
        if len(names) > 1:
            jexpr = f"({jexpr})"
        lo = min(int(r["start_year"]) for r in rows)
        hi = max(int(r["end_year"]) for r in rows)
        y = lo
        while y <= hi:
            y2 = min(hi, y + chunk - 1)
            queries.append({
                "id": f"Q{len(queries)+1:04d}",
                "name": f"{family}｜{y}-{y2}",
                "field": "LY",
                "query": jexpr,
                "purpose": "sampling_candidate_pool",
                "tier": "",
                "journal_family_name": family,
                "start_year": y,
                "end_year": y2,
            })
            y = y2 + 1
    return queries


def prepare_workspace(frame, workspace: Path, year_chunk_size: int = 2):
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    queries = build_queries(frame, year_chunk_size=year_chunk_size)
    qpath = workspace / "queries.json"
    qpath.write_text(json.dumps(queries, ensure_ascii=False, indent=2), encoding="utf-8")
    return qpath, queries


def _clone_login_profile(destination: Path) -> None:
    if not login_profile_ready():
        raise RuntimeError("尚未保存 CNKI 登录资料。请先点击“打开 CNKI 登录”，完成登录后点击“登录完成”。")
    from .browser_profile import clone_browser_profile
    clone_browser_profile(MASTER_PROFILE, destination)


def _reader_thread(worker_name: str, proc: subprocess.Popen, outq: queue.Queue):
    try:
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            outq.put((worker_name, "line", line.rstrip()))
        code = proc.wait()
        outq.put((worker_name, "done", code))
    except Exception as exc:
        outq.put((worker_name, "error", str(exc)))


def _consolidate_worker_outputs(workspace: Path, worker_roots: list[Path]):
    target_native = workspace / "output" / "native_exports"
    target_native.mkdir(parents=True, exist_ok=True)
    target_logs = workspace / "logs" / "parallel_workers"
    target_logs.mkdir(parents=True, exist_ok=True)
    for wr in worker_roots:
        native = wr / "output" / "native_exports"
        if native.exists():
            for collection_dir in native.iterdir():
                if collection_dir.is_dir():
                    shutil.copytree(collection_dir, target_native / collection_dir.name, dirs_exist_ok=True)
        logs = wr / "logs"
        if logs.exists():
            shutil.copytree(logs, target_logs / wr.name, dirs_exist_ok=True)


def collect(frame, workspace: Path, batch_size=500, concurrency=2, year_chunk_size=2):
    st = package_status()
    if not st["installed"]:
        raise RuntimeError(st["integrity_error"] or st["installed_error"] or "cnki-metadata-exporter 尚未安装。请先点击“安装 / 修复 CNKI 采集包”。")
    if not st["browser_ready"]:
        raise RuntimeError("未检测到可用浏览器，请先安装 / 修复 CNKI 采集组件。")
    if login_running():
        raise RuntimeError("CNKI 登录窗口仍然打开。请先点击“登录完成”，再开始信息采集。")
    if not login_profile_ready():
        raise RuntimeError("尚未保存 CNKI 登录资料。请先完成“打开 CNKI 登录 → 登录完成”。")

    workspace = Path(workspace)
    qpath, queries = prepare_workspace(frame, workspace, year_chunk_size=year_chunk_size)
    if not queries:
        raise RuntimeError("没有可执行的 CNKI 检索任务。")
    _STOP_REQUESTED.clear()

    worker_count = max(1, min(int(concurrency or 1), 3, len(queries)))
    shards = [[] for _ in range(worker_count)]
    for idx, q in enumerate(queries):
        shards[idx % worker_count].append(q["id"])

    workers_root = workspace / "workers"
    workers_root.mkdir(parents=True, exist_ok=True)
    worker_roots: list[Path] = []
    procs: list[tuple[str, subprocess.Popen]] = []
    outq: queue.Queue = queue.Queue()
    histories: dict[str, list[str]] = {}

    yield {
        "stage": 1, "total": 2,
        "message": f"准备并发采集：{len(queries)} 个期刊×年份分片，{worker_count} 个并发窗口…",
        "log": "", "workspace": str(workspace), "unique_json": "", "stopped": False,
    }

    master_native = workspace / "output" / "native_exports"
    for i, collection_ids in enumerate(shards, start=1):
        wr = workers_root / f"worker_{i:02d}"
        wr.mkdir(parents=True, exist_ok=True)
        profile = wr / ".cnki-profile"
        _clone_login_profile(profile)
        if master_native.exists():
            for cid in collection_ids:
                src = master_native / cid
                if src.exists():
                    shutil.copytree(src, wr / "output" / "native_exports" / cid, dirs_exist_ok=True)
        cmd = [sys.executable, str(RUNNER), "--queries", str(qpath), "--root", str(wr), "--batch-size", str(batch_size)]
        for cid in collection_ids:
            cmd.extend(["--collection", cid])
        proc = _popen(cmd, cwd=wr)
        name = f"W{i}"
        histories[name] = []
        procs.append((name, proc))
        worker_roots.append(wr)
        with _LOCK:
            _ACTIVE_PROCESSES.append(proc)
        threading.Thread(target=_reader_thread, args=(name, proc, outq), daemon=True).start()

    done: dict[str, int] = {}
    try:
        while len(done) < len(procs):
            if _STOP_REQUESTED.is_set():
                for _, p in procs:
                    _terminate_tree(p)
                raise CollectionStopped("用户结束了 CNKI 采集")
            try:
                name, kind, payload = outq.get(timeout=0.5)
            except queue.Empty:
                continue
            if kind == "line":
                histories[name].append(payload)
                merged_lines = []
                for w in sorted(histories):
                    if histories[w]:
                        merged_lines.append(f"[{w}] {histories[w][-1]}")
                yield {
                    "stage": 1, "total": 2,
                    "message": f"并发采集中：{name} · {payload}",
                    "log": "\n".join(merged_lines[-120:]),
                    "workspace": str(workspace), "unique_json": "", "stopped": False,
                }
            elif kind == "done":
                done[name] = int(payload)
                yield {
                    "stage": 1, "total": 2,
                    "message": f"{name} 已结束（code={payload}），等待其余窗口…",
                    "log": "\n".join([f"[{w}] {histories[w][-1] if histories[w] else 'no log'}" for w in sorted(histories)]),
                    "workspace": str(workspace), "unique_json": "", "stopped": False,
                }
            elif kind == "error":
                done[name] = 99
                histories[name].append(str(payload))

        bad = {w: c for w, c in done.items() if c != 0}
        if bad:
            detail = "\n".join(f"{w}: code={c}; tail={histories[w][-1] if histories[w] else ''}" for w, c in bad.items())
            raise RuntimeError("部分并发采集窗口失败：\n" + detail)

        _consolidate_worker_outputs(workspace, worker_roots)
        merge_cmd = [
            sys.executable, "-m", "cnki_metadata_exporter.merge_metadata",
            "--root", str(workspace), "--queries", str(qpath),
            "--out", str(workspace / "merged"), "--include-database", "期刊",
        ]
        log: list[str] = []
        yield {"stage": 2, "total": 2, "message": "并发采集完成，正在合并、核验并去重…", "log": "", "workspace": str(workspace), "unique_json": "", "stopped": False}
        for line, lines in _stream(merge_cmd, cwd=workspace):
            log.append(line)
            yield {"stage": 2, "total": 2, "message": line or "合并中…", "log": "\n".join(log[-120:]), "workspace": str(workspace), "unique_json": "", "stopped": False}
        unique = workspace / "merged" / "unique.json"
        if not unique.exists():
            raise RuntimeError("采集完成但未找到 merged/unique.json")
        yield {"stage": 2, "total": 2, "message": "CNKI 候选库已完成", "log": "\n".join(log[-120:]), "workspace": str(workspace), "unique_json": str(unique), "stopped": False}
    except CollectionStopped:
        yield {"stage": 0, "total": 2, "message": "采集已由用户结束；已完成批次已保留，可再次开始续接。", "log": "", "workspace": str(workspace), "unique_json": "", "stopped": True}
    finally:
        with _LOCK:
            for _, p in procs:
                if p in _ACTIVE_PROCESSES:
                    _ACTIVE_PROCESSES.remove(p)
