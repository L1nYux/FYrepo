# 知域 0.4.0 服务器升级

先升级服务器，再安装 Windows 客户端。不会改变已配置的 SMTP 地址、密码、业务附件和 API Key。

## 1. 上传源码包

用服务器控制台的文件上传，把交付包里的 **Zhiyu-0.4.0-source.zip** 上传到服务器 **/root/**。这是 Linux 服务器源码包；Windows 的 exe 留在自己的电脑安装。

## 2. 执行升级

先执行 `sudo -i`，然后整段复制以下内容。只执行一次，出现“已有升级正在运行”就等待原任务完成。

```bash
(
  set -euo pipefail
  test "$(id -u)" = 0 || { echo '请先执行 sudo -i'; exit 1; }
  test -f /root/Zhiyu-0.4.0-source.zip || {
    echo '还没有上传源码包：请放到 /root/Zhiyu-0.4.0-source.zip'
    exit 1
  }
  python3 - <<'PY'
from pathlib import Path
from zipfile import ZipFile
archive = Path('/root/Zhiyu-0.4.0-source.zip')
destination = Path('/root/zhiyu-0.4.0')
destination.mkdir(parents=True, exist_ok=True)
with ZipFile(archive) as source:
    for item in source.infolist():
        target = (destination / item.filename).resolve()
        if not target.is_relative_to(destination.resolve()):
            raise SystemExit('源码包路径异常，已停止。')
    source.extractall(destination)
print('源码已解压：', destination)
PY
  bash /root/zhiyu-0.4.0/zhiyu-0.4.0/deploy/upgrade_preserve_data.sh --apply
)
```

脚本复用已完整安装且版本匹配的 Chromium；先对数据库副本执行迁移，再停服务、备份、升级并重新启动。结束时应看到“升级完成”和新的运行目录；出错会停止并尝试恢复旧服务。

## 3. 确认运行版本

```bash
systemctl show research-workbench -p ActiveState -p WorkingDirectory
APP_DIR=$(systemctl show research-workbench -p WorkingDirectory --value)
python3 -c 'import json,sys; print("服务端版本：", json.load(open(sys.argv[1]))["version"])' "$APP_DIR/desktop/release-info.json"
```

应显示 `ActiveState=active` 和 `服务端版本：0.4.0`。然后在自己的电脑双击 **ResearchWorkbench-0.4.0-win-x64.exe**，覆盖安装并重新打开；“关于与更新”中客户端和服务端都应为 0.4.0。

## 数据与回滚

新增迁移会把个人 AI 历史迁回个人空间，保留原扣费来源；旧的已通过申请按容量和资格完成或退回审核。**不能只把旧程序切回来或直接反向迁移。**需要使用脚本结束时给出的 `/var/backups/research-workbench/upgrade-时间戳`，恢复升级前数据库及相配套的旧服务配置。上线后产生的新数据需先单独备份，再决定如何回退。

这份交付尚未公开发布到自动更新渠道。“检查更新”继续依据公开渠道；手动安装包和运行版本核对以上述结果为准。
