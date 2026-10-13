from datetime import date, timedelta
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from .models import (Workspace, Team, TeamMembership, MemberProfile, Project, Task,
    Announcement, FinanceEntry, ApplicantProfile, AccountNotice, PersonalMessage,
    ConversationPreference, RecruitmentOffer, TeamOpening, TeamApplication)
from .tenancy import scope
from .solo_teams import ensure


class TeamInboxAcceptance(TestCase):
    def setUp(self):
        with scope(None,http=True):
            self.owner=User.objects.create_user('accept-owner')
            self.peer=User.objects.create_user('accept-peer')
            self.stranger=User.objects.create_user('accept-stranger')
            for user in (self.owner,self.peer,self.stranger):MemberProfile.objects.create(user=user)
        self.team=Team.objects.create(name='协作团队',owner=self.owner,listed=True,member_limit=10)
        self.space=Workspace.objects.create(kind='team',team=self.team)
        TeamMembership.objects.create(team=self.team,user=self.owner,role='owner')
        self.client.force_login(self.owner)
        session=self.client.session;session['workbench-space']='team:'+str(self.team.pk);session.save()

    def test_closed_team_preserves_old_workspace_projects_and_exact_finance(self):
        old=Workspace.objects.create(kind='personal',owner=self.owner)
        with scope(old):
            project=Project.objects.create(name='旧项目',owner=self.owner,created_by=self.owner,public_state='public')
            entry=FinanceEntry.objects.create(kind='expense',amount='12.50',occurred_on=date.today(),created_by=self.owner)
        converted=ensure(self.owner)
        self.assertEqual(converted.pk,old.pk);self.assertEqual(converted.kind,'team')
        self.assertEqual(converted.team.solo_owner_id,self.owner.pk)
        self.assertFalse(converted.team.listed);self.assertEqual(converted.team.member_limit,1)
        self.assertEqual(ensure(self.owner).team_id,converted.team_id)
        project.refresh_from_db();entry.refresh_from_db()
        self.assertEqual(project.workspace_id,old.pk);self.assertEqual(project.team_id,converted.team_id)
        self.assertEqual(entry.amount,Decimal('12.50'));self.assertEqual(entry.workspace_id,old.pk)
        from .admission import admit_member
        with self.assertRaises(ValidationError):admit_member(self.peer,converted.team)
        with scope(converted):
            self.assertEqual(self.client.get(reverse('public_project_detail',args=[project.pk])).status_code,404)
        stranger=Client();stranger.force_login(self.stranger)
        self.assertEqual(stranger.get(reverse('project_detail',args=[project.pk])).status_code,404)

    def test_data_migration_preserves_legacy_record_id_and_amount(self):
        legacy=Workspace.objects.create(kind='personal',owner=self.peer)
        empty=Workspace.objects.create(kind='personal',owner=self.stranger)
        with scope(legacy):entry=FinanceEntry.objects.create(kind='income',amount='1.234567',occurred_on=date.today(),created_by=self.peer)
        # This fixture invokes historical conversion on the already-migrated test
        # database; its ORM state must match that schema, including new defaults.
        state=MigrationExecutor(connection).loader.project_state()
        import_module('core.migrations.0050_closed_teams_announcement_archive').convert(state.apps,SimpleNamespace(connection=connection))
        legacy.refresh_from_db();entry.refresh_from_db()
        self.assertEqual(legacy.kind,'team');self.assertEqual(entry.workspace_id,legacy.pk)
        self.assertEqual(entry.amount,Decimal('1.23'));self.assertEqual(entry.team_id,legacy.team_id)
        empty.refresh_from_db();self.assertEqual(empty.kind,'personal');self.assertIsNone(empty.team_id)
        self.assertFalse(TeamMembership.objects.filter(user=self.stranger).exists())

    def test_one_scope_remembered_and_creation_uses_same_team(self):
        solo=ensure(self.owner)
        with scope(self.space):Project.objects.create(name='协作项目',owner=self.owner,created_by=self.owner)
        with scope(solo):Project.objects.create(name='封闭项目',owner=self.owner,created_by=self.owner)
        page=self.client.get(reverse('workspace_home'),{'ownership':self.space.pk})
        self.assertContains(page,'name="ownership"',count=1);self.assertContains(page,'协作项目');self.assertNotContains(page,'封闭项目')
        self.assertEqual(self.client.get(reverse('project_new')).context['current_workspace'].pk,self.space.pk)
        self.assertEqual(self.client.get(reverse('document_new')).context['current_workspace'].pk,self.space.pk)
        self.assertNotContains(self.client.get(reverse('dashboard')),'封闭项目')
        self.assertContains(self.client.get(reverse('workspace_home'),{'ownership':'all'}),'封闭项目')
        foreign=ensure(self.stranger)
        self.assertEqual(self.client.get(reverse('workspace_home'),{'ownership':foreign.pk}).status_code,403)

    def test_desktop_has_real_teams_without_personal_option(self):
        data=self.client.get(reverse('desktop_api',args=['status'])).json()
        self.assertFalse(data['needsTeam']);self.assertEqual(data['spaceKind'],'team')
        self.assertFalse(any(item['id']=='personal' for item in data['spaces']))

    def test_announcement_delete_requires_owner_and_confirmation(self):
        with scope(self.space):notice=Announcement.objects.create(title='删除公告',body='正文')
        url=reverse('announcement_delete',args=[notice.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        self.assertEqual(self.client.post(url,{}).status_code,302)
        notice.refresh_from_db();self.assertIsNone(notice.deleted_at)
        self.assertEqual(self.client.post(url,{'confirm':'yes'}).status_code,302)
        notice.refresh_from_db();self.assertIsNotNone(notice.deleted_at);self.assertFalse(notice.is_published)
        self.assertEqual(len(self.client.get(reverse('workspace_home')).context['announcements']),0)
        self.assertEqual(self.client.get(reverse('announcement_edit',args=[notice.pk])).status_code,404)
        with scope(self.space):protected=Announcement.objects.create(title='其他公告',body='正文')
        stranger=Client();stranger.force_login(self.stranger)
        self.assertEqual(stranger.post(reverse('announcement_delete',args=[protected.pk]),{'confirm':'yes'}).status_code,404)
        TeamMembership.objects.create(team=self.team,user=self.peer)
        stranger.force_login(self.peer)
        self.assertEqual(stranger.post(reverse('announcement_delete',args=[protected.pk]),{'confirm':'yes'}).status_code,403)

    def test_discovery_messages_use_private_thread_and_keep_access_after_unlisting(self):
        profile=ApplicantProfile.objects.create(user=self.peer,listed=True,introduction='人才简介')
        page=self.client.get(reverse('talent_detail',args=[self.peer.pk]))
        self.assertContains(page,reverse('personal_chat',args=[self.peer.pk]))
        response=self.client.post(reverse('personal_chat',args=[self.peer.pk]),{'body':'协作咨询'},HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code,200)
        message=PersonalMessage.objects.get(sender=self.owner,recipient=self.peer)
        self.assertEqual(message.contact_source,'discovery')
        profile.listed=False;profile.save()
        self.assertEqual(self.client.get(reverse('personal_chat',args=[self.peer.pk])).status_code,200)
        ConversationPreference.objects.create(user=self.peer,channel='person:'+str(self.owner.pk),blocked=True)
        self.assertEqual(self.client.post(reverse('personal_chat',args=[self.peer.pk]),{'body':'禁止发送'},HTTP_ACCEPT='application/json').status_code,403)

    def test_offer_progress_is_private_card_and_system_inbox_does_not_duplicate(self):
        offer=RecruitmentOffer.objects.create(team=self.team,issued_by=self.owner,recipient=self.peer,title='项目协作',terms='讨论',expires_at=timezone.now()+timedelta(days=1))
        notice=AccountNotice.objects.create(user=self.peer,title='收到邀请',target_url=reverse('talent_offer',args=[offer.pk]))
        message=PersonalMessage.objects.get(notice=notice)
        self.assertEqual(message.sender_id,self.owner.pk);self.assertEqual(message.recipient_id,self.peer.pk)
        self.assertEqual(message.references[0]['kind'],'discovery-notice')
        self.client.force_login(self.peer)
        self.assertEqual(len(self.client.get(reverse('account_notices')).context['account_notices']),0)
        self.assertContains(self.client.get(reverse('personal_chat',args=[self.owner.pk])),'收到邀请')
        self.assertEqual(self.client.get(reverse('talent_offers')).context['shell_section'],'消息')
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('personal_message_action',args=[self.peer.pk,message.pk]),{'action':'withdraw'}).status_code,403)
        outsider=Client();outsider.force_login(self.stranger)
        self.assertEqual(outsider.get(reverse('personal_chat',args=[self.peer.pk])).status_code,404)

    def test_new_application_routes_progress_into_private_inbox(self):
        opening=TeamOpening.objects.create(team=self.team,title='职位',description='职责',planned_headcount=2)
        self.client.force_login(self.peer)
        self.assertEqual(self.client.post(reverse('team_apply',args=[opening.pk]),{'resume':'我的经历'}).status_code,302)
        application=TeamApplication.objects.get(opening=opening,applicant=self.peer)
        self.assertTrue(PersonalMessage.objects.filter(notice__application=application,recipient=self.owner).exists())
        self.assertTrue(PersonalMessage.objects.filter(notice__application=application,recipient=self.peer).exists())

    def test_discovery_navigation_includes_the_plugin_marketplace(self):
        page=self.client.get(reverse('talent_market'))
        import re
        nav=re.search(r'<nav class="settings-nav discovery-nav".*?</nav>',page.content.decode(),re.S).group()
        self.assertEqual(re.findall(r'<a\b[^>]*>(.*?)</a>',nav),['团队广场','人才市场','插件商城'])
