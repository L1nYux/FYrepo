# 运维与升级说明

本页适用于当前源码，功能和权限见 [使用说明书](USER_GUIDE.md)，旧数据库兼容见 [版本交接](INTEGRATION.md)。

## 1. 架构及交接文件

Django + SQLite + Gunicorn + WhiteNoise，消息采用 HTTP 增量轮询。没有额外数据库服务、Redis、WebSocket 服务或实验执行进程。默认 Gunicorn 2 workers、2 threads，面向 2C2G 和小团队。

| 内容 | 默认位置 |
| --- | --- |
| 代码及虚拟环境 | `/opt/research-workbench`、其下 `.venv` |
| 数据库 | `/var/lib/research-workbench/workbench.sqlite3` |
| 上传及发票凭证 | `/var/lib/research-workbench/private_uploads` |
| 环境配置 | `/etc/research-workbench.env` |
| systemd 服务 | `research-workbench.service` |
| 备份 | `/var/backups/research-workbench/` |

代码、迁移、模板、静态文件、文档和部署脚本上传 GitHub；数据、附件、真实环境配置、密码、密钥和备份在服务器管理，不进入源码仓库。服务器若改过路径，以实际环境配置为准。

## 2. 首次安装

将审核通过的源码放在 `/opt/research-workbench`，执行：

```bash
cd /opt/research-workbench
sudo bash deploy/install.sh
sudo -u workbench bash -c 'set -a; source /etc/research-workbench.env; set +a; /opt/research-workbench/.venv/bin/python /opt/research-workbench/manage.py createsuperuser'
```

脚本安装 Python venv 依赖，创建系统用户 `workbench`，生成随机 Django 密钥，执行数据库迁移和静态文件收集，建立 systemd 服务。默认只监听 `127.0.0.1:8000`，不会自动配置 Nginx 或 HTTPS。

已有服务器继续使用既有反向代理配置，确认指向本机 8000 端口。首次安装不自动产生示例业务记录或普通开发者账号。

## 3. 环境变量

| 变量 | 用途 |
| --- | --- |
| `WORKBENCH_SECRET_KEY` | 必填，生产保持既有随机密钥；不要写入仓库 |
| `WORKBENCH_DATA_DIR` | 数据库及附件目录 |
| `WORKBENCH_ALLOWED_HOSTS` | 允许访问的域名 / IP，逗号分隔 |
| `WORKBENCH_DEBUG` | 生产设 `0` |
| `WORKBENCH_HTTPS` | HTTPS 下设 `1`，启用安全 Cookie |
| `WORKBENCH_TRUST_PROXY` | 正确配置 HTTPS 反向代理时设 `1` |
| `WORKBENCH_CSRF_ORIGINS` | 可信访问源，例如 `https://workbench.example.com` |

环境配置权限默认 `0640 root:workbench`；数据目录由 `workbench` 写入，代码及虚拟环境由 root 管理。改配置后重启服务。Django 不自动读取 `.env` 文件，生产由 systemd EnvironmentFile 加载，命令行需先 `source`。

## 4. 常规升级：保留全部已有数据

适用于数据库使用本仓库迁移链的部署。先确认工作目录和数据目录与实际服务器一致；下面示例适用于 `/opt/research-workbench` 是 Git checkout 的安装。若服务器从压缩包安装，请准备独立新发布目录，并由运维完成代码切换，保留环境配置、虚拟环境及外部数据目录。

```bash
sudo -i
cd /opt/research-workbench
git status --short
# 工作区应干净；若有服务器本地修改，先保存并合并，不能直接覆盖。
git fetch origin
RELEASE_COMMIT='替换为审批通过的完整提交SHA'
systemctl stop research-workbench
bash deploy/backup.sh
git checkout --detach "$RELEASE_COMMIT"
.venv/bin/python -m pip install -r requirements.txt
runuser -u workbench -- bash -c 'set -a; source /etc/research-workbench.env; set +a; /opt/research-workbench/.venv/bin/python /opt/research-workbench/manage.py migrate --noinput'
set -a
source /etc/research-workbench.env
set +a
.venv/bin/python manage.py collectstatic --noinput
systemctl start research-workbench
systemctl status research-workbench --no-pager
```

