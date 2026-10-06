# 本机知网采集器 v2

需要 Python 3.11+。完整 FYrepo 已包含固定版本采集引擎，无需另行克隆 sample-llm。
引擎来源：`Synex1213/sample-llm`，提交 `2167aa39878bb892ba3ee90906c86d6a196d5035`；上游文件保持原样，许可证见 `vendor/sample_llm/`。

Windows：双击 `run_agent_windows.cmd`。macOS / Linux：执行 `bash run_agent_mac_linux.sh`。
首次运行会建立独立虚拟环境并安装 Python 依赖，需网络连接。终端显示连接码，粘贴到工作台；连接码保留在本机，不上传工作台，不放入 Git。

默认允许 `http://127.0.0.1:8000` 和 `http://localhost:8000`。线上工作台必须添加其**准确源地址**（无尾部路径）：

```bat
set SAMPLING_WORKBENCH_ORIGINS=https://你的工作台域名
run_agent_windows.cmd
```

```bash
SAMPLING_WORKBENCH_ORIGINS=https://你的工作台域名 bash run_agent_mac_linux.sh
```

也可直接运行 `python agent_server.py --allow-origin https://你的工作台域名`。仅监听 `127.0.0.1:8765`。现代浏览器询问本地网络访问权限时，需允许当前工作台访问本机。HTTPS→loopback 的权限策略需要在实际使用的浏览器和域名上验收。

1. 点击“检查连接”；缺少组件时点击“安装 / 修复采集组件”。组件固定为随包附带的 `cnki-metadata-exporter 0.2.0`。
2. 点击“打开知网登录”；本人在本机浏览器完成机构登录和验证码，再点击“登录完成”。
3. “开始采集”按真实抽样框采集，支持按年分片、1–3 个窗口和上游批次续采。同一样本集、范围保持独立工作目录。
4. 采集完成后浏览器分批回传题录。工作台范围已变更时，旧任务被拒绝，不写入新候选池。
5. 冻结后下载主样本和留出样本 PDF。有效 PDF 由浏览器上传工作台并进入转换队列；没有权限或下载失败的论文保留人工下载入口。
6. 中断 / 关闭工作台后重新填写连接码并检查连接，可恢复任务轮询。回传失败可点击“重试写回工作台”；重传按稳定键 / PDF SHA256 去重。

任务进度保存在 `tools/cnki_agent/runtime/`，登录资料和下载全文保存在采集引擎的 `runtime_outputs/`，这些目录不会进入 Git。不要手动上传 Cookie 或机构账号到服务器。Agent 同时只执行一个本机任务。

采集器提供连接、安装、登录、采集、停止、进度和 PDF 文件接口；不执行服务器抽样，不接收工作台登录 Cookie，不将凭据写入候选池。
