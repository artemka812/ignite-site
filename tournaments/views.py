from django.http import Http404
from django.shortcuts import render

from .data import TEAMS, TOURNAMENTS, matches_for


def home(request):
    featured = TOURNAMENTS[0]
    return render(request, "home.html", {
        "active_page": "home", "tournaments": TOURNAMENTS,
        "featured": featured, "final": matches_for(featured)[2],
    })


def tournament_list(request):
    query = request.GET.get("q", "").strip()
    game = request.GET.get("game", "")
    status = request.GET.get("status", "")
    tournaments = [
        t for t in TOURNAMENTS
        if (not query or query.casefold() in (t["name"] + " " + t["subtitle"]).casefold())
        and (not game or t["game"] == game)
        and (not status or t["status"] == status)
    ]
    return render(request, "tournament_list.html", {
        "active_page": "tournaments", "tournaments": tournaments,
        "query": query, "game": game, "status": status,
    })


def tournament_detail(request, slug):
    tournament = next((t for t in TOURNAMENTS if t["slug"] == slug), None)
    if tournament is None:
        raise Http404("Турнир не найден")
    return render(request, "tournament_detail.html", {
        "active_page": "tournaments", "tournament": tournament,
        "teams": TEAMS, "matches": matches_for(tournament),
    })