停机前保存旧提交 SHA、服务配置、反向代理配置及环境配置的独立副本。备份输出路径也应记录。任一步骤失败时先处理原因或恢复旧版本，不跳过失败直接启动。

`migrate` 由 `workbench` 用户执行，避免 SQLite 文件或上传目录因 root 写入失去应用写权限。静态文件收集由代码目录拥有者执行。**不要遗漏 `collectstatic`，新版聊天菜单及样式依赖新增 JS / CSS。**

本次源码自带 `0006`、`0007`，在服务器执行 `migrate`；服务器不要重新生成迁移，不要删除历史迁移或对业务库使用 `--fake`。

## 5. 仅保留旧账号的升级方式

`deploy/upgrade_accounts_only.sh --apply-accounts-only` 会新建业务库，只导入旧账号及密码摘要；项目、任务、实验、财务、聊天和附件留在旧备份，不进入新业务库。

这不是常规升级命令。只在明确决定只保留账号，或旧库使用不兼容迁移链时采用。脚本需在独立新发布目录运行，默认路径限制与步骤见 [交接说明](INTEGRATION.md)。

## 6. 备份与回滚

```bash
sudo bash /opt/research-workbench/deploy/backup.sh
```

脚本使用 SQLite 在线备份接口导出数据库，打包附件目录，输出默认备份路径。升级停机期间备份可保持数据库与附件一致；正常运行时也可备份，但附件复制期间的并发上传可能导致时间点不完全一致。

脚本使用默认数据目录，若 `WORKBENCH_DATA_DIR` 改过，先调整脚本或按实际路径备份。脚本不备份环境密钥、源码或反向代理配置，需另外保存。备份应留服务器外副本。

回滚步骤：停服务，保留失败升级后的数据副本，恢复升级前的数据库与附件、旧源码提交及对应依赖，确认属主为 `workbench:workbench`，再启动服务。数据库与代码必须对应同一版本；回滚会撤销备份时间点之后的业务写入。

不通过删除数据库、重跑建库或只回退代码来修复迁移失败。先由运维确认备份、迁移状态和当前代码。

## 7. 排障入口

```bash
systemctl status research-workbench --no-pager
journalctl -u research-workbench -n 100 --no-pager
systemctl show research-workbench -p EnvironmentFiles
```

| 现象 | 排查 |
| --- | --- |
| 缺少表 / 字段 | 当前源码对应的 `migrate` 是否完成；是否加载了正确的数据目录 |
| 样式或「＋」不更新 | `collectstatic` 是否执行，浏览器强制刷新，反向代理静态缓存是否更新 |
| 上传失败 | 反向代理请求大小限制、应用文件格式 / 大小限制、数据目录权限及磁盘空间 |
| 400 / CSRF 错误 | `ALLOWED_HOSTS`、`CSRF_ORIGINS`、HTTPS 与代理配置 |
| SQLite 锁等待 | 并发写入及长期事务；不要有额外脚本持续占用业务数据库 |
| 无权查看报销引用 | 按设计仅申请人 / 管理员可看申请；入账后查看团队账目 |
| 私聊或消息为空 | 先确认登录账号及频道，再检查服务状态、浏览器网络及缓存 |
| 忘记管理员密码 | 加载环境后，以 `workbench` 用户执行 `manage.py changepassword 账户名` |
| 账号权限不对 | 管理员在团队管理检查任免 / 启停；新版没有手动登录身份切换 |

## 8. 发布范围与验收

本次仅上传源码与说明书，未部署生产。本次没有运行新增功能自动化测试；仓库既有测试包含旧页面假设，不能直接视为新版验收结果。

运维可自行在独立预览环境验收：邀请码注册、权限、多人任务及成果、结项 / 删除恢复、实验公开及附件、比赛选用、报销入账、私聊隔离和引用权限。需要补充自动化覆盖时，在独立测试数据库中维护测试，再审批上线。
