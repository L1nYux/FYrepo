# 工作台评审与改进路线图

评审对象：本仓库（Django 5.2 + SQLite + Gunicorn/WhiteNoise 的科研团队工作台，迁移链 `0001`–`0011`）。
定位：**对外是项目展示站，对内是团队管理工作台**，两者共用一套模板与模型。
评审方式：通读代码 + 实际运行验证（见文末「验证记录」）。评审本身未修改业务代码；其后按本报告的结论落地了 10 项改动，见 0.1。

---

## 0.1 已落地的改动（评审后修复）

| 改动 | 内容 | 回归覆盖 |
| --- | --- | --- |
| 报销关联项目 | `ExpenseClaim` 新增可空 `project`（迁移 `0008`）；报销表单多一个「关联项目（可选）」下拉框，只列出本人参与的项目，管理员可选全部未删除项目；报销列表新增「项目」列，未关联显示「未关联项目」 | `ClaimProjectTests`（5 个用例） |
| 账本余额算错 | `finance_list` 原先先 `entries[:200]` 再求和，账目超过 200 条时余额静默算错；改为按整本账本用 `Sum(filter=...)` 聚合，并按「分」补齐两位小数 | `test_balance_counts_the_whole_ledger_not_just_the_visible_page`、`test_voided_entries_are_left_out_of_a_developers_totals` |
| 作废账目计入余额（评审后自查发现） | 上面那次修复只对非管理员排除了作废账目，导致**管理员看到的余额把作废金额算了进去**（实测差额 `-749` vs `-1526`）。已改为对所有人只统计未作废账目，作废记录仍对管理员显示在列表里 | `test_voided_entries_are_left_out_of_an_admins_totals` |
| 项目成本汇总 | `FinanceEntry` 新增可空 `project`、`Project` 新增可空 `budget`（迁移 `0009`）；记账表单可指定项目；报销审批入账时自动带入 `claim.project`；项目页「概览」新增成本汇总（已用 / 预算 / 剩余 / 收入 / 使用比例 + 关联账目列表） | `ProjectCostTests`（7 个用例） |
| 报销申请对成员全公开 | 按产品决定，报销申请（含他人待审申请、凭证与审核结论）改为对全体团队成员可见，与团队账本口径一致。涉及 4 处收窄逻辑：`permissions.can_view_claim`、报销凭证下载、`finance_list` 的申请人过滤、聊天引用搜索的申请人过滤；普通用户仍由中间件挡在门外 | `test_developer_sees_every_claim_including_pending`、`test_claim_vouchers_follow_the_claim_visibility`、`ChatReferenceScopeTests`（3 个用例）、`test_existing_normal_user_remains_restricted` |
| 邮箱自助找回密码 | 接入 Django 的 `PasswordResetView` 系列 + 4 个页面 + 邮件模板；注册与账户资料改为必填唯一邮箱；`pre_save` 统一小写 + 迁移 `0010` 非空邮箱唯一索引；`EMAIL_*` 走环境变量、DEBUG 用控制台后端；新增 `core.W001`–`W004` 启动自检；登录页加「忘记密码」入口；普通用户也可走完流程 | `PasswordResetTests`（12 个用例）、`EmailConfigurationCheckTests`（5 个用例） |
| 邮件发信健壮性（评审后自查修复） | 原实现里 DEBUG 会**强制**使用控制台后端，导致本地配了 SMTP 也收不到信；且发信异常未捕获会让成员看到 500，同时已签发的验证码白占 60 秒冷却与每小时配额。现改为「DEBUG 且未配 SMTP」才用控制台后端，两种找回流程都捕获发信失败并删掉未送达的验证码；页面如实说明验证码去了哪里 | `test_send_failure_is_reported_and_releases_the_cooldown` 等 6 个用例 |
| 已登录时的验证码重置 | 「密码与安全」新增「忘记密码」入口：`EmailVerificationCode`（迁移 `0011`）+ 发码/校码/设密三个视图，**先只验验证码，通过后才进入设置新密码页**（验证状态记在会话并绑定该条验证码，新码/过期/重置后即失效）；验证码只存加盐摘要、10 分钟有效、限 5 次尝试、60 秒冷却、每小时最多 5 封、每次签发作废旧码；只发往账号自己绑定的邮箱；改密后当前会话保持、其他设备登出 | `PasswordCodeResetTests`（17 个用例） |
| 账户设置「外观」栏 | 从设置导航、右上角账户菜单、`profile` 视图与模板中移除；主题只由顶栏开关切换；同步删掉只服务于该页签的 JS 与 CSS | `test_appearance_tab_is_gone`、改写后的 `ThemeTests` |
| 删除不可达模块 | 删除 4 个无路由视图（`showcase`/`about`/`register_normal`/`switch_role`）、3 个只服务于它们的模板（`showcase.html`/`about.html`/`register_user.html`）与 `NormalUserRegisterForm`；清理 `middleware` 失效白名单项与 views 中的失效 import | 全量测试 + `makemigrations --check` |
| 文档与代码对齐 | README、USER_GUIDE、INTEGRATION、MAINTENANCE、本次更新摘要改为与当前代码一致；`views.py` / `permissions.py` / `models.py` 的失效注释与房间命名一并修正 | — |

