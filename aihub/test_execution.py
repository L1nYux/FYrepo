"""Durable assistant, steering, replay and routing checks without paid requests."""
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, nullcontext
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections
from django.test import TestCase, TransactionTestCase, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Project, Task, Workspace
from core.tenancy import scope
from . import agent
from .context import fit_context, size, turn_history
from .delegation import issue, execute_operation
from .execution import claim, Journal, LeaseLost, InputsPending, continue_job, can_continue, can_retry, _event
from .inputs import enqueue, retry_history
from .models import AssistantJob, AssistantInput, AssistantConversation, Call, PoolModel, PriceVersion, Provider, AgentOperation
from .network import TransportError
from .routing import execute_assistant, RoutePlan
from .service import settle
from .test_relay_contract import RelayFixture
from .testing_private_history import personal_scope


class ExecutionFixture(RelayFixture):
    def setUp(self):
        super().setUp()
        self.user=self.member
        self.model.supports_tools=True
        self.model.max_output_tokens=256
        self.model.save(update_fields=['supports_tools','max_output_tokens'])
        self.personal=personal_scope(self,self.user)
        with scope(self.space):
            self.project=Project.objects.create(name='Execution project',owner=self.user,created_by=self.user)
        self.grant=issue(self.user,self.project.pk,['create_task'])

    def job(self,phase='prepare',**extra):
        data={'version':1,'phase':phase,'model_id':self.model.pk,
              'input_history':[{'role':'user','content':'开始工作'}],'step':0,'window_steps':0}
        return AssistantJob.objects.create(user=self.user,user_text='开始工作',billing_workspace=self.space,
            preferences={'web':False},execution=data,**extra)

    def result(self,text='完成。',tools=None,**extra):
        return {**super().result(),'text':text,'tool_calls':tools or [],**extra}

    def tool(self,title='One task'):
        return {'id':'task-call','type':'function','function':{'name':'create_task',
            'arguments':json.dumps({'project_id':self.project.pk,'title':title})}}

    def run_job(self,job,replies):
        with ExitStack() as stack:
            stack.enter_context(patch('aihub.agent.close_old_connections'))
            stack.enter_context(patch('aihub.agent.connections.close_all'))
            stack.enter_context(patch('aihub.execution.keep_alive',side_effect=lambda journal:nullcontext()))
            self.reader=stack.enter_context(patch('aihub.agent.run_tool',return_value={'projects':[]}))
            supplier=stack.enter_context(patch('aihub.service.invoke',side_effect=replies))
            agent.worker(job.pk)
        job.refresh_from_db()
        return supplier

    def leased(self,phase='ready',**extra):
        job=self.job(phase,**extra)
        journal=claim(job.pk)
        job.refresh_from_db()
        return job,journal


