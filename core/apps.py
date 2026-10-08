from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        from . import checks  # noqa: F401  注册启动自检（邮件配置等）
        from . import team_signals  # noqa: F401
        from . import workspace_audit  # noqa: F401
        from . import personal_history  # noqa: F401
        from . import local_chat_delivery  # noqa: F401
