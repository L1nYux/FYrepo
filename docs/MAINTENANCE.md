> 合并版权限、公开页面和跨版本账号迁移以 [INTEGRATION.md](INTEGRATION.md) 为准；本页保留常规备份与运维参考。

# 维护与交接说明

面向接手这个工作台的运维组。目标是：换人接手时，看这一份文档就能部署、升级、备份和排障。

## 一、交接范围

**进入团队 GitHub 仓库（由运维组维护）**

- 全部源码：`config/`、`core/`、`templates/`、`static/`
- 数据库迁移文件：`core/migrations/`（必须和模型一起提交，见第四节）
- 部署说明与脚本：`README.md`、`docs/`、`deploy/`、`requirements.txt`
- 自动化测试：`core/tests.py`
- 环境变量模板：`.env.example`（只有占位符，没有真实密钥）

**绝不进入仓库**

| 内容 | 实际位置 | 原因 |
| --- | --- | --- |
| 数据库 | `/var/lib/research-workbench/workbench.sqlite3` | 含全部业务数据 |
| 上传文件与发票凭证 | `/var/lib/research-workbench/private_uploads` | 含成员隐私与凭证 |
| 配置密钥 | `/etc/research-workbench.env` | 泄露等于会话可被伪造 |
| 备份包 | `/var/backups/research-workbench/` | 体积大且含上述全部数据 |
| 本地虚拟环境、本地数据目录 | `.venv/`、`data/` | 与服务器环境无关 |

`.gitignore` 已经覆盖这些路径。提交前用 `git status --short` 确认没有意外加入的文件；
如果 `deploy/` 打发布包，用 `tar --exclude=.venv --exclude=data --exclude=staticfiles` 打包。

## 二、环境变量

安装脚本会在 `/etc/research-workbench.env` 生成一份（权限 `0640 root:workbench`）。字段含义见 `.env.example`：

| 变量 | 说明 |
| --- | --- |
| `WORKBENCH_SECRET_KEY` | 必填。Django 密钥，安装时随机生成，**丢失会导致所有登录会话失效** |
| `WORKBENCH_DATA_DIR` | 数据目录，数据库与 `private_uploads` 都在其下 |
| `WORKBENCH_ALLOWED_HOSTS` | 允许访问的域名/IP，逗号分隔 |
| `WORKBENCH_DEBUG` | 生产必须为 `0` |
| `WORKBENCH_HTTPS` | 走 HTTPS 时设 `1`，启用安全 Cookie |
| `WORKBENCH_TRUST_PROXY` | 前面有 HTTPS 反向代理时设 `1` |
| `WORKBENCH_CSRF_ORIGINS` | 用域名时填写，例如 `https://workbench.example.com` |

修改环境变量后必须 `systemctl restart research-workbench`。改完先用
`systemctl show research-workbench -p EnvironmentFiles` 确认读的就是这份文件。

## 三、部署与升级

首次安装见 `README.md`。日常升级：

```bash
sudo -i
cd /opt/research-workbench
sudo -u workbench git pull --ff-only          # 或解压新的发布包覆盖
.venv/bin/python -m pip install -r requirements.txt
set -a; source /etc/research-workbench.env; set +a
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
systemctl restart research-workbench
systemctl status research-workbench --no-pager
```

升级前先备份（第四节）。`migrate` 会按 `core/migrations/` 里的文件逐步升级数据库，
不要把迁移文件和旧数据库拆开使用。

**升级到「项目展示 + 关于 + 聊天室 + 登录身份」这一版时**（`0004_chatmessage_memberprofile`）：
只新增两张表（账号档案 `MemberProfile`、聊天室消息 `ChatMessage`），**不需要搬移或修正任何既有数据**。
升级前的账号没有档案，一律按「开发者」处理，权限与升级前完全一致。升级步骤还是上面那一套
`git pull` → `migrate` → `collectstatic` → `systemctl restart`。

