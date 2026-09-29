# 科研团队工作台 · 第一版

这是一套独立于旧 `index.html` 原型的真实服务端程序。第一版包含：

- 管理员创建、撤销一次性开发者邀请码；开发者使用账户名、密码、邀请码注册。
- 管理员发布、编辑、归档任务；所有登录成员查看进度；被分配的开发者更新进度、上传成果；管理员审核结项或退回。
- 管理员记账、上传财务凭证、编辑和作废记录。
- 操作日志；成果与凭证文件不提供公开文件 URL，下载时检查权限。

没有预置虚构任务或财务记录。初始管理员由你在服务器上创建。

## 连接服务器前

1. 保留本目录的完整文件，不要只上传 HTML。服务器镜像为 Ubuntu 24.04。
2. 准备服务器公网 IP，并在阿里云轻量应用服务器控制台确认实例运行中。
3. 准备阿里云控制台登录。Workbench 一键连接进入的是 `admin` 用户，随后可用 `sudo -i` 获得 root 权限。
4. 当前安装脚本只让程序监听服务器本机 `127.0.0.1:8000`，不修改云防火墙，也不对外开放网页端口。

## 上传与安装

在阿里云控制台点击 **远程连接 → Workbench 一键连接**。左侧 **文件管理**进入 `/home/admin`，上传 `research-workbench.tar.gz`。

在 Workbench 终端执行：

```bash
sudo -i
mkdir -p /opt/research-workbench
tar -xzf /home/admin/research-workbench.tar.gz -C /opt
cd /opt/research-workbench
bash deploy/install.sh
```

安装完成后，创建第一个管理员。按提示自行输入账户名和密码，不要把密码发给别人：

```bash
runuser -u workbench -- bash -c 'set -a; source /etc/research-workbench.env; set +a; exec /opt/research-workbench/.venv/bin/python /opt/research-workbench/manage.py createsuperuser'
```

检查进程状态：

```bash
systemctl status research-workbench --no-pager
```

## 从自己的 Windows 电脑访问

先在阿里云控制台给服务器设置 root 密码。在 Windows PowerShell 中运行，把占位符换成实际公网 IP：

```powershell
ssh -N -L 8765:127.0.0.1:8000 root@<服务器公网IP>
```

SSH 窗口保持打开，然后在本机浏览器访问 `http://127.0.0.1:8765/`。首次用管理员账号登录，进入“邀请码”生成开发者邀请码。管理员的账户管理入口在页面导航中。

此方式适合安装后的首次验收。给团队长期使用时，应单独确定网络接入方式；不要给成员共享 root 密码。

## 数据与维护

- 数据库：`/var/lib/research-workbench/workbench.sqlite3`
- 私有上传目录：`/var/lib/research-workbench/private_uploads`
- 环境密钥：`/etc/research-workbench.env`，安装时随机生成，不能丢失。
- 服务日志：`journalctl -u research-workbench -n 100 --no-pager`
- 手动备份：`sudo bash /opt/research-workbench/deploy/backup.sh`。备份会放在 `/var/backups/research-workbench/`；还需定期下载到服务器之外。

## 当前限制

- 这是第一版核心流程；实验/GitHub 集成、公开展示、聊天室均未包含。
- 每个任务当前只有一名负责人；需要多人共同提交时需扩展分配模型。
- 上传限制为 TXT、PDF、DOC、DOCX、XLS、XLSX，单文件 20 MB；仅检查扩展名与大小，不提供文件杀毒。只给可信团队成员发邀请码。
- 数据库和文件都在同一台服务器；正式长期使用前必须落实服务器外备份。
- 安装脚本没有配置公网 Nginx、域名或 HTTPS。财务凭证不应通过明文公网 HTTP 传输。
