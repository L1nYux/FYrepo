"""Opt-in team listings and private, recipient-checked applications."""
from collections import Counter
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError
from django.db.models import Q, Count, F, Exists, OuterRef
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
        fields=['introduction','research_area']
        labels={'introduction':'团队介绍','research_area':'研究与业务方向'}
        widgets={'introduction':forms.Textarea(attrs={'rows':4})}


class OpeningForm(forms.ModelForm):
    planned_headcount=forms.IntegerField(label='计划招募人数',min_value=1,max_value=1000)
    class Meta:
        model=TeamOpening
        fields=['title','description','planned_headcount','active']
        labels={'title':'招募职位','description':'招募说明','active':'开放投递'}
        widgets={'description':forms.Textarea(attrs={'rows':4})}


class OpeningEditForm(OpeningForm):
    class Meta(OpeningForm.Meta):
        # Editing copy/capacity must not change the separately managed lifecycle.
        fields=['title','description','planned_headcount']


def lock_opening(opening):
    """Called inside admission transactions, before adding an actual member."""
    TeamOpening.objects.filter(pk=opening.pk).update(active=F('active'))
    opening.refresh_from_db()
    count=TeamApplication.objects.filter(opening=opening,state='joined').count()
    if not opening.active or opening.paused:raise ValidationError('该招聘已暂停或结束。')
    if opening.planned_headcount is None:raise ValidationError('请先由 HR 为这条历史招聘设置计划人数。')
    if count>=opening.planned_headcount:raise ValidationError('该招聘已招满。')


def finish_opening(opening):
    if opening.planned_headcount is not None and TeamApplication.objects.filter(opening=opening,state='joined').count()>=opening.planned_headcount:
        TeamOpening.objects.filter(pk=opening.pk).update(active=False,paused=False)
    sync_recruitment(opening.team_id)


def available_openings():
    return TeamOpening.objects.filter(active=True,paused=False,planned_headcount__isnull=False).annotate(
        joined_count=Count('applications',filter=Q(applications__state='joined'))).filter(planned_headcount__gt=F('joined_count'))


def sync_recruitment(team_id):
    recruiting=available_openings().filter(team_id=team_id).exists()
    Team.objects.filter(pk=team_id).update(listed=recruiting,recruitment_mode='open' if recruiting else 'closed')


class ResumeForm(forms.ModelForm):
    class Meta:
        model=ApplicantProfile
        fields=['listed','intention','availability','introduction','skills','portfolio']
        labels={'introduction':'经历与个人介绍','skills':'技能与研究方向','portfolio':'作品链接（可选）'}


class ApplicationForm(forms.Form):
    resume=forms.CharField(label='本次投递的简历',max_length=5000,widget=forms.Textarea)
    portfolio=forms.URLField(label='作品链接（可选）',required=False,max_length=1000)
    note=forms.CharField(label='给团队的话（可选）',required=False,max_length=1000,widget=forms.Textarea)


def listings():
    # The same rule hides old closed/full listings without a data migration.
    return Team.objects.filter(active=True,listed=True,recruitment_mode='open',solo_owner__isnull=True).annotate(
        active_member_count=Count('memberships',filter=Q(memberships__active=True,memberships__deleted_at__isnull=True))).filter(
        active_member_count__lt=F('member_limit')).annotate(
        has_available_opening=Exists(available_openings().filter(team_id=OuterRef('pk')))).filter(has_available_opening=True)


def recruiting_team_ids(user):
    return {membership.team_id for membership in TeamMembership.objects.filter(
        user=user,active=True,deleted_at__isnull=True,team__active=True,
        role__in=['owner','admin','member'])
        if membership.role=='owner' or 'recruitment' in membership.permissions}


@login_required
def square(request):
    query=request.GET.get('q','').strip()[:100]
    teams=listings()
    if query:
        teams=teams.filter(Q(name__icontains=query)|Q(research_area__icontains=query)|Q(introduction__icontains=query))
    listing_teams=page(request,teams.order_by('-created_at','-pk'))
    manageable=recruiting_team_ids(request.user)
    counts=Counter(available_openings().filter(team_id__in=[team.pk for team in listing_teams]).values_list('team_id',flat=True))
    for team in listing_teams:
        team.can_manage_recruitment=team.pk in manageable
        team.opening_count=counts[team.pk]
    return render(request,'core/team_square.html',{'listing_teams':listing_teams,'query':query})


@login_required
def detail(request,pk):
    team=get_object_or_404(listings(),pk=pk)
    return render(request,'core/team_listing.html',{'listing_team':team,
        'can_manage_listing':team.pk in recruiting_team_ids(request.user),
        'openings':page(request,available_openings().filter(team=team).order_by('-created_at','-pk'))})


