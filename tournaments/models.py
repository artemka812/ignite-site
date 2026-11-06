import re
from urllib.parse import parse_qs, urlencode, urlparse

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils import timezone
from django.urls import reverse


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Нужен email.")
        user = self.model(email=self.normalize_email(email).strip().lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("Администратору нужны is_staff и is_superuser.")
        return self.create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username)


class User(AbstractUser):
    class Role(models.TextChoices):
        PLAYER = "player", "Игрок"
        ORGANIZER = "organizer", "Организатор"

    username = None
    email = models.EmailField("email", unique=True)
    nickname = models.CharField("ник", max_length=40, unique=True)
    role = models.CharField("основная роль", max_length=16, choices=Role.choices, default=Role.PLAYER)
    game_id = models.CharField("игровой ID", max_length=100, blank=True)
    position = models.CharField("позиция в игре", max_length=60, blank=True)
    avatar = models.URLField("ссылка на аватар", blank=True)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nickname"]
    objects = UserManager()

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"
        constraints = [models.UniqueConstraint(Lower("email"), name="unique_email_case_insensitive")]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("player_detail", kwargs={"pk": self.pk})

    def __str__(self):
        return self.nickname or self.email


class Team(models.Model):
    class Color(models.TextChoices):
        LIME = "lime", "Лаймовый"
        BLUE = "blue", "Голубой"
        CORAL = "coral", "Коралловый"
        VIOLET = "violet", "Фиолетовый"

    name = models.CharField("название", max_length=100, unique=True)
    tag = models.CharField("короткое обозначение", max_length=5)
    captain = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="captained_teams", verbose_name="капитан")
    logo = models.URLField("ссылка на логотип", blank=True)
    contacts = models.CharField("контакты", max_length=200, blank=True)
    archive_note = models.TextField("примечание к архивному составу", blank=True)
    color = models.CharField("цвет", max_length=10, choices=Color.choices, default=Color.LIME)
    players = models.ManyToManyField(settings.AUTH_USER_MODEL, through="TeamMember", related_name="teams", verbose_name="игроки")

    class Meta:
        ordering = ["id"]
        verbose_name = "команда"
        verbose_name_plural = "команды"

    def get_absolute_url(self):
        return reverse("team_detail", kwargs={"pk": self.pk})

    def __str__(self):
        return self.name


class TeamMember(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Заявка"
        INVITED = "invited", "Приглашение"
        ACTIVE = "active", "Участник"
        REJECTED = "rejected", "Отклонено"
        LEFT = "left", "Вышел из команды"

    player = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships", verbose_name="игрок")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships", verbose_name="команда")
    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.PENDING)
    joined_at = models.DateTimeField("дата вступления", null=True, blank=True)
    left_at = models.DateTimeField("дата выхода", null=True, blank=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "участник команды"
        verbose_name_plural = "составы команд"
        constraints = [
            models.UniqueConstraint(fields=["player", "team"], name="unique_player_team"),
            models.CheckConstraint(condition=Q(left_at__isnull=True) | Q(joined_at__isnull=True) | Q(left_at__gte=F("joined_at")), name="membership_dates_ordered"),
        ]

    def __str__(self):
        return f"{self.player} — {self.team}"


class Tournament(models.Model):
    class Game(models.TextChoices):
        CS2 = "CS2", "Counter-Strike 2"
        DOTA2 = "DOTA2", "Dota 2"
        VALORANT = "VALORANT", "Valorant"

    class Format(models.TextChoices):
        SINGLE = "single", "Олимпийская система"
        ROUND_ROBIN = "round_robin", "Круговая система"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        SOON = "soon", "Скоро"
        LIVE = "live", "Идёт турнир"
        FINISHED = "finished", "Завершён"

    name = models.CharField("название", max_length=120)
    slug = models.SlugField("адрес страницы", unique=True)
    subtitle = models.CharField("подзаголовок", max_length=180, blank=True)
    source_url = models.URLField("источник архивных данных", blank=True)
    description = models.TextField("описание", blank=True)
    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="organized_tournaments", verbose_name="организатор")
    game = models.CharField("дисциплина", max_length=10, choices=Game.choices)
    format = models.CharField("формат", max_length=15, choices=Format.choices, default=Format.SINGLE)
    starts_at = models.DateTimeField("начало")
    ends_at = models.DateTimeField("окончание")
    team_limit = models.PositiveSmallIntegerField("лимит команд", default=4, validators=[MinValueValidator(2)])
    team_size = models.PositiveSmallIntegerField("игроков в команде", default=5, validators=[MinValueValidator(1)])
    rules = models.TextField("правила", blank=True)
    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.DRAFT)
    accent = models.CharField("цвет", max_length=10, choices=Team.Color.choices, default=Team.Color.LIME)
    registration_open = models.BooleanField("приём заявок открыт", default=True)
    edition = models.PositiveSmallIntegerField("номер турнира в сезоне", default=1)
    teams = models.ManyToManyField(Team, through="TournamentTeam", related_name="tournaments", verbose_name="команды")

    class Meta:
        ordering = ["edition", "id"]
        verbose_name = "турнир"
        verbose_name_plural = "турниры"
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gte=F("starts_at")), name="tournament_dates_ordered"),
            models.CheckConstraint(condition=Q(team_limit__gte=2), name="tournament_min_two_teams"),
            models.CheckConstraint(condition=Q(team_size__gte=1), name="tournament_positive_team_size"),
        ]

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at < self.starts_at:
            raise ValidationError({"ends_at": "Окончание не может быть раньше начала."})

    def get_absolute_url(self):
        return reverse("tournament_detail", kwargs={"slug": self.slug})

    def __str__(self):
        return self.name


