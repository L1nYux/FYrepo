from django.core.management.base import BaseCommand
from aihub.gifts import expire_gifts
class Command(BaseCommand):
    help = 'Return unclaimed supplemental AI points from expired gifts.'
    def handle(self,*args,**options):
        self.stdout.write(f'Returned {expire_gifts()} expired point gifts.')
