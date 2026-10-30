from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("tournaments/", views.tournament_list, name="tournament_list"),
    path("tournaments/<slug:slug>/", views.tournament_detail, name="tournament_detail"),
    path("previews/", views.previews, name="previews"),
    path("previews/<slug:page>/", views.previews, name="preview_detail"),
]
