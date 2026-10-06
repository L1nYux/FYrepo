from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError, PermissionDenied
from .tool_policy import supports_tools, requirements, pending, promise_only, outcome, from_history
from .models import Provider, PoolModel, AssistantJob
from .agent import worker
from .providers import normalize, invoke, native_payload
from .presentation import tool_protocol_leak, clean_response
from .tool_policy import search_query


PROVIDERS=[('https://api.minimaxi.com/v1','MiniMax-M3'),('https://api.minimax.io/v1','MiniMax-M2.7'),('https://dashscope.aliyuncs.com/compatible-mode/v1','qwen3.8-flash'),('https://open.bigmodel.cn/api/paas/v4','glm-5.3'),('https://api.deepseek.com','deepseek-chat'),('https://api.openai.com/v1','gpt-5'),('https://api.anthropic.com/v1','claude-sonnet-4'),('https://generativelanguage.googleapis.com/v1beta','gemini-2.5-flash')]


class ToolPolicyTests(SimpleTestCase):
    def test_known_text_models_without_capability_metadata(self):
        for url,name in PROVIDERS:
            with self.subTest(name=name): self.assertTrue(supports_tools(SimpleNamespace(base_url=url),name))
    def test_catalog_explicit_capability_overrides_inference(self):
        provider=SimpleNamespace(base_url='https://api.minimaxi.com/v1')
        self.assertFalse(supports_tools(provider,'MiniMax-M3',{'supports_tools':False}))
        self.assertFalse(supports_tools(provider,'MiniMax-M3',{'supported_parameters':[]}))
        self.assertTrue(supports_tools(provider,'custom',{'supported_parameters':['tools']}))
    def test_unknown_and_nonchat_models_are_not_guessed(self):
        for url,name in [('https://proxy.example/v1','custom'),('https://dashscope.aliyuncs.com/compatible-mode/v1','qwen3-tts-flash'),('https://api.minimaxi.com/v1','MiniMax-M2-her')]:
            self.assertFalse(supports_tools(SimpleNamespace(base_url=url),name))
    def test_discovery_uses_shared_capability_policy(self):
        from .discovery import fetch_models
        with patch('aihub.discovery.json_request',return_value={'data':[{'id':'MiniMax-M3'}]}):
            rows,_=fetch_models(SimpleNamespace(base_url=PROVIDERS[0][0],protocol='openai'),'fake')
        self.assertTrue(rows[0]['supports_tools'])
    def test_explicit_requests_cover_web_workspace_records_and_attachments(self):
        self.assertEqual(requirements('你能搜索有关福州一中的信息吗')[0]['tool'],'search_web')
        self.assertEqual(requirements('请读 https://example.com/page。')[0]['args']['url'],'https://example.com/page')
        self.assertEqual(requirements('搜索聊天中关于福州的消息')[0]['kind'],'message')
        self.assertEqual(requirements('读取附件 #12')[0]['args']['id'],12)
        self.assertEqual(requirements('查看任务 #3')[0]['args'],{'kind':'task','id':3})
    def test_normal_chat_code_and_negated_requests_do_not_trigger_network(self):
        for text in ['你好','搜索功能如何实现','请翻译：你能搜索学校的信息吗','不要联网搜索，直接解释概念','```search https://example.com```']:
            self.assertEqual(requirements(text),[],text)
    def test_only_actual_matching_tool_outcomes_satisfy_requests(self):
        need={'tool':'read_record','args':{'kind':'task','id':3}}
        self.assertTrue(pending(need,[{'tool':'read_record','kind':'project','id':3,'status':'success'}]))
        self.assertTrue(pending(need,[{'tool':'read_record','kind':'task','id':3,'status':'running'}]))
        self.assertFalse(pending(need,[{'tool':'read_record','kind':'task','id':3,'status':'error'}]))
    def test_promises_are_not_confused_with_answers_or_code(self):
        for text in ['我来帮你搜索福州一中的资料。','好的，我先读取附件。','Let me search for that.']:
            self.assertTrue(promise_only(text),text)
        for text in ['搜索失败，无法读取。','我查到了以下结果：学校资料。','代码：`我来搜索`','福州一中位于福州。']:
            self.assertFalse(promise_only(text),text)
    def test_outcomes_distinguish_empty_failure_and_success(self):
        for value,status in [({'results':[]},'empty'),({'error':'不可用'},'error'),({'results':[{'source':{'kind':'web'}}]},'success')]:
            self.assertEqual(outcome('search_web',{'query':'学校'},value)['status'],status)
    def test_all_protocols_preserve_truncation_reason(self):
        for protocol,raw in [('openai',{'choices':[{'message':{'content':'我来搜索'},'finish_reason':'length'}]}),('anthropic',{'content':[],'stop_reason':'max_tokens'}),('gemini',{'candidates':[{'content':{'parts':[]},'finishReason':'MAX_TOKENS'}]})]:
            self.assertIn(normalize(SimpleNamespace(provider=SimpleNamespace(protocol=protocol)),raw)['finish_reason'],('length','max_tokens','MAX_TOKENS'))
    def test_personal_account_queries_are_not_sent_to_public_search(self):
        self.assertEqual(requirements('查一下我的邮箱')[0]['tool'],'my_workspace')
        self.assertEqual(requirements('搜索公共讨论里的消息')[0]['tool'],'search_workspace')
        self.assertEqual(requirements('搜索福州一中官网的公告')[0]['tool'],'search_web')
    def test_short_followups_preserve_the_original_tool_request(self):
        history=[{'role':'user','content':'搜索福州一中'},{'role':'assistant','content':'我来帮你搜索。'},{'role':'user','content':'？'}]
        self.assertEqual(from_history(history)[0]['tool'],'search_web')
        history[-1]['content']='现在聊别的话题';self.assertEqual(from_history(history),[])
    def test_streaming_preserves_length_finish(self):
        model=SimpleNamespace(provider=SimpleNamespace(protocol='openai',base_url='https://example.com/v1'),model_id='test',output_parameter='max_tokens')
        with patch('aihub.providers.json_events',return_value=[{'choices':[{'delta':{'content':'我来搜索'},'finish_reason':'length'}],'usage':{'prompt_tokens':1,'completion_tokens':2}}]):
            result=invoke(model,'fake',[],[],32,on_progress=lambda _:None)
        self.assertEqual(result['finish_reason'],'length')

    def test_query_wrappers_keep_the_subject_and_spelling(self):
        cases={'能帮我查一下什么是brenchmark吗':'brenchmark','你能搜索有关福州一中的信息吗':'福州一中','请联网搜索千问价格':'千问价格','Can you search for benchmark?':'benchmark','查一下能量守恒的信息':'能量守恒','搜索加拿大的信息':'加拿大','能量守恒':'能量守恒','搜索引擎排名':'搜索引擎排名','搜索酒吧':'酒吧'}
        for text,expected in cases.items():
            with self.subTest(text=text): self.assertEqual(search_query(text),expected)
    def test_protocol_detection_preserves_code_and_never_executes_json(self):
        leak='<]minimax[>[\n{"name":"search_web","arguments":{"query":"benchmark 机器学习 大模型测评","count":6,"recency_days":1}}'
        self.assertTrue(tool_protocol_leak(leak))
        self.assertFalse(tool_protocol_leak('示例：```json\n'+leak+'\n```'))
        self.assertEqual(clean_response('我需要继续查找。'+leak),'我需要继续查找。')
        self.assertIn('search_web',clean_response('```json\n'+leak+'\n```'))
    def test_minimax_tool_turn_uses_complete_native_message(self):
        model=SimpleNamespace(provider=SimpleNamespace(protocol='openai',base_url='https://api.minimaxi.com/v1'),model_id='MiniMax-M3',output_parameter='max_tokens')
        raw={'id':'native-turn','choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'reasoning_details':[{'type':'reasoning.text','text':'查找 benchmark','signature':'keep-me'}],'tool_calls':[{'id':'call-one','type':'function','function':{'name':'search_web','arguments':'{"query":"benchmark"}'}}]}}],'usage':{'prompt_tokens':20,'completion_tokens':10}}
        progress=[]
        with patch('aihub.providers.json_request',return_value=raw) as request,patch('aihub.providers.json_events') as events:
            value=invoke(model,'fake',[],[{'type':'function','function':{'name':'search_web'}}],200,on_progress=progress.append)
        events.assert_not_called()
        self.assertFalse(request.call_args.args[2]['stream'])
        self.assertTrue(request.call_args.args[2]['reasoning_split'])
        self.assertEqual(value['tool_calls'][0]['function']['name'],'search_web')
        _,payload=native_payload(model,[value['assistant_message']],[],200)
        self.assertEqual(payload['messages'][0]['reasoning_details'],raw['choices'][0]['message']['reasoning_details'])
    def test_minimax_cn_model_capability_is_recognized(self):
        self.assertTrue(supports_tools(SimpleNamespace(base_url='https://api.minimax.cn/v1'),'MiniMax-M3'))


class ToolCompletionTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('tool-policy')
        self.source={'kind':'web','id':'https://example.com/school','url':'https://example.com/school','title':'学校资料'}
    def reply(self,text='学校资料 [1]',tools=None,**extra):
        return {'text':text,'tool_calls':tools or [],'status':'success','cost_cny':'0.01','counts':None,**extra}
    def call(self,name,args,id='call-1'):
        import json
        return {'id':id,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}
    def run_job(self,prompt,replies,tool=None,enabled=True,url='https://example.com/v1',identifier='test'):
        provider=Provider.objects.create(name='Test-'+str(Provider.objects.count()),base_url=url);model=PoolModel.objects.create(provider=provider,model_id=identifier,supports_tools=enabled)
        job=AssistantJob.objects.create(user=self.user,user_text=prompt)
        def read(user,name,args):
            if name=='my_workspace':return {'account':{'username':user.username}}
            if tool:return tool(user,name,args)
            if name=='search_web':return {'results':[{'source':self.source,'snippet':'摘要'}]}
            if name=='read_web':return {'source':self.source,'content':'公开正文'}
            if name=='read_attachment':return {'source':{'kind':'attachment','id':args['id'],'title':'附件'},'content':'附件正文'}
            if name=='read_record':return {'source':{'kind':args['kind'],'id':args['id'],'title':'详情'},'body':'详情正文'}
            if name=='search_workspace':return {'results':[{'source':{'kind':args['kind'],'id':1,'title':'工作台资料'}}]}
            raise ValidationError('未知工具')
        with ExitStack() as stack:
            for name in ['CAPACITY','connections.close_all','close_old_connections']:stack.enter_context(patch('aihub.agent.'+name))
            read_mock=stack.enter_context(patch('aihub.agent.run_tool',side_effect=read));execute=stack.enter_context(patch('aihub.agent.execute',side_effect=replies))
            worker(job.pk,self.user.pk,model.pk,[{'role':'user','content':prompt}],None)
        job.refresh_from_db();return job,execute,read_mock
    def test_explicit_search_works_for_all_providers_with_native_tools_disabled(self):
        for url,name in PROVIDERS:
            with self.subTest(name=name):
                job,execute,read=self.run_job('你能搜索有关福州一中的信息吗',[self.reply()],enabled=False,url=url,identifier=name)
                self.assertEqual(job.state,'done');self.assertEqual(execute.call_count,1);self.assertEqual(job.result['sources'][0]['citation'],1)
                self.assertEqual(sum(c.args[1]=='search_web' for c in read.call_args_list),1)
                self.assertEqual(execute.call_args.args[3],[])
                self.assertIn('学校资料',execute.call_args.args[2][-1]['content'])
    def test_missing_tool_is_completed_before_accepting_final_answer(self):
        job,execute,read=self.run_job('搜索福州一中',[self.reply('我来帮你搜索福州一中的资料。'),self.reply()])
        self.assertEqual(job.state,'done');self.assertEqual(execute.call_count,2);self.assertEqual(job.result['calls'],2)
        self.assertEqual(job.result['cost_cny'],'0.02');self.assertEqual(sum(c.args[1]=='search_web' for c in read.call_args_list),1)
    def test_repeated_promise_fails_after_one_correction(self):
        job,execute,read=self.run_job('搜索福州一中',[self.reply('我来帮你搜索资料。')]*2)
        self.assertEqual(job.state,'error');self.assertEqual(execute.call_count,2);self.assertIn('只返回了开场',job.result['error'])
    def test_workspace_search_is_checked_like_web_search(self):
        call=self.call('search_workspace',{'kind':'message','query':'福州'})
        job,execute,read=self.run_job('搜索聊天中有关福州的消息',[self.reply('我来查找聊天记录。'),self.reply('',[call]),self.reply('工作台实际消息结果')])
        self.assertEqual(job.state,'done');self.assertEqual(execute.call_count,3)
        self.assertTrue(any(a['tool']=='search_workspace' and a['status']=='success' for a in job.result['activity']))
    def test_disabled_workspace_tools_are_honestly_unavailable(self):
        job,execute,read=self.run_job('搜索聊天记录',[],enabled=False)
        self.assertEqual(job.state,'error');self.assertIn('未启用工具',job.result['error']);self.assertEqual(execute.call_count,0)
    def test_attachment_guard_executes_permission_checked_reader(self):
        job,execute,read=self.run_job('读取附件 #12',[self.reply('我来读取附件。'),self.reply('附件正文摘要')])
        self.assertEqual(job.state,'done');self.assertEqual(sum(c.args[1]=='read_attachment' for c in read.call_args_list),1)
    def test_permission_failure_does_not_retry_or_claim_success(self):
        def denied(*args):raise PermissionDenied
        job,execute,read=self.run_job('读取附件 #12',[self.reply('我来读取附件。')],tool=denied)
        self.assertEqual(job.state,'error');self.assertIn('无权',job.result['error']);self.assertEqual(execute.call_count,0)
    def test_empty_and_failed_search_stop_without_billable_call(self):
        for value in [{'error':'搜索服务不可用'},{'results':[]}]:
            job,execute,read=self.run_job('搜索福州一中',[],tool=lambda *args:value,enabled=False)
            self.assertEqual(job.state,'error');self.assertEqual(execute.call_count,0)
    def test_ordinary_chat_does_not_add_tool_or_model_calls(self):
        job,execute,read=self.run_job('你好',[self.reply('你好！')])
        self.assertEqual(job.state,'done');self.assertEqual(execute.call_count,1);self.assertEqual(read.call_count,1)
    def test_duplicate_native_calls_use_one_real_read(self):
        tools=[self.call('read_web',{'url':'https://example.com/school'},str(i)) for i in range(2)]
        job,execute,read=self.run_job('请读 https://example.com/school',[self.reply('',tools),self.reply()])
        self.assertEqual(job.state,'done');self.assertEqual(sum(c.args[1]=='read_web' for c in read.call_args_list),1)
        self.assertTrue(job.result['activity'][-1]['cached'])
    def test_unknown_billing_never_triggers_followup_or_fallback(self):
        job,execute,read=self.run_job('搜索福州一中',[self.reply('我来搜索资料。',status='unknown',cost_cny=None)])
        self.assertEqual(execute.call_count,1);self.assertEqual(read.call_count,3);self.assertTrue(job.result['pending_cost'])
        self.assertEqual([c.args[1] for c in read.call_args_list],['my_workspace','search_web','read_web'])
        self.assertNotIn('我来搜索',job.result['text'])
    def test_truncated_reply_fails_without_automatic_paid_retry(self):
        for reason in ['length','max_tokens','MAX_TOKENS']:
            job,execute,read=self.run_job('搜索福州一中',[self.reply('我来搜索资料。',finish_reason=reason)])
            self.assertEqual(job.state,'error');self.assertEqual(execute.call_count,1);self.assertIn('长度上限',job.result['error'])
    def test_record_request_matches_kind_and_id(self):
        job,execute,read=self.run_job('查看任务 #3',[self.reply('我来读取任务。'),self.reply('实际任务详情')])
        self.assertEqual(job.state,'done');self.assertTrue(any(a.get('kind')=='task' and a.get('id')==3 for a in job.result['activity']))
    def test_unknown_native_tool_is_not_executed(self):
        job,execute,read=self.run_job('你好',[self.reply('',[self.call('shell',{'command':'bad'})]),self.reply('无法执行该操作')])
        self.assertEqual(read.call_count,1);self.assertEqual(job.result['activity'][-1]['status'],'error');self.assertIn('部分工具未完成',job.result['warning'])

    def test_empty_final_reply_is_an_error_with_no_retry(self):
        job,execute,read=self.run_job('你好',[self.reply('')])
        self.assertEqual(job.state,'error');self.assertEqual(execute.call_count,1);self.assertIn('没有返回最终回答',job.result['error'])
    def test_disabled_model_cannot_execute_unsolicited_native_calls(self):
        job,execute,read=self.run_job('你好',[self.reply('',[self.call('read_attachment',{'id':5})])],enabled=False)
        self.assertEqual(job.state,'error');self.assertEqual(read.call_count,1)

    def test_native_background_read_reuses_bootstrap_result(self):
        job,execute,read=self.run_job('查一下我的账户',[self.reply('',[self.call('my_workspace',{})]),self.reply('当前账户 tool-policy')])
        self.assertEqual(job.state,'done');self.assertEqual(read.call_count,1);self.assertTrue(job.result['activity'][-1]['cached'])

    def test_screenshot_textual_call_is_corrected_into_native_call(self):
        leaked='我注意到之前的搜索没有找到相关结果，让我重新搜索 benchmark。<]minimax[>[\n{"name":"search_web","arguments":{"query":"benchmark 机器学习 大模型测评","count":6,"recency_days":1}}'
        native=self.call('search_web',{'query':'benchmark 机器学习 大模型测评'})
        job,execute,read=self.run_job('能帮我查一下什么是brenchmark吗',[self.reply(leaked),self.reply('',[native]),self.reply('Benchmark 是用于比较模型能力的评测基准。 [1]')])
        self.assertEqual(job.state,'done');self.assertEqual(execute.call_count,3)
        queries=[c.args[2]['query'] for c in read.call_args_list if c.args[1]=='search_web']
        self.assertEqual(queries,['brenchmark','benchmark 机器学习 大模型测评'])
        self.assertNotIn('minimax[',job.result['text']);self.assertEqual(job.result['calls'],3)
    def test_repeated_screenshot_protocol_is_error_with_retry(self):
        leaked='<]minimax[>[{"name":"search_web","arguments":{"query":"benchmark"}}'
        job,execute,read=self.run_job('搜索 benchmark',[self.reply(leaked)]*2)
        self.assertEqual(job.state,'error');self.assertIn('格式无效',job.result['error']);self.assertEqual(execute.call_count,2)
        self.assertEqual(sum(c.args[1]=='search_web' for c in read.call_args_list),1)
        self.assertNotIn('arguments',str(job.result.get('progress',{}).get('text','')))
    def test_disabled_tools_never_execute_textual_commands(self):
        leak='<]minimax[>[{"name":"read_attachment","arguments":{"id":123}}'
        job,execute,read=self.run_job('搜索 benchmark',[self.reply(leak),self.reply('Benchmark 是评测基准。')],enabled=False)
        self.assertEqual(job.state,'done');self.assertEqual(execute.call_count,2)
        self.assertFalse(any(c.args[1]=='read_attachment' for c in read.call_args_list))
        self.assertEqual(sum(c.args[1]=='search_web' for c in read.call_args_list),1)
    def test_complete_assistant_message_survives_format_correction(self):
        message={'role':'assistant','content':'我来搜索。','reasoning_details':[{'type':'reasoning.text','text':'保留推理','signature':'s'}]}
        job,execute,read=self.run_job('搜索 benchmark',[self.reply('我来搜索。',assistant_message=message),self.reply('基准概念')])
        self.assertEqual(job.state,'done')
        self.assertTrue(any(m.get('reasoning_details')==message['reasoning_details'] for m in execute.call_args.args[2]))
    def test_textual_protocol_in_code_is_an_example_not_a_tool(self):
        text='工具格式示例：```json\n{"name":"search_web","arguments":{"query":"benchmark"}}\n```'
        job,execute,read=self.run_job('解释这段代码',[self.reply(text)])
        self.assertEqual(job.state,'done');self.assertEqual(execute.call_count,1);self.assertEqual(read.call_count,1)
    def test_native_tool_finish_without_tool_fields_is_not_a_final_answer(self):
        job,execute,read=self.run_job('搜索 benchmark',[self.reply('准备查询',finish_reason='tool_calls')]*2)
        self.assertEqual(job.state,'error');self.assertEqual(execute.call_count,2)

    def test_screenshot_two_stage_failure_can_still_complete_in_four_calls(self):
        leak='之前结果无关，让我重新搜索。<]minimax[>[{"name":"search_web","arguments":{"query":"benchmark"}}'
        native=self.call('search_web',{'query':'benchmark 机器学习 大模型测评'})
        job,execute,read=self.run_job('能帮我查一下什么是brenchmark吗',[self.reply('我来帮你查一下。'),self.reply(leak),self.reply('',[native]),self.reply('Benchmark 是比较模型能力的评测基准。 [1]')])
        self.assertEqual(job.state,'done');self.assertEqual(execute.call_count,4);self.assertEqual(job.result['calls'],4)
        self.assertEqual(job.result['cost_cny'],'0.04')
        self.assertEqual([c.args[2]['query'] for c in read.call_args_list if c.args[1]=='search_web'],['brenchmark','benchmark 机器学习 大模型测评'])
    def test_format_correction_then_repeated_promise_stays_bounded(self):
        leak='<]minimax[>[{"name":"search_web","arguments":{"query":"benchmark"}}'
        job,execute,read=self.run_job('搜索 benchmark',[self.reply(leak),self.reply('我来帮你搜索。'),self.reply('我来帮你搜索。')])
        self.assertEqual(job.state,'error');self.assertEqual(execute.call_count,3)
        self.assertEqual(sum(c.args[1]=='search_web' for c in read.call_args_list),1)

    def test_native_providers_receive_real_search_before_first_model_turn(self):
        for url,name in PROVIDERS:
            with self.subTest(name=name):
                job,execute,read=self.run_job('搜索福州一中',[self.reply()],url=url,identifier=name)
                self.assertEqual(job.state,'done');self.assertEqual(execute.call_count,1)
                self.assertEqual([c.args[1] for c in read.call_args_list],['my_workspace','search_web','read_web'])
                self.assertIn('公开正文',execute.call_args.args[2][-1]['content'])

    def test_agent_can_complete_five_tool_rounds_then_answer(self):
        replies=[self.reply('',[self.call('search_web',{'query':'research '+str(i)},'round-'+str(i))]) for i in range(5)]
        replies.append(self.reply('研究结果 [1]'))
        job,execute,read=self.run_job('搜索 research',replies)
        self.assertEqual(job.state,'done');self.assertEqual(execute.call_count,6)
        self.assertEqual(sum(c.args[1]=='search_web' for c in read.call_args_list),6)
        self.assertEqual(job.result['text'],'研究结果 [1]')
