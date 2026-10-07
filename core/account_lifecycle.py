"""Account actions are platform-wide; organization records are never cascaded."""
import io
import json
import zipfile
from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import F, Q, FileField
from django.http import HttpResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from .models import MemberProfile, Team, TeamMembership, ChatGroup, GroupMember, Workspace, PlatformAudit
from .tenancy import TeamScopedModel


def can_manage(viewer):
    user=getattr(viewer,'user',viewer)
    return bool(user.is_authenticated and user.is_active and (user.is_superuser or user.has_perm('core.manage_platform_accounts')))


def revoke(user):
    from aihub.models import MemberToken, AssistantJob
    from .models import UserPresence, EmailVerificationCode
    MemberToken.all_objects.filter(user=user,revoked_at__isnull=True).update(revoked_at=timezone.now())
    UserPresence.all_objects.filter(user=user).delete()
    EmailVerificationCode.objects.filter(user=user,used_at__isnull=True).update(used_at=timezone.now())
    MemberProfile.objects.filter(user=user).update(security_version=F('security_version')+1)
    AssistantJob.all_objects.filter(user=user,state='running').update(cancel_requested=True)


def close_account(user,actor,reason=''):
    if Team.objects.filter(owner=user,active=True).exists():
        raise ValidationError('请先交接或解散你拥有的团队，再注销账号。')
    if ChatGroup.objects.filter(owner=user,active=True,members__active=True).exists():
        raise ValidationError('请先交接你拥有的群聊，再注销账号。')
    profile,_=MemberProfile.objects.get_or_create(user=user)
    if profile.deleted_at:raise ValidationError('账号已注销。')
    revoke(user)
    TeamMembership.objects.filter(user=user).update(active=False,deleted_at=timezone.now())
    GroupMember.objects.filter(user=user).update(active=False)
    Workspace.objects.filter(owner=user).update(active=False)
    from aihub.models import Provider
    from aihub.service import remove_keys
    identifiers=list(Provider.all_objects.filter(workspace__owner=user).values_list('pk',flat=True))
    Provider.all_objects.filter(pk__in=identifiers).update(enabled=False)
    transaction.on_commit(lambda: remove_keys(identifiers))
    profile.refresh_from_db()
    profile.deleted_at=timezone.now();profile.nickname='已注销用户';profile.legacy_login_allowed=False
    profile.avatar='';profile.must_change_password=False;profile.save()
    user.email='';user.first_name='';user.last_name='';user.is_active=False
    user.set_unusable_password();user.save()
    from .models import PublicProfile
    PublicProfile.objects.filter(user=user).update(is_public=False,display_name='',research_area='',bio='')
    PlatformAudit.objects.create(actor=actor,target=user,action='self_close' if actor.pk==user.pk else 'close',reason=reason)


class CloseForm(forms.Form):
    password=forms.CharField(label='当前密码',widget=forms.PasswordInput)
    confirm=forms.CharField(label='输入“注销”确认')


@login_required
@never_cache
@sensitive_post_parameters('password')
def close(request):
    form=CloseForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        if form.cleaned_data['confirm']!='注销' or not request.user.check_password(form.cleaned_data['password']):
            form.add_error(None,'确认文字或密码不正确。')
        else:
            try:
                with transaction.atomic():
                    user=User.objects.select_for_update().get(pk=request.user.pk)
                    # Recheck the current credential after obtaining the account lock.
                    if not user.is_active or not user.check_password(form.cleaned_data['password']):raise ValidationError('账号状态已变化，请重新登录。')
                    close_account(user,user)
            except ValidationError as error:form.add_error(None,error)
            else:
                logout(request);messages.success(request,'账号已注销，团队历史记录保留。');return redirect('login')
    return render(request,'core/account_close.html',{'form':form})


