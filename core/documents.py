"""In-app documents with approved drafts and explicit publication review."""
import json
from functools import wraps
from pathlib import Path
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F, Q
from django.http import FileResponse, JsonResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from . import document_permissions as access, document_content as content
from .models import SharedDocument, DocumentVersion, DocumentDraft, DocumentAccess, DocumentEditRequest, DocumentComment, DocumentImage, OfficeEditingSession, AccountNotice
from .pagination import page


def handled(view):
    @wraps(view)
    def wrapped(request,*args,**kwargs):
        try:return view(request,*args,**kwargs)
        except (ValidationError,ValueError,TypeError,json.JSONDecodeError) as error:
            detail=' '.join(error.messages) if isinstance(error,ValidationError) else '请求内容无效。'
            return JsonResponse({'error':detail},status=400)
        except PermissionDenied as error:
            return JsonResponse({'error':str(error) or '权限已失效。'},status=403)
    return wrapped


def get_document(request, pk):
    return get_object_or_404(access.visible(request.user),pk=pk)


def lock_document(request,pk):
    # Acquire SQLite's writer lock before reading; publication and grants serialize.
    SharedDocument.objects.filter(pk=pk).update(updated_at=F('updated_at'))
    return get_document(request,pk)


def notice(document,user,title,body='',draft=None):
    if user.is_active:
        AccountNotice.objects.create(user=user,title=title,body=body[:1000],target_url=reverse('document_detail',args=[document.pk])+(f'?draft={draft.pk}' if draft else ''))


def reviewers(document):
    ids={document.created_by_id}
    if document.workspace.owner_id:ids.add(document.workspace.owner_id)
    else:
        from .models import TeamMembership
        ids.update(TeamMembership.objects.filter(team_id=document.workspace.team_id,active=True,deleted_at__isnull=True,role__in=['owner','admin']).values_list('user_id',flat=True))
        project=access.related_project(document)
        if project:ids.add(project.owner_id)
    ids.update(document.access.filter(active=True,role='reviewer').values_list('user_id',flat=True))
    return [user for user in get_user_model().objects.filter(pk__in=ids,is_active=True) if access.reviewer(user,document)]


def context_target(request):
    from .models import Project, Task, Experiment, Competition
    from .resource_navigation import records
    supplied=[(kind,request.POST.get(kind) or request.GET.get(kind)) for kind in ('project','task','competition','experiment')]
    supplied=[(kind,value) for kind,value in supplied if value]
    if len(supplied)>1:raise PermissionDenied('请选择一个文档归属。')
    if not supplied:return None,None
    kind,value=supplied[0]
    if not str(value).isascii() or not str(value).isdigit() or len(str(value))>18:raise PermissionDenied('归属无效。')
    model={'project':Project,'task':Task,'experiment':Experiment,'competition':Competition}[kind]
    target=get_object_or_404(records(model,request,filtered=False),pk=value)
    if getattr(target,'archived_at',None) or kind=='task' and target.project.archived_at:raise PermissionDenied('归属已归档。')
    return kind,target


class DocumentForm(forms.Form):
    title=forms.CharField(label='文档名称',max_length=200,required=False)
    kind=forms.ChoiceField(label='类型',choices=SharedDocument._meta.get_field('kind').choices)
    purpose=forms.ChoiceField(label='用途',choices=SharedDocument._meta.get_field('purpose').choices)
    file=forms.FileField(label='导入文件（可选）',required=False,widget=forms.FileInput(attrs={'accept':'.docx,.xlsx,.pdf'}))

    def clean(self):
        data=super().clean()
        upload=data.get('file')
        if upload:
            kind=Path(upload.name).suffix.lower().lstrip('.')
            if kind not in ('docx','xlsx','pdf'):self.add_error('file','请选择 Word、Excel 或 PDF 文件。')
            else:data['kind']=kind
            if not data.get('title'):data['title']=Path(upload.name).stem[:200]
        if not data.get('title'):self.add_error('title','请填写文档名称。')
        return data


