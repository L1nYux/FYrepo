"""Shared mobile/desktop data contracts; permissions remain server enforced."""
import re
from functools import wraps
from django.contrib.auth.models import User
from django.db.models import Q, Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from .models import ConversationPreference, TeamMembership, PersonalThreadRead, ChatReadState, GroupMember, GroupMessage, ChatMessage, Friendship
from .identity import nickname, account_id
from .tenancy import scope


def account_api(view):
    @wraps(view)
    @never_cache
    def wrapped(request,*args,**kwargs):
        if not request.user.is_authenticated:return JsonResponse({'error':'登录已失效，请重新登录。'},status=401)
        return view(request,*args,**kwargs)
    wrapped.expects_json=True
    return wrapped


def contact_name(viewer, person):
    value=ConversationPreference.objects.filter(user=viewer,channel='person:'+str(person.pk)).values_list('remark',flat=True).first()
    return value or nickname(person)


@account_api
@require_GET
def teams(request):
    rows=TeamMembership.objects.filter(user=request.user,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).select_related('team','team__workspace').order_by('team__name')
    return JsonResponse({'teams':[{'id':m.team_id,'space':m.team.workspace.pk,'name':m.team.name,'role':m.role,'selected':m.team_id==getattr(getattr(request,'team',None),'pk',None)} for m in rows]})


def channel_access(request, key):
    if not re.fullmatch(r'(person|group|team):[1-9][0-9]{0,17}',key):return None
    kind,raw=key.split(':');pk=int(raw)
    if kind=='person':
        from .personal_messages import permitted_peer
        peer=get_object_or_404(User,pk=pk,is_active=True)
        from .models import PersonalMessage
        return peer if permitted_peer(request.user,peer) or PersonalMessage.objects.filter(Q(sender=request.user,recipient=peer)|Q(sender=peer,recipient=request.user),relation_verified=True).exists() or Friendship.objects.filter(first_id=min(peer.pk,request.user.pk),second_id=max(peer.pk,request.user.pk)).exists() or ConversationPreference.objects.filter(user=request.user,channel=key).exists() else None
    if kind=='group':
        from .personal_messages import permitted_group
        return permitted_group(request,pk)
    member=TeamMembership.objects.filter(user=request.user,team_id=pk,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).select_related('team','team__workspace').first()
    return member.team if member else None


def preference_value(pref):
    value = {key:getattr(pref,key) for key in ('channel','remark','note','phone','tags','pinned','manual_unread','blocked','notification_mode')}
    value['background_url'] = '/app/background/?channel=' + pref.channel if pref.background else ''
    return value


def conversation_preference(user, key, target=None):
    """Seed preferences from legacy read/member settings without resetting them."""
    defaults = {'notification_mode': 'all' if key.startswith('person:') else 'important'}
    state = PersonalThreadRead.objects.filter(user=user, channel=key).first()
    member = None
    if key.startswith('group:'):
        member = GroupMember.objects.filter(user=user, group_id=key.split(':')[1], active=True).first()
    elif key.startswith('team:'):
        member = GroupMember.objects.filter(user=user, group__team_id=key.split(':')[1], group__is_default=True, active=True).first()
        if target:
            with scope(target.workspace, http=True):
                state = ChatReadState.objects.filter(user=user, channel='developers').first()
    defaults['pinned'] = bool(member and member.pinned)
    if (member and member.muted) or (state and state.muted):
        defaults['notification_mode'] = 'none'
    return ConversationPreference.objects.get_or_create(user=user, channel=key, defaults=defaults)[0]


def sync_legacy_mute(user, key, muted, target=None):
    pref = conversation_preference(user, key, target)
    pref.notification_mode = 'none' if muted else 'all'
    pref.save(update_fields=['notification_mode'])


