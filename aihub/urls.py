from django.urls import path
from . import views

urlpatterns=[
    path('api-pool/',views.pool,name='api_pool'),
    path('api-pool/manage/',views.manage,name='api_manage'),
    path('api-pool/providers/<int:pk>/quota/',views.provider_quota,name='api_provider_quota'),
    path('api-pool/discover/',views.discover_models,name='api_discover'),
    path('api-pool/enable-models/',views.enable_models,name='api_enable_models'),
    path('api-pool/model-price/',views.update_model_price,name='api_model_price'),
    path('api-pool/catalog/',views.catalog,name='api_catalog'),
    path('api-pool/usage/',views.usage_summary,name='api_usage'),
    path('api-pool/preferences/',views.preferences,name='api_preferences'),
    path('assistant/',views.assistant,name='ai_assistant'),
    path('assistant/start/',views.assistant_start,name='ai_start'),
    path('assistant/conversations/',views.assistant_conversations,name='ai_conversations'),
    path('assistant/conversations/<int:pk>/',views.assistant_conversation,name='ai_conversation'),
    path('assistant/jobs/<uuid:pk>/',views.assistant_job,name='ai_job'),
    path('assistant/references/',views.references,name='ai_references'),
    path('api/pool/v1/models',views.api_models,name='pool_models'),
    path('api/pool/v1/experiments',views.api_experiments,name='pool_experiments'),
    path('api/pool/v1/chat/completions',views.api_chat,name='pool_chat'),
]
