from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Match, MatchConfirmation, MatchResultLog, Stream, Team, TeamMember, Tournament, TournamentTeam, User
from . import services


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class WebsiteFlowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner@tests.test", nickname="owner", role="organizer")
        self.stranger = User.objects.create_user("stranger@tests.test", nickname="stranger")
        self.start = timezone.localtime(timezone.now()).replace(second=0, microsecond=0)
        self.end = self.start + timedelta(days=2)
        self.teams = []
        for number in range(3):
            captain = User.objects.create_user(f"captain{number}@tests.test", nickname=f"captain{number}")
            self.client.force_login(captain)
            response = self.client.post(reverse("team_create"), {"name": f"Team {number}", "tag": f"T{number}", "color": "blue"})
            self.assertEqual(response.status_code, 302)
            self.teams.append(Team.objects.get(name=f"Team {number}"))

    def create_tournament(self, format="single"):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("tournament_create"), {
            "name": "Website Cup", "slug": "website-cup", "game": "CS2", "format": format,
            "starts_at": self.start.strftime("%Y-%m-%dT%H:%M"),
            "ends_at": self.end.strftime("%Y-%m-%dT%H:%M"),
            "team_limit": 8, "team_size": 1, "rules": "BO3",
        })
        self.assertEqual(response.status_code, 302)
        return Tournament.objects.get(slug="website-cup")

    def prepare_tournament(self, format="single"):
        tournament = self.create_tournament(format)
        self.client.post(reverse("tournament_action", args=[tournament.slug]), {"action": "publish"})
        for team in self.teams:
            self.client.force_login(team.captain)
            response = self.client.post(reverse("tournament_apply", args=[tournament.slug]), {"team_id": team.pk})
            self.assertEqual(response.status_code, 302)
        self.client.force_login(self.owner)
        for seed, entry in enumerate(tournament.entries.all(), 1):
            response = self.client.post(reverse("entry_action", args=[tournament.slug, entry.pk]), {"action": "approve", "seed": seed})
            self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("tournament_action", args=[tournament.slug]), {"action": "generate", "seeding": "manual"})
        self.assertEqual(response.status_code, 302)
        return tournament

    def finish_from_form(self, match):
        return self.client.post(reverse("match_edit", args=[match.pk]), {"score_a": 2, "score_b": 1, "status": "finished", "scheduled_at": ""})

    def test_complete_knockout_from_forms(self):
        tournament = self.prepare_tournament()
        self.assertEqual(tournament.entries.filter(status="approved").count(), 3)
        self.assertEqual(tournament.matches.count(), 3)
        self.assertEqual(tournament.matches.filter(is_bye=True).count(), 1)
        self.client.post(reverse("tournament_action", args=[tournament.slug]), {"action": "start"})
        for match in tournament.matches.all():
            match.refresh_from_db()
            if not match.is_bye:
                self.assertEqual(self.finish_from_form(match).status_code, 302)
        tournament.refresh_from_db()
        self.assertEqual(tournament.status, "finished")
        final = tournament.matches.order_by("-round").first()
        self.assertIsNotNone(final.winner)
        self.assertEqual(MatchResultLog.objects.count(), 2)
        self.assertEqual(services.standings(tournament)[0]["team"], final.winner)
        self.assertContains(self.client.get(tournament.get_absolute_url()), "Результаты")

    def test_complete_round_robin_and_archive_filters(self):
        tournament = self.prepare_tournament("round_robin")
        self.client.post(reverse("tournament_action", args=[tournament.slug]), {"action": "start"})
        for match in tournament.matches.all():
            self.assertEqual(self.finish_from_form(match).status_code, 302)
        tournament.refresh_from_db()
        self.assertEqual(tournament.status, "finished")
        response = self.client.get(reverse("match_list"), {"tournament": tournament.pk, "status": "finished"})
        self.assertEqual(len(response.context["matches"]), 3)
        self.assertEqual(sum(row["points"] for row in services.standings(tournament)), 9)

    def test_crafted_tournament_actions_do_not_cross_ownership(self):
        tournament = self.prepare_tournament()
        match = tournament.matches.filter(is_bye=False).first()
        entry = tournament.entries.first()
        self.client.force_login(self.stranger)
        for name, args, data in [
            ("tournament_action", [tournament.slug], {"action": "start"}),
            ("tournament_edit", [tournament.slug], {"name": "Hacked"}),
            ("entry_action", [tournament.slug, entry.pk], {"action": "reject"}),
            ("match_edit", [match.pk], {"status": "finished", "score_a": 2, "score_b": 0}),
            ("match_pair_edit", [match.pk], {"team_a": self.teams[0].pk}),
            ("match_stream_add", [match.pk], {"platform": "youtube", "url": "https://youtu.be/dQw4w9WgXcQ", "status": "live"}),
        ]:
            with self.subTest(route=name):
                self.assertEqual(self.client.post(reverse(name, args=args), data).status_code, 403)
        self.assertEqual(Stream.objects.count(), 0)

    def test_captain_can_only_register_their_team(self):
        tournament = self.create_tournament()
        self.client.post(reverse("tournament_action", args=[tournament.slug]), {"action": "publish"})
        self.client.force_login(self.teams[0].captain)
        self.assertEqual(self.client.post(reverse("tournament_apply", args=[tournament.slug]), {"team_id": self.teams[1].pk}).status_code, 404)
        self.assertEqual(tournament.entries.count(), 0)

    def test_result_errors_rollback_schedule(self):
        tournament = self.prepare_tournament()
        self.client.post(reverse("tournament_action", args=[tournament.slug]), {"action": "start"})
        match = tournament.matches.filter(is_bye=False, round=1).first()
        response = self.client.post(reverse("match_edit", args=[match.pk]), {
            "scheduled_at": (self.start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            "score_a": 9, "score_b": 0, "status": "finished",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        match.refresh_from_db()
        self.assertIsNone(match.scheduled_at)
        self.assertEqual(match.result_logs.count(), 0)

    def test_pair_edit_swaps_and_preserves_unique_teams(self):
        tournament = self.prepare_tournament()
        match = tournament.matches.filter(round=1, is_bye=False).first()
        bye = tournament.matches.get(is_bye=True)
        response = self.client.post(reverse("match_pair_edit", args=[match.pk]), {"team_a": bye.winner.pk, "team_b": match.team_b_id})
        self.assertEqual(response.status_code, 302)
        ids = [value for m in tournament.matches.filter(round=1) for value in (m.team_a_id, m.team_b_id) if value]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {team.pk for team in self.teams})

    def test_captain_confirmation_and_revision(self):
        tournament = self.prepare_tournament()
        services.start_tournament(tournament, self.owner)
        match = tournament.matches.filter(is_bye=False, round=1).first()
        match = services.update_result(match, self.owner, 2, 1)
        revision = match.result_logs.first().pk
        self.client.force_login(match.team_a.captain)
        url = reverse("match_confirm", args=[match.pk])
        self.assertEqual(self.client.post(url, {"team_id": match.team_a_id, "result_revision": revision}).status_code, 302)
        self.assertEqual(MatchConfirmation.objects.count(), 1)
        services.update_result(match, self.owner, 1, 2)
        self.client.post(url, {"team_id": match.team_a_id, "result_revision": revision})
        response = self.client.get(match.get_absolute_url())
        self.assertEqual(response.context["confirmations"].count(), 0)

    def test_stream_validation_embed_and_owner_edit(self):
        tournament = self.prepare_tournament()
        match = tournament.matches.first()
        url = reverse("match_stream_add", args=[match.pk])
        bad = self.client.post(url, {"platform": "youtube", "url": "https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ", "status": "live"})
        self.assertEqual(bad.status_code, 200)
        self.assertEqual(Stream.objects.count(), 0)
        good = self.client.post(url, {"platform": "youtube", "url": "https://youtu.be/dQw4w9WgXcQ", "status": "live"})
        self.assertEqual(good.status_code, 302)
        self.assertContains(self.client.get(match.get_absolute_url()), "youtube-nocookie.com/embed/dQw4w9WgXcQ")
        self.assertContains(self.client.get(reverse("live_streams")), "YouTube")
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.post(reverse("stream_edit", args=[Stream.objects.get().pk]), {"status": "recording"}).status_code, 403)

    def test_draft_match_json_and_page_are_private(self):
        tournament = self.prepare_tournament()
        match = tournament.matches.first()
        tournament.status = "draft"
        tournament.save()
        self.client.logout()
        self.assertEqual(self.client.get(match.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(reverse("match_state", args=[match.pk])).status_code, 404)

    def test_csrf_required_for_tournament_mutations(self):
        tournament = self.create_tournament()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(reverse("tournament_action", args=[tournament.slug]), {"action": "publish"}).status_code, 403)

    def test_landing_contains_no_demo_language(self):
        response = self.client.get(reverse("home"))
        for text in ("Демо", "учебный", "макеты"):
            self.assertNotContains(response, text)

    def test_calendar_shows_public_matches_and_handles_invalid_month(self):
        tournament = self.prepare_tournament()
        match = tournament.matches.filter(is_bye=False).first()
        match.scheduled_at = self.start
        match.save()
        month = self.start.strftime('%Y-%m')
        response = self.client.get(reverse('match_calendar'), {'month': month})
        self.assertContains(response, match.get_absolute_url())
        tournament.status = 'draft'
        tournament.save()
        self.assertNotContains(self.client.get(reverse('match_calendar'), {'month': month}), match.get_absolute_url())
        self.assertEqual(self.client.get(reverse('match_calendar'), {'month': 'bad'}).status_code, 200)

    def test_personal_calendar_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('match_calendar'), {'mine': '1'})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_draft_with_existing_bracket_can_be_published(self):
        tournament = self.prepare_tournament()
        tournament.status = 'draft'
        tournament.save(update_fields=['status'])
        self.client.post(reverse('tournament_action', args=[tournament.slug]), {'action': 'publish'})
        tournament.refresh_from_db()
        self.assertEqual(tournament.status, 'soon')
        self.assertFalse(tournament.registration_open)
        self.client.logout()
        self.assertContains(self.client.get(tournament.get_absolute_url()), 'Турнирная сетка')
