from django.core.management.base import BaseCommand,CommandError
from django.contrib.auth import get_user_model
from aihub.service import pool_settings


class Command(BaseCommand):
    help='通过服务器命令指定唯一 API 池负责人，不授予其他管理权限。'
    def add_arguments(self,parser): parser.add_argument('username')
    def handle(self,*args,**options):
        user=get_user_model().objects.filter(username=options['username'],is_active=True,is_staff=True).first()
        if not user: raise CommandError('请指定有效管理员账户。')
        pool=pool_settings(); pool.owner=user; pool.save(update_fields=['owner'])
        self.stdout.write(self.style.SUCCESS('API 池负责人已设置：'+user.username))