def validate_file(upload,kind):
    import zipfile
    if upload.size>20*1024*1024:raise ValidationError('文件不能超过 20 MB。')
    if Path(upload.name).suffix.lower()!='.'+kind:raise ValidationError('文件类型与所选类型不一致。')
    try:
        if kind=='pdf':
            from pypdf import PdfReader
            reader=PdfReader(upload)
            if reader.is_encrypted:raise ValidationError('请上传未加密的 PDF。')
        else:
            with zipfile.ZipFile(upload) as archive:
                infos=archive.infolist()
                if len(infos)>10000 or sum(x.file_size for x in infos)>100*1024*1024:raise ValidationError('文件解压后过大。')
                expected='word/document.xml' if kind=='docx' else 'xl/workbook.xml'
                if expected not in archive.namelist() or any('vbaproject' in x.filename.lower() for x in infos):raise ValidationError('文档格式无效或包含宏。')
    except ValidationError:raise
    except Exception:raise ValidationError('文件损坏或不是有效的文档。') from None
    finally:upload.seek(0)
    return upload


def blank_office(kind):
    from io import BytesIO
    stream=BytesIO()
    if kind=='docx':
        from docx import Document
        Document().save(stream)
    else:
        from openpyxl import Workbook
        Workbook().save(stream)
    return ContentFile(stream.getvalue(),name='新文档.'+kind)


@login_required
@never_cache
def index(request):
    rows=access.visible(request.user,archived=request.GET.get('view')=='trash')
    kind,target=context_target(request)
    if target:rows=rows.filter(**{kind:target})
    ownership=request.GET.get('ownership','all')
    if ownership!='all':
        from .resource_navigation import spaces
        if not str(ownership).isdigit() or not spaces(request.user).filter(pk=ownership).exists():raise PermissionDenied
        rows=rows.filter(workspace_id=ownership)
    query=request.GET.get('q','').strip()[:150]
    if query:rows=rows.filter(title__icontains=query)
    purpose=request.GET.get('purpose','')
    if purpose in ('plan','notes','result'):rows=rows.filter(purpose=purpose)
    documents=page(request,rows)
    if request.GET.get('view')=='trash':
        for document in documents:document.can_restore=access.manager(request.user,document,archived=True)
    return render(request,'core/documents.html',{'documents':documents,'document_context':target,'document_context_kind':kind,'query':query,'document_purpose':purpose,'document_trash':request.GET.get('view')=='trash'})


@login_required
def create(request):
    from .resource_navigation import create_spaces,spaces
    from .collaboration import participates
    kind,target=context_target(request)
    choices=create_spaces(request,'documents')
    selected=target.workspace if target else spaces(request.user).get(kind='personal')
    if not target and request.method=='POST' and request.POST.get('ownership'):
        selected=next((space for space in choices if str(space.pk)==request.POST['ownership']),None)
        if not selected:raise PermissionDenied
    if target and selected.kind=='team' and not access.member(request.user,type('Doc',(),{'workspace':selected})()) and not (kind in ('project','task') and participates(request.user,target if kind=='project' else target.project)):
        raise PermissionDenied('需要创建文档的授权。')
    form=DocumentForm(request.POST or None,request.FILES or None,initial={'kind':request.GET.get('kind','online'),'purpose':request.GET.get('purpose','plan') if target else 'notes'})
    if request.method=='POST' and form.is_valid():
        try:
            if not target:
                selected=next((space for space in choices if str(space.pk)==request.POST.get('ownership')),selected)
                if request.POST.get('ownership') and str(selected.pk)!=request.POST['ownership']:raise PermissionDenied
            upload=form.cleaned_data['file'];document_kind=form.cleaned_data['kind']
            if upload:validate_file(upload,document_kind)
            elif document_kind=='pdf':raise ValidationError('PDF 需要导入文件。')
            elif document_kind!='online':upload=blank_office(document_kind)
            with transaction.atomic():
                document=SharedDocument.objects.create(workspace=selected,created_by=request.user,title=form.cleaned_data['title'],kind=document_kind,purpose=form.cleaned_data['purpose'],**({kind:target} if target else {}))
                version=DocumentVersion.objects.create(document=document,number=1,content=content.EMPTY,file=upload or '',created_by=request.user,approved_by=request.user,summary='创建文档')
                document.current=version;document.save(update_fields=['current'])
                if not access.manager(request.user,document):DocumentAccess.objects.create(document=document,user=request.user,role='editor',granted_by=request.user,membership_required=False,project_required=True)
            return redirect('document_detail',pk=document.pk)
        except ValidationError as error:form.add_error(None,error)
    from .office_documents import configured
    return render(request,'core/document_form.html',{'form':form,'document_context':target,'document_context_kind':kind,'creation_spaces':choices,'selected_document_space':selected,'office_available':configured()})


