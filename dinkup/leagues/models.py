import random
from datetime import datetime, timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

# No look-alike characters (0/O, 1/I/L) so codes are quick to type on a phone.
CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def random_code(length=4):
    return "".join(random.choice(CODE_CHARS) for _ in range(length))


class League(models.Model):
    LEVELS = [("BEG", "Beginner"), ("INT", "Intermediate"), ("ADV", "Advanced")]
    DIVISIONS = [("WOM", "Women's"), ("MEN", "Men's"), ("MIX", "Mixed"), ("SCR", "Scramble")]
    EVENT_TYPES = [("league", "League"), ("tournament", "Tournament")]
    PARTNER_MODES = [
        ("fixed", "Set partners (same doubles team all night)"),
        ("rotate", "Rotating partners (play with everyone)"),
    ]

    name = models.CharField(max_length=80)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_leagues")
    co_admins = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="co_admin_leagues")

    event_type = models.CharField("What is this?", max_length=12, choices=EVENT_TYPES, default="league")
    level = models.CharField(max_length=3, choices=LEVELS, default="INT")
    division = models.CharField(max_length=3, choices=DIVISIONS, default="MIX")
    partner_mode = models.CharField("Partner format", max_length=6, choices=PARTNER_MODES, default="rotate")

    max_players = models.PositiveIntegerField(
        "Number of players", default=16, validators=[MinValueValidator(4), MaxValueValidator(64)]
    )
    num_courts = models.PositiveIntegerField(
        "Number of courts", default=4, validators=[MinValueValidator(1), MaxValueValidator(8)]
    )
    games_per_player = models.PositiveIntegerField(
        "Games per player", null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(30)],
        help_text="Leave blank and DinkUp makes sure everyone plays everyone.",
    )
    game_minutes = models.PositiveIntegerField(
        "Minutes per game", default=15, validators=[MinValueValidator(5), MaxValueValidator(60)]
    )
    points_to_win = models.PositiveIntegerField(
        "Points to win", default=11, validators=[MinValueValidator(5), MaxValueValidator(21)]
    )
    num_weeks = models.PositiveIntegerField(
        "Number of weeks / play days", default=1, validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="1 = a one-day event. Week 1 matchups repeat every week after that (in a new order).",
    )
    start_date = models.DateField("First play date")
    start_time = models.TimeField("Start time", default="18:00")

    join_code = models.CharField(max_length=16, unique=True, editable=False)
    spectator_code = models.CharField(max_length=16, unique=True, editable=False)

    scores_locked = models.BooleanField(default=False)
    auto_lock = models.BooleanField(
        "Yes, lock scores automatically after each play night", default=True,
    )
    schedule_generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "name"]

    def __str__(self):
        return self.name

    # ---------- codes ----------
    def _new_unique_code(self, prefix):
        while True:
            code = f"{prefix}{random_code()}"
            if not League.objects.filter(models.Q(join_code=code) | models.Q(spectator_code=code)).exists():
                return code

    def save(self, *args, **kwargs):
        if self.division == "SCR":
            self.partner_mode = "rotate"  # scrambles always rotate partners
        if not self.join_code:
            # Unique by level + division, e.g. INTMIX7K4Q
            self.join_code = self._new_unique_code(f"{self.level}{self.division}")
        if not self.spectator_code:
            self.spectator_code = self._new_unique_code("WATCH")
        super().save(*args, **kwargs)

    def new_codes(self):
        self.join_code = ""
        self.spectator_code = ""
        self.save()

    # ---------- permissions ----------
    def is_admin(self, user):
        if not user.is_authenticated:
            return False
        return user.id == self.owner_id or self.co_admins.filter(id=user.id).exists()

    # ---------- labels ----------
    @property
    def label(self):
        return f"{self.get_level_display()} · {self.get_division_display()}"

    @property
    def is_teams(self):
        return self.partner_mode == "fixed"

    @property
    def win_by_two_always(self):
        return self.event_type == "tournament"

    # ---------- dates & times ----------
    def play_date(self, week):
        return self.start_date + timedelta(weeks=week - 1)

    def round_time(self, round_number):
        start = datetime.combine(self.start_date, self.start_time)
        return (start + timedelta(minutes=self.game_minutes * (round_number - 1))).time()

    def match_is_locked(self, match):
        if self.scores_locked:
            return True
        if self.auto_lock:
            return timezone.localdate() > self.play_date(match.week)
        return False

    @property
    def end_date(self):
        return self.play_date(self.num_weeks)


class Team(models.Model):
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=80, blank=True)

    def __str__(self):
        return self.name or " & ".join(p.name for p in self.players.all())

    @property
    def display(self):
        return " & ".join(p.name for p in self.players.all()) or self.name


class Player(models.Model):
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="players")
    name = models.CharField(max_length=60)
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="players")
    self_joined = models.BooleanField(default=False)
    pin = models.CharField(max_length=4, blank=True,
                           help_text="4-digit PIN the player uses to sign back in. Blank until they first join.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def set_new_pin(self):
        self.pin = f"{random.randint(0, 9999):04d}"
        self.save(update_fields=["pin"])
        return self.pin

    def __str__(self):
        return self.name


class Match(models.Model):
    STAGES = [("rr", "Round robin"), ("bracket", "Bracket")]

    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="matches")
    stage = models.CharField(max_length=8, choices=STAGES, default="rr")
    week = models.PositiveIntegerField(default=1)
    round_number = models.PositiveIntegerField(default=1)
    court = models.PositiveIntegerField(default=1)
    bracket_round = models.PositiveIntegerField(null=True, blank=True)
    bracket_slot = models.PositiveIntegerField(null=True, blank=True)

    a1 = models.ForeignKey(Player, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    a2 = models.ForeignKey(Player, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    b1 = models.ForeignKey(Player, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    b2 = models.ForeignKey(Player, null=True, blank=True, on_delete=models.CASCADE, related_name="+")

    score_a = models.PositiveIntegerField(null=True, blank=True)
    score_b = models.PositiveIntegerField(null=True, blank=True)
    reported_by = models.CharField(max_length=60, blank=True)
    reported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["stage", "week", "round_number", "court"]

    @property
    def side_a(self):
        return [p for p in (self.a1, self.a2) if p]

    @property
    def side_b(self):
        return [p for p in (self.b1, self.b2) if p]

    @property
    def side_a_names(self):
        return " & ".join(p.name for p in self.side_a) or "TBD"

    @property
    def side_b_names(self):
        return " & ".join(p.name for p in self.side_b) or "TBD"

    @property
    def player_ids(self):
        return {pid for pid in (self.a1_id, self.a2_id, self.b1_id, self.b2_id) if pid}

    @property
    def is_complete(self):
        return self.score_a is not None and self.score_b is not None

    @property
    def winner(self):
        if not self.is_complete:
            return None
        return "a" if self.score_a > self.score_b else "b"

    @property
    def play_date(self):
        return self.league.play_date(self.week)

    @property
    def start_time(self):
        return self.league.round_time(self.round_number)

    @property
    def locked(self):
        return self.league.match_is_locked(self)

    @property
    def win_by_two(self):
        return self.stage == "bracket" or self.league.win_by_two_always

    def side_of(self, player_id):
        if player_id in (self.a1_id, self.a2_id):
            return "a"
        if player_id in (self.b1_id, self.b2_id):
            return "b"
        return None