@account_api
@require_http_methods(['GET','POST'])
def preference(request):
    key=request.POST.get('channel') or request.GET.get('channel','')
    target=channel_access(request,key)
    if not target:return JsonResponse({'error':'会话不可用。'},status=403)
    pref=conversation_preference(request.user,key,target)
    if request.method=='POST':
        action=request.POST.get('action','')
        if action in ('pin','unpin'):
            pref.pinned=action=='pin'
            members=GroupMember.objects.filter(user=request.user,active=True)
            if key.startswith('group:'):members.filter(group=target).update(pinned=pref.pinned)
            elif key.startswith('team:'):members.filter(group__team=target,group__is_default=True).update(pinned=pref.pinned)
        elif action in ('unread','read','clear_manual'):
            pref.manual_unread=action=='unread'
            if action=='read':
                from .models import PersonalMessage
                if key.startswith('team:'):
                    with scope(target.workspace,http=True):
                        from .messages import visible_messages
                        latest=visible_messages(request.user,ChatMessage.objects.filter(room='developers')).aggregate(last=Max('pk'))['last'] or 0
                        state,_=ChatReadState.objects.get_or_create(user=request.user,channel='developers')
                        ChatReadState.objects.filter(pk=state.pk).update(last_message_id=max(state.last_message_id,latest))
                else:
                    rows=PersonalMessage.objects.filter(Q(sender=request.user,recipient=target)|Q(sender=target,recipient=request.user)).exclude(hidden_by=request.user) if key.startswith('person:') else GroupMessage.objects.filter(group=target).exclude(hidden_by=request.user)
                    latest=rows.aggregate(last=Max('pk'))['last'] or 0
                    state,_=PersonalThreadRead.objects.get_or_create(user=request.user,channel=key)
                    PersonalThreadRead.objects.filter(pk=state.pk).update(last_message_id=max(state.last_message_id,latest))
        elif action in ('background','background_clear'):
            from .chat_media import clean_image
            from django.core.exceptions import ValidationError
            if action=='background':
                try: image=clean_image(request.FILES.get('image'))
                except ValidationError as error:return JsonResponse({'error':error.messages[0]},status=400)
                pref.background.save('background.webp',image,save=False)
            else:pref.background=''
        elif action=='edit':
            remark=request.POST.get('remark','').strip();note=request.POST.get('note','').strip()
            if len(remark)>80 or len(note)>1000:return JsonResponse({'error':'备注最多 80 字，备注说明最多 1000 字。'},status=400)
            phone=request.POST.get('phone','').strip();tags=request.POST.get('tags','').strip()
            if len(phone)>100 or len(tags)>200:return JsonResponse({'error':'联系电话最多 100 字，标签最多 200 字。'},status=400)
            pref.remark=remark;pref.note=note;pref.phone=phone;pref.tags=tags
        elif action=='notifications' and request.POST.get('mode') in ('all','important','none'):
            pref.notification_mode=request.POST['mode']
            muted = pref.notification_mode=='none'
            PersonalThreadRead.objects.filter(user=request.user,channel=key).update(muted=muted)
            if key.startswith('group:'):GroupMember.objects.filter(user=request.user,group=target,active=True).update(muted=muted)
            elif key.startswith('team:'):
                GroupMember.objects.filter(user=request.user,group__team=target,group__is_default=True,active=True).update(muted=muted)
                with scope(target.workspace,http=True):ChatReadState.objects.filter(user=request.user,channel='developers').update(muted=muted)
        elif action in ('block','unblock') and key.startswith('person:'):pref.blocked=action=='block'
        elif action=='delete_friend' and key.startswith('person:'):
            if request.POST.get('confirm')!='yes':return JsonResponse({'error':'请确认删除联系人。'},status=400)
            first,second=sorted([target.pk,request.user.pk]);Friendship.objects.filter(first_id=first,second_id=second).delete()
        else:return JsonResponse({'error':'操作无效。'},status=400)
        pref.save()
    return JsonResponse({'ok':True,**preference_value(pref)})


def important_label(message,user,owner,admins):
    if message.withdrawn_at:return ''
    text=message.body
    # Exact identifiers avoid matching @ann to @anna. Display names may coincide;
    # an account id always remains a valid mention target.
    names=[account_id(user),nickname(user)]
    if any(re.search(r'@'+re.escape(name)+r'(?=$|[\s，。！？,!?;；:：])',text) for name in names):return '[有人@我]'
    if message.author_id in admins or message.author_id==owner:
        if re.search(r'@(所有人|全体)(?=$|[\s，。！？,!?])',text):return '[@所有人]'
        if text.startswith('群公告已更新：'):return '[群公告]'
        return '[群主消息]' if message.author_id==owner else '[管理员消息]'
    return ''


