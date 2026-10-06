"""Personal friendships and private team groups; team colleagues are not automatic friends."""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.db.models import Q, F
from django.http import JsonResponse, FileResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_GET
from django.middleware.csrf import get_token
from django.utils import timezone
from datetime import timedelta
import uuid
from .avatars import avatar_url
from .models import (TeamMembership, FriendRequest, Friendship, PersonalMessage, ChatGroup, GroupMember, GroupMessage)
from .tenancy import team_users
from . import permissions as perms
from .pagination import page
from .teams import valid_id
from .identity import nickname, account_id, login_user


def friends(user):
    relations=Friendship.objects.filter(Q(first=user)|Q(second=user))
    ids=set(relations.values_list('first_id',flat=True))|set(relations.values_list('second_id',flat=True))
    return User.objects.filter(pk__in=ids-{user.pk},is_active=True)


def permitted_peer(user,peer):
    if not user.is_active or not peer.is_active:return False
    pair=sorted([user.pk,peer.pk])
    if pair[0]==pair[1]: return False
    if Friendship.objects.filter(first_id=pair[0],second_id=pair[1]).exists(): return True
    teams=TeamMembership.objects.filter(user=user,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).values('team_id')
    return TeamMembership.objects.filter(user=peer,team_id__in=teams,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).exists()


@login_required
@never_cache
def index(request):
    colleague_ids=TeamMembership.objects.filter(user=request.user,active=True,deleted_at__isnull=True,team__active=True,role__in=['owner','admin','member']).values('team_id')
    colleagues=User.objects.filter(pk__in=TeamMembership.objects.filter(team_id__in=colleague_ids,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).values('user_id'),is_active=True).exclude(pk=request.user.pk).order_by('username')
    from .communication import groups_for
    groups=groups_for(request.user).order_by('-created_at','-pk')
    return render(request,'core/social_inbox.html',{'friends':page(request,friends(request.user).order_by('username'),key='friends_page'),
        'colleagues':page(request,colleagues,key='colleagues_page'),'chat_groups':page(request,groups,key='groups_page'),
        'friend_requests':page(request,FriendRequest.objects.filter(recipient=request.user,state='pending').select_related('sender').order_by('-pk'),key='requests_page'),
        'selectable_members':team_users(member_only=True).exclude(pk=request.user.pk)[:1000] if perms.is_team_member(request) else []})


@login_required
@never_cache
@require_GET
def search_friend(request):
    name=request.GET.get('q','').strip()
    if not name or len(name)>150:return JsonResponse({'error':'请输入完整账号。'},status=400)
    peer=login_user(name)
    if peer and (not peer.is_active or peer.pk==request.user.pk):peer=None
    if not peer:return JsonResponse({'error':'没有找到该账号。'},status=404)
    from .models import PublicProfile
    profile=PublicProfile.objects.filter(user=peer,is_public=True).first()
    state='friends' if friends(request.user).filter(pk=peer.pk).exists() else 'sent' if FriendRequest.objects.filter(sender=request.user,recipient=peer,state='pending').exists() else 'none'
    return JsonResponse({'id':peer.pk,'username':account_id(peer),'display_name':nickname(peer),
        'friend_state':state,'friend_url':reverse('request_friend'),'csrf_token':get_token(request)})


@login_required
@require_POST
def request_friend(request):
    name=request.POST.get('username','').strip()[:150]
    peer=login_user(name)
    if peer and (not peer.is_active or peer.pk==request.user.pk):peer=None
    if not peer or friends(request.user).filter(pk=peer.pk).exists():
        messages.info(request,'账户不可申请或已是好友。');return JsonResponse({'error':'账户不可申请或已是好友。'},status=400) if request.headers.get('Accept')=='application/json' else redirect('messages_social')
    if FriendRequest.objects.filter(sender=request.user,created_at__gte=timezone.now()-timedelta(days=1)).count()>=20:
        messages.error(request,'今日好友申请已达上限。');return JsonResponse({'error':'今日好友申请已达上限。'},status=429) if request.headers.get('Accept')=='application/json' else redirect('messages_social')
    try:
        FriendRequest.objects.get_or_create(sender=request.user,recipient=peer,state='pending',defaults={'note':request.POST.get('note','').strip()[:200]})
    except IntegrityError: pass
    messages.success(request,'好友申请已发送，等待对方确认。')
    return JsonResponse({'state':'sent','message':'好友申请已发送，等待对方确认。'}) if request.headers.get('Accept')=='application/json' else redirect('messages_social')


