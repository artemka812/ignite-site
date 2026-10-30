"""Tournament operations. Lock the tournament first to serialize changes to its bracket."""
import random

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q

from .models import Match, MatchResultLog, TeamMember, Tournament, TournamentTeam


def can_manage_tournament(user, tournament):
    return bool(user and user.is_authenticated and user.is_active and (
        user.is_superuser or tournament.organizer_id == user.pk
    ))


def _locked_tournament(tournament, actor):
    tournament = Tournament.objects.select_for_update().get(pk=tournament.pk)
    if not can_manage_tournament(actor, tournament):
        raise PermissionDenied("Управлять турниром может только его организатор.")
    return tournament


def _before_start(tournament):
    if tournament.status not in (Tournament.Status.DRAFT, Tournament.Status.SOON):
        raise ValidationError("Турнир уже начался.")


@transaction.atomic
def decide_entry(entry, actor, approve, seed=None):
    tournament = _locked_tournament(entry.tournament, actor)
    _before_start(tournament)
    if tournament.matches.exists():
        raise ValidationError("После построения сетки нельзя менять участников или посев.")
    entry = TournamentTeam.objects.select_for_update().get(pk=entry.pk, tournament=tournament)
    entry.status = TournamentTeam.Status.APPROVED if approve else TournamentTeam.Status.REJECTED
    entry.seed = seed if approve else None
    entry.full_clean()
    entry.save(update_fields=["status", "seed"])
    return entry


