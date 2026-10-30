from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import Team, User


class RegistrationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("email", "nickname")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Этот email уже зарегистрирован.")
        return email

    def clean_nickname(self):
        nickname = self.cleaned_data["nickname"].strip()
        if User.objects.filter(nickname__iexact=nickname).exists():
            raise forms.ValidationError("Этот ник уже занят.")
        return nickname

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.PLAYER
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
        return user


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("nickname", "game_id", "position", "avatar")

    def clean_nickname(self):
        nickname = self.cleaned_data["nickname"].strip()
        if User.objects.filter(nickname__iexact=nickname).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Этот ник уже занят.")
        return nickname


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ("name", "tag", "logo", "contacts", "color")

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if Team.objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Команда с таким названием уже существует.")
        return name
