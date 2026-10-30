"""Recover only known membership intervals; future match snapshots are authoritative.

Older membership records may not describe every historical roster change. Never
infer players whose joining date is unknown or overwrite an existing snapshot.
"""
from django.db import migrations
from django.db.models import Q


def backfill_known_rosters(apps, schema_editor):
    Tournament = apps.get_model('tournaments', 'Tournament')
    Match = apps.get_model('tournaments', 'Match')
    TeamMember = apps.get_model('tournaments', 'TeamMember')
    alias = schema_editor.connection.alias
    tournaments_with_matches = Match.objects.using(alias).values('tournament_id')
    Tournament.objects.using(alias).filter(
        Q(pk__in=tournaments_with_matches) | Q(status__in=['live', 'finished'])
    ).update(registration_open=False)
    for match in Match.objects.using(alias).filter(status__in=['live', 'finished'], participants_snapshot={}):
        if match.scheduled_at is None:
            continue
        snapshot = {}
        for side in ('a', 'b'):
            team_id = getattr(match, f'team_{side}_id')
            snapshot[side] = list(TeamMember.objects.using(alias).filter(
                team_id=team_id,
                status__in=['active', 'left'],
                joined_at__isnull=False,
                joined_at__lte=match.scheduled_at,
            ).filter(Q(left_at__isnull=True) | Q(left_at__gt=match.scheduled_at))
              .order_by('player_id').values_list('player_id', flat=True)) if team_id else []
        Match.objects.using(alias).filter(pk=match.pk, participants_snapshot={}).update(participants_snapshot=snapshot)


class Migration(migrations.Migration):
    dependencies = [('tournaments', '0003_match_is_bye_match_participants_snapshot_and_more')]
    operations = [migrations.RunPython(backfill_known_rosters, migrations.RunPython.noop)]
