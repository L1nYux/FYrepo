"""Retain participant-owned legacy DMs independently of team membership."""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Q
from django.urls import reverse
from .tenancy import scope


@receiver(post_save, sender='core.ChatMessage')
def synchronize(sender, instance, raw=False, **kwargs):
    if raw or instance.room != 'private':return
    from .models import PersonalMessage
    from .identity import nickname
    quote = {'author': nickname(instance.quoted_message.author), 'body': instance.quoted_message.body[:500]} if instance.quoted_message_id else {}
    row,_=PersonalMessage.objects.update_or_create(legacy_message=instance,defaults={
        'sender_id':instance.author_id,'recipient_id':instance.recipient_id,'body':instance.body,
        'withdrawn_at':instance.withdrawn_at,'quote':quote,'sticker_id':instance.sticker_id,'relation_verified':True})
    PersonalMessage.objects.filter(pk=row.pk).update(created_at=instance.created_at)


def references_for(records, viewer):
    from .models import Workspace, TeamMembership
    from . import chat_references, permissions
    cards=[]
    for record in records[:10]:
        unavailable={'title':'内容已不可用或你无权查看','url':'','available':False,'label':'引用内容'}
        space=Workspace.objects.filter(pk=record.get('workspace'),active=True).first()
        if not space or space.owner_id!=viewer.pk and not TeamMembership.objects.filter(team_id=space.team_id,user=viewer,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).exists():
            cards.append(unavailable);continue
        with scope(space):
            kind=record.get('kind')
            if kind not in chat_references.MODELS:cards.append(unavailable);continue
            obj=chat_references.available(viewer,kind).filter(pk=record.get('pk')).first()
            cards.append(chat_references.card(kind,obj) if obj else unavailable)
    return cards


def legacy_data(row, viewer):
    from .models import TeamMembership
    source=row.legacy_message
    files=[{'name':file.original_name,'url':reverse('personal_legacy_file',args=[file.pk])} for file in source.attachments.all()]
    result={'files':files,'references':[],'gift':None,'kind':source.kind}
    records=[{'workspace':ref.workspace_id,'kind':ref.kind,'pk':getattr(ref,ref.kind+'_id')} for ref in source.references.all()]
    result['references']=references_for(records,viewer)
    if TeamMembership.objects.filter(user=viewer,team_id=source.team_id,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).exists():
        from aihub.gifts import card
        from aihub.models import PointGift
        with scope(source.workspace):
            gift=PointGift.objects.filter(message=source).first()
            if gift:result['gift']={**card(gift,viewer),'workspace':source.workspace_id}
    elif __import__('aihub.models',fromlist=['PointGift']).PointGift.all_objects.filter(message=source).exists():
        result['body']='积分转赠记录（原团队）'
    return result
