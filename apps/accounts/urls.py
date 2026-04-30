from django.urls import path
from . import views

urlpatterns = [
    path("login/",                          views.login_view,          name="login"),
    path("logout/",                         views.logout_view,         name="logout"),
    path("profile/",                        views.profile_view,        name="profile"),
    path("documents/",                      views.documents_view,      name="documents"),
    path("documents/<int:doc_id>/download/",views.document_download,   name="doc_download"),
    path("documents/<int:doc_id>/delete/",  views.document_delete,     name="doc_delete"),
    path("documents/<int:doc_id>/primary/", views.document_set_primary,name="doc_primary"),
    path("photo/",                          views.photo_view,          name="user_photo"),
]
