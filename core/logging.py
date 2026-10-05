import logging
from django.conf import settings
from django.core.mail import mail_admins


class OperationsEmailHandler(logging.Handler):
    """Error alerts omit request bodies, headers, keys, prompts and local variables."""
    def emit(self, record):
        if not settings.ADMINS: return
        request=getattr(record,'request',None)
        summary='模块：'+record.name+'\n等级：'+record.levelname
        if request is not None: summary+='\n请求：'+request.method+' '+request.path[:200]
        summary+='\n请查看服务器日志定位异常。通知不包含请求正文、密钥或个人资料。'
        try: mail_admins('科研工作台服务异常',summary,fail_silently=True)
        except Exception: pass
