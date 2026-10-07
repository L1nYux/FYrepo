from django.db import migrations


def move_private_history(apps,schema_editor):
    db=schema_editor.connection.alias
    Workspace=apps.get_model('core','Workspace')
    Job=apps.get_model('aihub','AssistantJob')
    Conversation=apps.get_model('aihub','AssistantConversation')
    Image=apps.get_model('aihub','AssistantImage')
    Order=apps.get_model('aihub','AssistantJobOrder')
    users=set(Conversation.objects.using(db).values_list('user_id',flat=True))|set(Job.objects.using(db).values_list('user_id',flat=True))|set(Image.objects.using(db).values_list('user_id',flat=True))
    for user_id in users:
        personal,_=Workspace.objects.using(db).get_or_create(owner_id=user_id,defaults={'kind':'personal'})
        for old in Job.objects.using(db).filter(user_id=user_id,billing_workspace__isnull=True).values('pk','workspace_id').iterator():
            Job.objects.using(db).filter(pk=old['pk']).update(billing_workspace_id=old['workspace_id'])
        ids=Job.objects.using(db).filter(user_id=user_id).values('pk')
        Order.objects.using(db).filter(job_id__in=ids).update(workspace_id=personal.pk,team_id=None)
        for model in (Conversation,Job,Image):
            model.objects.using(db).filter(user_id=user_id).update(workspace_id=personal.pk,team_id=None)


class Migration(migrations.Migration):
    dependencies=[('aihub','0019_collaboration_and_private_funding')]
    operations=[migrations.RunPython(move_private_history)]
