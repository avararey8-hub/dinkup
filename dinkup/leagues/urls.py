from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", views.signup, name="signup"),

    # Admin
    path("dashboard/", views.dashboard, name="dashboard"),
    path("leagues/new/", views.league_create, name="league_create"),
    path("leagues/<int:pk>/", views.league_manage, name="league_manage"),
    path("leagues/<int:pk>/edit/", views.league_edit, name="league_edit"),
    path("leagues/<int:pk>/delete/", views.league_delete, name="league_delete"),
    path("leagues/<int:pk>/do/<str:action>/", views.league_action, name="league_action"),
    path("leagues/<int:pk>/players/add/", views.players_add, name="players_add"),
    path("leagues/<int:pk>/players/<int:player_id>/remove/", views.player_remove, name="player_remove"),
    path("leagues/<int:pk>/players/<int:player_id>/reset-pin/", views.player_reset_pin, name="player_reset_pin"),
    path("leagues/<int:pk>/players/pair/", views.pair_players, name="pair_players"),
    path("leagues/<int:pk>/teams/<int:team_id>/split/", views.team_split, name="team_split"),
    path("leagues/<int:pk>/coadmins/add/", views.coadmin_add, name="coadmin_add"),
    path("leagues/<int:pk>/coadmins/<int:user_id>/remove/", views.coadmin_remove, name="coadmin_remove"),
    path("leagues/<int:pk>/qr/<str:kind>.svg", views.qr_code, name="qr_code"),

    # Players & spectators
    path("j/<str:code>/", views.join_league, name="join_league"),
    path("w/<str:code>/", views.watch, name="watch"),
    path("play/<int:pk>/", views.player_home, name="player_home"),
    path("play/<int:pk>/leave/", views.player_leave, name="player_leave"),
    path("match/<int:match_id>/score/", views.submit_score, name="submit_score"),
    path("league/<int:pk>/board/", views.board, name="board"),

    # AI assistant
    path("league/<int:pk>/coach/", views.assistant_page, name="assistant"),
    path("league/<int:pk>/coach/ask/", views.assistant_ask, name="assistant_ask"),
]