测试总数由 105 增至 **175，全部通过**；迁移链推进到 `0011`，`makemigrations --check` 无待生成迁移。

---

## 0. 结论摘要

基础质量好于同类小项目：权限集中在 `core/permissions.py` 一处、附件全部走私有下载并逐对象鉴权、聊天轮询零新依赖、公开/内部两套壳分离清晰，`manage.py check` 无告警，**105 个既有测试全部通过**。

真正值得投入的是三类问题：

1. **展示侧「只展示了过程的一半」。** 公开页有项目、实验、成员、联系方式，唯独**没有任何成果**——而首页文案承诺的是「让成果有出处」。这是定位与实现之间最大的一处缺口。
2. **管理侧有几条断链。** 项目成本核算已打通（报销与账本都可关联项目、项目页有成本汇总与预算），忘记密码也有了解法（邮箱自助找回）；仍缺的是列表大量切片截断但无分页、工作台首页缺少「我的任务 / 最新动态」（**视图已经查好了数据，模板没有渲染**）、无导出、无通知。
3. **工程与运维欠账。** 无数据库索引、无日志配置、无 CI、无健康检查、无 404/500 模板、6 个样式表全量加载且 141 个选择器互相重复。

按收益/成本排序的落地顺序见[第 6 节](#6-建议的迭代顺序)。

---

## 1. 先修：低成本、可立即处理的问题

这一节都是删改量很小、几乎没有回归风险的项目。

### 1.1 死代码与失效的路由名（本轮已删除）

这些**不是功能 bug**：旧版普通用户账号依赖 `MemberProfile.NORMAL` 继续受限访问，这是有意保留的兼容行为（已实测 `exclude(member_profile__tier='normal')` 不会误伤无档案账号）。问题是留下了 4 个不可达视图 + 3 个死模板 + 1 个失效白名单项，后来者会以为它们有用。

**已全部删除**：

| 位置 | 评审时的问题 | 处理 |
| --- | --- | --- |
| `core/views.py` `register_normal` | 无任何 URL 指向它；`core/urls.py` 只注册了 `views.register`（邀请码注册）。普通用户自助注册已被产品明确关闭（`docs/USER_GUIDE.md:45`） | 删除视图、`NormalUserRegisterForm` 与 `templates/core/register_user.html` |
| `core/views.py` `switch_role` | 同样无 URL；`docs/USER_GUIDE.md:45` 明确「关闭手动登录身份切换」 | 删除视图 |
| `core/views.py` `showcase`、`about` | `core/urls.py` 已把 `showcase`/`about` 两个 URL 名指向 `portal.public_projects` / `portal.public_members`，这两个视图与对应模板永远不会被渲染 | 删除 2 个视图与 `showcase.html`、`about.html` |
| `core/middleware.py` | `NORMAL_ALLOWED_VIEWS` 里列着已不存在的 `'switch_role'` | 删除该白名单项（`showcase`/`about` 两个名字仍有效，因为指向 `portal`） |
| `core/views.py` | 失效的 `import json` 与 `NormalUserRegisterForm` import | 已清理（`pyflakes` 式清点确认无残留引用） |

`MemberProfile.NORMAL`、普通用户的中间件限制与公共聊天室访问全部保留，行为不变。

### 1.1b 仍未处理：`Project.PAUSED` 不可达

`Project`（`core/models.py`）定义了 `PAUSED`（「已暂停」），但**全仓库没有任何写入点**：`ProjectForm.fields` 不含 `status`，`project_close` 只在 `active` / `closed` 之间切换，admin 的 `list_filter` 也改不了实际数据。这个状态徽标永远不会出现。

**建议**：二选一——给项目加「暂停 / 恢复」动作与界面入口（`Project.status`、CSS 徽标、筛选都已就绪，成本很低），或者删掉这个枚举值。本轮未动，因为它涉及产品决策而不是清理。

### 1.2 视图算完却不用的上下文（白跑查询）

- `core/views.py:381-387`：`dashboard` 查出 `my_tasks`、`latest_submissions`、`latest_comments`，但 `templates/core/dashboard.html` 只渲染了 `project_rows`，三者从未出现在模板中（已全仓 grep 确认）。这三次查询（含 `visible_submissions` 的权限过滤）每次都白跑。
- `core/views.py:452-453`：`project_detail` 传的 `project_results`、`task_results` 在 `templates/core/project_detail.html` 中未被使用。

顺带暴露一个**真实的功能回归**：`core/views.py:7` 的模块注释仍写着「工作台首页：项目总览、我的任务、最新进展」，数据也还在查——说明首页原本有「我的任务 / 最新进展」两块，后来从模板里掉了。管理工作台的首页没有个人待办和最新动态，是这一版体验上最明显的退步（见 3.2）。

### 1.3 无 404 / 500 模板

`templates/` 下只有 `core/`，没有 `404.html` / `500.html`。`DEBUG=0` 时用户看到的是 Django 的英文默认页，与公开站的浅色视觉体系完全脱节。对一个「展示型」站点，错误页也是门面。
**建议**：加 `templates/404.html`、`500.html`（延续 `public-site` 壳），并在 `DEBUG=0` 下验证一次。

### 1.4 列表静默截断（无分页、无提示）

以下位置直接切片，超出部分**无声消失**，页面既不显示总数也不提示「仅显示最近 N 条」：

| 位置 | 上限 |
| --- | --- |
| `core/views.py:366` 项目总览 | 50 |
| `core/views.py:414` 任务列表 | 300 |
| `core/views.py:435` 项目页成果 | 120 |
| `core/views.py:458` 项目页最近留言 | 8 |
| `core/views.py:862` 邀请码 | 100 |
| `core/views.py:942` / `:958` 账本 / 报销 | 200 / 200 |
| `core/views.py:290-291`、`:343` 聊天记录 / 轮询 | 200 |
| `core/messages.py:101` / `:127` 消息历史 / 轮询 | 200 / 100 |
| `core/chat_references.py:95` 引用搜索 | 20 |

10 人团队暂时够用，但「账本只显示最近 200 条」在财务场景下是**数据可信度问题**：余额曾经是按 `entries[:200]` 算出来的，账目一旦超过 200 条，**页面上的余额会静默算错**。**这一条本轮已修复**（见 0.1）：金额统计改为数据库聚合，列表仍只显示最近 200 条，但总额不再受切片影响。剩下的问题只是列表本身仍无分页与总数提示。

### 1.5 仓库卫生

- 仓库根目录残留：`workbench-backup-before-0004.sqlite3`（319 KB）、空文件 `workbench.sqlite3`、空目录 `FYrepo/`、`.test-scratch/`、`tmpzlhwtbho/`。
- `pr5-run/` 是一个 git worktree（分支 `pr5`），仅靠 `.git/info/exclude:8` 在**本机**忽略；换一台机器 clone 会直接看到它。
- `.gitignore` 的本地修改（新增 `.test-scratch/`）尚未提交。

**建议**：删掉上述残留，把 `pr5-run/` 的忽略规则挪进 `.gitignore`，提交 `.gitignore`。

### 1.6 文档与注释漂移（本轮已全部修正）

| 位置 | 评审时的问题 | 处理结果 |
| --- | --- | --- |
| `core/views.py` 模块 docstring | 「项目展示：内容还在开发中，先给占位说明」「关于：目前只列出管理员与开发者」 | 重写为与当前页面分工一致，并说明展示页已由 `core/portal.py` 提供 |
| `core/views.py` 模块 docstring | 「所有页面都要求登录，访客看不到任何内容」 | 改为「工作台与消息区要求登录；公开站与公开附件例外」 |
| `core/permissions.py:279-282`、`core/models.py:395` | 仍称「开发者聊天室」 | 统一改为「公共讨论」，与界面标签、USER_GUIDE 一致；`templates/core/chat.html` 与测试 docstring 一并修正 |
| `README.md`、`USER_GUIDE.md`、`INTEGRATION.md`、`local-research-preview.md` | 称「本次没有运行新增功能的自动化测试」 | 改为说明仓库自带 175 个自动化测试且全部通过，同时保留「仍未部署生产、需团队验收」的表述 |
| `README.md`、`USER_GUIDE.md`、`INTEGRATION.md`、`MAINTENANCE.md` | 迁移链写到 `0007` | 全部更新到 `0009`，并说明 `0008`/`0009` 只增加可空外键与可空预算 |
| `README.md`、`USER_GUIDE.md`、`local-research-preview.md` | 仍把「外观」列为账户设置内容 | 随「外观」栏移除一并更新，改为「主题由顶栏开关切换」 |

> 历史迁移 `0004_chatmessage_memberprofile` 里仍保留 `'开发者聊天室'` 这个 choices 文本。那是迁移的历史记录，`0006` 已把标签改为「公共讨论」，**不要为此改动历史迁移**。

### 1.7 两套聊天入口并存

`ChatMessage` 一张表承担三个房间（`public` / `developers` / `private`），却有两套页面：

- `templates/core/chat.html` → `/chat/public/`、`/chat/developers/`（旧版，`core/views.py:277-357`）
- `templates/core/messages.html` → `/messages/`（新版消息中心，`core/messages.py`）

导航里只挂了「消息」；旧聊天页从导航消失但仍可直达，且旧页会把消息写进 `public` 房间——而新版把该房间标成「公共聊天室 · 已有公共消息」的**兼容入口**（`core/messages.py:115`）。`core/messages.py:112` 的 `public_unread` 实际装的是 `developers` 房间的未读数、`:114` 的 `legacy_unread` 装 `public`，命名与含义已经对不上。

**建议**：明确取舍。要么删掉 `/chat/*` 与 `chat.html`、把 `public` 房间定型为只读历史；要么在 `_render_chat` 上加弃用横幅。同时修正 `public_unread` / `legacy_unread` 的命名。

---

## 2. 展示侧：从「项目介绍页」变成真正的项目展示

### 2.1 **公开成果完全缺失**（最高优先级）

公开站现在能看项目、实验、成员、联系方式，唯独看不到任何**成果**：`Submission`（`core/models.py:288`）已有 `is_final`、`status=accepted` 等成熟状态，`Experiment` 有 `visibility` 公开审核链路，但 `Submission` **没有对应的公开字段与公开页面**，`portal.py` 里也没有任何读取 `Submission` 的公开视图。

而首页主标题是「让研究过程可理解，**让成果有出处**」（`templates/core/public_home.html:2`）——目前的公开站只兑现了前半句。

**建议**：
1. `Submission` 增加 `public_state`（`internal` / `pending` / `public`），复用 `Project.public_state` 的审核模式（申请 → 管理员批准，`core/portal.py:204-221` 已有现成实现可参考）。
2. 新增 `/public/results/` 列表与 `/public/results/<pk>/` 详情，并在公开项目详情页聚合该项目下已公开成果。
3. 复用实验公开时的风险提示口径：`docs/USER_GUIDE.md:117` 已写明「实验公开则附件也允许访客下载」，成果公开需同样明确（源码链接、附件是否随之公开）。
4. 补充一个「成果 → 来源项目 / 来源实验」的溯源链，这正是工作台相对 GitHub README 的差异点。

### 2.2 公开项目详情太薄

`templates/core/public_project_detail.html` 只渲染 `public_summary` + 关联公开实验列表。缺少：项目周期/起止时间、当前阶段、参与成员（公开资料）、公开成果、更新动态、关键词/标签、封面图。`Project` 模型也没有对应字段（`core/models.py:146-171`：只有 `name/goal/description/public_summary/status` 等）。

**建议**：模型加 `public_tags`、`started_on`、`cover`（可选）、`public_stage`；详情页加时间线与成员区。

### 2.3 全站没有任何图片

全模板 `<img>` 标签数为 **0**（已 grep 确认）；附件只能下载，图片附件没有缩略图/预览，成员头像是首字母色块。展示型站点没有一张图，视觉说服力受限。

**建议**：至少做 (a) 图片附件的缩略图预览（下载入口已有鉴权，缩略图需复用同一权限判断，**不要**退回 `MEDIA_URL`），(b) 项目封面 / 成员头像可选上传。

### 2.4 SEO 与分享基础缺失

已确认全站**没有**：`<meta name="description">`、Open Graph / Twitter Card、`rel="canonical"`、favicon、`sitemap.xml`、`robots.txt`。公开页标题只有 `{{ project.name }} · 公开项目` 之类的简单拼接。

对一个要被外部看到、被引用的展示站，这是性价比最高的一组改动：加 meta 描述 + OG 标签（分享到群/微信时才有预览卡）、favicon、`django.contrib.sitemaps`、`robots.txt`。

### 2.5 公开列表无分页、无筛选

- `portal.public_projects` / `public_experiments` 全量返回，无分页、无排序选项、无按项目/年份筛选（`core/portal.py:29-45`）。
- 公开项目页连搜索框都没有（公开实验页有 `q`，但只搜 `title/number/purpose`，`core/portal.py:44`）。
- 公开成员页是一整页列表，没有个人主页，无法从成员跳到其成果。

### 2.6 其他

- 无 RSS / Atom，外部无法订阅公开更新。
- 「联系我们」无留言/合作申请表单——`docs/USER_GUIDE.md:13` 说明是有意不做，建议在页面上明示「暂不接收在线留言」，否则访客会以为表单坏了。

---

## 3. 管理侧：补齐工作台的闭环

### 3.1 账本与项目的关联（本轮已打通）

`FinanceEntry` 与 `ExpenseClaim` 原先**都没有 `project` 外键**，`Project` 也没有预算字段。结果是：账本能算出团队余额，但**无法回答「这个项目花了多少钱」「还剩多少预算」**。

**已落地**：
- `ExpenseClaim.project`（`0008`）与 `FinanceEntry.project`（`0009`），都可为空，历史数据不受影响。
- 项目 `budget`（`0009`），在项目设置里填写。
- 记账表单可指定项目；报销审批入账时自动把 `claim.project` 带入生成的账本记录。
- 项目页「概览」新增成本汇总：已用（流出合计）、项目收入、预算、预算剩余、使用比例与进度条（超支标注、封顶 100%），并列出来源账目（最多 20 条）。作废账目一律不计入。

**仍可继续**：按项目查看报销申请（现在报销只在财务页按申请人过滤，项目页看不到待审金额）；成本按任务/实验分摊；导出项目成本 CSV。这些属于增量，不再是「断链」。

### 3.2 工作台首页缺「我的待办」与「最新动态」

见 1.2：`dashboard` 视图把数据查好了，模板没渲染。

**建议**：在项目管理首页补两块——「我的未结项任务」（按 `due_date` 排序，逾期高亮；`Task.overdue` 已实现于 `core/models.py:267`，目前只在任务列表页用到）与「最新成果 / 最新留言」（数据现成）。这样团队成员登录后第一眼看到的才是「我该做什么」。

### 3.3 无导出

没有任何导出能力。管理型工作台的高频诉求：账本导出 CSV/XLSX（对账）、任务与进度导出（周报）、实验记录导出（论文附录）、结题报告导出（DOCX/Markdown）。

**建议**：先做纯 CSV（零依赖，全站已有 `Content-Disposition` 附件下载范式）；结题报告可后置。

### 3.4 无通知、邮件字段闲置

`ProfileForm` 维护 `email`（`core/forms.py:145-152`），但 `settings.py` 里**没有任何 `EMAIL_*` / `ADMINS` 配置**，全站不发邮件。成员只能靠站内未读红点（`core/messages.py:27-40`）感知变化。

**建议**：先做最低成本的两项——(a) 配置 `ADMINS` + `SERVER_EMAIL`，让 500 错误能发出来；(b) 明确写清「本版不发送邮件通知」，避免邮箱字段造成预期落差。

### 3.5 忘记密码 缺失（运维硬缺口）——本轮已解决

`core/urls.py` 原先只有 `login` / `logout` / `register` / `profile` / `change_password`，**没有 Django 的密码重置流程**；`members` 视图只能启用/停用/升降管理员，**管理员也无法为成员重置密码**。

真实后果：成员忘记密码 → 该账号在系统内无法恢复，只能走 `manage.py changepassword`（需服务器权限），而 `docs/USER_GUIDE.md:54` 又强调「SSH 权限不等于网站管理员权限」。这是设计与运维现实的冲突点。

**已落地（邮箱自助找回）**：接入 Django 自带的 `PasswordResetView` 系列，配合三项前置改造——
- **收邮箱**：邀请码注册与「账户资料」都要求填邮箱（原先注册根本不收邮箱，导致大部分账号没有找回凭据）。
- **邮箱唯一**：表单层大小写不敏感去重 + `pre_save` 统一小写 + 迁移 `0010` 加非空邮箱的部分唯一索引；重复邮箱会让迁移报错停下并列出冲突账号。
- **邮件配置**：`EMAIL_*` 走环境变量，`DEBUG` 下用控制台后端（重置链接直接打印在 runserver 输出，本地零配置可走通），并加了 `core.W001`–`W003` 启动自检，把「生产没配 SMTP」从成员遇到的 500 变成启动时的明确警告。

安全属性：邮箱不存在时同样跳到「已发送」页（不枚举账号）、令牌哈希含密码与邮箱（改密或改邮箱后旧链接立即失效）、1 小时有效、单次使用、重置后不自动登录且其他设备会话失效。

**仍缺**：`ADMINS` + `SERVER_EMAIL` 仍未配置，500 错误不会发邮件给运维（原建议的另一半）。

### 3.6 无全局搜索

现在只有分散的局部搜索：任务列表 `q`、实验库 `q`、聊天引用搜索 `core/chat_references.py:79`。没有跨项目/任务/实验/成果/账本的统一搜索框，成员找一个半年前的东西只能靠翻。

### 3.7 无变更历史（有意为之，但需权衡）

`core/models.py:8` 明确写「不保存网站运行流水，也不保存用户操作审计」；`docs/USER_GUIDE.md:131,165` 也重申。作为隐私/精简取舍可以理解，但要意识到代价：**成果被退回、账目被作废、成员被降权之后，没有任何地方能回答「谁在什么时候改的」**。建议至少保留已有的时间戳字段（`reviewed_at`/`closed_at`/`voided_at` 等已在），并考虑为项目与账本加一个轻量「变更记录」列表（复用 `Comment` 的 `NOTE` 类型即可，不需要新表）。

### 3.8 其他管理侧增强

- 无数据看板：进度分布、逾期任务数、成果产出趋势、预算燃尽。已有 `summarise_progress`（`core/models.py:123`）作为聚合基础。
- 比赛模块偏薄：`Competition`（`core/models.py:190`）只有名称/官网/截止/说明/选用成果，缺获奖结果、名次、参赛状态。
- `Project.status` 的 `paused`（已暂停）没有界面入口，见 1.1，需要补「暂停 / 恢复」按钮或删掉该状态。
- 邀请码创建后仅显示一次（安全性上正确），但缺少一键复制按钮（`templates/core/invites.html:2` 让用户手动选中 `{{ fresh_code }}`）。

---

## 4. 技术与运维

### 4.1 数据库全表无索引

`core/migrations/` 中 **`db_index` / `indexes` 出现次数为 0**。但代码大量按这些字段过滤：

- `Project.archived_at`、`Project.public_state`（`core/models.py:152,166`）
- `Experiment.visibility`（`core/models.py:609`）
- `Task.archived_at`、`Task.status`、`Task.due_date`
- `ChatMessage.room` + `pk`（轮询高频，`core/messages.py:127`）
- `Submission.status`、`is_final`

10 人规模下无感，但轮询 + 公开站在增长后会先痛。**建议**：迁移 `0008` 为上述字段加 `db_index=True`（零风险，只需 `Meta.indexes`）。

### 4.2 SQLite 生产参数

`deploy/install.sh:55` 起 2 workers × 2 threads = 4 并发，全部写同一个 SQLite（`config/settings.py:47`，仅 `timeout: 20`）。未开 WAL，未用 `transaction_mode`。财务入账、成果审核这些都用 `select_for_update`（如 `core/views.py:768`、`:1028`）——SQLite 下这会退化为全库写锁，并发写入有 `database is locked` 风险。

**建议**：`OPTIONS` 加 `init_command: 'PRAGMA journal_mode=WAL;'`（Django 5.1+ 亦可用 `transaction_mode: 'IMMEDIATE'`），并把 `--workers` 降到 2 以内或改用线程模型；同时给出「超过 ~20 人换 PostgreSQL」的明确阈值。

**换库时的一个隐藏路障**：实验搜索用了 `parameters__icontains`（`core/portal.py:90`）。Django 把它实现为对 JSON 整列做大小写不敏感的 `LIKE`（`.venv/.../django/db/models/fields/json.py:346` 的 `JSONIContains` 直接继承 `IContains`）。已实测**在 SQLite 上工作正常**（返回匹配记录），但这依赖 SQLite 把 JSON 存成文本；若按上面的建议迁到 PostgreSQL（jsonb），`UPPER(jsonb)` 没有对应运算符，这一条检索预计会直接报错。真要换库，这里需同步改写（例如改查 `parameters__name__icontains` 或上全文检索）。

### 4.3 无日志配置

`config/settings.py` 全文 88 行，**没有 `LOGGING`**，也没有 `ADMINS`。生产上 `DEBUG=0` 的 500 异常只落在 gunicorn stderr（进 journald），`django.request` 的 WARNING 无结构化去处。

**建议**：显式 `LOGGING`（`django.request` → WARNING 以上），配 `ADMINS` + `SERVER_EMAIL`。

### 4.4 无 CI

仓库没有 `.github/`，也没有 `pytest.ini`/`tox.ini`/`pyproject.toml`。105 个测试只能人手跑，而 `README.md:55` 还写着「本次没有运行新增功能的自动化测试」。

**建议**：加一个最小 GitHub Actions workflow（`WORKBENCH_SECRET_KEY=ci` + `python manage.py test core`），并同步修正 README 那段话。这是让「既有测试」真正产生约束的最低成本一步。

### 4.5 无反向代理示例配置

`deploy/` 只有 `install.sh` / `backup.sh` / `upgrade_accounts_only.sh`，没有 nginx 示例。而上传上限是单文件 20 MB、单次合计 40 MB（`core/models.py:29-31`），若反代未设 `client_max_body_size ≥ 40m`，用户会撞上可配置层面的 413，且报错现象容易误判为应用 bug。**建议**：补 `deploy/nginx.conf.example`（含 `client_max_body_size`、静态文件与 `X-Forwarded-Proto`）。

### 4.6 无健康检查、无定时备份

- 没有 `/healthz/` 之类探活端点，systemd/反代无法判断应用是否真的可用。
- `deploy/backup.sh` 是手动脚本，没有配套 `systemd timer` / cron；`docs/MAINTENANCE.md:84-96` 描述了备份与回滚流程，但依赖运维记得执行。

### 4.7 安全项

好消息先说：附件全部无公开 URL、逐个对象鉴权（`core/permissions.py:231-255`）；上传有扩展名与大小白名单（`core/models.py:37-56`）；文件名重写为 UUID（`core/models.py:59-61`）；`_back_to` 防开放重定向（`core/views.py:67-72`）；前端 JS **完全不用 `innerHTML`**（已 grep 确认），聊天内容走 `textContent`，无 XSS 面；`SECURE_CONTENT_TYPE_NOSNIFF`、`X_FRAME_OPTIONS=DENY`、`SESSION_COOKIE_HTTPONLY`、`SameSite=Lax` 均已设置。

仍值得补的：

1. **登录无限速**：`/login/` 无失败次数限制、无验证码、无冷却，可暴力破解。10 人内部站风险有限，但邀请码注册页同样可被刷。建议加简单 IP/用户维度失败计数（缓存即可，无需新依赖）。
2. **HTTPS 下缺 HSTS**：`WORKBENCH_HTTPS=1` 时只开了 Secure Cookie（`config/settings.py:81-82`），没有 `SECURE_HSTS_SECONDS`/`SECURE_HSTS_INCLUDE_SUBDOMAINS`/`SECURE_SSL_REDIRECT`。
3. **无 CSP**：`django-csp` 之类未接入。当前模板里有内联 `<script>`（`templates/core/base.html:3` 主题预设脚本）与 `style="width:…%"` 内联样式，接入 CSP 时需要 nonce 或 hash，属于改动量中等的加固项。
4. **公开实验附件随实验公开**：`core/portal.py:163-169` 对访客开放公开实验的全部附件下载。逻辑与文档一致（`docs/USER_GUIDE.md:117` 有醒目提示），但**发布前的检查责任全在管理员**，建议发布流程里加一次「附件清单确认」步骤，把提示从文档搬到界面上。

### 4.8 前端资源打包

`templates/core/base.html:4` 在**每一个页面**（含公开站）无条件加载 6 个样式表与 4 个脚本：

| 资源 | 大小 | 是否每页都需要 |
| --- | --- | --- |
| `site.css` | 23.2 KB | 是 |
| `portal.css` | 16.2 KB | 仅公开站 |
| `graphite.css` | 18.7 KB | 仅工作台 |
| `research.css` | 13.4 KB | 仅任务/实验页 |
| `navigation.css` | 7.1 KB | 仅工作台 |
| `shell.css` | 4.4 KB | 仅工作台 |
| `research.js` | 7.4 KB | 仅任务/实验页 |
| `site.js` | 6.4 KB | 是 |
| `chat-references.js` | 5.0 KB | 仅消息页 |
| `graphite.js` | 4.0 KB | 是 |

合计 CSS 约 83 KB、JS 约 23 KB。更好的是：**6 个样式表中 141 个选择器在多个文件里重复定义**，`site.css`/`portal.css`/`graphite.css` 三者都重定义了 `:root`、`body`、`a`、`.card`、`.button`、`th`、表单控件与 `input:focus`——目前只有「加载顺序」在保证结果正确（顺序为 site → portal → graphite → navigation → research → shell，见 `templates/core/base.html:4`）。任何一次重排都是全站视觉事故。

**建议**：(a) 按 `public` / `workbench` 两个壳拆 bundle，公开站不再加载 4 个工作台样式表；(b) 把 `:root` 变量、`.card`/`.button`/表单控件收敛到一份 base，`graphite.css` 只保留主题差异；(c) `chat-references.js`、`research.js` 按页 `{% block scripts %}` 注入。

### 4.9 可访问性

已有基础不错（`role="log" aria-live="polite"` 在 `chat.html:9`、`messages.html`、`_chat_reference_picker.html:5`；进度条用 `role="img"` + `aria-label`，如 `dashboard.html:4`；页签用 `aria-current="page"`；导航有 `aria-label`；聊天内容不用 `innerHTML`）。缺口：

1. **无「跳到主内容」skip link**（全仓 grep 为 0）。工作台左侧栏有 30 个项目分支链接，键盘/读屏用户每次换页都要 Tab 穿越导航。
2. **全局提示不是 live region**：`templates/core/base.html:27` 的 `<div class="notices">` 没有 `role="status"`/`aria-live`，而全站所有成功/失败反馈（新建、审核、报错）都走这里 → 读屏用户**感知不到操作结果**。这是最值得先修的一条。
3. **表单错误未与输入框关联**：13 个模板用 `{{ form.as_p }}`，Django 会输出 `<ul class="errorlist">`，但没有 `aria-invalid` / `aria-describedby`（全仓 `aria-describedby` grep 为 0）。
4. **未读徽标无声**：顶部未读数由 JS 更新（`static/core/research.js:50`），无 live region。
5. 8 处 `<table>` 均无 `<caption>`（有 `thead`，属次要）。
6. 主题切换按钮的 `aria-pressed` 初始恒为 `false`（`templates/core/base.html:7,25`），未随实际主题同步。

---

## 5. 值得保留的设计（评审中确认的优点）

写改进清单容易掩盖已有优点，这些建议**不要**在重构中弄丢：

- **权限集中**：所有判定在 `core/permissions.py`，且以「生效角色」而非 `user.is_staff` 为准；已实测「先选身份、越权登录被拒、降级后旧会话自动降权」都成立。
- **附件安全模型**：无公开 URL + 逐对象鉴权 + UUID 落盘 + 扩展名/大小白名单，`core/models.py:37-61`、`core/permissions.py:231-255`。这套设计比多数同类项目更严谨。
- **聊天引用只存关系、不复制正文**（`core/chat_references.py:68-74`）：无权限时连标题、金额、原 ID 都不返回，避免通过引用绕过对象权限。这个细节做得很好。
- **零新增依赖**：轮询替代 WebSocket、参数用 `JSONField`、状态用 `CharField` 常量，部署面极小（`requirements.txt` 仅 Django/gunicorn/whitenoise）。
- **诚实的文档**：`docs/USER_GUIDE.md` 明确列出「没有自动支付、银行对账、财务修改版本历史」「没有审计、没有访客统计」「未接入 GitHub 自动同步」，并提示公开附件的风险。这种「写明不做什么」比堆功能清单更有价值，建议继续保持并更新（见 1.6）。

---

## 6. 建议的迭代顺序

### 第 1 轮：修错 + 清债（低风险，1–2 天）

1. ✅ **已修：账本余额统计**——改为数据库聚合，去掉先切片再求和；并修正了随之暴露的「作废账目被计入管理员余额」问题。
2. ✅ **已修：账户设置「外观」栏已移除**。
3. ✅ **已修：文档与代码对齐**（1.6）。
4. ✅ **已做：删除不可达模块**（1.1）——4 个无路由视图、3 个死模板、1 个失效表单类与白名单项。
5. 补 `role="status"` 到全局 `.notices`；加 skip link。
6. 恢复首页「我的任务 / 最新动态」，同时消掉 1.2 的无效查询。
7. 补 `templates/404.html`、`templates/500.html`。
8. 清理仓库残留、提交 `.gitignore`（1.5）。
9. 加 `db_index` 迁移（下一个可用编号是 `0010`，`0008`/`0009` 已被占用）。
10. 决定 `Project.PAUSED`：补暂停/恢复入口，或删掉该状态（1.1b）。

### 第 2 轮：展示站成型（约 1 周）

1. `Submission.public_state` + 公开成果列表/详情 + 项目页聚合（2.1）——**这是定位上最关键的一步**。
2. meta/OG/favicon/sitemap/robots（2.4）。
3. 公开项目与实验分页、筛选、排序（2.5）。
4. 项目详情补周期/阶段/成员/成果（2.2）。
5. 图片附件缩略图（2.3 提到的权限复用）。

### 第 3 轮：管理闭环与运维（约 1–2 周）

1. ✅ **已做：项目成本核算**（3.1）——报销与账目都可关联项目、项目可设预算、项目页有成本汇总。
2. 导出 CSV（账本、任务、实验，可含项目成本）（3.3）。
3. 密码重置（或管理员生成一次性密码）（3.5）。
4. CI + `LOGGING` + `ADMINS`（4.3、4.4）。
5. nginx 示例 + `/healthz/` + 备份 timer + WAL（4.2、4.5、4.6）。
6. 前端按壳拆 bundle、收敛重复 CSS（4.8）。
7. 登录失败限速、HSTS（4.7）。

---

## 附：验证记录

评审与实际改动中执行过的验证（非静态推断）：

| 验证项 | 命令/方法 | 结果 |
| --- | --- | --- |
| Django 系统检查 | `manage.py check` | 无告警 |
| 测试套件（评审时） | `manage.py test core` | 105 个测试全部通过 |
| 测试套件（改动后） | `manage.py test core` | **175 个测试全部通过**（13.1s，新增 70 个回归用例） |
| 迁移一致性 | `makemigrations --check --dry-run` | `No changes detected`；`0008`–`0011` 已生成并应用到本地库 |
| 账本聚合正确性 | 201 条账目（1 笔早期大额收入 + 200 笔近期支出）直接查询 `aggregate(Sum(filter=...))` | 收入 10000 / 支出 200（旧写法只算到最近 200 条，收入为 0） |
| 作废账目是否计入余额 | 同一数据集分别用「不过滤作废」与「过滤作废」聚合 | 余额 `-1526` vs `-749`，确认修复前管理员余额确实被作废金额污染 |
| 项目成本汇总 | 项目关联 200+50 支出、500 收入、777 已作废，另有 999 属其他账目 | 页面显示 已用 `¥ 250.00`、收入 `¥ 500.00`、剩余 `¥ 750.00`、`已使用预算的 25%`；777 与 999 均未计入 |
| 金额显示格式 | 实际渲染 `/finance/` 与 `/finance/?tab=claims` | `¥ 4871.50` 余额、`¥ 5000.00` 收入、`¥ 128.50` 支出；报销表头含「项目」，未关联显示「未关联项目」 |
| 报销项目下拉框 | 分别以管理员、项目成员、项目外开发者渲染报销页 | 管理员看到全部项目；成员看到自己参与的项目；项目外开发者只看到「不关联项目」 |
| 死代码清理 | 全仓 grep `register_normal`/`switch_role`/`NormalUserRegisterForm`/`showcase.html`/`about.html`/`register_user` | 无任何残留引用；3 个模板文件已从磁盘删除 |
| 源文件编码 | Python 全仓 `decode('utf-8')` | 非 UTF-8 文件 0 个 |
| URL name 冲突 | 遍历 resolver 统计重名 | `login`/`logout` 与 admin 重名，但 `reverse()` 实测解析到 `/login/`、`/logout/`（core 覆盖 admin），**当前无实际故障**，仅属脆弱 |
| `exclude(member_profile__tier='normal')` | 测试库中建「无档案账号 + 普通用户」比对 | 无档案账号**未被误排除**，`core/messages.py:46`、`core/forms.py:397` 逻辑正确 |
| 不可达视图 | 全仓 grep URL name + `reverse()` 实测 | `switch_role`、`register_normal` 无路由；`showcase`/`about` 名字被 `portal` 占用 |
| 死模板 | 交叉比对 `core/*.py` 与 include/extends 引用 | 除上述 2 个视图外无孤儿模板 |
| `Project.PAUSED` 可达性 | grep `PAUSED`/`paused` + 读 `ProjectForm.fields`、`project_close` | 定义处之外**无任何写入点**，状态不可达 |
| 未使用上下文 | grep `my_tasks`/`latest_*`/`project_results`/`task_results` | 视图传入、模板未用（确认 1.2） |
| 缺失的站点基础文件 | grep `description`/`og:`/`canonical`/`favicon`/`sitemap`/`robots` | 全部为 0 |
| 错误页模板 | `templates/` 目录清点 | 无 `404.html`/`500.html` |
| 图片与 a11y 清点 | grep `<img`/`alt=`/`skip`/`aria-live`/`aria-describedby` | `<img>` 0；skip link 0；`aria-describedby` 0；`aria-live` 3 处 |
| JS XSS 面 | grep `innerHTML`/`insertAdjacentHTML`/`document.write`/`eval` | **0 处** |
| CSS 选择器重复 | 解析 6 个样式表统计同名选择器 | 141 个选择器在 >1 个文件中定义 |
| 索引缺失 | grep 迁移中的 `db_index`/`indexes` | 0 处 |
| JSONField 检索可移植性 | 实测 `Experiment.objects.filter(parameters__icontains='gpt')` + 读 Django `JSONIContains` 实现 | SQLite 上正常工作；实现是整列 `LIKE`，换 PostgreSQL 需改写 |
| 日志/CI/健康检查/nginx | grep `LOGGING`/`ADMINS`/`.github`/`healthz`/`client_max_body_size` | 全部缺失 |
| 安全设置现状 | 通读 `config/settings.py` | 已设 nosniff、X-Frame-Options、HttpOnly、SameSite、Secure Cookie（HTTPS 开关）；缺 HSTS、CSP、登录限速 |
| 附件与上传约束 | 通读 `core/models.py:23-61`、`forms.py:11-31` | 扩展名白名单、单文件 20 MB、单次 5 个/40 MB，文件名 UUID 化 |

**未做**：未在生产或反向代理环境下实测；未做性能压测；未做浏览器端人工可访问性走查（上述 a11y 结论来自模板静态清点）。