class DurableExecutionTests(ExecutionFixture,TestCase):
    def test_claim_is_exclusive_and_expired_owner_is_fenced(self):
        job,old=self.leased()
        self.assertIsNone(claim(job.pk))
        AssistantJob.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now()-timezone.timedelta(seconds=1))
        replacement=claim(job.pk)
        self.assertNotEqual(old.token,replacement.token)
        for action in (lambda:old.save('stale'),lambda:old.finish('done',{}),old.check):
            with self.assertRaises(LeaseLost):action()
        replacement.save('fresh',phase='ready')
        self.assertEqual(job.events.filter(kind='fresh').count(),1)

    def test_missing_execution_cannot_be_manufactured_by_queue(self):
        job=self.job();job.execution={};job.save(update_fields=['execution'])
        self.assertIsNone(claim(job.pk));job.refresh_from_db()
        self.assertEqual(job.state,'error')

    def test_interrupted_paid_request_is_not_automatically_resent(self):
        job=self.job('calling')
        supplier=self.run_job(job,[])
        self.assertEqual(job.state,'error');self.assertEqual(supplier.call_count,0)
        self.assertFalse(can_continue(job));self.assertIn('回复未完整保存',job.result['error'])

    def test_unknown_bill_prevents_continue_and_retry(self):
        job=self.job('calling')
        with scope(self.space):
            call=self.admit(token=False)
            Call.objects.filter(pk=call.pk).update(group_id=job.pk)
            settle(call,None,status='unknown')
        self.run_job(job,[])
        self.assertTrue(job.result['pending_cost']);self.assertFalse(can_continue(job));self.assertFalse(can_retry(job))

    def test_confirmed_zero_cost_failure_can_continue_same_job(self):
        job=self.job()
        self.run_job(job,[TransportError('dns_error')])
        self.assertEqual(job.state,'error');self.assertTrue(can_continue(job));self.assertEqual(job.result['calls'],1)
        continued=continue_job(job,self.user)
        self.assertEqual(continued.pk,job.pk)
        self.run_job(job,[self.result()])
        self.assertEqual(job.state,'done');self.assertEqual(job.result['calls'],2)

    def test_resume_after_committed_write_replays_receipt_without_second_task(self):
        job,journal=self.leased('tools',authorization=self.grant)
        tool=self.tool()
        messages=[{'role':'user','content':job.user_text,'_turn':str(job.pk)},
                  {'role':'assistant','content':None,'tool_calls':[tool]}]
        journal.save('model.completed',messages=messages,pending={'text':'','tool_calls':[tool],'status':'success'},tool_index=0)
        receipt=execute_operation(self.user,job,'create_task',json.loads(tool['function']['arguments']))
        AssistantJob.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now()-timezone.timedelta(seconds=1))
        self.run_job(job,[self.result('任务已保存。')])
        self.assertEqual(job.state,'done');self.assertEqual(Task.all_objects.filter(title='One task').count(),1)
        self.assertEqual(AgentOperation.objects.count(),1)
        self.grant.refresh_from_db();self.assertEqual(self.grant.used_operations,1)
        content=[json.loads(row['content']) for row in job.execution['messages'] if row['role']=='tool']
        self.assertTrue(content[0]['replayed']);self.assertEqual(content[0]['receipt'],receipt['receipt'])

    def test_resume_rechecks_revoked_authorization_before_call_or_write(self):
        job=self.job('ready',authorization=self.grant)
        job.state='error';job.save(update_fields=['state'])
        self.grant.revoked_at=timezone.now();self.grant.save(update_fields=['revoked_at'])
        with self.assertRaises(PermissionDenied):continue_job(job,self.user)
        self.assertEqual(Task.all_objects.count(),0)

    def test_terminal_history_keeps_all_steering_and_tool_pairs(self):
        job,journal=self.leased()
        rows=[{'role':'user','content':'old'}, {'role':'assistant','content':'old answer'},
              {'role':'user','content':job.user_text,'_turn':str(job.pk)},
              {'role':'assistant','content':None,'tool_calls':[self.tool()]},
              {'role':'tool','tool_call_id':'task-call','content':'{"saved":true,"receipt":1}'},
              {'role':'user','content':'补充','_turn':str(job.pk)}, {'role':'assistant','content':'完成。'}]
        journal.save('ready',messages=rows)
        journal.finish('done',{'text':'完成。'})
        job.refresh_from_db();history=turn_history(job)
        self.assertEqual([row['content'] for row in history if row['role']=='user'],['开始工作','补充'])
        self.assertEqual(len(history),5)


