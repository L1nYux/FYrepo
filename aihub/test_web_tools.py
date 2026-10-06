from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings
from .web_tools import public_url, read_web, search_web, PageText, fetch_public

@override_settings(WORKBENCH_SEARCH_BACKEND='html', WORKBENCH_WEB_RENDER=False)
class WebToolTests(SimpleTestCase):
    def dns(self,address):return [(2,1,6,'',(address,443))]
    def test_blocks_local_private_metadata_and_reserved_addresses(self):
        for address in ['127.0.0.1','10.0.0.1','172.16.0.2','192.168.1.1','169.254.169.254','100.64.0.1','::1','fc00::1','::ffff:127.0.0.1']:
            with self.subTest(address=address),patch('aihub.web_tools.socket.getaddrinfo',return_value=self.dns(address)):
                with self.assertRaises(ValidationError):public_url('https://example.com/')
    def test_blocks_credentials_non_web_schemes_and_other_ports(self):
        for url in ['file:///etc/passwd','javascript:alert(1)','https://u:p@example.com/','https://example.com:8000/']:
            with self.assertRaises(ValidationError):public_url(url)
    def test_public_address_is_pinned(self):
        with patch('aihub.web_tools.socket.getaddrinfo',return_value=self.dns('8.8.8.8')):
            self.assertEqual(public_url('https://example.com/a')[3],'8.8.8.8')
    @patch('aihub.web_tools.fetch_public',return_value=('https://example.com/','text/html',b'<title>Source</title><script>secret-script</script><nav>menu</nav><p>Research content</p>'))
    def test_reader_returns_text_and_real_source_not_scripts(self,_fetch):
        result=read_web('https://example.com/');self.assertEqual(result['source']['url'],'https://example.com/');self.assertIn('Research content',result['content']);self.assertNotIn('secret-script',result['content']);self.assertNotIn('menu',result['content'])
    @patch('aihub.web_tools.fetch_public',return_value=('https://html.duckduckgo.com/html/','text/html',b'<a class="result__a" href="https://example.com/">Research title</a><a class="result__snippet">Useful summary</a>'))
    def test_search_has_real_url_title_and_snippet(self,_fetch):
        result=search_web('research');self.assertEqual(result['results'][0]['source']['url'],'https://example.com/');self.assertEqual(result['results'][0]['snippet'],'Useful summary')
    @patch('aihub.web_tools.fetch_public',return_value=('https://html.duckduckgo.com/html/','text/html',b'<p>challenge</p>'))
    def test_failed_search_does_not_invent_sources(self,_fetch):
        result=search_web('research');self.assertEqual(result['results'],[]);self.assertIn('error',result)
    @patch('aihub.web_tools.fetch_public',return_value=('https://example.com/','text/html',b'<script>Only JS</script>'))
    def test_empty_dynamic_page_is_reported(self,_fetch):
        with self.assertRaises(ValidationError):read_web('https://example.com/')
    def test_tool_definitions_and_progress_exist(self):
        from .agent import TOOLS,run_tool
        self.assertTrue({'search_web','read_web'}.issubset({tool['function']['name'] for tool in TOOLS}))

    def test_dictionary_mismatch_falls_back_to_related_results(self):
        rss='<rss><channel><item><title>能（汉语文字）</title><link>https://dictionary.example/neng</link><description>能的字义</description></item></channel></rss>'.encode()
        html=b'<a class="result__a" href="https://example.com/benchmark">Benchmark evaluation</a><a class="result__snippet">Machine learning benchmark</a>'
        with patch('aihub.web_tools.fetch_public',side_effect=[('https://bing.com','text/xml',rss),('https://html.duckduckgo.com/html/','text/html',html)]) as fetch:
            result=search_web('能帮我查一下什么是brenchmark吗')
        self.assertEqual(fetch.call_count,2);self.assertEqual(result['query'],'brenchmark')
        self.assertEqual(len(result['results']),1);self.assertIn('Benchmark',result['results'][0]['source']['title'])
        self.assertNotIn('neng',str(result['results']))
    def test_two_unrelated_search_services_do_not_claim_completion(self):
        rss='<rss><channel><item><title>能（汉语文字）</title><link>https://dictionary.example/neng</link></item></channel></rss>'.encode()
        html='<a class="result__a" href="https://dictionary.example/neng">能的拼音</a>'.encode()
        with patch('aihub.web_tools.fetch_public',side_effect=[('https://bing.com','text/xml',rss),('https://html.duckduckgo.com/html/','text/html',html)]):
            result=search_web('benchmark')
        self.assertEqual(result['results'],[]);self.assertIn('相关结果',result['error'])
    def test_chinese_subject_is_not_replaced_by_dictionary_results(self):
        from .web_tools import relevant_results
        rows=[{'source':{'title':'福建省福州第一中学'},'snippet':'校园简介'},{'source':{'title':'能的拼音'},'snippet':'字典释义'}]
        self.assertEqual(relevant_results('福州一中',rows),rows[:1])
