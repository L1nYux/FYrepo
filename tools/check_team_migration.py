"""Upgrade a disposable 0.2.17 database and check original account/data identity."""
import os
import sys
import tempfile
from pathlib import Path
from decimal import Decimal

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
scratch = root / '.test-scratch'
scratch.mkdir(exist_ok=True)

with tempfile.TemporaryDirectory(prefix='team-upgrade-', dir=scratch) as directory:
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', WORKBENCH_DATA_DIR=directory,
                      WORKBENCH_SECRET_KEY='isolated-team-migration-check', WORKBENCH_DEBUG='1')
    import django
    django.setup()
    from django.db import connection, connections
    from django.db.migrations.executor import MigrationExecutor
    from django.contrib.auth.hashers import make_password
    from django.utils import timezone

    try:
        executor = MigrationExecutor(connection)
        previous = [('core', '0023_member_account_lifecycle'), ('aihub', '0015_assistant_images')]
        executor.migrate(previous)
        old = executor.loader.project_state(previous).apps
        def model(app, name): return old.get_model(app, name)
        password = make_password('fixture-account-password-only')
        User = model('auth', 'User')
        admin = User.objects.create(username='original-admin', email='admin@example.com', password=password,
                                    is_staff=True, is_superuser=True, is_active=True)
        member = User.objects.create(username='original-member', password=password, is_active=True)
        guest = User.objects.create(username='original-guest', password=password, is_active=True)
        suspended = User.objects.create(username='original-suspended', password=password, is_active=False)
        model('core', 'MemberProfile').objects.create(user=guest, tier='normal')
        model('core', 'MemberProfile').objects.create(user=suspended, tier='developer')
        project = model('core', 'Project').objects.create(name='原项目', owner=admin, created_by=admin)
        project.members.add(member)
        task = model('core', 'Task').objects.create(project=project, title='原任务', assignee=member, created_by=admin)
        experiment = model('core', 'Experiment').objects.create(project=project, title='尚无结果的实验', number='E-1', created_by=member)
        chat = model('core', 'ChatMessage').objects.create(room='private', author=admin, recipient=member, body='原私聊')
        settings = model('aihub', 'PoolSettings').objects.create(owner=admin, weekly_limit=Decimal('25'))
        allowance = model('aihub', 'Allowance').objects.create(user=member, extra_balance=Decimal('3.5'))
        provider = model('aihub', 'Provider').objects.create(name='原接口', base_url='https://example.com/v1', key_env='LEGACY_TEST_KEY')
        pooled = model('aihub', 'PoolModel').objects.create(provider=provider, model_id='test-model')
        budget = model('aihub', 'BudgetWeek').objects.create(scope='user:'+str(member.pk), week=timezone.now().date(), spent=Decimal('1.25'))
        identities = [(app, name, row.pk) for app, name, row in [
            ('core','Project',project), ('core','Task',task), ('core','Experiment',experiment),
            ('core','ChatMessage',chat), ('aihub','PoolSettings',settings), ('aihub','Allowance',allowance),
            ('aihub','Provider',provider), ('aihub','PoolModel',pooled), ('aihub','BudgetWeek',budget)]]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate(latest)
        current = executor.loader.project_state(latest).apps
        Team = current.get_model('core','Team')
        Membership = current.get_model('core','TeamMembership')
        assert Team.objects.get(pk=1).owner_id == admin.pk
        assert dict(Membership.objects.values_list('user_id','role')) == {
            admin.pk:'owner', member.pk:'member', guest.pk:'guest', suspended.pk:'member'}
        assert not Membership.objects.get(user_id=suspended.pk).active
        for app, name, pk in identities:
            assert current.get_model(app,name).objects.get(pk=pk).team_id == 1, name
        upgraded = current.get_model('auth','User').objects.get(pk=admin.pk)
        assert upgraded.password == password and upgraded.email == 'admin@example.com'
        assert upgraded.is_staff and upgraded.is_superuser
        upgraded_project = current.get_model('core','Project').objects.get(pk=project.pk)
        assert list(upgraded_project.members.values_list('pk',flat=True)) == [member.pk]
        assert current.get_model('aihub','Allowance').objects.get(pk=allowance.pk).extra_balance == Decimal('3.5')
        assert current.get_model('aihub','BudgetWeek').objects.get(pk=budget.pk).spent == Decimal('1.25')
        assert current.get_model('core','ChatMessage').objects.get(pk=chat.pk).body == '原私聊'
        assert current.get_model('aihub','Provider').objects.get(pk=provider.pk).key_env == 'LEGACY_TEST_KEY'
        MigrationExecutor(connection).migrate(latest)
        assert Membership.objects.count() == 4 and Team.objects.count() == 1
        print('PASS: original identities, password, email, memberships, relationships, balances and idempotent migration')
    finally:
        connections.close_all()
