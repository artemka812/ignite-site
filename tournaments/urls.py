from django.urls import include, path
from . import views

urlpatterns = [
    path('', include('tournaments.community_urls')),
    path('', views.home, name='home'),
    path('tournaments/', views.tournament_list, name='tournament_list'),
    path('tournaments/new/', views.tournament_create, name='tournament_create'),
    path('tournaments/<slug:slug>/', views.tournament_detail, name='tournament_detail'),
    path('tournaments/<slug:slug>/edit/', views.tournament_edit, name='tournament_edit'),
    path('tournaments/<slug:slug>/manage/', views.tournament_manage, name='tournament_manage'),
    path('tournaments/<slug:slug>/actions/', views.tournament_action, name='tournament_action'),
    path('tournaments/<slug:slug>/apply/', views.tournament_apply, name='tournament_apply'),
    path('tournaments/<slug:slug>/entries/<int:pk>/', views.entry_action, name='entry_action'),
    path('matches/', views.match_list, name='match_list'),
    path('calendar/', views.match_calendar, name='match_calendar'),
    path('matches/<int:pk>/', views.match_detail, name='match_detail'),
    path('matches/<int:pk>/edit/', views.match_edit, name='match_edit'),
    path('matches/<int:pk>/pair/', views.match_pair_edit, name='match_pair_edit'),
    path('matches/<int:pk>/confirm/', views.match_confirm, name='match_confirm'),
    path('matches/<int:pk>/streams/new/', views.match_stream_add, name='match_stream_add'),
    path('matches/<int:pk>/state/', views.match_state, name='match_state'),
    path('streams/', views.live_streams, name='live_streams'),
    path('streams/<int:pk>/edit/', views.stream_edit, name='stream_edit'),
    path('previews/', views.previews, name='previews'),
    path('previews/<slug:page>/', views.previews, name='preview_detail'),
]