@login_required
@require_POST
def friend_action(request,pk):
    action=request.POST.get('action')
    if action not in ('accept','reject'):raise PermissionDenied
    with transaction.atomic():
        FriendRequest.objects.filter(pk=pk,recipient=request.user,state='pending').update(state=F('state'))
        item=get_object_or_404(FriendRequest.objects.select_for_update(),pk=pk,recipient=request.user,state='pending')
        item.state='accepted' if action=='accept' else 'rejected';item.save(update_fields=['state'])
        if action=='accept':
            first,second=sorted([item.sender_id,item.recipient_id])
            Friendship.objects.get_or_create(first_id=first,second_id=second)
    return JsonResponse({'state':'friends' if action=='accept' else 'none'}) if request.headers.get('Accept')=='application/json' else redirect(reverse('messages_social')+'?tab=requests')


def body(request):
    text=request.POST.get('body','').strip()
    if (not text and not request.POST.get('resend_message') and not request.FILES.getlist('attachments') and not request.POST.get('sticker_id') and not request.POST.getlist('references')) or len(text)>2000:raise ValidationError('请输入 1–2000 字的消息。')
    return text


def serialize_message(item,request,group=None,peer=None):
    from .personal_history import references_for, legacy_data
    author=getattr(item,'sender',getattr(item,'author',None))
    source=getattr(item,'legacy_message',None)
    withdrawn=bool(item.withdrawn_at or source and source.withdrawn_at)
    value={'id':item.pk,'author':nickname(author),'author_id':author.pk,'avatar_url':avatar_url(author),
        'mine':author.pk==request.user.pk,'body':item.body if not withdrawn else '消息已撤回','withdrawn':withdrawn,
        'quote':item.quote,'action_url':reverse('group_message_action' if group else 'personal_message_action',args=[group.pk if group else peer.pk,item.pk]),
        'files':[{'name':f.original_name,'url':reverse('personal_message_file',args=[f.pk])} for f in item.uploads.all()] if not withdrawn else [],
        'at':timezone.localtime(item.created_at).strftime('%m-%d %H:%M'),'references':[],'sticker':None,'gift':None}
    if not withdrawn:
        value['references']=references_for(item.references,request.user)
        if item.sticker_id:value['sticker']={'url':reverse('sticker_file',args=[item.sticker_id]),'name':item.sticker.name}
        if source:
            legacy=legacy_data(item,request.user);value['files']+=legacy.pop('files');value.update(legacy)
    return value


