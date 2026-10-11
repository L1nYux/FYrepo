# Windows CNKI 浏览器资料复制修复（2026-10-07）

基于 FYrepo sampling-preview `07b118ecc8d13fd4ad74b1264e8ff0b880959301`。

## 故障与处理

实际截图显示，点击采集后复制 `cnki_master_profile` 到 worker 的 `.cnki-profile` 失败，包含多条 `EdgeOptimizationGuideModels…` 与 `[WinError 3] 系统找不到指定的路径`。错误发生在启动采集浏览器之前。

此前采集和 PDF 下载均直接复制整个浏览器资料目录。Edge 的模型组件和可再生缓存不需要随登录资料复制；它们可能有深层路径、失效链接或正在变化的文件。截图无法单独确定是路径长度还是失效缓存文件，修复同时处理这两种情况。

新增共享 `integrations/browser_profile.py`：

- 在进入目录前排除 Edge 模型组件、浏览器缓存、临时锁和运行文件。
- 保留 Cookie 及 WAL、Local State、Preferences、Local Storage、IndexedDB 和 Session Storage。
- Windows 文件复制与清理使用扩展绝对路径，支持盘符路径及 UNC 路径。
- 登录资料复制失败仍停止；清理未完成的工作副本，显示简短业务错误。
- 采集与 PDF 下载都使用此方法；不修改源登录资料、候选题录、业务数据库和全文文件。

同步更新 `vendor/SAMPLE_LLM_SOURCE.json`，保留上游原始哈希及 H1 重建安装包的来源记录。活跃完整性清单现在含 23 个文件，新增复制方法也参与 SHA256 验证；wheel 与源码 ZIP 字节没有变化。

## 本地覆盖与继续验收

1. 点击“登录完成”，关闭由采集器打开的登录或采集浏览器。不要删除登录资料。
2. 在采集器终端按 Ctrl+C 停止。工作台启动窗口也按 Ctrl+C 停止。
3. 将修复 ZIP 解压到一个临时目录，把其中 `vendor`、`sampling`、`docs` 文件夹合并复制到现有 FYrepo 根目录（与 `manage.py` 同级），选择替换同名文件。保留原目录中的其他文件。
4. 双击 `START_SAMPLING_LOCAL_WINDOWS.cmd` 启动工作台，再打开采集器。在项目根目录 CMD 可执行：

```bat
tools\cnki_agent\.venv\Scripts\python.exe tools\cnki_agent\agent_server.py
```

5. 网页刷新后填入采集器显示的连接码，点击“检查连接”。完整性检查应通过；无需重建 exporter wheel。
6. 若尚未登录，重新完成“打开知网登录 → 登录完成”。选择一个并发窗口，再点击“开始采集”建立新任务。
7. 之前失败任务的日志可能仍从本机任务记录恢复；以新任务的日志和真实候选题录回传结果判断本次验收。

若上述采集器虚拟环境尚未建立，先按照 `docs/SAMPLING_LOCAL_WINDOWS.md` / `tools/cnki_agent/README.md` 安装采集器。覆盖后仅刷新网页不会重新加载采集器 Python 代码，必须重启采集器。

## 上传到同一个 PR

在 sampling-preview 分支根目录上传修复包中解压后的文件和目录，提交到原分支；不上传 ZIP 文件本身。本次没有数据库迁移。

## 验证边界

回归覆盖旧方式复制失败、新方式跳过模型目录成功、认证文件字节保留、认证文件失败时中止、已有工作副本替换、源目录保护、Windows 扩展路径构造，以及采集和 PDF 下载两个实际调用入口。

实际验证：`manage.py check` 通过；`makemigrations --check --dry-run` 无变化；`tools/verify_cnki_component.py` 验证 23 文件通过。针对性测试 26 项通过，完整 `manage.py test` 233 项通过（Linux，已安装 Web 与 Agent 两份依赖；无跳过）。

模拟文件复制故障和 Linux 回归不能代替 Windows 实机及机构登录验收。修复后应确认采集浏览器启动，并等待真实题录写回候选池。本补丁专门修复浏览器资料复制，不包含前次审查提到的损坏业务 ZIP 或长版本名修复。
