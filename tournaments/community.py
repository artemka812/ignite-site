from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from .community_forms import EmailAuthenticationForm, ProfileForm, RegistrationForm, TeamForm
from .models import Match, Team, TeamMember, Tournament, User
from . import services


class EmailLoginView(LoginView):
    template_name = "form.html"
    authentication_form = EmailAuthenticationForm
    next_page = reverse_lazy("dashboard")
    extra_context = {"title": "Вход", "submit_label": "Войти", "description": "Войдите в свой аккаунт IGNITE.", "cancel_url": "/"}


class SiteLogoutView(LogoutView):
    next_page = "/"


def form_page(request, form, title, submit_label="Сохранить", cancel_url="/", description=""):
    return render(request, "form.html", {"form": form, "title": title, "submit_label": submit_label, "cancel_url": cancel_url, "description": description})


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Аккаунт создан. Добро пожаловать!")
        return redirect("dashboard")
    return form_page(request, form, "Создать аккаунт", "Зарегистрироваться")


def player_matches(player):
    return services.player_matches(player)


@login_required
@require_http_methods(["GET", "POST"])
def dashboard(request):
    if request.method == "POST":
        if request.POST.get("action") == "become_organizer":
            User.objects.filter(pk=request.user.pk).update(role=User.Role.ORGANIZER)
            messages.success(request, "Теперь вы можете создавать турниры.")
        else:
            messages.error(request, "Неизвестное действие.")
        return redirect("dashboard")
    memberships = request.user.memberships.select_related("team").all()
    return render(request, "community/dashboard.html", {
        "teams": Team.objects.filter(memberships__player=request.user, memberships__status=TeamMember.Status.ACTIVE),
        "memberships": memberships,
        "invitations": memberships.filter(status=TeamMember.Status.INVITED),
        "organized_tournaments": request.user.organized_tournaments.all(),
        "my_matches": player_matches(request.user).exclude(tournament__status=Tournament.Status.DRAFT).select_related("tournament", "team_a", "team_b"),
    })


@login_required
@require_http_methods(["GET", "POST"])
def profile_edit(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Профиль обновлён.")
        return redirect("player_detail", pk=request.user.pk)
    return form_page(request, form, "Редактировать профиль", cancel_url=reverse("dashboard"))


def team_list(request):
    query = request.GET.get("q", "").strip()[:100]
    teams = Team.objects.select_related("captain").annotate(member_count=Count("memberships", filter=Q(memberships__status=TeamMember.Status.ACTIVE)))
    if query:
        teams = teams.filter(Q(name__icontains=query) | Q(tag__icontains=query))
    return render(request, "community/team_list.html", {"teams": teams, "query": query})


def player_list(request):
    query = request.GET.get("q", "").strip()[:100]
    players = User.objects.filter(is_active=True).order_by("nickname")
    if query:
        players = players.filter(Q(nickname__icontains=query) | Q(game_id__icontains=query))
    return render(request, "community/player_list.html", {"players": players, "query": query})


def player_detail(request, pk):
    player = get_object_or_404(User, pk=pk, is_active=True)
    return render(request, "community/player_detail.html", {
        "player": player, "statistics": services.player_statistics(player),
        "is_archive": player.email.endswith("@archive.ignite.invalid"),
        "memberships": player.memberships.filter(status=TeamMember.Status.ACTIVE).select_related("team"),
        "matches": player_matches(player).exclude(tournament__status=Tournament.Status.DRAFT).select_related("team_a", "team_b", "tournament"),
    })


def can_manage_team(user, team):
    return user.is_authenticated and (user.is_superuser or team.captain_id == user.pk)


def team_detail(request, pk):
    team = get_object_or_404(Team.objects.select_related("captain"), pk=pk)
    can_manage = can_manage_team(request.user, team)
    matches = Match.objects.filter(Q(team_a=team) | Q(team_b=team)).exclude(tournament__status=Tournament.Status.DRAFT).select_related("team_a", "team_b", "tournament")
    return render(request, "community/team_detail.html", {
        "team": team, "members": team.memberships.filter(status=TeamMember.Status.ACTIVE).select_related("player"),
        "requests": team.memberships.filter(status__in=[TeamMember.Status.PENDING, TeamMember.Status.INVITED]).select_related("player") if can_manage else TeamMember.objects.none(),
        "can_manage": can_manage,
        "membership": team.memberships.filter(player=request.user).first() if request.user.is_authenticated else None,
        "statistics": services.team_statistics(team),
        "upcoming_matches": matches.exclude(status=Match.Status.FINISHED),
        "history": matches.filter(status=Match.Status.FINISHED),
    })


@login_required
@require_http_methods(["GET", "POST"])
def team_create(request):
    form = TeamForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            team = form.save(commit=False)
            team.captain = request.user
            team.save()
            TeamMember.objects.create(team=team, player=request.user, status=TeamMember.Status.ACTIVE, joined_at=timezone.now())
        messages.success(request, "Команда создана. Вы её капитан.")
        return redirect("team_detail", pk=team.pk)
    return form_page(request, form, "Создать команду", "Создать", reverse("team_list"))


@login_required
@require_http_methods(["GET", "POST"])
def team_edit(request, pk):
    with transaction.atomic():
        team = get_object_or_404(Team.objects.select_for_update(), pk=pk)
        if not can_manage_team(request.user, team):
            raise PermissionDenied
        form = TeamForm(request.POST or None, instance=team)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, "Команда обновлена.")
            return redirect("team_detail", pk=pk)
    return form_page(request, form, "Редактировать команду", cancel_url=reverse("team_detail", args=[pk]))


