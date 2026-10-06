"""One navigation surface for personal relationships and team conversations."""
from django.db.models import Q, Max, Case, When, F, OuterRef, Subquery
from django.urls import reverse
from django.contrib.auth.models import User
from .models import TeamMembership, PersonalMessage, ChatGroup, GroupMessage, FriendRequest, ChatMessage
from . import permissions as perms
from .identity import nickname, account_id


def groups_for(user):
    for membership in TeamMembership.objects.filter(user=user,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).select_related('team'):
        default_group(membership.team)
    return ChatGroup.objects.filter(active=True,members__user=user,members__active=True).filter(
        Q(team__isnull=True)|Q(team__active=True,team__memberships__user=user,
        team__memberships__active=True,team__memberships__deleted_at__isnull=True,
        team__memberships__role__in=['owner','admin','member'])).distinct()



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
        return {'person':person,'title':nickname(person),'url':reverse('personal_chat',args=[person.pk])}
    groups=groups_for(user).select_related('team').order_by('name','pk')
    contacts=list(people.order_by('username')[:1000]); colleagues=list(colleagues.order_by('username')[:1000]); groups=list(groups[:1000])
    rows=PersonalMessage.objects.filter(Q(sender=user)|Q(recipient=user)).exclude(hidden_by=user).exclude(legacy_message__hidden_by=user).annotate(peer=Case(When(sender=user,then=F('recipient_id')),default=F('sender_id')))
    from .models import PersonalThreadRead, ChatReadState
    states={s.channel:s for s in PersonalThreadRead.objects.filter(user=user)}
    for key,state in states.items():
        kind,_,pk=key.partition(':')
        if kind=='person' and pk.isdigit():rows=rows.exclude(peer=int(pk),pk__lte=state.cleared_through)
    for state in ChatReadState.all_objects.filter(user=user,channel__startswith='dm:'):
        if state.channel[3:].isdigit():rows=rows.exclude(legacy_message__workspace_id=state.workspace_id,legacy_message_id__lte=state.cleared_through)
    # Imported legacy messages retain their time but receive new personal ids.
    # The newest id therefore need not be the newest message in a conversation.
    latest=rows.filter(peer=OuterRef('peer')).order_by('-created_at','-pk')
    ids=list(rows.order_by().values('peer').annotate(last=Subquery(latest.values('pk')[:1]),
        latest_at=Subquery(latest.values('created_at')[:1])).order_by('-latest_at','-last').values_list('last',flat=True).distinct()[:100])
    recents={}
    for message in rows.filter(pk__in=ids).select_related('sender','recipient'):
        peer=message.recipient if message.sender_id==user.pk else message.sender
        if not message.relation_verified and peer.pk not in {p.pk for p in contacts+colleagues}:continue
        key='person:'+str(peer.pk);state=states.get(key)
        if state and state.removed:
            if message.pk<=state.removed_through:continue
            PersonalThreadRead.objects.filter(pk=state.pk).update(removed=False)
        recents['person:'+str(peer.pk)]={'person':peer,'title':nickname(peer),'preview':'消息已撤回' if message.withdrawn_at or message.legacy_message_id and message.legacy_message.withdrawn_at else message.body[:80],'at':message.created_at,'url':reverse('personal_chat',args=[peer.pk]),'key':'person:'+str(peer.pk),'unread':0}
    group_ids=[g.pk for g in groups]
    group_rows=GroupMessage.objects.filter(group_id__in=group_ids).exclude(hidden_by=user)
    for key,state in states.items():
        kind,_,pk=key.partition(':')
        if kind=='group' and pk.isdigit():group_rows=group_rows.exclude(group_id=int(pk),pk__lte=state.cleared_through)
    latest=group_rows.values('group_id').annotate(last=Max('pk')).values_list('last',flat=True)
    group_latest={m.group_id:m for m in GroupMessage.objects.filter(pk__in=latest)}
    for group in groups:
        if group.is_default:
            from .tenancy import scope
            with scope(group.team.workspace):
                latest=visible_messages(user,ChatMessage.objects.filter(room='developers')).order_by('-pk').first()
                counts=unread_counts(user)
                state=conversation_states(user).get('developers')
                if state and state.removed:continue
            recents['team:'+str(group.team_id)]={'title':group.name,'preview':('消息已撤回' if latest.withdrawn_at else latest.body[:80]) if latest else group.team.name,
                'at':latest.created_at if latest else group.created_at,'url':reverse('group_chat',args=[group.pk]),'key':'team:'+str(group.team_id),'unread':counts.get('developers',0)}
            continue
        message=group_latest.get(group.pk)
        state=states.get('group:'+str(group.pk))
        if state and state.removed:
            if not message or message.pk<=state.removed_through:continue
            PersonalThreadRead.objects.filter(pk=state.pk).update(removed=False)
        preview=('消息已撤回' if message.withdrawn_at else message.body[:80]) if message else group.team.name if group.team_id else '好友群'
        recents['group:'+str(group.pk)]={'title':group.name,'preview':preview,'at':message.created_at if message else group.created_at,'url':reverse('group_chat',args=[group.pk]),'key':'group:'+str(group.pk),'unread':0}
    tab=request.GET.get('tab','chats');tab=tab if tab in ('chats','friends','requests','groups','team') else 'chats'
    match=lambda title:not query or query.casefold() in title.casefold()
    from .models import GroupMember
    preferences={('team:'+str(m.group.team_id) if m.group.is_default else 'group:'+str(m.group_id)):m for m in GroupMember.objects.filter(user=user,active=True,group_id__in=group_ids).select_related('group')}
    for key,entry in recents.items():
        preference=preferences.get(key)
        if preference:
            entry['pinned']=preference.pinned
            if preference.remark:entry['title']=preference.remark
    recent_list=sorted(recents.values(),key=lambda v:(v.get('pinned',False),v['at'] is not None,v['at'].timestamp() if v['at'] else 0),reverse=True)
    personal_counts=unread(user)
    for entry in recent_list:
        entry['selected']=request.path==entry['url'] or entry['key']=='team:'+str(getattr(request.team,'pk',None)) and request.resolver_match and request.resolver_match.url_name=='messages_hub' and request.GET.get('room')!='public'
        entry['muted']=bool(states.get(entry['key']) and states[entry['key']].muted or preferences.get(entry['key']) and preferences[entry['key']].muted)
        entry['unread']=personal_counts.get(entry['key'],entry['unread'])
    return {'communication_tab':tab,'communication_query':query,
        'communication_recent':[v for v in recent_list if match(v['title']+' '+v['preview'])],
        'communication_friends':[contact(p) for p in contacts if match(nickname(p)+' '+account_id(p))],
        'communication_colleagues':[contact(p) for p in colleagues if match(nickname(p)+' '+account_id(p))],
        'communication_groups':[g for g in groups if match(g.name)],
        'communication_requests':FriendRequest.objects.filter(recipient=user,state='pending').select_related('sender').order_by('-pk')[:100],
        'communication_request_count':FriendRequest.objects.filter(recipient=user,state='pending').count(),
        'communication_members':colleagues if getattr(request,'team',None) and perms.is_team_member(request) else [],
        'communication_group_friends':contacts,
        'team_application_count':team_application_count(request)}


