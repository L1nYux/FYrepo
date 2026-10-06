"""Check frozen five-founder login compatibility using a disposable old database."""
import os
import sys
import tempfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
scratch=root/'.test-scratch';scratch.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='identity-upgrade-',dir=scratch) as directory:
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',WORKBENCH_DATA_DIR=directory,
                      WORKBENCH_SECRET_KEY='disposable-identity-upgrade',WORKBENCH_DEBUG='1')
    import django
    django.setup()
    from django.db import connection,connections
    from django.db.migrations.executor import MigrationExecutor
    from django.contrib.auth.hashers import make_password
    try:
        executor=MigrationExecutor(connection);previous=[('core','0028_personal_thread_read'),('aihub','0016_alter_assistantimage_options_and_more')]
        executor.migrate(previous);old=executor.loader.project_state(previous).apps
        User=old.get_model('auth','User');Profile=old.get_model('core','MemberProfile')
        Team=old.get_model('core','Team');Membership=old.get_model('core','TeamMembership')
        digest=make_password('disposable-founder-check-only')
        founders=[User.objects.create(username=name,password=digest) for name in ['原所有者','hyacinth','l1nyux','zhou','原成员']]
        team,_=Team.objects.update_or_create(pk=1,defaults={'name':'原团队','owner':founders[0]})
        for index,user in enumerate(founders):
            Profile.objects.create(user=user)
            Membership.objects.create(team=team,user=user,role='owner' if index==0 else 'member')
        outsider=User.objects.create(username='outside-admin',is_staff=True,is_superuser=True,password=digest)
        executor=MigrationExecutor(connection);latest=executor.loader.graph.leaf_nodes();executor.migrate(latest)
        current=executor.loader.project_state(latest).apps;Profile=current.get_model('core','MemberProfile')
        assert set(Profile.objects.filter(legacy_login_allowed=True).values_list('user_id',flat=True))=={u.pk for u in founders}
        assert not Profile.objects.get(user_id=outsider.pk).legacy_login_allowed
        assert current.get_model('auth','User').objects.get(pk=founders[0].pk).password==digest
        from django.contrib.auth.models import User as LiveUser
        from core.models import MemberProfile,TeamMembership
        from core.identity import login_user
        from core.tenancy import scope
        with scope(None,http=True): newcomer=LiveUser.objects.create_user('newcomer')
        profile=MemberProfile.objects.create(user=newcomer,workbench_id='new_member')
        TeamMembership.objects.update_or_create(user=newcomer,team_id=1,defaults={'role':'admin'})
        assert not profile.legacy_login_allowed and login_user('newcomer') is None
        assert login_user('new_member').pk==newcomer.pk
        owner_profile=MemberProfile.objects.get(user_id=founders[0].pk);owner_profile.workbench_id='new_owner';owner_profile.save(update_fields=['workbench_id'])
        assert login_user('原所有者').pk==founders[0].pk and login_user('new_owner').pk==founders[0].pk
        MigrationExecutor(connection).migrate(latest)
        assert MemberProfile.objects.filter(legacy_login_allowed=True).count()==5
        assert not LiveUser.objects.get(pk=founders[0].pk).is_staff
        print('PASS: exactly five frozen founders, legacy login after ID change, no grants for new admins, password preservation and idempotent migration')
    finally:connections.close_all()
