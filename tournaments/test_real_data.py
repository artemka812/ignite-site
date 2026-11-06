from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Match, Team, TeamMember, Tournament, User
from .services import player_statistics, standings


@override_settings(ALLOWED_HOSTS=["testserver"])
class RealArchiveTests(TestCase):
    def seed(self, **kwargs):
        call_command("seed_real", stdout=StringIO(), **kwargs)

    def test_complete_brackets_rosters_winners_and_substitute(self):
        self.seed()
        self.assertEqual(Team.objects.count(), 21)
        self.assertEqual(User.objects.filter(role="player").count(), 106)
        self.assertEqual(Match.objects.count(), 30)
        for tournament, champion in zip(Tournament.objects.all(), ("BC.Game", "OG")):
            self.assertEqual(tournament.entries.count(), 16)
            self.assertEqual(tournament.matches.count(), 15)
            self.assertEqual(standings(tournament)[0]["team"].name, champion)
            for match in tournament.matches.all():
                match.full_clean()
                self.assertEqual([len(ids) for ids in match.participants_snapshot.values()], [5, 5])
                if match.next_match:
                    self.assertEqual(match.winner.pk, getattr(match.next_match, f"team_{match.next_slot}_id"))
        self.assertEqual(player_statistics(User.objects.get(nickname="POP0V"))["played"], 1)
        self.assertEqual(player_statistics(User.objects.get(nickname="SHiPZ"))["played"], 4)
        self.assertTrue(all(not user.has_usable_password() for user in User.objects.all()))

    def test_repeat_import_preserves_edits_and_does_not_duplicate(self):
        self.seed()
        tournament = Tournament.objects.first()
        tournament.description = "Пользовательская правка"
        tournament.save()
        member = TeamMember.objects.filter(status="active").first()
        member.status = "left"
        member.save()
        self.seed()
        tournament.refresh_from_db()
        member.refresh_from_db()
        self.assertEqual(tournament.description, "Пользовательская правка")
        self.assertEqual(member.status, "left")
        self.assertEqual((Tournament.objects.count(), Match.objects.count(), Team.objects.count()), (2, 30, 21))

    def test_dry_run_leaves_database_untouched(self):
        self.seed(dry_run=True)
        self.assertFalse(User.objects.exists())
        self.assertFalse(Tournament.objects.exists())

    def test_conflicting_team_rolls_back_import(self):
        owner = User.objects.create_user("owner@example.test", nickname="owner")
        team = Team.objects.create(name="Nexus", tag="NXS", captain=owner)
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Team.objects.get(pk=team.pk).captain_id, owner.pk)
        self.assertFalse(Tournament.objects.exists())

    def test_archive_pages_and_rosters_are_visible(self):
        self.seed()
        for tournament in Tournament.objects.all():
            response = self.client.get(tournament.get_absolute_url())
            self.assertContains(response, "Источник: HLTV")
            self.assertContains(response, "Швейцарский этап основного турнира")
            self.assertNotContains(response, "Архив")
        quarterfinal = Match.objects.get(source_url__contains="2380551/")
        response = self.client.get(quarterfinal.get_absolute_url())
        self.assertContains(response, "POP0V")
        self.assertNotContains(response, ">SHiPZ</a>")
        self.assertContains(response, "15.03.2025")
        self.assertContains(response, "без времени")
        self.assertContains(self.client.get("/"), "Результаты CCT")
        self.assertContains(self.client.get(reverse("match_calendar") + "?month=2025-03"), "Завершён")
        team = Team.objects.get(name="500")
        self.assertContains(self.client.get(team.get_absolute_url()), "Состав и результаты по добавленным матчам CCT.")
        player = User.objects.get(nickname="POP0V")
        self.assertContains(self.client.get(player.get_absolute_url()), "Статистика по добавленным матчам CCT.")

    def test_archive_team_cannot_accept_join_requests(self):
        self.seed()
        viewer = User.objects.create_user("viewer@example.test", nickname="viewer")
        self.client.force_login(viewer)
        team = Team.objects.get(name="500")
        self.client.post(reverse("team_action", args=[team.pk]), {"action": "join"})
        self.assertFalse(TeamMember.objects.filter(team=team, player=viewer).exists())
