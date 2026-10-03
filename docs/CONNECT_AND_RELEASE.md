# 官网、网页工作台与桌面上线交接

## 交付关系

- `/` 是公开官网；项目、实验和成员仍按既有公开权限展示。内部任务、财务和聊天不因登录桌面而变成公开内容。
- `/workspace/` 是网页工作台，未登录会先登录，成功后按账户角色进入工作区。
- `/download/` 是桌面下载页；安装版连接同一台服务器。账户密码、邀请码、业务数据、AI 对话及 API 成本只有一份服务端来源。
- 安装版、源码正常启动和快捷方式默认连接 `http://47.117.89.248`，成员直接登录，不选择模式、不填写地址。开发命令 `npm run dev:local` 单独启动测试后端，**不会上传本地数据库覆盖线上账户**。
- 安装版不自带 Python 或第二个业务后端；不必给成员 SSH。需要 Git 的成员在自己的电脑安装 Git 并使用自己的远程认证。

## 先准备，服务器操作另行进行

当前源码和安装包构建可以提前完成。以下实际服务器步骤需要负责人登录服务器后操作，不能声称已部署：

1. 确认线上服务、数据和环境文件的真实路径；默认 `/etc/research-workbench.env`、`/var/lib/research-workbench/workbench.sqlite3`、`research-workbench.service`。已有站点的反向代理配置保持其实际域名和证书。
2. 把批准的源码解压到独立目录，不要先覆盖正在运行的旧代码，不带预览数据库和 API Key。
3. 执行 `sudo bash deploy/upgrade_preserve_data.sh --prepare`：建立独立版本目录和 Python 环境，在旧数据库的 SQLite 备份副本上运行完整迁移，收集静态资源。不会停止或更新线上服务。
4. 确认准备结果后执行 `sudo bash deploy/upgrade_preserve_data.sh --apply`。它重新准备、停止网站及价格刷新任务、备份最新数据库 / 数据目录 / 环境与服务配置，再执行迁移、通过 systemd drop-in 切换代码和 Python 环境。数据目录与 `SECRET_KEY` 保持原值。失败时尝试恢复旧数据库与服务配置。
5. 本脚本适用于当前仓库迁移链及标准 `workbench` 系统用户、8000 回环端口的部署。数据库迁移冲突或重复邮箱会停止准备，需要处理后重跑，不能盲目 `--fake`。原始旧代码仍在原位置；生效代码在 `/opt/research-workbench-releases/<时间>/`，之后升级仍使用该脚本，避免误改不再运行的旧目录。
6. 在原 Nginx 配置中加入桌面认证接口的限流。示例 `deploy/nginx-workbench.example.conf` 需按真实域名合入并检查 Nginx 配置后重载。默认 Python 节流是短期进程内缓存，**跨 Gunicorn workers 的限流由 Nginx 完成**。
7. HTTPS 使用有效证书；环境设置 `WORKBENCH_HTTPS=1`、`WORKBENCH_TRUST_PROXY=1`，允许域名加入 `WORKBENCH_ALLOWED_HOSTS`。客户端 CSRF 的 Origin / Referer 使用配置的同一服务器，不需要放开跨域或设置 `CSRF_TRUSTED_ORIGINS=*`。当前部署方指定的默认地址是 HTTP；修改到其他 HTTP 地址时客户端提示明文传输风险。客户端不会关闭 TLS 校验。
8. 升级后桌面自动连接预设服务器，用原有账户登录；网页与桌面手动查看同一个任务和消息，确认数据一致。管理员检查成员、财务和 API 池所有权。真实联调需目标服务器升级后完成。

该脚本保留全部业务数据，区别于旧 `upgrade_accounts_only.sh` 的仅账号导入。以后应优先使用保留数据脚本。备份含凭证和密钥，只存服务器，不提交 GitHub。每日价格刷新仍使用服务端定时任务；若旧服务器没有 timer，按现有部署说明安装并确认对应版本路径。

## Windows 和 macOS 安装包

- `desktop/package.json` 固定版本 `0.2.2`，依赖由锁文件安装。
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

证书配置完毕后，版本更新 `desktop/package.json` 与锁文件，批准对应提交，再推送匹配的 `v0.2.2` 类标签。标签构建强制检查 Apple 签名 / 公证凭证；两端成功后自动生成 **GitHub Release 草稿**，包含安装文件和更新清单。确认服务器兼容与安装包后由负责人发布草稿。后续版本必须递增，更新器不自动降级、不获取草稿或预发布版本。

公开下载后设置服务器 `WORKBENCH_DESKTOP_RELEASE=0.2.2` 并重启，使官网下载页显示对应正式资产。未设置时只链接 GitHub 发布页，不假装已有可下载版本。公开发布库不得混入服务器配置、个人 API Key 或预览数据。

## 自动更新与会话

安装版启动后及每 4 小时自动检查正式 GitHub Release；发现新版本自动下载，SHA-512 / 平台签名校验交由 electron-updater，保留默认校验。用户在设置 → 关于与更新选择安装，需先保存网页草稿和本地编辑，才重启。不会自动更新服务器或迁移线上数据库。macOS 自动更新要求实际 Developer ID 签名；未签名预览显示手动更新说明。