@login_required
@never_cache
def export(request):
    space=Workspace.objects.get_or_create(owner=request.user,defaults={'kind':'personal'})[0]
    content={'account':{'workbench_id':request.user.member_profile.workbench_id,'email':request.user.email},'records':{}}
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for model in apps.get_models():
            if not issubclass(model,TeamScopedModel) or model._meta.app_label not in ('core','aihub') or model.__name__=='MemberToken':continue
            rows=list(model.all_objects.filter(workspace=space))
            safe=[]
            for row in rows:
                values={}
                for field in model._meta.fields:
                    if field.name in ('digest','secret','api_key','key_env'):continue
                    value=getattr(row,field.attname)
                    if isinstance(field, FileField):
                        values[field.name]=str(value)
                        if value and value.storage.exists(value.name):
                            with value.open('rb') as file:archive.writestr('files/'+str(row._meta.label_lower)+'/'+str(row.pk)+'/'+field.name,file.read())
                    else:values[field.name]=value
                safe.append(values)
            content['records'][model._meta.label_lower]=safe
        from .personal_messages import thread_rows
        from .models import PersonalMessage, GroupMessage, MessageUpload, FriendRequest, Friendship
        personal=PersonalMessage.objects.filter(Q(sender=request.user)|Q(recipient=request.user)).exclude(hidden_by=request.user)
        content['relationships']={
            'friends':list(Friendship.objects.filter(Q(first=request.user)|Q(second=request.user)).values('first_id','second_id')),
            'requests':list(FriendRequest.objects.filter(Q(sender=request.user)|Q(recipient=request.user)).values('sender_id','recipient_id','state','note','created_at')),
        }
        retained=[]
        peers=(set(personal.values_list('sender_id',flat=True))|set(personal.values_list('recipient_id',flat=True)))-{request.user.pk}
        for peer in peers:
            try:rows,_,_,_=thread_rows(request,peer,False)
            except (PermissionDenied, Http404):continue
            retained.extend(rows.filter(withdrawn_at__isnull=True).exclude(legacy_message__withdrawn_at__isnull=False))
        content['personal_messages']=[{'id':m.pk,'sender_id':m.sender_id,'recipient_id':m.recipient_id,'body':m.body,'quote':m.quote,'sticker_id':m.sticker_id,'references':m.references,'created_at':m.created_at} for m in retained]
        groups=ChatGroup.objects.filter(team__isnull=True,active=True,members__user=request.user,members__active=True)
        group_rows=[]
        for group in groups:
            rows,_,_,_=thread_rows(request,group.pk,True)
            group_rows.extend(rows.filter(withdrawn_at__isnull=True))
        content['groups']=list(groups.values('id','name','owner_id','announcement'))
        content['group_messages']=[{'id':m.pk,'group_id':m.group_id,'author_id':m.author_id,'body':m.body,'quote':m.quote,'sticker_id':m.sticker_id,'references':m.references,'created_at':m.created_at} for m in group_rows]
        uploads=MessageUpload.objects.filter(Q(personal_id__in=[m.pk for m in retained])|Q(message_id__in=[m.pk for m in group_rows]))
        for upload in uploads:
            if upload.file and upload.file.storage.exists(upload.file.name):
                with upload.file.open('rb') as file:archive.writestr('messages/'+str(upload.pk)+'/'+upload.original_name,file.read())
        content['message_files']=list(uploads.values('id','personal_id','message_id','original_name'))
        for row in retained:
            if not row.legacy_message_id:continue
            for attachment in row.legacy_message.attachments.all():
                if attachment.file and attachment.file.storage.exists(attachment.file.name):
                    with attachment.file.open('rb') as file:
                        archive.writestr('legacy-messages/'+str(row.pk)+'/'+str(attachment.pk)+'/'+attachment.original_name,file.read())
        archive.writestr('个人数据.json',json.dumps(content,cls=DjangoJSONEncoder,ensure_ascii=False,indent=2))
    response=HttpResponse(buffer.getvalue(),content_type='application/zip')
    response['Content-Disposition']='attachment; filename="zhiyu-personal-data.zip"'
    return response