这一版改了 `static/core/site.js`（新增聊天室轮询）和 `static/core/site.css`（登录身份选择、
聊天室、名单样式），**漏跑 `collectstatic` 会让聊天室不再自动刷新、登录页样式错位**。
新增的 `core/middleware.py` 与 `core/context_processors.py` 已经在 `config/settings.py` 里注册好，
如果升级时手工合并过 `settings.py`，请确认 `MIDDLEWARE` 末尾有 `core.middleware.LoginRoleMiddleware`
（必须在 `AuthenticationMiddleware` 和 `MessageMiddleware` 之后），且 `TEMPLATES` 的
`context_processors` 里有 `core.context_processors.role`。

升级后请留意两点：

- 普通用户注册入口 `/register/user/` 默认开放、不需要邀请码。对外开放前请确认这是想要的；
  要关掉就删掉 `core/urls.py` 里的 `register/user/` 一行，并同时移除登录页上的注册链接。
- 管理员可以自助「升为开发者」，把普通用户纳入团队，不需要额外操作数据库。

**升级到“个人中心 + 深色模式 + 财务报销合并”这一版时**：没有数据模型改动，不需要写迁移，
只要按上面的流程 `git pull`、`collectstatic`、`systemctl restart` 即可，数据库不动。
注意这一版新增了 `static/core/site.js` 并改写了 `static/core/site.css`，漏跑 `collectstatic`
会让右上角的主题切换按钮失效（样式表按内容哈希命名，旧文件不会被浏览器自动替换）；
成员端如果看到的还是旧样子，让浏览器强制刷新一次即可。旧书签
`/finance/claims/`、`/account/password/` 会自动跳到合并后的区块，不需要通知成员改链接。

**升级到“项目树 + 讨论 + 报销”这一版时**（`0002_project_tree_discussions_finance`）：
升级前已存在的任务会整体归入一个名为「升级前的既有任务」的项目，旧的成果文件与财务凭证会
转成统一附件记录，成果正文和审核结论都保留。迁移完成后请以管理员身份登录，进入该项目把任务
按实际研究方向重新归类、指定项目负责人和成员，然后归档这个临时项目。

**升级到“成果与留言可挂项目”这一版时**（`0003_results_and_comments_on_projects`）：
只是新增归属字段和两条数据库约束，不需要人工处理。唯一的数据修正是把「针对成果的留言」上
重复记录的任务归属清空（`task_id` 置空、保留 `submission_id`），留言内容本身不受影响；
升级前用过的成果留言，升级后仍挂在对应成果下面。

## 四、改动数据模型的标准流程

1. 修改 `core/models.py`。
2. 生成迁移：`manage.py makemigrations core`。
3. 确认没有遗漏：`manage.py makemigrations --check --dry-run` 必须输出 `No changes detected`。
4. **把新迁移文件一起提交**，不要只提交模型代码。
5. 服务器上执行 `manage.py migrate`。

如果迁移涉及既有数据的搬移（例如改了字段含义），必须写数据迁移（`migrations.RunPython`）
并先用一份旧库副本演练，确认数据没有丢失再上生产。

## 五、备份与恢复

### 备份

```bash
sudo bash /opt/research-workbench/deploy/backup.sh
# 输出：/var/backups/research-workbench/YYYYmmdd-HHMMSS.tar.gz
```

脚本用 SQLite 的在线备份接口导出数据库（不会拿到写了一半的文件），并打包 `private_uploads`。
建议用 cron 每天执行，并把备份同步到服务器之外：

```cron
15 3 * * * root bash /opt/research-workbench/deploy/backup.sh >> /var/log/workbench-backup.log 2>&1
```

只存在同一台机器上的备份不算备份。定期在别的机器上验证备份能解开、数据库能打开。

### 恢复

```bash
sudo systemctl stop research-workbench
sudo -i
mkdir -p /tmp/restore && tar -xzf /var/backups/research-workbench/<时间戳>.tar.gz -C /tmp/restore
install -d -o workbench -g workbench -m 0700 /var/lib/research-workbench
install -o workbench -g workbench -m 0600 /tmp/restore/workbench.sqlite3 /var/lib/research-workbench/workbench.sqlite3
rm -rf /var/lib/research-workbench/private_uploads
cp -a /tmp/restore/private_uploads /var/lib/research-workbench/private_uploads
chown -R workbench:workbench /var/lib/research-workbench
rm -rf /tmp/restore
systemctl start research-workbench
systemctl status research-workbench --no-pager
```

