from datetime import datetime,time,timedelta
from decimal import Decimal
from django.contrib.auth.models import User
from django.db.models import Sum,Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from core import permissions as perms
from .permissions import is_pool_owner,visible_budget
from .models import Call
from .service import summary,week_now


def activity(user,team=False):
    today=timezone.localdate(); first=today-timedelta(days=364)
    start=timezone.make_aware(datetime.combine(first,time.min))
    end=timezone.make_aware(datetime.combine(today+timedelta(days=1),time.min))
    calls=Call.objects.filter(created_at__gte=start,created_at__lt=end)
    if not team: calls=calls.filter(user=user)
    rows={row['day']:row for row in calls.annotate(day=TruncDate('created_at')).values('day').annotate(
        input=Sum('input_tokens'),output=Sum('output_tokens'),count=Count('pk'),cost=Sum('cost_cny'))}
    days=[]
    for offset in range(365):
        day=first+timedelta(days=offset); row=rows.get(day,{})
        days.append({'day':str(day),'tokens':(row.get('input') or 0)+(row.get('output') or 0),
            'calls':row.get('count',0),'cost':str(row.get('cost') or Decimal('0'))})
    return {'days':days,'total_tokens':sum(d['tokens'] for d in days),'first':str(first),'last':str(today)}


def dashboard(user,team=False):
    team=bool(team and is_pool_owner(user))
    today=timezone.localdate(); first=today-timedelta(days=6)
    start=timezone.make_aware(datetime.combine(first,time.min))
    calls=Call.objects.filter(created_at__gte=start)
    if not team: calls=calls.filter(user=user)
    grouped={row['day']:row for row in calls.annotate(day=TruncDate('created_at')).values('day').annotate(
        cost=Sum('cost_cny'),input=Sum('input_tokens'),output=Sum('output_tokens'),count=Count('pk'))}
    days=[]
    for offset in range(7):
        day=first+timedelta(days=offset); row=grouped.get(day,{})
        days.append({'day':str(day),'label':day.strftime('%m-%d'),'cost':str(row.get('cost') or Decimal('0')),
            'tokens':(row.get('input') or 0)+(row.get('output') or 0),'calls':row.get('count',0)})
    models=[]
    for row in calls.values('model__provider__name','model__label','model__model_id').annotate(
            cost=Sum('cost_cny'),input=Sum('input_tokens'),output=Sum('output_tokens')).order_by('-cost')[:8]:
        models.append({'label':row['model__provider__name']+' / '+(row['model__label'] or row['model__model_id']),
            'cost':str(row['cost'] or Decimal('0')),'tokens':(row['input'] or 0)+(row['output'] or 0)})
    accounts=[]
    if team:
        week_start=timezone.make_aware(datetime.combine(week_now(),time.min))
        totals={row['user_id']:row for row in Call.objects.filter(created_at__gte=week_start).values('user_id').annotate(
            cost=Sum('cost_cny'),input=Sum('input_tokens'),output=Sum('output_tokens'))}
        for member in User.objects.filter(is_active=True).order_by('username'):
            if not perms.is_team_member(member): continue
            allowance=summary(member); total=totals.get(member.pk,{})
            accounts.append({'id':member.pk,'name':member.username,'budget':allowance,'enabled':member.api_allowance.enabled,
                'cost':str(total.get('cost') or Decimal('0')),'tokens':(total.get('input') or 0)+(total.get('output') or 0)})
    return {'budget':visible_budget(user),'scope':'team' if team else 'mine','days':days,'models':models,'members':accounts,'activity':activity(user,team),
        'total_cost':str(sum(Decimal(day['cost']) for day in days)),
        'total_tokens':sum(day['tokens'] for day in days),'total_calls':sum(day['calls'] for day in days)}
