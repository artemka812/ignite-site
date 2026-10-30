from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from .models import Match, MatchResultLog, Stream, Team, TeamMember, Tournament, TournamentTeam, User
from .services import (decide_entry, generate_bracket, player_matches, player_statistics, standings,
                       start_tournament, team_statistics, update_result, update_schedule)


class TournamentEngineTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner@example.test', nickname='owner', role='organizer')
        self.stranger = User.objects.create_user('stranger@example.test', nickname='stranger')
        self.now = timezone.now()

    def make_tournament(self, size, format='single'):
        tournament = Tournament.objects.create(name='Cup', slug=f'cup-{Tournament.objects.count()}', organizer=self.owner, game='CS2', format=format, starts_at=self.now, ends_at=self.now + timedelta(days=2), team_limit=16)
        for number in range(size):
            index = Team.objects.count()
            player = User.objects.create_user(f'p{index}@example.test', nickname=f'p{index}')
            team = Team.objects.create(name=f'Team {index}', tag=f'T{index}', captain=player)
            TeamMember.objects.create(team=team, player=player, status='active', joined_at=self.now)
            TournamentTeam.objects.create(tournament=tournament, team=team, status='approved', seed=number + 1)
        return tournament

    def finish(self, match, a=2, b=0):
        return update_result(match, self.owner, a, b)

    def test_single_all_sizes_and_completion(self):
        for size in (2, 3, 5, 8):
            with self.subTest(size=size):
                tournament = self.make_tournament(size)
                matches = generate_bracket(tournament, self.owner, 'manual')
                power = 1 << (size - 1).bit_length()
                self.assertEqual(len(matches), power - 1)
                self.assertEqual(sum(match.is_bye for match in matches), power - size)
                for match in matches:
                    match.full_clean()
                self.assertFalse(tournament.matches.filter(round__gt=1, status='finished').exists())
                start_tournament(tournament, self.owner)
                played = 0
                for match in tournament.matches.all():
                    match.refresh_from_db()
                    if not match.is_bye:
                        self.assertIsNotNone(match.team_a_id)
                        self.assertIsNotNone(match.team_b_id)
                        self.finish(match)
                        played += 1
                self.assertEqual(played, size - 1)
                tournament.refresh_from_db()
                self.assertEqual(tournament.status, 'finished')
                final = tournament.matches.order_by('-round').first()
                self.assertEqual(standings(tournament)[0]['team'], final.winner)

    def test_round_robin_pairs_and_round_rest(self):
        for size in (3, 4, 5, 8):
            tournament = self.make_tournament(size, 'round_robin')
            matches = generate_bracket(tournament, self.owner)
            self.assertEqual(len(matches), size * (size - 1) // 2)
            pairs = {tuple(sorted((m.team_a_id, m.team_b_id))) for m in matches}
            self.assertEqual(len(pairs), len(matches))
            for round_number in {m.round for m in matches}:
                participants = [team for m in matches if m.round == round_number for team in (m.team_a_id, m.team_b_id)]
                self.assertEqual(len(participants), len(set(participants)))
            self.assertTrue(all(not m.is_bye and not m.next_match_id for m in matches))

    def test_round_robin_completion_and_points(self):
        tournament = self.make_tournament(3, "round_robin")
        matches = generate_bracket(tournament, self.owner, "manual")
        start_tournament(tournament, self.owner)
        for match in matches:
            self.finish(match)
        tournament.refresh_from_db()
        self.assertEqual(tournament.status, "finished")
        rows = standings(tournament)
        self.assertEqual(sum(row["points"] for row in rows), 9)
        self.assertTrue(all(row["played"] == 2 for row in rows))

    def test_manual_and_random_seed(self):
        tournament = self.make_tournament(4)
        teams = list(tournament.teams.order_by('id'))
        matches = generate_bracket(tournament, self.owner, 'manual')
        self.assertEqual((matches[0].team_a, matches[0].team_b), (teams[0], teams[3]))
        other = self.make_tournament(4)
        with patch('tournaments.services.random.shuffle') as shuffle:
            generate_bracket(other, self.owner)
            shuffle.assert_called_once()
        missing = self.make_tournament(2)
        missing.entries.update(seed=None)
        with self.assertRaises(ValidationError):
            generate_bracket(missing, self.owner, 'manual')
        self.assertFalse(missing.matches.exists())

    def test_permissions_and_no_overwrite(self):
        tournament = self.make_tournament(2)
        with self.assertRaises(PermissionDenied):
            generate_bracket(tournament, self.stranger)
        match = generate_bracket(tournament, self.owner)[0]
        with self.assertRaises(ValidationError):
            generate_bracket(tournament, self.owner)
        with self.assertRaises(ValidationError):
            self.finish(match)
        start_tournament(tournament, self.owner)
        with self.assertRaises(PermissionDenied):
            update_result(match, self.stranger, 2, 0)
        with self.assertRaises(PermissionDenied):
            update_schedule(match, self.stranger, self.now)
        with self.assertRaises(ValidationError):
            generate_bracket(tournament, self.owner)
        self.assertEqual(tournament.matches.count(), 1)

    def test_correction_updates_waiting_final_and_locks_started_final(self):
        tournament = self.make_tournament(4)
        generate_bracket(tournament, self.owner, 'manual')
        start_tournament(tournament, self.owner)
        first, second = tournament.matches.filter(round=1)
        self.finish(first)
        self.finish(first, 0, 2)
        final = tournament.matches.get(round=2)
        self.assertEqual(final.team_a_id, first.team_b_id)
        self.assertIsNone(final.team_b_id)
        self.finish(second)
        update_result(final, self.owner, 0, 0, 'live')
        with self.assertRaises(ValidationError):
            self.finish(first)
        first.refresh_from_db()
        self.assertEqual((first.score_a, first.score_b), (0, 2))
        self.assertEqual(first.result_logs.count(), 2)

    def test_invalid_score_and_log_failure_roll_back(self):
        tournament = self.make_tournament(2)
        match = generate_bracket(tournament, self.owner)[0]
        start_tournament(tournament, self.owner)
        with self.assertRaises(ValidationError):
            self.finish(match, 1, 1)
        with patch.object(MatchResultLog.objects, 'create', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.finish(match)
        match.refresh_from_db()
        self.assertEqual(match.status, 'planned')
        self.assertEqual(match.participants_snapshot, {})
        self.assertIsNone(match.score_a)
        self.assertEqual(MatchResultLog.objects.count(), 0)

    def test_player_statistics_keep_historical_roster(self):
        tournament = self.make_tournament(2)
        match = generate_bracket(tournament, self.owner)[0]
        start_tournament(tournament, self.owner)
        player = match.team_a.captain
        update_result(match, self.owner, 0, 0, 'live')
        TeamMember.objects.filter(team=match.team_a).update(status='left', left_at=self.now)
        TeamMember.objects.create(team=match.team_a, player=self.stranger, status='active')
        self.finish(match)
        self.assertEqual(player_statistics(player)['wins'], 1)
        self.assertIn(match, player_matches(player))
        self.assertNotIn(match, player_matches(self.stranger))
        self.assertEqual(player_statistics(self.stranger)['played'], 0)
        self.assertEqual(team_statistics(match.team_a)['maps_won'], 2)

    def test_schedule_and_entry_decision(self):
        tournament = self.make_tournament(2)
        entry = tournament.entries.first()
        decide_entry(entry, self.owner, False)
        self.assertEqual(tournament.entries.filter(status='approved').count(), 1)
        decide_entry(entry, self.owner, True, seed=1)
        match = generate_bracket(tournament, self.owner)[0]
        with self.assertRaises(ValidationError):
            decide_entry(entry, self.owner, False)
        with self.assertRaises(ValidationError):
            update_schedule(match, self.owner, self.now - timedelta(days=1))
        update_schedule(match, self.owner, self.now + timedelta(hours=1))
        match.refresh_from_db()
        self.assertEqual(match.scheduled_at, self.now + timedelta(hours=1))

    def test_stream_embed_is_strict(self):
        youtube = Stream(platform='youtube', url='https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        youtube.clean()
        self.assertEqual(youtube.embed_url('localhost:8000'), 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ')
        twitch = Stream(platform='twitch', url='https://www.twitch.tv/videos/12345')
        twitch.clean()
        self.assertIn('video=v12345&parent=localhost&autoplay=false', twitch.embed_url('localhost:8000'))
        for url in ('https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ', 'javascript:alert(1)', 'https://youtube.com/watch?v=bad', 'https://user@youtube.com/watch?v=dQw4w9WgXcQ'):
            stream = Stream(platform='youtube', url=url)
            with self.assertRaises(ValidationError):
                stream.clean()
            self.assertEqual(stream.embed_url(), '')

    def test_bye_does_not_count_in_statistics(self):
        tournament = self.make_tournament(3)
        matches = generate_bracket(tournament, self.owner, 'manual')
        bye = next(match for match in matches if match.is_bye)
        self.assertEqual(team_statistics(bye.winner)['played'], 0)
        self.assertEqual(player_statistics(bye.winner.captain)['played'], 0)

    def test_legacy_snapshot_uses_only_known_intervals(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection

        backfill = import_module('tournaments.migrations.0004_backfill_known_rosters').backfill_known_rosters
        tournament = self.make_tournament(4)
        matches = generate_bracket(tournament, self.owner, 'manual')
        first, second = [match for match in matches if match.round == 1]
        first.status = 'finished'
        first.score_a, first.score_b = 2, 0
        first.scheduled_at = self.now + timedelta(hours=1)
        first.save()
        second.status = 'live'
        second.save()
        known = first.team_a.captain
        TeamMember.objects.filter(player=known).update(status='left', left_at=self.now + timedelta(hours=2))
        unknown = first.team_b.captain
        TeamMember.objects.filter(player=unknown).update(joined_at=None)
        TeamMember.objects.create(team=first.team_a, player=self.stranger, status='active', joined_at=self.now + timedelta(hours=2))
        tournament.registration_open = True
        tournament.save(update_fields=['registration_open'])
        backfill(apps, connection.schema_editor())
        first.refresh_from_db()
        second.refresh_from_db()
        tournament.refresh_from_db()
        self.assertEqual(first.participants_snapshot, {'a': [known.pk], 'b': []})
        self.assertEqual(second.participants_snapshot, {})
        self.assertFalse(tournament.registration_open)
        self.assertEqual(player_statistics(known)['wins'], 0)
        tournament.status = Tournament.Status.LIVE
        tournament.save(update_fields=['status'])
        self.assertEqual(player_statistics(known)['wins'], 1)
        self.assertEqual(player_statistics(unknown)['played'], 0)
        self.assertEqual(player_statistics(self.stranger)['played'], 0)
        # Running again never replaces a captured roster, even if membership changes.
        TeamMember.objects.filter(player=known).update(left_at=self.now)
        backfill(apps, connection.schema_editor())
        first.refresh_from_db()
        self.assertEqual(first.participants_snapshot['a'], [known.pk])
