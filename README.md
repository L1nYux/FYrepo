# 科研团队工作台

## 本地启动（Windows / PowerShell）

在仓库根目录（`manage.py` 所在目录）执行。首次准备：

```powershell
# 1. 虚拟环境与依赖（仓库里已有 .venv 时前两行可跳过）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 环境变量（只在当前窗口有效）
$env:WORKBENCH_SECRET_KEY = 'dev-only-change-me'   # 必填，缺了程序会直接拒绝启动
$env:WORKBENCH_DEBUG      = '1'                    # 本地开发：按原始文件名提供静态文件，不必 collectstatic
# $env:WORKBENCH_DATA_DIR = "$PWD\data"            # 可选；默认就是仓库下的 data\

# 3. 建库并创建第一个管理员
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser

# 4. 启动
.\.venv\Scripts\python.exe manage.py runserver
```

浏览器打开 <http://127.0.0.1:8000/>，用第 3 步的管理员账号登录，登录页身份选**「管理员登录」**。

日常再次启动只要第 2 步加 `runserver`；**每次 `git pull` 拉到新迁移、或看到
`no such table: core_xxx` 这类报错时，补跑一次第 3 步的 `migrate` 即可**（不用重启服务，刷新页面就行）。

Linux / macOS 把第 2–4 步换成：

