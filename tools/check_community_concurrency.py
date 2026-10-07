"""Exercise personal relationships and ownership handoff on disposable SQLite."""
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root)); (root/'.test-scratch').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='community-race-',dir=root/'.test-scratch') as directory:
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',WORKBENCH_DATA_DIR=directory,
        WORKBENCH_SECRET_KEY='isolated-community-race-only',WORKBENCH_DEBUG='1')
    import django
    django.setup()
    from django.core.management import call_command
    from django.contrib.auth.models import User
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.db import connections
    from django.http import Http404
    from django.test import RequestFactory
    from core.models import Team,TeamMembership,FriendRequest,Friendship
    from core.personal_messages import friend_action
    from core.teams import transfer
    from core.tenancy import scope
    try:
        call_command('migrate',interactive=False,verbosity=0)
        with scope(None,http=True):
            users=[User.objects.create_user('race-'+str(i)) for i in range(3)]
        team=Team.objects.create(name='Disposable handoff',owner=users[0])
        for index,user in enumerate(users):
            TeamMembership.objects.create(team=team,user=user,role='owner' if index==0 else 'member')
        requests=[FriendRequest.objects.create(sender=users[0],recipient=users[1]),
                  FriendRequest.objects.create(sender=users[1],recipient=users[0])]
        barrier=Barrier(2)
        def accept(item):
            try:
                with scope(None,http=True):
                    request=RequestFactory().post('/messages/friends/action/',{'action':'accept'})
                    request.user=User.objects.get(pk=item.recipient_id)
                    barrier.wait(timeout=10)
                    return friend_action(request,item.pk).status_code
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(accept,requests))==[302,302]
        assert Friendship.objects.count()==1
        assert FriendRequest.objects.filter(state='accepted').count()==2
        print('PASS: simultaneous reciprocal accepts create one friendship without SQLite lock errors')
        barrier=Barrier(2)
        def handoff(candidate):
            try:
                with scope(team,http=True):
                    request=RequestFactory().post('/teams/transfer/',{'user':str(candidate.pk),'confirm':team.name})
                    request.user=User.objects.get(pk=users[0].pk); request.team=Team.objects.get(pk=team.pk)
                    request.session={}; request._messages=FallbackStorage(request)
                    barrier.wait(timeout=10)
                    return transfer(request).status_code
            except Http404: return 404
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(handoff,users[1:]))
        assert sorted(results)==[302,404],results
        team.refresh_from_db()
        assert team.owner_id in {users[1].pk,users[2].pk}
        owners=TeamMembership.objects.filter(team=team,role='owner')
        assert owners.count()==1 and owners.get().user_id==team.owner_id
        print('PASS: competing handoffs commit one consistent owner; stale handoff is rejected')
    finally: connections.close_all()
