"""Small team messaging, with participant-only private conversations."""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Prefetch, Count, Max, F
from django import forms
from django.views.decorators.cache import never_cache
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.views.decorators.http import require_POST, require_http_methods

from . import permissions as perms
from .forms import ChatMessageForm
from .models import Attachment, ChatMessage, ChatReadState, ChatReference, UserPresence, attach_files
from . import chat_references
from .avatars import avatar_url


def visible_messages(user, rows):
    rows = rows.exclude(hidden_by=user)
    excluded = Q(pk__in=[])
    for state in ChatReadState.objects.filter(user=user, cleared_through__gt=0):
        if state.channel in ('developers', 'public'):
            excluded |= Q(room=state.channel, pk__lte=state.cleared_through)
        elif state.channel.startswith('dm:') and state.channel[3:].isdigit():
            peer = int(state.channel[3:])
            excluded |= Q(room='private', pk__lte=state.cleared_through) & (
                Q(author=user, recipient_id=peer) | Q(author_id=peer, recipient=user))
    return rows.exclude(excluded)


def conversation_states(user):
    states = list(ChatReadState.objects.filter(user=user))
    for state in states:
        if not state.removed: continue
        if state.channel in ('developers', 'public'):
            rows = ChatMessage.objects.filter(room=state.channel)
        elif state.channel.startswith('dm:') and state.channel[3:].isdigit():
            peer = int(state.channel[3:])
            rows = ChatMessage.objects.filter(room='private').filter(Q(author=user,recipient_id=peer)|Q(author_id=peer,recipient=user))
        else: continue
        if visible_messages(user, rows).filter(pk__gt=state.removed_through, withdrawn_at__isnull=True).exists():
            ChatReadState.objects.filter(pk=state.pk, removed_through=state.removed_through).update(removed=False)
            state.removed = False
    return {state.channel: state for state in states}


def unread_payload(user, counts):
    states = conversation_states(user)
    muted = [key for key, state in states.items() if state.muted]
    return {'total': sum(count for key, count in counts.items() if key not in muted),
            'channels': counts, 'muted_channels': muted,
            'hidden_channels': [key for key, state in states.items() if state.removed]}


def reference_prefetch():
    return Prefetch('references', queryset=ChatReference.objects.select_related(
        'task__project', 'task__parent', 'experiment', 'entry', 'claim', 'announcement'))


def message_data(rows, user):
    from aihub.models import PointGiftReceipt
    return rows.select_related('author__member_profile', 'point_gift', 'system_gift__sender', 'sticker', 'quoted_message__author').prefetch_related(
        'attachments', reference_prefetch(), Prefetch('point_gift__receipts',
            queryset=PointGiftReceipt.objects.filter(user=user), to_attr='viewer_receipts'))


def require_member(request):
    if not perms.is_team_member(request):
        raise PermissionDenied('消息中心仅供团队成员使用。')


def unread_counts(user, request=None):
    if request is not None and hasattr(request, '_unread_counts'):
        return request._unread_counts
    reads = dict(ChatReadState.objects.filter(user=user).values_list('channel', 'last_message_id'))
    query = (Q(room=ChatMessage.DEVELOPERS, pk__gt=reads.get('developers', 0)) |
             Q(room=ChatMessage.PUBLIC, pk__gt=reads.get('public', 0)))
    private = Q(room=ChatMessage.PRIVATE, recipient=user, author__is_active=True)
    for key, last in reads.items():
        if key.startswith('dm:'):
            private &= ~Q(author_id=int(key[3:]), pk__lte=last)
    rows = visible_messages(user, ChatMessage.objects.filter(query | private, withdrawn_at__isnull=True)).exclude(author=user).order_by().values('room', 'author_id').annotate(count=Count('pk'))
    counts = {}
    for row in rows:
        key = f"dm:{row['author_id']}" if row['room'] == ChatMessage.PRIVATE else row['room']
        counts[key] = counts.get(key, 0) + row['count']
    if request is not None:
        request._unread_counts = counts
    return counts


def channel(request, peer_pk=None):
    require_member(request)
    if peer_pk:
        peer = get_object_or_404(User.objects.select_related('member_profile').filter(
            Q(is_active=True) | Q(member_profile__deleted_at__isnull=False)
        ).exclude(member_profile__tier='normal'), pk=peer_pk)
        if peer.pk == request.user.pk:
            raise PermissionDenied('请选择另一位成员。')
        rows = ChatMessage.objects.filter(room=ChatMessage.PRIVATE).filter(
            Q(author=request.user, recipient=peer) | Q(author=peer, recipient=request.user))
        if not peer.is_active and not rows.exists():
            raise Http404
        return peer, f'dm:{peer.pk}', rows, peer.username
    room = ChatMessage.PUBLIC if request.GET.get('room') == 'public' else ChatMessage.DEVELOPERS
    return None, room, ChatMessage.objects.filter(room=room, recipient__isnull=True), dict(ChatMessage.ROOMS)[room]


