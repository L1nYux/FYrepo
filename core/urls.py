from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
    path('account/password/', views.change_password, name='change_password'),
    path('tasks/<int:pk>/', views.task_detail, name='task_detail'),
    path('tasks/new/', views.task_edit, name='task_new'),
    path('tasks/<int:pk>/edit/', views.task_edit, name='task_edit'),
    path('tasks/<int:pk>/archive/', views.task_archive, name='task_archive'),
    path('tasks/<int:pk>/progress/', views.task_progress, name='task_progress'),
    path('tasks/<int:pk>/submit/', views.task_submit, name='task_submit'),
    path('submissions/<int:pk>/review/', views.submission_review, name='submission_review'),
    path('submissions/<int:pk>/download/', views.submission_download, name='submission_download'),
    path('manage/invites/', views.invites, name='invites'),
    path('finance/', views.finance_list, name='finance_list'),
    path('finance/new/', views.finance_edit, name='finance_new'),
    path('finance/<int:pk>/edit/', views.finance_edit, name='finance_edit'),
    path('finance/<int:pk>/void/', views.finance_void, name='finance_void'),
    path('finance/<int:pk>/receipt/', views.finance_receipt, name='finance_receipt'),
    path('audit/', views.audit_list, name='audit_list'),
]
