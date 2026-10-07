from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404,redirect
from django.views.decorators.http import require_POST
from .models import Project,ProjectCollaborator,AccountNotice
from .permissions import require_project_manager


@login_required
@require_POST
def revoke(request,pk):
    project=get_object_or_404(Project.objects,pk=pk,archived_at__isnull=True)
    require_project_manager(request,project)
    value=request.POST.get('user','')
    if not value.isascii() or not value.isdigit() or len(value)>18:raise PermissionDenied
    count=ProjectCollaborator.objects.filter(project=project,user_id=value,active=True).update(active=False)
    if count:AccountNotice.objects.create(user_id=value,title='项目合作授权已结束',body=project.name,target_url='/discover/offers/')
    messages.success(request,'合作授权已结束。')
    return redirect('project_detail',pk=pk)