@transaction.atomic
def generate_bracket(tournament, actor, seeding="random"):
    tournament = _locked_tournament(tournament, actor)
    _before_start(tournament)
    if tournament.matches.exists():
        raise ValidationError("Сетка уже существует. Существующие матчи сохраняются.")
    entries = list(tournament.entries.filter(status=TournamentTeam.Status.APPROVED).select_related("team").order_by("seed", "id"))
    if not 2 <= len(entries) <= tournament.team_limit:
        raise ValidationError("Для сетки нужны минимум две принятые команды в пределах лимита.")
    if seeding == "random":
        random.shuffle(entries)
    elif seeding == "manual":
        if any(entry.seed is None for entry in entries):
            raise ValidationError("При ручном посеве каждой команде нужен номер.")
    else:
        raise ValidationError("Неизвестный способ посева.")
    teams = [entry.team for entry in entries]
    if tournament.format == Tournament.Format.ROUND_ROBIN:
        rotation = teams + ([None] if len(teams) % 2 else [])
        for round_number in range(1, len(rotation)):
            position = 0
            for i in range(len(rotation) // 2):
                a, b = rotation[i], rotation[-i - 1]
                if a is not None and b is not None:
                    position += 1
                    Match.objects.create(tournament=tournament, round=round_number, position=position, team_a=a, team_b=b)
            rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    elif tournament.format == Tournament.Format.SINGLE:
        size = 1 << (len(teams) - 1).bit_length()
        # Standard seed positions separate the strongest seeds until later rounds.
        order = [1, 2]
        while len(order) < size:
            total = len(order) * 2 + 1
            order = [value for seed in order for value in (seed, total - seed)]
        slots = [teams[seed - 1] if seed <= len(teams) else None for seed in order]
        rounds = size.bit_length() - 1
        following = []
        for round_number in range(rounds, 0, -1):
            current = []
            for index in range(size // (2 ** round_number)):
                kwargs = {}
                if following:
                    kwargs.update(next_match=following[index // 2], next_slot="a" if index % 2 == 0 else "b")
                if round_number == 1:
                    a, b = slots[index * 2:index * 2 + 2]
                    bye = a is None or b is None
                    kwargs.update(team_a=a, team_b=b, is_bye=bye, status=Match.Status.FINISHED if bye else Match.Status.PLANNED)
                match = Match.objects.create(tournament=tournament, round=round_number, position=index + 1, **kwargs)
                if match.is_bye and match.next_match_id:
                    Match.objects.filter(pk=match.next_match_id).update(**{f"team_{match.next_slot}": match.winner})
                current.append(match)
            following = current
    else:
        raise ValidationError("Формат турнира не поддерживается.")
    tournament.registration_open = False
    tournament.save(update_fields=["registration_open"])
    return list(tournament.matches.all())


@transaction.atomic
def start_tournament(tournament, actor):
    tournament = _locked_tournament(tournament, actor)
    _before_start(tournament)
    if not tournament.matches.exists():
        raise ValidationError("Сначала сформируйте сетку.")
    tournament.status = Tournament.Status.LIVE
    tournament.registration_open = False
    tournament.save(update_fields=["status", "registration_open"])
    return tournament


def _snapshot(match):
    if not match.participants_snapshot:
        match.participants_snapshot = {
            side: list(TeamMember.objects.filter(team_id=getattr(match, f"team_{side}_id"), status=TeamMember.Status.ACTIVE).order_by("player_id").values_list("player_id", flat=True))
            for side in ("a", "b")
        }


@transaction.atomic
def update_result(match, actor, score_a, score_b, status="finished"):
    tournament = _locked_tournament(match.tournament, actor)
    if tournament.status not in (Tournament.Status.LIVE, Tournament.Status.FINISHED):
        raise ValidationError("Сначала начните турнир.")
    match = Match.objects.select_for_update().get(pk=match.pk, tournament=tournament)
    if match.is_bye:
        raise ValidationError("Проход без соперника не требует счёта.")
    old_scores = (match.score_a, match.score_b)
    old_status = match.status
    if (score_a, score_b, status) == (*old_scores, old_status):
        return match
    descendant_id = match.next_match_id
    while descendant_id:
        descendant = Match.objects.get(pk=descendant_id)
        if descendant.status != Match.Status.PLANNED or descendant.score_a is not None or descendant.participants_snapshot:
            raise ValidationError("Следующий матч уже начат. Результат предыдущего менять нельзя.")
        descendant_id = descendant.next_match_id
    match.score_a, match.score_b, match.status = score_a, score_b, status
    match.full_clean()
    if status != Match.Status.PLANNED or score_a is not None:
        _snapshot(match)
    match.save(update_fields=["score_a", "score_b", "status", "participants_snapshot"])
    MatchResultLog.objects.create(match=match, changed_by=actor, old_score_a=old_scores[0], old_score_b=old_scores[1], new_score_a=score_a, new_score_b=score_b)
    if match.next_match_id:
        Match.objects.filter(pk=match.next_match_id).update(**{f"team_{match.next_slot}": match.winner})
    if not tournament.matches.exclude(status=Match.Status.FINISHED).exists():
        tournament.status = Tournament.Status.FINISHED
    else:
        tournament.status = Tournament.Status.LIVE
    tournament.save(update_fields=["status"])
    return match


@transaction.atomic
def update_schedule(match, actor, scheduled_at):
    tournament = _locked_tournament(match.tournament, actor)
    match = Match.objects.select_for_update().get(pk=match.pk, tournament=tournament)
    if match.status != Match.Status.PLANNED:
        raise ValidationError("Расписание можно менять только до начала матча.")
    if scheduled_at is not None and not tournament.starts_at <= scheduled_at <= tournament.ends_at:
        raise ValidationError("Время матча должно находиться в пределах дат турнира.")
    match.scheduled_at = scheduled_at
    match.full_clean()
    match.save(update_fields=["scheduled_at"])
    return match


def standings(tournament):
    rows = {entry.team_id: dict(team=entry.team, played=0, wins=0, losses=0, points=0, difference=0, place=0) for entry in tournament.entries.filter(status=TournamentTeam.Status.APPROVED).select_related("team")}
    for match in tournament.matches.filter(status=Match.Status.FINISHED, is_bye=False).select_related("team_a", "team_b"):
        if not match.winner:
            continue
        for side, other in (("a", "b"), ("b", "a")):
            row = rows.get(getattr(match, f"team_{side}_id"))
            if row is None:
                continue
            won = match.winner.pk == row["team"].pk
            row["played"] += 1
            row["wins"] += int(won)
            row["losses"] += int(not won)
            row["points"] += 3 * int(won)
            row["difference"] += getattr(match, f"score_{side}") - getattr(match, f"score_{other}")
    # For knockouts final placement must outweigh number of matches (including byes).
    ranking = {}
    if tournament.format == Tournament.Format.SINGLE:
        for match in tournament.matches.filter(status=Match.Status.FINISHED).select_related("team_a", "team_b"):
            if match.winner:
                ranking[match.winner.pk] = max(ranking.get(match.winner.pk, 0), match.round * 2 + 1)
                for team_id in (match.team_a_id, match.team_b_id):
                    if team_id:
                        ranking[team_id] = max(ranking.get(team_id, 0), match.round * 2)
    result = sorted(rows.values(), key=lambda row: (-ranking.get(row["team"].pk, 0), -row["points"], -row["difference"], row["team"].name))
    for place, row in enumerate(result, 1):
        row["place"] = place
    return result


def _statistics(matches, side_for):
    result = dict(played=0, wins=0, losses=0, maps_won=0, maps_lost=0, win_rate=0, tournaments=0)
    tournament_ids = set()
    for match in matches:
        side = side_for(match)
        if side is None or match.score_a is None or match.score_b is None:
            continue
        other = "b" if side == "a" else "a"
        own, opposite = getattr(match, f"score_{side}"), getattr(match, f"score_{other}")
        result["played"] += 1
        result["wins"] += int(own > opposite)
        result["losses"] += int(own < opposite)
        result["maps_won"] += own
        result["maps_lost"] += opposite
        tournament_ids.add(match.tournament_id)
    result["tournaments"] = len(tournament_ids)
    result["win_rate"] = round(result["wins"] * 100 / result["played"], 1) if result["played"] else 0
    return result


def team_statistics(team):
    matches = Match.objects.filter(Q(team_a=team) | Q(team_b=team), status=Match.Status.FINISHED, is_bye=False).exclude(tournament__status=Tournament.Status.DRAFT)
    return _statistics(matches, lambda match: "a" if match.team_a_id == team.pk else "b")


def player_statistics(user):
    matches = Match.objects.filter(status=Match.Status.FINISHED, is_bye=False).exclude(tournament__status=Tournament.Status.DRAFT).exclude(participants_snapshot={})
    return _statistics(matches, lambda match: next((side for side in ("a", "b") if user.pk in match.participants_snapshot.get(side, [])), None))


def player_matches(user):
    """Keep historical matches tied to the roster captured when play began."""
    historical_ids = [
        match.pk for match in Match.objects.exclude(participants_snapshot={}).only('pk', 'participants_snapshot')
        if any(user.pk in match.participants_snapshot.get(side, []) for side in ('a', 'b'))
    ]
    team_ids = TeamMember.objects.filter(player=user, status=TeamMember.Status.ACTIVE).values_list('team_id', flat=True)
    return Match.objects.filter(
        Q(pk__in=historical_ids) |
        (Q(status=Match.Status.PLANNED, participants_snapshot={}) & (Q(team_a_id__in=team_ids) | Q(team_b_id__in=team_ids)))
    ).distinct()