@account_api
@require_GET
def notifications(request):
    from .communication import navigation
    from .chat_media import preview as message_preview, group_avatar_url
    data=navigation(request);user=request.user
    prefs={p.channel:p for p in ConversationPreference.objects.filter(user=user)}
    reads={r.channel:r for r in PersonalThreadRead.objects.filter(user=user)}
    groups={m.group_id:m for m in GroupMember.objects.filter(user=user,active=True,group__active=True).select_related('group','group__team__workspace')}
    teams={m.group.team_id:m for m in groups.values() if m.group.is_default}
    from .models import PersonalMessage
    incoming=PersonalMessage.objects.filter(recipient=user,withdrawn_at__isnull=True).exclude(hidden_by=user).exclude(legacy_message__hidden_by=user).exclude(legacy_message__withdrawn_at__isnull=False)
    latest_private={str(row['sender_id']):row['last'] for row in incoming.values('sender_id').annotate(last=Max('pk'))}
    administrators={}
    for group_id,administrator in GroupMember.objects.filter(group_id__in=groups,active=True,admin=True).values_list('group_id','user_id'):administrators.setdefault(group_id,set()).add(administrator)
    output=[];total=0
    for entry in data['communication_recent'][:100]:
        key=entry['key'];pref=prefs.get(key);manual=bool(pref and pref.manual_unread)
        muted=bool(entry.get('muted'));count=entry.get('unread',0);label='';important_id=0;latest_id=0;preview=entry['preview']
        kind,raw=key.split(':')
        mode=pref.notification_mode if pref else 'all' if kind=='person' else 'important'
        muted=muted or mode=='none'
        if kind=='person':
            latest_id=latest_private.get(raw,0)
        else:
            member=teams.get(int(raw)) if kind=='team' else groups.get(int(raw))
            if not member:continue
            group=member.group
            admins=administrators.get(group.pk,set())
            if kind=='team':
                with scope(group.team.workspace,http=True):
                    from .messages import visible_messages
                    state=ChatReadState.objects.filter(user=user,channel='developers').first()
                    cursor=max(state.last_message_id,state.cleared_through) if state else 0
                    unread=list(visible_messages(user,ChatMessage.objects.filter(room='developers',pk__gt=cursor,withdrawn_at__isnull=True).exclude(author=user)).order_by('-pk')[:200])
            else:
                state=reads.get(key);cursor=max(state.last_message_id,state.cleared_through) if state else 0
                unread=list(GroupMessage.objects.filter(group=group,pk__gt=cursor,withdrawn_at__isnull=True).exclude(author=user).exclude(hidden_by=user).order_by('-pk')[:200])
            latest_id=unread[0].pk if unread else 0
            for message in unread:
                label=important_label(message,user,group.owner_id,admins)
                if label:
                    important_id=message.pk
                    if mode=='important' or muted:preview=message_preview(message,author=True)
                    break
        badge=count if kind=='person' and not muted and mode!='none' else 0
        total+=badge
        if mode=='none':label=''
        popup=count>0 and mode!='none' and ((kind=='person' and not muted) or (bool(label) if mode=='important' or muted else True))
        from .avatars import avatar_url
        person=entry.get('person')
        event_id=important_id if kind!='person' and (mode=='important' or muted) else latest_id
        output.append({'member_id':person.pk if person else None,'avatar_url':avatar_url(person) if person else group_avatar_url(entry['group']) if entry.get('group') else '', 'initial':nickname(person)[:1] if person else '群','at':entry['at'].isoformat() if entry.get('at') else '', 'key':key,'title':entry['title'],'preview':preview,'url':entry['url'],'unread':count,'badge':min(badge,100),'muted':muted,'manual_unread':manual,'pinned':bool(pref and pref.pinned or entry.get('pinned')),'label':label,'message_id':event_id,'latest_message_id':latest_id,'popup':popup})
    from .models import AccountNotice
    notices=AccountNotice.objects.filter(user=user,read_at__isnull=True,private_message__isnull=True).count()
    total+=data['communication_request_count']+data.get('team_application_count',0)+notices
    return JsonResponse({'account':str(user.pk),'total':total,'conversations':output,'friend_request_count':data['communication_request_count'],'notice_count':notices})


