"""Latest account heartbeat, visible only to friends and current teammates."""
from datetime import timedelta
from django.db.models import F, Q
from django.utils import timezone
from .models import Friendship, TeamMembership, UserPresence, Workspace


def visible_users(user):
    pairs = Friendship.objects.filter(Q(first=user) | Q(second=user))
    identifiers = set(pairs.values_list('first_id', flat=True)) | set(pairs.values_list('second_id', flat=True))
    teams = TeamMembership.objects.filter(user=user, active=True, deleted_at__isnull=True,
        team__active=True, role__in=['owner', 'admin', 'member']).values('team_id')
    identifiers.update(TeamMembership.objects.filter(team_id__in=teams, active=True,
        deleted_at__isnull=True, user__is_active=True, role__in=['owner', 'admin', 'member']).values_list('user_id', flat=True))
    identifiers.add(user.pk)
    return identifiers


def heartbeat(user):
    personal = Workspace.objects.get_or_create(owner=user, defaults={'kind': 'personal'})[0]
    now = timezone.now()
    # Heartbeats are transient account state, independent of the selected team.
    # Use the unscoped manager only for the authenticated user's own space and
    # bypass business record audit history for this latest timestamp.
    rows = UserPresence.all_objects.filter(workspace=personal, user=user)
    if not rows.update(last_seen=now):
        UserPresence.all_objects.bulk_create([
            UserPresence(workspace=personal, team=None, user=user, last_seen=now)
        ], ignore_conflicts=True)


def status(user):
    permitted = visible_users(user)
    online = set(UserPresence.all_objects.filter(user_id__in=permitted, user__is_active=True,
        workspace__kind='personal', workspace__owner_id=F('user_id'),
        last_seen__gte=timezone.now() - timedelta(seconds=90)).values_list('user_id', flat=True))
    return {str(pk): pk in online for pk in permitted}
