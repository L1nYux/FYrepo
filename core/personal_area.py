"""Account-owned tools, independent of the last selected team."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.urls import reverse



@login_required
def home(request):
    return render(request, 'core/me.html')


@login_required
def usage(request):
    return redirect('me_api')


@login_required
def connections(request):
    return api(request)


@login_required
def api(request):
    from aihub.funding import select_team
    selected=select_team(request)
    if not selected:return redirect('ai_assistant')
    return redirect(reverse('api_pool')+'?ownership='+str(selected.pk))


@login_required
def ledger(request, pk=None):
    messages.info(request,'个人手工记账已停用，已有记录仍保留。团队财务请从工作台进入。')
    return redirect('me_home')


@login_required
def team_finance(request):
    from .resource_navigation import spaces
    return render(request, 'core/team_finance.html', {'finance_teams': spaces(request.user).filter(kind='team')})