@account_api
@require_http_methods(['GET','POST'])
def forward(request):
    """Copy a visible message through the existing send path, never a gift."""
    if request.method == 'GET':
        return forward_recipients(request)
    from .personal_messages import thread_rows, stream, personal, group_chat
    from .models import PersonalMessage
    from .messages import visible_messages
    key=request.POST.get('source','');destination=request.POST.get('target','')
    raw=request.POST.get('id','')
    if not raw.isascii() or not raw.isdigit() or len(raw)>18:return JsonResponse({'error':'消息无效。'},status=400)
    token=request.POST.get('token','')
    if not re.fullmatch(r'[a-zA-Z0-9-]{16,64}',token):return JsonResponse({'error':'转发请求无效。'},status=400)
    if request.POST.get('confirm')!='yes':return JsonResponse({'error':'请确认转发。'},status=400)
    note=request.POST.get('note','').strip()
    if len(note)>2000:return JsonResponse({'error':'留言最多 2000 字。'},status=400)
    selected_file=request.POST.get('attachment','')
    if selected_file and not re.fullmatch(r'(upload|legacy|attachment):[1-9][0-9]{0,17}',selected_file):
        return JsonResponse({'error':'文件无效。'},status=400)
    from .models import MessageForwardReceipt
    import hashlib
    source=hashlib.sha256((key+':'+raw+'|'+selected_file+'|'+note).encode()).hexdigest() if selected_file or note else key+':'+raw
    receipt=MessageForwardReceipt.objects.filter(user=request.user,token=token).first()
    if receipt:
        # A committed receipt confirms a lost response even after the source is withdrawn.
        if receipt.source!=source or receipt.target!=destination:return JsonResponse({'error':'转发请求已用于另一条消息。'},status=409)
        return JsonResponse({'ok':True,'repeated':True})
    if not channel_access(request,key) or not channel_access(request,destination):return JsonResponse({'error':'来源或目标会话不可用。'},status=403)
    kind,pk=key.split(':')
    if kind=='team':
        team=channel_access(request,key)
        with scope(team.workspace,http=True):
            item=get_object_or_404(visible_messages(request.user,ChatMessage.objects.filter(room='developers')),pk=raw)
            uploads=list(item.attachments.all())
        legacy=item
    else:
        rows,_,_,_=thread_rows(request,int(pk),kind=='group');item=rows.filter(pk=raw).first()
        if item is None:
            from .models import LocalChatDelivery
            delivery=LocalChatDelivery.objects.filter(kind='personal' if kind=='person' else 'group',message_id=raw,purged_at__isnull=False).first()
            if not delivery or request.user.pk not in delivery.recipients or kind=='person' and int(pk) not in delivery.recipients or kind=='group' and delivery.group_id!=int(pk):return JsonResponse({'error':'原记录不可用。'},status=404)
            text=request.POST.get('body','').strip()
            if not text or len(text)>2000:return JsonResponse({'error':'本机记录转发限 1–2000 字。'},status=400)
            from types import SimpleNamespace
            item=SimpleNamespace(body=text,withdrawn_at=None,sticker=None)
            legacy=None;uploads=[]
        else:
            legacy=getattr(item,'legacy_message',None);uploads=list(item.uploads.all())
        if legacy:
            from .models import Attachment
            uploads+=list(Attachment.all_objects.filter(chat_message=legacy))
    if item.withdrawn_at or legacy and legacy.withdrawn_at:return JsonResponse({'error':'消息已撤回。'},status=400)
    if legacy and (legacy.kind=='notice' or hasattr(legacy,'point_gift')):return JsonResponse({'error':'积分消息和系统提示不能转发。'},status=400)
    body=item.body
    if selected_file:
        file_kind,file_pk=selected_file.split(':')
        from .models import MessageUpload, Attachment
        model=MessageUpload if file_kind=='upload' else Attachment
        uploads=[file for file in uploads if isinstance(file,model) and file.pk==int(file_pk)]
        if len(uploads)!=1:return JsonResponse({'error':'该文件不属于原消息或已不可用。'},status=404)
        body=''
    # Recheck destination's normal send permission; historical access is insufficient.
    from .personal_messages import permitted_peer, permitted_group
    from .models import ChatGroup, MessageUpload
    from django.db import transaction
    from django.core.exceptions import PermissionDenied
    sticker=getattr(item,'sticker',None) or (getattr(legacy,'sticker',None) if legacy else None)
    if sticker and not selected_file:
        from types import SimpleNamespace
        from pathlib import Path
        uploads.append(SimpleNamespace(file=sticker.file,original_name=sticker.name+Path(sticker.file.name).suffix))
    if not body and not uploads:return JsonResponse({'error':'这条消息只有资料引用，请复制需要的内容后发送。'},status=400)
    target_kind,target_pk=destination.split(':')
    with transaction.atomic():
        receipt,created=MessageForwardReceipt.objects.get_or_create(user=request.user,token=token,defaults={'source':source,'target':destination})
        if not created:
            if receipt.source!=source or receipt.target!=destination:return JsonResponse({'error':'转发请求已用于另一条消息。'},status=409)
            return JsonResponse({'ok':True,'repeated':True})
        # Copies inherit the destination message permission, including animated images.
        sticker=None
        if target_kind=='person':
            peer=get_object_or_404(User,pk=target_pk,is_active=True)
            if not permitted_peer(user:=request.user,peer):raise PermissionDenied('无法向该联系人发送消息。')
            new=PersonalMessage.objects.create(sender=user,recipient=peer,body=body,sticker=sticker,relation_verified=True)
            for f in uploads:MessageUpload.objects.create(personal=new,file=f.file.name,original_name=f.original_name)
            if note:PersonalMessage.objects.create(sender=user,recipient=peer,body=note,relation_verified=True)
        else:
            group=permitted_group(request,int(target_pk)) if target_kind=='group' else get_object_or_404(ChatGroup,team_id=target_pk,is_default=True,active=True)
            if group.is_default:
                from .models import Attachment
                with scope(group.team.workspace,http=True):
                    new=ChatMessage.objects.create(author=request.user,room='developers',body=body,sticker=sticker)
                    for f in uploads:Attachment.objects.create(chat_message=new,file=f.file.name,original_name=f.original_name,uploaded_by=request.user)
                    if note:ChatMessage.objects.create(author=request.user,room='developers',body=note)
            else:
                new=GroupMessage.objects.create(group=group,author=request.user,body=body,sticker=sticker)
                for f in uploads:MessageUpload.objects.create(message=new,file=f.file.name,original_name=f.original_name)
                if note:GroupMessage.objects.create(group=group,author=request.user,body=note)
    return JsonResponse({'ok':True})


