from django.core.management.base import BaseCommand, CommandError
from aihub.service import pool_settings
from core.tenancy import scope, team_users
from core.models import Team
from core import permissions as perms

class Command(BaseCommand):
    help='指定团队 API 池负责人，不授予其他管理权限。'
    def add_arguments(self,parser):
        parser.add_argument('username'); parser.add_argument('--team', type=int, default=1)
    def handle(self,*args,**options):
        if not Team.objects.filter(pk=options['team'], active=True).exists(): raise CommandError('团队不存在或已停用。')
        with scope(options['team']):
            user=team_users().filter(username=options['username']).first()
            if not user or not perms.is_admin(user): raise CommandError('请指定本团队有效管理员。')
            pool=pool_settings(); pool.owner=user; pool.save(update_fields=['owner'])
            self.stdout.write(self.style.SUCCESS('API 池负责人已设置：'+user.username))
