from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db import transaction

from tournaments.data import TEAMS, TOURNAMENTS, matches_for
from tournaments.models import Match, Team, TeamMember, Tournament, TournamentTeam, User

MOSCOW = ZoneInfo("Europe/Moscow")


class Command(BaseCommand):
    help = "Добавить примеры турниров, сохранив существующие записи и правки."

    @transaction.atomic
    def handle(self, *args, **options):
        organizer, created = User.objects.get_or_create(
            email="organizer@example.test",
            defaults={"nickname": "Организатор IGNITE", "role": User.Role.ORGANIZER},
        )
        if created:
            organizer.set_unusable_password()
            organizer.save(update_fields=["password"])
        teams = {}
        for source in TEAMS:
            players = []
            for nickname in source["players"].split(" · "):
                player, created = User.objects.get_or_create(
                    email=f"{nickname}@example.test", defaults={"nickname": nickname},
                )
                if created:
                    player.set_unusable_password()
                    player.save(update_fields=["password"])
                players.append(player)
            team = Team.objects.filter(tag=source["tag"]).first()
            if team is None:
                team = Team.objects.create(name=source["name"], tag=source["tag"], captain=players[0], color=source["color"])
            teams[source["name"]] = team
            for player in players:
                TeamMember.objects.get_or_create(team=team, player=player, defaults={
                    "status": TeamMember.Status.ACTIVE,
                    "joined_at": datetime(2026, 10, 15, 12, tzinfo=MOSCOW),
                })
        days = {"ignite-cup": 23, "campus-arena": 30, "first-strike": 16}
        statuses = {"Завершён": Match.Status.FINISHED, "Идёт матч": Match.Status.LIVE, "Запланирован": Match.Status.PLANNED}
        for source in TOURNAMENTS:
            day = days[source["slug"]]
            rules = (
                "В турнире участвуют четыре команды по пять игроков.\n"
                "Поражение завершает участие; победители полуфиналов встречаются в финале.\n"
                "Все встречи проходят до двух побед по картам — BO3.\n"
                "Время указано по Москве. Будьте готовы за 15 минут до матча."
            )
            tournament, _ = Tournament.objects.get_or_create(slug=source["slug"], defaults={
                "name": source["name"], "subtitle": source["subtitle"],
                "description": source["description"], "organizer": organizer,
                "game": source["game"], "starts_at": datetime(2026, 10, day, 15, tzinfo=MOSCOW),
                "ends_at": datetime(2026, 10, day, 21, tzinfo=MOSCOW),
                "status": source["status"], "accent": source["accent"],
                "edition": int(source["edition"]), "rules": rules,
            })
            for seed, team in enumerate(teams.values(), 1):
                TournamentTeam.objects.get_or_create(tournament=tournament, team=team, defaults={
                    "status": TournamentTeam.Status.APPROVED, "seed": seed,
                })
            matches, new_matches = [], []
            for index, match in enumerate(matches_for(source)):
                hour = int(match["time"].split(":")[0])
                obj, created = Match.objects.get_or_create(
                    tournament=tournament, round=2 if index == 2 else 1,
                    position=1 if index == 2 else index + 1,
                    defaults={
                        "team_a": teams[match["a"]["name"]] if match["a"] else None,
                        "team_b": teams[match["b"]["name"]] if match["b"] else None,
                        "scheduled_at": datetime(2026, 10, day, hour, tzinfo=MOSCOW),
                        "score_a": int(match["score_a"]) if match["score_a"].isdigit() else None,
                        "score_b": int(match["score_b"]) if match["score_b"].isdigit() else None,
                        "status": statuses[match["status"]],
                    },
                )
                matches.append(obj)
                new_matches.append(created)
            for semifinal, slot in zip(matches[:2], ("a", "b")):
                if new_matches[matches.index(semifinal)]:
                    semifinal.next_match = matches[2]
                    semifinal.next_slot = slot
                    semifinal.save(update_fields=["next_match", "next_slot"])
        self.stdout.write(self.style.SUCCESS("Примеры добавлены. Существующие значения не перезаписывались."))
