# 科研团队工作台

基于 Django、SQLite、Gunicorn 的轻量团队工作台，面向 2C2G Linux、小于 10 人的科研团队。

## 合并版功能

- 访客公开首页；登录与邀请码注册弹窗；管理员和开发者共用导航，操作按账号权限开放。
- 公告栏、项目管理、实验库、团队财务、个人信息和密码修改；保留聊天室和深色模式。
- 项目 → 母任务 → 子任务，多人协作，留言、成果提交和审核集中在任务页。
- 成果支持文字、多附件、源码链接及实验记录引用；不要求上传附件。
- 子任务可自主结项；母任务由项目负责人审核；项目最终结项、财务及人事由管理员主管。
- 财务账本对全体开发者可见，成员申请报销，管理员审核入账。
- 实验库保存实验条件、数据来源编号、结果、人工评价和 Git 版本；API 密钥不得写入记录或附件。
- 项目摘要、实验公开由管理员把关；成员自行选择公开资料；管理员填写团队邮箱和电话。
- 项目和任务可以删除并从回收站恢复。删除项目或母任务会隐藏整个下级分支。

完整权限、数据库兼容与升级说明见 [合并版交接](docs/INTEGRATION.md)。已有普通用户保持原受限权限，普通用户自由注册与手动身份切换已关闭。

## 本地启动

Windows PowerShell，在 manage.py 所在目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:WORKBENCH_SECRET_KEY = 'replace-with-a-random-local-secret'
$env:WORKBENCH_DEBUG = '1'
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Linux 使用 `.venv/bin/python`，环境变量通过 `export` 设置。默认数据库和附件位于 `data/`，不会进入 Git。首次使用没有项目或实验示例数据。

## 验证与部署

```bash
python manage.py test core
python manage.py makemigrations --check --dry-run
```

首次安装使用 `sudo bash deploy/install.sh`。生产静态文件需要 `python manage.py collectstatic --noinput`。

源码合并沿用 GitHub 的迁移链；旧本地版本的迁移不能直接混入。仅保留旧账号的服务器更新使用 `deploy/upgrade_accounts_only.sh`，步骤及限制见 [合并版交接](docs/INTEGRATION.md)。

源码仓库不包含生产数据库、附件、凭证、密钥和备份。部署脚本不会自动配置 Nginx 或 HTTPS；既有服务器接入配置由运维继续维护。
