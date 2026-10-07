"""Explicit conversation space, independent of the workspace selected in the shell."""
from urllib.parse import urlencode
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from .models import Workspace, TeamMembership

SCOPED_VIEWS = frozenset({
    'messages_hub', 'messages_poll', 'messages_private', 'messages_private_poll',
    'messages_read', 'messages_manage', 'messages_history', 'message_action',
    'chat_reference_search', 'chat_reference_detail', 'attachment_download', 'member_card',
    'stickers', 'sticker_file', 'chat_public', 'chat_public_messages',
})

def select(request, identifier, *, allow_guest=False):
    from .tenancy import _space, _team
    if not str(identifier).isascii() or not str(identifier).isdigit() or len(str(identifier)) > 18:
        raise PermissionDenied('聊天空间无效。')
    space = get_object_or_404(Workspace.objects.select_related('team'), pk=identifier, active=True)
    roles = ['owner', 'admin', 'member', 'guest'] if allow_guest else ['owner', 'admin', 'member']
    if not request.user.is_authenticated or not (
        space.kind == 'personal' and space.owner_id == request.user.pk or
        space.kind == 'team' and space.team.active and TeamMembership.objects.filter(
            team=space.team, user=request.user, active=True, deleted_at__isnull=True, role__in=roles).exists()
    ):
        raise PermissionDenied('无权访问该聊天空间。')
    request.workspace = space
    request.team = space.team if space.team_id else None
    _space.set(space.pk)
    _team.set(space.team_id)
    from .permissions import account_role
    request.role = account_role(request.user)
    return space

def qualify(url, space):
    return url + ('&' if '?' in url else '?') + urlencode({'space': space.pk})
