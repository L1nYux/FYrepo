"""Opt-in discovery and private offers with capacity and authority checks."""
from datetime import timedelta
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, F
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from .models import ApplicantProfile, TeamMembership, RecruitmentOffer, AccountNotice, Project, ProjectCollaborator
from .pagination import page
from .recruitment import ResumeForm


def recruiting_memberships(user):
    return [m for m in TeamMembership.objects.filter(user=user,active=True,deleted_at__isnull=True,team__active=True).select_related('team') if m.role in ('owner','admin') or m.role=='member' and 'recruitment' in m.permissions]


def can_offer(user,team):
    return user.is_active and any(m.team_id==team.pk for m in recruiting_memberships(user))


def public_profiles(user):
    return ApplicantProfile.objects.filter(listed=True,user__is_active=True).exclude(blocked_teams__in=TeamMembership.objects.filter(user=user,active=True,deleted_at__isnull=True).values('team_id')).select_related('user__member_profile').distinct()


@login_required
@never_cache
def market(request):
    q=request.GET.get('q','').strip()[:100]
    rows=public_profiles(request.user)
    if q:rows=rows.filter(Q(skills__icontains=q)|Q(intention__icontains=q)|Q(introduction__icontains=q)|Q(user__member_profile__nickname__icontains=q))
    return render(request,'core/talent_market.html',{'talents':page(request,rows.order_by('-updated_at','pk')),'query':q})


@login_required
@never_cache
def profile(request):
    value=ApplicantProfile.objects.filter(user=request.user).first()
    form=ResumeForm(request.POST or None,instance=value)
    if request.method=='POST' and form.is_valid():
        value=form.save(commit=False);value.user=request.user;value.save()
        messages.success(request,'人才资料已保存。' if value.listed else '人才资料已保存，未在市场展示。')
        return redirect('talent_profile')
    return render(request,'core/talent_profile.html',{'form':form,'talent_profile':value})


class OfferForm(forms.Form):
    team=forms.ChoiceField(label='发出邀请的团队')
    project=forms.ChoiceField(label='项目合作（可选）',required=False)
    title=forms.CharField(label='职位或合作名称',max_length=120)
    terms=forms.CharField(label='负责事项与合作条件',max_length=4000,widget=forms.Textarea(attrs={'rows':5}))
    days=forms.IntegerField(label='有效期（天）',min_value=1,max_value=30,initial=7)


@login_required
@never_cache
def detail(request,pk):
    person=get_object_or_404(public_profiles(request.user),user_id=pk)
    memberships=recruiting_memberships(request.user)
    form=OfferForm(request.POST or None)
    form.fields['team'].choices=[(str(m.team_id),m.team.name) for m in memberships]
    from .tenancy import scope
    from .permissions import can_manage_project
    projects=[]
    for membership in memberships:
        with scope(membership.team):
            projects += [p for p in Project.objects.filter(archived_at__isnull=True).select_related('workspace') if can_manage_project(request.user,p)]
    form.fields['project'].choices=[('','邀请加入团队')]+[(str(p.pk),p.name+' · '+p.workspace.name) for p in projects]
    if request.method=='POST' and form.is_valid():
        if pk==request.user.pk:raise PermissionDenied('不能向自己发出邀请。')
        team=next(m.team for m in memberships if str(m.team_id)==form.cleaned_data['team'])
        if team.recruitment_mode=='closed':form.add_error('team','该团队已暂停招募。')
        elif person.blocked_teams.filter(pk=team.pk).exists():raise PermissionDenied('对方不接受这个团队的邀请。')
        elif not can_offer(request.user,team):raise PermissionDenied('团队招募授权已失效。')
        else:
            project=next((p for p in projects if str(p.pk)==form.cleaned_data['project']),None)
            if project and project.team_id!=team.pk:form.add_error('project','请选择该团队的项目。')
            else:
                with transaction.atomic():
                    # Serialize pending-offer creation across database engines.
                    type(team).objects.filter(pk=team.pk).update(member_limit=F('member_limit'))
                    RecruitmentOffer.objects.filter(team=team,recipient=person.user,state='pending',expires_at__lte=timezone.now()).update(state='expired')
                    if RecruitmentOffer.objects.filter(team=team,recipient=person.user,state='pending').exists():form.add_error(None,'该团队已有待回应的邀请，可在发出的邀请中查看。')
                    elif RecruitmentOffer.objects.filter(team=team,created_at__gte=timezone.now()-timedelta(days=1)).count()>=30:form.add_error(None,'今天发出的邀请已达上限，请稍后再试。')
                    else:
                        offer=RecruitmentOffer.objects.create(team=team,recipient=person.user,issued_by=request.user,project=project,title=form.cleaned_data['title'],terms=form.cleaned_data['terms'],expires_at=timezone.now()+timedelta(days=form.cleaned_data['days']))
                        AccountNotice.objects.create(user=person.user,title=team.name+' 向你发出合作邀请',body=offer.title,target_url='/discover/offers/'+str(offer.pk)+'/')
                        messages.success(request,'邀请已发出，等待对方接受。');return redirect('talent_offers')
    return render(request,'core/talent_detail.html',{'talent':person,'offer_form':form if memberships and pk!=request.user.pk else None})


