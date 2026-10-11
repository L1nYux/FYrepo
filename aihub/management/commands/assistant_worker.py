"""Run private assistant jobs independently of the web server."""
import time
from concurrent.futures import ThreadPoolExecutor
from django.core.management.base import BaseCommand
from django.db import close_old_connections, connections
from aihub.agent import worker
from aihub.execution import queued


class Command(BaseCommand):
    help='执行 AI 助手队列；重启后从安全步骤恢复，不重发未保存回复的上游请求。'

    def add_arguments(self,parser):
        parser.add_argument('--once',action='store_true')
        parser.add_argument('--concurrency',type=int,choices=[1,2],default=2)
        parser.add_argument('--poll-interval',type=float,default=1)

    def handle(self,*args,**options):
        def run(identifier):
            try:worker(identifier)
            finally:connections.close_all()
        active={}
        with ThreadPoolExecutor(max_workers=options['concurrency'],thread_name_prefix='assistant') as pool:
            while True:
                close_old_connections()
                for identifier,future in list(active.items()):
                    if future.done():
                        try:future.result()
                        except Exception as error:self.stderr.write(f'任务 {identifier} 中断：{type(error).__name__}')
                        del active[identifier]
                slots=options['concurrency']-len(active)
                if slots:
                    for identifier in queued().exclude(pk__in=active).values_list('pk',flat=True)[:slots]:
                        active[identifier]=pool.submit(run,identifier)
                if options['once'] and not active:break
                time.sleep(max(.2,min(5,options['poll_interval'])))
