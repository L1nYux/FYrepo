import os
from unittest import skipUnless
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from django.core.exceptions import ValidationError
from .render_web import render


@skipUnless(os.environ.get('WORKBENCH_BROWSER_TESTS')=='1', 'Run with installed Chromium and WORKBENCH_BROWSER_TESTS=1')
@override_settings(WORKBENCH_WEB_RENDER=True)
class BrowserReaderTests(SimpleTestCase):
    def fixture(self, script):
        return ('https://reader.example/article','text/html; charset=utf-8',
                ('<title>Rendered article</title><body><div id="app"></div><script>'+script+'</script></body>').encode())

    def dns(self,*args,**kwargs):return [(2,1,6,'',('8.8.8.8',443))]

    def test_real_javascript_hydration_is_read_not_script_source(self):
        fixture=self.fixture("document.querySelector('#app').innerText='真实浏览器读取的实验方法和研究资料。 This content came from a JavaScript page.'")
        with patch('aihub.web_tools.socket.getaddrinfo',side_effect=self.dns),patch('aihub.web_tools.fetch_public',return_value=fixture):
            result=render(fixture[0],fixture)
        self.assertIn('真实浏览器读取',result['content']);self.assertNotIn('document.querySelector',result['content'])
        self.assertEqual(result['read_mode'],'browser')

    def test_public_fetch_can_hydrate_but_private_post_and_websocket_are_blocked(self):
        fixture=self.fixture("""document.querySelector('#app').innerText='安全网页正文 public JavaScript hydration test';
fetch('/data.json').then(r=>r.json()).then(v=>document.querySelector('#app').innerText += v.text);
fetch('http://169.254.169.254/metadata').catch(()=>{});
fetch('/write',{method:'POST',body:'must-not-send'}).catch(()=>{});
try { new WebSocket('wss://reader.example/socket'); } catch (_) {}""")
        def fetch(url):
            self.assertEqual(url,'https://reader.example/data.json')
            return url,'application/json',b'{"text":" PINNED API CONTENT"}'
        with patch('aihub.web_tools.socket.getaddrinfo',side_effect=self.dns),patch('aihub.web_tools.fetch_public',side_effect=fetch) as reader:
            result=render(fixture[0],fixture)
        self.assertIn('PINNED API CONTENT',result['content']);self.assertGreaterEqual(result['blocked_requests'],2)
        self.assertEqual(reader.call_count,1)

    def test_empty_page_is_not_reported_as_successful_read(self):
        fixture=self.fixture('')
        with patch('aihub.web_tools.socket.getaddrinfo',side_effect=self.dns),self.assertRaises(ValidationError):render(fixture[0],fixture)
