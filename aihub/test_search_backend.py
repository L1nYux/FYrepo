import json
from unittest.mock import patch, MagicMock
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings
from .search_backend import result_rows, search, rpc
from .web_tools import search_web, resolve_public, read_web


class StructuredSearchTests(SimpleTestCase):
    def test_explicit_service_records_become_sources_and_no_prose_urls_are_invented(self):
        result=result_rows({'content':[{'type':'text','text':
            'Title: Benchmark\nURL: https://example.com/benchmark\nPublished: 2026-09-30\nAuthor: Example\nHighlights:\nMeasured evaluation\n\n---\n\nTitle: Other\nURL: javascript:alert(1)\nText: invalid'}]})
        self.assertEqual(len(result),1);self.assertEqual(result[0]['source']['published_at'],'2026-09-30')
        self.assertEqual(result[0]['snippet'],'Measured evaluation')
        self.assertEqual(result_rows({'content':[{'type':'text','text':'Maybe https://example.com exists'}]}),[])

    def test_structured_result_is_bounded_and_deduplicated(self):
        values=[{'title':'Result','url':f'https://example.com/{i}','text':'x'*9000} for i in range(20)]
        rows=result_rows({'structuredContent':{'results':[values[0]]+values}})
        self.assertEqual(len(rows),8);self.assertEqual(len(rows[0]['snippet']),1600)

    @override_settings(WORKBENCH_SEARCH_BACKEND='auto', WORKBENCH_SEARCH_URL='')
    def test_service_rate_limit_falls_back_to_html_sources(self):
        html=b'<a class="result__a" href="https://example.com">Benchmark evaluation</a>'
        with patch('aihub.search_backend.search',side_effect=ValidationError('rate limited')),patch('aihub.web_tools.fetch_public',return_value=('https://bing.com','text/html',html)):
            result=search_web('benchmark')
        self.assertEqual(len(result['results']),1);self.assertNotIn('error',result)

    @override_settings(WORKBENCH_SEARCH_BACKEND='auto', WORKBENCH_SEARCH_URL='')
    def test_service_sources_precede_scraping(self):
        value={'results':[{'source':{'title':'Benchmark','url':'https://example.com'}}],'query':'benchmark','backend':'exa'}
        with patch('aihub.search_backend.search',return_value=value),patch('aihub.web_tools.fetch_public') as fetch:
            self.assertEqual(search_web('benchmark')['backend'],'exa')
        fetch.assert_not_called()

    def test_rpc_sse_is_bound_to_request_id_and_never_sends_model_keys(self):
        connection=MagicMock();response=connection.getresponse.return_value
        response.status=200;response.getheader.return_value='identity'
        def request(method,path,body,headers):
            value=json.loads(body);self.assertEqual(value['params']['name'],'web_search_exa')
            self.assertNotIn('Authorization',headers);self.assertNotIn('x-api-key',headers)
            response.read.return_value=('data: '+json.dumps({'id':value['id'],'result':{'content':[]}})+'\n\n').encode()
        connection.request.side_effect=request
        with patch('aihub.web_tools.resolve_public',return_value=(type('Parts',(),{'path':'/mcp'})(),'mcp.exa.ai',443,['8.8.8.8'])),patch('aihub.web_tools.PinnedHTTP',return_value=connection):
            self.assertEqual(rpc('web_search_exa',{'query':'benchmark'}),{'content':[]})

    def test_free_limit_metadata_is_not_reported_as_empty_search(self):
        connection=MagicMock();response=connection.getresponse.return_value
        response.status=200;response.getheader.return_value='identity'
        def request(method,path,body,headers):
            value=json.loads(body)
            response.read.return_value=json.dumps({'id':value['id'],'result':{'_meta':{'ai.exa/rateLimited':True},'content':[]}}).encode()
        connection.request.side_effect=request
        with patch('aihub.web_tools.resolve_public',return_value=(type('Parts',(),{'path':'/mcp'})(),'mcp.exa.ai',443,['8.8.8.8'])),patch('aihub.web_tools.PinnedHTTP',return_value=connection),self.assertRaisesMessage(ValidationError,'免费频率限制'):
            rpc('web_search_exa',{'query':'benchmark'})

    def test_proxy_synthetic_dns_requires_separate_real_public_answer(self):
        with patch('aihub.web_tools.socket.getaddrinfo',return_value=[(2,1,6,'',('198.18.1.1',443))]),patch('aihub.public_dns.resolve',return_value=['8.8.8.8']):
            self.assertEqual(resolve_public('https://example.com')[3],['8.8.8.8'])
        with patch('aihub.web_tools.socket.getaddrinfo',return_value=[(2,1,6,'',('198.18.1.1',443))]),patch('aihub.public_dns.resolve',return_value=['127.0.0.1']),self.assertRaises(ValidationError):
            resolve_public('https://example.com')

    def test_literal_synthetic_or_mixed_private_dns_does_not_trigger_fallback(self):
        with patch('aihub.public_dns.resolve') as resolver:
            with self.assertRaises(ValidationError):resolve_public('https://198.18.1.1')
            with patch('aihub.web_tools.socket.getaddrinfo',return_value=[(2,1,6,'',('198.18.1.1',443)),(2,1,6,'',('127.0.0.1',443))]),self.assertRaises(ValidationError):
                resolve_public('https://example.com')
            resolver.assert_not_called()

    @override_settings(WORKBENCH_WEB_RENDER=True)
    def test_javascript_reader_uses_rendered_body_and_records_real_read_mode(self):
        raw=b'<title>Loading</title><div id="root"></div><script src="/app.js"></script>'
        with patch('aihub.web_tools.fetch_public',return_value=('https://example.com','text/html',raw)),patch('aihub.render_web.render',return_value={'url':'https://example.com','title':'Loaded','content':'Real rendered article'}) as render:
            result=read_web('https://example.com')
        self.assertEqual(result['content'],'Real rendered article');self.assertEqual(result['source']['read_mode'],'browser')
        render.assert_called_once()

    def test_invalid_read_mode_is_rejected_before_network(self):
        with patch('aihub.web_tools.fetch_public') as fetch,self.assertRaises(ValidationError):read_web('https://example.com',mode='secret')
        fetch.assert_not_called()