class TournamentTeam(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает рассмотрения"
        APPROVED = "approved", "Принята"
        REJECTED = "rejected", "Отклонена"

    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="entries", verbose_name="турнир")
    team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="entries", verbose_name="команда")
    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.PENDING)
    seed = models.PositiveSmallIntegerField("номер посева", null=True, blank=True, validators=[MinValueValidator(1)])
    applied_at = models.DateTimeField("дата заявки", default=timezone.now)

    class Meta:
        ordering = ["seed", "id"]
        verbose_name = "заявка на турнир"
        verbose_name_plural = "заявки на турниры"
        constraints = [
            models.UniqueConstraint(fields=["tournament", "team"], name="unique_tournament_team"),
            models.UniqueConstraint(fields=["tournament", "seed"], condition=Q(status="approved", seed__isnull=False), name="unique_approved_seed"),
        ]

    def clean(self):
        super().clean()
        if self.status == self.Status.APPROVED and self.tournament_id:
            accepted = type(self).objects.filter(tournament_id=self.tournament_id, status=self.Status.APPROVED).exclude(pk=self.pk).count()
            if accepted >= self.tournament.team_limit:
                raise ValidationError({"status": "Лимит команд этого турнира уже заполнен."})

    def __str__(self):
        return f"{self.team} → {self.tournament}"


