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