def _management_page(request,team,form,opening_form,editing=None,edit_form=None):
    rows=TeamOpening.objects.filter(team=team).annotate(
        joined_count=Count('applications',filter=Q(applications__state='joined')))
    opening_page=page(request,rows.order_by('-created_at','-pk'))
    visible_ids=set()
    for item in opening_page:
        visible_ids.add(item.pk)
        item.edit_form=edit_form if editing and item.pk==editing.pk else OpeningEditForm(
            instance=item,auto_id='opening_'+str(item.pk)+'_%s')
    # Keep invalid edits reachable when a stale form posts from another page.
    failed_opening=None
    if editing and editing.pk not in visible_ids:
        failed_opening=rows.get(pk=editing.pk)
        failed_opening.edit_form=edit_form
    return render(request,'core/recruitment_manage.html',{
        'form':form,'opening_form':opening_form,'openings':opening_page,
        'failed_opening':failed_opening,
        'recruitment_visible':listings().filter(pk=team.pk).exists(),
        'recruitment_capacity_full':TeamMembership.objects.filter(
            team=team,active=True,deleted_at__isnull=True).count()>=team.member_limit,
        'opening_total':rows.count(),'opening_available':available_openings().filter(team=team).count(),
        'opening_paused':rows.filter(paused=True).count(),
        'can_stop_recruitment':rows.filter(Q(active=True)|Q(paused=True)).exists(),
    })


@login_required
def manage(request):
    require(request,'recruitment')
    team=request.team
    if team.solo_owner_id:
        raise PermissionDenied('封闭单人团队不公开展示，也不开放招募。')
    form=ListingForm(request.POST if request.method=='POST' and request.POST.get('action')=='listing' else None,instance=team)
    opening_form=OpeningForm(request.POST if request.method=='POST' and request.POST.get('action')=='opening' else None)
    if request.method=='POST':
        with transaction.atomic():
            from .team_permissions import require_hr_locked
            require_hr_locked(request,team)
            action=request.POST.get('action')
            if action=='stop_recruitment':
                Team.objects.filter(pk=team.pk).update(recruitment_mode='closed',listed=False)
                TeamOpening.objects.filter(team=team).update(active=False,paused=False)
                messages.success(request,'已取消全部招聘并从团队广场撤下；团队与历史申请保留。')
                return redirect('recruitment_manage')
            if action=='listing' and form.is_valid():
                # Only listing fields belong to this form; capacity and ownership may
                # have changed since request.team was loaded.
                Team.objects.filter(pk=team.pk).update(**form.cleaned_data)
                messages.success(request,'团队广场资料已保存。'); return redirect('recruitment_manage')
            if action=='opening' and opening_form.is_valid():
                item=opening_form.save(commit=False);item.team=team;item.save()
                sync_recruitment(team.pk)
                messages.success(request,'招募职位已发布。'); return redirect('recruitment_manage')
            if action in ('close','pause','resume','edit'):
                if not valid_id(request.POST.get('opening','')): raise PermissionDenied
                item=get_object_or_404(TeamOpening.objects.select_for_update(),pk=request.POST.get('opening'),team=team)
                if action=='edit':
                    edit=OpeningEditForm(request.POST,instance=item,auto_id='opening_'+str(item.pk)+'_%s')
                    if not edit.is_valid():
                        return _management_page(request,team,form,opening_form,item,edit)
                    for name in ('title','description','planned_headcount'):setattr(item,name,edit.cleaned_data[name])
                elif action=='pause':item.active=False;item.paused=True
                elif action=='close':item.active=False;item.paused=False
                else:item.active=True;item.paused=False
                joined=TeamApplication.objects.filter(opening=item,state='joined').count()
                if item.active and (item.planned_headcount is None or joined>=item.planned_headcount):
                    if action=='edit':
                        edit.add_error('planned_headcount','该职位已有 '+str(joined)+' 人加入，请增加计划人数后保存。')
                        return _management_page(request,team,form,opening_form,item,edit)
                    messages.error(request,'请先增加计划人数，招满的职位不能重新开放。')
                    return redirect('recruitment_manage')
                item.save(update_fields=['title','description','planned_headcount','active','paused'])
                sync_recruitment(team.pk)
                messages.success(request,'招募已更新，申请与审核记录保留。')
                return redirect('recruitment_manage')
            if action=='headcount':
                if not valid_id(request.POST.get('opening','')):raise PermissionDenied
                item=get_object_or_404(TeamOpening,pk=request.POST.get('opening'),team=team)
                number=request.POST.get('planned_headcount','')
                if not number.isascii() or not number.isdigit() or len(number)>4 or not 1<=int(number)<=1000:
                    messages.error(request,'计划招募人数须为 1–1000。')
                else:
                    joined=TeamApplication.objects.filter(opening=item,state='joined').count()
                    TeamOpening.objects.filter(pk=item.pk).update(planned_headcount=int(number),active=item.active and joined<int(number))
                    sync_recruitment(team.pk)
                    messages.success(request,'计划人数已保存；已招满的招聘自动结束。')
                return redirect('recruitment_manage')
            if action not in ('listing','opening','close','headcount','pause','resume','edit','stop_recruitment'): raise PermissionDenied
    return _management_page(request,team,form,opening_form)


@login_required
def resume(request):
    from .talent import legacy_profile
    return legacy_profile(request)