@login_required
def platform_accounts(request):
    if not can_manage(request):raise PermissionDenied('需要软件账号管理权限。')
    if request.method=='POST':
        action=request.POST.get('action');reason=request.POST.get('reason','').strip()[:500]
        if action not in ('ban','unban','close','grant_developer','revoke_developer') or not reason:raise PermissionDenied('请填写操作原因。')
        with transaction.atomic():
            target=get_object_or_404(User.objects.select_for_update(),pk=request.POST.get('user'))
            if action in ('grant_developer','revoke_developer'):
                if not request.user.is_superuser or target.is_superuser or target.pk==request.user.pk or not target.is_active:raise PermissionDenied
                permissions=Permission.objects.filter(content_type__app_label='core',codename__in=['manage_platform_accounts','manage_team_admission'])
                if action=='grant_developer':target.user_permissions.add(*permissions)
                else:target.user_permissions.remove(*permissions)
                PlatformAudit.objects.create(actor=request.user,target=target,action=action,reason=reason)
                return redirect('platform_accounts')
            if target.pk==request.user.pk or target.is_superuser or can_manage(target) and not request.user.is_superuser:raise PermissionDenied('需要由软件所有者处理此管理账号。')
            if action=='close':
                try:close_account(target,request.user,reason)
                except ValidationError as error:messages.error(request,' '.join(error.messages))
            else:
                if getattr(getattr(target,'member_profile',None),'deleted_at',None):raise PermissionDenied('已注销账号不能恢复。')
                MemberProfile.objects.get_or_create(user=target)
                revoke(target);target.is_active=action=='unban';target.save(update_fields=['is_active'])
                PlatformAudit.objects.create(actor=request.user,target=target,action=action,reason=reason)
        return redirect('platform_accounts')
    from .pagination import page
    query=request.GET.get('q','').strip()[:150]
    accounts=User.objects.select_related('member_profile').order_by('pk')
    if query:accounts=accounts.filter(Q(username__icontains=query)|Q(member_profile__nickname__icontains=query)|Q(member_profile__workbench_id__icontains=query)|Q(email__icontains=query))
    accounts=page(request,accounts)
    for account in accounts:
        account.software_manager=can_manage(account)
        account.can_manage_account=(account.pk!=request.user.pk and not account.is_superuser and not getattr(getattr(account,'member_profile',None),'deleted_at',None) and (request.user.is_superuser or not account.software_manager))
    return render(request,'core/platform_accounts.html',{'accounts':accounts,'account_query':query})


@login_required
@never_cache
@require_GET
def platform_audit(request):
    if not can_manage(request):raise PermissionDenied('需要软件账号管理权限。')
    from .pagination import page
    labels={'ban':'封禁账号','unban':'解封账号','close':'注销账号','grant_developer':'授予软件管理身份','revoke_developer':'撤销软件管理身份','reset_password':'重置密码'}
    rows=page(request,PlatformAudit.objects.select_related('actor','target'))
    for row in rows:row.action_label=labels.get(row.action,'账号操作')
    return render(request,'core/platform_audit.html',{'account_events':rows})


@login_required
@never_cache
@sensitive_variables('temporary')
def reset_password(request,pk):
    import secrets
    from datetime import timedelta
    if not can_manage(request):raise PermissionDenied('需要独立的软件账号管理权限。')
    target=get_object_or_404(User,pk=pk)
    if target.pk==request.user.pk or target.is_superuser or can_manage(target) and not request.user.is_superuser or getattr(getattr(target,'member_profile',None),'deleted_at',None):raise PermissionDenied
    temporary=None
    if request.method=='POST':
        if request.POST.get('confirm')!='reset':
            messages.error(request,'请确认密码重置操作。')
        else:
          with transaction.atomic():
            target=User.objects.select_for_update().get(pk=pk)
            if target.is_superuser or can_manage(target) and not request.user.is_superuser or getattr(getattr(target,'member_profile',None),'deleted_at',None):raise PermissionDenied
            revoke(target)
            temporary=secrets.token_urlsafe(18);target.set_password(temporary);target.save(update_fields=['password'])
            MemberProfile.objects.update_or_create(user=target,defaults={'must_change_password':True,'temporary_password_expires_at':timezone.now()+timedelta(hours=24)})
            PlatformAudit.objects.create(actor=request.user,target=target,action='reset_password',reason='生成一次性临时密码')
    response=render(request,'core/member_reset_password.html',{'target':target,'temporary_password':temporary,'platform_reset':True})
    response['Referrer-Policy']='same-origin'
    return response