class Match(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", "Запланирован"
        LIVE = "live", "Идёт матч"
        FINISHED = "finished", "Завершён"

    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="matches", verbose_name="турнир")
    team_a = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="matches_as_a", null=True, blank=True, verbose_name="первая команда")
    team_b = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="matches_as_b", null=True, blank=True, verbose_name="вторая команда")
    round = models.PositiveSmallIntegerField("раунд", default=1, validators=[MinValueValidator(1)])
    position = models.PositiveSmallIntegerField("номер в раунде", default=1, validators=[MinValueValidator(1)])
    best_of = models.PositiveSmallIntegerField("число карт (BO)", choices=[(1, "BO1"), (3, "BO3"), (5, "BO5")], default=3)
    scheduled_at = models.DateTimeField("время матча", null=True, blank=True)
    date_only = models.BooleanField("известна только дата", default=False)
    source_url = models.URLField("источник результата и составов", blank=True)
    score_a = models.PositiveSmallIntegerField("счёт первой команды", null=True, blank=True)
    score_b = models.PositiveSmallIntegerField("счёт второй команды", null=True, blank=True)
    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.PLANNED)
    is_bye = models.BooleanField("проход без соперника", default=False)
    participants_snapshot = models.JSONField("составы на начало матча", default=dict, blank=True)
    next_match = models.ForeignKey("self", on_delete=models.RESTRICT, related_name="previous_matches", null=True, blank=True, verbose_name="следующий матч")
    next_slot = models.CharField("место в следующем матче", max_length=1, choices=[("a", "Первая команда"), ("b", "Вторая команда")], blank=True)

    class Meta:
        ordering = ["round", "position", "id"]
        verbose_name = "матч"
        verbose_name_plural = "матчи"
        constraints = [
            models.UniqueConstraint(fields=["tournament", "round", "position"], name="unique_match_position"),
            models.UniqueConstraint(fields=["next_match", "next_slot"], condition=Q(next_match__isnull=False), name="unique_next_match_slot"),
            models.CheckConstraint(condition=Q(team_a__isnull=True) | Q(team_b__isnull=True) | ~Q(team_a=F("team_b")), name="different_match_teams"),
            models.CheckConstraint(condition=Q(next_match__isnull=True, next_slot="") | Q(next_match__isnull=False, next_slot__in=["a", "b"]), name="next_match_has_slot"),
            models.CheckConstraint(condition=Q(score_a__isnull=True, score_b__isnull=True) | Q(score_a__isnull=False, score_b__isnull=False), name="both_scores_or_none"),
        ]

    def get_absolute_url(self):
        return reverse("match_detail", kwargs={"pk": self.pk})

    @property
    def winner(self):
        if self.is_bye and self.status == self.Status.FINISHED:
            return self.team_a or self.team_b
        if self.status != self.Status.FINISHED or self.score_a is None or self.score_b is None:
            return None
        if self.score_a == self.score_b:
            return None
        return self.team_a if self.score_a > self.score_b else self.team_b

    def clean(self):
        super().clean()
        errors = {}
        if self.team_a_id and self.team_a_id == self.team_b_id:
            errors["team_b"] = "Команда не может играть сама с собой."
        for side in ("team_a", "team_b"):
            team_id = getattr(self, f"{side}_id")
            if team_id and self.tournament_id and not TournamentTeam.objects.filter(tournament_id=self.tournament_id, team_id=team_id, status=TournamentTeam.Status.APPROVED).exists():
                errors[side] = "Команда должна быть принята в этот турнир."
        if (self.score_a is None) != (self.score_b is None):
            errors["score_b"] = "Укажите оба значения счёта или оставьте оба пустыми."
        if self.is_bye:
            if self.round != 1 or bool(self.team_a_id) == bool(self.team_b_id) or self.status != self.Status.FINISHED or self.score_a is not None or self.score_b is not None:
                errors["is_bye"] = "Проход без соперника возможен только в первом раунде с одной командой, без счёта."
        if not self.is_bye and (self.score_a is not None or self.status != self.Status.PLANNED) and not (self.team_a_id and self.team_b_id):
            errors["status"] = "Для счёта или начатого матча нужны оба соперника."
        needed = self.best_of // 2 + 1
        if self.score_a is not None and self.score_b is not None:
            if max(self.score_a, self.score_b) > needed or min(self.score_a, self.score_b) >= needed:
                errors["score_a"] = f"Недопустимый счёт для BO{self.best_of}."
            if self.status == self.Status.FINISHED and (max(self.score_a, self.score_b) != needed or self.score_a == self.score_b):
                errors["score_a"] = f"Победителю нужны {needed} победы по картам."
            if self.status != self.Status.FINISHED and max(self.score_a, self.score_b) == needed:
                errors["status"] = "При победном счёте матч нужно завершить."
        elif self.status == self.Status.FINISHED and not self.is_bye:
            errors["score_a"] = "Для завершённого матча нужен счёт."
        if self.next_match_id:
            if self.next_match_id == self.pk:
                errors["next_match"] = "Матч не может ссылаться на себя."
            elif self.next_match.tournament_id != self.tournament_id or self.next_match.round <= self.round:
                errors["next_match"] = "Нужен более поздний раунд того же турнира."
        if self.tournament_id and self.tournament.format == Tournament.Format.ROUND_ROBIN and self.is_bye:
            errors["is_bye"] = "В круговом турнире нет матчей без соперника."
        if self.tournament_id and self.tournament.format == Tournament.Format.ROUND_ROBIN and self.next_match_id:
            errors["next_match"] = "В круговом формате продвижение в следующий матч не используется."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.tournament}: {self.team_a or '?'} — {self.team_b or '?'}"