@login_required
@never_cache
@handled
def detail(request,pk):
    document=get_document(request,pk);draft=None
    if request.GET.get('draft'):
        draft=get_object_or_404(DocumentDraft,document=document,pk=request.GET['draft'])
        if not access.draft_visible(request.user,draft):raise Http404
    version=document.current
    if request.GET.get('version'):
        version=get_object_or_404(DocumentVersion,document=document,pk=request.GET['version'])
    comments=document.comments.filter(draft=draft) if draft else document.comments.filter(draft__isnull=True,version=version)
    payload={'content':draft.content if draft else version.content,'editable':bool(draft and access.draft_editable(request.user,draft)),
        'generation':draft.generation if draft else 0,'draft':draft.pk if draft else None,'kind':document.kind,
        'document':document.pk,'csrf':'','save':reverse('document_save',args=[pk,draft.pk]) if draft else '',
        'state':reverse('document_state',args=[pk]),'image':reverse('document_image_upload',args=[pk]),
        'file':reverse('document_file',args=[pk])+('?draft='+str(draft.pk) if draft else '?version='+str(version.pk))}
    from .office_documents import configured
    import difflib
    def revision_text(row):
        if document.kind=='online':return content.text(row.content)
        if document.kind=='docx':
            from .document_planning import source_text
            return source_text(row)
        return ''
    difference=''
    if draft and document.kind in ('online','docx'):
        try:difference='\n'.join(difflib.unified_diff(revision_text(document.current).splitlines(),revision_text(draft).splitlines(),fromfile='当前正式版',tofile='修改稿',lineterm=''))
        except (ValidationError,OSError):difference='暂时无法提取文字差异，请对照文档内容。'
    return render(request,'core/document_detail.html',{'document':document,'document_version':version,'draft':draft,'document_payload':payload,
        'document_diff':difference,
        'can_document_edit':access.editor(request.user,document),'can_document_review':access.reviewer(request.user,document),'can_document_manage':access.manager(request.user,document),
        'can_document_comment':access.commenter(request.user,document),'document_comments':comments.select_related('author'),
        'document_versions':document.versions.all()[:30],'document_drafts':document.drafts.exclude(state='draft').select_related('author')[:30],
        'own_draft':document.drafts.filter(author=request.user,state__in=['draft','submitted','changes_requested']).first(),
        'edit_requests':document.edit_requests.filter(state='pending').select_related('user') if access.reviewer(request.user,document) else [],
        'access_list':document.access.select_related('user') if access.manager(request.user,document) else [],'office_available':configured(),
        'document_conflict':bool(draft and draft.base_id!=document.current_id)})


