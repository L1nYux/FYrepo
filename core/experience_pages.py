"""Authorized full-page chat settings and contact details."""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from .app_experience import channel_access, account_api
from .models import ConversationPreference, GroupMember
from .identity import nickname
from .avatars import avatar_url


@login_required
@never_cache
@require_GET
def page(request):
    view = request.GET.get('view', 'chat')
    if view == 'stickers':
        key = request.GET.get('channel', '')
        target = channel_access(request, key) if key else None
        return_url = '/messages/social/'
        if target and key.startswith('person:'):
            return_url = reverse('personal_chat', args=[target.pk])
        elif target and key.startswith('group:'):
            return_url = reverse('group_chat', args=[target.pk])
        elif target and key.startswith('team:'):
            from .communication import default_group
            return_url = reverse('group_chat', args=[default_group(target).pk])
        return render(request, 'core/stickers.html', {'return_url': return_url})
    if view in ('create-group', 'add-friend', 'my-qr', 'scan', 'existing-groups'):
        return contact_workflow(request, view)
    if view not in ('chat', 'profile', 'settings', 'edit', 'background', 'history', 'group', 'notifications', 'group-avatar'):
        raise Http404
    key = request.GET.get('channel', '')
    target = channel_access(request, key)
    if view == 'profile':
        from .social import member
        raw = request.GET.get('member', '')
        if not raw.isascii() or not raw.isdigit() or len(raw) > 18:
            raise Http404
        member(request, int(raw))  # Apply the same contact visibility policy.
        target = get_object_or_404(User, pk=raw)
        key = 'person:' + str(target.pk)
    elif not target:
        raise PermissionDenied('会话不可用。')
    if view in ('edit', 'settings') and not key.startswith('person:'):
        raise Http404
    if view in ('group', 'group-avatar') and key.startswith('person:'):raise Http404
    pref = ConversationPreference.objects.filter(user=request.user, channel=key).first()
    context = {'page_view': view, 'page_channel': key, 'saved': pref,
               'page_title': {'chat':'聊天信息','profile':'联系人资料','settings':'联系人设置','edit':'设置备注','background':'聊天背景','history':'查找聊天记录','group':'群管理','notifications':'消息提醒','group-avatar':'群头像'}[view],
               'return_url': '/messages/social/', 'members': []}
    if key.startswith('person:'):
        context.update(member_id=target.pk, person=target, return_url=reverse('personal_chat', args=[target.pk]))
        context['members'] = [{'id':target.pk, 'name':nickname(target), 'avatar':avatar_url(target)}]
        context['history_url'] = reverse('personal_thread_history', args=[target.pk])
        if view=='settings':
            from .social import member
            import json
            context['member_manage_url']=json.loads(member(request,target.pk).content).get('manage_url','')
    else:
        from .communication import default_group
        from .chat_media import group_avatar_url
        group = default_group(target) if key.startswith('team:') else target
        context.update(group=group, group_avatar=group_avatar_url(group), return_url=reverse('group_chat', args=[group.pk]),
                       history_url=reverse('group_thread_history', args=[group.pk]))
        context['members'] = [{'id':m.user_id, 'name':nickname(m.user), 'avatar':avatar_url(m.user)} for m in GroupMember.objects.filter(group=group, active=True).select_related('user').order_by('pk')[:200]]
        context['can_manage_avatar'] = group.owner_id == request.user.pk or GroupMember.objects.filter(group=group, user=request.user, active=True, admin=True).exists()
        if view == 'group-avatar' and not context['can_manage_avatar']:
            raise PermissionDenied('只有群主或管理员可以修改群头像。')
        if key.startswith('team:'):
            context['team_space'] = target.workspace.pk
            context['history_url'] = reverse('messages_history')+'?room=developers&space='+str(target.workspace.pk)
        context['manage_url'] = reverse('group_manage', args=[group.pk])
        from .personal_messages import group_details
        context.update(group_details(request,group))
    return render(request, 'core/experience_page.html', context)


def contact_workflow(request, view):
    """Account workflows do not require a team or a conversation."""
    from .personal_messages import friends
    from .identity import account_id
    if view == 'my-qr' and request.GET.get('image') == '1':
        import io, qrcode, qrcode.image.svg
        from urllib.parse import urlencode
        from django.http import HttpResponse
        address = request.build_absolute_uri('/app/pages/?'+urlencode({'view':'add-friend','q':account_id(request.user)}))
        output = io.BytesIO()
        qrcode.make(address, image_factory=qrcode.image.svg.SvgPathImage, border=3).save(output)
        return HttpResponse(output.getvalue(), content_type='image/svg+xml')
    context = {'workflow': view, 'page_title': {'create-group':'发起群聊','add-friend':'添加朋友','my-qr':'我的二维码','scan':'扫一扫','existing-groups':'选择已有的群聊'}[view],
               'own_account':account_id(request.user), 'own_avatar':avatar_url(request.user),
               'search_account':request.GET.get('q','')[:150], 'return_url':'/messages/social/'}
    if view == 'create-group':
        from .app_experience import contact_name
        peers = friends(request.user).select_related('member_profile').order_by('username')
        context['group_contacts'] = [{'id':p.pk,'name':contact_name(request.user,p),'account':account_id(p),'avatar':avatar_url(p)} for p in peers]
        context['selected_peer'] = request.GET.get('create_with','')
    elif view == 'existing-groups':
        from .communication import groups_for
        context['existing_groups'] = groups_for(request.user).order_by('name','pk')
        context['return_url'] = '/app/pages/?view=create-group'
    return render(request, 'core/contact_workflow.html', context)


@account_api
@require_POST
def group_image(request, pk):
    from .personal_messages import permitted_group
    from .chat_media import clean_image, group_avatar_url
    group = permitted_group(request, pk)
    if group.owner_id != request.user.pk and not GroupMember.objects.filter(group=group, user=request.user, active=True, admin=True).exists():
        return JsonResponse({'error':'只有群主或管理员可以修改群头像。'}, status=403)
    if request.POST.get('action') == 'reset':
        group.avatar = ''
    else:
        try:
            image = clean_image(request.FILES.get('image'), square=True)
        except ValidationError as error:
            return JsonResponse({'error':error.messages[0]}, status=400)
        group.avatar.save('avatar.webp', image, save=False)
    group.save(update_fields=['avatar'])
    return JsonResponse({'ok':True, 'avatar_url':group_avatar_url(group)})
