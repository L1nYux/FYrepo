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

0.2.7 源码包含 core 至 `0017`、aihub 至 `0008` 的迁移，在服务器执行 `migrate`；服务器不要重新生成迁移，不要删除历史迁移或对业务库使用 `--fake`。`0008`、`0009` 只增加可空外键与可空预算字段，历史报销、账目与项目不受影响；`0011` 是新表，无历史数据。aihub `0007` 增加厂商额度类型与上次查询缓存，`0008` 增加可空的助手重试关联，保留已有对话。

### 6.1 邮件配置（成员自助找回密码）

0.2.5 的登录页及账户设置共用邮箱验证码找回流程，生产环境必须配置 SMTP。已登录发信失败会提示重试；匿名页面统一回复以避免泄露账户状态。原有重置链接仍兼容，但新流程不再签发链接。

**可以直接用某个管理员的邮箱发信**，不必专门申请新邮箱：把 `WORKBENCH_EMAIL_HOST` / `WORKBENCH_EMAIL_USER` / `WORKBENCH_EMAIL_PASSWORD` 三项填成那个邮箱即可，`WORKBENCH_EMAIL_FROM` 留空会自动跟随 `WORKBENCH_EMAIL_USER`（多数邮箱服务要求发件人与登录账号一致，填别的地址会被拒或进垃圾邮件）。

```bash
# 以 QQ 邮箱为例（465 / SSL）
WORKBENCH_EMAIL_HOST=smtp.qq.com
WORKBENCH_EMAIL_PORT=465
WORKBENCH_EMAIL_USER=someone@qq.com
WORKBENCH_EMAIL_PASSWORD='授权码，不是邮箱登录密码'
WORKBENCH_EMAIL_TLS=0
WORKBENCH_EMAIL_SSL=1
```

其他服务商：腾讯企业邮 `smtp.exmail.qq.com:465`、163 `smtp.163.com:465`、Gmail `smtp.gmail.com:587`（TLS，需两步验证后生成应用专用密码）。

- 587 端口用 `TLS=1 / SSL=0`；465 端口改成 `TLS=0 / SSL=1`。两个同时为 1 会导致发信失败（`core.W002` 会提示）。
- 密码类型取决于服务商和账号策略：QQ 等服务使用 **SMTP 授权码 / 应用专用密码**；阿里企业邮箱未开启三方客户端安全密码时可使用邮箱登录密码，开启或被强制开启后必须使用专用安全密码。
- 配置后 `sudo systemctl restart research-workbench`，然后 `python manage.py check`：
  - `core.W001` SMTP 还没配；`core.W004` 配了主机但没填用户名；`core.W005` 有用户名但没填密码；`core.W003` 仍在用控制台后端（验证码只会写进服务日志）。
- 验证方式：用任意一个已填邮箱的账号走一遍「忘记密码」，确认能收到信。
- 邮件里的链接按请求协议生成。通过 HTTPS 反向代理访问时**必须**设置 `WORKBENCH_TRUST_PROXY=1`，否则链接会是 `http://`，成员点开可能失败。
- 重置链接默认 1 小时有效，可用 `WORKBENCH_RESET_TIMEOUT`（秒）调整。
- **邮件后端的选择规则**：只有在「`WORKBENCH_DEBUG=1` 且没有配置 `WORKBENCH_EMAIL_HOST`」时才用控制台后端——此时重置链接与验证码只打印在 `runserver` 的终端里，**不会真的发信**。一旦配置了 SMTP，开发环境也会真实发信（便于本地联调）。页面上会如实说明当前是哪一种模式。
- 邮箱验证码的有效期（10 分钟）、尝试上限（5 次）、重发冷却（60 秒）与每小时发送上限（5 次）是 `core/models.py` 里 `EmailVerificationCode` 的类常量，按需在代码里调整；它们是业务参数，没有做成环境变量。
- 每次发送验证码会写一行 `core_emailverificationcode`（只存加盐摘要）。10 人团队的体量下无需清理；如需清理，可在 Django admin 里按时间删除旧记录。
- **发信失败不会给成员 500**：找回流程捕获异常并删除未发出的验证码记录，不占账户发送配额。浏览器仍有 60 秒重试冷却；匿名回复不会透露发信或账户状态。

#### 阿里企业邮箱：现有服务器直接配置

服务器地址为 `smtp.qiye.aliyun.com:465`，使用 `SSL=1 / TLS=0`。需要同时确认账号 SMTP 权限和团队第三方客户端访问策略：

1. 管理后台「用户与组 → 用户」，编辑发件账号，在「功能权限 → 客户端」开启 **SMTP 服务**。
2. 管理后台「安全 → 访问策略」，检查 **禁止使用三方客户端** 策略是否包含该账号。仅工作台发件账号需要使用时，优先编辑策略，将其设为例外；当前界面名称可能随版本变化。
3. 策略修改后等待约 5 分钟。网页能登录、已完成手机验证，并不代表 SMTP 已获准；`526 Authentication failure` 仍需检查凭据、专用密码要求和访问限制。不要关闭网页双重认证来猜测 SMTP 故障。
4. 若开启或强制启用了三方客户端安全密码，在邮箱网页端为服务器生成独立密码；否则可使用当前邮箱登录密码。管理员账号编辑页的「安全密码」列表为空只能说明没有已生成的密码，不能证明未启用强制策略。

