from django.core.management.base import BaseCommand
from aihub.gifts import expire_gifts
class Command(BaseCommand):
    help = 'Return unclaimed supplemental AI points from expired gifts.'
    def handle(self,*args,**options):
        from core.models import Team
        from core.tenancy import scope
        total = 0
        for team in Team.objects.all().iterator():
            with scope(team):
                total += expire_gifts()
        self.stdout.write(f'Returned {total} expired point gifts.')