def stream(request, rows, create, title, action_url, group=None, peer=None):
    from .models import PersonalThreadRead
    key='group:'+str(group.pk) if group else 'person:'+str(peer.pk)
    state,_=PersonalThreadRead.objects.get_or_create(user=request.user,channel=key)
    rows=rows.filter(pk__gt=state.cleared_through)
    if state.removed:state.removed=False;state.save(update_fields=['removed'])
    def mark_read(cursor):
        if not cursor:return
        state,_=PersonalThreadRead.objects.get_or_create(user=request.user,channel='group:'+str(group.pk) if group else 'person:'+str(peer.pk))
        PersonalThreadRead.objects.filter(pk=state.pk,last_message_id__lt=cursor).update(last_message_id=cursor)
    rows=rows.exclude(hidden_by=request.user)
    if not group:rows=rows.exclude(legacy_message__hidden_by=request.user)
    json_response=request.headers.get('Accept')=='application/json'
    if json_response:
        try: after=int(request.GET.get('after','0'))
        except ValueError: return JsonResponse({'error':'消息游标无效。'},status=400)
        if not 0<=after<=9223372036854775807:
            return JsonResponse({'error':'消息游标无效。'},status=400)
    if request.method=='POST':
        try:
            from .models import validate_private_files, MessageUpload
            from pathlib import Path
            uploads=validate_private_files(request.FILES.getlist('attachments'))
            sticker=None
            if request.POST.get('sticker_id'):
                from .social import accessible
                raw=request.POST['sticker_id']
                if not valid_id(raw):raise ValidationError('表情编号无效。')
                sticker=get_object_or_404(accessible(request.user),pk=raw)
            from . import chat_references
            from .tenancy import required_workspace_id
            references=[]
            tokens=request.POST.getlist('references')
            if len(tokens)==1 and tokens[0].startswith('['):
                import json
                try:tokens=json.loads(tokens[0])
                except (ValueError,TypeError):raise ValidationError('引用内容无效。')
                if not isinstance(tokens,list) or any(not isinstance(token,str) for token in tokens):raise ValidationError('引用内容无效。')
            if len(tokens)>10:raise ValidationError('最多引用十项内容。')
            for token in tokens:
                kind,separator,identifier=token.partition(':')
                if kind not in chat_references.MODELS or not separator or not valid_id(identifier):raise ValidationError('引用内容无效。')
                if not chat_references.available(request,kind).filter(pk=identifier).exists():raise ValidationError('引用内容已不可用。')
                references.append({'workspace':required_workspace_id(),'kind':kind,'pk':int(identifier)})
            source=None;retained=[]
            raw=request.POST.get('resend_message','')
            if raw:
                if not valid_id(raw):raise ValidationError('重新编辑的消息无效。')
                source=get_object_or_404(rows,pk=raw)
                author=getattr(source,'sender_id',getattr(source,'author_id',None))
                legacy=getattr(source,'legacy_message',None)
                if author!=request.user.pk or not (source.withdrawn_at or legacy and legacy.withdrawn_at):raise PermissionDenied
                retained=list(source.uploads.all())
                if legacy:retained+=list(legacy.attachments.all())
                from .models import MAX_FILES_PER_UPLOAD, MAX_UPLOAD_BYTES
                if len(retained)+len(uploads)>MAX_FILES_PER_UPLOAD or sum(f.file.size for f in retained)+sum(f.size for f in uploads)>MAX_UPLOAD_BYTES:raise ValidationError('重新编辑时携带的附件超出数量或大小限制。')
            if not request.POST.get('body','').strip() and not retained and not uploads and not sticker and not references:raise ValidationError('请输入消息内容。')
            quoted=rows.filter(pk=request.POST.get('quoted_message')).first() if str(request.POST.get('quoted_message','')).isdigit() else None
            with transaction.atomic():
                item=create(body(request))
                item.sticker=sticker;item.references=references;item.save(update_fields=['sticker','references'])
                if quoted:
                    item.quote={'author':nickname(getattr(quoted,'sender',getattr(quoted,'author',None))),'body':'消息已撤回' if quoted.withdrawn_at or getattr(quoted,'legacy_message',None) and quoted.legacy_message.withdrawn_at else quoted.body[:500]}
                    item.save(update_fields=['quote'])
                for original in retained:
                    MessageUpload.objects.create(personal=item if not group else None,message=item if group else None,file=original.file.name,original_name=original.original_name)
                for upload in uploads:
                    original=Path(upload.name).name[:255]
                    upload.name=uuid.uuid4().hex+Path(original).suffix.lower()
                    MessageUpload.objects.create(personal=item if not group else None,message=item if group else None,file=upload,original_name=original)

        except ValidationError as error:return JsonResponse({'error':' '.join(error.messages)},status=400)
        if not json_response:return redirect(action_url)
    if json_response:
        changed=Q(pk__gt=after)|Q(withdrawn_at__gte=timezone.now()-timedelta(minutes=3))
        if not group:changed|=Q(legacy_message__withdrawn_at__gte=timezone.now()-timedelta(minutes=3))|Q(legacy_message__point_gift__isnull=False)
        values=[serialize_message(item,request,group,peer) for item in rows.filter(changed).order_by('pk').prefetch_related('uploads')[:100]]

        mark_read(values[-1]['id'] if values else 0)
        known=[int(v) for v in request.GET.get('known','').split(',')[:200] if valid_id(v)]
        visible=set(rows.filter(pk__in=known).values_list('pk',flat=True))
        return JsonResponse({'messages':values,'removed':[pk for pk in known if pk not in visible]})
    history=list(rows.prefetch_related('uploads').order_by('-created_at','-pk')[:100])[::-1]
    for item in history:
        item.chat_author=getattr(item,'sender',getattr(item,'author',None))
        item.mine=item.chat_author.pk==request.user.pk
        item.action_url=reverse('group_message_action' if group else 'personal_message_action',args=[group.pk if group else peer.pk,item.pk])
        item.display=serialize_message(item,request,group,peer)
    mark_read(max((item.pk for item in history),default=0))
    return render(request,'core/personal_thread.html',{'title':title,'thread_url':action_url,
        'chat_rows':history,'peer':peer,'group':group, 'can_send':not peer or permitted_peer(request.user,peer),'channel_key':'dm:'+str(peer.pk) if peer else '',
        'thread_state':state,'thread_settings_url':reverse('group_thread_settings' if group else 'personal_thread_settings',args=[group.pk if group else peer.pk]),
        'thread_history_url':reverse('group_thread_history' if group else 'personal_thread_history',args=[group.pk if group else peer.pk]),
        'can_send_gift':bool(peer and request.team and team_users(member_only=True).filter(pk=peer.pk).exists()),
        **group_details(request,group),'can_manage_group':bool(group and (group.owner_id==request.user.pk or GroupMember.objects.filter(group=group,user=request.user,active=True,admin=True).exists()))})