参考：[SMTP 地址和端口](https://help.aliyun.com/zh/document_detail/36576.html)、[526 认证失败](https://help.aliyun.com/zh/document_detail/602363.html)、[第三方客户端访问策略](https://help.aliyun.com/zh/document_detail/606337.html)。

现有部署使用 `/etc/research-workbench.env` 时，可执行：

```bash
sudo python3 deploy/configure_aliyun_smtp.py --user your-mailbox@example.com
```

脚本在终端隐藏输入密码，先认证，成功后备份原环境文件到 `/var/backups/research-workbench/smtp-*/environment.env`，仅更新七项邮件参数，重启 `research-workbench`，检查本机连接接口。启动失败会恢复原环境配置并尝试恢复服务。无需迁移数据库或替换应用代码；不会发送测试邮件。最后由成员实际使用「忘记密码」确认收信。

密码不出现在命令参数、输出或源码中；环境文件保留原属主，权限限制为原权限与 `0640` 的交集，备份目录为 `0700`、备份文件为 `0600`。密码中的引号、反斜线、美元符和反引号使用同时兼容 systemd 与升级脚本的转义。邮箱改密或更换专用密码后重新执行上述命令即可更新。

#### 成员报告「收不到验证码 / 重置邮件」时的排查顺序

1. **开发环境**：`WORKBENCH_DEBUG=1` 且没配 SMTP 时本来就不发信，验证码在 `runserver` 的终端里。页面上也会有说明。
2. **看服务日志**：发信失败会记录 `验证码发送失败` 或 `重置邮件发送失败` 以及底层异常，`journalctl -u research-workbench -n 100 --no-pager` 里能看到认证失败、连接被拒或域名解析失败。
3. **跑配置自检**：`python manage.py check` —— 见上面 `core.W001` / `W002` / `W004` / `W005` 各自对应的缺项。
4. **确认收件地址**：账号绑定的邮箱在「账户设置 → 账户资料」；页面上只显示掩码（`z***@example.com`）。填错时成员自己就能改。
5. **垃圾邮件与延迟**：个人邮箱向自己发信容易被判定为垃圾邮件，先查垃圾箱；部分服务商有几分钟延迟。
6. **链接点开失败**：走 HTTPS 反向代理但没设 `WORKBENCH_TRUST_PROXY=1` 时，邮件里的链接会是 `http://`（验证码流程不受影响）。

#### 用管理员个人邮箱发信要注意什么

这是 10 人以内完全可以接受的做法，但有几条要事先知道：

1. **凭据落在服务器上**。授权码存在 `$ENV_FILE`（`chmod 0640`、`root:workbench`），意味着应用进程和 root 都能用它发信。授权码应单独生成并记住，方便随时吊销；不要用邮箱主密码。
2. **发信额度与风控**。个人邮箱有每日发信上限，短时间大量发送可能被限流或临时封禁。本场景量很小（每次找回一封），正常使用没问题，但不要拿它做群发。
3. **单人依赖**。管理员改密码、离职或邮箱被停用时，全团队的找回入口会一起失效，需要更新 `$ENV_FILE` 并重启服务。用团队共用邮箱或专门申请一个免费邮箱可以避开这一点。
4. **收件人可能疑惑**。成员会收到一封来自该管理员个人地址的系统邮件，可在团队内先说明。要换发件人显示名可以自行调整 `DEFAULT_FROM_EMAIL` 的格式（例如 `科研团队工作台 <someone@qq.com>`），但地址部分仍需与登录账号一致。

### 6.2 `0010` 迁移可能因重复邮箱停下

`0010` 会统一把邮箱转小写并加唯一索引（一个邮箱只能对应一个账号，这是「按邮箱找回」的前提）。若现有账号里已经存在重复邮箱，`migrate` 会报错并列出冲突的邮箱与账号 ID，例如：

```
存在重复邮箱，无法为「邮箱自助找回密码」建立唯一索引。请先处理这些账号的邮箱后再运行 migrate：same@example.com → 账号 [3, 7]
```

用 Django admin 或 `manage.py shell` 把冲突账号改成各自唯一的邮箱，再重新运行 `migrate`。邮箱为空白的账号不受影响，可以继续并存。

用 `deploy/upgrade_accounts_only.sh` 导入旧账号时，导入命令会把邮箱统一转小写；如果旧库本身有重复邮箱，唯一索引会在这里报错——这属于源数据问题，需要在旧库里先处理。

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

### 0.2.5 升级

使用 `deploy/upgrade_preserve_data.sh --apply` 完成备份、迁移、静态资源和服务切换。core `0017` 给账目和报销增加可空的回收站时间，不修改历史金额。原 `/etc/research-workbench.env` 中 SMTP 设置、用户密码、附件和 API 密钥保留。客户端安装与服务端升级是两个步骤；发布调试结果见 `RELEASE_0_2_5.md`。

## 0.2.10 运维

`GET /healthz/` 只检查数据库连接，返回 200 / status=ok，故障返回 503 / status=unavailable。404/500 模板不依赖数据库上下文，故障页仍能显示。主要业务列表每页 30 条；消息历史仍使用原有游标加载。

标准日志写入服务控制台，由 systemd journal 收集。设置 `WORKBENCH_ADMINS`（逗号分隔邮箱）并保留已有 SMTP 后，Django 请求错误发送简短运维邮件，仅含级别、请求方法与路径；不含请求正文、凭证或提示词。HTTPS 部署设置 WORKBENCH_HTTPS=1 后按 WORKBENCH_HSTS_SECONDS（默认一年）启用 HSTS；HTTP 开发与现有 HTTP 地址默认不发送 HSTS。反向代理仍使用已有 nginx 示例。

core.0020 增加引用、表情、实验进度和运行；core.0021 将已有非空结果的实验标为已完成。aihub.0011 修正调用排序，0012 增加实验/成员调用与助手对话索引。不要清空原库或重建账户；执行保留数据升级脚本。

助手 UUID 和重试标识保持原值；aihub.0013 以独立的创建序号处理相同时间戳，迁移为旧记录补序号。重试只恢复原消息之前的上下文，同时间戳的后续消息不混入。
