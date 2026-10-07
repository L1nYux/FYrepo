# 科研文档与策划书导入

## 使用

工作台 → 文档 → 新建或导入；也可以从项目的“文档”或任务详情进入。

- 在线文档：在修改稿里编辑文字、标题、列表、表格和图片，自动保存。
- Word、Excel、PDF：直接在应用内阅读。Word、Excel 的完整在线编辑需要下述文档服务。
- 正式版保持只读。成员先申请修改，批准后建立自己的修改稿，提交审核后由负责人采纳。
- 正式版更新后，旧修改稿不能直接覆盖；需对照新版并调整后重新提交。
- 提交成果可以选择正式文档版本。后续修改文档不会改变已提交的版本。
- 可按工作台号向跨团队伙伴授予查看、评论、修改或审核权限。退出团队会失去依赖成员身份的授权；关闭项目合作也会停止依赖合作资格的编辑。

策划书页面点“生成项目计划”，选择额度来源与已配置的模型。一次调用生成预览，用户检查任务、原文依据、分工与日期后确认创建。无依据的人员账号、日期和预算不自动填入。重复确认复用已创建项目，重复生成复用现有预览；失败重试需要主动确认费用。生成会将提取的文字发送给用户选择的模型服务商。

## 启用 Word 与 Excel 在线编辑

使用自建的 ONLYOFFICE Docs 文档服务。服务器管理员按官方安装说明部署，再把以下配置加入现有工作台环境文件：

    WORKBENCH_PUBLIC_URL=https://知域服务器域名
    WORKBENCH_OFFICE_URL=https://文档服务域名
    WORKBENCH_OFFICE_SECRET=与文档服务一致的随机JWT密钥

工作台和文档服务需能互相访问，用户电脑也需能访问文档服务。反向代理应支持文档服务的 WebSocket。HTTPS 地址要使用有效证书。密钥不要写入源码或群聊；更改后重启两边服务。

文档服务部署在独立的主机或有足够资源的服务器上。现有小规格服务器不要直接叠加运行；ONLYOFFICE 官方最低内存为 2 GB，另有系统依赖和存储要求。安装前按实际并发量确认资源和对应版本许可。

编辑器只获得短期签名的文件读取地址，保存回调必须使用共享 JWT 验证，并再次检查修改稿、账号和权限。团队的模型厂商 Key 不会交给文档服务。

参考：

- [ONLYOFFICE 官方安装](https://helpcenter.onlyoffice.com/docs/installation/docs-community-install-ubuntu.aspx)
- [系统要求](https://helpcenter.onlyoffice.com/docs/installation/docs-community-sys-reqs-linux.aspx)
- [保存回调](https://api.onlyoffice.com/docs/docs-api/usage-api/callback-handler/)
- [强制保存](https://api.onlyoffice.com/docs/docs-api/additional-api/command-service/forcesave/)
- [JWT 验证](https://api.onlyoffice.com/docs/docs-api/get-started/how-it-works/security/)

## 前端维护

文档阅读和编辑使用 Tiptap、docx-preview、ExcelJS、PDF.js。已构建的前端文件在 static/vendor/documents，服务器升级不需要安装 Node。

修改编辑器后，在 editor 目录执行 npm ci 和 npm run build，随源码提交构建产物。依赖锁定在 editor/package-lock.json。源文件和第三方许可需一起保留。
