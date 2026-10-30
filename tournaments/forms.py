from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django import forms

from .models import Match, User


class AdminUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "nickname", "role")


class AdminUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


class AdminMatchForm(forms.ModelForm):
    class Meta:
        model = Match
        fields = "__all__"

    def clean(self):
        data = super().clean()
        if not self.instance.pk:
            return data
        old = Match.objects.get(pk=self.instance.pk)
        changed = (data.get("score_a"), data.get("score_b"), data.get("status")) != (old.score_a, old.score_b, old.status)
        if changed and old.tournament.status in ("live", "finished"):
            if old.is_bye:
                raise forms.ValidationError("Проход без игры не требует ручного результата.")
            descendant_id = old.next_match_id
            while descendant_id:
                descendant = Match.objects.get(pk=descendant_id)
                if descendant.status != "planned" or descendant.score_a is not None or descendant.participants_snapshot:
                    raise forms.ValidationError("Следующий матч уже начался. Изменение предыдущего результата заблокировано.")
                descendant_id = descendant.next_match_id
        return data
