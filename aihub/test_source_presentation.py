from decimal import Decimal
from django.test import SimpleTestCase, TestCase
from django.contrib.auth.models import User
from .presentation import clean_response, display_result
from .agent import collect_sources
from .models import PoolSettings, BudgetWeek
from .service import week_now
from .usage import activity

class SourcePresentationTests(SimpleTestCase):
    def test_protocol_removed_but_code_retained(self):
        value='正文\n</search_results>\n</tool_name>\n</\n代码： `<tool_name>`\n```xml\n<search_results>example</search_results>\n```'
        cleaned=clean_response(value)
        self.assertTrue(cleaned.startswith('正文'))
        self.assertNotIn('</tool_name>',cleaned)
        self.assertIn('`<tool_name>`',cleaned)
        self.assertIn('<search_results>example</search_results>',cleaned)
    def test_stream_partial_protocol_never_shows(self):
        for suffix in ['</search_','</tool_na','</tool_name>']:
            self.assertEqual(clean_response('答案'+suffix),'答案')
    def test_only_adjacent_exact_duplicate_paragraphs_removed(self):
        paragraph='这是足够长的一段结论，不能重复出现两遍。'
        self.assertEqual(clean_response(paragraph+'\n\n'+paragraph),paragraph)
        self.assertIn('引用',clean_response(paragraph+'\n\n引用\n\n'+paragraph))
    def test_display_does_not_mutate_billing_or_saved_history(self):
        value={'text':'答案</tool_name>','progress':{'text':'临时</search_results>'},'cost_cny':'0.123','calls':2}
        self.assertEqual(display_result(value)['progress']['text'],'临时')
        self.assertEqual(display_result(value)['cost_cny'],'0.123')
        self.assertIn('</tool_name>',value['text'])
    def test_unique_citations_and_read_status_use_actual_sources(self):
        sources={};one={'kind':'web','id':'https://one.example/','url':'https://one.example/','title':'One'}
        collect_sources({'results':[{'source':one,'snippet':'摘要'},{'source':one}]},sources)
        self.assertEqual(len(sources),1);self.assertFalse(next(iter(sources.values()))['read'])
        collect_sources({'source':one,'content':'读到的正文'},sources)
        self.assertTrue(next(iter(sources.values()))['read']);self.assertEqual(next(iter(sources.values()))['citation'],1)
        self.assertEqual(next(iter(sources.values()))['snippet'],'摘要')

class ActivitySnapshotTests(TestCase):
    def test_old_unknown_limits_are_marked_as_estimates(self):
        user=User.objects.create_user('activity');PoolSettings.objects.create(pk=1,default_weekly_limit=20)
        row=activity(user)['days'][-1]
        self.assertTrue(row['limit_estimated']);self.assertEqual(Decimal(row['weekly_limit']),20)
    def test_recorded_week_limit_survives_later_plan_changes(self):
        user=User.objects.create_user('activity');PoolSettings.objects.create(pk=1,default_weekly_limit=30)
        BudgetWeek.objects.create(scope='user:'+str(user.pk),week=week_now(),base_limit_snapshot=20,base_limit_recorded=True)
        row=activity(user)['days'][-1]
        self.assertFalse(row['limit_estimated']);self.assertEqual(Decimal(row['weekly_limit']),20)

class WorkerSourceBoundaryTests(TestCase):
    def test_tool_turn_prose_is_not_the_final_answer_and_sources_are_numbered(self):
        from unittest.mock import patch
        from contextlib import ExitStack
        from .models import Provider,PoolModel,AssistantJob
        from .agent import worker
        user=User.objects.create_user('source-worker');model=PoolModel.objects.create(provider=Provider.objects.create(name='Test',base_url='https://example.com/v1'),model_id='test');job=AssistantJob.objects.create(user=user,user_text='联网')
        source={'kind':'web','id':'https://one.example/','url':'https://one.example/','title':'来源'}
        calls=[{'id':'1','function':{'name':'search_web','arguments':'{"query":"测试"}'}},{'id':'2','function':{'name':'read_web','arguments':'{"url":"https://one.example/"}'}}]
        replies=[{'text':'临时工具内容</tool_name>','tool_calls':calls,'status':'success','cost_cny':'0','counts':None},{'text':'最终答案 [1]</search_results>','tool_calls':[],'status':'success','cost_cny':'0','counts':None}]
        def tool(_user,name,args):
            if name=='search_web':return {'results':[{'source':source,'snippet':'真实摘要'}]}
            if name=='read_web':return {'source':source,'content':'网页正文'}
            return {}
        with ExitStack() as stack:
            for name in ['CAPACITY','connections.close_all','close_old_connections']:stack.enter_context(patch('aihub.agent.'+name))
            stack.enter_context(patch('aihub.agent.run_tool',side_effect=tool));execute=stack.enter_context(patch('aihub.agent.execute',side_effect=replies))
            worker(job.pk,user.pk,model.pk,[{'role':'user','content':'联网'}],None)
        job.refresh_from_db();self.assertEqual(job.result['text'],'最终答案 [1]');self.assertEqual(len(job.result['sources']),1);self.assertTrue(job.result['sources'][0]['read']);self.assertEqual(job.result['sources'][0]['citation'],1)
        self.assertEqual([s.get('tool') for s in job.result['activity'][1:]],['search_web','read_web','read_web'])
        self.assertEqual([s.get('count') for s in job.result['activity'][1:]],[1,1,1])
        self.assertTrue(job.result['activity'][-1]['cached'])
        self.assertIn('"citation": 1',execute.call_args_list[1].args[2][-1]['content'])
    def test_historical_reply_cleanup_does_not_change_saved_result(self):
        from django.urls import reverse
        from .models import AssistantJob,AssistantConversation
        user=User.objects.create_user('history-cleanup');conversation=AssistantConversation.objects.create(user=user,title='历史');job=AssistantJob.objects.create(user=user,conversation=conversation,user_text='问题',state='done',result={'text':'答案</tool_name>','cost_cny':'0.123'})
        self.client.force_login(user);data=self.client.get(reverse('ai_conversation',args=[conversation.pk])).json()
        self.assertEqual(data['messages'][-1]['text'],'答案');job.refresh_from_db();self.assertEqual(job.result['text'],'答案</tool_name>')