@login_required
@never_cache
def personal(request,pk):
    peer=get_object_or_404(User,pk=pk)
    rows=PersonalMessage.objects.filter(Q(sender=request.user,recipient=peer)|Q(sender=peer,recipient=request.user)).select_related('sender')
    if not permitted_peer(request.user,peer):
        if not rows.filter(relation_verified=True).exists():raise Http404
        if request.method=='POST':raise PermissionDenied('没有共同团队，请先添加好友。')
    from .models import ChatReadState
    states=ChatReadState.all_objects.filter(user=request.user,channel='dm:'+str(pk))
    for state in states.filter(cleared_through__gt=0):
        rows=rows.exclude(legacy_message__workspace_id=state.workspace_id,legacy_message_id__lte=state.cleared_through)
    states.filter(removed=True).update(removed=False)
    return stream(request,rows,lambda text:PersonalMessage.objects.create(sender=request.user,recipient=peer,body=text,relation_verified=True),nickname(peer),reverse('personal_chat',args=[pk]),peer=peer)


def permitted_group(request,pk):
    group=get_object_or_404(ChatGroup.objects.select_related('team'),pk=pk,active=True)
    if not GroupMember.objects.filter(group=group,user=request.user,active=True).exists():
        raise PermissionDenied('无权访问这个群。')
    if group.team_id and (not group.team.active or not TeamMembership.objects.filter(team=group.team,user=request.user,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).exists()):
        raise PermissionDenied('团队群的成员资格已失效。')
    return group


def group_details(request,group):
    if not group:return {}
    members=GroupMember.objects.filter(group=group,active=True).select_related('user')
    available=(friends(request.user) if not group.team_id else User.objects.filter(pk__in=TeamMembership.objects.filter(team=group.team,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).values('user_id'),is_active=True)).exclude(pk__in=members.values('user_id'))
    return {'group_members':members,'available_members':available,'group_self':members.get(user=request.user), 'can_invite_group':not group.team_id or group.owner_id==request.user.pk or members.filter(user=request.user,admin=True).exists()}


