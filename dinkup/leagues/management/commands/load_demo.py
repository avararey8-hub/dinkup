"""
python manage.py load_demo

Creates an admin account (demo / pickle123) and two sample leagues with players,
a schedule, and some scores — handy for a class presentation.
"""
import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from leagues.models import League, Player, Team
from leagues.services import generate_schedule, save_score

NAMES = ["Avery Cole", "Jordan Reyes", "Taylor Brooks", "Morgan Diaz", "Riley Hart", "Casey Nguyen",
         "Jamie Fox", "Quinn Patel", "Drew Carter", "Skyler Ross", "Parker Lane", "Reese Kim"]


class Command(BaseCommand):
    help = "Load a demo admin and sample leagues."

    def handle(self, *args, **opts):
        rng = random.Random(7)
        user, created = User.objects.get_or_create(username="demo")
        if created:
            user.set_password("pickle123")
            user.save()
        League.objects.filter(owner=user).delete()
        today = timezone.localdate()

        # 1) Rotating-partner scramble: 7 players, 1 court, play with everyone
        scramble = League.objects.create(
            name="Friday Scramble", owner=user, event_type="league", level="BEG", division="SCR",
            max_players=7, num_courts=1, game_minutes=15, num_weeks=1, start_date=today,
        )
        for n in NAMES[:7]:
            Player.objects.create(league=scramble, name=n)
        generate_schedule(scramble, seed=1)

        # 2) 4-week intermediate mixed league, set partners, 3 courts
        mixed = League.objects.create(
            name="Tuesday Night Mixed", owner=user, event_type="league", level="INT", division="MIX",
            partner_mode="fixed", max_players=12, num_courts=3, num_weeks=4, start_date=today,
        )
        for i in range(0, 12, 2):
            t = Team.objects.create(league=mixed)
            Player.objects.create(league=mixed, name=NAMES[i], team=t)
            Player.objects.create(league=mixed, name=NAMES[i + 1], team=t)
        generate_schedule(mixed, seed=2)

        # Score the first few rounds so the standings look alive
        for league, rounds in ((scramble, 4), (mixed, 3)):
            for m in league.matches.filter(stage="rr", week=1, round_number__lte=rounds):
                loser = rng.randint(3, 9)
                a, b = (11, loser) if rng.random() < 0.5 else (loser, 11)
                save_score(m, a, b, "demo")

        self.stdout.write(self.style.SUCCESS(
            "Demo ready! Log in as  demo / pickle123\n"
            f"  Scramble join code: {scramble.join_code}   watch code: {scramble.spectator_code}\n"
            f"  Mixed league join code: {mixed.join_code}   watch code: {mixed.spectator_code}"
        ))
