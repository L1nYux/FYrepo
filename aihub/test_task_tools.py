from django.core.exceptions import PermissionDenied,ValidationError
from django.test import TestCase
from django.utils import timezone
from core.models import Task
from core.tenancy import scope
from . import test_delegation as fixtures
from .delegation import issue,execute_operation
from .models import AgentOperation,AgentPluginSetting
from .agent import read_record


class TaskDetailsToolTests(TestCase):
    def setUp(self):
        fixtures.DelegationTests.setUp(self)
        self.grant=issue(self.user,self.project.pk,['update_task_details'])
        self.job.authorization=self.grant;self.job.save(update_fields=['authorization'])

    def change(self,**changes):
        return execute_operation(self.user,self.job,'update_task_details',{'task_id':self.task.pk,'expected_updated_at':self.task.updated_at.isoformat(),'description':'新说明',**changes})

    def test_assign_and_schedule_reuses_business_form(self):
        with scope(self.space):self.task.members.add(self.user)
        receipt=self.change(title='新名称',assignee_id=self.user.pk,member_ids=[self.member.pk],due_date='2026-12-01')
        row=Task.all_objects.get(pk=self.task.pk)
        self.assertEqual(row.title,'新名称');self.assertEqual(row.description,'新说明');self.assertEqual(row.assignee,self.user)
        self.assertEqual(str(row.due_date),'2026-12-01');self.assertEqual(list(row.members.values_list('pk',flat=True)),[self.member.pk])
        self.assertEqual(row.project,self.project);self.assertEqual(row.status,Task.OPEN);self.assertEqual(row.progress,0);self.assertTrue(receipt['saved'])

    def test_unspecified_values_are_preserved(self):
        self.change();row=Task.all_objects.get(pk=self.task.pk)
        self.assertEqual(row.title,'Existing task');self.assertEqual(row.assignee,self.member)

    def test_receipt_replay_does_not_repeat_write_or_consume_operations(self):
        first=self.change();second=self.change();self.grant.refresh_from_db()
        self.assertTrue(second['replayed']);self.assertEqual(first['receipt'],second['receipt']);self.assertEqual(self.grant.used_operations,1)

    def test_concurrent_edit_rejects_stale_version(self):
        Task.all_objects.filter(pk=self.task.pk).update(description='他人修改',updated_at=timezone.now())
        with self.assertRaises(ValidationError):self.change()
        self.assertEqual(Task.all_objects.get(pk=self.task.pk).description,'他人修改');self.assertFalse(AgentOperation.objects.exists())

    def test_form_rejects_nonmembers_and_invalid_dates(self):
        from django.contrib.auth.models import User
        outsider=User.objects.create_user('task-outsider')
        for values in ({'assignee_id':outsider.pk},{'member_ids':[outsider.pk]},{'due_date':'not-date'}):
            with self.subTest(values=values),self.assertRaises(ValidationError):self.change(**values)
        self.assertFalse(AgentOperation.objects.exists())

    def test_archived_and_reviewed_tasks_cannot_be_changed(self):
        for status,archived in ((Task.SUBMITTED,None),(Task.COMPLETED,None),(Task.OPEN,timezone.now())):
            Task.all_objects.filter(pk=self.task.pk).update(status=status,archived_at=archived)
            with self.subTest(status=status),self.assertRaises((ValidationError,PermissionDenied)):self.change()

    def test_schema_does_not_allow_reassignment_progress_or_publication(self):
        for values in ({'project_id':self.project.pk},{'progress':100},{'status':Task.COMPLETED},{'created_by_id':self.member.pk}):
            with self.subTest(values=values),self.assertRaises(ValidationError):self.change(**values)

    def test_member_cannot_grant_manager_edits_and_closed_plugin_stops_work(self):
        with self.assertRaises(PermissionDenied):issue(self.member,self.project.pk,['update_task_details'])
        AgentPluginSetting.objects.create(user=self.user,plugin='tasks',enabled=False)
        with self.assertRaises(PermissionDenied):self.change()

    def test_read_record_supplies_version_and_assignment_identifiers(self):
        record=read_record(self.user,'task',self.task.pk)
        self.assertEqual(record['updated_at'],self.task.updated_at.isoformat());self.assertEqual(record['assignee_id'],self.member.pk)

    def test_job_poll_reports_committed_receipt_for_native_cache_refresh(self):
        from django.urls import reverse
        self.client.force_login(self.user)
        url=reverse('ai_job',args=[self.job.pk]);self.assertNotIn('X-Zhiyu-Workspace-Change',self.client.get(url).headers)
        value=self.change();response=self.client.get(url)
        self.assertEqual(response['X-Zhiyu-Workspace-Change'],str(value['receipt']))
        self.assertEqual(self.client.get(url)['X-Zhiyu-Workspace-Change'],str(value['receipt']))

    def test_another_account_cannot_receive_the_job_receipt_header(self):
        from django.urls import reverse
        self.change();self.client.force_login(self.member)
        response=self.client.get(reverse('ai_job',args=[self.job.pk]))
        self.assertEqual(response.status_code,404);self.assertNotIn('X-Zhiyu-Workspace-Change',response.headers)
