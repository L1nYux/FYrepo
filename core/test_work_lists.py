from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from .models import Project, Task, Team, TeamMembership, Workspace, ProjectCollaborator
from .solo_teams import ensure
from .tenancy import scope


class WorkListTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('component-owner')
        self.other=User.objects.create_user('component-other')
        self.home=ensure(self.user);self.private=ensure(self.other)
        self.team=Team.objects.create(name='协作团队',owner=self.user)
        TeamMembership.objects.create(team=self.team,user=self.user,role='owner')
        self.space=Workspace.objects.create(kind='team',team=self.team)
        with scope(self.home):
            self.project=Project.objects.create(name='论文计划',owner=self.user,created_by=self.user)
            self.task=Task.objects.create(project=self.project,title='盖章工作',created_by=self.user,assignee=self.user,progress=20)
        with scope(self.space):
            self.shared=Project.objects.create(name='团队计划',owner=self.user,created_by=self.user)
        with scope(self.private):
            self.secret=Project.objects.create(name='不可见计划',owner=self.other,created_by=self.other)
            Task.objects.create(project=self.secret,title='不可见任务',created_by=self.other)
        self.client.force_login(self.user)

    def data(self,name='dashboard',**query):
        response=self.client.get(reverse(name),query,HTTP_X_ZHIYU_COMPONENT='work-list-v1')
        self.assertEqual(response.status_code,200,response.content[:300])
        return response.json()

    def test_html_and_json_share_the_authorized_contract(self):
        response=self.client.get(reverse('dashboard'))
        self.assertContains(response,'data-work-list')
        self.assertContains(response,'论文计划');self.assertNotContains(response,'不可见计划')
        self.assertContains(response,'work-list.js')
        self.assertEqual(response.context['work_list'],self.data())
        self.assertIn('X-Zhiyu-Component',response['Vary'])
        self.assertEqual(response['Cache-Control'],'private, no-store')

    def test_json_is_data_only_and_excludes_other_accounts(self):
        response=self.client.get(reverse('task_list'),HTTP_X_ZHIYU_COMPONENT='work-list-v1')
        self.assertEqual(response['Content-Type'],'application/json')
        self.assertNotContains(response,'<script')
        self.assertNotContains(response,'不可见任务')
        self.assertEqual(response.json()['account'],str(self.user.pk))

    def test_ownership_filters_survive_pagination_and_creation(self):
        with scope(self.space):
            for index in range(31):Project.objects.create(name='团队 '+str(index),owner=self.user,created_by=self.user)
        data=self.data(ownership=str(self.space.pk))
        self.assertEqual(len(data['items']),30);self.assertEqual(data['pagination']['total'],32)
        self.assertIn('ownership='+str(self.space.pk),data['pagination']['next'])
        self.assertIn('ownership='+str(self.space.pk),data['create_url'])
        self.assertEqual(self.data(ownership=str(self.space.pk),page=2)['pagination']['number'],2)

    def test_invalid_or_unowned_scope_is_denied(self):
        for owner in ('bogus',str(self.private.pk),'9'*100):
            self.assertEqual(self.client.get(reverse('dashboard'),{'ownership':owner},HTTP_X_ZHIYU_COMPONENT='work-list-v1').status_code,403)

    def test_task_search_includes_project_names(self):
        data=self.data('task_list',q='论文计划')
        self.assertEqual([row['id'] for row in data['items']],[self.task.pk])
        self.assertEqual(self.data(q='论文')['items'][0]['id'],self.project.pk)
        self.assertEqual(self.data('task_list',q='没有匹配')['pagination']['total'],0)

    def test_status_category_and_mine_are_combined(self):
        with scope(self.home):
            self.task.status='submitted';self.task.category='analysis';self.task.save()
            ProjectCollaborator.objects.create(project=self.project,user=self.other,granted_by=self.user)
            Task.objects.create(project=self.project,title='其他人任务',created_by=self.user,assignee=self.other,category='analysis',status='submitted')
        data=self.data('task_list',mine='1',status='submitted',category='analysis')
        self.assertEqual([row['id'] for row in data['items']],[self.task.pk])
        self.assertEqual(self.data('task_list',status='completed')['items'],[])
        self.assertEqual(self.data('task_list',status='invalid')['filters']['status'],'')

    def test_progress_matches_mother_task_and_project_calculations(self):
        with scope(self.home):
            Task.objects.create(project=self.project,parent=self.task,title='子一',created_by=self.user,progress=40)
            Task.objects.create(project=self.project,parent=self.task,title='子二',created_by=self.user,progress=80)
            Task.objects.create(project=self.project,parent=self.task,title='已归档',created_by=self.user,progress=0,archived_at=timezone.now())
        tasks=self.data('task_list')['items']
        self.assertEqual(next(row['progress'] for row in tasks if row['id']==self.task.pk),60)
        self.assertEqual(next(row['progress'] for row in self.data()['items'] if row['id']==self.project.pk),60)

    def test_archived_parent_and_project_hide_their_tasks(self):
        with scope(self.home):
            Task.objects.create(project=self.project,parent=self.task,title='隐藏子任务',created_by=self.user)
            self.task.archived_at=timezone.now();self.task.save()
        self.assertEqual(self.data('task_list')['items'],[])
        with scope(self.home):self.project.archived_at=timezone.now();self.project.save()
        self.assertNotIn(self.project.pk,[row['id'] for row in self.data()['items']])

    def test_external_collaborator_is_in_mine_before_pagination(self):
        with scope(self.private):ProjectCollaborator.objects.create(project=self.secret,user=self.user,granted_by=self.other)
        data=self.data(scope='mine')
        row=next(row for row in data['items'] if row['id']==self.secret.pk)
        self.assertTrue(row['participant'])
        with scope(self.private):ProjectCollaborator.objects.filter(project=self.secret).update(active=False)
        self.assertNotIn(self.secret.pk,[row['id'] for row in self.data()['items']])

    def test_membership_removal_is_enforced_on_next_read(self):
        self.assertIn(self.shared.pk,[row['id'] for row in self.data()['items']])
        TeamMembership.objects.filter(team=self.team,user=self.user).update(active=False)
        self.assertNotIn(self.shared.pk,[row['id'] for row in self.data()['items']])
        self.assertEqual(self.client.get(reverse('dashboard'),{'ownership':str(self.space.pk)},HTTP_X_ZHIYU_COMPONENT='work-list-v1').status_code,403)

    def test_progress_and_people_do_not_add_queries_per_row(self):
        with CaptureQueriesContext(connection) as first:self.data('task_list')
        with scope(self.home):
            for index in range(25):Task.objects.create(project=self.project,title='More '+str(index),created_by=self.user,assignee=self.user)
        with CaptureQueriesContext(connection) as second:self.data('task_list')
        self.assertLessEqual(len(second),len(first)+1)

    def test_without_javascript_lists_and_filters_remain_available(self):
        page=self.client.get(reverse('task_list'),{'q':'盖章'})
        self.assertContains(page,'盖章工作');self.assertContains(page,'method="get"')
        self.assertContains(page,'href="'+reverse('task_detail',args=[self.task.pk])+'"')

    def test_list_read_does_not_mutate_business_records(self):
        before=(Project.all_objects.count(),Task.all_objects.count())
        self.data();self.data('task_list',mine='1')
        self.assertEqual(before,(Project.all_objects.count(),Task.all_objects.count()))