def unread(user):
    from .models import PersonalThreadRead
    from .personal_messages import friends
    from django.db.models import Count
    reads=dict(PersonalThreadRead.objects.filter(user=user).values_list('channel','last_message_id'))
    teams=TeamMembership.objects.filter(user=user,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).values('team_id')
    colleagues=TeamMembership.objects.filter(team_id__in=teams,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).values('user_id')
    peers=User.objects.filter(Q(pk__in=friends(user).values('pk'))|Q(pk__in=colleagues),is_active=True).exclude(pk=user.pk)
    rows=PersonalMessage.objects.filter(Q(relation_verified=True)|Q(sender__in=peers),recipient=user,withdrawn_at__isnull=True).exclude(hidden_by=user).exclude(legacy_message__hidden_by=user).exclude(legacy_message__withdrawn_at__isnull=False)
    from .models import ChatReadState
    for state in ChatReadState.all_objects.filter(user=user,channel__startswith='dm:'):
        if state.channel[3:].isdigit():rows=rows.exclude(legacy_message__workspace_id=state.workspace_id,legacy_message_id__lte=max(state.cleared_through,state.last_message_id))
    all_groups=list(groups_for(user).select_related('team__workspace'))
    group_rows=GroupMessage.objects.filter(group__in=all_groups,withdrawn_at__isnull=True).exclude(author=user).exclude(hidden_by=user)
    for channel,cursor in reads.items():
        kind,_,pk=channel.partition(':')
        if kind=='person':rows=rows.exclude(sender_id=pk,pk__lte=cursor)
        elif kind=='group':group_rows=group_rows.exclude(group_id=pk,pk__lte=cursor)
    result={'person:'+str(v['sender_id']):v['count'] for v in rows.values('sender_id').annotate(count=Count('pk'))} | {
        'group:'+str(v['group_id']):v['count'] for v in group_rows.values('group_id').annotate(count=Count('pk'))}
    from .tenancy import scope
    from .messages import unread_counts
    for group in all_groups:
        if group.is_default:
            with scope(group.team.workspace):result['team:'+str(group.team_id)]=unread_counts(user).get('developers',0)
    return result


def team_application_count(request):
    from .models import TeamApplication
    memberships=TeamMembership.objects.filter(user=request.user,active=True,deleted_at__isnull=True,team__active=True)
    permitted=[m.team_id for m in memberships if m.role in ('owner','admin') or 'recruitment' in m.permissions]
    return TeamApplication.objects.filter(opening__team_id__in=permitted,state='pending').count()


def default_group(team):
    from .models import GroupMember
    owner=team.owner_id or TeamMembership.objects.filter(team=team,role='owner',active=True).values_list('user_id',flat=True).first()
    if not owner:return None
    group,_=ChatGroup.objects.get_or_create(team=team,is_default=True,defaults={'name':team.name+' · 团队群','owner_id':owner})
    if group.owner_id!=owner:ChatGroup.objects.filter(pk=group.pk).update(owner_id=owner);group.owner_id=owner
    ids=list(TeamMembership.objects.filter(team=team,active=True,deleted_at__isnull=True,role__in=['owner','admin','member'],user__is_active=True).values_list('user_id',flat=True))
    known=set(GroupMember.objects.filter(group=group).values_list('user_id',flat=True))
    missing=[GroupMember(group=group,user_id=pk,admin=pk==group.owner_id) for pk in ids if pk not in known]
    if missing:GroupMember.objects.bulk_create(missing,ignore_conflicts=True)
    GroupMember.objects.filter(group=group,user_id__in=ids,active=False).update(active=True)
    administrators=list(TeamMembership.objects.filter(team=team,user_id__in=ids,role__in=['owner','admin']).values_list('user_id',flat=True))
    GroupMember.objects.filter(group=group,user_id__in=administrators,admin=False).update(admin=True)
    GroupMember.objects.filter(group=group,admin=True).exclude(user_id__in=administrators).update(admin=False)
    GroupMember.objects.filter(group=group,active=True).exclude(user_id__in=ids).update(active=False)
    return group