def forward_recipients(request):
    """Recent chats, contacts and joined groups, without requiring a prior message."""
    from .communication import navigation
    from .personal_messages import permitted_peer
    from .avatars import avatar_url
    from .chat_media import group_avatar_url
    data=navigation(request)
    contacts={};groups={};recent=[]
    rows=data['communication_friends']+data['communication_colleagues']
    people={row['person'].pk for row in rows}
    blocked={int(key.split(':')[1]) for key in ConversationPreference.objects.filter(
        user=request.user,blocked=True,channel__startswith='person:').values_list('channel',flat=True)
        if re.fullmatch(r'person:[1-9][0-9]*',key)}
    blocked.update(ConversationPreference.objects.filter(user_id__in=people,blocked=True,
        channel='person:'+str(request.user.pk)).values_list('user_id',flat=True))
    for row in rows:
        person=row['person']
        # Navigation already checks friendships and current team membership.
        if person.is_active and person.pk not in blocked and person.pk!=request.user.pk:
            key='person:'+str(person.pk)
            contacts[key]={'key':key,'title':row['title'],'account':account_id(person),'avatar_url':avatar_url(person)}
    for group in data['communication_groups']:
        key=('team:'+str(group.team_id)) if group.is_default else ('group:'+str(group.pk))
        groups[key]={'key':key,'title':group.name,'avatar_url':group_avatar_url(group)}
    for row in data['communication_recent'][:100]:
        key=row['key']
        if key in groups:item=groups[key]
        elif key in contacts:item=contacts[key]
        elif key.startswith('person:') and row.get('person') and permitted_peer(request.user,row['person']):
            item={'key':key,'title':row['title'],'avatar_url':avatar_url(row['person'])}
            contacts[key]=item
        else:continue
        recent.append(item)
    contact_list=sorted(contacts.values(),key=lambda item:item['title'].casefold())
    group_list=sorted(groups.values(),key=lambda item:item['title'].casefold())
    return JsonResponse({'recent':recent,'contacts':contact_list,'groups':group_list,'all':contact_list+group_list})
