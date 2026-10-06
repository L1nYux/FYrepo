from . import permissions as perms
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from aihub.service import callable_experiments
from .models import ExperimentRun, attach_files
from .forms import MultipleFileField


class RunForm(forms.ModelForm):
    files = MultipleFileField(label='数据与输出文件', required=False)
    class Meta:
        model = ExperimentRun
        fields = ('title', 'status', 'parameters', 'result')
        widgets = {'parameters': forms.Textarea(attrs={'rows': 4}), 'result': forms.Textarea(attrs={'rows': 7})}


@login_required
def edit(request, pk, run_pk=None):
    experiment = get_object_or_404(callable_experiments(request.user), pk=pk)
    run = get_object_or_404(ExperimentRun, pk=run_pk, experiment=experiment) if run_pk else None
    if run and not (perms.is_admin(request) or run.created_by_id == request.user.pk or experiment.created_by_id == request.user.pk):
        raise PermissionDenied
    form = RunForm(request.POST or None, request.FILES or None, instance=run)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            value = form.save(commit=False)
            value.experiment = experiment
            if not run: value.created_by = request.user
            value.save()
            files = attach_files('experiment', experiment, form.cleaned_data['files'], request.user)
            value.attachments.add(*files)
        messages.success(request, '运行记录已保存。')
        return redirect('/experiments/'+str(pk)+'/?tab=runs')
    return render(request, 'core/experiment_run_form.html', {'form': form, 'experiment': experiment})
