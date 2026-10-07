# CNKI 采集组件 H1 修复（2026-10-07）

## 原因与影响

PR #7 的 `sampling-preview@3130441745ffdf44f6230d16870dbb510422fcb8` 与上游 `Synex1213/sample-llm@2167aa39878bb892ba3ee90906c86d6a196d5035` 的两个组件文件字节完全相同。损坏已存在于 sample-llm 最初加入组件的提交 `997933193db58ff89d9cba085563e30f92d964fb`，并非本次网页上传、换行转换或检出造成。

旧源码 ZIP 为 15048 字节，SHA256 `cded83f11080f1bf02615fa4676fd065ff1613092622a23eb4607a2ebb537e7c`；旧 wheel 为 14997 字节，SHA256 `1731bc90a9f69e047f91af827c60095204847d9fc2682f4827a79d57047c2f66`。两者均无 ZIP 中央目录和 EOCD。wheel 第一个 `native_export.py` 条目可解压，偏移 5698 的第二条目出现 `invalid distance too far back`。原始 Git blob 同样损坏；仅凭现有记录不能进一步确定当时为什么产生这些损坏字节。

旧安装器直接将损坏 wheel 交给 pip，必然安装失败；后续采集要求组件已安装，因而主流程被阻断。旧来源清单只记录字节哈希，且未被运行代码读取：哈希一致不能证明压缩包有效。此前 FYrepo 验收覆盖了表单、抽样、回传边界与 PDF 转换，漏掉了随附组件的实际安装检查。

## 最终修复

- 从最初的 `JYao-Chen/cnki-metadata-exporter@4bdf8e108c81c4d1a0590377aec1238f534e1a18` Git 树完整重建，不从损坏 ZIP 拼装源码、不改为远程最新版本。源码 ZIP 使用 `git archive`，wheel 使用原始 `pyproject.toml` 和 Hatchling 构建；六个 Python 模块与该固定提交逐字节一致，许可证保留。
- 来源清单采用 schema 2，分别记录 `upstream_sha256` 与当前 `sha256`、本地修复标识、组件提交与 Git tree、固定构建工具。安装器真实读取清单，检查交付文件 SHA256、两个包的全条目解压 / CRC、wheel METADATA / RECORD，以及 wheel 与源码包模块一致性。
- 安装使用 `pip --no-index --no-deps --force-reinstall` 安装本地 wheel。安装后核验六个实际文件、版本，并在真实子进程中执行采集和合并入口 `--help`；缺模块或依赖时不会宣称安装成功。
- 状态接口和界面显示完整性失败原因。损坏时不启动 pip；登录和采集使用同一就绪检查，返回业务错误。
- `.gitattributes` 禁止转换 vendor 源码的换行，Windows Git checkout 也保留清单对应的原始字节。

新源码 ZIP SHA256：`10f022f6d36fc67e3e9668735ad40dca70b97ae6f6905cf60cbce8731a2335d1`。

新 wheel SHA256：`7790d55d7c9407132dae72027d29c56d1cfde5ada5d70101d4120b1d325ae70a`。

## 本轮实际验收

环境：Linux、Python 3.12.14、pip 25.0.1；安装了 Web 和 Agent 的两份 requirements。

| 检查 | 实际结果 |
| --- | --- |
| 原安装包及 Git 原始 blob | 两份均 `BadZipFile`；21 个原始来源哈希与 sample-llm 固定提交核对一致 |
| 原 wheel 的真实离线 pip 安装 | 退出码 1，pip 报 wheel 无效 |
| 新 ZIP / wheel 全条目、CRC、wheel RECORD | 通过；大小分别为 44700 / 25577 字节 |
| 新 wheel 与 exporter 原始 Git blob 比较 | 六个 Python 模块全部逐字节一致 |
| 重复构建 | 两份文件 SHA256 均完全一致 |
| 独立临时虚拟环境中的真实离线 pip 安装 | 退出码 0；包版本、安装位置和合并入口通过 |
| 实际 Agent 安装器与入口 | 安装器、采集 `--help`、登录 `--help`、合并 `--help` 通过；未访问知网 |
| 损坏包的真实 HTTP 反馈 | `/status` 返回 200 并报告错误；安装任务返回 202 后正确失败；登录返回 400；未启动 pip 或浏览器 |
| `python manage.py check` | 通过，无问题 |
| `python manage.py test` | 225 项通过，无失败或跳过，包含 H1 新增 13 项回归与既有工作台测试 |
| JS 语法 / Git diff 格式 | `node --check`、`git diff --check` 通过 |

