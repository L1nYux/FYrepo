"""Personal notifications remain accessible without a team membership."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import AccountNotice
from .pagination import page


@login_required
def inbox(request):
    from .communication import navigation
    items = AccountNotice.objects.filter(user=request.user).select_related('application__opening__team')
    return render(request, 'core/account_notices.html', {**navigation(request), 'account_notices': page(request, items)})


@login_required
@require_POST
def read(request, pk):
    item = get_object_or_404(AccountNotice, user=request.user, pk=pk)
    AccountNotice.objects.filter(pk=item.pk, user=request.user).update(read_at=timezone.now())
    return redirect('account_notices')