@login_required
@never_cache
def group_chat(request,pk):
    group=permitted_group(request,pk)
    if group.is_default:
        from .tenancy import scope
        from .models import Workspace
        from .messages import hub
        request.team=group.team;request.workspace=Workspace.objects.get_or_create(team=group.team,defaults={'kind':'team'})[0]
        with scope(request.workspace,http=True):
            request.role=perms.account_role(request.user)
            return hub(request)
    rows=GroupMessage.objects.filter(group=group).select_related('author')
    return stream(request,rows,lambda text:GroupMessage.objects.create(group=group,author=request.user,body=text),group.name,reverse('group_chat',args=[pk]),group)


@login_required
@require_POST
def create_group(request):
    kind=request.POST.get('kind','team')
    if kind not in ('team','personal'):raise PermissionDenied
    if kind=='team' and (not request.team or not perms.is_team_member(request)):raise PermissionDenied
    name=request.POST.get('name','').strip()
    ids=request.POST.getlist('members')
    if not name or len(name)>80 or len(ids)>1000 or any(not value.isascii() or not value.isdigit() or len(value)>18 for value in ids):
        messages.error(request,'群名称或成员无效。');return redirect('messages_social')
    selected=set(map(int,ids))|{request.user.pk}
    members=(team_users(member_only=True) if kind=='team' else User.objects.filter(Q(pk__in=friends(request.user).values('pk'))|Q(pk=request.user.pk),is_active=True)).filter(pk__in=selected)
    if members.count()!=len(selected):raise PermissionDenied('只能选择当前团队的在用成员。')
    with transaction.atomic():
        group=ChatGroup.objects.create(team=request.team if kind=='team' else None,owner=request.user,name=name)
        GroupMember.objects.bulk_create([GroupMember(group=group,user=user,admin=user.pk==request.user.pk) for user in members])
    return redirect('group_chat',pk=group.pk)


@login_required
def manage_group(request,pk):
    group=permitted_group(request,pk)
    manager=group.owner_id==request.user.pk or GroupMember.objects.filter(group=group,user=request.user,active=True,admin=True).exists()
    if request.method=='POST':
        action=request.POST.get('action')
        with transaction.atomic():
            group=ChatGroup.objects.select_for_update().get(pk=group.pk)
            if action=='settings':
                own=GroupMember.objects.get(group=group,user=request.user,active=True)
                own.remark=request.POST.get('remark','').strip()[:80];own.nickname=request.POST.get('nickname','').strip()[:80]
                own.muted=request.POST.get('muted')=='on';own.save()
            elif action=='rename':
                if not manager:raise PermissionDenied
                name=request.POST.get('name','').strip()
                if not name or len(name)>80:raise PermissionDenied('群名称须为 1–80 字。')
                group.name=name;group.announcement=request.POST.get('announcement','').strip()[:4000];group.save(update_fields=['name','announcement'])
            elif action=='disband':
                if group.owner_id!=request.user.pk or group.is_default:raise PermissionDenied
                group.active=False;group.save(update_fields=['active']);GroupMember.objects.filter(group=group).update(active=False)
                return redirect('messages_social')
            elif action=='leave':
                if group.is_default:raise PermissionDenied('请通过团队管理退出团队。')
                if group.owner_id==request.user.pk:raise PermissionDenied('请先交接群主。')
                GroupMember.objects.filter(group=group,user=request.user).update(active=False)
                return redirect('messages_social')
            else:
                if not valid_id(request.POST.get('user','')):raise PermissionDenied
                user=get_object_or_404(User,pk=request.POST.get('user'),is_active=True)
                if action=='add':
                    if group.team_id:
                        if not manager or not TeamMembership.objects.filter(team=group.team,user=user,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).exists():raise PermissionDenied
                    elif not friends(request.user).filter(pk=user.pk).exists():raise PermissionDenied('只能邀请自己的好友。')
                    if group.owner_id!=request.user.pk and GroupMember.objects.filter(group=group,user=user,active=True,admin=True).exists():raise PermissionDenied
                    member,created=GroupMember.objects.get_or_create(group=group,user=user,defaults={'active':True})
                    if not created and not member.active:GroupMember.objects.filter(pk=member.pk).update(active=True,admin=False)
                elif action=='transfer':
                    if group.is_default:raise PermissionDenied('请通过团队管理交接所有权。')
                    if group.owner_id!=request.user.pk:raise PermissionDenied
                    target=get_object_or_404(GroupMember,group=group,user=user,active=True)
                    group.owner=user;group.save(update_fields=['owner']);target.admin=True;target.save(update_fields=['admin'])
                elif action in ('remove','admin','member'):
                    if group.is_default and action=='remove':raise PermissionDenied('默认团队群随团队成员关系同步。')
                    if not manager or user.pk==group.owner_id:raise PermissionDenied
                    if action!='remove' and group.owner_id!=request.user.pk:raise PermissionDenied
                    target=get_object_or_404(GroupMember,group=group,user=user,active=True)
                    if target.admin and group.owner_id!=request.user.pk:raise PermissionDenied
                    GroupMember.objects.filter(pk=target.pk).update(active=action!='remove',admin=action=='admin')
                else:raise PermissionDenied
        if request.headers.get('Accept')=='application/json':return JsonResponse({'ok':True})
        return redirect(reverse('group_chat',args=[pk])+'?details=1')
    return group_chat(request,pk)