恢复的数据库版本必须与当前代码匹配：备份里如果有未应用的新迁移，启动后先跑一次
`manage.py migrate`。`WORKBENCH_SECRET_KEY` 不作为数据备份的一部分单独管理，请另行妥善保存。

## 六、2C2G 服务器的取舍

现有配置已经按小机器调过，改动前先确认机器扛得住：

- gunicorn `--workers 2 --threads 2`：2 核即可跑满，内存占用可控；不要再加 worker。
- SQLite 单文件数据库，`timeout=20` 秒等待锁：写入量不大时完全够用，且省掉一个服务进程。
- WhiteNoise 直接服务静态文件（`collectstatic` 生成带哈希名的文件），不需要额外的 Nginx 也能跑。
- 上传限制：单文件 20 MB、一次最多 5 个、单次合计 40 MB，内存缓冲阈值 2 MB，
  超过阈值会落到临时文件，不会把整包读进内存。
- 页面列表都做了截断（任务 300 条、账本 200 条、进展 6~15 条），避免一次渲染过多数据。
- 系统日志交给 journald，不在业务库里记录访问流水。

## 七、排障

```bash
systemctl status research-workbench --no-pager
journalctl -u research-workbench -n 200 --no-pager
```

| 现象 | 排查方向 |
| --- | --- |
| 服务起不来，日志报缺少密钥 | `/etc/research-workbench.env` 是否存在、`WORKBENCH_SECRET_KEY` 是否为空、权限是否 `0640 root:workbench` |
| 页面样式丢失 | 没跑 `manage.py collectstatic --noinput` |
| 上传文件 500 | `/var/lib/research-workbench/private_uploads` 的属主与权限（应为 `workbench:workbench`，目录 `0700`） |
| 数据库被锁 | 是否有第二个进程直接连了同一个 sqlite 文件；正常只有一个 gunicorn 服务在写 |
| 访问报 400 Bad Request | `WORKBENCH_ALLOWED_HOSTS` 没有包含当前访问的域名/IP |
| 忘记管理员密码 | `manage.py changepassword <账户名>`（以 `workbench` 用户执行） |
| 成员被误停用 | 由另一名管理员在「成员」页面重新启用；最后一名在用管理员不能被停用 |
| 登录页提示「权限不足」 | 所选身份高于账号层级（例如开发者选了管理员登录）。让管理员在「成员」页点「邀请成为管理员」，或改选较低的身份 |
| 登录后总被带回项目展示 | 当前会话是「普通用户」身份。左上角导航里没有项目/任务/财务就是这种情况；在右上角头像菜单里切换身份视图即可，不必退出重登 |
| 聊天室不自动刷新 | 没跑 `manage.py collectstatic`，或浏览器缓存了旧的 `site.js`；强制刷新一次 |
| 管理员看不到邀请码/成员入口 | 当前是以「开发者」或「普通用户」身份登录的；在头像菜单里切回管理员视图 |

## 八、交接检查清单

- [ ] 团队 GitHub 仓库权限已转移给运维组，源码、迁移、部署说明都已推送
- [ ] 确认仓库里没有数据库、上传文件、`.env`、备份包（`git log --stat` 抽查历史提交）
- [ ] `/etc/research-workbench.env` 的密钥已另存到团队密码管理器
- [ ] 备份 cron 已配置，且已成功恢复到另一台机器验证过一次
- [ ] `manage.py test core` 全部通过
- [ ] `manage.py makemigrations --check --dry-run` 输出 `No changes detected`
- [ ] 管理员账号至少两人持有，避免单点
- [ ] 已确定长期网络接入方式（域名/HTTPS/反向代理），不再依赖 SSH 端口转发