@login_required
@never_cache
@handled
def state(request,pk):
    document=get_document(request,pk)
    value={'version':document.current_id,'can_edit':access.editor(request.user,document)}
    if request.GET.get('draft'):
        draft=get_object_or_404(DocumentDraft,document=document,pk=request.GET['draft'])
        if not access.draft_visible(request.user,draft):raise Http404
        value.update(generation=draft.generation,state=draft.state,editable=access.draft_editable(request.user,draft))
        session=draft.office_sessions.filter(user=request.user,closed=False,expires_at__gt=timezone.now()).last()
        if session:value['save_completed']=str(session.save_completed or '')
    return JsonResponse(value)


@login_required
@require_POST
@handled
def action(request,pk):
    with transaction.atomic():
        operation=request.POST.get('action')
        if operation=='restore':
            SharedDocument.objects.filter(pk=pk).update(updated_at=F('updated_at'))
            document=get_object_or_404(access.visible(request.user,archived=True),pk=pk)
        else:document=lock_document(request,pk)
        if operation=='request':
            if access.editor(request.user,document):return redirect('document_detail',pk=pk)
            reason=request.POST.get('reason','').strip()[:500] or '申请参与修改'
            row,created=DocumentEditRequest.objects.get_or_create(document=document,user=request.user,state='pending',defaults={'reason':reason})
            if created:
                for user in reviewers(document):notice(document,user,'有人申请修改文档',reason)
        elif operation=='draft':
            if document.kind=='pdf':raise ValidationError('PDF 用于阅读与引用，请在原始 Word 或在线文档中修改。')
            if not access.editor(request.user,document):raise PermissionDenied('请先申请并获得修改权限。')
            draft=document.drafts.filter(author=request.user,state__in=['draft','submitted','changes_requested']).first()
            if not draft:draft=DocumentDraft.objects.create(document=document,author=request.user,base=document.current,content=document.current.content,file=document.current.file.name)
            return redirect(reverse('document_detail',args=[pk])+f'?draft={draft.pk}')
        elif operation in ('approve_request','reject_request'):
            if not access.reviewer(request.user,document):raise PermissionDenied
            row=get_object_or_404(DocumentEditRequest,document=document,pk=request.POST.get('request'),state='pending')
            if not access.visible(row.user).filter(pk=pk).exists():raise ValidationError('申请人已无权访问文档。')
            row.state='approved' if operation=='approve_request' else 'rejected';row.reviewed_by=request.user;row.save()
            if row.state=='approved':
                existing=access.grant(row.user,document)
                project_required=bool(access.related_project(document) and not access.member(row.user,document) and (not existing or existing.project_required))
                DocumentAccess.objects.update_or_create(document=document,user=row.user,defaults={'role':'editor','active':True,'membership_required':access.member(row.user,document),'project_required':project_required,'granted_by':request.user})
            notice(document,row.user,'文档修改申请'+('已批准' if row.state=='approved' else '未通过'),document.title)
        elif operation in ('grant','revoke'):
            if not access.manager(request.user,document):raise PermissionDenied
            # Resolve a known account identifier, without exposing arbitrary account lists.
            from .identity import login_user
            user=login_user(request.POST.get('account',''))
            if user and not user.is_active:user=None
            if not user:raise ValidationError('没有找到这个工作台号。')
            if operation=='revoke':
                document.access.filter(user=user).update(active=False)
                OfficeEditingSession.objects.filter(draft__document=document,user=user).update(closed=True)
            else:
                role=request.POST.get('role','viewer')
                if role not in ('viewer','commenter','editor','reviewer'):raise ValidationError('权限无效。')
                DocumentAccess.objects.update_or_create(document=document,user=user,defaults={'role':role,'active':True,'membership_required':access.member(user,document),'project_required':False,'granted_by':request.user})
                notice(document,user,'文档已与你共享',document.title)
        elif operation in ('archive','restore'):
            if operation=='restore':
                document.archived_at=None
                document.save(update_fields=['archived_at'])
            if not access.manager(request.user,document):raise PermissionDenied
            document.archived_at=timezone.now() if operation=='archive' else None;document.save(update_fields=['archived_at'])
            OfficeEditingSession.objects.filter(draft__document=document).update(closed=True)
            return redirect('documents')
        else:raise ValidationError('操作无效。')
    return redirect('document_detail',pk=pk)