def message_action(request,rows,message_pk):
    item=get_object_or_404(rows.exclude(hidden_by=request.user),pk=message_pk)
    author=getattr(item,'sender_id',getattr(item,'author_id',None))
    if request.POST.get('action')=='delete':
        item.hidden_by.add(request.user);return JsonResponse({'ok':True,'deleted':item.pk})
    if request.POST.get('action')=='draft':
        source=getattr(item,'legacy_message',None)
        if author!=request.user.pk or not (item.withdrawn_at or source and source.withdrawn_at):raise PermissionDenied
        files=[f.original_name for f in item.uploads.all()]
        if source:files += [f.original_name for f in source.attachments.all()]
        return JsonResponse({'draft':{'body':item.body,'id':item.pk,'attachments':files}})
    if author!=request.user.pk or request.POST.get('action')!='withdraw' or timezone.now()-item.created_at>timedelta(minutes=2):raise PermissionDenied('只能撤回两分钟内本人发送的消息。')
    if getattr(item,'legacy_message_id',None):
        from aihub.models import PointGift
        if item.legacy_message.kind=='notice' or PointGift.all_objects.filter(message_id=item.legacy_message_id).exists():raise PermissionDenied('系统提示和积分消息不能撤回。')
        from .models import ChatMessage
        ChatMessage.all_objects.filter(pk=item.legacy_message_id).update(withdrawn_at=timezone.now())
    rows.filter(pk=item.pk).update(withdrawn_at=timezone.now())
    return JsonResponse({'ok':True})


@login_required
@require_POST
def personal_action(request,pk,message_pk):
    rows,group,peer,state=thread_rows(request,pk,False)
    return message_action(request,rows,message_pk)


@login_required
@require_POST
def group_action(request,pk,message_pk):
    rows,group,peer,state=thread_rows(request,pk,True)
    return message_action(request,rows,message_pk)


@login_required
def upload_file(request,pk):
    from .models import MessageUpload
    item=get_object_or_404(MessageUpload.objects.select_related('personal','message'),pk=pk)
    if item.personal_id:
        peer=item.personal.recipient_id if item.personal.sender_id==request.user.pk else item.personal.sender_id
        rows,_,_,_=thread_rows(request,peer,False)
        if not rows.filter(pk=item.personal_id).exists():raise PermissionDenied
        if request.user.pk not in (item.personal.sender_id,item.personal.recipient_id) or item.personal.withdrawn_at:raise PermissionDenied
    else:
        rows,_,_,_=thread_rows(request,item.message.group_id,True)
        if not rows.filter(pk=item.message_id).exists():raise PermissionDenied
        if item.message.withdrawn_at:raise PermissionDenied
    response=FileResponse(item.file.open('rb'),as_attachment=True,filename=item.original_name)
    response['X-Content-Type-Options']='nosniff';response['Cache-Control']='private, no-store'
    return response


