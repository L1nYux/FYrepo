from django.contrib import admin
from django.urls import include, path
from core import operations

handler404 = operations.not_found
handler500 = operations.server_error

admin.site.site_header = '科研团队工作台管理'
admin.site.site_title = '科研团队工作台'
admin.site.index_title = '管理'

urlpatterns = [
    path('healthz/', operations.healthz, name='healthz'),
    path('admin/', admin.site.urls),
    path('', include('aihub.urls')),
    path('', include('core.urls')),
]
