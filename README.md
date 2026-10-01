# 科研团队工作台

基于 Django、SQLite、Gunicorn 和 WhiteNoise，面向 2C2G Linux、前期不超过 10 人的科研团队。

## 文档入口

- [功能与使用说明书](docs/USER_GUIDE.md)：页面入口、日常操作、角色权限、任务与实验的分工、聊天引用。
- [运维与升级说明](docs/MAINTENANCE.md)：安装、数据库迁移、保留数据升级、备份、排障。
- [版本交接说明](docs/INTEGRATION.md)：与主分支的关系、迁移兼容、旧版本账号导入。
- [本次更新摘要](docs/local-research-preview.md)：新版 UI、比赛、通用实验、消息及引用。

## 功能概览

| 模块 | 当前功能 |
| --- | --- |
| 公开首页 | 访客浏览已公开项目、实验及附件、成员公开资料、团队联系方式 |
| 账户 | 统一登录、邀请码注册开发者、个人资料、修改密码、外观设置；管理员任免及停启账号 |
| 公告 | 管理员发布和编辑团队公告，成员查看；支持聊天引用 |
| 项目与任务 | 项目 → 母任务 → 子任务；指定负责人及多名成员；留言、提交、审核、结项、删除与恢复 |
| 任务类型 | 实验设计、实验过程、结果分析、其他事务；可选关联比赛 |
| 成果 | 纯文字、附件、源码链接、实验记录引用；可在提交时同时创建实验记录 |
| 比赛 | 负责人、DDL、要求、关联任务、选用参赛成果、归档与恢复 |
| 实验库 | 通用实验记录、自定义参数、参数模板、附件、搜索、我的记录、2–3 条对照、公开审核 |
| 财务 | 开发者共享团队账本；成员提交报销及凭证；管理员审核入账、直接记账及作废 |
| 消息 | 独立消息区、公共讨论、成员私聊、附件、未读提示；「＋」引用任务、实验、财务及公告 |

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

本版数据库迁移链为 `0001` 至 `0007`。已有同一迁移链的数据库，备份后运行 `migrate` 保留账号与业务数据，随后 `collectstatic` 和重启服务。

`deploy/upgrade_accounts_only.sh` 是另一种升级方式：新建空业务库，只导入旧账号与密码摘要。仅在明确决定丢弃旧业务数据时使用，详见交接说明。

源码仓库不包含生产数据库、上传文件、账号密码、真实密钥及备份。本版未在生产服务器部署；功能验收由团队完成。本次没有运行新增功能的自动化测试，仓库既有测试不代表新版已验收。