@login_required
def legacy_file(request,pk):
    from .models import Attachment
    item=get_object_or_404(Attachment.all_objects.select_related('chat_message'),pk=pk,chat_message__room='private')
    message=item.chat_message
    peer=message.recipient_id if message.author_id==request.user.pk else message.author_id
    rows,_,_,_=thread_rows(request,peer,False)
    if not rows.filter(legacy_message=message).exists():raise PermissionDenied
    if request.user.pk not in (message.author_id,message.recipient_id) or message.withdrawn_at or message.hidden_by.filter(pk=request.user.pk).exists():raise PermissionDenied
    response=FileResponse(item.file.open('rb'),as_attachment=True,filename=item.original_name)
    response['X-Content-Type-Options']='nosniff';response['Cache-Control']='private, no-store'
    return response


def thread_rows(request,pk,is_group):
    from .models import PersonalThreadRead
    if is_group:
        group=permitted_group(request,pk)
        if group.is_default:raise PermissionDenied('默认团队群使用团队聊天记录。')
        rows=GroupMessage.objects.filter(group=group);peer=None;key='group:'+str(pk)
    else:
        group=None;peer=get_object_or_404(User,pk=pk);key='person:'+str(pk)
        rows=PersonalMessage.objects.filter(Q(sender=request.user,recipient=peer)|Q(sender=peer,recipient=request.user))
        if not permitted_peer(request.user,peer) and not rows.filter(relation_verified=True).exists():raise Http404
        from .models import ChatReadState
        for legacy in ChatReadState.all_objects.filter(user=request.user,channel='dm:'+str(pk),cleared_through__gt=0):
            rows=rows.exclude(legacy_message__workspace_id=legacy.workspace_id,legacy_message_id__lte=legacy.cleared_through)
        rows=rows.exclude(legacy_message__hidden_by=request.user)
    state,_=PersonalThreadRead.objects.get_or_create(user=request.user,channel=key)
    return rows.exclude(hidden_by=request.user).filter(pk__gt=state.cleared_through),group,peer,state


@login_required
@require_POST
def thread_settings(request,pk,is_group=False):
    rows,group,peer,state=thread_rows(request,pk,is_group)
    action=request.POST.get('action')
    if action in ('clear','remove') and request.POST.get('confirm')!='yes':raise PermissionDenied('请确认操作。')
    if action in ('mute','unmute'):
        state.muted=action=='mute'
        if group:GroupMember.objects.filter(group=group,user=request.user).update(muted=state.muted)
    elif action=='clear':
        state.cleared_through=rows.order_by('-pk').values_list('pk',flat=True).first() or state.cleared_through
        state.last_message_id=max(state.last_message_id,state.cleared_through)
    elif action=='remove':
        state.removed=True;state.removed_through=rows.order_by('-pk').values_list('pk',flat=True).first() or state.removed_through
    else:raise PermissionDenied
    state.save();return JsonResponse({'ok':True,'removed':state.removed,'muted':state.muted})


@login_required
@require_GET
def thread_history(request,pk,is_group=False):
    rows,group,peer,state=thread_rows(request,pk,is_group)
    query=request.GET.get('q','').strip()[:150]
    if query:rows=rows.filter(body__icontains=query,withdrawn_at__isnull=True)
    before=request.GET.get('before','')
    if before:
        if not valid_id(before):return JsonResponse({'error':'记录游标无效。'},status=400)
        anchor=get_object_or_404(rows,pk=before)
        rows=rows.filter(Q(created_at__lt=anchor.created_at)|Q(created_at=anchor.created_at,pk__lt=anchor.pk))
    history=list(rows.prefetch_related('uploads').order_by('-created_at','-pk')[:100])
    return JsonResponse({'messages':[serialize_message(item,request,group,peer) for item in history],
        'next_before':history[-1].pk if len(history)==100 else None})