class SteeringTests(ExecutionFixture,TestCase):
    def test_input_is_durable_idempotent_even_after_completion(self):
        job,journal=self.leased();identifier=str(uuid.uuid4())
        first=enqueue(job,self.user,' 补充 ',identifier)
        again=enqueue(job,self.user,'补充',identifier)
        self.assertEqual(first.pk,again.pk);self.assertEqual(job.inputs.count(),1)
        rows=[];journal.apply_inputs(rows);journal.finish('done',{'text':'完成。'})
        self.assertEqual(enqueue(job,self.user,'补充',identifier).pk,first.pk)
        with self.assertRaises(ValidationError):enqueue(job,self.user,'不同内容',identifier)
        with self.assertRaises(ValidationError):enqueue(job,self.user,'新的要求',str(uuid.uuid4()))

    def test_validation_and_owner_boundary(self):
        job=self.job()
        for text,key in [('',str(uuid.uuid4())),('x'*30001,str(uuid.uuid4())),('ok','bad'),(None,str(uuid.uuid4())),('ok',1)]:
            with self.subTest(text=str(text)[:12]),self.assertRaises(ValidationError):enqueue(job,self.user,text,key)
        with self.assertRaises(PermissionDenied):enqueue(job,self.owner,'No',str(uuid.uuid4()))
        self.assertEqual(job.inputs.count(),0)

    def test_queue_and_total_byte_limits(self):
        job,journal=self.leased()
        for number in range(20):enqueue(job,self.user,str(number),str(uuid.uuid4()))
        with self.assertRaises(ValidationError):enqueue(job,self.user,'overflow',str(uuid.uuid4()))
        rows=[];journal.apply_inputs(rows)
        enqueue(job,self.user,'下一条',str(uuid.uuid4()))
        for _ in range(3):enqueue(job,self.user,'字'*10000,str(uuid.uuid4()))
        with self.assertRaises(ValidationError):enqueue(job,self.user,'字'*10000,str(uuid.uuid4()))

    def test_finalizing_checkpoint_and_input_projection_are_atomic(self):
        job,journal=self.leased();value=enqueue(job,self.user,'补充',str(uuid.uuid4()))
        with self.assertRaises(InputsPending):journal.save('completed',phase='finalizing')
        self.assertEqual(journal.data['phase'],'ready')
        messages=[{'role':'user','content':job.user_text,'_turn':str(job.pk)}]
        journal.apply_inputs(messages);value.refresh_from_db();job.refresh_from_db()
        self.assertEqual(value.state,'applied');self.assertEqual(messages,job.execution['messages'])
        self.assertEqual(journal.apply_inputs(messages),[])
        journal.save('completed',phase='finalizing')
        with self.assertRaises(ValidationError):enqueue(job,self.user,'太晚',str(uuid.uuid4()))

    def test_stop_retains_accepted_text_but_does_not_execute_it(self):
        job,journal=self.leased();value=enqueue(job,self.user,'补充',str(uuid.uuid4()))
        AssistantJob.objects.filter(pk=job.pk).update(cancel_requested=True)
        self.assertEqual(journal.apply_inputs([]),[])
        journal.finish('cancelled',{'text':'已停止。'});value.refresh_from_db()
        self.assertEqual(value.state,'discarded');self.assertEqual(value.text,'补充')
        self.assertEqual(retry_history(job),[{'role':'user','content':'开始工作','_turn':str(job.pk)}])

    def test_input_during_model_request_enters_next_call_and_final_history(self):
        job=self.job();requests=[]
        def supplier(model,key,messages,*args,**kwargs):
            requests.append([dict(row) for row in messages])
            if len(requests)==1:
                enqueue(job,self.user,'回答请简短',str(uuid.uuid4()))
                return self.result('原答案。')
            return self.result('简短答案。')
        self.run_job(job,supplier)
        self.assertEqual(job.state,'done',job.result);self.assertEqual(job.result['text'],'简短答案。')
        self.assertEqual(len(requests),2);self.assertEqual(job.result['calls'],2)
        self.assertEqual([r['content'] for r in requests[1] if r['role']=='user'],['开始工作','回答请简短'])
        self.assertEqual([r['content'] for r in turn_history(job) if r['role']=='user'],['开始工作','回答请简短'])
        self.assertEqual(job.inputs.get().state,'applied')

    def test_input_before_worker_can_cancel_original_forced_read(self):
        job=self.job();job.user_text='读取附件 #12'
        job.execution['input_history']=[{'role':'user','content':job.user_text}]
        job.save(update_fields=['user_text','execution'])
        enqueue(job,self.user,'不用读取了，回答你好即可',str(uuid.uuid4()))
        self.run_job(job,[self.result('你好。')])
        self.assertEqual(job.state,'done',job.result)
        self.assertFalse(any(item.args[1]=='read_attachment' for item in self.reader.call_args_list))

    def test_arriving_input_blocks_new_write_without_spending_grant(self):
        job,journal=self.leased(authorization=self.grant)
        enqueue(job,self.user,'不要创建任务',str(uuid.uuid4()))
        with self.assertRaisesMessage(ValidationError,'补充要求'):
            execute_operation(self.user,job,'create_task',{'project_id':self.project.pk,'title':'No task'})
        self.grant.refresh_from_db();self.assertEqual(self.grant.used_operations,0)
        self.assertEqual(Task.all_objects.count(),0)

    def test_steering_after_tool_response_skips_requested_write_then_returns_pairs(self):
        job=self.job(authorization=self.grant);turns=[]
        def supplier(model,key,messages,*args,**kwargs):
            turns.append([dict(row) for row in messages])
            if len(turns)==1:
                enqueue(job,self.user,'不要创建任务',str(uuid.uuid4()))
                return self.result('',[self.tool()])
            return self.result('已按补充要求停止创建。')
        self.run_job(job,supplier)
        self.assertEqual(job.state,'done',job.result);self.assertEqual(Task.all_objects.count(),0)
        responses=[r for r in turns[1] if r['role']=='tool']
        self.assertEqual(responses[0]['tool_call_id'],'task-call');self.assertIn('补充要求',responses[0]['content'])

    def test_race_at_final_checkpoint_keeps_native_response_and_processes_input(self):
        job=self.job();original=Journal.save;injected=False
        def raced(journal,kind,payload=None,**changes):
            nonlocal injected
            if changes.get('phase')=='finalizing' and not injected:
                injected=True;enqueue(job,self.user,'补充',str(uuid.uuid4()))
            return original(journal,kind,payload,**changes)
        native={'protocol':'anthropic','message':{'content':[{'type':'thinking','thinking':'x','signature':'sig'}]}}
        with patch.object(Journal,'save',raced):
            supplier=self.run_job(job,[self.result(native=native),self.result('补充后答案。')])
        self.assertEqual(job.state,'done');self.assertEqual(supplier.call_count,2)
        self.assertTrue(any(row.get('_native')==native for row in supplier.call_args.args[2]))

    def test_job_events_are_paged_owner_only_and_exclude_arguments(self):
        job=self.job();value=enqueue(job,self.user,'补充',str(uuid.uuid4()))
        job.refresh_from_db()
        for number in range(105):_event(job,'tool.started',{'tool':'read_record','arguments':'private','text':'private'})
        url=reverse('ai_job',args=[job.pk]);first=self.client.get(url)
        self.assertEqual(first.status_code,200)
        page=first.json();self.assertEqual(len(page['events']),100);self.assertTrue(page['has_more_events'])
        self.assertEqual(page['inputs'][0]['id'],str(value.pk));self.assertNotIn('private',json.dumps(page['events']))
        second=self.client.get(url,{'after':page['cursor']}).json()
        self.assertFalse(second['has_more_events']);self.assertGreater(second['cursor'],page['cursor'])
        self.client.force_login(self.owner);self.assertEqual(self.client.get(url).status_code,404)

    def test_append_endpoint_cannot_change_model_or_authorization(self):
        job=self.job();url=reverse('ai_job',args=[job.pk])
        response=self.client.post(url,json.dumps({'action':'append','text':'补充','request_id':str(uuid.uuid4()),'model':self.model.pk}),content_type='application/json')
        self.assertEqual(response.status_code,400);self.assertEqual(job.inputs.count(),0)

    def test_conversation_projection_and_retry_preserve_all_inputs(self):
        conversation=AssistantConversation.objects.create(user=self.user)
        job,journal=self.leased(conversation=conversation)
        for text in ['补充一','补充二']:enqueue(job,self.user,text,str(uuid.uuid4()))
        messages=[{'role':'user','content':job.user_text,'_turn':str(job.pk)}]
        journal.apply_inputs(messages);journal.finish('error',{'error':'temporary'})
        job.refresh_from_db()
        response=self.client.get(reverse('ai_conversation',args=[conversation.pk])).json()
        self.assertEqual([row['text'] for row in response['messages'] if row['role']=='user'],['开始工作','补充一','补充二'])
        self.assertEqual([row['content'] for row in retry_history(job)],['开始工作','补充一','补充二'])


