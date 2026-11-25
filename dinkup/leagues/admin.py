from django.contrib import admin

from .models import League, Match, Player, Team


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ("name", "event_type", "level", "division", "start_date", "join_code", "spectator_code")
    list_filter = ("event_type", "level", "division")


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("name", "league", "team", "self_joined")
    list_filter = ("league",)


admin.site.register(Team)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("league", "stage", "week", "round_number", "court", "score_a", "score_b")
    list_filter = ("league", "stage", "week")
