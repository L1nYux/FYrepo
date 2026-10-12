# 知域 0.6.4 中转更新

## 接入

生成一次团队 API Key，复制模型列表中的 ID 即可使用。项目和实验关联可省略。

| 客户端 | Base URL | 接口 |
| --- | --- | --- |
| OpenAI Chat / Responses SDK | `https://知域域名/v1` | `/v1/chat/completions`、`/v1/responses` |
| Anthropic SDK | `https://知域域名` | `/v1/messages` |
| Gemini SDK | `https://知域域名`，API version 为 v1beta | `/v1beta/models/{模型}:generateContent` / `streamGenerateContent` |
| 向量客户端 | `https://知域域名/v1` | `/v1/embeddings` |

Key 支持 Bearer、x-api-key 或 x-goog-api-key，冲突凭证会拒绝。Gemini 保留 SDK 使用的 key 参数兼容，建议使用请求头以减少 URL 日志中的凭证。浏览器登录不会替代 Key 鉴权。

原生入口保留上游请求与响应格式、思考签名、工具调用和事件类型。对应连接必须支持该接口：在 OpenAI 兼容地址下配置模型，并不代表那个供应商同时支持 Responses。Chat 入口仍可以转换三种文本协议。

支持 token 计数入口、Responses 的 GET/DELETE 与本 Key 的 previous_response_id。共享上游凭证下不能读取其他 Key 的响应；未登记归属的上游 file_id、conversation、cachedContent 不接受，可传完整文本、图片或文件数据。当前不提供通用 Files 上传、WebSocket/Realtime、独立图片生成或音频/视频任务入口。

## 输入与费用

- 请求体与上下文默认 16 MiB，服务器配置和前置代理需一致；不会自动拆分正文。
- 未填输出上限时，采用模型的默认输出，初始为 4096 且不超过模型最大输出。长回答可显式填写 max_tokens / max_output_tokens，或由管理员修改默认值。
- 对已知 OpenAI tokenizer 使用随包核验的词表；其他模型使用带余量的估算。可在高级模型设置指定 tokenizer 或选择按字节保守预留。**预留不是最终收费，估算也不是供应商的准确 token 数。**
- 结算按当次价格快照、上游真实 usage 和对应输入档位计算，保留缓存读取/写入和思考用量。套餐折扣、特殊 service tier 和内置工具的额外费用仍以供应商账单为准，技术账目可能存在差异。
- OpenAI、Anthropic、Gemini 增加 LiteLLM 公共价格表参考源，严格匹配厂商与型号，并在来源中标注“公开参考价”。已有厂商官方来源按原逻辑处理；手动价格不被覆盖。源读取失败保留原有效价格并显示失败状态。
- 返回无法确定的收费结果时保留预留，不自动重发已可能计费的请求。SDK 示例关闭自动重试，并提供 1800 秒等待时间；客户端应根据业务调整。

## 渠道与管理

多个连接下的模型填写同一“对外模型名”，即可组成渠道池。数字更小的优先级先使用，同级按权重选择；旧的“供应商编号/模型 ID”保持可用。Key 的模型范围仍按具体授权模型检查。仅在明确未计费、尚未发出流事件的失败时尝试备用连接，最多 8 个，已输出的请求不切换。

管理页的“连接运行情况”显示近 7 天最近最多 1000 笔调用的成功率、首字和完成 P95、待核对数量与价格更新失败。费用记录不保存提示词、回答、工具正文或供应商 Key，新调用保存实际模型及连接快照，修改配置不改写这些记录。

Responses 已完成的供应商 usage、OpenRouter 确认的账单支持自动核对；缺少明确记录的仍保留待核对。每日维护会尝试核对，管理员也可点击查询或运行 `python manage.py reconcile_relay_calls`。原币种、请求 ID 和当次价格快照用于结算，核对不会重复扣费。

Web 服务默认改为两个进程、每个 8 个线程，可用 WORKBENCH_WEB_WORKERS / WORKBENCH_WEB_THREADS 调整。这改善长请求同时等待时的承载，数据库仍为 SQLite，未宣称达到大型公共中转站容量。

## PR #11 与升级

已将采集器发布修复合入实际 0.6.4 发布分支，保留既有 worker、浏览器/Office 预览与回滚逻辑。发布准备按清单复制启动器和核验的引擎；在关闭旧服务之前，从实际新发布目录构建采集器 ZIP。Cookie、任务数据、旧 Origin 和虚拟环境不复制。

升级沿用备份、数据库副本迁移与正式切换流程。安装客户端不会升级服务器；需要在服务器运行随包的升级脚本。