def mark_read(user, key, last):
    if last:
        state, _ = ChatReadState.objects.get_or_create(user=user, channel=key)
        ChatReadState.objects.filter(pk=state.pk, last_message_id__lt=last).update(last_message_id=last)


def quote_card(row, user):
    original=row.quoted_message
    if not original: return None
    visible=visible_messages(user, ChatMessage.objects.filter(pk=original.pk)).exists()
    return {'id':original.pk, 'author':original.author.username if visible else '',
            'text':original.body[:160] if visible and not original.withdrawn_at else '原消息已撤回或不可用',
            'available':visible and not original.withdrawn_at}


def serialize(row, viewer):
    user = perms.user_of(viewer)
    from aihub.models import PointGift
    from aihub.gifts import card as gift_card
    try: gift=gift_card(row.point_gift,user)
    except PointGift.DoesNotExist: gift=None
    body=row.body
    if row.kind=='notice' and row.system_gift_id:
        sender=row.system_gift.sender
        actor='你' if row.author_id==user.pk else row.author.username
        owner='你' if sender.pk==user.pk else sender.username
        body=actor+('收取了' if row.system_gift.kind=='transfer' else '领取了')+owner+('的转账' if row.system_gift.kind=='transfer' else '的红包')
    return {'id': row.pk, 'author': row.author.username, 'gift':gift,
            'kind': row.kind, 'author_id': row.author_id, 'quote': quote_card(row, user), 'sticker': {'id': row.sticker_id, 'url': reverse('sticker_file', args=[row.sticker_id]), 'name': row.sticker.name} if row.sticker_id and not row.withdrawn_at else None, 'notice_gift': str(row.system_gift_id) if row.system_gift_id else None, 'initial': row.author.username[:1].upper(), 'avatar_url': avatar_url(row.author), 'at': row.spoken_at,
            'body': '' if row.withdrawn_at else body, 'mine': row.author_id == user.pk,
            'withdrawn': bool(row.withdrawn_at), 'action_url': reverse('message_action', args=[row.pk]),
            'references': [] if row.withdrawn_at else [chat_references.display(ref, viewer) for ref in row.references.all()],
            'attachments': [{'name': file.original_name, 'url': reverse('attachment_download', args=[file.pk])}
                            for file in row.attachments.all()] if not row.withdrawn_at else []}


@login_required
@require_POST
def message_action(request, pk):
    require_member(request)
    rows = ChatMessage.objects.filter(Q(room__in=[ChatMessage.PUBLIC, ChatMessage.DEVELOPERS]) |
        Q(room=ChatMessage.PRIVATE, author=request.user) | Q(room=ChatMessage.PRIVATE, recipient=request.user))
    row = get_object_or_404(message_data(visible_messages(request.user, rows), request.user), pk=pk)
    action = request.POST.get('action')
    if action == 'delete':
        row.hidden_by.add(request.user)
        return JsonResponse({'deleted': row.pk})
    if row.author_id != request.user.pk:
        raise PermissionDenied('只能撤回或重新编辑自己发送的消息。')
    if row.kind == 'notice': raise PermissionDenied('系统提示只能从自己的记录中删除。')
    if action == 'withdraw':
        from aihub.models import PointGift
        if PointGift.objects.filter(message=row).exists():
            return JsonResponse({'error':'积分红包和转账不能撤回。未领取的转账可在详情中退回；红包到期后自动退回未领取部分。'},status=400)
        ChatMessage.objects.filter(pk=pk, withdrawn_at__isnull=True).update(withdrawn_at=timezone.now())
        row.refresh_from_db()
        return JsonResponse({'message': serialize(row, request)})
    if action == 'draft' and row.withdrawn_at:
        references = [chat_references.display(ref, request) for ref in row.references.all()]
        return JsonResponse({'draft': {'id': row.pk, 'body': row.body,
            'references': [ref for ref in references if ref.get('available')],
            'attachments': [file.original_name for file in row.attachments.all()]}})
    return JsonResponse({'error': '消息操作无效。'}, status=400)