连接地址保存在本机 `server-connection.json`；登录使用 Electron 独立、持久 cookie session。勾选保持登录时是 30 天服务器会话，不保存明文密码。退出、服务器停用账户、改密码导致会话失效时需重新登录。安装版只在线访问；不支持业务离线写入或双向数据库同步。

## 本轮检查边界

已执行 JavaScript / Python 语法检查及 Windows 安装构建。没有新加或执行功能测试、截图验收；2026-10-04 负责人已执行生产升级，脚本报告保留数据成功，公网桌面状态接口返回 protocol=1。成员真实账户登录、Mac 安装运行和跨版本更新仍需对应环境。构建依赖的 npm 审计存在间接下载库告警，本次 `npm audit --omit=dev` 的生产运行依赖告警为 0；升级打包工具时继续关注上游修复，不用强制降级造成更多告警。

官方说明：[electron-builder 自动更新](https://www.electron.build/v26/docs/features/auto-update/)、[安全与签名](https://www.electron.build/docs/features/security/)。

## 0.2.2 修复与部署说明

- 保留已发布的完整迁移名称与 0012 合并链，新增 core.0015_repair_legacy_schema 和 0016_chat_unread_indexes，以及 aihub.0005_history_and_rate_limits。迁移定点操作用完整名称，禁止仅使用歧义的 0008 前缀。修复仅补缺失表或字段；遇到残缺表/账户约束会停止，不删除重建用户数据。
- 升级脚本在备份副本的任何迁移前检查重复邮箱（按 Python strip/lower 规则）和 SQLite quick_check；停止写入并备份最新数据后再检查一次，避免准备期间的新冲突。SQLite 只保证单个迁移事务回滚，已完成的更早迁移仍存在；正式升级失败沿用全数据库备份恢复。不要改名已应用迁移，也不要使用 --fake 掩盖缺失结构。
- 普通客户端和正常源码启动使用系统 appData/ResearchWorkbench/client；开发命令 npm run dev:local 使用仓库 desktop/.local。WORKBENCH_DESKTOP_STATE 是开发/运维明确覆盖路径，不是成员配置项。旧源码配置只复制到新路径缺失的偏好文件，不移动旧库和上游密钥，也不自动覆盖已有新配置。
- 摄像头、麦克风、定位、通知、网页剪贴板与设备权限默认拒绝；原生菜单复制粘贴不依赖网页权限。
- 回收站永久删除先显示任务、成果、留言和附件引用数量及清单；未归档任务阻止直接清除，可先明确将所含任务移入回收站。签名确认有效 10 分钟，提交时重新计算内容范围；变化后需重新查看。独立实验、财务和用量账目保留，不新增日常操作审计。
- 管理页加载或切换连接不调用厂商。读取模型是显式 POST，方案及 Key 暂存服务端 0700/0600 私有目录、15 分钟有效，确认后才保存正式配置；客户端票据不携带 Key。确认后删除临时文件，过期文件在下次读取及每日维护清理。
- 未读计数由 SQL 分组完成，同请求复用结果；桌面将同一轮未读/在线状态推送嵌入页，避免两套周期查询。
- Bearer 仅支持 /api/pool/v1/，访问受保护网页端点时返回 401 JSON，不能把令牌扩展成网页登录权限。会话 JSON 接口失效返回 401、权限不足返回 403。共享数据库短期计数器按令牌 30 请求/分钟、2 并发，按账号 60 请求/分钟、3 并发；超限返回 429 与 Retry-After:60。租约崩溃恢复上限 5 分钟，空闲计数 10 分钟过期，无请求正文和操作历史。未知/无效凭证的 IP 限速须合入现有 Nginx，示例不会自动覆盖实际配置。
- AI 对话默认由本人自行删除，可选 7/30/90 天按最后使用时间自动清理，并可清空全部对话；执行中对话不可删除，费用账目永不随对话清理。服务器需启用现有 research-workbench-prices.timer（包含清理），否则仅个人更新保留设置/发起助手时清理。
- 提交成果默认不改变任务状态；只有显式 submission_action=finish 才结项或送审核，无 JavaScript 也相同。旧 finish 参数不再隐式触发结项。

连接排查：在服务器执行 sudo bash deploy/diagnose_connection.sh，输出本地 Gunicorn、Nginx HTTP 状态与监听端口，不输出环境 Key、密码或业务数据。两处 200 而外网失败时继续查云防火墙/外网链路；服务器入口正常而仅客户端失败时按显示的代理/证书/超时错误处理，不关闭 TLS 校验。

本轮仅做编译、模板和框架配置检查及安装包构建；没有运行功能测试套件、付费模型调用或截图验收。生产更新和真实客户端登录仍需负责人执行与确认。

客户端遇到网络中断或 502/503/504 会自动重试最多 3 次，每次最多 8 秒；证书错误不重试、不忽略校验。当前公网检查可返回 200，先前空响应属于尚未定位的间歇失败，未把它归因于代理。
