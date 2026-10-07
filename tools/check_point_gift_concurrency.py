"""Exercise real SQLite writer contention using only a temporary database.

Run with the project's Python. Never uses the application's database or keys.
"""
import os
import sys
import tempfile
import uuid
from pathlib import Path
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from contextlib import ExitStack

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
scratch = root / '.test-scratch'
scratch.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='gift-race-', dir=scratch) as data_dir, ExitStack() as cleanup:
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', WORKBENCH_DATA_DIR=data_dir,
                      WORKBENCH_SECRET_KEY='isolated-concurrency-test', WORKBENCH_DEBUG='1',
                      WORKBENCH_ALLOWED_HOSTS='testserver', GIFT_RACE_FAKE_KEY='test-only')
    import django
    django.setup()
    from django.core.management import call_command
    from django.contrib.auth.models import User
    from django.test import Client
    from django.db import connections, close_old_connections
    cleanup.callback(connections.close_all)
    from django.core.exceptions import ValidationError
    from django.utils import timezone
    from aihub.models import Allowance, PointGift, PointGiftReceipt, Provider, PoolModel, PriceVersion, BudgetWeek
    from aihub.service import allowance, pool_settings, reserve, settle, week_now
    from aihub.gifts import expire_gifts
    call_command('migrate', verbosity=0)
    users = [User.objects.create_user('race-'+str(i)) for i in range(9)]
    clients = []
    for user in users:
        allowance(user)
        client = Client(); client.force_login(user); clients.append(client)
    config = pool_settings()
    Allowance.objects.filter(user=users[0]).update(extra_balance=1)

    def race(jobs):
        barrier = Barrier(len(jobs))
        def run(job):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                return job()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
            return list(executor.map(run, jobs))

    def send(client, **kwargs):
        payload = dict(request_id=str(uuid.uuid4()), kind='packet', mode='random', points='50',
                       count='2', channel='developers', greeting='race', confirm='yes')
        payload.update(kwargs)
        return client.post('/messages/points/send/', payload).status_code

    same_id = str(uuid.uuid4())
    # Separate clients/sessions prevent session writes from hiding gift contention.
    senders=[]
    for _ in range(8):
        client=Client();client.force_login(users[0]);senders.append(client)
    statuses=race([lambda client=c: send(client, request_id=same_id) for c in senders])
    assert sorted(statuses)==[200]*7+[201], statuses
    assert PointGift.objects.count()==1 and Allowance.objects.get(user=users[0]).extra_balance==Decimal('.5')
    print('PASS concurrent identical sends debit once')
    statuses=race([lambda client=c: client.post('/messages/points/'+same_id+'/claim/', {'confirm':'yes'}).status_code for c in clients[1:]])
    assert statuses.count(200)==2 and statuses.count(400)==6, statuses
    gift=PointGift.objects.get(pk=same_id)
    assert gift.claimed_count==2 and gift.remaining_cny==0
    assert sum(Allowance.objects.values_list('extra_balance',flat=True))==1
    print('PASS competing claims conserve all points and enforce share count')

    assert send(clients[0], kind='transfer', mode='equal', count='1', points='10', channel='dm:'+str(users[1].pk))==201
    gift=PointGift.objects.latest('created_at');claim_url='/messages/points/'+str(gift.pk)+'/claim/'
    receivers=[]
    for _ in range(8):
        client=Client();client.force_login(users[1]);receivers.append(client)
    statuses=race([lambda client=c: client.post(claim_url,{'confirm':'yes'}).status_code for c in receivers])
    assert statuses==[200]*8 and PointGiftReceipt.objects.filter(gift=gift).count()==1
    assert sum(Allowance.objects.values_list('extra_balance',flat=True))==1
    print('PASS duplicate concurrent claims credit once')

    assert send(clients[0], kind='transfer', mode='equal', count='1', points='10', channel='dm:'+str(users[1].pk))==201
    gift=PointGift.objects.latest('created_at')
    PointGift.objects.filter(pk=gift.pk).update(expires_at=timezone.now()-timezone.timedelta(seconds=1))
    results=race([expire_gifts for _ in range(8)])
    assert sum(results)==1 and sum(Allowance.objects.values_list('extra_balance',flat=True))==1
    print('PASS concurrent expiration refunds once')

    provider=Provider.objects.create(name='race',base_url='https://example.invalid/v1',key_env='GIFT_RACE_FAKE_KEY')
    model=PoolModel.objects.create(provider=provider,model_id='race')
    PriceVersion.objects.create(model=model,effective_from=timezone.now(),input_rate=0,output_rate=100,cached_rate=0,cache_write_rate=0)
    config.default_weekly_limit=0;config.max_call_cost=1;config.save()
    Allowance.objects.filter(user=users[0]).update(extra_balance=1,extra_reserved=0)
    def reserve_only():
        try:
            call=reserve(User.objects.get(pk=users[0].pk),model,[],[],1000,'chat',uuid.uuid4(),None,None)
            return ('reserved',call)
        except ValidationError:
            return ('refused',None)
    results=race([reserve_only,lambda: ('gift',send(clients[0],kind='transfer',mode='equal',count='1',points='95',channel='dm:'+str(users[1].pk)))])
    balance=Allowance.objects.get(user=users[0]);assert balance.extra_balance>=balance.extra_reserved>=0
    assert not (results[0][0]=='reserved' and results[1][1]==201),results
    assert results[0][0]=='reserved' or results[1][1]==201, results
    if results[0][0]=='reserved': settle(results[0][1],None,status='failed')
    assert not BudgetWeek.objects.filter(scope='user:'+str(users[0].pk),week=week_now(),spent__gt=0).exists()
    print('PASS gift/API reservation race never spends reserved or weekly points')
    connections.close_all()
print('TOTAL CONCURRENCY CHECKS 5; no provider or SMTP requests')
