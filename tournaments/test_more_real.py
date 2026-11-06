from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from tournaments.models import Match, Stream, Team, Tournament, User
from tournaments.services import standings


@override_settings(ALLOWED_HOSTS=['testserver'])
class ExtendedArchiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_real', stdout=StringIO())

    def seed(self, **kwargs):
        call_command('seed_more_real', stdout=StringIO(), **kwargs)

    def test_real_results_full_trees_and_videos(self):
        self.seed()
        self.assertEqual((Tournament.objects.count(), Match.objects.count(), Stream.objects.count()), (8, 120, 15))
        champions = {12: 'BETBOOM', 13: 'GamerLegion', 14: 'Spirit Academy', 15: 'Spirit Academy', 17: '500', 18: 'B8'}
        for series, champion in champions.items():
            tournament = Tournament.objects.get(slug__startswith=f'cct-s2-europe-{series}-')
            self.assertEqual(standings(tournament)[0]['team'].name, champion)
            self.assertEqual(tournament.entries.count(), 16)
            for match in tournament.matches.all():
                match.full_clean()
                self.assertTrue(match.date_only)
                self.assertTrue(tournament.starts_at <= match.scheduled_at <= tournament.ends_at)
                if match.next_match:
                    self.assertEqual(match.winner.pk, getattr(match.next_match, f'team_{match.next_slot}_id'))
        for stream in Stream.objects.all():
            stream.full_clean()
            self.assertEqual(stream.status, 'recording')
            self.assertTrue(stream.title)
            if stream.embed_allowed:
                self.assertIn('youtube-nocookie.com/embed/', stream.embed_url())
            else:
                self.assertEqual(stream.embed_url(), '')
        self.assertEqual(Stream.objects.filter(embed_allowed=True).count(), 3)
        self.assertFalse(User.objects.filter(password__startswith='pbkdf2_').exists())

    def test_repeat_import_preserves_user_edits(self):
        self.seed()
        tournament = Tournament.objects.get(slug__startswith='cct-s2-europe-17-')
        tournament.description = 'Моя заметка'
        tournament.save()
        stream = Stream.objects.first()
        stream.title = 'Моя подпись'
        stream.save()
        self.seed()
        tournament.refresh_from_db()
        stream.refresh_from_db()
        self.assertEqual((tournament.description, stream.title), ('Моя заметка', 'Моя подпись'))
        self.assertEqual((Tournament.objects.count(), Match.objects.count(), Stream.objects.count()), (8, 120, 15))

    def test_dry_run_changes_nothing_and_conflicts_roll_back(self):
        before = (Tournament.objects.count(), Team.objects.count(), Match.objects.count())
        self.seed(dry_run=True)
        self.assertEqual((Tournament.objects.count(), Team.objects.count(), Match.objects.count()), before)
        owner = User.objects.create_user('owner@tests.test', nickname='owner')
        Team.objects.create(name='GamerLegion', tag='GL', captain=owner)
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual((Tournament.objects.count(), Match.objects.count(), Stream.objects.count()), (2, 30, 0))

    def test_video_labels_dates_and_embeds_on_pages(self):
        self.seed()
        response = self.client.get('/streams/')
        self.assertContains(response, 'лучшие моменты')
        self.assertContains(response, 'Запись эфира')
        stream = Stream.objects.filter(embed_allowed=True).first()
        self.assertContains(self.client.get(stream.match.get_absolute_url()), stream.embed_url('testserver'))
        restricted = Stream.objects.filter(embed_allowed=False).first()
        response = self.client.get(restricted.match.get_absolute_url())
        self.assertContains(response, restricted.url)
        video_id = restricted.url.split('v=')[1]
        self.assertNotContains(response, 'youtube-nocookie.com/embed/' + video_id)
        tournament = Tournament.objects.get(slug__startswith='cct-s2-europe-12-')
        self.assertContains(self.client.get(tournament.get_absolute_url()), '15.09.2024')
        self.assertNotContains(self.client.get(tournament.get_absolute_url()), 'март 2025')
        self.assertContains(self.client.get('/'), 'Трансляции и записи')
