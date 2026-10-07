"""Inspect public retrieval from the deployed server, without AI calls or keys."""
import json
import time
from urllib.parse import urlencode
from django.core.management.base import BaseCommand
from django.core.exceptions import ValidationError
from django.conf import settings
from aihub.web_tools import fetch_public, parse_search, relevant_results


class Command(BaseCommand):
    help='检查公共搜索来源的 DNS、连接、响应和相关结果；不调用模型、不读取厂商密钥。'

    def add_arguments(self,parser):parser.add_argument('--query',default='benchmark 机器学习')

    def handle(self,*args,**options):
        query=options['query'].strip()[:300]
        endpoints=[('必应国内 RSS','https://cn.bing.com/search?format=rss','q'),('必应国内网页','https://cn.bing.com/search','q'),('百度网页','https://www.baidu.com/s','wd'),('DuckDuckGo 网页','https://html.duckduckgo.com/html/','q')]
        if settings.WORKBENCH_SEARCH_URL:endpoints.insert(0,('配置的搜索服务',settings.WORKBENCH_SEARCH_URL,'q'))
        for label,url,field in endpoints:
            began=time.monotonic()
            try:
                final,mime,raw=fetch_public(url+('?' if '?' not in url else '&')+urlencode({field:query}))
                rows=parse_search(final,mime,raw)
                status={'source':label,'seconds':round(time.monotonic()-began,1),'content_type':mime,'bytes':len(raw),'parsed_results':len(rows),'relevant_results':len(relevant_results(query,rows))}
            except ValidationError as error:status={'source':label,'seconds':round(time.monotonic()-began,1),'error':' '.join(error.messages)}
            self.stdout.write(json.dumps(status,ensure_ascii=False))
