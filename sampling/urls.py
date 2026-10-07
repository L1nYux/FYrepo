from django.urls import path

from . import views

app_name = "sampling"

urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.run_new, name="new"),
    path("import-bundle/", views.bundle_import, name="bundle_import"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.run_edit, name="edit"),
    path("<int:pk>/clone/", views.run_clone, name="clone"),
    path("<int:pk>/candidates/import/", views.candidate_import, name="candidate_import"),
    path("<int:pk>/review/", views.review_apply, name="review_apply"),
    path("<int:pk>/freeze/", views.run_freeze, name="freeze"),
    path("<int:pk>/artifacts/<int:artifact_pk>/download/", views.artifact_download, name="artifact_download"),
    path("<int:pk>/experiment/new/", views.create_experiment, name="create_experiment"),
    path("<int:pk>/agent/config/", views.agent_config, name="agent_config"),
    path("<int:pk>/agent/import/", views.agent_import, name="agent_import"),
    path("<int:pk>/agent/pdf-config/", views.agent_pdf_config, name="agent_pdf_config"),
    path("<int:pk>/documents/upload/", views.document_upload, name="document_upload"),
    path("<int:pk>/documents/convert/", views.document_convert, name="document_convert"),
    path("<int:pk>/documents/status/", views.document_status, name="document_status"),
    path("<int:pk>/documents/bundle/", views.document_bundle_download, name="document_bundle"),
    path("<int:pk>/documents/manifest/", views.pdf_manifest_template, name="pdf_manifest"),
    path("<int:pk>/documents/<int:document_pk>/<str:kind>/", views.document_download, name="document_download"),
    path("<int:pk>/agent/pdf-report/", views.agent_pdf_report, name="agent_pdf_report"),
]
