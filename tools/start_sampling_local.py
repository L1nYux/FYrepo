"""Start the real FYrepo and PDF worker locally, without GitHub or demo data."""

import argparse
import hashlib
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
import webbrowser
from datetime import datetime


ROOT = Path(__file__).resolve().parent.parent
HOST, PORT = "127.0.0.1", 8000
URL = f"http://{HOST}:{PORT}/sampling/"


def port_available():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((HOST, PORT))
        except OSError:
            return False
    return True


def virtualenv_python():
    directory = ROOT / ".venv"
    python = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        print("正在创建项目自己的 Python 环境……", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(directory)], check=True)
    subprocess.run(
        [str(python), "-c", "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ required'"],
        check=True,
    )
    return python


def install_dependencies(python):
    requirements = ROOT / "requirements.txt"
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = ROOT / ".venv" / "local_test_requirements.sha256"
    probe = subprocess.run(
        [str(python), "-c", "import django, whitenoise, openpyxl, pdfplumber, pandas"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if not marker.is_file() or marker.read_text().strip() != digest or probe.returncode:
        print("正在安装工作台依赖，首次启动需要联网，请等待……", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(requirements)], check=True)
        marker.write_text(digest, encoding="ascii")


def local_environment(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    key_path = data_dir / "local-test.key"
    if not key_path.is_file():
        key_path.write_text(secrets.token_urlsafe(48), encoding="ascii")
        if os.name != "nt":
            key_path.chmod(0o600)
    secret_key = key_path.read_text(encoding="utf-8-sig").strip()
    if not secret_key:
        raise RuntimeError(f"本地密钥文件为空：{key_path}")
    environment = os.environ.copy()
    environment.update({
        "WORKBENCH_SECRET_KEY": secret_key,
        "WORKBENCH_DATA_DIR": str(data_dir),
        "WORKBENCH_DEBUG": "1",
        "WORKBENCH_HTTPS": "0",
        "WORKBENCH_ALLOWED_HOSTS": "127.0.0.1,localhost",
        "WORKBENCH_CSRF_ORIGINS": "http://127.0.0.1:8000,http://localhost:8000",
        "SAMPLING_AGENT_ORIGIN": "http://127.0.0.1:8765",
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    })
    # A production proxy setting must not affect direct loopback HTTP.
    environment.pop("WORKBENCH_TRUST_PROXY", None)
    return environment


def backup_existing_database(data_dir):
    database = data_dir / "workbench.sqlite3"
    if not database.is_file():
        return
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_dir / f"workbench-before-local-test-{stamp}.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(backup_path) as target:
            source.backup(target)
    print(f"已有数据库已备份：{backup_path}", flush=True)


def manage(python, environment, *args):
    subprocess.run(
        [str(python), str(ROOT / "manage.py"), *args],
        cwd=ROOT, env=environment, check=True,
    )


def has_administrator(python, environment):
    probe = subprocess.run(
        [str(python), "-c", "import django; django.setup(); "
         "from django.contrib.auth import get_user_model; "
         "print(get_user_model().objects.filter(is_superuser=True, is_active=True).exists())"],
        cwd=ROOT, env=environment, capture_output=True, text=True, check=True,
    )
    return probe.stdout.strip() == "True"


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def serve(python, environment, open_browser):
    processes = []
    try:
        worker = subprocess.Popen(
            [str(python), str(ROOT / "manage.py"), "sampling_worker"], cwd=ROOT, env=environment,
        )
        processes.append(worker)
        server = subprocess.Popen(
            [str(python), str(ROOT / "manage.py"), "runserver", f"{HOST}:{PORT}", "--noreload"],
            cwd=ROOT, env=environment,
        )
        processes.append(server)
        deadline = time.monotonic() + 30
        while True:
            if server.poll() is not None:
                raise RuntimeError("网页进程已退出，请查看上方的错误输出。")
            if worker.poll() is not None:
                raise RuntimeError("PDF 转换 worker 已退出，请查看上方的错误输出。")
            try:
                with socket.create_connection((HOST, PORT), timeout=0.25):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("网页在 30 秒内未能启动，请查看上方输出。")
                time.sleep(0.2)
        print(f"\n本地正式版已启动：{URL}", flush=True)
        print("网页与 PDF 转换 worker 同时运行。请保持此窗口打开，停止时按 Ctrl+C。", flush=True)
        print("登录后从左侧进入样本库。首次空库不会生成示例项目或候选论文。\n", flush=True)
        if open_browser:
            try:
                webbrowser.open(URL)
            except Exception:
                print(f"请手动在浏览器打开：{URL}", flush=True)
        while server.poll() is None:
            if worker.poll() is not None:
                raise RuntimeError("PDF 转换 worker 已退出，请查看上方的错误输出。")
            time.sleep(0.5)
        if server.returncode:
            raise RuntimeError(f"网页进程已退出，退出码 {server.returncode}。")
    except KeyboardInterrupt:
        print("\n正在停止本地网页与 PDF worker……", flush=True)
    finally:
        for process in reversed(processes):
            stop_process(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check-only", action="store_true", help="迁移并检查后退出")
    parser.add_argument("--non-interactive", action="store_true", help="不交互创建管理员，用于启动检查")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise RuntimeError("请使用 Python 3.11 或更新版本。")
    if not (ROOT / "manage.py").is_file():
        raise RuntimeError("请先解压完整源码包；启动文件必须与 manage.py 位于同一项目中。")
    if not args.check_only and not port_available():
        raise RuntimeError("本机 8000 端口已被占用。请先在旧网页的运行窗口按 Ctrl+C，再重新启动。")
    data_dir = args.data_dir.expanduser().resolve()
    print(f"FYrepo Sampling 本地正式版\n项目目录：{ROOT}\n数据目录：{data_dir}\n", flush=True)
    python = virtualenv_python()
    install_dependencies(python)
    environment = local_environment(data_dir)
    backup_existing_database(data_dir)
    manage(python, environment, "migrate", "--noinput")
    manage(python, environment, "check")
    if args.check_only:
        print("本地启动配置与数据库检查通过。", flush=True)
        return
    if not has_administrator(python, environment):
        if args.non_interactive:
            print("当前为空库；请交互启动并创建自己的管理员后登录。", flush=True)
        else:
            print("首次启动请创建你自己的管理员账号。输入密码时不显示字符是正常的。", flush=True)
            manage(python, environment, "createsuperuser")
    serve(python, environment, not args.no_browser)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消本地启动。", flush=True)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"\n启动未完成：{exc}\n请保留窗口中的具体错误信息。", file=sys.stderr, flush=True)
        sys.exit(1)