```bash
export WORKBENCH_SECRET_KEY='dev-only-change-me'
export WORKBENCH_DEBUG=1
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

几点说明：

- `.env.example` 只是字段模板，**程序不会自动读取 `.env`**（依赖里没有 dotenv），
  每个新开的终端窗口都要重新设置 `WORKBENCH_SECRET_KEY`；想一劳永逸就写进系统环境变量。
- 本地开发用 `DEBUG=1` 最省事；`DEBUG=0` 属于生产配置，它要求先跑 `collectstatic`
  生成带哈希名的静态文件清单，否则页面会因为找不到 `core/site.css` 而报
  `Missing staticfiles manifest entry`。
- 测试：`.\.venv\Scripts\python.exe manage.py test core`（同样需要先设 `WORKBENCH_SECRET_KEY`）。

服务器部署（Ubuntu 24.04 + systemd）见文末[安装与首次使用](#安装与首次使用)。

---

面向小型科研团队的协作工作台：管理员立项目标，项目负责人拆解任务，开发者推进自己负责的部分，
成果、讨论与团队账本都留在一处。以 2C2G 服务器为目标，保持简单、稳定、易维护。

## 角色与权限

账号本身有层级，登录时还要再选一次「以什么身份看」，两者取较小者。

| 账号层级 | 说明 | 主要权限 |
| --- | --- | --- |
| 管理员（`is_staff`） | 团队负责人/运维 | 创建项目、确定目标、指定项目负责人与成员；审核并选取最终成果；随时介入任意项目与任务；分发邀请码、任免人员；记账、作废、审批报销 |
| 项目负责人（`Project.owner`） | 由管理员指定 | 权限只在自己负责的项目内：拆分母任务与子任务、分配负责人、审核成果、结项任务、参与讨论 |
| 开发者 | 凭邀请码注册 | 查看全部项目与任务进度；**对任何任务和项目留言、发布成果**（不必先是项目成员）；推进被分配任务的进度；提交报销申请 |
| 普通用户 | 自助注册，不需要邀请码 | 只能查看项目展示、公共聊天室与关于页面 |
| 访客（未登录） | — | 看不到任何内容，账本与凭证同样不可见 |

账号层级记在 `MemberProfile` 里（`developer` / `normal`）；管理员仍由 `User.is_staff` 表示，
没有档案的账号一律按开发者处理，所以升级前的既有账号行为不变。

## 登录身份

登录页先选身份，再输入账号（**用户名或邮箱**都可以）：

| 登录方式 | 界面 |
| --- | --- |
| 管理员登录 | 完整界面：项目、任务、财务、聊天室，以及邀请码、成员任免与 Django 后台 |
| 开发者登录 | 项目、任务、财务与聊天室；**看不到后台、审核入口和邀请码** |
| 普通用户登录 | 只有项目展示、公共聊天室与关于 |

**生效权限取所选身份与账号层级的较小者**：选更低身份是「降级查看」（管理员选普通用户登录，
就只看到普通用户界面）；选更高身份会被当场拒绝并提示权限不足（开发者选管理员登录只会看到
「权限不足：该账号是开发者，不能以「管理员」身份登录」）。登录后还可以在右上角头像菜单里
**随时切换身份视图**，不必退出重登；账号被降级时，会话里的高身份会立刻失效。

管理员可以在「成员」页把开发者**邀请成为管理员**（点「邀请成为管理员」），也可以把普通用户升为开发者。

角色和权限在「个人中心」（右上角头像）里有清单，账号名、姓名、邮箱、账号层级、当前身份视图、
注册时间也都在那里。生效角色由 `core/middleware.py` 解析到 `request.role`，
判定集中在 `core/permissions.py`，页面范围（普通用户只能进哪几页）也在中间件里一处说明。

项目成员由管理员在项目里指定；任务负责人只能从项目负责人和项目成员中选。需要新人参与时，
管理员先把他加为项目成员（或让他凭邀请码注册后再加入项目）。

**留言和发布成果对全体登录成员开放**，不需要先是项目成员；区别只在管理动作和审核：
任务拆分、结项、审核、人员任免、记账这些仍限管理员或项目负责人。他人未审核的成果，
只有作者本人、管理员和项目内成员能看到，通过审核或选为最终成果后对所有成员可见。

## 功能

- **项目展示**：对外展示团队项目用的页面，当前内容还在开发中，页面上直接写明「项目开发中」。
- **关于**：团队介绍，目前只列出管理员与开发者（普通用户不在名单里，只显示总数）。
- **聊天室**：分「开发者聊天室」（所有管理员与开发者）和「公共聊天室」（所有登录用户）。
  页面每几秒按自增主键增量拉取新消息，不引入 WebSocket，保持零新依赖；消息用 DOM 节点拼装，
  正文只走 `textContent`，不会被当作 HTML 执行。房间之间互不可见，普通用户进不去开发者聊天室。
- **项目树**：项目 → 母任务 → 子任务三级。母任务进度由子任务汇总，项目进度由母任务汇总。
- **成果**：可以直接写纯文本，不强制上传附件；附件支持 TXT、PDF、Word、Excel、Markdown 和图片
  （png/jpg/jpeg/gif/webp/bmp），单个不超过 20 MB，一次最多 5 个、合计不超过 40 MB。
  成果既可以挂在任务上，也可以直接挂在项目上（结题报告、数据集这类不属于单个任务的产出）。
  每个开发者都能发布成果，审核由管理员或项目负责人完成；还有待审核成果时任务停在「待审核」，
  全部审完才按结果结项或退回。
- **讨论**：任务、项目、以及每一份成果都能留言，并区分「目标／思路／问题／结论／讨论」，
  便于追溯上下文、提问并明确责任。
- **审核**：成果、审核、留言在页面上是分开的三块。待审核成果汇总在「审核」区，点「去审核」
  直接跳到对应成果卡片给出结论；管理员可随时把有价值的成果选为最终成果，不必等其他分支完成。
- **项目页**：汇总项目目标、成员、任务树、最新成果和最新留言，管理员一眼看清整体情况。
- **个人中心**：右上角头像进入，显示账号名、姓名、邮箱、角色、注册时间和权限清单；
  本人可以在这里补充姓名与邮箱，并**修改密码**（改密后当前登录保持有效）。
- **财务与报销（合并为一页）**：报销申请在上、团队账本在下，用页内导航切换。
  成员在同一页提交报销申请与发票凭证；管理员在同一页审核，通过后自动生成一条「报销入账」的
  账本记录，凭证同步出现在账本里；账本对所有开发者可见，只有管理员可以记账和作废。
- **深色模式**：右上角一键切换深色／浅色，选择记在浏览器本地并立即生效（无需刷新），
  首次访问跟随系统偏好；刷新时在样式加载前就已定好主题，不会闪白。主题不影响服务端数据。
- **精简记录**：不保存网站运行流水，也不保存用户操作审计；只保留任务讨论、成果、审核结论和财务凭证。

## 页面

| 路径 | 页面 | 可见范围 |
| --- | --- | --- |
| `/showcase/` | 项目展示（当前「项目开发中」） | 登录成员 |
| `/about/` | 关于（管理员与开发者名单） | 登录成员 |
| `/chat/`、`/chat/developers/`、`/chat/public/` | 聊天室入口、开发者聊天室、公共聊天室 | 开发者聊天室限管理员与开发者；公共聊天室对所有登录用户开放 |
| `/` | 项目总览、我的任务、最新进展 | 开发者及以上（普通用户会被带到项目展示） |
| `/projects/<id>/` | 项目页（目标、成员、任务树、成果与留言） | 开发者及以上 |
| `/tasks/` | 全部任务进度（可按状态、只看我负责的筛选） | 开发者及以上 |
| `/tasks/<id>/` | 任务页（进度、成果、审核、留言） | 开发者及以上 |
| `/account/` | 个人中心（账号资料、身份视图、权限清单、修改密码） | 登录成员，只能看自己 |
| `/finance/` | 财务与报销（报销申请与团队账本合并成一页） | 开发者及以上 |
| `/manage/invites/`、`/manage/members/` | 邀请码、成员任免 | 仅管理员 |
| `/admin/` | Django 管理后台（排障用） | 仅管理员 |

普通用户访问上表里「开发者及以上」的页面时，会被中间件带回项目展示并给出提示，而不是丢一个 403。

登录与注册入口：`/login/`（先选身份）、`/register/`（开发者，需邀请码）、`/register/user/`（普通用户，无需邀请码）。

旧的 `/finance/claims/`、`/finance/claims/new/`、`/account/password/` 仍然可用，
会自动跳到合并后的对应区块（`/finance/#claims`、`/account/#password`），方便旧书签继续使用。
报销申请成员只看自己的，管理员看全部；账本对全体登录成员公开，访客完全看不到。

