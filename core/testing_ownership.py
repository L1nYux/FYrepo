"""Explicit ownership for existing fixtures created in the original team."""
from urllib.parse import parse_qsl, urlencode
from django.test import Client
from django.urls import resolve, Resolver404
from .models import Workspace


class TeamFixtureClient(Client):
    def request(self, **request):
        try:
            name = resolve(request.get('PATH_INFO', '/')).url_name
        except Resolver404:
            name = None
        scoped = {'project_new', 'competition_new', 'experiment_new', 'task_new',
                  'finance_list', 'finance_new', 'claim_list', 'claim_new',
                  'api_pool', 'api_manage', 'api_discover', 'api_enable_models',
                  'api_model_price', 'api_catalog', 'api_usage', 'api_preferences',
                  'api_provider_quota', 'ai_assistant', 'ai_start', 'ai_conversations',
                  'ai_upload_image', 'ai_references', 'ai_web_preview'}
        if name in scoped:
            query = dict(parse_qsl(request.get('QUERY_STRING', '')))
            if 'ownership' not in query:
                space = Workspace.objects.get_or_create(team_id=1, defaults={'kind':'team'})[0]
                query['ownership'] = str(space.pk)
                request['QUERY_STRING'] = urlencode(query)
        return super().request(**request)
