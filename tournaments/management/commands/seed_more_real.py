"""Append verified CCT playoffs and public videos without replacing user data."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify

from tournaments.cct_media import VIDEOS
from tournaments.management.commands.seed_real import ARCHIVE_EMAIL
from tournaments.models import Match, Stream, Team, Tournament, TournamentTeam, User

MOSCOW = ZoneInfo('Europe/Moscow')
DATA_PATH = Path(__file__).resolve().parents[2] / 'data_cct_archive.json'


def bracket_rows(event):
    """Recover the tree from the recorded round results and winners, not seeding guesses."""
    source = event['matches']
    if len(source) != 15:
        raise CommandError('Для полного плей-офф нужны 15 результатов.')
    levels = {4: source[:1], 3: source[1:3], 2: source[3:7], 1: source[7:]}
    used = set()
    ordered = []

    def visit(row, round_, position):
        index = source.index(row)
        if index in used:
            raise CommandError('Матч повторяется в сетке.')
        used.add(index)
        ordered.append((round_, position, row))
        if round_ == 1:
            return
        for offset, participant in enumerate((row['a'], row['b'])):
            previous = [match for match in levels[round_ - 1]
                        if (match['a'] if match['score_a'] > match['score_b'] else match['b']) == participant]
            if len(previous) != 1:
                raise CommandError(f'Не найден однозначный предыдущий матч для {participant}.')
            visit(previous[0], round_ - 1, position * 2 - 1 + offset)

    visit(source[0], 4, 1)
    if len(used) != 15 or len({row[key] for row in levels[1] for key in ('a', 'b')}) != 16:
        raise CommandError('Участники или связи плей-офф не совпадают.')
    return sorted(ordered, key=lambda item: item[:2])


class Command(BaseCommand):
    help = 'Добавить ещё 6 реальных плей-офф CCT (90 матчей) и проверенные видео.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        events = json.loads(DATA_PATH.read_text(encoding='utf-8'))
        counts = dict(tournaments=0, teams=0, matches=0, videos=0)
        curator, created = User.objects.get_or_create(email=ARCHIVE_EMAIL, defaults={
            'nickname': 'IGNITE · CCT', 'role': User.Role.ORGANIZER,
        })
        if created:
            curator.set_unusable_password()
            curator.save(update_fields=['password'])
        elif curator.has_usable_password():
            raise CommandError('Архивный адрес занят пользовательским аккаунтом.')

        for event in events:
            ordered = bracket_rows(event)
            year = event['start'][:4]
            slug = f"cct-s2-europe-{event['series']}-{year}-playoffs"
            existing = Tournament.objects.filter(slug=slug).first()
            if existing:
                if existing.organizer_id != curator.pk:
                    raise CommandError(f'Адрес {slug} уже занят другим организатором.')
                continue
            teams = {}
            for index, name in enumerate(sorted({row[key] for _, _, row in ordered for key in ('a', 'b')})):
                team, created = Team.objects.get_or_create(name=name, defaults={
                    'tag': slugify(name).replace('-', '')[:5].upper() or 'TEAM',
                    'captain': curator, 'color': ('lime', 'blue', 'coral', 'violet')[index % 4],
                    'archive_note': (
                        'Справочная карточка участника CCT, не официальный аккаунт команды. '
                        'Исторические составы показаны только там, где подтверждены источником; '
                        'текущий состав и капитан команды здесь не устанавливаются.'
                    ),
                })
                if not created and (team.captain_id != curator.pk or not team.archive_note):
                    raise CommandError(f'Команда {name} существует вне архива; импорт отменён.')
                counts['teams'] += int(created)
                teams[name] = team
            tournament = Tournament(
                name=f"CCT Season 2 Europe Series {event['series']}", slug=slug,
                subtitle=f'{year} · плей-офф · CS2 · тир-2/тир-3',
                description=(
                    'Онлайн-турнир европейской сцены CCT с общим призовым фондом $50 000. '
                    'Здесь представлен полный плей-офф: 16 участников и 15 матчей BO3. '
                    'Швейцарский этап не включён. Даты и результаты сверены с источниками. '
                    'тир-2/тир-3 описывает сцену, а не официальный рейтинг всех участников.'
                ),
                source_url=event['source'], organizer=curator, game=Tournament.Game.CS2,
                format=Tournament.Format.SINGLE, starts_at=datetime.fromisoformat(event['start']).replace(tzinfo=MOSCOW),
                ends_at=datetime.fromisoformat(event['end']).replace(hour=23, minute=59, tzinfo=MOSCOW),
                team_limit=16, team_size=5, status=Tournament.Status.FINISHED,
                registration_open=False, edition=0, accent=('lime', 'blue', 'coral', 'violet')[event['series'] % 4],
                rules='Плей-офф: single elimination, BO3. Поражение завершает участие. Источник результатов: ' + event['results'],
            )
            tournament.full_clean()
            tournament.save()
            counts['tournaments'] += 1
            # Positional order is a display order reconstructed from the actual tree, not official seeding.
            participants = [row[key] for round_, _, row in ordered if round_ == 1 for key in ('a', 'b')]
            for name in participants:
                TournamentTeam.objects.create(tournament=tournament, team=teams[name], status=TournamentTeam.Status.APPROVED)
            matches = {}
            for round_, position, row in ordered:
                match = Match(
                    tournament=tournament, round=round_, position=position,
                    team_a=teams[row['a']], team_b=teams[row['b']], best_of=3,
                    score_a=row['score_a'], score_b=row['score_b'], status=Match.Status.FINISHED,
                    scheduled_at=datetime.fromisoformat(row['date']).replace(hour=12, tzinfo=MOSCOW), date_only=True,
                    source_url=event['results'], participants_snapshot={},
                )
                match.full_clean()
                match.save()
                matches[round_, position] = match
                counts['matches'] += 1
            for (round_, position), match in matches.items():
                if round_ == 4:
                    continue
                target = matches[round_ + 1, (position + 1) // 2]
                match.next_match = target
                match.next_slot = 'a' if target.team_a_id == match.winner.pk else 'b'
                match.full_clean()
                match.save(update_fields=['next_match', 'next_slot'])

        for series, a, b, video, title, embed_allowed in VIDEOS:
            matches = Match.objects.filter(
                tournament__organizer=curator, tournament__slug__startswith=f'cct-s2-europe-{series}-',
                source_url__gt='',
            ).filter(Q(team_a__name=a, team_b__name=b) | Q(team_a__name=b, team_b__name=a))
            if matches.count() != 1:
                raise CommandError(f'Не найден однозначный матч {a} — {b}; сначала выполните seed_real.')
            stream, created = Stream.objects.get_or_create(
                match=matches.get(), url=f'https://www.youtube.com/watch?v={video}',
                defaults={'platform': Stream.Platform.YOUTUBE, 'status': Stream.Status.RECORDING, 'title': title, 'embed_allowed': embed_allowed},
            )
            if created:
                stream.full_clean()
            counts['videos'] += int(created)

        if options['dry_run']:
            transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(('DRY RUN: ' if options['dry_run'] else 'Добавлено: ') + str(counts)))
