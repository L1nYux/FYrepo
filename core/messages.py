"""Small team messaging, with participant-only private conversations."""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from . import permissions as perms
from .forms import ChatMessageForm
from .models import ChatMessage, ChatReadState, ChatReference, attach_files
from . import chat_references


def reference_prefetch():
    return Prefetch('references', queryset=ChatReference.objects.select_related(
        'task__project', 'task__parent', 'experiment', 'entry', 'claim', 'announcement'))


def require_member(request):
    if not perms.is_team_member(request):
        raise PermissionDenied('消息中心仅供团队成员使用。')


def unread_counts(user):
    reads = dict(ChatReadState.objects.filter(user=user).values_list('channel', 'last_message_id'))
    query = (Q(room=ChatMessage.DEVELOPERS, pk__gt=reads.get('developers', 0)) |
             Q(room=ChatMessage.PUBLIC, pk__gt=reads.get('public', 0)))
    private = Q(room=ChatMessage.PRIVATE, recipient=user, author__is_active=True)
    for key, last in reads.items():
        if key.startswith('dm:'):
            private &= ~Q(author_id=int(key[3:]), pk__lte=last)
    rows = ChatMessage.objects.filter(query | private).exclude(author=user).values('room', 'author_id')
    counts = {}
    for row in rows:
        key = f"dm:{row['author_id']}" if row['room'] == ChatMessage.PRIVATE else row['room']
        counts[key] = counts.get(key, 0) + 1
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
            'body': row.body, 'mine': row.author_id == user.pk,
            'references': [chat_references.display(ref, viewer) for ref in row.references.all()],
            'attachments': [{'name': file.original_name, 'url': reverse('attachment_download', args=[file.pk])}
                            for file in row.attachments.all()]}


@login_required
def hub(request, peer_pk=None):
    peer, key, rows, label = channel(request, peer_pk)
    form = ChatMessageForm(request.POST or None, request.FILES or None, allow_references=True)
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
            ChatReference.objects.bulk_create([
                ChatReference(message=message, kind=kind, **{kind: obj}) for kind, obj in targets])
        return redirect(reverse('messages_private', args=[peer.pk]) if peer else reverse('messages_hub') + ('?room=public' if key == 'public' else ''))
    counts = unread_counts(request.user)
    history = list(rows.select_related('author').prefetch_related('attachments', reference_prefetch()).order_by('-pk')[:200])
    history.reverse()
    for message in history:
        message.reference_cards = [chat_references.display(ref, request) for ref in message.references.all()]
    mark_read(request.user, key, history[-1].pk if history else 0)
    counts.pop(key, None)
    members = list(User.objects.filter(is_active=True).exclude(member_profile__tier='normal').exclude(pk=request.user.pk).order_by('username'))
    for member in members:
        member.unread = counts.get(f'dm:{member.pk}', 0)
    return render(request, 'core/messages.html', {
        'peer': peer, 'channel_key': key, 'channel_label': label, 'chat_log': history,
        'form': form, 'chat_members': members, 'public_unread': counts.get('developers', 0),
        'selected_references': selected,
        'legacy_unread': counts.get('public', 0),
        'show_legacy': key == 'public' or ChatMessage.objects.filter(room=ChatMessage.PUBLIC).exists(),
        'poll_url': reverse('messages_private_poll', args=[peer.pk]) if peer else reverse('messages_poll') + ('?room=public' if key == 'public' else ''),
    })


@login_required
def poll(request, peer_pk=None):
    peer, key, rows, label = channel(request, peer_pk)
    try:
        after = max(0, int(request.GET.get('after', 0)))
    except (TypeError, ValueError):
        after = 0
    latest = list(rows.filter(pk__gt=after).select_related('author').prefetch_related('attachments', reference_prefetch()).order_by('pk')[:100])
    mark_read(request.user, key, latest[-1].pk if latest else 0)
    return JsonResponse({'messages': [serialize(row, request) for row in latest]})


@login_required
def unread(request):
    require_member(request)
    counts = unread_counts(request.user)
    return JsonResponse({'total': sum(counts.values()), 'channels': counts})
