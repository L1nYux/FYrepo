# 本机知网采集器 v2

需要 Python 3.11+。完整 FYrepo 已包含固定版本采集引擎，无需另行克隆 sample-llm。
引擎来源：`Synex1213/sample-llm`，提交 `2167aa39878bb892ba3ee90906c86d6a196d5035`。H1 修复从原始 exporter 提交重建两份损坏的安装包，并对安装适配器增加完整性校验；采集、登录、PDF 下载和抽样算法继续复用原引擎。原始哈希、本地修改和构建来源见 `vendor/SAMPLE_LLM_SOURCE.json`，许可证见 `vendor/sample_llm/`。

从登录页、样本库或知网采集面板下载完整采集器 ZIP 并全部解压；也可使用完整 FYrepo 源码中的采集器。

Windows：双击包根目录的 START_CNKI_AGENT_WINDOWS.cmd，或此目录的 run_agent_windows.cmd。启动器寻找已有环境、Python Launcher / PATH 和常见 Conda 的 Python 3.11+。macOS / Linux：在根目录执行 bash START_CNKI_AGENT_MAC_LINUX.sh。

首次建立独立环境并联网安装依赖；后续仅依赖变化或缺失时安装。窗口显示连接码，粘贴回工作台并保持窗口打开。连接码保留本机，不上传工作台。

默认允许 http://127.0.0.1:8000 和 http://localhost:8000。网页下载包自动将当前源地址写入 workbench_origin.json；用新启动器运行时自动授权。完整源码运行或要额外授权时，可添加**准确源地址**（无路径）：

```bat
set SAMPLING_WORKBENCH_ORIGINS=https://你的工作台域名
run_agent_windows.cmd
```

```bash
SAMPLING_WORKBENCH_ORIGINS=https://你的工作台域名 bash run_agent_mac_linux.sh
```

也可直接运行 `python agent_server.py --allow-origin https://你的工作台域名`。仅监听 `127.0.0.1:8765`。现代浏览器询问本地网络访问权限时，需允许当前工作台访问本机。HTTPS→loopback 的权限策略需要在实际使用的浏览器和域名上验收。

1. 点击“检查连接”；缺少组件时点击“安装 / 修复采集组件”。组件固定为随包附带的 `cnki-metadata-exporter 0.2.0`。安装前会校验来源清单、SHA256、压缩包 CRC、wheel RECORD 和源码一致性；损坏时显示具体错误并停止，不调用 pip。正常组件通过本地 wheel 离线安装；Agent Python 依赖及缺少的浏览器仍可能需要联网安装。
2. 点击“打开知网登录”；本人在本机浏览器完成机构登录和验证码，再点击“登录完成”。
3. “开始采集”按真实抽样框采集，支持按年分片、1–3 个窗口和上游批次续采。同一样本集、范围保持独立工作目录。
4. 采集完成后浏览器分批回传题录。工作台范围已变更时，旧任务被拒绝，不写入新候选池。
5. 冻结后下载主样本和留出样本 PDF。有效 PDF 由浏览器上传工作台并进入转换队列；没有权限或下载失败的论文保留人工下载入口。
6. 中断 / 关闭工作台后重新填写连接码并检查连接，可恢复任务轮询。回传失败可点击“重试写回工作台”；重传按稳定键 / PDF SHA256 去重。

任务进度保存在 `tools/cnki_agent/runtime/`，登录资料和下载全文保存在采集引擎的 `runtime_outputs/`，这些目录不会进入 Git。不要手动上传 Cookie 或机构账号到服务器。Agent 同时只执行一个本机任务。

采集器提供连接、安装、登录、采集、停止、进度和 PDF 文件接口；不执行服务器抽样，不接收工作台登录 Cookie，不将凭据写入候选池。

只校验包与地址配置，不安装或打开浏览器：python start_agent.py --check。

下载 ZIP 按明确文件清单生成，打包前检查 23 个引擎文件、归档 CRC 与 wheel RECORD；不含数据库、虚拟环境、Cookie、连接码和运行目录。升级合并替换代码后重启，保留原 .venv、runtime 与引擎 runtime_outputs。
