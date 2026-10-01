import tempfile
from pathlib import Path
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import get_template
from django.test import override_settings
from django.urls import reverse
from . import tests as upstream
from .models import Experiment, Project, Submission, Task, TeamContact


class IntegrationTests(upstream.WorkbenchTestCase):
    def test_all_templates_compile(self):
        for file in (Path(__file__).resolve().parent.parent / 'templates/core').glob('*.html'):
            get_template('core/' + file.name)

    def test_new_pages_render_for_guest_and_admin(self):
        for name in ['public_home','public_projects','public_experiments','public_members','contact']:
            self.assertEqual(self.client.get(reverse(name)).status_code,200,name)
        self.client.force_login(self.admin)
        for name in ['workspace_home','experiments','experiment_new','public_profile_edit','contact_edit','recycle_bin','announcement_new']:
            self.assertEqual(self.client.get(reverse(name)).status_code,200,name)

    def test_contact_changes_require_admin(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.post(reverse('contact_edit'),{'phone':'123456'}).status_code,403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('contact_edit'),{'email':'team@example.com','phone':'123456'}).status_code,302)
        self.client.logout()
        response=self.client.get(reverse('contact'))
        self.assertContains(response,'team@example.com')
        self.assertContains(response,'123456')

    def test_experiment_creation_linking_and_publication(self):
        self.client.force_login(self.dev)
        result=self.client.post(reverse('experiment_new'),{'title':'Trial','project':self.project.pk,'procedure':'Method','result':'Result','task':self.child.pk})
        self.assertEqual(result.status_code,302)
        experiment=Experiment.objects.get()
        self.assertTrue(experiment.number.startswith('EXP-'))
        self.assertEqual(experiment.project,self.project)
        self.assertContains(self.client.get(reverse('task_detail',args=[self.child.pk])), experiment.number)
        result=self.client.post(reverse('task_submit',args=[self.child.pk]),{'experiments':[experiment.pk]})
        self.assertEqual(result.status_code,302)
        self.assertEqual(Submission.objects.get().experiments.get(),experiment)
        self.assertContains(self.client.get(reverse('experiment_detail',args=[experiment.pk])),self.child.title)
        self.assertEqual(self.client.post(reverse('experiment_visibility',args=[experiment.pk]),{'action':'publish'}).status_code,403)
        self.client.force_login(self.admin)
        self.client.post(reverse('experiment_visibility',args=[experiment.pk]),{'action':'publish'})
        self.client.logout()
        self.assertEqual(self.client.get(reverse('public_experiment_detail',args=[experiment.pk])).status_code,200)
        self.client.force_login(self.dev)
        self.client.post(reverse('experiment_edit',args=[experiment.pk]),{'title':'Revised','number':experiment.number,'project':self.project.pk,'procedure':'Method','result':'Changed'})
        self.client.logout()
        self.assertEqual(self.client.get(reverse('public_experiment_detail',args=[experiment.pk])).status_code,404)

    def test_collaborator_can_submit_and_self_close_child(self):
        self.project.members.add(self.outsider)
        self.child.members.add(self.outsider)
        self.client.force_login(self.outsider)
        result=self.client.post(reverse('task_submit',args=[self.child.pk]),{'summary':'Done','finish':'on'})
        self.assertEqual(result.status_code,302)
        self.child.refresh_from_db()
        self.assertEqual(self.child.status,Task.COMPLETED)

    def test_task_form_saves_collaborators(self):
        self.client.force_login(self.owner)
        result=self.client.post(reverse('task_edit',args=[self.child.pk]),{'title':self.child.title,'description':'Updated','assignee':self.dev.pk,'members':[self.owner.pk]})
        self.assertEqual(result.status_code,302)
        self.assertTrue(self.child.members.filter(pk=self.owner.pk).exists())

    def test_deleted_parent_hides_children_and_restore_preserves_them(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('task_archive',args=[self.mother.pk]))
        self.assertEqual(self.client.get(reverse('task_detail',args=[self.child.pk])).status_code,404)
        self.assertNotContains(self.client.get(reverse('task_list')),self.child.title)
        self.client.post(reverse('restore',args=['task',self.mother.pk]))
        self.assertEqual(self.client.get(reverse('task_detail',args=[self.child.pk])).status_code,200)
        self.client.post(reverse('project_archive',args=[self.project.pk]))
        self.assertEqual(self.client.get(reverse('task_detail',args=[self.child.pk])).status_code,404)

    def test_source_attachment_only_submission(self):
        self.client.force_login(self.dev)
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            result=self.client.post(reverse('task_submit',args=[self.child.pk]),{'attachments':SimpleUploadedFile('anonymize.py',b'print("example")')})
            self.assertEqual(result.status_code,302)
            self.assertEqual(Submission.objects.get().attachments.get().original_name,'anonymize.py')

    def test_cannot_link_other_projects_experiment(self):
        project=Project.objects.create(name='Other',goal='Other',owner=self.outsider,created_by=self.admin)
        experiment=Experiment.objects.create(title='Other',number='OTHER',project=project,created_by=self.outsider)
        self.client.force_login(self.dev)
        self.client.post(reverse('task_submit',args=[self.child.pk]),{'experiments':[experiment.pk]})
        self.assertFalse(Submission.objects.exists())
