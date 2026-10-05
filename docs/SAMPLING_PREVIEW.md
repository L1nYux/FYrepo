# Sampling 模块分支说明

目标分支：`sampling-preview`

本分支用于在 FYrepo 工作台中验证 Sampling / 样本库模块的页面结构与交互，不应直接合并到 `main`。

## 当前已包含

- 工作台侧栏“样本库”入口；
- `/sampling/` 样本库页面；
- 概览；
- 知网采集页面与交互状态展示；
- 候选池及筛选；
- 入选复核（全选 / 取消全选 / 批量选入 / 批量排除 / 保存）；
- 主样本 / 留出样本 / 备用样本展示及用途说明；
- 抽样协议与交付文件下载入口。

## 当前仍属于联调内容

以下功能尚未与 FYrepo 后端正式打通：

- CNKI Playwright 自动采集；
- CNKI XLS 实际导出；
- PDF 自动获取；
- SamplingRun / SamplePaper 数据库模型；
- sampling_result_bundle.zip 的真实解析入库；
- 与 Experiment 的真实外键关联。

页面中的采集日志、样本数及交付文件目前用于验证工作台 UI 和交互路径。

## 边界

- 不修改生产数据库；
- 不增加数据库 migration；
- 不创建 Pull Request；
- 不合并到 `main`；
- 后续完成 UI 验收后，再逐步接入已验证的 sample-llm 采集与抽样逻辑。
