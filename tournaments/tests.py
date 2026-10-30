from datetime import timedelta
from io import StringIO

from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Match, MatchResultLog, Stream, Team, TeamMember, Tournament, TournamentTeam, User


class DatabaseDemoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo', stdout=StringIO())
        cls.admin = User.objects.create_superuser(
            email='admin@example.test', nickname='Администратор теста', password='Test-password-2026',
        )

    def test_home_and_navigation(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Всё начинается')
        self.assertContains(response, reverse('tournament_list'))
        self.assertContains(response, reverse('tournament_detail', args=['ignite-cup']))

    def test_all_tournaments_have_database_detail_pages(self):
        for tournament in Tournament.objects.all():
            with self.subTest(tournament=tournament.slug):
                response = self.client.get(reverse('tournament_detail', args=[tournament.slug]))
                self.assertContains(response, tournament.name)
                self.assertEqual(len(response.context['teams']), 4)
                self.assertEqual(len(response.context['matches']), 3)
                for team in Team.objects.all():
                    self.assertContains(response, team.name)

    def test_filters_combine_and_keep_selected_values(self):
        response = self.client.get(reverse('tournament_list'), {'q': 'ignite', 'game': 'CS2', 'status': 'live'})
        self.assertEqual([t['slug'] for t in response.context['tournaments']], ['ignite-cup'])
        self.assertContains(response, 'value="CS2" selected')
        self.assertContains(response, 'value="ignite"')

    def test_empty_search_has_reset_link(self):
        response = self.client.get(reverse('tournament_list'), {'game': 'CS2', 'status': 'soon'})
        self.assertContains(response, 'Турниров не найдено')
        self.assertContains(response, 'Сбросить фильтры')

    def test_unknown_tournament_returns_404(self):
        self.assertEqual(self.client.get('/tournaments/missing/').status_code, 404)

    def test_future_final_hides_undetermined_teams(self):
        tournament = Tournament.objects.get(slug='campus-arena')
        final = tournament.matches.get(round=2)
        self.assertIsNone(final.team_a)
        self.assertIsNone(final.team_b)
        self.assertContains(self.client.get('/tournaments/campus-arena/'), 'Соперник уточняется')

    def test_search_is_rendered_as_text(self):
        response = self.client.get(reverse('tournament_list'), {'q': '<script>alert("x")</script>'})
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertContains(response, '&lt;script&gt;')

    def test_home_uses_actual_names_teams_and_scores(self):
        tournament = Tournament.objects.get(slug='ignite-cup')
        tournament.name = 'Новый кубок колледжа'
        tournament.save()
        team = Team.objects.get(name='RED PIXELS')
        team.name = 'Новая команда'
        team.save()
        final = tournament.matches.get(round=2)
        final.score_a, final.score_b = 0, 1
        final.save()
        response = self.client.get('/')
        self.assertContains(response, 'Новый кубок колледжа')
        self.assertContains(response, 'Новая команда')
        self.assertEqual(response.context['final']['score_a'], 0)

    def test_edited_match_time_and_team_roster_appear(self):
        match = Match.objects.filter(tournament__slug='ignite-cup', round=1).first()
        match.scheduled_at = timezone.localtime(match.scheduled_at).replace(hour=11, minute=45)
        match.save()
        member = TeamMember.objects.filter(team=match.team_a).select_related('player').first()
        member.player.nickname = 'Новый ник'
        member.player.save()
        response = self.client.get('/tournaments/ignite-cup/')
        self.assertContains(response, '11:45')
        self.assertContains(response, 'Новый ник')

    def test_drafts_are_not_public(self):
        tournament = Tournament.objects.get(slug='ignite-cup')
        tournament.status = Tournament.Status.DRAFT
        tournament.save()
        self.assertNotContains(self.client.get('/tournaments/'), 'IGNITE CUP')
        self.assertEqual(self.client.get('/tournaments/ignite-cup/').status_code, 404)

    def test_empty_database_states(self):
        Tournament.objects.update(status=Tournament.Status.DRAFT)
        self.assertContains(self.client.get('/'), 'Первый турнир впереди')
        self.assertContains(self.client.get('/tournaments/'), 'Турниров не найдено')

    def test_new_tournament_without_matches_or_teams(self):
        source = Tournament.objects.first()
        tournament = Tournament.objects.create(
            name='Новый турнир', slug='new-cup', organizer=source.organizer,
            game='CS2', starts_at=source.starts_at, ends_at=source.ends_at,
            team_limit=8, status=Tournament.Status.SOON,
        )
        response = self.client.get(reverse('tournament_detail', args=[tournament.slug]))
        self.assertContains(response, 'Матчи ещё не назначены')
        self.assertContains(response, 'Команд: 0 / 8')
        self.assertEqual(response.context['rounds'], [])

    def test_finished_winner_is_derived_from_result(self):
        match = Match.objects.get(tournament__slug='first-strike', round=2)
        match.score_a, match.score_b = 1, 2
        match.save()
        self.assertEqual(self.client.get('/tournaments/first-strike/').context['winner'], match.team_b)

    def test_seed_is_repeatable_and_preserves_edits(self):
        team = Team.objects.first()
        team.contacts = 'Контакт после редактирования'
        team.name = 'Переименованная команда'
        team.save()
        before = (User.objects.count(), Team.objects.count(), Match.objects.count(), TournamentTeam.objects.count())
        call_command('seed_demo', stdout=StringIO())
        self.assertEqual(before, (User.objects.count(), Team.objects.count(), Match.objects.count(), TournamentTeam.objects.count()))
        team.refresh_from_db()
        self.assertEqual(team.contacts, 'Контакт после редактирования')
        self.assertEqual(team.name, 'Переименованная команда')

    def test_demo_users_have_no_login_passwords(self):
        self.assertFalse(User.objects.get(email='chefran@example.test').has_usable_password())

    def test_email_login_is_case_insensitive(self):
        self.assertEqual(authenticate(username='ADMIN@EXAMPLE.TEST', password='Test-password-2026'), self.admin)
        self.assertNotEqual(self.admin.password, 'Test-password-2026')

    def test_duplicate_email_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(email='ADMIN@EXAMPLE.TEST', nickname='Другой ник')

    def test_duplicate_team_entry_rejected(self):
        entry = TournamentTeam.objects.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TournamentTeam.objects.create(tournament=entry.tournament, team=entry.team)

    def test_team_limit_is_validated(self):
        tournament = Tournament.objects.first()
        team = Team.objects.create(name='Запасная команда', tag='EX', captain=self.admin)
        entry = TournamentTeam(tournament=tournament, team=team, status=TournamentTeam.Status.APPROVED)
        with self.assertRaises(ValidationError):
            entry.full_clean()

    def test_dates_and_self_match_are_validated(self):
        tournament = Tournament.objects.first()
        tournament.ends_at = tournament.starts_at - timedelta(hours=1)
        with self.assertRaises(ValidationError):
            tournament.full_clean()
        match = Match.objects.filter(round=1).first()
        match.team_b = match.team_a
        with self.assertRaises(ValidationError):
            match.full_clean()

    def test_match_team_must_be_an_approved_participant(self):
        match = Match.objects.filter(round=1).first()
        match.team_b = Team.objects.create(name='Не участник', tag='OUT', captain=self.admin)
        with self.assertRaises(ValidationError):
            match.full_clean()

    def test_invalid_score_and_next_match_rejected(self):
        match = Match.objects.filter(round=1).first()
        match.score_a, match.score_b = 9, 0
        with self.assertRaises(ValidationError):
            match.full_clean()
        match.score_a, match.score_b = 2, 0
        match.next_match = match
        with self.assertRaises(ValidationError):
            match.full_clean()

    def test_invalid_stream_domain_rejected(self):
        stream = Stream(match=Match.objects.first(), platform='youtube', url='https://youtube.com.attacker.test/video')
        with self.assertRaises(ValidationError):
            stream.full_clean()

    def test_admin_requires_staff_access(self):
        self.assertRedirects(self.client.get('/admin/'), '/admin/login/?next=/admin/', fetch_redirect_response=False)
        self.client.force_login(User.objects.get(email='chefran@example.test'))
        self.assertRedirects(self.client.get('/admin/'), '/admin/login/?next=/admin/', fetch_redirect_response=False)

    def test_all_models_available_to_admin(self):
        self.client.force_login(self.admin)
        for name in ('user', 'team', 'teammember', 'tournament', 'tournamentteam', 'match', 'stream', 'matchresultlog'):
            with self.subTest(model=name):
                self.assertEqual(self.client.get(f'/admin/tournaments/{name}/').status_code, 200)

    def test_admin_can_create_email_user(self):
        self.client.force_login(self.admin)
        response = self.client.post('/admin/tournaments/user/add/', {
            'email': 'new@example.test', 'nickname': 'Новичок', 'role': 'player',
            'password1': 'New-test-password-2026', 'password2': 'New-test-password-2026',
            'usable_password': 'true',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.get(email='new@example.test').check_password('New-test-password-2026'))

    def test_admin_edit_writes_result_history(self):
        self.client.force_login(self.admin)
        match = Match.objects.get(tournament__slug='ignite-cup', round=2)
        response = self.client.post(reverse('admin:tournaments_match_change', args=[match.pk]), {
            'tournament': match.tournament_id, 'team_a': match.team_a_id, 'team_b': match.team_b_id,
            'round': match.round, 'position': match.position, 'best_of': match.best_of,
            'scheduled_at_0': '2026-10-23', 'scheduled_at_1': '19:30:00',
            'score_a': 2, 'score_b': 1, 'status': 'finished', 'next_match': '', 'next_slot': '',
            '_save': 'Сохранить',
        })
        self.assertEqual(response.status_code, 302)
        log = MatchResultLog.objects.get(match=match)
        self.assertEqual((log.old_score_a, log.old_score_b), (1, 1))
        self.assertEqual((log.new_score_a, log.new_score_b), (2, 1))
        self.assertEqual(log.changed_by, self.admin)
        self.assertContains(self.client.get('/tournaments/ignite-cup/'), '19:30')

    def test_preview_pages_do_not_offer_working_forms(self):
        for page in ('register', 'login', 'player', 'team', 'organizer'):
            self.assertContains(self.client.get(f'/previews/{page}/'), 'пока не отправляют')
        self.assertEqual(self.client.get('/previews/missing/').status_code, 404)
