from django.core.management.base import BaseCommand
from core.releases import sync

class Command(BaseCommand):
    help='Publish one system announcement per stable desktop version'
    def add_arguments(self,parser): parser.add_argument('--check-latest',action='store_true')
    def handle(self,*args,**options):
        from core.models import Team
        from core.tenancy import scope
        from core.releases import bundled, latest, publish
        infos=[bundled()]
        if options['check_latest']:
            try: infos.append(latest())
            except Exception: self.stderr.write('版本查询暂不可用，保留现有公告。')
        for team in Team.objects.filter(active=True).iterator():
            with scope(team):
                for info in infos: publish(info)
        self.stdout.write('Version announcement synchronized; duplicate versions are not reposted.')
