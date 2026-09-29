from django.contrib import admin
from django.urls import include, path

admin.site.site_header = '科研团队工作台管理'
admin.site.site_title = '科研团队工作台'
admin.site.index_title = '管理'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
]