class Stream(models.Model):
    class Platform(models.TextChoices):
        YOUTUBE = "youtube", "YouTube"
        TWITCH = "twitch", "Twitch"

    class Status(models.TextChoices):
        SOON = "soon", "Скоро"
        LIVE = "live", "Идёт эфир"
        RECORDING = "recording", "Запись"

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="streams", verbose_name="матч")
    platform = models.CharField("платформа", max_length=10, choices=Platform.choices)
    url = models.URLField("ссылка")
    title = models.CharField("название видео", max_length=180, blank=True)
    embed_allowed = models.BooleanField("автор разрешает встраивание", default=True)
    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.SOON)

    class Meta:
        verbose_name = "трансляция"
        verbose_name_plural = "трансляции"

    def _video(self):
        domains = {self.Platform.YOUTUBE: ("youtube.com", "www.youtube.com", "youtu.be"), self.Platform.TWITCH: ("twitch.tv", "www.twitch.tv")}
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or parsed.hostname not in domains.get(self.platform, ()) or parsed.username or parsed.password or parsed.netloc != parsed.hostname:
            return None
        parts = parsed.path.strip("/").split("/")
        if self.platform == self.Platform.YOUTUBE:
            video = None
            if parsed.hostname == "youtu.be" and len(parts) == 1:
                video = parts[0]
            elif parts == ["watch"]:
                video = parse_qs(parsed.query).get("v", [None])[0]
            elif len(parts) == 2 and parts[0] in ("embed", "live", "shorts"):
                video = parts[1]
            return ("video", video) if video and re.fullmatch(r"[A-Za-z0-9_-]{11}", video) else None
        if len(parts) == 2 and parts[0] == "videos" and re.fullmatch(r"[0-9]+", parts[1]):
            return ("video", "v" + parts[1])
        if len(parts) == 1 and re.fullmatch(r"[A-Za-z0-9_]{1,25}", parts[0]) and parts[0].lower() not in ("directory", "downloads", "settings", "videos"):
            return ("channel", parts[0])
        return None

    def clean(self):
        super().clean()
        if not self._video():
            raise ValidationError({"url": "Укажите HTTPS-ссылку на видео YouTube, канал или запись Twitch."})

    def embed_url(self, host="localhost"):
        if not self.embed_allowed:
            return ""
        video = self._video()
        if not video:
            return ""
        if self.platform == self.Platform.YOUTUBE:
            return "https://www.youtube-nocookie.com/embed/" + video[1]
        parent = host.split(":", 1)[0]
        if not re.fullmatch(r"[A-Za-z0-9.-]+", parent):
            return ""
        return "https://player.twitch.tv/?" + urlencode({video[0]: video[1], "parent": parent, "autoplay": "false"})

    def __str__(self):
        return f"{self.get_platform_display()} — {self.match}"


class MatchResultLog(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="result_logs", verbose_name="матч")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="result_changes", verbose_name="автор изменения")
    old_score_a = models.PositiveSmallIntegerField("прежний счёт первой команды", null=True, blank=True)
    old_score_b = models.PositiveSmallIntegerField("прежний счёт второй команды", null=True, blank=True)
    new_score_a = models.PositiveSmallIntegerField("новый счёт первой команды", null=True, blank=True)
    new_score_b = models.PositiveSmallIntegerField("новый счёт второй команды", null=True, blank=True)
    changed_at = models.DateTimeField("время изменения", default=timezone.now)

    class Meta:
        ordering = ["-changed_at", "-id"]
        verbose_name = "изменение счёта"
        verbose_name_plural = "история счёта"

    def __str__(self):
        return f"Матч {self.match_id}: {self.old_score_a}:{self.old_score_b} → {self.new_score_a}:{self.new_score_b}"


class MatchConfirmation(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="confirmations", verbose_name="матч")
    team = models.ForeignKey(Team, on_delete=models.PROTECT, verbose_name="команда")
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="капитан")
    result_revision = models.PositiveBigIntegerField(default=0, verbose_name="версия результата")
    score_a = models.PositiveSmallIntegerField()
    score_b = models.PositiveSmallIntegerField()
    confirmed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "подтверждение результата"
        verbose_name_plural = "подтверждения результатов"
        constraints = [models.UniqueConstraint(fields=["match", "team"], name="one_confirmation_per_team")]
