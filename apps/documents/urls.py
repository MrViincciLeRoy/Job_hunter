from django.urls import path
from apps.documents import views

urlpatterns = [
    path("",                          views.documents_list,   name="documents_list"),
    path("upload/",                   views.upload_document,  name="upload_document"),
    path("<int:doc_id>/delete/",      views.delete_document,  name="delete_document"),
    path("<int:doc_id>/set-active/",  views.set_active,       name="set_document_active"),
    path("<int:doc_id>/download/",    views.download_document, name="download_document"),
]