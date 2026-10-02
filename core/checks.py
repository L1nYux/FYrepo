"""启动自检：把「配置缺失」变成启动时的明确警告，而不是成员点「忘记密码」时的 500。

Django 默认的邮件后端指向 localhost 的 SMTP。生产环境若没配 SMTP，
`PasswordResetView` 会在发信时抛出连接错误 —— 成员看到的是 500，也很难自查。
这里在 `manage.py check` 和每次启动时给一条明确的警告。
"""
from django.conf import settings
from django.core.checks import Warning as CheckWarning, register


@register()
def email_configuration(app_configs, **kwargs):
    issues = []
    if settings.DEBUG:
        return issues  # 开发用控制台后端，把重置链接打印在控制台，不需要 SMTP。
    if not settings.EMAIL_HOST:
        issues.append(CheckWarning(
            '未配置 SMTP：成员无法使用「忘记密码」自助找回。',
            hint='设置 WORKBENCH_EMAIL_HOST / WORKBENCH_EMAIL_USER / WORKBENCH_EMAIL_PASSWORD，'
                 '详见 .env.example 与 docs/MAINTENANCE.md。',
            id='core.W001',
        ))
    if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
        issues.append(CheckWarning(
            'EMAIL_USE_TLS 与 EMAIL_USE_SSL 同时为真，邮件发送会失败。',
            hint='587 端口用 TLS，465 端口用 SSL，只开其中一个。',
            id='core.W002',
        ))
    if settings.EMAIL_HOST and not settings.EMAIL_HOST_USER:
        issues.append(CheckWarning(
            '配置了 SMTP 主机但没有 SMTP 用户名，多数邮箱服务会拒绝发信。',
            hint='WORKBENCH_EMAIL_USER 填发信邮箱地址，WORKBENCH_EMAIL_PASSWORD 填它的'
                 '「授权码 / 应用专用密码」（不是邮箱登录密码）。',
            id='core.W004',
        ))
    if settings.EMAIL_HOST and settings.EMAIL_HOST_USER and not settings.EMAIL_HOST_PASSWORD:
        issues.append(CheckWarning(
            '配置了 SMTP 主机和用户名但没有密码，发信会因认证失败而被拒。',
            hint='WORKBENCH_EMAIL_PASSWORD 填邮箱的「授权码 / 应用专用密码」，'
                 '不是邮箱登录密码。',
            id='core.W005',
        ))
    if settings.EMAIL_BACKEND.endswith('console.EmailBackend') and not settings.DEBUG:
        issues.append(CheckWarning(
            '生产环境仍在使用控制台邮件后端，重置链接只会打印到服务日志里。',
            hint='确认 WORKBENCH_DEBUG 未被设为 1，或改用 SMTP 后端。',
            id='core.W003',
        ))
    return issues
