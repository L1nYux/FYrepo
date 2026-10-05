# 科研团队工作台

基于 Django、SQLite、Gunicorn 和 WhiteNoise，面向 2C2G Linux、前期不超过 10 人的科研团队。

## 桌面与团队服务器

桌面 0.2.16 默认连接团队服务器，支持用户名或邮箱登录。本地导航与设置直接呈现，远程内容准备好后显示。内部操作留在工作台，公开内容通过预览单独打开。提供 Windows 安装程序、macOS 双架构构建配置和自动更新入口。公开官网、网页工作台和桌面业务共用服务端账户与数据库。正式发布与现有服务器升级按 [上线交接](docs/CONNECT_AND_RELEASE.md) 进行；本版详见 [0.2.16 更新说明](docs/RELEASE_0_2_16.md)。

## 文档入口

- [功能与使用说明书](docs/USER_GUIDE.md)：页面入口、日常操作、角色权限、任务与实验的分工、聊天引用。
- [运维与升级说明](docs/MAINTENANCE.md)：安装、数据库迁移、保留数据升级、备份、排障。
- [版本交接说明](docs/INTEGRATION.md)：与主分支的关系、迁移兼容、旧版本账号导入。
- [本次更新摘要](docs/local-research-preview.md)：新版 UI、比赛、通用实验、消息及引用。
- [评审与改进路线图](docs/REVIEW-AND-ROADMAP.md)：逐项评审结论、已修问题与后续迭代顺序。

## 功能概览

| 模块 | 当前功能 |
| --- | --- |
| 公开首页 | 访客浏览已公开项目、实验及附件、成员公开资料、团队联系方式 |
| 账户 | 用户名或邮箱登录、邀请码注册开发者（需邮箱）、邮箱验证码找回或重置密码、未绑定邮箱提醒、个人资料、修改密码；成员资料库；管理员任免、停启、重置密码及交接后删除账号 |
| 公告 | 管理员发布和编辑团队公告，成员查看；支持聊天引用 |
| 项目与任务 | 项目 → 母任务 → 子任务；指定负责人及多名成员；可选项目预算与成本汇总；留言、提交、审核、结项、删除与恢复 |
| 任务类型 | 实验设计、实验过程、结果分析、其他事务；可选关联比赛 |
| 成果 | 纯文字、附件、源码链接、实验记录引用；可在提交时同时创建实验记录 |
| 比赛 | 负责人、DDL、要求、关联任务、选用参赛成果、归档与恢复 |
| 实验库 | 通用实验记录、自定义参数、参数模板、附件、搜索、我的记录、2–3 条对照、公开审核 |
| 财务 | 开发者共享团队账本与报销申请；成员提交报销及凭证，可关联项目；管理员审核入账、直接记账、作废、移入回收站、恢复及确认后彻底删除 |
| 消息 | 独立消息区、公共讨论、成员私聊、附件、未读提示；「＋」引用任务、实验、财务及公告；右键复制、撤回本人消息、从本人记录删除；撤回提示旁可重新编辑，无倒计时 |

工作台采用中性灰配色，顶部切换工作台与消息；账户设置在右上角菜单。访客使用独立的浅色公开页面。

## 本地启动

在 `manage.py` 所在目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:WORKBENCH_SECRET_KEY = 'replace-with-a-random-local-secret'
$env:WORKBENCH_DEBUG = '1'
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

打开 `http://127.0.0.1:8000/`，在右上角登录。管理员先建立项目、分配成员、生成邀请码。首次运行为空库，不自动填充示例项目或实验。

Linux 使用 `.venv/bin/python` 与 `export` 设置环境变量。默认数据目录为 `data/`，可用 `WORKBENCH_DATA_DIR` 指定。`.env` 不会由 Django 自动读取，需由 shell 或 systemd 加载。

## 部署与更新

首次安装可使用 `sudo bash deploy/install.sh`。安装脚本默认只监听 `127.0.0.1:8000`；公网反向代理沿用运维配置。完整步骤见 [运维说明](docs/MAINTENANCE.md)。

0.2.16 的 core 迁移已到 `0023_member_account_lifecycle`，aihub 已到 `0014_budgetweek_base_limit_recorded_and_more`。已有兼容迁移链的数据库，备份后运行 `migrate` 保留账号与业务数据，随后 `collectstatic` 和重启服务。

`0010` 是「邮箱自助找回密码」的前置整理：把已有邮箱统一转小写，并给非空邮箱加唯一索引。**如果现有账号里存在重复邮箱，`migrate` 会报错停下并列出冲突的邮箱**（哪个账号该保留需要人工判断，迁移不替你做决定）；处理完再重新运行即可。

`0014` 在 auth 迁移完成后恢复邮箱唯一索引，避免 SQLite 重建用户表时丢失约束；非空邮箱忽略大小写和两端空格。发现冲突会停止升级，不会自动删除或合并账户。

生产环境还要配置 SMTP，否则成员点「忘记密码」会失败：复制 `.env.example` 里的 `WORKBENCH_EMAIL_*` 到服务器环境配置，`manage.py check` 会提示 `core.W001`。

仓库自带 Django、Node、SQLite 并发和 Electron 界面测试。0.2.16 包含 454 个 Django、51 个 Node、5 个并发用例及 11 套 Electron 界面检查，Linux 与 Windows 都是发布前置检查。运行方式见 [测试说明](docs/TESTING.md)，Linux 与 Windows 均执行完整检查。AI 测试使用模拟结果，不产生真实调用费用。自动化检查不代替真实厂商连接验收。

`deploy/upgrade_accounts_only.sh` 是另一种升级方式：新建空业务库，只导入旧账号与密码摘要。仅在明确决定丢弃旧业务数据时使用，详见交接说明。

源码仓库不包含生产数据库、上传文件、账号密码、真实密钥及备份。本版未在生产服务器部署；功能验收由团队完成。

## 本地合并：公共 API 池与助手

基于 GitHub main `c9d518a` 合并桌面版与简化流程，新增公共 API 池、多厂商模型选择、成员费用计量、历史价格和只读工作台助手。AI 助手使用独立对话侧栏，按账户保存历史，支持搜索、重命名和删除。见 [配置与使用说明](docs/API_POOL_AND_ASSISTANT.md)、[桌面版说明](desktop/README.md) 和 [运维交接摘要](docs/INTEGRATION.md)。本版提交至独立审阅分支，尚未部署生产服务器。
# 0.2.3 更新

浅色设置导航与加载反馈已修正。成员共用统一的每周 Plan（100 点 = ¥1），负责人可向全员或指定成员发放跨周保留的额外点数。无个人 Plan 调整入口。规则与升级说明见 [点数说明](docs/PLAN_POINTS.md)。生产 SMTP 沿用原服务器配置。

助手 UUID 和重试标识保持原值；aihub.0013 以独立的创建序号处理相同时间戳，迁移为旧记录补序号。重试只恢复原消息之前的上下文，同时间戳的后续消息不混入。
