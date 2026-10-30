from collections import defaultdict

from django.db.models import Count, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.formats import date_format

from .models import Match, TeamMember, Tournament, TournamentTeam


def public_tournaments():
    return Tournament.objects.exclude(status=Tournament.Status.DRAFT).annotate(
        team_count=Count("entries", filter=Q(entries__status=TournamentTeam.Status.APPROVED)),
    ).order_by("edition", "pk")


def tournament_card(tournament):
    date = timezone.localtime(tournament.starts_at)
    return {
        "slug": tournament.slug, "name": tournament.name,
        "subtitle": tournament.subtitle, "description": tournament.description,
        "game": tournament.game, "game_label": tournament.get_game_display(),
        "format": tournament.format, "format_label": tournament.get_format_display(),
        "date": date_format(date, "j E Y"), "short_date": date_format(date, "j M"),
        "year": date.year, "status": tournament.status,
        "status_label": tournament.get_status_display(), "accent": tournament.accent,
        "edition": f"{tournament.edition:02d}", "team_count": tournament.team_count,
        "team_limit": tournament.team_limit, "team_size": tournament.team_size,
        "rules": tournament.rules.splitlines(),
    }


def team_card(team):
    if team is None:
        return None
    return {"name": team.name, "tag": team.tag, "color": team.color}


def match_card(match, label):
    return {
        "round": label, "best_of": match.best_of,
        "date": timezone.localtime(match.scheduled_at) if match.scheduled_at else None,
        "time": timezone.localtime(match.scheduled_at).strftime("%H:%M") if match.scheduled_at else "Не назначено",
        "a": team_card(match.team_a), "b": team_card(match.team_b),
        "score_a": match.score_a if match.score_a is not None else "—",
        "score_b": match.score_b if match.score_b is not None else "—",
        "status": match.get_status_display(), "status_code": match.status,
        "winner": match.winner.name if match.winner else "",
    }


def home(request):
    tournaments = list(public_tournaments())
    featured = next((t for t in tournaments if t.status == Tournament.Status.LIVE), None)
    featured = featured or (tournaments[0] if tournaments else None)
    final = None
    if featured:
        match = featured.matches.select_related("team_a", "team_b").order_by("-round", "position").first()
        if match:
            final = match_card(match, f"Раунд {match.round}")
    return render(request, "home.html", {
        "active_page": "home", "tournaments": [tournament_card(t) for t in tournaments[:3]],
        "featured": tournament_card(featured) if featured else None, "final": final,
        "tournament_count": len(tournaments),
        "team_count": TournamentTeam.objects.filter(status=TournamentTeam.Status.APPROVED).exclude(tournament__status=Tournament.Status.DRAFT).values("team_id").distinct().count(),
        "game_count": len({t.game for t in tournaments}),
    })


def tournament_list(request):
    query = request.GET.get("q", "").strip()
    game = request.GET.get("game", "")
    status = request.GET.get("status", "")
    tournaments = public_tournaments()
    if query:
        tournaments = tournaments.filter(Q(name__icontains=query) | Q(subtitle__icontains=query))
    if game:
        tournaments = tournaments.filter(game=game)
    if status:
        tournaments = tournaments.filter(status=status)
    return render(request, "tournament_list.html", {
        "active_page": "tournaments", "tournaments": [tournament_card(t) for t in tournaments],
        "query": query, "game": game, "status": status,
    })


def tournament_detail(request, slug):
    tournament = get_object_or_404(public_tournaments(), slug=slug)
    raw_matches = list(tournament.matches.select_related("team_a", "team_b"))
    by_round = defaultdict(list)
    for match in raw_matches:
        by_round[match.round].append(match)
    last_round = max(by_round, default=0)
    has_final = tournament.format == Tournament.Format.SINGLE and len(by_round.get(last_round, [])) == 1
    rounds, matches = [], []
    for number, rows in sorted(by_round.items()):
        if has_final and number == last_round:
            title = "Финал"
        elif has_final and number == last_round - 1:
            title = "Полуфиналы"
        else:
            title = f"Тур {number}" if tournament.format == Tournament.Format.ROUND_ROBIN else f"Раунд {number}"
        cards = [match_card(m, title if len(rows) == 1 else f"{title} · {m.position}") for m in rows]
        rounds.append({"title": title, "matches": cards})
        matches.extend(cards)
    teams = []
    entries = tournament.entries.filter(status=TournamentTeam.Status.APPROVED).select_related("team__captain").prefetch_related(
        Prefetch("team__memberships", queryset=TeamMember.objects.filter(status=TeamMember.Status.ACTIVE).select_related("player"), to_attr="active_members"),
    )
    for entry in entries:
        team = entry.team
        teams.append({**team_card(team), "captain": team.captain.nickname,
                      "players": " · ".join(m.player.nickname for m in team.active_members)})
    winner = raw_matches[-1].winner if has_final and raw_matches else None
    return render(request, "tournament_detail.html", {
        "active_page": "tournaments", "tournament": tournament_card(tournament),
        "teams": teams, "matches": matches, "rounds": rounds,
        "winner": winner if tournament.status == Tournament.Status.FINISHED else None,
    })


PREVIEWS = {
    "register": "Регистрация", "login": "Вход", "player": "Профиль игрока",
    "team": "Профиль команды", "organizer": "Кабинет организатора",
}


def previews(request, page=None):
    if page is not None and page not in PREVIEWS:
        raise Http404("Макет не найден")
    return render(request, "previews.html", {
        "page": page, "preview_title": PREVIEWS.get(page, "Макеты следующих страниц"),
        "previews": PREVIEWS.items(),
    })
