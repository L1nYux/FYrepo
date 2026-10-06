from django.urls import path

from . import views, portal, messages, competitions, chat_references, recovery, experiment_runs, social, releases, member_management
from .desktop_api import desktop_api
from .avatars import member_avatar
from . import teams
from . import account_registration
from aihub import gifts

urlpatterns = [
    path('account/register/', account_registration.register, name='account_register'),
    path('teams/', teams.index, name='teams'),
    path('teams/create/', teams.create, name='team_create'),
    path('teams/switch/', teams.switch, name='team_switch'),
    path('teams/join/', teams.join, name='team_join'),
    path('teams/transfer/', teams.transfer, name='team_transfer'),
    path('platform/', teams.platform, name='platform'),
    path('desktop/api/<str:action>/', desktop_api, name='desktop_api'),
    path('updates/current/', releases.current, name='release_current'),
    path('download/', portal.download, name='public_download'),
    path('competitions/', competitions.index, name='competitions'),
    path('competitions/new/', competitions.edit, name='competition_new'),
    path('competitions/<int:pk>/', competitions.detail, name='competition_detail'),
    path('competitions/<int:pk>/edit/', competitions.edit, name='competition_edit'),
    path('competitions/<int:pk>/archive/', competitions.archive, name='competition_archive'),
    path('messages/', messages.hub, name='messages_hub'),
    path('messages/poll/', messages.poll, name='messages_poll'),
    path('messages/unread/', messages.unread, name='messages_unread'),
    path('messages/read/', messages.read, name='messages_read'),
    path('messages/manage/', messages.manage, name='messages_manage'),
    path('messages/history/', messages.search_history, name='messages_history'),
    path('members/<int:pk>/card/', social.member, name='member_card'),
    path('members/<int:pk>/reset-password/', member_management.reset_password, name='member_reset_password'),
    path('members/<int:pk>/delete/', member_management.delete_account, name='member_delete'),
    path('account/set-password/', member_management.set_password, name='required_password_change'),
    path('messages/stickers/', social.stickers, name='stickers'),
    path('messages/stickers/<int:pk>/file/', social.sticker_file, name='sticker_file'),
    path('messages/points/', gifts.wallet, name='point_wallet'),
    path('messages/points/send/', gifts.send, name='point_gift_send'),
    path('messages/points/<uuid:pk>/', gifts.detail, name='point_gift_detail'),
    path('messages/points/<uuid:pk>/claim/', gifts.claim, name='point_gift_claim'),
    path('messages/<int:pk>/action/', messages.message_action, name='message_action'),
    path('messages/references/search/', chat_references.search, name='chat_reference_search'),
    path('messages/references/<str:kind>/<int:pk>/', chat_references.detail, name='chat_reference_detail'),
    path('messages/to/<int:peer_pk>/', messages.hub, name='messages_private'),
    path('messages/to/<int:peer_pk>/poll/', messages.poll, name='messages_private_poll'),
    path('public/experiment-files/<int:pk>/', portal.public_experiment_file, name='public_experiment_file'),
    path('workspace/', portal.workspace_home, name='workspace_home'),
    path('public/projects/', portal.public_projects, name='public_projects'),
    path('public/projects/<int:pk>/', portal.public_project_detail, name='public_project_detail'),
    path('public/experiments/', portal.public_experiments, name='public_experiments'),
    path('public/experiments/<int:pk>/', portal.public_experiment_detail, name='public_experiment_detail'),
    path('public/members/', portal.public_members, name='public_members'),
    path('contact/', portal.public_members, name='contact'),  # 与成员公开信息合并为同一页
    path('manage/contact/', portal.contact_edit, name='contact_edit'),
    path('workspace/announcements/new/', portal.announcement_edit, name='announcement_new'),
    path('workspace/announcements/<int:pk>/edit/', portal.announcement_edit, name='announcement_edit'),
    path('experiments/', portal.experiments, name='experiments'),
    path('experiments/new/', portal.experiment_edit, name='experiment_new'),
    path('experiments/compare/', portal.experiments_compare, name='experiments_compare'),
    path('experiments/templates/<int:pk>/delete/', portal.experiment_template_delete, name='experiment_template_delete'),
    path('experiments/<int:pk>/', portal.experiment_detail, name='experiment_detail'),
    path('experiments/<int:pk>/edit/', portal.experiment_edit, name='experiment_edit'),
    path('experiments/<int:pk>/runs/new/', experiment_runs.edit, name='experiment_run_new'),
    path('experiments/<int:pk>/runs/<int:run_pk>/edit/', experiment_runs.edit, name='experiment_run_edit'),
    path('experiments/<int:pk>/visibility/', portal.experiment_visibility, name='experiment_visibility'),
    path('projects/<int:pk>/visibility/', portal.project_visibility, name='project_visibility'),
    path('account/public/', portal.public_profile_edit, name='public_profile_edit'),
    path('recycle-bin/', portal.recycle_bin, name='recycle_bin'),
    path('recycle-bin/<str:kind>/<int:pk>/restore/', portal.restore, name='restore'),
    path('recycle-bin/<str:kind>/<int:pk>/delete/', portal.permanently_delete, name='permanently_delete'),

    path('', portal.public_home, name='public_home'),
    path('projects/', views.dashboard, name='dashboard'),

    # 项目展示 · 关于 · 聊天室
    path('showcase/', portal.public_projects, name='showcase'),
    path('about/', portal.public_members, name='about'),
    path('chat/', views.chat, name='chat'),
    path('chat/public/', views.chat_public, name='chat_public'),
    path('chat/public/messages/', views.chat_public_messages, name='chat_public_messages'),
    path('chat/developers/', views.chat_developers, name='chat_developers'),
    path('chat/developers/messages/', views.chat_developers_messages, name='chat_developers_messages'),

    # 登录（先选身份：管理员／开发者／普通用户）
    path('login/', views.RoleLoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),

    # 忘记密码：邮箱自助找回。URL 名沿用 Django 约定，令牌与邮件模板都依赖它们。
    path('account/forgot/', recovery.recover, name='password_reset'),
    path('account/forgot/sent/', recovery.legacy_code, name='password_reset_done'),
    path('account/reset/<uidb64>/<token>/', views.ResetPasswordConfirmView.as_view(),
         name='password_reset_confirm'),
    path('account/reset/done/', views.ResetPasswordCompleteView.as_view(), name='password_reset_complete'),


    # 个人中心：资料、角色权限与修改密码（旧改密链接跳到同一页）
    path('account/', views.profile, name='profile'),
    path('accounts/<int:pk>/avatar/<str:version>/', member_avatar, name='member_avatar'),
    path('account/password/', views.change_password, name='change_password'),

    # 已登录但忘了当前密码：邮箱验证码验证身份后重置（先验证码，再设新密码）
    path('account/forgot-code/', recovery.legacy_code, name='password_code_reset'),
    path('account/forgot-code/send/', recovery.legacy_code, name='password_code_send'),
    path('account/forgot-code/new-password/', recovery.legacy_code,
         name='password_code_new_password'),


    # 项目（项目 → 母任务 → 子任务）
    path('projects/new/', views.project_edit, name='project_new'),
    path('projects/<int:pk>/', views.project_detail, name='project_detail'),
    path('projects/<int:pk>/edit/', views.project_edit, name='project_edit'),
    path('projects/<int:pk>/close/', views.project_close, name='project_close'),
    path('projects/<int:pk>/archive/', views.project_archive, name='project_archive'),
    path('projects/<int:pk>/submit/', views.project_submit, name='project_submit'),
    path('projects/<int:pk>/comment/', views.project_comment, name='project_comment'),

    # 任务
    path('tasks/', views.task_list, name='task_list'),
    path('tasks/new/', views.task_edit, name='task_new'),
    path('tasks/<int:pk>/', views.task_detail, name='task_detail'),
    path('tasks/<int:pk>/edit/', views.task_edit, name='task_edit'),
    path('tasks/<int:pk>/progress/', views.task_progress, name='task_progress'),
    path('tasks/<int:pk>/submit/', views.task_submit, name='task_submit'),
    path('tasks/<int:pk>/comment/', views.task_comment, name='task_comment'),
    path('tasks/<int:pk>/close/', views.task_close, name='task_close'),
    path('tasks/<int:pk>/archive/', views.task_archive, name='task_archive'),

    # 成果与附件
    path('submissions/<int:pk>/review/', views.submission_review, name='submission_review'),
    path('submissions/<int:pk>/final/', views.submission_final, name='submission_final'),
    path('submissions/<int:pk>/comment/', views.submission_comment, name='submission_comment'),
    path('attachments/<int:pk>/download/', views.attachment_download, name='attachment_download'),

    # 人员：邀请码与成员任免
    path('manage/', views.team_manage, name='team_manage'),
    path('manage/invites/', views.invites, name='invites'),
    path('manage/members/', views.members, name='members'),

    # 财务：报销申请与团队账本合并在一页（旧报销链接跳到同一页的报销区）
    path('finance/', views.finance_list, name='finance_list'),
    path('finance/new/', views.finance_edit, name='finance_new'),
    path('finance/<int:pk>/edit/', views.finance_edit, name='finance_edit'),
    path('finance/<int:pk>/void/', views.finance_void, name='finance_void'),
    path('finance/<int:pk>/delete/', views.finance_archive, name='finance_archive'),
    path('claims/<int:pk>/delete/', views.claim_archive, name='claim_archive'),
    path('finance/claims/', views.claim_list, name='claim_list'),
    path('finance/claims/new/', views.claim_new, name='claim_new'),
    path('finance/claims/<int:pk>/review/', views.claim_review, name='claim_review'),
]
