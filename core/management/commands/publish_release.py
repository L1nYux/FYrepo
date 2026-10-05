from django.core.management.base import BaseCommand
from core.releases import sync

class Command(BaseCommand):
    help='Publish one system announcement per stable desktop version'
    def add_arguments(self,parser): parser.add_argument('--check-latest',action='store_true')
    def handle(self,*args,**options):
        sync(options['check_latest'])
        self.stdout.write('Version announcement synchronized; duplicate versions are not reposted.')
