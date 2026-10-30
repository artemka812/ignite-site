from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db import transaction

from .forms import AdminMatchForm, AdminUserChangeForm, AdminUserCreationForm
from .models import Match, MatchResultLog, Stream, Team, TeamMember, Tournament, TournamentTeam, User
from . import services

admin.site.site_header = "IGNITE — управление сайтом"
admin.site.site_title = "IGNITE"
admin.site.index_title = "Турниры, команды и пользователи"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = AdminUserChangeForm
    add_form = AdminUserCreationForm
    ordering = ("email",)
    list_display = ("email", "nickname", "role", "is_staff", "is_active")
    search_fields = ("email", "nickname", "game_id")
    list_filter = ("role", "is_staff", "is_active")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Профиль", {"fields": ("nickname", "role", "game_id", "position", "avatar")}),
        ("Доступ", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Даты", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "nickname", "role", "password1", "password2")}),)


class TeamMemberInline(admin.TabularInline):
    model = TeamMember
    extra = 0
    autocomplete_fields = ("player",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "tag", "captain", "color")
    search_fields = ("name", "tag", "captain__nickname")
    autocomplete_fields = ("captain",)
    inlines = (TeamMemberInline,)


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ("player", "team", "status", "joined_at")
    list_filter = ("status", "team")
    search_fields = ("player__nickname", "team__name")
    autocomplete_fields = ("player", "team")


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = ("name", "game", "format", "status", "starts_at", "organizer")
    list_filter = ("game", "format", "status")
    search_fields = ("name", "organizer__email")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("organizer",)
    fieldsets = (
        ("Описание", {"fields": ("name", "slug", "subtitle", "description", "organizer")}),
        ("Проведение", {"fields": ("game", "format", "status", "starts_at", "ends_at", "team_limit", "team_size", "rules")}),
        ("Оформление", {"fields": ("accent", "edition")}),
    )


@admin.register(TournamentTeam)
class TournamentTeamAdmin(admin.ModelAdmin):
    list_display = ("team", "tournament", "status", "seed", "applied_at")
    list_filter = ("status", "tournament")
    search_fields = ("team__name", "tournament__name")
    autocomplete_fields = ("team", "tournament")


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    form = AdminMatchForm
    list_display = ("tournament", "round", "position", "team_a", "team_b", "scheduled_at", "score_a", "score_b", "status")
    list_filter = ("tournament", "status", "round")
    search_fields = ("tournament__name", "team_a__name", "team_b__name")
    autocomplete_fields = ("tournament", "team_a", "team_b", "next_match")

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.tournament.status in ("live", "finished"):
            return ("tournament", "team_a", "team_b", "round", "position", "best_of", "next_match", "next_slot", "is_bye", "participants_snapshot", "scheduled_at")
        return ("participants_snapshot",)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        with transaction.atomic():
            if request.method == "POST" and object_id and object_id.isdecimal():
                tournament_id = Match.objects.filter(pk=object_id).values_list("tournament_id", flat=True).first()
                if tournament_id:
                    Tournament.objects.select_for_update().get(pk=tournament_id)
            return super().changeform_view(request, object_id, form_url, extra_context)

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        old = Match.objects.select_for_update().get(pk=obj.pk) if change else None
        if old and old.tournament.status in ("live", "finished"):
            saved = services.update_result(old, request.user, obj.score_a, obj.score_b, obj.status)
            obj.participants_snapshot = saved.participants_snapshot
            return
        super().save_model(request, obj, form, change)
        old_score = (old.score_a, old.score_b) if old else (None, None)
        if old_score != (obj.score_a, obj.score_b):
            MatchResultLog.objects.create(
                match=obj, changed_by=request.user,
                old_score_a=old_score[0], old_score_b=old_score[1],
                new_score_a=obj.score_a, new_score_b=obj.score_b,
            )


@admin.register(Stream)
class StreamAdmin(admin.ModelAdmin):
    list_display = ("match", "platform", "status")
    list_filter = ("platform", "status")
    search_fields = ("match__tournament__name", "url")
    autocomplete_fields = ("match",)


@admin.register(MatchResultLog)
class MatchResultLogAdmin(admin.ModelAdmin):
    list_display = ("match", "changed_by", "old_score_a", "old_score_b", "new_score_a", "new_score_b", "changed_at")
    list_filter = ("changed_at",)
    search_fields = ("match__tournament__name", "changed_by__nickname")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
