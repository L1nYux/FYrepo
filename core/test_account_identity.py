from django.test import TestCase
from django.urls import reverse
from .test_community import CommunityTests
from .models import MemberProfile, PersonalMessage
from .identity import account_id, nickname, login_user
from .forms import RegisterForm


class AccountIdentityTests(TestCase):
    setUp=CommunityTests.setUp

    def test_nickname_name_and_account_id_are_independent_and_old_login_works(self):
        MemberProfile.objects.create(user=self.owner,legacy_login_allowed=True)
        response=self.client.post(reverse('profile'),{'action':'profile','nickname':'知域昵称','first_name':'真实姓名','workbench_id':'zhiyu_owner'})
        self.assertEqual(response.status_code,302)
        self.owner.refresh_from_db();self.assertEqual(self.owner.username,'org-owner')
        self.assertEqual(self.owner.first_name,'真实姓名');self.assertEqual(nickname(self.owner),'知域昵称');self.assertEqual(account_id(self.owner),'zhiyu_owner')
        card=self.client.get(reverse('member_card',args=[self.owner.pk])).json()
        self.assertEqual(card['display_name'],'知域昵称');self.assertEqual(card['username'],'zhiyu_owner')
        self.client.logout()
        for identity in ['zhiyu_owner','org-owner']:
            response=self.client.post(reverse('login'),{'username':identity,'password':'test-community-Q9-only'})
            self.assertEqual(response.status_code,302);self.client.logout()
        for identity in ['知域昵称','真实姓名']:
            response=self.client.post(reverse('login'),{'username':identity,'password':'test-community-Q9-only'})
            self.assertEqual(response.status_code,200);self.assertNotIn('_auth_user_id',self.client.session)

    def test_non_founders_cannot_bypass_id_login_via_internal_username(self):
        import json
        MemberProfile.objects.create(user=self.owner,workbench_id='new_owner',nickname='原昵称')
        self.client.logout()
        for identity in ['org-owner','原昵称']:
            self.assertIsNone(login_user(identity))
            response=self.client.post(reverse('login'),{'username':identity,'password':'test-community-Q9-only'})
            self.assertEqual(response.status_code,200);self.assertNotIn('_auth_user_id',self.client.session)
            response=self.client.post(reverse('desktop_api',args=['login']),json.dumps({'username':identity,'password':'test-community-Q9-only'}),content_type='application/json')
            self.assertEqual(response.status_code,400);self.assertNotIn('_auth_user_id',self.client.session)
        self.assertEqual(login_user('new_owner'),self.owner)
        self.owner.email='founder-test@example.com';self.owner.save(update_fields=['email'])
        for identity in ['NEW_OWNER','founder-test@example.com']:
            self.assertEqual(self.client.post(reverse('login'),{'username':identity,'password':'test-community-Q9-only'}).status_code,302)
            self.client.logout()

    def test_founder_marker_cannot_be_requested_via_profile_or_registration(self):
        response=self.client.post(reverse('profile'),{'action':'profile','workbench_id':'new_owner','legacy_login_allowed':'true'})
        self.assertEqual(response.status_code,302)
        self.owner.refresh_from_db();self.assertFalse(self.owner.member_profile.legacy_login_allowed)
        self.assertIsNone(login_user('org-owner'))
        self.assertFalse(self.owner.is_staff or self.owner.is_superuser)
        profile=MemberProfile.objects.create(user=self.root)
        self.assertFalse(profile.legacy_login_allowed)

    def test_workbench_id_cannot_be_changed_twice_or_impersonate_legacy_login(self):
        self.client.post(reverse('profile'),{'action':'profile','workbench_id':'zhiyu_owner','nickname':'相同昵称'})
        self.client.post(reverse('profile'),{'action':'profile','workbench_id':'second_owner','nickname':'新的昵称'})
        self.owner.refresh_from_db();self.assertEqual(account_id(self.owner),'zhiyu_owner');self.assertEqual(nickname(self.owner),'新的昵称')
        self.client.force_login(self.worker)
        response=self.client.post(reverse('profile'),{'action':'profile','workbench_id':self.owner.username})
        self.assertEqual(response.status_code,200);self.assertContains(response,'已被使用')
        response=self.client.post(reverse('profile'),{'action':'profile','workbench_id':'ZHIYU_OWNER'})
        self.assertEqual(response.status_code,200);self.assertContains(response,'已被使用')

    def test_new_registration_rejects_names_and_accepts_repeated_nicknames(self):
        from .identity import validate_id
        from django.core.exceptions import ValidationError
        for value in ['中文昵称','ab','123abc','a@b.com','../root']:
            with self.assertRaises(ValidationError):validate_id(value)
        self.assertEqual(validate_id('User_One'),'user_one')
        MemberProfile.objects.create(user=self.owner,nickname='相同昵称')
        MemberProfile.objects.create(user=self.worker,nickname='相同昵称')
        self.assertNotEqual(account_id(self.owner),account_id(self.worker))

    def test_messages_display_nicknames_and_friend_search_uses_id(self):
        MemberProfile.objects.create(user=self.worker,nickname='聊天昵称',workbench_id='worker_new')
        PersonalMessage.objects.create(sender=self.worker,recipient=self.owner,body='消息')
        data=self.client.get(reverse('personal_chat',args=[self.worker.pk]),HTTP_ACCEPT='application/json').json()
        self.assertEqual(data['messages'][0]['author'],'聊天昵称')
        result=self.client.get(reverse('friend_search'),{'q':'worker_new'}).json()
        self.assertEqual(result['display_name'],'聊天昵称');self.assertEqual(result['username'],'worker_new')
        self.assertEqual(self.client.get(reverse('friend_search'),{'q':'聊天昵称'}).status_code,404)

    def test_website_brand_and_logo_match_application(self):
        response=self.client.get(reverse('workspace_home'))
        self.assertContains(response,'知域');self.assertContains(response,'core/brand-mark.svg')
        self.assertNotContains(response,'<span class="shell-mark">研</span>')
