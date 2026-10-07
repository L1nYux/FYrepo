import io
import json
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings, TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import AssistantJob, PoolModel, Provider
from .agent import worker
from .network import json_events, TransportError
from .providers import invoke, normalize


class StreamingTests(SimpleTestCase):
    def model(self,protocol='openai'):
        return SimpleNamespace(provider=SimpleNamespace(protocol=protocol,base_url='https://example.com/v1'),model_id='test',output_parameter='max_tokens')

    def chunks(self):
        return [
            {'id':'test-id','choices':[{'delta':{'reasoning_content':'分析'}}]},
            {'choices':[{'delta':{'content':'答'}}]},
            {'choices':[{'delta':{'content':'案'},'finish_reason':'stop'}]},
            {'choices':[],'usage':{'prompt_tokens':10,'completion_tokens':20}},
        ]

    @patch('aihub.providers.json_events')
    def test_live_reasoning_text_and_usage(self,events):
        events.return_value=self.chunks();updates=[]
        result=invoke(self.model(),'fake',[{'role':'user','content':'hi'}],[],32,on_progress=updates.append)
        self.assertEqual(result['text'],'答案');self.assertEqual(result['reasoning'],'分析')
        self.assertEqual(updates[0],{'text':'','reasoning':'分析'});self.assertEqual(result['counts']['output_tokens'],20)
        self.assertTrue(events.call_args.args[2]['stream']);self.assertTrue(events.call_args.args[2]['stream_options']['include_usage'])

    @patch('aihub.providers.json_events')
    def test_glm_native_stream_usage_needs_no_extra_option(self,events):
        events.return_value=self.chunks();model=self.model();model.provider.base_url='https://open.bigmodel.cn/api/paas/v4'
        result=invoke(model,'fake',[],[],32,on_progress=lambda _:None)
        self.assertNotIn('stream_options',events.call_args.args[2]);self.assertEqual(result['counts']['output_tokens'],20)

    @patch('aihub.providers.json_events')
    def test_fragmented_tools_and_reasoning_roundtrip(self,events):
        chunks=self.chunks();chunks[1]['choices'][0]['delta']['tool_calls']=[{'index':0,'id':'tool1','function':{'name':'read_','arguments':'{"id":'}}]
        chunks[2]['choices'][0]['delta']['tool_calls']=[{'index':0,'function':{'name':'record','arguments':'1}'}}]
        events.return_value=chunks
        result=invoke(self.model(),'fake',[],[],32,on_progress=lambda _:None)
        self.assertEqual(result['tool_calls'][0]['function'],{'name':'read_record','arguments':'{"id":1}'})
        self.assertEqual(result['assistant_message']['reasoning_content'],'分析')

    @patch('aihub.providers.json_events')
    def test_inline_minimax_think_is_separate_and_original_retained(self,events):
        events.return_value=[{'choices':[{'delta':{'content':p},**({'finish_reason':'stop'} if i==4 else {})}]} for i,p in enumerate(['<th','ink>','思考','</think>','回答'])]
        updates=[];result=invoke(self.model(),'fake',[],[],32,on_progress=updates.append)
        self.assertEqual(result['text'],'回答');self.assertEqual(result['reasoning'],'思考')
        self.assertEqual(updates[0]['text'],'');self.assertEqual(result['assistant_message']['content'],'<think>思考</think>回答')

    @patch('aihub.providers.json_events')
    def test_interrupted_or_missing_finish_never_retries(self,events):
        events.return_value=self.chunks()[:2]
        with self.assertRaises(TransportError) as caught:invoke(self.model(),'fake',[],[],32,on_progress=lambda _:None)
        self.assertTrue(caught.exception.uncertain);self.assertEqual(events.call_count,1)

    @patch('aihub.providers.json_events')
    def test_single_request_json_fallback(self,events):
        events.return_value=[{'choices':[{'message':{'content':'完整回复','reasoning_content':'思考'}}],'usage':{'prompt_tokens':1,'completion_tokens':2}}]
        result=invoke(self.model(),'fake',[],[],32,on_progress=lambda _:None)
        self.assertEqual(result['text'],'完整回复');self.assertEqual(events.call_count,1)

    def test_non_stream_vendor_reasoning(self):
        result=normalize(self.model('anthropic'),{'content':[{'type':'thinking','thinking':'摘要'},{'type':'text','text':'正文'}]})
        self.assertEqual(result['reasoning'],'摘要');self.assertEqual(result['text'],'正文')
        result=normalize(self.model('gemini'),{'candidates':[{'content':{'parts':[{'thought':True,'text':'摘要'},{'text':'正文'}]}}]})
        self.assertEqual(result['reasoning'],'摘要');self.assertEqual(result['text'],'正文')

    @override_settings(DEBUG=True)
    @patch('aihub.network.build_opener')
    def test_sse_boundaries_comments_and_unicode(self,opener):
        raw=b':heartbeat\r\n\r\n'+('data: '+json.dumps(self.chunks()[0],ensure_ascii=False)+'\r\n\r\n').encode()+b'data: [DONE]\n\n'
        response=io.BytesIO(raw);response.headers={'Content-Type':'text/event-stream'}
        opener.return_value.open.return_value=response
        self.assertEqual(list(json_events('http://localhost/v1',{},{})),self.chunks()[:1])

    @override_settings(DEBUG=True)
    @patch('aihub.network.build_opener')
    def test_malformed_stream_is_uncertain(self,opener):
        response=io.BytesIO(b'data: not-json\n\n');response.headers={'Content-Type':'text/event-stream'}
        opener.return_value.open.return_value=response
        with self.assertRaises(TransportError) as caught:list(json_events('http://localhost/v1',{},{}))
        self.assertTrue(caught.exception.uncertain)


class WorkerProgressTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('stream-member')
        from .testing_private_history import personal_scope
        personal_scope(self,self.user)
        self.model=PoolModel.objects.create(provider=Provider.objects.create(name='Test',base_url='https://example.com/v1'),model_id='test')
        self.job=AssistantJob.objects.create(user=self.user,user_text='hello')

    @patch('aihub.agent.CAPACITY')
    @patch('aihub.agent.connections.close_all')
    @patch('aihub.agent.close_old_connections')
    @patch('aihub.agent.execute')
    @patch('aihub.agent.run_tool',return_value={})
    def test_progress_persisted_and_thinking_preserved_for_tool_turn(self,tool,execute,*_):
        calls=[]
        def upstream(user,model,messages,tools,**kwargs):
            calls.append(messages.copy());kwargs['on_progress']({'text':'正文','reasoning':'思考'},True)
            snapshot=AssistantJob.objects.get(pk=self.job.pk).result['progress']
            self.assertEqual(snapshot['text'],'正文');self.assertTrue(snapshot['reasoning'].endswith('思考'))
            if len(calls)==1:
                tool_calls=[{'id':'1','type':'function','function':{'name':'my_workspace','arguments':'{}'}}]
                return {'text':'','reasoning':'思考','tool_calls':tool_calls,'assistant_message':{'role':'assistant','content':'','reasoning_content':'思考','tool_calls':tool_calls},'status':'success','counts':None,'cost_cny':'0'}
            return {'text':'最终','tool_calls':[],'status':'success','counts':None,'cost_cny':'0'}
        execute.side_effect=upstream
        worker(self.job.pk,self.user.pk,self.model.pk,[{'role':'user','content':'hello'}],None)
        self.job.refresh_from_db();self.assertEqual(self.job.state,'done')
        self.assertEqual(self.job.result['reasoning'],'思考');self.assertEqual(self.job.result['text'],'最终')
        self.assertEqual(next(m for m in calls[1] if m['role']=='assistant')['reasoning_content'],'思考')

    @patch('aihub.agent.CAPACITY')
    @patch('aihub.agent.connections.close_all')
    @patch('aihub.agent.close_old_connections')
    @patch('aihub.agent.execute')
    @patch('aihub.agent.run_tool',return_value={})
    def test_failure_keeps_partial_progress_without_automatic_retry(self,tool,execute,*_):
        def broken(*args,**kwargs):
            kwargs['on_progress']({'text':'部分正文','reasoning':'思考'},True)
            raise ValidationError('模拟断流')
        execute.side_effect=broken
        worker(self.job.pk,self.user.pk,self.model.pk,[{'role':'user','content':'hello'}],None)
        self.job.refresh_from_db();self.assertEqual(self.job.state,'error')
        self.assertEqual(self.job.result['progress']['text'],'部分正文');self.assertEqual(execute.call_count,1)
