"""Acceptance reimburses usage or grants a quota; never discloses AI history."""
import uuid
from decimal import Decimal,ROUND_UP
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from aihub.models import Call,Allowance,PointGrant
from .models import ExpenseClaim,UsageReceipt,AccountNotice,Workspace,TeamMembership
from .tenancy import scope


def personal_usage(user):
    return Call.all_objects.filter(user=user,workspace__kind='personal',workspace__owner=user,status='success',cost_cny__gt=0).exclude(reimbursement_receipts__active=True).select_related('model__provider').order_by('-created_at')


def validate_receipts(claim):
    """Recheck reservations under the usage lock before paying a pending claim."""
    receipts=list(claim.usage_receipts.select_related('call__workspace').order_by('call_id'))
    Call.all_objects.filter(pk__in=[row.call_id for row in receipts]).update(status=F('status'))
    if any(not row.active for row in receipts):
        raise ValidationError('用量凭证已失效，请重新提交申请。')
    _check_receipts(claim,receipts)


def _check_receipts(claim,receipts):
    if claim.settlement_kind=='api_quota' and not receipts:
        raise ValidationError('API 用量补发必须附个人用量凭证；日常预支额度由团队 API 池直接分发。')
    for row in receipts:
        call=row.call
        if call.user_id!=claim.applicant_id or call.workspace.kind!='personal' or call.workspace.owner_id!=claim.applicant_id or call.status!='success':
            raise ValidationError('用量凭证不再可用。')
    if UsageReceipt.objects.filter(call_id__in=[row.call_id for row in receipts],active=True).exclude(claim=claim).exists():
        raise ValidationError('该用量已在另一笔申请中使用，不能重复报销。')
    total=sum((row.amount for row in receipts),Decimal('0'))
    if receipts and claim.amount>total.quantize(Decimal('.01'),rounding=ROUND_UP):
        raise ValidationError('申请金额不能超过个人用量凭证的合计。')


@transaction.atomic
def restore_receipts(claims):
    """Restoring a pending claim must reserve its usage again, or fail entirely."""
    rows=[]
    for claim in claims:
        if claim.status==ExpenseClaim.PENDING:
            receipts=list(claim.usage_receipts.select_related('call__workspace').order_by('call_id'))
            rows.append((claim,receipts))
    ids=[row.call_id for _claim,receipts in rows for row in receipts]
    Call.all_objects.filter(pk__in=ids).update(status=F('status'))
    if len(ids)!=len(set(ids)):
        raise ValidationError('恢复范围中存在重复用量申请，请分别核对。')
    for claim,receipts in rows:
        _check_receipts(claim,receipts)
    UsageReceipt.objects.filter(pk__in=[row.pk for _claim,receipts in rows for row in receipts]).update(active=True)


def submit(claim,calls):
    with transaction.atomic():
        # Lock each usage row before reserving it, across all requesting teams.
        ids=sorted([item.pk for item in calls],key=str)
        Call.all_objects.filter(pk__in=ids).update(status=F('status'))
        available=list(personal_usage(claim.applicant).filter(pk__in=ids))
        if len(available)!=len(ids):raise ValidationError('所选用量已提交过申请或不再可用，请刷新后重选。')
        if claim.settlement_kind=='api_quota' and not available:
            raise ValidationError('API 用量补发必须附个人用量凭证。')
        total=sum((item.cost_cny for item in available),Decimal('0'))
        if ids and claim.amount>total.quantize(Decimal('.01'),rounding=ROUND_UP):raise ValidationError('申请金额不能超过所选个人用量的合计。')
        if claim.settlement_kind=='api_quota' and claim.workspace.kind!='team':raise ValidationError('请选择一个团队申请 AI 额度。')
        claim.save()
        for item in available:UsageReceipt.objects.create(claim=claim,call=item,amount=item.cost_cny,model_label=str(item.model)[:200],occurred_at=item.created_at)
        if claim.team_id:
            from .team_permissions import allowed
            recipients=TeamMembership.objects.filter(team_id=claim.team_id,active=True,deleted_at__isnull=True,user__is_active=True).select_related('user')
            for member in recipients:
                if allowed(member.user,'finance'):AccountNotice.objects.create(user=member.user,title='新的经费申请',body=claim.memo[:120],target_url='/finance/?tab=claims&ownership='+str(claim.workspace_id))
    return claim


def issue_quota(claim,reviewer):
    from aihub.permissions import require_pool_owner
    from aihub.service import allowance
    require_pool_owner(reviewer)
    if not TeamMembership.objects.filter(team_id=claim.team_id,user=claim.applicant,active=True,deleted_at__isnull=True,role__in=['owner','admin','member'],team__active=True).exists():raise ValidationError('申请人已离开团队，无法补发团队额度。')
    member=allowance(claim.applicant)
    if not member.enabled:raise ValidationError('申请人的 API 池资格已停用，无法补发额度。')
    identifier=uuid.uuid5(uuid.NAMESPACE_URL,'workbench-claim-quota:'+str(claim.pk))
    grant,created=PointGrant.objects.get_or_create(id=identifier,defaults={'user':claim.applicant,'issued_by':reviewer,'amount_cny':claim.amount})
    if created:Allowance.objects.filter(pk=member.pk).update(extra_balance=F('extra_balance')+claim.amount)
    return created


def finish(claim):
    if claim.status==ExpenseClaim.REJECTED:claim.usage_receipts.update(active=False)
    body=claim.review_note
    if claim.status==ExpenseClaim.APPROVED:
        body=('用量报销已通过，已补发 '+str(claim.amount*100)+' 点团队 AI 额度。'
              if claim.settlement_kind=='api_quota' else '现金报销已通过并入账。')
    AccountNotice.objects.create(user=claim.applicant,title='经费申请已处理',body=body,target_url='/finance/?tab=claims&ownership='+str(claim.workspace_id))