## 目录结构

```
config/            项目配置（settings/urls/wsgi）
core/              工作台应用
  models.py        项目、任务、成果、留言、财务、报销、附件、账号档案、聊天室消息
  permissions.py   角色判定集中在这里（生效角色、可见性、聊天室准入）
  middleware.py    把登录身份解析成 request.role，并限定普通用户的页面范围
  context_processors.py  把生效角色交给所有模板
  views.py         所有页面逻辑
  forms.py         表单、多附件上传字段、登录身份表单
  admin.py         后台注册（排障用）
  migrations/      数据库迁移，必须入库
  tests.py         主流程与权限边界测试
templates/core/    页面模板（项目展示、关于、聊天室、个人中心、财务与报销等）
static/core/       site.css 单文件样式（含深色配色）与 site.js（主题切换、聊天室轮询），无外部依赖
deploy/            install.sh 安装脚本、backup.sh 备份脚本
docs/MAINTENANCE.md 部署、升级、备份与交接说明
```

## 安装与首次使用

服务器为 Ubuntu 24.04。在开发机打包时排除本地环境、数据目录和静态文件产物，
不要把这些一起传上服务器：

```bash
tar --exclude=.venv --exclude=data --exclude=staticfiles --exclude=__pycache__ \
    --exclude=.git -czf research-workbench.tar.gz -C /path/to FYrepo
```

上传后在服务器执行（不要只上传 HTML）：

```bash
sudo -i
mkdir -p /opt/research-workbench
tar -xzf /home/admin/research-workbench.tar.gz -C /opt
cd /opt/research-workbench
bash deploy/install.sh
```

创建第一个管理员（自己输入账户名和密码，不要发给别人）：

```bash
runuser -u workbench -- bash -c 'set -a; source /etc/research-workbench.env; set +a; exec /opt/research-workbench/.venv/bin/python /opt/research-workbench/manage.py createsuperuser'
```

检查服务：

```bash
systemctl status research-workbench --no-pager
```

从 Windows 访问（首次验收用，把占位符换成实际公网 IP）：

```powershell
ssh -N -L 8765:127.0.0.1:8000 root@<服务器公网IP>
```

保持 SSH 窗口打开，浏览器访问 `http://127.0.0.1:8765/`。用管理员登录后，先到「成员 → 邀请码」
生成开发者邀请码交给成员注册。长期使用应单独确定网络接入方式，不要共享 root 密码。

## 数据与备份

| 内容 | 位置 | 是否入库 |
| --- | --- | --- |
| 数据库 | `/var/lib/research-workbench/workbench.sqlite3` | 否 |
| 上传文件与凭证 | `/var/lib/research-workbench/private_uploads` | 否 |
| 配置密钥 | `/etc/research-workbench.env` | 否 |
| 备份包 | `/var/backups/research-workbench/` | 否 |
| 源码、迁移文件、部署说明 | GitHub 仓库 | 是 |

```bash
sudo bash /opt/research-workbench/deploy/backup.sh
```

备份包要定期下载到服务器之外；只放在同一台机器上不算备份。恢复步骤与更多运维细节见
[docs/MAINTENANCE.md](docs/MAINTENANCE.md)。

## 测试

```bash
cd /opt/research-workbench
set -a; source /etc/research-workbench.env; set +a
.venv/bin/python manage.py test core
```

## 当前限制

- 每个任务只有一名负责人；需要多人共同提交时，先拆成多条子任务。
- 只按扩展名和大小检查附件，不做病毒扫描；只给可信成员发邀请码。
- 聊天室是**轮询**实现（默认 4 秒一次，页面隐藏时暂停），不是 WebSocket 实时推送：
  消息略滞后，但零新依赖，2C2G 机器无压力。聊天记录保留在数据库里，只显示最近 200 条，不分页。
- 聊天室没有做发言频率限制和内容审核，只有 2000 字长度上限；对内使用足够，对外开放前需要补。
- **普通用户注册是开放的，不需要邀请码**；普通用户看不到任何团队内容，但会占用一个账号。
  如果希望关闭或改成邀请制，取消 `core/urls.py` 里的 `register/user/` 路由即可。
- 数据库和上传文件在同一台服务器上，必须落实服务器外备份。
- 安装脚本只让程序监听 `127.0.0.1:8000`，没有配置公网 Nginx、域名和 HTTPS；
  财务凭证不应通过明文公网 HTTP 传输。
