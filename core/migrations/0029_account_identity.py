import re
from django.db import migrations, models


def populate(apps, schema_editor):
    users=apps.get_model('auth','User');profiles=apps.get_model('core','MemberProfile');alias=schema_editor.connection.alias
    rows=list(users.objects.using(alias).order_by('pk').values('pk','username'))
    names={row['username'].casefold():row['pk'] for row in rows};used=set()
    # Freeze the original five once, during upgrade. Joining a team or gaining
    # an administrator role later cannot confer this login compatibility.
    membership=apps.get_model('core','TeamMembership')
    founders=list(membership.objects.using(alias).filter(team_id=1,active=True,
        deleted_at__isnull=True,user__is_active=True,role__in=['owner','admin','member'])
        .order_by('user_id').values_list('user_id',flat=True))
    founders=set(founders) if len(founders)==5 else set()
    for row in rows:
        name=row['username'].lower()
        if not re.fullmatch(r'[a-z][a-z0-9_-]{2,31}',name) or name in used or names.get(name)!=row['pk']:
            name='zy_'+str(row['pk']).zfill(6)
            while name in used or name in names and names[name]!=row['pk']:name+='x'
        used.add(name)
        profile,_=profiles.objects.using(alias).get_or_create(user_id=row['pk'])
        profile.workbench_id=name;profile.nickname=row['username'][:80]
        profile.legacy_login_allowed=row['pk'] in founders
        profile.save(update_fields=['workbench_id','nickname','legacy_login_allowed'])


class Migration(migrations.Migration):
    dependencies=[('core','0028_personal_thread_read')]
    operations=[
        migrations.AddField(model_name='memberprofile',name='workbench_id',field=models.CharField('工作台号',max_length=32,unique=True,null=True,blank=True)),
        migrations.AddField(model_name='memberprofile',name='nickname',field=models.CharField('昵称',max_length=80,blank=True)),
        migrations.AddField(model_name='memberprofile',name='workbench_id_changed',field=models.BooleanField(default=False)),
        migrations.AddField(model_name='memberprofile',name='legacy_login_allowed',field=models.BooleanField('元老账号登录兼容',default=False,editable=False)),
        migrations.RunPython(populate,migrations.RunPython.noop),
    ]