@login_required
def apply(request,pk):
    opening=get_object_or_404(available_openings().filter(team_id__in=listings().values('pk')),pk=pk)
    if TeamMembership.objects.filter(team=opening.team,user=request.user,active=True,deleted_at__isnull=True).exists():
        messages.info(request,'你已在这个团队中。'); return redirect('team_listing',pk=opening.team_id)
    profile=ApplicantProfile.objects.filter(user=request.user).first()
    form=ApplicationForm(request.POST or None,initial={'resume':(profile.skills+'\n\n'+profile.introduction).strip(),'portfolio':profile.portfolio} if profile else {})
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                Team.objects.filter(pk=opening.team_id).update(active=F('active'))
                if not listings().filter(pk=opening.team_id).exists():
                    raise ValidationError('团队已停止招募或人数已达上限。')
                opening.refresh_from_db()
                if not available_openings().filter(pk=opening.pk).exists():
                    raise ValidationError('该招聘已暂停或招满。')
                old=TeamApplication.objects.select_for_update().filter(opening=opening,applicant=request.user).first()
                if old and old.state in ('pending','accepted'):raise IntegrityError
                if old:
                    if old.invite_id:Invite.all_objects.filter(pk=old.invite_id,used_at__isnull=True).update(revoked_at=timezone.now())
                    for key,value in form.cleaned_data.items():setattr(old,key,value)
                    old.state='pending';old.invite=None;old.reviewed_by=None;old.review_note='';old.save()
                else:old=TeamApplication.objects.create(opening=opening,applicant=request.user,**form.cleaned_data)
                from .models import AccountNotice
                if opening.team.owner_id:
                    AccountNotice.objects.create(user_id=opening.team.owner_id,application=old,title='收到职位申请：'+opening.title,body=old.note or '对方已投递资料。',target_url='/messages/teams/review/?team='+str(opening.team_id))
                AccountNotice.objects.create(user=request.user,application=old,title='申请已发送：'+opening.title,body='团队审核后，进度将显示在这段私信中。',target_url='/team-square/applications/')
        except ValidationError as error:
            form.add_error(None,' '.join(error.messages))
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
        if action=='join':
            team_id=TeamApplication.objects.filter(pk=pk,applicant=request.user).values_list('opening__team_id',flat=True).first()
            Team.objects.filter(pk=team_id).update(active=F('active'))
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
                lock_opening(item.opening)
                team=join_from_invitation(request.user,invite=Invite.all_objects.filter(pk=item.invite_id).first())
            except ValidationError as error:
                messages.error(request,' '.join(error.messages))
            else:
                item.state='joined';item.save(update_fields=['state','updated_at'])
                finish_opening(item.opening)
                from .models import AccountNotice
                AccountNotice.objects.filter(application=item,user=request.user,read_at__isnull=True).update(read_at=timezone.now())
                if item.reviewed_by_id:
                    AccountNotice.objects.create(user_id=item.reviewed_by_id,application=item,title='申请人已确认加入 '+team.name,body='对方已加入团队，可在团队成员中查看。')
                request.session['message-team']=team.pk
                return redirect('/messages/teams/?team='+str(team.pk))
        else: raise PermissionDenied
    return redirect('my_applications')


@login_required
def review(request):
    require(request,'recruitment')
    fresh_code=None
    if request.method=='POST':
        if not valid_id(request.POST.get('application','')): raise PermissionDenied
        with transaction.atomic():
            from .team_permissions import require_hr_locked
            require_hr_locked(request,request.team)
            TeamApplication.objects.filter(pk=request.POST['application'],opening__team=request.team,state='pending').update(state=F('state'))
            item=get_object_or_404(TeamApplication.objects.select_for_update(),pk=request.POST.get('application'),opening__team=request.team,state='pending')
            action=request.POST.get('action')
            if action not in ('accept','reject'): raise PermissionDenied
            item.state='accepted' if action=='accept' else 'rejected'
            item.reviewed_by=request.user;item.review_note=request.POST.get('review_note','').strip()[:500]
            if action=='accept':
                from .admission import admit_member
                try:
                    lock_opening(item.opening)
                    if TeamMembership.objects.filter(team=item.opening.team,user=item.applicant,active=True,deleted_at__isnull=True,role__in=['owner','admin','member']).exists():raise ValidationError('申请人已在团队中，不能再次计入招聘人数。')
                    admit_member(item.applicant,item.opening.team)
                except ValidationError as error:
                    messages.error(request,' '.join(error.messages));return redirect('team_application_review')
                item.state='joined'
            item.save()
            if action=='accept':finish_opening(item.opening)
            from .models import AccountNotice
            AccountNotice.objects.create(user=item.applicant,application=item,
                title=item.opening.team.name+(' 通过了你的申请' if action=='accept' else ' 已完成申请审核'),
                body='申请已通过，你已加入团队。' if action=='accept' else item.review_note or '此次申请未通过。', target_url='/messages/teams/?team='+str(item.opening.team_id) if action=='accept' else '/discover/applications/')
            messages.success(request,'审核已保存，申请通过后直接加入团队，并已发送通知。')
    return render(request,'core/team_applications.html',{'review_mode':True,'fresh_code':fresh_code,
        'applications':page(request,TeamApplication.objects.filter(opening__team=request.team).select_related('opening','applicant'))})
