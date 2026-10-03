# 官网、网页工作台与桌面上线交接

## 交付关系

- `/` 是公开官网；项目、实验和成员仍按既有公开权限展示。内部任务、财务和聊天不因登录桌面而变成公开内容。
- `/workspace/` 是网页工作台，未登录会先登录，成功后按账户角色进入工作区。
- `/download/` 是桌面下载页；安装版连接同一台服务器。账户密码、邀请码、业务数据、AI 对话及 API 成本只有一份服务端来源。
- 本地预览仍保留，数据独立。切换到服务器只改变连接，**不会上传本地数据库覆盖线上账户**。
- 安装版不自带 Python 或第二个业务后端；不必给成员 SSH。需要 Git 的成员在自己的电脑安装 Git 并使用自己的远程认证。

## 先准备，服务器操作另行进行

当前源码和安装包构建可以提前完成。以下实际服务器步骤需要负责人登录服务器后操作，不能声称已部署：

1. 确认线上服务、数据和环境文件的真实路径；默认 `/etc/research-workbench.env`、`/var/lib/research-workbench/workbench.sqlite3`、`research-workbench.service`。已有站点的反向代理配置保持其实际域名和证书。
2. 把批准的源码解压到独立目录，不要先覆盖正在运行的旧代码，不带预览数据库和 API Key。
3. 执行 `sudo bash deploy/upgrade_preserve_data.sh --prepare`：建立独立版本目录和 Python 环境，在旧数据库的 SQLite 备份副本上运行完整迁移，收集静态资源。不会停止或更新线上服务。
4. 确认准备结果后执行 `sudo bash deploy/upgrade_preserve_data.sh --apply`。它重新准备、停止网站及价格刷新任务、备份最新数据库 / 数据目录 / 环境与服务配置，再执行迁移、通过 systemd drop-in 切换代码和 Python 环境。数据目录与 `SECRET_KEY` 保持原值。失败时尝试恢复旧数据库与服务配置。
5. 本脚本适用于当前仓库迁移链及标准 `workbench` 系统用户、8000 回环端口的部署。数据库迁移冲突或重复邮箱会停止准备，需要处理后重跑，不能盲目 `--fake`。原始旧代码仍在原位置；生效代码在 `/opt/research-workbench-releases/<时间>/`，之后升级仍使用该脚本，避免误改不再运行的旧目录。
6. 在原 Nginx 配置中加入桌面认证接口的限流。示例 `deploy/nginx-workbench.example.conf` 需按真实域名合入并检查 Nginx 配置后重载。默认 Python 节流是短期进程内缓存，**跨 Gunicorn workers 的限流由 Nginx 完成**。
7. HTTPS 使用有效证书；环境设置 `WORKBENCH_HTTPS=1`、`WORKBENCH_TRUST_PROXY=1`，允许域名加入 `WORKBENCH_ALLOWED_HOSTS`。客户端 CSRF 的 Origin / Referer 使用配置的同一服务器，不需要放开跨域或设置 `CSRF_TRUSTED_ORIGINS=*`。HTTP 仅供明确确认的临时连接；客户端不会关闭 TLS 校验。
8. 升级后在桌面登录页填服务器网址，用原有账户登录；网页与桌面手动查看同一个任务和消息，确认数据一致。管理员检查成员、财务和 API 池所有权。真实联调需目标服务器升级后完成。

该脚本保留全部业务数据，区别于旧 `upgrade_accounts_only.sh` 的仅账号导入。以后应优先使用保留数据脚本。备份含凭证和密钥，只存服务器，不提交 GitHub。每日价格刷新仍使用服务端定时任务；若旧服务器没有 timer，按现有部署说明安装并确认对应版本路径。

## Windows 和 macOS 安装包

- `desktop/package.json` 固定版本 `0.2.0`，依赖由锁文件安装。
- Windows：`cd desktop` → `npm ci` → `npm run dist:win`，生成 `.exe`、`.blockmap` 和 `latest.yml`。安装程序创建桌面 / 开始菜单快捷方式，卸载不删除账户会话与本机主题配置。
- macOS：在 Mac 上 `npm ci` → `npm run dist:mac`，生成 Intel / Apple 芯片各自的 DMG、ZIP 和 `latest-mac.yml`。不能在 Windows 上声称已验证 Mac 运行。
- 打包文件使用显式清单；数据库、`.env`、上传、备份、开发 Python、旧连接密钥都不进入安装包。安装版状态在系统应用数据目录 `ResearchWorkbench`，用户按自己账户登录。
- `.github/workflows/desktop-build.yml` 在分支 push / 手动触发时构建两种系统。分支的无证书 Mac 构建只作预览，自动更新关闭；未签名软件可能被 Gatekeeper 阻止。

## 正式签名与发布

仓库 Settings → Secrets and variables → Actions 配置，**不要通过聊天或仓库文件传私钥 / 密码**：

| Secret | 用途 |
| --- | --- |
| `MAC_CSC_LINK` | Developer ID Application 的 `.p12` 证书（base64 或受保护下载地址） |
| `MAC_CSC_KEY_PASSWORD` | 证书密码 |
| `APPLE_ID` | 公证 Apple 账号 |
| `APPLE_APP_SPECIFIC_PASSWORD` | Apple 应用专用密码 |
| `APPLE_TEAM_ID` | Apple 开发者团队 ID |
| `WIN_CSC_LINK` / `WIN_CSC_KEY_PASSWORD` | Windows 签名证书和密码，可选；未配置会出现未验证发布者提示 |

证书配置完毕后，版本更新 `desktop/package.json` 与锁文件，批准对应提交，再推送匹配的 `v0.2.0` 类标签。标签构建强制检查 Apple 签名 / 公证凭证；两端成功后自动生成 **GitHub Release 草稿**，包含安装文件和更新清单。确认服务器兼容与安装包后由负责人发布草稿。后续版本必须递增，更新器不自动降级、不获取草稿或预发布版本。

公开下载后设置服务器 `WORKBENCH_DESKTOP_RELEASE=0.2.0` 并重启，使官网下载页显示对应正式资产。未设置时只链接 GitHub 发布页，不假装已有可下载版本。公开发布库不得混入服务器配置、个人 API Key 或预览数据。

## 自动更新与会话

安装版启动后及每 4 小时自动检查正式 GitHub Release；发现新版本自动下载，SHA-512 / 平台签名校验交由 electron-updater，保留默认校验。用户在设置 → 关于与更新选择安装，需先保存网页草稿和本地编辑，才重启。不会自动更新服务器或迁移线上数据库。macOS 自动更新要求实际 Developer ID 签名；未签名预览显示手动更新说明。

连接地址保存在本机 `server-connection.json`；登录使用 Electron 独立、持久 cookie session。勾选保持登录时是 30 天服务器会话，不保存明文密码。退出、服务器停用账户、改密码导致会话失效时需重新登录。安装版只在线访问；不支持业务离线写入或双向数据库同步。

## 本轮检查边界

已执行 JavaScript / Python 语法检查及 Windows 安装构建。没有新加或执行功能测试、截图验收；真实服务器连接、生产升级、Mac 安装运行、跨版本更新仍需对应环境。构建依赖的 npm 审计存在间接下载库告警，本次 `npm audit --omit=dev` 的生产运行依赖告警为 0；升级打包工具时继续关注上游修复，不用强制降级造成更多告警。

官方说明：[electron-builder 自动更新](https://www.electron.build/v26/docs/features/auto-update/)、[安全与签名](https://www.electron.build/docs/features/security/)。
