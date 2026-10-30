"""Изменения пар до старта. Запись результатов выполняется в services.py."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import Match, Tournament
from .services import can_manage_tournament


@transaction.atomic
def change_pairing(match, actor, team_a, team_b):
    tournament = Tournament.objects.select_for_update().get(pk=match.tournament_id)
    if not can_manage_tournament(actor, tournament):
        raise PermissionDenied
    if tournament.status not in (Tournament.Status.DRAFT, Tournament.Status.SOON):
        raise ValidationError("Менять пары можно только до начала турнира.")
    if tournament.format != Tournament.Format.SINGLE or match.round != 1:
        raise ValidationError("Редактируются пары первого раунда олимпийской сетки.")
    if tournament.matches.filter(is_bye=False).exclude(status=Match.Status.PLANNED).exists():
        raise ValidationError("Один из матчей уже начат.")
    approved = set(tournament.entries.filter(status="approved").values_list("team_id", flat=True))
    if not team_a or team_a.pk not in approved or (team_b and team_b.pk not in approved) or team_a == team_b:
        raise ValidationError("Выберите разные принятые команды.")
    first_round = list(tournament.matches.filter(round=1).order_by("position"))
    slots = [team_id for row in first_round for team_id in (row.team_a_id, row.team_b_id)]
    index = next(i for i, row in enumerate(first_round) if row.pk == match.pk) * 2
    for target, value in ((index, team_a.pk), (index + 1, team_b.pk if team_b else None)):
        source = next((i for i, team_id in enumerate(slots) if team_id == value and (i != index if target == index + 1 else True)), None)
        if source is None:
            raise ValidationError("В сетке нет свободного прохода для такой пары.")
        slots[target], slots[source] = slots[source], slots[target]
    if any(slots[i] is None and slots[i + 1] is None for i in range(0, len(slots), 2)):
        raise ValidationError("В каждой паре должна оставаться хотя бы одна команда.")
    for row in first_round:
        position = first_round.index(row) * 2
        row.team_a_id, row.team_b_id = slots[position:position + 2]
        row.is_bye = row.team_a_id is None or row.team_b_id is None
        row.status = Match.Status.FINISHED if row.is_bye else Match.Status.PLANNED
        row.full_clean()
        row.save(update_fields=["team_a", "team_b", "is_bye", "status"])
    # Будущие соперники ещё не играли; после обмена обновляем только проходы.
    for row in tournament.matches.filter(round__gt=1):
        row.team_a = row.team_b = None
        row.save(update_fields=["team_a", "team_b"])
    for row in first_round:
        if row.is_bye and row.next_match_id:
            Match.objects.filter(pk=row.next_match_id).update(**{f"team_{row.next_slot}_id": row.winner.pk})
