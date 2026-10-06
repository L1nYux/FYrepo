"""Compete for the final team slot against a disposable file-backed SQLite database."""
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root));(root/'.test-scratch').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='team-admission-',dir=root/'.test-scratch') as directory:
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',WORKBENCH_DATA_DIR=directory,
        WORKBENCH_SECRET_KEY='isolated-team-admission-only',WORKBENCH_DEBUG='1')
    import django
    django.setup()
    from django.core.management import call_command
    from django.core.exceptions import ValidationError
    from django.contrib.auth.models import User
    from django.db import connections
    from core.models import Team,TeamMembership,Invite
    from core.admission import join_from_invitation
    from core.tenancy import scope
    try:
        call_command('migrate',interactive=False,verbosity=0)
        with scope(None,http=True):
            owner=User.objects.create_user('owner')
            candidates=[User.objects.create_user('candidate-'+str(i)) for i in range(2)]
        team=Team.objects.create(name='Two seat team',owner=owner,member_limit=2)
        TeamMembership.objects.create(team=team,user=owner,role='owner')
        with scope(team):
            codes=[Invite.issue(owner)[1] for _ in candidates]
        barrier=Barrier(2)
        def redeem(pair):
            user,code=pair
            try:
                with scope(None,http=True):
                    barrier.wait(timeout=10)
                    join_from_invitation(user,code)
                return 'joined'
            except ValidationError:
                return 'full'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as workers:
            results=list(workers.map(redeem,zip(candidates,codes)))
        assert sorted(results)==['full','joined'],results
        assert TeamMembership.objects.filter(team=team,active=True).count()==2
        assert Invite.all_objects.filter(team=team,used_at__isnull=False).count()==1
        print('PASS: exactly one final slot allocated; rejected invite remains unused')
    finally:connections.close_all()