@login_required
@require_POST
@handled
def save(request,pk,draft_pk):
    data=json.loads(request.body)
    if not isinstance(data,dict):raise ValidationError('文档内容无效。')
    with transaction.atomic():
        document=lock_document(request,pk);draft=get_object_or_404(DocumentDraft,document=document,pk=draft_pk)
        if document.kind!='online' or not access.draft_editable(request.user,draft):raise PermissionDenied('修改稿已提交或编辑权限已失效。')
        if type(data.get('generation')) is not int or data['generation']!=draft.generation:
            return JsonResponse({'error':'另一处已保存新的修改，请保留当前内容后重新打开。','conflict':True},status=409)
        draft.content=content.clean(data.get('content'),pk);draft.generation+=1;draft.save(update_fields=['content','generation','updated_at'])
    return JsonResponse({'generation':draft.generation,'saved':True})


@login_required
@require_POST
@handled
def review(request,pk,draft_pk):
    with transaction.atomic():
        document=lock_document(request,pk);draft=get_object_or_404(DocumentDraft,document=document,pk=draft_pk)
        operation=request.POST.get('action');generation=request.POST.get('generation')
        if not generation or str(draft.generation)!=generation:return JsonResponse({'error':'修改稿版本已变化，请重新检查。'},status=409)
        if operation in ('submit','resume','rebase'):
            if draft.author_id!=request.user.pk or not access.editor(request.user,document):raise PermissionDenied
            if operation=='submit':
                if not access.draft_editable(request.user,draft):raise ValidationError('这份修改稿已经提交。')
                summary=request.POST.get('summary','').strip()
                if not summary or len(summary)>500:raise ValidationError('请简要说明本次修改。')
                if draft.base_id!=document.current_id:raise ValidationError('正式版已更新，请先对照新版本调整修改稿。')
                if document.kind in ('docx','xlsx'):
                    nonce=request.POST.get('office_save')
                    session=draft.office_sessions.filter(user=request.user,expires_at__gt=timezone.now(),closed=False).last()
                    if not nonce or not session or str(session.save_requested)!=nonce or str(session.save_completed)!=nonce or session.generation!=draft.generation:raise ValidationError('请先等待文档保存完成，再提交审核。')
                draft.state='submitted';draft.summary=summary
                OfficeEditingSession.objects.filter(draft=draft).update(closed=True)
                for user in reviewers(document):notice(document,user,'文档修改待审核',summary,draft)
            elif operation=='resume':
                if draft.state!='submitted':raise ValidationError('修改稿状态已变化。')
                draft.state='draft'
            else:
                if not access.draft_editable(request.user,draft):raise PermissionDenied
                if request.POST.get('confirm')!='1':raise ValidationError('请确认已对照最新正式版保留所需修改。')
                draft.base=document.current
            draft.save()
        else:
            if not access.reviewer(request.user,document) or draft.state!='submitted':raise PermissionDenied
            if draft.author_id==request.user.pk and not access.manager(request.user,document):raise PermissionDenied('请由其他审核人审核你的修改。')
            note=request.POST.get('note','').strip()
            if len(note)>1000:raise ValidationError('审核说明过长。')
            if operation=='accept':
                if str(document.current_id)!=request.POST.get('base') or document.current_id!=draft.base_id:return JsonResponse({'error':'正式版已更新，需要重新对照和提交。','conflict':True},status=409)
                version=DocumentVersion.objects.create(document=document,number=document.current.number+1,content=draft.content,file=draft.file.name,created_by=draft.author,approved_by=request.user,summary=draft.summary)
                document.current=version;document.save(update_fields=['current','updated_at']);draft.state='merged'
            elif operation in ('changes','reject'):
                if not note:raise ValidationError('请说明需要调整或未采纳的原因。')
                draft.state='changes_requested' if operation=='changes' else 'rejected'
            else:raise ValidationError('审核操作无效。')
            draft.review_note=note;draft.reviewed_by=request.user;draft.save()
            notice(document,draft.author,'文档修改'+draft.get_state_display(),note,draft)
    return redirect(reverse('document_detail',args=[pk])+f'?draft={draft.pk}')


