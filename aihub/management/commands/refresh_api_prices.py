from django.core.management.base import BaseCommand
from aihub.maintenance import daily


class Command(BaseCommand):
    help='Record daily API prices and remove assistant results older than seven days.'

    def handle(self, **options):
        count=daily()
        self.stdout.write(f'已处理 {count} 个模型的每日价格记录。')
