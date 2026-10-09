"""Adjust only the existing application proxy, retaining a rollback copy."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
from inference_timeout_hotfix import nginx_patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup', required=True)
    args = parser.parse_args()
    site = Path('/etc/nginx/sites-enabled/research-workbench').resolve()
    if not site.exists():
        print('没有本机知域 Nginx 配置，外层代理等待需由运维检查。')
        return
    if not site.is_file() or Path('/etc/nginx') not in site.parents:
        raise SystemExit('Nginx 配置路径无效。')
    idle = float(os.environ.get('WORKBENCH_INFERENCE_IDLE_SECONDS', '900'))
    if not 0 <= idle <= 86400:
        raise SystemExit('推理等待配置无效。')
    # Nginx has no equivalent of Gunicorn timeout=0. This is an idle read
    # timeout; 0 would expire immediately. Keep it outside the transport guard.
    seconds = int(idle + 60) if idle else 86400
    text = site.read_text()
    updated, count = nginx_patch(text, str(seconds)+'s')
    backup = Path(args.backup)
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(site, backup/'nginx-before.conf')
    (backup/'nginx-path.txt').write_text(str(site))
    try:
        site.write_text(updated)
        subprocess.run(['nginx', '-t'], check=True)
        subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
    except Exception:
        shutil.copy2(backup/'nginx-before.conf', site)
        subprocess.run(['nginx', '-t'], check=False)
        subprocess.run(['systemctl', 'reload', 'nginx'], check=False)
        raise
    print('Nginx 应用代理无数据等待：'+str(seconds)+' 秒（'+str(count)+' 个位置）。')


if __name__ == '__main__':
    main()
