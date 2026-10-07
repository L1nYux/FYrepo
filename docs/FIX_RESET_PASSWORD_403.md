# 0.2.16 管理员重置密码返回 403 的修复

服务器已执行 `core.0023_member_account_lifecycle` 后，管理员仍可能在点击「生成临时密码」时遇到 HTTP 403。

原因是重置页面响应使用 `Referrer-Policy: no-referrer`。真实 Electron 浏览器提交该表单时会发送 `Origin: null` 并省略 Referer；Django 的 CSRF 校验因此拒绝请求。

修复将该页面的策略改为 `same-origin`，让同站表单保留来源、跨站导航仍不发送来源。临时密码响应继续使用 `no-store`，管理员权限、CSRF 校验、旧凭据撤销和强制改密保持生效。

新增 HTTPS 严格 CSRF 回归：同站且带有效 token 的提交成功；空来源、跨站来源、缺少来源及缺少 token 的请求仍返回 403。成员界面检查也通过真实 Chromium 表单提交，使用当前 Django 页面和响应策略复现该问题。

此修复位于服务端，不需要重新安装 0.2.16 桌面客户端，也不新增数据库迁移。使用包含修复的源码提交运行 `deploy/upgrade_preserve_data.sh --apply`，完成后重新打开重置页面再提交。