class AssistantRoutingTests(ExecutionFixture,TestCase):
    def backup(self):
        with scope(self.space):
            provider=Provider.objects.create(name='Assistant backup',base_url='https://backup.example.com/v1')
            backup=PoolModel.objects.create(provider=provider,model_id=self.model.model_id,supports_tools=True,max_output_tokens=256)
            PriceVersion.objects.create(model=backup,effective_from=timezone.now(),input_rate=3,output_rate=6,cached_rate=1,cache_write_rate=1)
            self.model.fallback_model=backup;self.model.save(update_fields=['fallback_model'])
        return backup

    def test_agent_uses_relay_fallback_actual_price_and_shared_job_group(self):
        backup=self.backup();job=self.job();models=[]
        def supplier(model,*args,**kwargs):
            models.append(model.pk)
            if model.pk==self.model.pk:raise TransportError('dns_error')
            return self.result()
        self.run_job(job,supplier)
        self.assertEqual(job.state,'done');self.assertEqual(models,[self.model.pk,backup.pk])
        rows=list(Call.all_objects.filter(group_id=job.pk).order_by('created_at'))
        self.assertEqual(len(rows),2);self.assertEqual(rows[0].cost_cny,0);self.assertEqual(rows[1].cost_cny,Decimal('.006'))
        self.assertEqual(job.result['calls'],2);self.assertEqual(Decimal(job.result['cost_cny']),Decimal('.006'))

    def test_partial_output_prevents_automatic_backup(self):
        self.backup();job=self.job()
        def supplier(model,key,messages,*args,**kwargs):
            kwargs['on_progress']({'text':'partial'})
            raise TransportError('dns_error')
        invoked=self.run_job(job,supplier)
        self.assertEqual(job.state,'error');self.assertEqual(invoked.call_count,1)
        self.assertTrue(job.result['pending_cost']);self.assertFalse(can_retry(job))

    def test_signed_history_does_not_move_to_different_connection(self):
        self.backup()
        with scope(self.space),patch('aihub.service.invoke',side_effect=TransportError('dns_error')) as invoked:
            with self.assertRaises(ValidationError):
                execute_assistant(self.user,self.model,[{'role':'assistant','content':'x','_native':{'signature':'sig'}}])
        self.assertEqual(invoked.call_count,1)

    def test_sticky_backup_keeps_native_tool_history_on_the_same_connection(self):
        backup=self.backup();job=self.job();requested=[]
        tool={'id':'read-one','type':'function','function':{'name':'my_workspace','arguments':'{}'}}
        def supplier(model,*args,**kwargs):
            requested.append(model.pk)
            if len(requested)==1:raise TransportError('dns_error')
            if len(requested)==2:return self.result('',[tool],native={'signature':'sig'})
            return self.result('完成。')
        self.run_job(job,supplier)
        self.assertEqual(job.state,'done');self.assertEqual(requested,[self.model.pk,backup.pk,backup.pk])


