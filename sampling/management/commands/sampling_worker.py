import time
from django.core.management.base import BaseCommand
from sampling.documents import process_next_document, recover_abandoned_documents


class Command(BaseCommand):
    help = '处理真实 PDF→Markdown 队列；--once 处理当前队列后退出。'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--poll-interval', type=float, default=2)

    def handle(self, *args, **options):
        self.stdout.write('PDF→Markdown worker 已启动')
        while True:
            recover_abandoned_documents()
            doc = process_next_document()
            if doc:
                self.stdout.write(f'{doc.candidate.paper_id}: {doc.get_status_display()}')
            elif options['once']:
                break
            else:
                time.sleep(max(0.5, min(10, options['poll_interval'])))
