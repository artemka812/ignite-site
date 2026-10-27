from django.test import SimpleTestCase
from django.urls import reverse

from .data import TEAMS, TOURNAMENTS, matches_for


class DemoTests(SimpleTestCase):
    def test_home_and_navigation(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Всё начинается")
        self.assertContains(response, reverse("tournament_list"))
        self.assertContains(response, reverse("tournament_detail", args=["ignite-cup"]))

    def test_all_tournaments_have_working_detail_pages(self):
        for tournament in TOURNAMENTS:
            with self.subTest(tournament=tournament["slug"]):
                response = self.client.get(reverse("tournament_detail", args=[tournament["slug"]]))
                self.assertContains(response, tournament["name"])
                self.assertEqual(len(response.context["teams"]), 4)
                self.assertEqual(len(response.context["matches"]), 3)
                for team in TEAMS:
                    self.assertContains(response, team["name"])

    def test_filters_combine_and_keep_selected_values(self):
        response = self.client.get(reverse("tournament_list"), {"q": "ignite", "game": "CS2", "status": "live"})
        self.assertEqual([t["slug"] for t in response.context["tournaments"]], ["ignite-cup"])
        self.assertContains(response, 'value="CS2" selected')
        self.assertContains(response, 'value="ignite"')

    def test_empty_search_has_reset_link(self):
        response = self.client.get(reverse("tournament_list"), {"game": "CS2", "status": "soon"})
        self.assertContains(response, "Турниров не найдено")
        self.assertContains(response, "Сбросить фильтры")

    def test_unknown_tournament_returns_404(self):
        response = self.client.get(reverse("tournament_detail", args=["missing"]))
        self.assertEqual(response.status_code, 404)

    def test_future_final_hides_undetermined_teams(self):
        tournament = next(t for t in TOURNAMENTS if t["status"] == "soon")
        final = matches_for(tournament)[2]
        self.assertIsNone(final["a"])
        self.assertIsNone(final["b"])
        self.assertEqual(final["score_a"], "—")
        response = self.client.get(reverse("tournament_detail", args=[tournament["slug"]]))
        self.assertContains(response, "Победитель полуфинала 1")

    def test_search_is_rendered_as_text(self):
        response = self.client.get(reverse("tournament_list"), {"q": '<script>alert("x")</script>'})
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertContains(response, "&lt;script&gt;")
