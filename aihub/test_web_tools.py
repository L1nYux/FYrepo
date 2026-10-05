from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from .web_tools import public_url, read_web, search_web, PageText, fetch_public

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
    @patch('aihub.web_tools.fetch_public',return_value=('https://html.duckduckgo.com/html/','text/html',b'<a class="result__a" href="https://example.com/">Real title</a><a class="result__snippet">Useful summary</a>'))
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