@login_required
@never_cache
def hub(request, peer_pk=None):
    peer, key, rows, label = channel(request, peer_pk)
    if peer and not peer.is_active and request.method == 'POST':
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'errors': {'__all__': [{'message': '该账号已删除，只能查看历史消息。'}]}}, status=403)
        raise PermissionDenied('该账号已删除，只能查看历史消息。')
    rows = visible_messages(request.user, rows)
    ChatReadState.objects.filter(user=request.user, channel=key, removed=True).update(removed=False)
    source = None
    if request.method == 'POST' and request.POST.get('resend_message'):
        try:
            source_id = int(request.POST['resend_message'])
            if not 0 < source_id <= 9223372036854775807: raise ValueError
        except (TypeError, ValueError):
            raise PermissionDenied('重新编辑的消息无效。')
        source = get_object_or_404(rows, pk=source_id, author=request.user, withdrawn_at__isnull=False)
    old_files = list(source.attachments.all()) if source else []
    sticker=None; quoted=None
    if request.method=='POST':
        for field in ('sticker_id','quoted_message'):
            raw=request.POST.get(field,'')
            if raw and (not raw.isascii() or not raw.isdigit() or len(raw)>18): return JsonResponse({'error':'消息参数无效。'},status=400)
        if request.POST.get('sticker_id'):
            from .social import accessible
            sticker=get_object_or_404(accessible(request.user),pk=int(request.POST['sticker_id']))
        if request.POST.get('quoted_message'):
            quoted=get_object_or_404(visible_messages(request.user,rows),pk=int(request.POST['quoted_message']),withdrawn_at__isnull=True,kind__in=['text','sticker'])
    form = ChatMessageForm(request.POST or None, request.FILES or None, allow_references=True, existing_attachments=bool(old_files or sticker))
    selected = []
    targets = []
    valid = form.is_valid() if request.method == 'POST' else False
    if request.method == 'POST':
        for token in form.cleaned_data.get('references', []):
            kind, pk = token.split(':')
            obj = chat_references.available(request, kind).filter(pk=int(pk)).first()
            if obj is None:
                form.add_error('references', '引用内容已不可用或你无权查看，请重新选择。')
                valid = False
            else:
                targets.append((kind, obj))
                selected.append(chat_references.card(kind, obj))
    if valid:
        with transaction.atomic():
            message = form.save(commit=False)
            message.quoted_message = quoted
            message.sticker = sticker
            if sticker: message.kind = 'sticker'
            message.author = request.user
            message.recipient = peer
            message.room = ChatMessage.PRIVATE if peer else key
            message.save()
            attach_files('chat_message', message, form.cleaned_data['attachments'], request.user)
            Attachment.objects.bulk_create([Attachment(chat_message=message, file=file.file.name,
                original_name=file.original_name, uploaded_by=request.user) for file in old_files])
            ChatReference.objects.bulk_create([
                ChatReference(message=message, kind=kind, **{kind: obj}) for kind, obj in targets])
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'message': serialize(message, request)}, status=201)
        return redirect(reverse('messages_private', args=[peer.pk]) if peer else reverse('messages_hub') + ('?room=public' if key == 'public' else ''))
    if request.method == 'POST' and request.headers.get('Accept') == 'application/json':
        return JsonResponse({'errors': form.errors.get_json_data()}, status=400)
    counts = unread_counts(request.user, request)
    history = list(message_data(rows, request.user).order_by('-pk')[:200])
    history.reverse()
    for message in history:
        message.reference_cards = [] if message.withdrawn_at else [chat_references.display(ref, request) for ref in message.references.all()]
        info=serialize(message,request)
        message.gift_card = info['gift']
        message.quote_card = info['quote']
        message.display_body = info['body']
    states = conversation_states(request.user)
    private_rows = ChatMessage.objects.filter(room=ChatMessage.PRIVATE)
    former_peers = Q(pk__in=private_rows.filter(author=request.user).values('recipient_id')) | Q(pk__in=private_rows.filter(recipient=request.user).values('author_id'))
    members = list(User.objects.filter(Q(is_active=True) | (Q(member_profile__deleted_at__isnull=False) & former_peers)).exclude(member_profile__tier='normal').exclude(pk=request.user.pk).select_related('member_profile').order_by('username'))
    for member in members:
        member.unread = counts.get(f'dm:{member.pk}', 0)
        member.conversation_hidden = bool(states.get(f'dm:{member.pk}') and states[f'dm:{member.pk}'].removed)
        member.conversation_muted = bool(states.get(f'dm:{member.pk}') and states[f'dm:{member.pk}'].muted)
    return render(request, 'core/messages.html', {
        'peer': peer, 'channel_key': key, 'channel_label': label, 'chat_log': history,
        'form': form, 'chat_members': members, 'public_unread': counts.get('developers', 0),
        'selected_references': selected,
        'legacy_unread': counts.get('public', 0),
        'show_legacy': key == 'public' or ChatMessage.objects.filter(room=ChatMessage.PUBLIC, withdrawn_at__isnull=True).exclude(hidden_by=request.user).exists(),
        'poll_url': reverse('messages_private_poll', args=[peer.pk]) if peer else reverse('messages_poll') + ('?room=public' if key == 'public' else ''),
        'read_url': reverse('messages_read'),
        'resend_message': source.pk if source else '',
        'resend_files': old_files,
        'conversation_muted': bool(states.get(key) and states[key].muted),
        'conversation_states': unread_payload(request.user, counts),
        'manage_url': reverse('messages_manage'),
        'history_url': reverse('messages_history'),
        'has_older': len(history) == 200,
        'history_authors': User.objects.filter(pk__in=rows.values('author_id')).order_by('username'),
    })