测试时仍显示既有 `core.W001`（临时测试环境没有配置 SMTP）；邮件成功 / 失败用例均通过。Windows 实际浏览器登录、机构权限及真实知网题录采集尚未由本轮自动化完成，需按下方步骤在用户电脑验收。

## 实际修改的文件

```text
.gitattributes
.gitignore
docs/SAMPLING.md
docs/SAMPLING_CNKI_H1.md
sampling/static/sampling/agent.js
sampling/test_agent.py
sampling/test_cnki_component.py
tools/cnki_agent/README.md
tools/rebuild_cnki_package.py
tools/verify_cnki_component.py
vendor/SAMPLE_LLM_SOURCE.json
vendor/sample_llm/integrations/cnki_external.py
vendor/sample_llm/integrations/component_integrity.py
vendor/sample_llm/third_party/README.md
vendor/sample_llm/third_party/cnki-metadata-exporter-0.2.0-4bdf8e1.zip
vendor/sample_llm/third_party/cnki_metadata_exporter-0.2.0-py3-none-any.whl
```

## 开发者复现

在 FYrepo 根目录，Python 3.11+：

```bash
python -m pip install -r requirements.txt -r tools/cnki_agent/requirements.txt
python tools/verify_cnki_component.py
python manage.py check
python manage.py test sampling.test_cnki_component sampling.test_agent
python manage.py test
```

验证当前虚拟环境的实际安装，包含采集和合并入口加载；此命令不下载浏览器、不打开知网、不读取机构账号：

```bash
python tools/verify_cnki_component.py --install
```

组件归档验证与真正的 pip 安装回归始终执行。H1 的两个涉及 Playwright 的入口 / 已安装状态测试需要 Agent 依赖；只装 Web requirements 时它们会明确跳过。后续新增的 `sampling.test_browser_profile` 同样只在 PDF 下载入口一项上按 Playwright 是否安装跳过，并在该用例内部导入 `pdf_downloader`，其余 7 项照常执行。当前完整 Web 测试因此共跳过 3 项；完整采集器验收应使用上面的两份 requirements，执行全部用例。独立临时虚拟环境中的真实安装不污染用户的 Agent 环境。

仅维护者需要重建二进制：

```bash
git clone https://github.com/JYao-Chen/cnki-metadata-exporter.git ../cnki-metadata-exporter-source
python -m pip install build==1.4.0 hatchling==1.28.0
python tools/rebuild_cnki_package.py --source ../cnki-metadata-exporter-source
python tools/verify_cnki_component.py
```

脚本只从固定 Git 提交归档，忽略 checkout 中未提交修改，固定 `SOURCE_DATE_EPOCH` 并记录构建来源。

## 用户上传与本地验收

修复提交基于当前 PR #7 的 `sampling-preview@3130441`。修复 ZIP 内保持仓库根目录结构；解压后在同一分支根目录的 **Add file → Upload files** 页面上传解压后的文件及文件夹并提交。不要上传 ZIP 文件本身，不必新建 PR。本轮没有模型或数据库迁移。

请一并上传根目录的 `.gitattributes` 和 `.gitignore`；它们分别保护 vendor 字节一致性、排除本地任务与登录资料。

本地测试时先关闭旧工作台、worker 和本机采集器，将同一修复包覆盖到现有 FYrepo 根目录；保留 `data/`、虚拟环境和登录资料。重新运行 `START_SAMPLING_LOCAL_WINDOWS.cmd`，另开 `tools/cnki_agent/run_agent_windows.cmd`，在样本库填连接码并点击“检查连接 → 安装 / 修复采集组件”。这一步才会给 Agent 的独立环境安装新 wheel；仅重启网页不等于安装了采集组件。

安装成功后，本人在弹出的浏览器完成知网登录与验证码，点击“登录完成”，先选一本有权限访问的期刊与较短范围采集，再确认真实题录写入候选池。自动化验收不代替 Windows 浏览器、机构权限和真实知网采集验收。
