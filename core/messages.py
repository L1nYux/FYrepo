"""Small team messaging, with participant-only private conversations."""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Prefetch, Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.views.decorators.http import require_POST, require_http_methods

from . import permissions as perms
from .forms import ChatMessageForm
from .models import Attachment, ChatMessage, ChatReadState, ChatReference, UserPresence, attach_files
from . import chat_references


def reference_prefetch():
    return Prefetch('references', queryset=ChatReference.objects.select_related(
        'task__project', 'task__parent', 'experiment', 'entry', 'claim', 'announcement'))


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
    rows = ChatMessage.objects.filter(query | private, withdrawn_at__isnull=True).exclude(hidden_by=user).exclude(author=user).order_by().values('room', 'author_id').annotate(count=Count('pk'))
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
        peer = get_object_or_404(User.objects.filter(is_active=True).exclude(member_profile__tier='normal'), pk=peer_pk)
        if peer.pk == request.user.pk:
            raise PermissionDenied('请选择另一位成员。')
        rows = ChatMessage.objects.filter(room=ChatMessage.PRIVATE).filter(
            Q(author=request.user, recipient=peer) | Q(author=peer, recipient=request.user))
        return peer, f'dm:{peer.pk}', rows, peer.username
    room = ChatMessage.PUBLIC if request.GET.get('room') == 'public' else ChatMessage.DEVELOPERS
    return None, room, ChatMessage.objects.filter(room=room, recipient__isnull=True), dict(ChatMessage.ROOMS)[room]


def mark_read(user, key, last):
    if last:
        state, _ = ChatReadState.objects.get_or_create(user=user, channel=key)
        ChatReadState.objects.filter(pk=state.pk, last_message_id__lt=last).update(last_message_id=last)


def serialize(row, viewer):
    user = perms.user_of(viewer)
    return {'id': row.pk, 'author': row.author.username,
            'initial': row.author.username[:1].upper(), 'at': row.spoken_at,
            'body': '' if row.withdrawn_at else row.body, 'mine': row.author_id == user.pk,
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
    row = get_object_or_404(rows.exclude(hidden_by=request.user).select_related('author').prefetch_related('attachments', reference_prefetch()), pk=pk)
    action = request.POST.get('action')
    if action == 'delete':
        row.hidden_by.add(request.user)
        return JsonResponse({'deleted': row.pk})
    if row.author_id != request.user.pk:
        raise PermissionDenied('只能撤回或重新编辑自己发送的消息。')
    if action == 'withdraw':
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
def hub(request, peer_pk=None):
    peer, key, rows, label = channel(request, peer_pk)
    rows = rows.exclude(hidden_by=request.user)
    source = None
    if request.method == 'POST' and request.POST.get('resend_message'):
        try:
            source_id = int(request.POST['resend_message'])
            if not 0 < source_id <= 9223372036854775807: raise ValueError
        except (TypeError, ValueError):
            raise PermissionDenied('重新编辑的消息无效。')
        source = get_object_or_404(rows, pk=source_id, author=request.user, withdrawn_at__isnull=False)
    old_files = list(source.attachments.all()) if source else []
    form = ChatMessageForm(request.POST or None, request.FILES or None, allow_references=True, existing_attachments=bool(old_files))
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
    history = list(rows.select_related('author').prefetch_related('attachments', reference_prefetch()).order_by('-pk')[:200])
    history.reverse()
    for message in history:
        message.reference_cards = [] if message.withdrawn_at else [chat_references.display(ref, request) for ref in message.references.all()]
    members = list(User.objects.filter(is_active=True).exclude(member_profile__tier='normal').exclude(pk=request.user.pk).order_by('username'))
    for member in members:
        member.unread = counts.get(f'dm:{member.pk}', 0)
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
    })


@login_required
def poll(request, peer_pk=None):
    peer, key, rows, label = channel(request, peer_pk)
    try:
        after = min(9223372036854775807, max(0, int(request.GET.get('after', 0))))
    except (TypeError, ValueError):
        after = 0
    rows = rows.exclude(hidden_by=request.user)
    latest = list(rows.filter(pk__gt=after).select_related('author').prefetch_related('attachments', reference_prefetch()).order_by('pk')[:100])
    known = []
    for value in request.GET.get('known', '').split(',')[:200]:
        if len(value) <= 19 and value.isascii() and value.isdigit() and 0 < int(value) <= 9223372036854775807: known.append(int(value))
    visible = set(rows.filter(pk__in=known).values_list('pk', flat=True))
    updates = rows.filter(pk__in=visible, withdrawn_at__isnull=False).select_related('author')
    return JsonResponse({'messages': [serialize(row, request) for row in latest],
                         'updates': [serialize(row, request) for row in updates],
                         'removed': sorted(set(known) - visible)})


@login_required
@require_http_methods(['GET', 'POST'])
def unread(request):
    require_member(request)
    if request.method == 'POST':
        UserPresence.objects.update_or_create(user=request.user, defaults={'last_seen': timezone.now()})
    counts = unread_counts(request.user, request)
    recent = timezone.now() - timedelta(seconds=90)
    online = set(UserPresence.objects.filter(last_seen__gte=recent).values_list('user_id', flat=True))
    members = User.objects.filter(is_active=True).exclude(member_profile__tier='normal').values_list('pk', flat=True)
    return JsonResponse({'total': sum(counts.values()), 'channels': counts,
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
    return JsonResponse({'total': sum(counts.values()), 'channels': counts})
