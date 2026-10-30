from django.contrib.auth import SESSION_KEY
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Match, Team, TeamMember, Tournament, User


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CommunityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.captain = User.objects.create_user("captain@example.com", "ValidPass!452", nickname="Captain")
        cls.player = User.objects.create_user("player@example.com", "ValidPass!452", nickname="Player")
        cls.other = User.objects.create_user("other@example.com", "ValidPass!452", nickname="Other")
        cls.team = Team.objects.create(name="First", tag="ONE", captain=cls.captain)
        TeamMember.objects.create(team=cls.team, player=cls.captain, status="active")

    def action(self, user, action, **fields):
        self.client.force_login(user)
        return self.client.post(reverse("team_action", args=[self.team.pk]), {"action": action, **fields})

    def membership(self, player=None):
        return TeamMember.objects.get(team=self.team, player=player or self.player)

    def test_registration_hashes_password_and_ignores_privileges(self):
        response = self.client.post(reverse("register"), {
            "email": "NEW@Example.com", "nickname": "Fresh", "password1": "StrongPass!591", "password2": "StrongPass!591",
            "role": "organizer", "is_staff": "true", "is_superuser": "true",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="new@example.com")
        self.assertTrue(user.check_password("StrongPass!591"))
        self.assertNotEqual(user.password, "StrongPass!591")
        self.assertEqual(user.role, "player")
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertEqual(int(self.client.session[SESSION_KEY]), user.pk)

    def test_registration_rejects_weak_password_and_duplicate_email(self):
        from .community_forms import RegistrationForm
        form = RegistrationForm({"email": "CAPTAIN@EXAMPLE.COM", "nickname": "Fresh", "password1": "12345678", "password2": "12345678"})
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
        self.assertIn("password2", form.errors)

    def test_email_login_is_case_insensitive_and_logout_post_only(self):
        response = self.client.post(reverse("login"), {"username": "PLAYER@EXAMPLE.COM", "password": "ValidPass!452"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.player.pk)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertIn(SESSION_KEY, self.client.session)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_login_does_not_redirect_to_external_next(self):
        response = self.client.post(reverse("login"), {"username": self.player.email, "password": "ValidPass!452", "next": "https://evil.example/"})
        self.assertEqual(response.url, reverse("dashboard"))

    def test_profile_only_edits_current_user(self):
        self.client.force_login(self.player)
        response = self.client.post(reverse("profile_edit"), {"nickname": "Updated", "game_id": "id42", "position": "Support", "avatar": "", "id": self.captain.pk, "email": "evil@example.com", "is_staff": "true", "role": "organizer"})
        self.assertEqual(response.status_code, 302)
        self.player.refresh_from_db()
        self.captain.refresh_from_db()
        self.assertEqual(self.player.nickname, "Updated")
        self.assertEqual(self.captain.nickname, "Captain")
        self.assertEqual(self.player.email, "player@example.com")
        self.assertEqual(self.player.role, "player")
        self.assertFalse(self.player.is_staff)

    def test_organizer_opt_in_never_grants_staff(self):
        self.client.force_login(self.player)
        response = self.client.post(reverse("dashboard"), {"action": "become_organizer", "is_staff": "true", "is_superuser": "true"})
        self.assertEqual(response.status_code, 302)
        self.player.refresh_from_db()
        self.assertEqual(self.player.role, "organizer")
        self.assertFalse(self.player.is_staff or self.player.is_superuser)

    def test_team_creation_assigns_current_user_as_active_captain(self):
        self.client.force_login(self.player)
        response = self.client.post(reverse("team_create"), {"name": "Second", "tag": "TWO", "color": "lime", "captain": self.captain.pk})
        self.assertEqual(response.status_code, 302)
        team = Team.objects.get(name="Second")
        self.assertEqual(team.captain_id, self.player.pk)
        membership = team.memberships.get(player=self.player)
        self.assertEqual(membership.status, "active")
        self.assertIsNotNone(membership.joined_at)

    def test_team_edit_forbidden_for_other_player(self):
        self.client.force_login(self.player)
        response = self.client.post(reverse("team_edit", args=[self.team.pk]), {"name": "Hacked", "tag": "NO", "color": "lime"})
        self.assertEqual(response.status_code, 403)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "First")

    def test_join_is_unique_and_only_captain_can_approve(self):
        self.action(self.player, "join", player_id=self.other.pk)
        self.action(self.player, "join")
        self.assertEqual(self.team.memberships.filter(player=self.player).count(), 1)
        self.assertFalse(self.team.memberships.filter(player=self.other).exists())
        member = self.membership()
        self.assertEqual(member.status, "pending")
        self.assertEqual(self.action(self.other, "approve", member_id=member.pk).status_code, 403)
        self.action(self.captain, "approve", member_id=member.pk)
        self.assertEqual(self.membership().status, "active")
        self.assertIsNotNone(self.membership().joined_at)

    def test_invitation_can_only_be_accepted_by_recipient(self):
        self.action(self.captain, "invite", nickname="pLaYeR")
        member = self.membership()
        self.assertEqual(member.status, "invited")
        self.action(self.other, "accept_invite", member_id=member.pk, player_id=self.player.pk)
        self.assertEqual(self.membership().status, "invited")
        self.action(self.player, "accept_invite")
        self.assertEqual(self.membership().status, "active")
        self.action(self.captain, "reject", member_id=member.pk)
        self.assertEqual(self.membership().status, "active")

    def test_invitation_rejection_and_reinvite_reuses_membership(self):
        self.action(self.captain, "invite", nickname="Player")
        initial = self.membership().pk
        self.action(self.player, "reject_invite")
        self.assertEqual(self.membership().status, "rejected")
        self.action(self.captain, "invite", nickname="Player")
        self.assertEqual(self.membership().pk, initial)
        self.assertEqual(self.membership().status, "invited")

    def test_captain_must_transfer_before_leaving(self):
        self.action(self.captain, "leave")
        self.assertEqual(self.membership(self.captain).status, "active")
        self.action(self.player, "join")
        member = self.membership()
        self.action(self.captain, "transfer_captain", member_id=member.pk)
        self.team.refresh_from_db()
        self.assertEqual(self.team.captain_id, self.captain.pk)
        self.action(self.captain, "approve", member_id=member.pk)
        self.action(self.captain, "transfer_captain", member_id=member.pk)
        self.team.refresh_from_db()
        self.assertEqual(self.team.captain_id, self.player.pk)
        self.action(self.captain, "leave")
        self.assertEqual(self.membership(self.captain).status, "left")
        self.assertEqual(self.action(self.captain, "invite", nickname="Other").status_code, 403)

    def test_remove_only_active_member_and_self_leave_is_scoped(self):
        self.action(self.player, "join")
        member = self.membership()
        self.action(self.captain, "approve", member_id=member.pk)
        self.action(self.other, "leave", member_id=member.pk)
        self.assertEqual(self.membership().status, "active")
        self.action(self.captain, "remove", member_id=member.pk)
        self.assertEqual(self.membership().status, "left")
        self.assertIsNotNone(self.membership().left_at)

    def test_cross_team_member_id_cannot_be_modified(self):
        other_team = Team.objects.create(name="Foreign", tag="X", captain=self.other)
        member = TeamMember.objects.create(team=other_team, player=self.player, status="pending")
        self.assertEqual(self.action(self.captain, "approve", member_id=member.pk).status_code, 404)
        member.refresh_from_db()
        self.assertEqual(member.status, "pending")

    def test_mutations_require_post_authentication_and_csrf(self):
        url = reverse("team_action", args=[self.team.pk])
        self.assertEqual(self.client.post(url, {"action": "join"}).status_code, 302)
        self.client.force_login(self.player)
        self.assertEqual(self.client.get(url, {"action": "join"}).status_code, 405)
        secured = Client(enforce_csrf_checks=True)
        secured.force_login(self.player)
        self.assertEqual(secured.post(url, {"action": "join"}).status_code, 403)
        self.assertFalse(self.team.memberships.filter(player=self.player).exists())

    @override_settings(TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "OPTIONS": {"loaders": [("django.template.loaders.locmem.Loader", {
        "community/team_detail.html": "{{ team.name }}",
        "community/team_list.html": "{{ query }}",
        "community/player_list.html": "{{ query }}",
        "community/player_detail.html": "{{ player.nickname }}",
        "community/dashboard.html": "dashboard",
    })]}}])
    def test_public_lists_profiles_and_private_requests(self):
        self.action(self.player, "join")
        self.client.logout()
        response = self.client.get(reverse("team_list"), {"q": "first"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["teams"]), [self.team])
        response = self.client.get(reverse("player_list"), {"q": "play"})
        self.assertEqual(list(response.context["players"]), [self.player])
        response = self.client.get(reverse("team_detail", args=[self.team.pk]))
        self.assertFalse(response.context["can_manage"])
        self.assertFalse(response.context["requests"].exists())
        response = self.client.get(reverse("player_detail", args=[self.player.pk]))
        self.assertEqual(response.status_code, 200)
        self.client.force_login(self.captain)
        response = self.client.get(reverse("team_detail", args=[self.team.pk]))
        self.assertTrue(response.context["can_manage"])
        self.assertEqual(response.context["requests"].count(), 1)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["teams"]), [self.team])

    def test_match_history_remains_with_player_after_leaving_team(self):
        from .community import player_matches
        tournament = Tournament.objects.create(name="Cup", slug="cup", organizer=self.captain, game="CS2", starts_at=timezone.now(), ends_at=timezone.now())
        rival = Team.objects.create(name="Rival", tag="R", captain=self.other)
        TeamMember.objects.create(team=self.team, player=self.player, status="left")
        match = Match.objects.create(tournament=tournament, team_a=self.team, team_b=rival, status="finished", score_a=2, score_b=0, participants_snapshot={"a": [self.player.pk], "b": [self.other.pk]})
        self.assertEqual(list(player_matches(self.player)), [match])
        self.assertNotIn(match, player_matches(self.captain))
