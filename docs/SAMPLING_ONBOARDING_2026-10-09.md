# Sampling main 复盘与下载流程修复（2026-10-09）

基线：main@1786462de8c22ef7da0f020817d01b247098a9f9，含知域 0.3 的个人空间与多团队体系。原 Sampling 已由 PR #7 合并，但该 main 不含 sampling-preview 后续 6a6b910（Windows 资料复制）和 58a4b32（可选依赖测试）；本轮均纳入并保留 H1 完整性校验。

## 已完成

| 问题 | 处理 |
| --- | --- |
| 页面只有 CMD 路径 | 登录页、样本库、采集与 PDF 面板提供下载和说明。完整 ZIP 包含启动文件、固定引擎、组件归档与许可证 |
| 线上工作台需手配允许域名 | 下载包写入当前请求的已校验源地址，独立启动器自动授权；本地网络访问权限由用户允许 |
| Windows 只寻找 PATH 的 python | 支持已有环境、Python Launcher、PATH 和常见 Conda，仅依赖变化或缺失时安装 |
| 未连接或未登录也能点击采集 | 依据实际连接、组件和登录状态启用按钮；进行中阻止重复操作，后端校验继续执行 |
| main 多空间，但 Sampling 全局可见 | 复用 Workspace / TeamScopedModel；读取与操作验证可访问归属，新建和导入保留所选空间；项目可空 |
| ZIP 目录合法但压缩数据损坏报 500 | PDF / 结果 ZIP 捕获 zlib.error，返回业务错误、保留输入、不写入半包数据 |
| 长版本名复制后超过字段上限 | 按字段长度生成有界名称与递增后缀，保留原冻结版本 |
| 候选池翻页丢筛选 | 保留查询条件和 candidates 标签 |
| 本地 SQLite 并发心跳返回 500 | 未读消息心跳改为按空间和用户的单次 UPSERT；保留归属校验，避免先读事务升级写锁 |

产品数据仍来自数据库或本人采集 / 上传；测试夹具仅在临时验收库中使用。

## 数据迁移

新增 sampling.0004_samplingrun_workspace。关联项目的旧样本继承项目归属；旧独立样本的创建人仍属原团队 1 时保留原团队样本库，否则归入创建人的个人空间。不推断其他团队归属。

迁移仅新增归属字段，不改候选池、编号、协议、冻结指纹、文件路径或用户项目记录。独立 SQLite 中验证原团队项目样本、原团队独立样本、个人项目样本、个人独立样本四种情况，迁移前后全部既有 sampling / core / auth 行一致（不计新增列）。

线上升级先按原流程备份并停止 Web / worker，再执行：

~~~bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check
~~~

重启 Web 与 sampling_worker。本地主启动器自动备份旧 SQLite 并迁移。若旧独立样本真实归属与上述规则不同，维护者应核对创建人与项目记录后执行正式升级。

## 本轮实际验收

Linux / Python 3.12.14，两个独立虚拟环境：

- 最新 main 根 Web requirements：完整测试 672 项，669 通过、3 项有条件跳过。
- Web + Agent 两份 requirements：同样 672 项，669 通过、3 项跳过。
- 跳过的是既有 aihub.test_render_web 三项，需 WORKBENCH_BROWSER_TESTS=1；Sampling 的 73 项全部执行。
- manage.py check 无问题，makemigrations --check --dry-run 无变化，引擎 23 文件校验通过，JS 与 Git diff 检查通过。
- 真实 HTTP / Chromium 134：未登录下载、ZIP CRC、当前地址配置、解压包标准库校验、真实登录、单一样本库导航、必填错误与首错 focus、可选项目、保存与编辑回填、真实 token / Origin 的 loopback 状态、侧栏展开 / 收起不遮挡内容、深浅色、620px 抽屉及 390px 窄屏通过，无页面 JS 异常。
- 组件 / 登录按钮的两种就绪状态另外用浏览器测试夹具校验，没有生成知网研究题录。
- 真实浏览器未出现页面 JS 或 HTTP 500；24 次并发 Sampling 页面读取 / 消息心跳全部 HTTP 200。
- 最新主启动器在已有、已核验的 Web 依赖环境中实际启动 Web + sampling_worker，未登录下载成功；中断后退出码 0。未代替首次联网安装或 Windows 原生 CMD 验收。
- 四种旧数据迁移通过，既有数据和冻结指纹保留。

测试中的未配置 SMTP 提示与模拟邮件失败是原有验收输出。尚未代替 Windows 原生 CMD 双击、本人机构认证 / 验证码、真实采集或受权限限制的全文下载。PDF 转 MD 继续使用文字层提取，不含 OCR 或自动匿名化。

## 用户本地验收

1. 完整试运行包解压到新目录；需旧账号 / 项目时，备份并复制整个旧 data 目录。
2. 停止旧工作台，双击 START_SAMPLING_LOCAL_WINDOWS.cmd，按提示建立本人账号或沿用原账号。
3. 登录页直接下载完整采集器 ZIP 并解压，双击 START_CNKI_AGENT_WINDOWS.cmd；也可运行完整源码中同名文件。
4. 登录工作台，选择样本库归属，新建真实研究样本集；关联原有项目或留空。
5. 知网采集页粘贴连接码、检查连接、安装组件，再完成本人登录并点击“登录完成”。
6. 按有权限的一本期刊、小年份范围、单窗口采集，核对真实题录与来源链接。
7. 复核、冻结后下载 / 上传匹配编号的真实 PDF，确认 worker 生成 MD 并核对转换报告。
8. 重启 Web / 采集器，检查业务数据、指纹、登录资料和全文保留。

GitHub 网页上传补丁 ZIP 解压后的文件，保持仓库根目录结构并提交新 PR；不上传完整试运行 ZIP、数据库或运行目录。实际修改清单附在文档末尾。

## 实际修改文件（相对本轮 main 基线）

共 41 个文件，包含纳入的两份后续修复。

~~~text
.gitattributes
START_CNKI_AGENT_MAC_LINUX.sh
START_CNKI_AGENT_WINDOWS.cmd
core/messages.py
core/middleware.py
core/navigation.py
core/resource_navigation.py
core/test_spaces_v3.py
docs/SAMPLING.md
docs/SAMPLING_CNKI_H1.md
docs/SAMPLING_CNKI_WINDOWS_PROFILE.md
docs/SAMPLING_LOCAL_WINDOWS.md
docs/SAMPLING_ONBOARDING_2026-10-09.md
sampling/agent_distribution.py
sampling/bundles.py
sampling/documents.py
sampling/migrations/0004_samplingrun_workspace.py
sampling/models.py
sampling/static/sampling/agent.js
sampling/static/sampling/sampling.css
sampling/templates/sampling/_agent_setup_links.html
sampling/templates/sampling/_scope_drawer.html
sampling/templates/sampling/agent_setup.html
sampling/templates/sampling/detail.html
sampling/templates/sampling/index.html
sampling/test_agent_distribution.py
sampling/test_browser_profile.py
sampling/test_cnki_component.py
sampling/test_production.py
sampling/test_runtime_regressions.py
sampling/urls.py
sampling/views.py
templates/core/login.html
tools/cnki_agent/README.md
tools/cnki_agent/run_agent_mac_linux.sh
tools/cnki_agent/run_agent_windows.cmd
tools/cnki_agent/start_agent.py
vendor/SAMPLE_LLM_SOURCE.json
vendor/sample_llm/integrations/browser_profile.py
vendor/sample_llm/integrations/cnki_external.py
vendor/sample_llm/integrations/pdf_downloader.py
~~~