@login_required
@never_cache
def offers(request):
    sent=request.GET.get('view')=='sent'
    teams=[m.team_id for m in recruiting_memberships(request.user)]
    rows=RecruitmentOffer.objects.filter(team_id__in=teams) if sent else RecruitmentOffer.objects.filter(recipient=request.user)
    return render(request,'core/talent_offers.html',{'offers':page(request,rows.select_related('team','recipient__member_profile','project')),'sent':sent,'now':timezone.now()})


@login_required
@never_cache
def offer_detail(request,pk):
    offer=get_object_or_404(RecruitmentOffer.objects.select_related('team','recipient__member_profile','project','issued_by'),pk=pk)
    recipient=offer.recipient_id==request.user.pk
    if not recipient and not can_offer(request.user,offer.team):raise PermissionDenied
    AccountNotice.objects.filter(user=request.user,target_url='/discover/offers/'+str(pk)+'/',read_at__isnull=True).update(read_at=timezone.now())
    return render(request,'core/talent_offer.html',{'offer':offer,'recipient':recipient,'offer_available':offer.state=='pending' and offer.expires_at>timezone.now() and offer.team.active})


@login_required
@require_POST
def respond(request,pk):
    with transaction.atomic():
        RecruitmentOffer.objects.filter(pk=pk).update(state=F('state'))
        offer=get_object_or_404(RecruitmentOffer.objects.select_for_update().select_related('team','recipient','project','issued_by'),pk=pk)
        action=request.POST.get('action')
        if action=='withdraw':
            if not can_offer(request.user,offer.team):raise PermissionDenied
        elif offer.recipient_id!=request.user.pk:raise PermissionDenied
        if offer.state!='pending':messages.info(request,'这份邀请已经处理。');return redirect('talent_offer',pk=pk)
        if offer.expires_at<=timezone.now():offer.state='expired'
        elif action in ('decline','block','withdraw'):
            offer.state='withdrawn' if action=='withdraw' else 'declined'
            if action=='block':ApplicantProfile.objects.get_or_create(user=request.user)[0].blocked_teams.add(offer.team)
        elif action=='accept':
            if not offer.team.active or not can_offer(offer.issued_by,offer.team):raise PermissionDenied('邀请授权已失效，请联系团队重新发出。')
            try:
                if offer.project_id:
                    if offer.project.archived_at:raise ValidationError('合作项目已归档。')
                    from .tenancy import scope
                    from .permissions import can_manage_project
                    with scope(offer.project.workspace):
                        if not can_manage_project(offer.issued_by,offer.project):raise PermissionDenied('项目邀请授权已失效。')
                    ProjectCollaborator.objects.update_or_create(project=offer.project,user=request.user,defaults={'granted_by':offer.issued_by,'offer':offer,'active':True,'expires_at':None})
                else:
                    from .admission import admit_member
                    admit_member(request.user,offer.team,offer.title)
            except ValidationError as error:messages.error(request,' '.join(error.messages));return redirect('talent_offer',pk=pk)
            offer.state='accepted'
        else:raise PermissionDenied
        offer.responded_at=timezone.now();offer.save(update_fields=['state','responded_at'])
        other=offer.recipient if action=='withdraw' else offer.issued_by
        AccountNotice.objects.create(user=other,title=offer.team.name+' 的邀请'+offer.get_state_display(),body=offer.title,target_url='/discover/offers/'+str(pk)+'/')
    return redirect('project_detail',pk=offer.project_id) if offer.state=='accepted' and offer.project_id else redirect('talent_offer',pk=pk)