@login_required
@require_POST
@handled
def comment(request,pk):
    with transaction.atomic():
        document=lock_document(request,pk)
        if not access.commenter(request.user,document):raise PermissionDenied('需要评论权限。')
        if request.POST.get('resolve'):
            row=get_object_or_404(DocumentComment,document=document,pk=request.POST['resolve'])
            if row.author_id!=request.user.pk and not access.reviewer(request.user,document):raise PermissionDenied
            row.resolved_at=timezone.now();row.save(update_fields=['resolved_at'])
        else:
            body=request.POST.get('body','').strip();anchor=request.POST.get('anchor','').strip()
            if not body or len(body)>4000 or len(anchor)>300:raise ValidationError('评论内容无效。')
            draft=get_object_or_404(DocumentDraft,document=document,pk=request.POST['draft']) if request.POST.get('draft') else None
            if draft and not access.draft_visible(request.user,draft):raise PermissionDenied
            version=None if draft else get_object_or_404(DocumentVersion,document=document,pk=request.POST.get('version') or document.current_id)
            DocumentComment.objects.create(document=document,draft=draft,version=version,author=request.user,body=body,anchor=anchor)
            for user in reviewers(document):
                if user.pk!=request.user.pk:notice(document,user,'文档有新评论',body,draft)
    return redirect(reverse('document_detail',args=[pk])+('?draft='+request.POST['draft'] if request.POST.get('draft') else '?version='+str(version.pk) if 'version' in locals() and version else ''))


@login_required
@never_cache
def file(request,pk):
    document=get_document(request,pk)
    row=document.current
    if request.GET.get('draft'):
        row=get_object_or_404(DocumentDraft,document=document,pk=request.GET['draft'])
        if not access.draft_visible(request.user,row):raise Http404
    elif request.GET.get('version'):row=get_object_or_404(DocumentVersion,document=document,pk=request.GET['version'])
    if not row.file:raise Http404
    try:response=FileResponse(row.file.open('rb'),as_attachment=request.GET.get('download')=='1',filename=document.title+'.'+document.kind)
    except OSError:raise Http404
    response['Cache-Control']='private, no-store';response['X-Content-Type-Options']='nosniff'
    return response


@login_required
@require_POST
@handled
def image_upload(request,pk):
    document=get_document(request,pk)
    if not access.editor(request.user,document):raise PermissionDenied
    from PIL import Image
    from io import BytesIO
    upload=request.FILES.get('image')
    if not upload or upload.size>5*1024*1024:raise ValidationError('图片不能超过 5 MB。')
    try:
        image=Image.open(upload)
        if image.width*image.height>20000000:raise ValueError
        image.load()
        image.thumbnail((2400,2400));stream=BytesIO();image.convert('RGB').save(stream,format='JPEG',quality=90)
    except Exception:raise ValidationError('图片无效。') from None
    row=DocumentImage.objects.create(document=document,uploaded_by=request.user,file=ContentFile(stream.getvalue(),name='image.jpg'))
    return JsonResponse({'src':reverse('document_image',args=[pk,row.pk])})


@login_required
@never_cache
def image(request,pk,image_pk):
    document=get_document(request,pk);row=get_object_or_404(DocumentImage,document=document,pk=image_pk)
    response=FileResponse(row.file.open('rb'),content_type='image/jpeg');response['Cache-Control']='private, no-store'
    return response
