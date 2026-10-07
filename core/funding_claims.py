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


def submit(claim,calls):
    with transaction.atomic():
        # Lock each usage row before reserving it, across all requesting teams.
        ids=sorted([item.pk for item in calls],key=str)
        Call.all_objects.filter(pk__in=ids).update(status=F('status'))
        available=list(personal_usage(claim.applicant).filter(pk__in=ids))
        if len(available)!=len(ids):raise ValidationError('所选用量已提交过申请或不再可用，请刷新后重选。')
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
    AccountNotice.objects.create(user=claim.applicant,title='经费申请已处理',body=('已补发 '+str(claim.amount*100)+' 点团队 AI 额度。' if claim.status==ExpenseClaim.APPROVED and claim.settlement_kind=='api_quota' else '现金报销已通过并入账。' if claim.status==ExpenseClaim.APPROVED else claim.review_note),target_url='/finance/?tab=claims&ownership='+str(claim.workspace_id))
