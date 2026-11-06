from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from tournaments.models import Match, Team, TeamMember, Tournament, TournamentTeam, User
from tournaments.real_data import EVENTS, PLAYER_POSITIONS, PLAYOFFS, ROSTERS, match_roster, match_source

ARCHIVE_EMAIL = "curator@archive.ignite.invalid"
MOSCOW = ZoneInfo("Europe/Moscow")


class Command(BaseCommand):
    help = "Добавить архив CCT 19/20 (2025) и заполнить подтверждённые позиции в пустых архивных профилях."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Проверить импорт и откатить добавленные записи.")

    @transaction.atomic
    def handle(self, *args, **options):
        curator, created = User.objects.get_or_create(email=ARCHIVE_EMAIL, defaults={
            "nickname": "IGNITE · CCT", "role": User.Role.ORGANIZER,
        })
        if created:
            curator.set_unusable_password()
            curator.save(update_fields=["password"])
        elif curator.has_usable_password():
            raise CommandError("Адрес архивного куратора занят пользовательским аккаунтом.")

        players = {}
        for nickname in sorted({name for roster in ROSTERS.values() for name in roster} | {"POP0V"}):
            email = f"{slugify(nickname)}@archive.ignite.invalid"
            position = PLAYER_POSITIONS.get(nickname, "")
            player, created = User.objects.get_or_create(
                email=email, defaults={"nickname": nickname, "position": position},
            )
            if created:
                player.set_unusable_password()
                player.save(update_fields=["password"])
            elif player.nickname != nickname or player.has_usable_password():
                raise CommandError(f"Конфликт архивного игрока {nickname}; импорт отменён.")
            elif position and not player.position:
                User.objects.filter(pk=player.pk, position="").update(position=position)
            players[nickname] = player

        teams = {}
        for index, (name, roster) in enumerate(ROSTERS.items()):
            team, created = Team.objects.get_or_create(name=name, defaults={
                "tag": slugify(name).replace("-", "")[:5].upper(), "captain": curator,
                "color": ("lime", "blue", "coral", "violet")[index % 4],
                "archive_note": (
                    "Архивный состав на март 2025 года, по матчам CCT Europe Series 19/20. "
                    "Это справочная карточка, а не официальный аккаунт команды. "
                    "Дата вступления и игровые роли не указаны, если они не проверены. "
                    "Замены сохранены отдельно в составах конкретных матчей."
                ),
            })
            if not created and (team.captain_id != curator.pk or not team.archive_note):
                raise CommandError(f"Команда {name} уже существует вне архива; импорт отменён.")
            teams[name] = team
            if created:
                for nickname in roster:
                    TeamMember.objects.create(team=team, player=players[nickname], status=TeamMember.Status.ACTIVE)
        # A stand-in remains visible as a historical member without claiming a current place.
        TeamMember.objects.get_or_create(team=teams["500"], player=players["POP0V"], defaults={"status": TeamMember.Status.LEFT})

        added = 0
        for series, rows in PLAYOFFS.items():
            start, end, source = EVENTS[series]
            tournament, created = Tournament.objects.get_or_create(slug=f"cct-s2-europe-{series}-2025-playoffs", defaults={
                "name": f"CCT Season 2 Europe Series {series}",
                "subtitle": "2025 · плей-офф · CS2 · европейская сцена тир-2/тир-3",
                "description": (
                    "Реальный онлайн-турнир CCT. Общий призовой фонд — $50 000. "
                    "На этой странице полностью представлен плей-офф: 16 команд, 15 матчей, BO3. "
                    "Швейцарский этап основного турнира (24 участника) сюда не включён. "
                    "Результаты и составы сверены с карточками матчей HLTV; "
                    "тир-2/тир-3 — описание сцены, а не официальный рейтинг каждой команды."
                ),
                "organizer": curator, "game": Tournament.Game.CS2,
                "starts_at": datetime.fromisoformat(start).replace(tzinfo=MOSCOW),
                "ends_at": datetime.fromisoformat(end).replace(hour=23, minute=59, tzinfo=MOSCOW),
                "status": Tournament.Status.FINISHED, "registration_open": False,
                "team_limit": 16, "team_size": 5, "edition": 0,
                "accent": "lime" if series == 19 else "blue", "source_url": source,
                "rules": "Плей-офф: single elimination, все матчи BO3.\n"
                         "Указаны календарные даты матчей, без неподтверждённого времени начала.\n"
                         "Личная и командная статистика на сайте рассчитана только по добавленным матчам.\n"
                         "Организатор соревнования — CCT.",
            })
            if not created:
                if tournament.organizer_id != curator.pk or tournament.source_url != source:
                    raise CommandError(f"Адрес турнира CCT {series} занят; импорт отменён.")
                self.stdout.write(f"CCT {series}: уже добавлен, сохранён без изменений.")
                continue
            participants = list(dict.fromkeys(team for row in rows if row[0] == 1 for team in row[4:6]))
            for seed, name in enumerate(participants, 1):
                TournamentTeam.objects.create(tournament=tournament, team=teams[name], seed=seed, status=TournamentTeam.Status.APPROVED)
            matches = {}
            for round_, position, match_id, day, a, b, score_a, score_b in rows:
                match = Match(
                    tournament=tournament, round=round_, position=position,
                    team_a=teams[a], team_b=teams[b], score_a=score_a, score_b=score_b,
                    scheduled_at=datetime(2025, 3, day, 12, tzinfo=MOSCOW), date_only=True,
                    source_url=match_source(match_id), status=Match.Status.FINISHED,
                    participants_snapshot={
                        side: [players[name].pk for name in match_roster(series, match_id, team)]
                        for side, team in (("a", a), ("b", b))
                    },
                )
                match.full_clean()
                match.save()
                matches[round_, position] = match
            for (round_, position), match in matches.items():
                if round_ == 4:
                    continue
                target = matches[round_ + 1, (position + 1) // 2]
                winner_id = match.winner.pk
                if winner_id not in (target.team_a_id, target.team_b_id):
                    raise CommandError("Победитель не совпадает с участником следующего раунда.")
                match.next_match = target
                match.next_slot = "a" if target.team_a_id == winner_id else "b"
                match.full_clean()
                match.save(update_fields=["next_match", "next_slot"])
            added += len(matches)
        if options["dry_run"]:
            transaction.set_rollback(True)
            self.stdout.write(self.style.SUCCESS(f"Проверка пройдена: {added} новых матчей. Записи не сохранены."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Добавлено матчей: {added}. Существующие данные сохранены."))
