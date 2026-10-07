# FYrepo Sampling 正式版 v2（2026-10-06）

基于 FYrepo `sampling-preview`（`138bac85bd4b5fdec0800b5d2e9c2607bc74ff25`），含 main `c9d518a9fb40b913579077aaef242b73f4267722` 的完整工作台。按 Sampling Project Handoff 继续；不合并 main，不自动创建 PR。原 Preview 路由、模板和静态演示结果已删除。

## 使用流程

样本库 → 新建样本集 → 保存范围 → 本机知网采集 / 上传原生题录 → 候选池 → UNCERTAIN 人工复核 → 确认冻结并抽样 → 全文 PDF → Canonical Markdown → 实验记录。

新建和编辑共用约 620px 右侧抽屉，使用 FYrepo 的按钮、卡片、颜色、导航及原项目树。名称独立必填；关联项目可空，选项来自 `core.Project` 的真实数据和工作台访问权限。保存后显示范围摘要。

必填项统一标星、红框及具体错误，前端定位第一个错误，后端 Form 始终校验。时期使用规范 `periods` 多选字段，在 ModelForm 验证模型前转换为 JSON。空 POST 或未知时期正常返回抽屉，不进入 Django traceback。留出样本关闭时年份不参与校验，开启时数量和年份必填，年份不倒置且不与主时期重叠。

P1/P2/P3 和 50 刊目录来自项目既有研究编码配置，非运行数据或官方排名。法律适用在 P1/P2 为 T4、P3 为 T3；中国社会科学需法学内容复核。留出期采用 P3 的期刊层级编码。

修改时期、期刊或留出年份会清空未冻结候选池；只修改名称、项目、版本、抽样数量、方法或 Seed 会保留候选。冻结版本禁止覆盖，创建新版本保留 source_run 关系，重新采集。

## 与 sample-llm 的对接

固定源提交 `2167aa39878bb892ba3ee90906c86d6a196d5035`，实际采集、批次续采、登录、停止及 PDF 下载直接调用上游 `integrations` 和随附 exporter wheel。固定代码及许可证位于 `vendor/sample_llm/`；不依赖外部同名目录，也不附带 Gradio 演示页面、候选数据或登录资料。

2026-10-07 H1 修复：上游随附 wheel / ZIP 在原始 Git blob 中已经损坏，因此从 exporter 原始提交 `4bdf8e1` 重建，六个 Python 模块不作修改。安装适配器加入来源清单、哈希、ZIP/CRC、wheel RECORD、源码与已安装文件一致性校验，采集与合并入口在实际子进程中检查；原始来源与本地修复分开记录。详见 [H1 修复和验收](SAMPLING_CNKI_H1.md)。

候选池标准化、稳定键去重、抽样框匹配、自动排除 / 纳入 / 元数据异常 / UNCERTAIN 都由工作台真实数据库处理。UNCERTAIN 分页批量复核，重导入保留已作出的人工决策。

冻结检查每个主 / 留出抽样格数量、未决复核和研究范围。两种方法均执行 SHA256(seed | stratum_id | candidate_key)，备用使用 seed + `|reserve`。与上游 sampler 对照测试包括主 / 备用的编号、稳定键和哈希。主 / 留出不足阻止冻结；备用不足保留真实不足记录。

冻结保存抽样框快照、协议及规则 / 目录哈希；以后目录变更不会改变已冻结的抽样框。P/H/R 编号、frame / registry 哈希、运行指纹、完整排序、逐样本凭证、下载任务、证据任务、safe manifest 和 labels vault 均从数据库生成。结果 ZIP 导入核验协议、文件 SHA256、指纹、实际抽样选择和凭证，禁止缺字段时补造范围。

sample-llm 原生结果包使用排序 CSV 哈希；FYrepo 使用明确标记的 `canonical_json_v1`。两者指纹公式相同，哈希序列化格式不同；导入分别校验，不声称两种格式的指纹相同。

## 本机连接

[启动和操作说明](../tools/cnki_agent/README.md)。线上域名须加入 Agent 的准确 Origin 白名单；连接码只发 loopback，同源写回使用 CSRF。登录 Cookie 和验证码留在用户电脑。本机进度持久保存，浏览器可恢复轮询和重试回传；旧研究范围任务不会写入新候选池。

不能保证所有知网论文均可自动获取 PDF。下载报告不代表工作台已经取得文件；只有有效文件上传后标记已接收。人工下载的 PDF 也可在“全文与 Markdown”上传。

## PDF → Markdown

接入用户提供的文字层转换器，以 pdfplumber 在独立子进程中提取。原 PDF 文件名保持原样，私有存储采用独立路径，MD 输出为正式 paper_id.md。每份记录原文件名、PDF / MD SHA256、页数、字符数、警告、转换器版本和失败原因，支持幂等重传、版本历史及重试。

单份 PDF ≤20MB；批量 ZIP ≤40MB、解压总量 ≤80MB、最多100份；内含 `pdf_manifest.csv`：paper_id、source_pdf。模板从当前冻结编号生成，不要求重命名 PDF。

任务持久排队，worker 通过原子状态更新领取，在独立进程转换（300秒上限）；中断任务15分钟后标为可重试失败。上传请求不阻塞等待全文转换。

下载 Canonical MD 包含原 PDF→编号映射和转换报告。Canonical MD 保留真实题名、作者、期刊，**尚未匿名化**。扫描件无文字层不产生伪正文，先 OCR 再上传；公式、表格、双栏和低文本量有质量限制，需人工核对。未接入 MinerU、OCR 或自动 LLM 匿名化 / 评审执行。

## 安装、迁移、运行

保留既有数据库、用户、项目与配置，先按原运维规范备份。仅升级采样模块，不执行“只保留账号”的重建脚本。

```bash
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check
python manage.py test
python manage.py test sampling
```

同样的工作台环境变量下，另开进程运行：

```bash
python manage.py sampling_worker
# 处理现有队列后退出：
python manage.py sampling_worker --once
```

既有 Linux 安装可运行 `sudo bash deploy/install_sampling_worker.sh` 安装常驻服务，复用 `/etc/research-workbench.env`、workbench 用户和既有数据目录。查看 `journalctl -u research-sampling-worker -f`。升级 / 备份时与 Web 服务一起停止此 worker，再迁移并重启；缺少 worker 时文件保持队列状态。

## 权限、实验与边界

开发者和管理员可查看内部样本集；管理员、创建者、关联项目负责人可管理；普通用户遵守 FYrepo 既有中间件跳回公开页面。项目下拉与原项目树复用既有团队查看权限。PDF / MD 和抽样文件只经登录、对象归属及团队权限控制的下载路由提供，无公开媒体目录。

冻结后创建既有 `core.Experiment`，写入来源、版本与 fingerprint；重复点击复用已建立记录，不另建实验模型。该操作建立可编辑实验记录，后续实际实验由既有工作台流程完成。证据任务保留清单和人工采集要求，尚无证据截图上传 / 归档界面。

正式包不携带示例候选集、业务数据库、真实全文、连接码、Cookie 或默认测试账号。自动化回归与浏览器验收采用独立临时数据库和测试夹具，与正式运行隔离。
