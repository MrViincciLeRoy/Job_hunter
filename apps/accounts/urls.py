from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/",                           views.login_view,           name="login"),
    path("logout/",                          views.logout_view,          name="logout"),
    path("onboarding/",                      views.onboarding_view,      name="onboarding"),
    path("onboarding/extract-cv/",           views.extract_cv_view,      name="extract_cv"),
    path("profile/",                         views.profile_view,         name="profile"),
    path("documents/",                       views.documents_view,       name="documents"),
    path("documents/<int:doc_id>/download/", views.document_download,    name="doc_download"),
    path("documents/<int:doc_id>/delete/",   views.document_delete,      name="doc_delete"),
    path("documents/<int:doc_id>/primary/",  views.document_set_primary, name="doc_primary"),
    path("photo/",                           views.photo_view,           name="user_photo"),

    path("experience/add/",            views.experience_save,   name="experience_add"),
    path("experience/<int:pk>/edit/",  views.experience_save,   name="experience_edit"),
    path("experience/<int:pk>/delete/",views.experience_delete, name="experience_delete"),

    path("education/add/",             views.education_save,    name="education_add"),
    path("education/<int:pk>/edit/",   views.education_save,    name="education_edit"),
    path("education/<int:pk>/delete/", views.education_delete,  name="education_delete"),

    path("skills/add/",                views.skill_save,        name="skill_add"),
    path("skills/<int:pk>/edit/",      views.skill_save,        name="skill_edit"),
    path("skills/<int:pk>/delete/",    views.skill_delete,      name="skill_delete"),

    path("languages/add/",             views.language_save,     name="language_add"),
    path("languages/<int:pk>/edit/",   views.language_save,     name="language_edit"),
    path("languages/<int:pk>/delete/", views.language_delete,   name="language_delete"),

    path("references/add/",            views.reference_save,    name="reference_add"),
    path("references/<int:pk>/edit/",  views.reference_save,    name="reference_edit"),
    path("references/<int:pk>/delete/",views.reference_delete,  name="reference_delete"),

    path("links/add/",                 views.social_link_save,  name="link_add"),
    path("links/<int:pk>/edit/",       views.social_link_save,  name="link_edit"),
    path("links/<int:pk>/delete/",     views.social_link_delete,name="link_delete"),
]
