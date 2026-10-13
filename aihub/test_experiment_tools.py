from django.core.exceptions import PermissionDenied,ValidationError
from django.test import TestCase
from django.utils import timezone
from core.models import Experiment
from . import test_delegation as fixtures
from .delegation import issue,execute_operation
from .models import AgentPluginSetting,AgentOperation
from .agent import read_record


class ExperimentToolTests(TestCase):
    def setUp(self):
        fixtures.DelegationTests.setUp(self)
        from core.tenancy import scope
        context=scope(self.space);context.__enter__();self.addCleanup(context.__exit__,None,None,None)
        self.experiment=Experiment.objects.create(project=self.project,title='原实验',number='EXP-TOOL',created_by=self.user,parameters=[{'name':'temperature','value':'0.2'}])
        self.grant=issue(self.user,self.project.pk,['create_experiment_record','update_experiment_record'])
        self.job.authorization=self.grant
        with scope(self.personal):self.job.save(update_fields=['authorization'])

    def change(self,**overrides):
        return execute_operation(self.user,self.job,'update_experiment_record',{'experiment_id':self.experiment.pk,'expected_updated_at':self.experiment.updated_at.isoformat(),'result':'新结果',**overrides})

    def test_create_uses_form_number_and_receipt(self):
        args={'project_id':self.project.pk,'title':'新实验','content':'记录方法'}
        value=execute_operation(self.user,self.job,'create_experiment_record',args)
        replay=execute_operation(self.user,self.job,'create_experiment_record',args)
        row=Experiment.objects.get(title='新实验')
        self.assertEqual(row.project,self.project);self.assertTrue(row.number.startswith('EXP-'))
        self.assertEqual(row.visibility,'internal');self.assertTrue(value['saved']);self.assertTrue(replay['replayed'])
        self.grant.refresh_from_db();self.assertEqual(self.grant.used_operations,1)

    def test_update_preserves_parameters_and_metadata(self):
        self.change(status='running');self.experiment.refresh_from_db()
        self.assertEqual(self.experiment.result,'新结果');self.assertEqual(self.experiment.status,'running')
        self.assertEqual(self.experiment.parameters,[{'name':'temperature','value':'0.2'}])
        self.assertEqual(self.experiment.number,'EXP-TOOL');self.assertEqual(self.experiment.project,self.project)

    def test_stale_record_cannot_overwrite_another_edit(self):
        Experiment.objects.filter(pk=self.experiment.pk).update(updated_at=timezone.now(),result='他人结果')
        with self.assertRaises(ValidationError):self.change()
        self.experiment.refresh_from_db();self.assertEqual(self.experiment.result,'他人结果')
        self.assertFalse(AgentOperation.objects.filter(tool='update_experiment_record').exists())

    def test_public_update_returns_to_review(self):
        self.experiment.visibility='public';self.experiment.save()
        self.change();self.experiment.refresh_from_db();self.assertEqual(self.experiment.visibility,'pending')

    def test_archived_and_cross_project_records_are_refused(self):
        self.experiment.status='archived';self.experiment.save()
        with self.assertRaises(ValidationError):self.change()
        from core.models import Project
        project=Project.objects.create(name='别的项目',owner=self.user,created_by=self.user)
        self.experiment.status='design';self.experiment.project=project;self.experiment.save()
        with self.assertRaises(PermissionDenied):self.change()

    def test_plugin_disable_and_revoke_block_new_work(self):
        AgentPluginSetting.objects.create(user=self.user,plugin='experiments',enabled=False)
        with self.assertRaises(PermissionDenied):self.change()
        AgentPluginSetting.objects.filter(user=self.user,plugin='experiments').delete()
        self.grant.revoked_at=timezone.now();self.grant.save()
        with self.assertRaises(PermissionDenied):self.change()

    def test_tool_cannot_publish_or_reassign_record(self):
        with self.assertRaises(ValidationError):self.change(visibility='public')
        with self.assertRaises(ValidationError):self.change(project_id=self.project.pk)

    def test_read_record_returns_version_for_followup(self):
        value=read_record(self.user,'experiment',self.experiment.pk)
        self.assertEqual(value['updated_at'],self.experiment.updated_at.isoformat())
        self.assertEqual(value['status'],'design')
