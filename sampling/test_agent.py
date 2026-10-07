"""Loopback HTTP 边界与持久任务测试；不访问机构登录或伪造知网结果。"""
import importlib.util
import json
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.test import SimpleTestCase


class LocalAgentTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        spec=importlib.util.spec_from_file_location('fyrepo_agent_test',settings.BASE_DIR/'tools/cnki_agent/agent_server.py')
        cls.agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.agent)
        cls.server=cls.agent.ThreadingHTTPServer(('127.0.0.1',0),cls.agent.Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=2)
        super().tearDownClass()

    def request(self,path,origin='http://127.0.0.1:8000',token=True,method='GET',data=None,host=None):
        headers={'Origin':origin}
        if token: headers['X-Sampling-Agent-Token']=self.agent.AGENT_TOKEN
        if host: headers['Host']=host
        req=urllib.request.Request(self.url+path,data=data,headers=headers,method=method)
        try: response=urllib.request.urlopen(req,timeout=5)
        except urllib.error.HTTPError as error: response=error
        return response.status,dict(response.headers),response.read()

    def test_token_origin_and_host_required(self):
        self.assertEqual(self.request('/status',token=False)[0],401)
        self.assertEqual(self.request('/status',origin='https://untrusted.example')[0],403)
        self.assertEqual(self.request('/status',host='rebind.example')[0],403)

    def test_cors_private_network_preflight_only_allowed_origin(self):
        code,headers,_=self.request('/status',method='OPTIONS',token=False)
        self.assertEqual(code,204)
        self.assertEqual(headers['Access-Control-Allow-Origin'],'http://127.0.0.1:8000')
        self.assertEqual(headers['Access-Control-Allow-Private-Network'],'true')
        self.assertEqual(self.request('/status',method='OPTIONS',origin='https://untrusted.example')[0],403)

    def test_unknown_job_and_invalid_collection_return_business_errors(self):
        self.assertEqual(self.request('/jobs/00000000-0000-0000-0000-000000000000')[0],404)
        code,_,body=self.request('/collect',method='POST',data=b'{}')
        self.assertEqual(code,400);self.assertIn('error',json.loads(body))
        code,_,body=self.request('/pdf',method='POST',data=json.dumps({'records':[{'paper_id':'P001','url':'https://untrusted.example/full.pdf'}]}).encode())
        self.assertEqual(code,400);self.assertIn('error',json.loads(body))

    def test_restart_recovers_task_without_manufacturing_records(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(self.agent,'RUNTIME',Path(temp)),patch.object(self.agent,'JOBS',{}):
            job={'job_id':'12345678','status':'running','records':[],'kind':'collect','log':[]}
            self.agent._save(job);self.agent.load_jobs()
            recovered=self.agent.JOBS['12345678']
            self.assertEqual(recovered['status'],'stopped');self.assertEqual(recovered['records'],[])

    def test_bundled_engine_located_without_sibling_checkout(self):
        self.assertEqual(self.agent._find_engine_root(),(settings.BASE_DIR/'vendor/sample_llm').resolve())

    def test_corrupt_component_has_status_and_failed_job_without_http_500(self):
        cnki, _ = self.agent._engine()
        finished = threading.Event()
        original_finish = self.agent._finish_error

        def finish(jid, error):
            original_finish(jid, error)
            finished.set()

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'sample_llm'; root.mkdir()
            with (patch.object(cnki, 'ROOT', root), patch.object(cnki, '_stream') as stream,
                  patch.object(cnki, '_popen') as popen,
                  patch.object(self.agent, 'RUNTIME', Path(temp) / 'jobs'),
                  patch.object(self.agent, 'JOBS', {}),
                  patch.object(self.agent, '_finish_error', side_effect=finish)):
                code, _, body = self.request('/status')
                self.assertEqual(code, 200)
                state = json.loads(body)
                self.assertFalse(state['engine_ready'])
                self.assertIn('完整性校验失败', state['package']['integrity_error'])
                code, _, body = self.request('/install', method='POST', data=b'{}')
                self.assertEqual(code, 202)
                job_id = json.loads(body)['job_id']
                self.assertTrue(finished.wait(timeout=5))
                code, _, body = self.request('/jobs/' + job_id)
                self.assertEqual(code, 200)
                self.assertEqual(json.loads(body)['status'], 'failed')
                self.assertIn('完整性校验失败', json.loads(body)['message'])
                self.assertEqual(self.request('/login/open', method='POST', data=b'{}')[0], 400)
                stream.assert_not_called()
                popen.assert_not_called()