class ContextBoundaryTests(SimpleTestCase):
    def test_pruning_keeps_current_steering_and_write_receipts_without_orphan_tools(self):
        old=[{'role':'user','content':'old'*1500,'_turn':'old'},
             {'role':'assistant','content':None,'tool_calls':[{'id':'old-tool'}]},
             {'role':'tool','tool_call_id':'old-tool','content':'{"saved":true,"receipt":42,"id":7}'}]
        current=[{'role':'user','content':'new','_turn':'new'},
                 {'role':'assistant','content':None,'tool_calls':[{'id':'new-tool'}]},
                 {'role':'tool','tool_call_id':'new-tool','content':'{"content":"read"}'},
                 {'role':'user','content':'补充','_turn':'new'}]
        with override_settings(WORKBENCH_ASSISTANT_CONTEXT_BYTES=1600):
            value=fit_context([{'role':'system','content':'instructions'}]+old+current,[])
        self.assertEqual([r['content'] for r in value if r['role']=='user'],['new','补充'])
        self.assertTrue(any('42' in r.get('content','') for r in value if r['role']=='system'))
        self.assertEqual([r['tool_call_id'] for r in value if r['role']=='tool'],['new-tool'])

    def test_current_steering_is_not_pruned_to_hide_excess_size(self):
        rows=[{'role':'user','content':'x'*1500,'_turn':'same'},{'role':'user','content':'补充','_turn':'same'}]
        with override_settings(WORKBENCH_ASSISTANT_CONTEXT_BYTES=800),self.assertRaises(ValidationError):fit_context(rows,[])


class ExecutionConcurrencyTests(ExecutionFixture,TransactionTestCase):
    def race(self,functions):
        gate=threading.Barrier(len(functions))
        def run(action):
            connections.close_all()
            try:
                with scope(self.personal):gate.wait(timeout=5);return action()
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            return list(pool.map(run,functions))

    def test_two_workers_have_one_valid_owner(self):
        job=self.job('ready')
        values=self.race([lambda:claim(job.pk),lambda:claim(job.pk)])
        self.assertEqual(sum(value is not None for value in values),1)

    def test_duplicate_append_creates_one_event_and_one_input(self):
        job=self.job();key=str(uuid.uuid4())
        values=self.race([lambda:enqueue(job,self.user,'补充',key),lambda:enqueue(job,self.user,'补充',key)])
        self.assertEqual(values[0].pk,values[1].pk);self.assertEqual(job.inputs.count(),1)
        self.assertEqual(job.events.filter(kind='input.accepted').count(),1)

    def test_concurrent_receipt_replay_creates_one_task(self):
        job,journal=self.leased(authorization=self.grant)
        args={'project_id':self.project.pk,'title':'Concurrent one'}
        values=self.race([lambda:execute_operation(self.user,job,'create_task',args),lambda:execute_operation(self.user,job,'create_task',args)])
        self.assertEqual(values[0]['receipt'],values[1]['receipt']);self.assertEqual(Task.all_objects.filter(title=args['title']).count(),1)
        self.grant.refresh_from_db();self.assertEqual(self.grant.used_operations,1)

    def test_append_and_finalization_never_drop_an_accepted_input(self):
        job,journal=self.leased()
        def append():
            try:enqueue(job,self.user,'补充',str(uuid.uuid4()));return 'accepted'
            except ValidationError:return 'rejected'
        def finish():
            try:journal.save('completed',phase='finalizing');return 'finished'
            except InputsPending:return 'pending'
        added,finalized=self.race([append,finish])
        self.assertIn((added,finalized),[('accepted','pending'),('rejected','finished')])
