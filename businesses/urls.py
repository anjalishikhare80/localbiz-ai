from django.urls import path

from . import views

app_name = "businesses"
urlpatterns = [
    path("create/", views.BusinessCreateView.as_view(), name="create"),
    path("switch/", views.SwitchBusinessView.as_view(), name="switch"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("team/", views.TeamListView.as_view(), name="team"),
    path("team/add/", views.MemberAddView.as_view(), name="member_add"),
    path("team/<int:pk>/edit/", views.MemberEditView.as_view(), name="member_edit"),
]
