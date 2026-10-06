"""Check the local desktop bridge against an isolated database, not installed data."""
import os
import sys
import json
import tempfile
import types
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root));(root/'.test-scratch').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='local-team-auth-',dir=root/'.test-scratch') as directory:
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',WORKBENCH_DATA_DIR=directory,
        WORKBENCH_DESKTOP_STATE=directory,WORKBENCH_DESKTOP_BOOT_TOKEN='fixture-local-bridge-token',
        WORKBENCH_SECRET_KEY='isolated-local-team-auth',WORKBENCH_DEBUG='1',WORKBENCH_ALLOWED_HOSTS='testserver')
    (Path(directory)/'server').mkdir()
    import django
    django.setup()
    from django.core.management import call_command
    from django.db import connections
    from django.test import Client,override_settings
    from unittest.mock import patch
    import re
    from django.urls import include,path
    from core.models import TeamMembership, TeamCreationInvite
    from django.contrib.auth.models import User
    from desktop.desktop_auth import urlpatterns
    urls=types.ModuleType('local_bridge_test_urls');urls.urlpatterns=urlpatterns+[path('',include('config.urls'))]
    sys.modules[urls.__name__]=urls
    try:
        call_command('migrate',interactive=False,verbosity=0)
        with override_settings(ROOT_URLCONF=urls.__name__):
            client=Client(REMOTE_ADDR='127.0.0.1',HTTP_X_DESKTOP_TOKEN='fixture-local-bridge-token')
            def post(action,data):
                return client.post('/_desktop/auth/'+action+'/',json.dumps(data),content_type='application/json')
            password='fixture-local-account-Q5-only'
            result=post('setup',{'password':password,'passwordConfirm':password})
            assert result.status_code==200,result.content
            assert result.json()['isAdmin'] and result.json()['isPlatformAdmin'] and result.json()['teamId']==1
            assert TeamMembership.objects.get(user__username='local-admin').role=='owner'
            print('PASS local bootstrap explicitly provisions original team owner')
            _,creation_code=TeamCreationInvite.issue(User.objects.get(username='local-admin'),6)
            post('logout',{})
            with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'),patch('core.registration_email.send_mail',return_value=1) as mail:
                client.post('/desktop/api/registration-code/',json.dumps({'email':'independent@example.com'}),content_type='application/json')
            email_code=re.search(r'\d{6}',mail.call_args.args[1]).group()
            result=post('register',{'emailCode':email_code,'username':'independent','email':'independent@example.com','inviteCode':creation_code,'teamName':'新的本地团队','password':password,'passwordConfirm':password})
            assert result.status_code==200,result.content
            assert result.json()['authenticated'] and not result.json()['needsTeam'] and result.json()['isAdmin']
            assert TeamMembership.objects.get(user__username='independent').team.member_limit==6
            print('PASS local invitation registration creates a separately capped team')
            status=client.get('/_desktop/auth/status/').json()
            assert status['isAdmin'] and not status['isPlatformAdmin'] and status['teamName']=='新的本地团队'
            print('PASS local team creation separates software and team administration')
            post('logout',{})
            result=post('login',{'username':'independent','password':password})
            assert result.status_code==200 and result.json()['teamId']==status['teamId']
            print('PASS local login restores team membership')
    finally:connections.close_all()
