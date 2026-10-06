"""Opt-in team listings and private, recipient-checked applications."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError
from django.db.models import Q, Count, F
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import Team, TeamMembership, TeamOpening, TeamApplication, ApplicantProfile, Invite
from .pagination import page
from .team_permissions import require
from .admission import join_from_invitation
from .teams import valid_id


class ListingForm(forms.ModelForm):
    class Meta:
        model=Team
        fields=['listed','introduction','research_area']
        labels={'listed':'公开展示在团队广场','introduction':'团队介绍','research_area':'研究与业务方向'}


class OpeningForm(forms.ModelForm):
    class Meta:
        model=TeamOpening
        fields=['title','description','active']
        labels={'title':'招募职位','description':'招募说明','active':'开放投递'}


class ResumeForm(forms.ModelForm):
    class Meta:
        model=ApplicantProfile
        fields=['introduction','skills','portfolio']
        labels={'introduction':'经历与个人介绍','skills':'技能与研究方向','portfolio':'作品链接（可选）'}


class ApplicationForm(forms.Form):
    resume=forms.CharField(label='本次投递的简历',max_length=5000,widget=forms.Textarea)
    portfolio=forms.URLField(label='作品链接（可选）',required=False,max_length=1000)
    note=forms.CharField(label='给团队的话（可选）',required=False,max_length=1000,widget=forms.Textarea)


def listings():
    return Team.objects.filter(active=True,listed=True)


@login_required
def square(request):
    query=request.GET.get('q','').strip()[:100]
    teams=listings().annotate(opening_count=Count('openings',filter=Q(openings__active=True)))
    if query:
        teams=teams.filter(Q(name__icontains=query)|Q(research_area__icontains=query)|Q(introduction__icontains=query))
    return render(request,'core/team_square.html',{'listing_teams':page(request,teams.order_by('-created_at','-pk')),'query':query})


@login_required
def detail(request,pk):
    team=get_object_or_404(listings(),pk=pk)
    return render(request,'core/team_listing.html',{'listing_team':team,'openings':page(request,TeamOpening.objects.filter(team=team,active=True))})


@login_required
def manage(request):
    require(request,'recruitment')
    team=request.team
    form=ListingForm(request.POST if request.method=='POST' and request.POST.get('action')=='listing' else None,instance=team)
    opening_form=OpeningForm(request.POST if request.method=='POST' and request.POST.get('action')=='opening' else None)
    if request.method=='POST':
        action=request.POST.get('action')
        if action=='listing' and form.is_valid():
            # Only listing fields belong to this form; capacity and ownership may
            # have changed since request.team was loaded.
            Team.objects.filter(pk=team.pk).update(**form.cleaned_data)
            messages.success(request,'团队广场资料已保存。'); return redirect('recruitment_manage')
        if action=='opening' and opening_form.is_valid():
            item=opening_form.save(commit=False);item.team=team;item.save()
            messages.success(request,'招募职位已发布。'); return redirect('recruitment_manage')
        if action=='close':
            if not valid_id(request.POST.get('opening','')): raise PermissionDenied
            item=get_object_or_404(TeamOpening,pk=request.POST.get('opening'),team=team)
            TeamOpening.objects.filter(pk=item.pk,team=team).update(active=False)
            return redirect('recruitment_manage')
        if action not in ('listing','opening','close'): raise PermissionDenied
    return render(request,'core/recruitment_manage.html',{'form':form,'opening_form':opening_form,
        'openings':page(request,TeamOpening.objects.filter(team=team))})


@login_required
def resume(request):
    profile=ApplicantProfile.objects.filter(user=request.user).first()
    form=ResumeForm(request.POST or None,instance=profile)
    if request.method=='POST' and form.is_valid():
        item=form.save(commit=False);item.user=request.user;item.save()
        messages.success(request,'简历已保存，仅在你投递时发送给对应团队。')
        return redirect('my_applications')
    return render(request,'core/community_form.html',{'form':form,'title':'我的简历','submit_label':'保存简历'})


@login_required
def apply(request,pk):
    opening=get_object_or_404(TeamOpening,pk=pk,active=True,team__active=True,team__listed=True)
    if TeamMembership.objects.filter(team=opening.team,user=request.user,active=True,deleted_at__isnull=True).exists():
        messages.info(request,'你已在这个团队中。'); return redirect('team_listing',pk=opening.team_id)
    profile=ApplicantProfile.objects.filter(user=request.user).first()
    form=ApplicationForm(request.POST or None,initial={'resume':(profile.skills+'\n\n'+profile.introduction).strip(),'portfolio':profile.portfolio} if profile else {})
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                old=TeamApplication.objects.select_for_update().filter(opening=opening,applicant=request.user).first()
                if old and old.state in ('pending','accepted'):raise IntegrityError
                if old:
                    if old.invite_id:Invite.all_objects.filter(pk=old.invite_id,used_at__isnull=True).update(revoked_at=timezone.now())
                    for key,value in form.cleaned_data.items():setattr(old,key,value)
                    old.state='pending';old.invite=None;old.reviewed_by=None;old.review_note='';old.save()
                else:TeamApplication.objects.create(opening=opening,applicant=request.user,**form.cleaned_data)
        except IntegrityError:
            form.add_error(None,'你已投递过该职位，请在我的申请中查看进度。')
        else:
            messages.success(request,'申请已发送，正式加入仍需团队审核和成员名额。')
            return redirect('my_applications')
    return render(request,'core/community_form.html',{'form':form,'title':'投递 · '+opening.title,'submit_label':'发送申请'})


@login_required
def applications(request):
    return render(request,'core/team_applications.html',{'applications':page(request,TeamApplication.objects.filter(applicant=request.user).select_related('opening__team'))})


@login_required
@require_POST
def application_action(request,pk):
    action=request.POST.get('action')
    with transaction.atomic():
        TeamApplication.objects.filter(pk=pk,applicant=request.user).update(state=F('state'))
        item=get_object_or_404(TeamApplication.objects.select_for_update().select_related('opening__team'),pk=pk,applicant=request.user)
        if action=='withdraw' and item.state in ('pending','accepted'):
            was_accepted = item.state == 'accepted'
            if item.invite_id: Invite.all_objects.filter(pk=item.invite_id,used_at__isnull=True).update(revoked_at=timezone.now())
            item.state='withdrawn'; item.save(update_fields=['state','updated_at'])
            from .models import AccountNotice
            AccountNotice.objects.filter(application=item,user=request.user,read_at__isnull=True).update(read_at=timezone.now())
            if was_accepted and item.reviewed_by_id:
                AccountNotice.objects.create(user_id=item.reviewed_by_id, application=item,
                    title='申请人取消了加入 '+item.opening.team.name, body='对方已撤回这次申请，未加入团队。')
        elif action=='join' and item.state=='accepted':
            try:
                team=join_from_invitation(request.user,invite=Invite.all_objects.filter(pk=item.invite_id).first())
            except ValidationError as error:
                messages.error(request,' '.join(error.messages))
            else:
                item.state='joined';item.save(update_fields=['state','updated_at'])
                from .models import AccountNotice
                AccountNotice.objects.filter(application=item,user=request.user,read_at__isnull=True).update(read_at=timezone.now())
                if item.reviewed_by_id:
                    AccountNotice.objects.create(user_id=item.reviewed_by_id,application=item,title='申请人已确认加入 '+team.name,body='对方已加入团队，可在团队成员中查看。')
                request.session['workbench-team']=team.pk
                request.session['workbench-space']='team:'+str(team.pk)
                return redirect('workspace_home')
        else: raise PermissionDenied
    return redirect('my_applications')


@login_required
def review(request):
    require(request,'recruitment')
    fresh_code=None
    if request.method=='POST':
        if not valid_id(request.POST.get('application','')): raise PermissionDenied
        with transaction.atomic():
            TeamApplication.objects.filter(pk=request.POST['application'],opening__team=request.team,state='pending').update(state=F('state'))
            item=get_object_or_404(TeamApplication.objects.select_for_update(),pk=request.POST.get('application'),opening__team=request.team,state='pending')
            action=request.POST.get('action')
            if action not in ('accept','reject'): raise PermissionDenied
            item.state='accepted' if action=='accept' else 'rejected'
            item.reviewed_by=request.user;item.review_note=request.POST.get('review_note','').strip()[:500]
            if action=='accept':
                invite,fresh_code=Invite.issue(request.user)
                invite.restricted_user=item.applicant;invite.save(update_fields=['restricted_user'])
                item.invite=invite
            item.save()
            from .models import AccountNotice
            AccountNotice.objects.create(user=item.applicant,application=item,
                title=item.opening.team.name+(' 通过了你的申请' if action=='accept' else ' 已完成申请审核'),
                body='请确认是否加入该团队。确认后才成为团队成员。' if action=='accept' else item.review_note or '此次申请未通过。')
            messages.success(request,'审核已保存。接受申请后，对方可在我的申请中确认加入；加入时仍检查人数上限。')
    return render(request,'core/team_applications.html',{'review_mode':True,'fresh_code':fresh_code,
        'applications':page(request,TeamApplication.objects.filter(opening__team=request.team).select_related('opening','applicant'))})
