from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import League


class SignupForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        fields = ("username",)


class LeagueForm(forms.ModelForm):
    class Meta:
        model = League
        fields = [
            "name", "event_type", "level", "division", "partner_mode",
            "max_players", "num_courts", "games_per_player", "game_minutes", "points_to_win",
            "num_weeks", "start_date", "start_time", "auto_lock",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Tuesday Night Mixed"}),
            "event_type": forms.RadioSelect,
            "level": forms.RadioSelect,
            "division": forms.RadioSelect,
            "partner_mode": forms.RadioSelect,
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "max_players": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "num_courts": forms.NumberInput(attrs={"inputmode": "numeric", "max": 8}),
            "games_per_player": forms.NumberInput(attrs={"inputmode": "numeric", "placeholder": "Auto"}),
            "game_minutes": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "points_to_win": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "num_weeks": forms.NumberInput(attrs={"inputmode": "numeric"}),
        }

    def clean_num_courts(self):
        courts = self.cleaned_data["num_courts"]
        if courts > 8:
            raise forms.ValidationError("8 courts is the limit.")
        return courts


class PlayerBulkForm(forms.Form):
    names = forms.CharField(
        label="Player names",
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": "One per line.\nFor set partners: Sam Lee / Jo Park"}),
    )


class CoAdminForm(forms.Form):
    username = forms.CharField(label="Co-admin's username", max_length=150,
                               widget=forms.TextInput(attrs={"placeholder": "Their DinkUp username"}))


class CodeForm(forms.Form):
    code = forms.CharField(
        label="League code", max_length=16,
        widget=forms.TextInput(attrs={"autocapitalize": "characters", "autocomplete": "off",
                                      "placeholder": "e.g. INTMIX7K4Q", "class": "code-input"}),
    )


class JoinForm(forms.Form):
    name = forms.CharField(label="Your name", max_length=60,
                           widget=forms.TextInput(attrs={"autocomplete": "name", "placeholder": "First & last name"}))
    partner_name = forms.CharField(label="Your partner's name", max_length=60, required=False)
    pin = forms.CharField(label="Your PIN", max_length=4, required=False,
                          widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off",
                                                        "placeholder": "4 digits", "pattern": "[0-9]*"}))


class ScoreForm(forms.Form):
    score_a = forms.IntegerField(min_value=0, max_value=99, widget=forms.NumberInput(attrs={"inputmode": "numeric"}))
    score_b = forms.IntegerField(min_value=0, max_value=99, widget=forms.NumberInput(attrs={"inputmode": "numeric"}))
    confirm = forms.BooleanField(label="Yes, this score is correct", required=True)


class BracketForm(forms.Form):
    size = forms.TypedChoiceField(
        label="How many teams advance?", coerce=int,
        choices=[(2, "Top 2 (final only)"), (4, "Top 4 (semis + final)"), (8, "Top 8 (quarters, semis, final)")],
        initial=4, widget=forms.RadioSelect,
    )
