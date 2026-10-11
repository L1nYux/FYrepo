"""Transactional issue, redeem and revoke for internal quota reset entitlements."""
import uuid
from datetime import timedelta
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from core.tenancy import team_users
from .models import ResetCard, PoolSettings, BudgetWeek, BudgetMonth
from .service import pool_settings, reset_budget, require_member, week_now, month_now


def issue(actor, target, period, count, days, batch_id):
    require_member(actor)
    from .permissions import is_pool_owner
    if not is_pool_owner(actor): raise PermissionDenied('仅 API 池负责人可以发放重置卡。')
    if period not in ('week', 'month', 'both'):
        raise ValidationError('请选择重置周期。')
    try:
        count, days, batch_id = int(count), int(days), uuid.UUID(str(batch_id))
    except (ValueError, TypeError, OverflowError):
        raise ValidationError('发卡参数无效。') from None
    if not 1 <= count <= 20 or not 1 <= days <= 365:
        raise ValidationError('每人可发 1–20 张，有效期为 1–365 天。')
    members = team_users(member_only=True)
    if target != 'all':
        if not str(target).isascii() or not str(target).isdigit() or len(str(target)) > 18:
            raise ValidationError('请选择本团队成员。')
        members = members.filter(pk=target)
    members = list(members.order_by('pk'))
    if not members:
        raise ValidationError('没有可发放的成员。')
    config = pool_settings()
    caps = [cap for name, cap in [('week',config.default_weekly_limit),('month',config.default_member_limit)] if period in (name,'both')]
    if not any(cap is not None and cap > 0 for cap in caps):
        raise ValidationError('请先设置对应的成员周期额度。')
    with transaction.atomic():
        PoolSettings.objects.filter(pk=config.pk).update(enabled=F('enabled'))
        existing = list(ResetCard.objects.filter(batch_id=batch_id))
        if existing:
            if len(existing) != len(members)*count or {c.user_id for c in existing} != {u.pk for u in members} or any(c.period != period or c.issued_by_id != actor.pk for c in existing):
                raise ValidationError('这个发放请求已经处理，请刷新后重新发放。')
            return 0
        expires = timezone.now()+timedelta(days=days)
        ResetCard.objects.bulk_create([ResetCard(batch_id=batch_id,ordinal=i,user=user,issued_by=actor,period=period,expires_at=expires) for user in members for i in range(count)])
    return len(members)*count


def redeem(user, identifier):
    require_member(user)
    try: identifier = uuid.UUID(str(identifier))
    except (ValueError, TypeError): raise ValidationError('重置卡无效。') from None
    config = pool_settings()
    with transaction.atomic():
        PoolSettings.objects.filter(pk=config.pk).update(enabled=F('enabled'))
        card = ResetCard.objects.filter(pk=identifier,user=user).first()
        if not card or card.cancelled_at or card.expires_at <= timezone.now():
            raise ValidationError('重置卡已过期、已撤销或不可用。')
        if card.used_at:
            return False
        periods = [(BudgetWeek, 'week', week_now(), config.default_weekly_limit),
                   (BudgetMonth, 'month', month_now(), config.default_member_limit)]
        usable = False
        for model, period, start, cap in periods:
            if card.period not in (period, 'both') or cap is None or cap <= 0: continue
            row = model.objects.filter(scope='user:'+str(user.pk), **{period:start}).first()
            if row and (row.spent > row.reset_credit or row.reserved > 0): usable = True
        if not usable:
            raise ValidationError('当前没有可恢复的周期用量，重置卡已保留。')
        reset_budget('user:'+str(user.pk),card.period,actor=user,card=card,reason='使用重置卡')
        ResetCard.objects.filter(pk=card.pk,used_at__isnull=True).update(used_at=timezone.now())
    return True


def revoke(actor, identifier):
    from .permissions import is_pool_owner
    if not is_pool_owner(actor): raise PermissionDenied('仅 API 池负责人可以撤销重置卡。')
    try: identifier = uuid.UUID(str(identifier))
    except (ValueError, TypeError): raise ValidationError('重置卡无效。') from None
    return ResetCard.objects.filter(pk=identifier,used_at__isnull=True,cancelled_at__isnull=True).update(cancelled_at=timezone.now())