def transition(member, allowed, target):
    if member.status not in allowed:
        raise ValidationError("Действие недоступно для текущего статуса участника.")
    member.status = target
    if target == TeamMember.Status.ACTIVE:
        member.joined_at, member.left_at = timezone.now(), None
    elif target == TeamMember.Status.LEFT:
        member.left_at = timezone.now()
    elif target in (TeamMember.Status.PENDING, TeamMember.Status.INVITED):
        member.joined_at, member.left_at = None, None
    member.save()


@login_required
@require_POST
def team_action(request, pk):
    try:
        with transaction.atomic():
            team = get_object_or_404(Team.objects.select_for_update(), pk=pk)
            if team.archive_note:
                raise ValidationError("Это архивная команда. Заявки и изменения состава недоступны.")
            action = request.POST.get("action")
            management = {"invite", "approve", "reject", "remove", "transfer_captain"}
            personal = {"join", "accept_invite", "reject_invite", "leave"}
            if action not in management | personal:
                raise ValidationError("Неизвестное действие.")
            if action in management and not can_manage_team(request.user, team):
                raise PermissionDenied
            if action == "invite":
                matches = User.objects.filter(nickname__iexact=request.POST.get("nickname", "").strip(), is_active=True)
                if matches.count() != 1:
                    raise ValidationError("Игрок с таким ником не найден или ник неоднозначен.")
                player = matches.get()
            elif action in personal:
                player = request.user
            else:
                member_id = request.POST.get("member_id", "")
                player_id = request.POST.get("player_id", "")
                if member_id.isdecimal():
                    player = get_object_or_404(TeamMember, pk=member_id, team=team).player
                elif player_id.isdecimal():
                    player = get_object_or_404(User, pk=player_id)
                else:
                    raise ValidationError("Выберите участника команды.")
            member = team.memberships.filter(player=player).first()
            if action in {"join", "invite"}:
                target = TeamMember.Status.PENDING if action == "join" else TeamMember.Status.INVITED
                if member is None:
                    TeamMember.objects.create(team=team, player=player, status=target)
                else:
                    transition(member, [TeamMember.Status.LEFT, TeamMember.Status.REJECTED], target)
            else:
                if member is None:
                    raise ValidationError("Участник не найден в этой команде.")
                if action in {"accept_invite", "approve"}:
                    source = TeamMember.Status.INVITED if action == "accept_invite" else TeamMember.Status.PENDING
                    transition(member, [source], TeamMember.Status.ACTIVE)
                elif action in {"reject_invite", "reject"}:
                    source = TeamMember.Status.INVITED if action == "reject_invite" else TeamMember.Status.PENDING
                    transition(member, [source], TeamMember.Status.REJECTED)
                elif action in {"leave", "remove"}:
                    if team.captain_id == player.pk:
                        raise ValidationError("Сначала передайте капитанство другому участнику.")
                    transition(member, [TeamMember.Status.ACTIVE], TeamMember.Status.LEFT)
                elif action == "transfer_captain":
                    if member.status != TeamMember.Status.ACTIVE or not player.is_active:
                        raise ValidationError("Капитаном может стать только активный участник.")
                    team.captain = player
                    team.save(update_fields=["captain"])
        messages.success(request, "Готово. Состав команды обновлён.")
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    return redirect("team_detail", pk=pk)
