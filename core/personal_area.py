"""Account-owned tools, independent of the last selected team."""
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import render, redirect
from django.urls import reverse

from .models import FinanceEntry, OUTFLOW_KINDS
from .pagination import page


@login_required
def home(request):
    return render(request, 'core/me.html')


@login_required
def usage(request):
    return redirect(reverse('api_pool') + '?ownership=' + str(request.workspace.pk))


@login_required
def connections(request):
    return redirect(reverse('api_manage') + '?ownership=' + str(request.workspace.pk))


@login_required
def ledger(request):
    # Middleware selects the authenticated person's workspace for every me_ route.
    entries = FinanceEntry.objects.filter(archived_at__isnull=True, voided_at__isnull=True)
    totals = entries.aggregate(
        income=Sum('amount', filter=~Q(kind__in=OUTFLOW_KINDS), default=Decimal('0')),
        outflow=Sum('amount', filter=Q(kind__in=OUTFLOW_KINDS), default=Decimal('0')),
    )
    return render(request, 'core/personal_ledger.html', {
        'entries': page(request, entries.select_related('project').prefetch_related('attachments')),
        'income': totals['income'], 'outflow': totals['outflow'],
        'balance': totals['income'] - totals['outflow'],
    })


@login_required
def team_finance(request):
    from .resource_navigation import spaces
    return render(request, 'core/team_finance.html', {'finance_teams': spaces(request.user).filter(kind='team')})
