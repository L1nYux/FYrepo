"""One navigation surface for personal relationships and team conversations."""
from django.db.models import Q, Max, Case, When, F
from django.urls import reverse
from django.contrib.auth.models import User
from .models import TeamMembership, PersonalMessage, ChatGroup, GroupMessage, FriendRequest, ChatMessage
from . import permissions as perms
from .identity import nickname, account_id


def groups_for(user):
    return ChatGroup.objects.filter(members__user=user, members__active=True, team__active=True,
        team__memberships__user=user, team__memberships__active=True,
        team__memberships__deleted_at__isnull=True, team__memberships__role__in=['owner','admin','member']).distinct()


def navigation(request):
    from .personal_messages import friends
    from .messages import visible_messages, conversation_states, unread_counts
    from .tenancy import team_users
    user=request.user
    query=request.GET.get('q','').strip()[:150]
    teams=TeamMembership.objects.filter(user=user,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).values('team_id')
    colleagues=User.objects.filter(pk__in=TeamMembership.objects.filter(team_id__in=teams,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).values('user_id'),is_active=True).exclude(pk=user.pk)
    people=friends(user)
    local_ids=set(team_users(member_only=True).values_list('pk',flat=True)) if perms.is_team_member(request) else set()
    def contact(person):
        return {'person':person,'title':nickname(person),'url':reverse('messages_private' if person.pk in local_ids else 'personal_chat',args=[person.pk])}
    groups=groups_for(user).select_related('team').order_by('name','pk')
    contacts=list(people.order_by('username')[:1000]); colleagues=list(colleagues.order_by('username')[:1000]); groups=list(groups[:1000])
    rows=PersonalMessage.objects.filter(Q(sender=user)|Q(recipient=user)).annotate(peer=Case(When(sender=user,then=F('recipient_id')),default=F('sender_id')))
    ids=list(rows.values('peer').annotate(last=Max('pk')).order_by('-last').values_list('last',flat=True)[:100])
    recents={}
    for message in rows.filter(pk__in=ids).select_related('sender','recipient'):
        peer=message.recipient if message.sender_id==user.pk else message.sender
        if not peer.is_active or (peer.pk not in {p.pk for p in contacts+colleagues}):continue
        recents['person:'+str(peer.pk)]={'person':peer,'title':nickname(peer),'preview':message.body[:80],'at':message.created_at,'url':reverse('personal_chat',args=[peer.pk]),'key':'person:'+str(peer.pk),'unread':0}
    group_ids=[g.pk for g in groups]
    latest=GroupMessage.objects.filter(group_id__in=group_ids).values('group_id').annotate(last=Max('pk')).values_list('last',flat=True)
    group_latest={m.group_id:m for m in GroupMessage.objects.filter(pk__in=latest)}
    for group in groups:
        message=group_latest.get(group.pk)
        recents['group:'+str(group.pk)]={'title':group.name,'preview':message.body[:80] if message else group.team.name,'at':message.created_at if message else group.created_at,'url':reverse('group_chat',args=[group.pk]),'key':'group:'+str(group.pk),'unread':0}
    if perms.is_team_member(request):
        states=conversation_states(user); counts=unread_counts(user,request)
        legacy=visible_messages(user,ChatMessage.objects.filter(Q(room='private',author=user)|Q(room='private',recipient=user)|Q(room__in=['public','developers'])))
        keys=legacy.annotate(peer=Case(When(author=user,then=F('recipient_id')),default=F('author_id'))).values('room','peer').annotate(last=Max('pk')).values_list('last',flat=True)
        for message in legacy.filter(pk__in=keys).select_related('author','recipient').order_by('pk'):
            private=message.room=='private'; peer=message.recipient if message.author_id==user.pk else message.author
            if private and peer.pk not in local_ids:continue
            key='dm:'+str(peer.pk) if private else message.room
            if states.get(key) and states[key].removed:continue
            entry={'person':peer if private else None,'title':nickname(peer) if private else '公共讨论' if key=='developers' else '公共聊天室',
                'preview':'消息已撤回' if message.withdrawn_at else message.body[:80] or '图片 / 附件', 'at':message.created_at,
                'url':reverse('messages_private',args=[peer.pk]) if private else reverse('messages_hub')+('?room=public' if key=='public' else ''),
                'key':key,'unread':counts.get(key,0),'muted':bool(states.get(key) and states[key].muted)}
            index='person:'+str(peer.pk) if private else key
            if index not in recents or entry['at']>recents[index]['at']:recents[index]=entry
        for key,label in [('developers','公共讨论'),('public','公共聊天室')]:
            if key not in recents and not (states.get(key) and states[key].removed):recents[key]={'title':label,'preview':getattr(request,'team',None).name,'url':reverse('messages_hub')+('?room=public' if key=='public' else ''),'key':key,'unread':counts.get(key,0),'at':None}
    tab=request.GET.get('tab','chats');tab=tab if tab in ('chats','friends','requests','groups','team') else 'chats'
    match=lambda title:not query or query.casefold() in title.casefold()
    recent_list=sorted(recents.values(),key=lambda v:(v['at'] is not None,v['at'].timestamp() if v['at'] else 0),reverse=True)
    personal_counts=unread(user)
    for entry in recent_list:
        entry['unread']=personal_counts.get(entry['key'],entry['unread'])
    return {'communication_tab':tab,'communication_query':query,
        'communication_recent':[v for v in recent_list if match(v['title']+' '+v['preview'])],
        'communication_friends':[contact(p) for p in contacts if match(nickname(p)+' '+account_id(p))],
        'communication_colleagues':[contact(p) for p in colleagues if match(nickname(p)+' '+account_id(p))],
        'communication_groups':[g for g in groups if match(g.name)],
        'communication_requests':FriendRequest.objects.filter(recipient=user,state='pending').select_related('sender').order_by('-pk')[:100],
        'communication_request_count':FriendRequest.objects.filter(recipient=user,state='pending').count(),
        'communication_members':colleagues if perms.is_team_member(request) else []}


def unread(user):
    from .models import PersonalThreadRead
    from .personal_messages import friends
    from django.db.models import Count
    reads=dict(PersonalThreadRead.objects.filter(user=user).values_list('channel','last_message_id'))
    teams=TeamMembership.objects.filter(user=user,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).values('team_id')
    colleagues=TeamMembership.objects.filter(team_id__in=teams,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).values('user_id')
    peers=User.objects.filter(Q(pk__in=friends(user).values('pk'))|Q(pk__in=colleagues),is_active=True).exclude(pk=user.pk)
    rows=PersonalMessage.objects.filter(recipient=user,sender__in=peers)
    group_rows=GroupMessage.objects.filter(group__in=groups_for(user)).exclude(author=user)
    for channel,cursor in reads.items():
        kind,_,pk=channel.partition(':')
        if kind=='person':rows=rows.exclude(sender_id=pk,pk__lte=cursor)
        elif kind=='group':group_rows=group_rows.exclude(group_id=pk,pk__lte=cursor)
    return {'person:'+str(v['sender_id']):v['count'] for v in rows.values('sender_id').annotate(count=Count('pk'))} | {
        'group:'+str(v['group_id']):v['count'] for v in group_rows.values('group_id').annotate(count=Count('pk'))}
