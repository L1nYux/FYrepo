from django.test import TestCase, TransactionTestCase
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse
from django.core.exceptions import ValidationError
from core import test_collaboration_v4
from core.models import TeamMembership
from core.tenancy import scope
from .models import SamplingRun


class SamplingOwnershipTests(TestCase):
    setUp=test_collaboration_v4.CollaborationV4Tests.setUp

    def make_run(self, workspace=None, project=None, creator=None):
        with scope(workspace or self.teamspace):
            return SamplingRun.objects.create(name='私有样本集',created_by=creator or self.owner,
                project=project,periods=[{'id':'P3','label':'P3','start_year':2024,'end_year':2025}],
                selected_tiers=['T1'],selected_journals=['中国法学'])

    def test_foreign_account_cannot_read_write_or_download_by_direct_url(self):
        run=self.make_run()
        self.client.force_login(self.stranger)
        self.assertNotContains(self.client.get(reverse('sampling:index')),run.name)
        read=('detail','agent_config','agent_pdf_config','document_status','document_bundle','pdf_manifest')
        write=('edit','clone','candidate_import','review_apply','freeze','create_experiment','agent_import',
               'document_upload','document_convert','agent_pdf_report')
        for route in read:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(reverse('sampling:'+route,args=[run.pk])).status_code,404)
        for route in write:
            with self.subTest(route=route):
                self.assertEqual(self.client.post(reverse('sampling:'+route,args=[run.pk]),{}).status_code,404)
        self.assertEqual(self.client.get(reverse('sampling:artifact_download',args=[run.pk,1])).status_code,404)
        self.assertEqual(self.client.get(reverse('sampling:document_download',args=[run.pk,1,'pdf'])).status_code,404)

    def test_removed_creator_and_team_guest_cannot_open_team_samples(self):
        member=TeamMembership.objects.create(team=self.team,user=self.person,role='member')
        run=self.make_run(creator=self.person)
        self.assertEqual(self.client.get(reverse('sampling:detail',args=[run.pk])).status_code,200)
        for role,active in [('guest',True),('member',False)]:
            TeamMembership.objects.filter(pk=member.pk).update(role=role,active=active)
            self.assertEqual(self.client.get(reverse('sampling:detail',args=[run.pk])).status_code,404)

    def test_personal_samples_are_private_even_for_team_owner(self):
        run=self.make_run(workspace=self.personal,creator=self.person)
        self.assertEqual(self.client.get(reverse('sampling:detail',args=[run.pk])).status_code,200)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('sampling:detail',args=[run.pk])).status_code,404)
        self.assertNotContains(self.client.get(reverse('sampling:index')),run.name)

    def test_owner_can_manage_team_run_from_personal_session_without_switching(self):
        run=self.make_run()
        self.client.force_login(self.owner)
        session=self.client.session;session['workbench-space']='personal';session.save()
        response=self.client.post(reverse('sampling:clone',args=[run.pk]))
        self.assertEqual(response.status_code,302)
        clone=SamplingRun.objects.get(source_run=run)
        self.assertEqual(clone.workspace_id,run.workspace_id)
        self.assertEqual(self.client.session['workbench-space'],'personal')

    def test_project_and_source_version_cannot_cross_ownership(self):
        with self.assertRaises(ValidationError):
            self.make_run(workspace=self.personal,project=self.project,creator=self.person)
        run=self.make_run()
        run.workspace=self.personal
        with self.assertRaises(ValidationError):run.save()

    def test_platform_admin_is_not_a_backdoor_into_foreign_samples(self):
        run=self.make_run()
        self.stranger.is_staff=True;self.stranger.is_superuser=True;self.stranger.save()
        self.client.force_login(self.stranger)
        self.assertNotContains(self.client.get(reverse('admin:sampling_samplingrun_changelist')),run.name)
        self.assertEqual(self.client.get(reverse('admin:sampling_samplingrun_change',args=[run.pk])).status_code,302)


class LegacySamplingMigrationTests(TransactionTestCase):
    old=('sampling','0003_candidatepaper_cross_disciplinary_journal')
    new=('sampling','0004_workspace_ownership')

    def setUp(self):
        executor=MigrationExecutor(connection)
        executor.migrate([self.old])
        self.apps=executor.loader.project_state([self.old,('core','0044_documentaccess_project_required')]).apps
        Team=self.apps.get_model('core','Team')
        self.team=Team.objects.create(name='唯一测试团队') if not Team.objects.exists() else Team.objects.get(active=True)
        user=self.apps.get_model('auth','User').objects.create(username='migration-sampler')
        self.run=self.apps.get_model('sampling','SamplingRun').objects.create(name='旧样本',created_by=user,status='frozen',run_fingerprint='a'*64)

    def tearDown(self):
        # Restore schema even when the deliberately ambiguous migration aborts.
        self.apps.get_model('sampling','SamplingRun').objects.all().delete()
        MigrationExecutor(connection).migrate([self.new])
        super().tearDown()

    def test_all_legacy_samples_assign_to_only_team_without_changing_fingerprint(self):
        executor=MigrationExecutor(connection);executor.migrate([self.new])
        run=executor.loader.project_state([self.new]).apps.get_model('sampling','SamplingRun').objects.get(pk=self.run.pk)
        self.assertEqual(run.workspace.team_id,self.team.pk)
        self.assertEqual(run.run_fingerprint,'a'*64);self.assertEqual(run.status,'frozen')

    def test_multiple_teams_abort_without_guessing_ownership(self):
        self.apps.get_model('core','Team').objects.create(name='额外团队')
        with self.assertRaisesRegex(RuntimeError,'唯一团队'):
            MigrationExecutor(connection).migrate([self.new])
        self.assertEqual(self.apps.get_model('sampling','SamplingRun').objects.get(pk=self.run.pk).run_fingerprint,'a'*64)