@login_required
@never_cache
def poll(request, peer_pk=None):
    peer, key, rows, label = channel(request, peer_pk)
    try:
        after = min(9223372036854775807, max(0, int(request.GET.get('after', 0))))
    except (TypeError, ValueError):
        after = 0
    rows = visible_messages(request.user, rows)
    latest = list(message_data(rows.filter(pk__gt=after), request.user).order_by('pk')[:100])
    known = []
    for value in request.GET.get('known', '').split(',')[:200]:
        if len(value) <= 19 and value.isascii() and value.isdigit() and 0 < int(value) <= 9223372036854775807: known.append(int(value))
    visible = set(rows.filter(pk__in=known).values_list('pk', flat=True))
    updates = message_data(rows.filter(Q(withdrawn_at__isnull=False)|Q(point_gift__isnull=False)|Q(quoted_message__isnull=False),pk__in=visible), request.user)
    return JsonResponse({'messages': [serialize(row, request) for row in latest],
                         'updates': [serialize(row, request) for row in updates],
                         'removed': sorted(set(known) - visible)})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def unread(request):
    require_member(request)
    if request.method == 'POST':
        UserPresence.objects.update_or_create(user=request.user, defaults={'last_seen': timezone.now()})
    counts = unread_counts(request.user, request)
    recent = timezone.now() - timedelta(seconds=90)
    online = set(UserPresence.objects.filter(last_seen__gte=recent).values_list('user_id', flat=True))
    members = User.objects.filter(is_active=True).exclude(member_profile__tier='normal').values_list('pk', flat=True)
    return JsonResponse({**unread_payload(request.user, counts),
        'presence': {str(pk): pk in online for pk in members}})


@login_required
@require_POST
def read(request):
    require_member(request)
    key = request.POST.get('channel', '')
    try:
        last = int(request.POST.get('last', 0))
        if not 0 < last <= 9223372036854775807:
            raise ValueError
    except (ValueError, TypeError):
        return JsonResponse({'error': '消息编号无效'}, status=400)
    if key in (ChatMessage.DEVELOPERS, ChatMessage.PUBLIC):
        rows = ChatMessage.objects.filter(room=key, recipient__isnull=True)
    elif key.startswith('dm:') and key[3:].isascii() and key[3:].isdigit() and 0 < int(key[3:]) <= 9223372036854775807:
        _, _, rows, _ = channel(request, int(key[3:]))
    else:
        return JsonResponse({'error': '会话无效'}, status=400)
    visible_last = rows.filter(pk__lte=last).order_by('-pk').values_list('pk', flat=True).first()
    mark_read(request.user, key, visible_last or 0)
    counts = unread_counts(request.user, request)
    return JsonResponse(unread_payload(request.user, counts))


def requested_channel(request):
    key = request.POST.get('channel', '') if request.method == 'POST' else request.GET.get('channel', '')
    if key in ('public', 'developers'):
        return channel(request_with_room(request, key))
    if key.startswith('dm:') and key[3:].isascii() and key[3:].isdigit() and 0 < int(key[3:]) <= 9223372036854775807:
        return channel(request, int(key[3:]))
    raise PermissionDenied('会话无效。')


def request_with_room(request, key):
    # Do not change the original request's query string for downstream code.
    from copy import copy
    proxy = copy(request)
    proxy.GET = request.GET.copy()
    proxy.GET['room'] = key
    return proxy


