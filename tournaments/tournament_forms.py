from django import forms
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from uuid import uuid4

from .models import Match, Stream, Tournament, TournamentTeam


class LocalDateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"


class TournamentForm(forms.ModelForm):
    class Meta:
        model = Tournament
        fields = ("name", "slug", "subtitle", "description", "game", "format", "starts_at", "ends_at", "team_limit", "team_size", "rules")
        widgets = {
            "starts_at": LocalDateTimeInput(format="%Y-%m-%dT%H:%M"),
            "ends_at": LocalDateTimeInput(format="%Y-%m-%dT%H:%M"),
            "description": forms.Textarea(attrs={"rows": 3}),
            "rules": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["slug"].help_text = "Короткий адрес латиницей. Можно оставить пустым."
        for name in ("starts_at", "ends_at"):
            self.fields[name].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"]
            self.fields[name].help_text = "Московское время."
        if self.instance.pk and self.instance.matches.exists():
            for name in ("game", "format", "team_limit", "team_size"):
                self.fields[name].disabled = True
        if self.instance.pk:
            self.fields["slug"].disabled = True

    def clean_slug(self):
        value = self.cleaned_data.get("slug")
        if value:
            if Tournament.objects.filter(slug=value).exclude(pk=self.instance.pk).exists():
                raise ValidationError("Такой адрес уже занят.")
            return value
        base = slugify(self.cleaned_data.get("name", ""))[:100] or "tournament"
        value = base
        while Tournament.objects.filter(slug=value).exclude(pk=self.instance.pk).exists():
            value = f"{base}-{uuid4().hex[:6]}"
        return value


class MatchEditForm(forms.Form):
    scheduled_at = forms.DateTimeField(label="Время матча", required=False, widget=LocalDateTimeInput(format="%Y-%m-%dT%H:%M"), input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"], help_text="Московское время.")
    score_a = forms.IntegerField(label="Счёт первой команды", min_value=0, required=False)
    score_b = forms.IntegerField(label="Счёт второй команды", min_value=0, required=False)
    status = forms.ChoiceField(label="Статус", choices=Match.Status.choices)

    def __init__(self, *args, match, **kwargs):
        self.match = match
        kwargs.setdefault("initial", {name: getattr(match, name) for name in ("scheduled_at", "score_a", "score_b", "status")})
        super().__init__(*args, **kwargs)
        if match.status != Match.Status.PLANNED:
            self.fields["scheduled_at"].disabled = True
        if match.tournament.status not in (Tournament.Status.LIVE, Tournament.Status.FINISHED):
            for name in ("score_a", "score_b", "status"):
                self.fields[name].disabled = True

    def clean(self):
        data = super().clean()
        if (data.get("score_a") is None) != (data.get("score_b") is None):
            raise ValidationError("Укажите оба значения счёта или оставьте оба пустыми.")
        return data


class StreamForm(forms.ModelForm):
    class Meta:
        model = Stream
        fields = ("platform", "url", "status")


class PairingForm(forms.Form):
    team_a = forms.ModelChoiceField(label="Первая команда", queryset=TournamentTeam.objects.none())
    team_b = forms.ModelChoiceField(label="Вторая команда", queryset=TournamentTeam.objects.none(), required=False)

    def __init__(self, *args, match, **kwargs):
        super().__init__(*args, **kwargs)
        teams = match.tournament.teams.filter(entries__tournament=match.tournament, entries__status="approved").distinct()
        for name in ("team_a", "team_b"):
            self.fields[name].queryset = teams
            self.fields[name].initial = getattr(match, name)
        self.fields["team_b"].help_text = "Без соперника — автоматический проход. При выборе занятой команды соперники поменяются местами."

    def clean(self):
        data = super().clean()
        if data.get("team_a") and data.get("team_a") == data.get("team_b"):
            raise ValidationError("Выберите разные команды.")
        return data
