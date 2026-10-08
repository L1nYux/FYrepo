# 知域 0.4.1 服务器升级

先升级服务器，再安装 Windows 客户端。此文是待发布步骤，尚未在正式服务器执行。

## 1. 上传源码包

把 **Zhiyu-0.4.1-source.zip** 上传到服务器 **/root/**。Windows exe 留在电脑安装。

## 2. 执行升级

先执行 `sudo -i`，再整段复制以下内容。源码包上传位置与指令一致，缺少文件会立即提示。

```bash
(
  set -euo pipefail
  test "$(id -u)" = 0 || { echo '请先执行 sudo -i'; exit 1; }
  test -f /root/Zhiyu-0.4.1-source.zip || {
    echo '请先上传源码包到 /root/Zhiyu-0.4.1-source.zip'
    exit 1
  }
  python3 - <<'PY'
from pathlib import Path
from zipfile import ZipFile
archive = Path('/root/Zhiyu-0.4.1-source.zip')
destination = Path('/root/zhiyu-0.4.1')
destination.mkdir(parents=True, exist_ok=True)
with ZipFile(archive) as source:
    for item in source.infolist():
        target = (destination / item.filename).resolve()
        if not target.is_relative_to(destination.resolve()):
            raise SystemExit('源码包路径异常，已停止。')
    source.extractall(destination)
print('源码已解压：', destination)
PY
  bash /root/zhiyu-0.4.1/zhiyu-0.4.1/deploy/upgrade_preserve_data.sh --apply
)
```

脚本先在数据库副本检查迁移，再备份、切换服务和收集静态资源。出错停止并尝试恢复旧服务；不要反复同时运行升级。保留原账户、业务附件、SMTP 与 API Key 配置。

新增迁移将历史样本归唯一在用团队。多团队或历史关联项目归属冲突会停止迁移；不能清库或跳过。冻结状态与研究参数保持原值。

## 3. 核对版本与服务

```bash
systemctl show research-workbench -p ActiveState -p WorkingDirectory
APP_DIR=$(systemctl show research-workbench -p WorkingDirectory --value)
python3 -c 'import json,sys; print("服务端版本：", json.load(open(sys.argv[1]))["version"])' "$APP_DIR/desktop/release-info.json"
```

应显示 `ActiveState=active` 和 `服务端版本：0.4.1`。随后核对 HTTPS 证书、登录、静态资源、采样和后台任务，再安装 **ResearchWorkbench-0.4.1-win-x64.exe**。

证书错误必须在服务器解决；临时 HTTP 只能由用户明确确认。“检查更新”依据公开渠道，本地待发布包不会自动成为公开最新版。

## 回滚

保存脚本给出的 `/var/backups/research-workbench/upgrade-时间戳`。数据库与旧代码需配套恢复，不能只切回旧程序。上线后新增数据先单独备份，再由运维决定回滚；不要删库重建。
