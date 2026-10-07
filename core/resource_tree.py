"""Load one authorized project branch without changing the active workspace."""
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from .models import Project, Task
from .resource_navigation import records


@login_required
@require_GET
@never_cache
def branch(request, pk):
    project=get_object_or_404(records(Project,request,filtered=False),pk=pk,archived_at__isnull=True)
    tasks=list(records(Task,request,filtered=False).filter(project=project,archived_at__isnull=True,parent__archived_at__isnull=True).order_by('created_at','pk')[:1001])
    truncated=len(tasks)>1000
    tasks=tasks[:1000]
    children={}
    for task in tasks:children.setdefault(task.parent_id,[]).append(task)
    def link(task):return {'title':task.title,'path':reverse('task_detail',args=[task.pk])}
    return JsonResponse({'project':{'title':project.name,'path':reverse('project_detail',args=[project.pk]),
        'owner':project.workspace.name,'space':str(project.workspace_id),
        'tasks':[{**link(task),'children':[link(child) for child in children.get(task.pk,[])]} for task in children.get(None,[])]},'truncated':truncated})
