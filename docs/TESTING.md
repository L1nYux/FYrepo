# 自动化检查

当前团队分层与网页读取开发分支：Django 516 项、Node 51 项、SQLite 积分并发 5 项和 13 套 Electron 界面检查，另有团队准入并发、旧数据库迁移与本地桌面认证隔离检查。以后数量以同版本 CI 输出为准。

安装 requirements.txt 和 desktop 的 npm 依赖后运行：

```text
python manage.py test core aihub --noinput
python tools/check_point_gift_concurrency.py
python tools/check_team_admission_concurrency.py
python tools/check_team_migration.py
python tools/check_desktop_team_auth.py
node --test desktop/tests/*.test.cjs
```

界面检查必须先设置 `WORKBENCH_CAPTURE_UI` 为仓库里的 `.test-scratch/render-pages`，再运行 Django 测试生成页面。随后逐个用 Electron 运行 desktop/tests 下的十三个 `*-smoke.cjs`。Linux 需要 xvfb。fixtures 由当前服务端模板生成，不提交过期 HTML。

tests.yml 在 Linux、Windows 执行以上全部检查；失败日志与截图作为 CI artifacts 保存。不要用 `continue-on-error` 掩盖失败。构建发布前必须通过同版本检查。

公开网站连通性使用 `python tools/check_public_web.py` 单独检查；可能受代理、DNS、站点限流影响，不替代固定 fixture 的功能回归。CI public-web.yml 保留这一检查的结果。

真实浏览器回归需要先安装 Chromium：`python -m playwright install chromium`（Linux 加 `--with-deps`），并设置 `WORKBENCH_BROWSER_TESTS=1`。这不会调用付费 AI 模型。Chromium 沙盒始终开启。CI 同时安装并执行这组回归，不以跳过浏览器测试冒充通过。
