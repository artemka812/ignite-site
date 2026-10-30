from django.urls import path

from . import community

urlpatterns = [
    path("register/", community.register, name="register"),
    path("login/", community.EmailLoginView.as_view(), name="login"),
    path("logout/", community.SiteLogoutView.as_view(), name="logout"),
    path("dashboard/", community.dashboard, name="dashboard"),
    path("profile/edit/", community.profile_edit, name="profile_edit"),
    path("players/", community.player_list, name="player_list"),
    path("players/<int:pk>/", community.player_detail, name="player_detail"),
    path("teams/", community.team_list, name="team_list"),
    path("teams/new/", community.team_create, name="team_create"),
    path("teams/<int:pk>/", community.team_detail, name="team_detail"),
    path("teams/<int:pk>/edit/", community.team_edit, name="team_edit"),
    path("teams/<int:pk>/actions/", community.team_action, name="team_action"),
]