@login_required
@never_cache
@require_POST
def manage(request):
    peer, key, rows, label = requested_channel(request)
    action = request.POST.get('action')
    if action not in ('mute', 'unmute', 'clear', 'remove', 'restore'):
        return JsonResponse({'error': '会话操作无效。'}, status=400)
    if action in ('clear', 'remove') and request.POST.get('confirm') != 'yes':
        return JsonResponse({'error': '请确认此操作仅影响自己的聊天记录。'}, status=400)
    with transaction.atomic():
        ChatReadState.objects.filter(user=request.user, channel=key).update(last_message_id=F('last_message_id'))
        state, _ = ChatReadState.objects.get_or_create(user=request.user, channel=key)
        state = ChatReadState.objects.select_for_update().get(pk=state.pk)
        latest = rows.aggregate(last=Max('pk'))['last'] or 0
        if action in ('mute', 'unmute'): state.muted = action == 'mute'
        elif action == 'clear':
            state.cleared_through = max(state.cleared_through, latest)
            state.last_message_id = max(state.last_message_id, latest)
        elif action == 'remove':
            state.removed = True
            state.removed_through = latest
            state.last_message_id = max(state.last_message_id, latest)
        else: state.removed = False
        state.save()
    counts = unread_counts(request.user)
    return JsonResponse({**unread_payload(request.user, counts), 'muted': state.muted,
                         'cleared_through': state.cleared_through})


class HistoryForm(forms.Form):
    q = forms.CharField(required=False, max_length=100)
    start = forms.DateField(required=False)
    end = forms.DateField(required=False)
    author = forms.IntegerField(required=False, min_value=1, max_value=9223372036854775807)
    kind = forms.ChoiceField(required=False, choices=[('', '全部'), ('image', '图片'), ('file', '文件'), ('reference', '引用')])
    before = forms.IntegerField(required=False, min_value=1, max_value=9223372036854775807)
    around = forms.IntegerField(required=False, min_value=1, max_value=9223372036854775807)


@login_required
@never_cache
@require_http_methods(['GET'])
def search_history(request):
    _, key, rows, _ = requested_channel(request)
    rows = visible_messages(request.user, rows).filter(withdrawn_at__isnull=True)
    form = HistoryForm(request.GET)
    if not form.is_valid(): return JsonResponse({'error': '筛选条件无效。'}, status=400)
    values = form.cleaned_data
    if values['start'] and values['end'] and values['start'] > values['end']:
        return JsonResponse({'error': '开始日期不能晚于结束日期。'}, status=400)
    if values['around']:
        cursor = rows.aggregate(last=Max('pk'))['last'] or 0
        target = get_object_or_404(rows, pk=values['around'])
        before = list(rows.filter(pk__lte=target.pk).order_by('-pk').values_list('pk', flat=True)[:81])
        after = list(rows.filter(pk__gt=target.pk).order_by('pk').values_list('pk', flat=True)[:80])
        rows = rows.filter(pk__in=before + after).order_by('pk')
        return JsonResponse({'messages': [serialize(row, request) for row in message_data(rows, request.user)],
                             'target': target.pk, 'cursor': cursor})
    if values['q']: rows = rows.filter(Q(body__icontains=values['q'])|Q(attachments__original_name__icontains=values['q']))
    if values['start']: rows = rows.filter(created_at__date__gte=values['start'])
    if values['end']: rows = rows.filter(created_at__date__lte=values['end'])
    if values['author']: rows = rows.filter(author_id=values['author'])
    if values['kind'] == 'reference': rows = rows.filter(references__isnull=False)
    elif values['kind'] in ('image', 'file'):
        images = Q(pk__in=[])
        for suffix in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'):
            images |= Q(attachments__original_name__iendswith=suffix)
        image_messages = rows.filter(images).values('pk')
        if values['kind'] == 'image': rows = rows.filter(pk__in=image_messages)
        else:
            image_files = Q(pk__in=[])
            for suffix in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'):
                image_files |= Q(original_name__iendswith=suffix)
            rows = rows.filter(attachments__in=Attachment.objects.exclude(image_files))
    if values['before']: rows = rows.filter(pk__lt=values['before'])
    results = list(message_data(rows.distinct(), request.user).order_by('-pk')[:51])
    return JsonResponse({'messages': [serialize(row, request) for row in results[:50]],
                         'next_before': results[49].pk if len(results) > 50 else None})
