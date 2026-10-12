"""Reconcile only confirmed supplier usage; unconfirmed costs remain reserved."""
from django.core.management.base import BaseCommand
from core.models import Workspace
from core.tenancy import scope
from aihub.operations import reconcile

class Command(BaseCommand):
    help='Read supported supplier usage records and settle pending calls.'
    def handle(self,**options):
        total=0
        for workspace in Workspace.objects.filter(kind='team',active=True,team__active=True):
            with scope(workspace):total+=reconcile()['settled']
        self.stdout.write('Confirmed and settled: '+str(total))
