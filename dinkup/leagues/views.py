import json
from collections import OrderedDict

import qrcode
import qrcode.image.svg
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import assistant
from .forms import (BracketForm, CoAdminForm, CodeForm, JoinForm, LeagueForm, PlayerBulkForm, ScoreForm,
                    SignupForm)
from .models import League, Match, Player, Team
from .services import (ScheduleError, bracket_rounds, clear_score, create_bracket, generate_schedule, preview,
                       save_score, standings, unscheduled_players, update_schedule, validate_score)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _admin_league(request, pk):
    league = get_object_or_404(League, pk=pk)
    if not league.is_admin(request.user):
        raise Http404("League not found")
    return league


def _session_player(request, league):
    pid = request.session.get("players", {}).get(str(league.id))
    if not pid:
        return None
    return Player.objects.filter(id=pid, league=league).first()


def _remember_player(request, player):
    players = request.session.get("players", {})
    players[str(player.league_id)] = player.id
    request.session["players"] = players


def _can_view(request, league):
    return (league.is_admin(request.user) or _session_player(request, league) is not None
            or league.id in request.session.get("watching", []))


def _schedule_by_round(matches):
    """Group matches as {(week, round): [matches]} for display."""
    grouped = OrderedDict()
    for m in matches:
        grouped.setdefault((m.week, m.round_number), []).append(m)
    return [{"week": w, "round": r, "matches": ms, "time": ms[0].start_time, "date": ms[0].play_date}
            for (w, r), ms in grouped.items()]


def _find_league_by_code(code):
    code = (code or "").strip().upper().replace(" ", "").replace("-", "")
    if not code:
        return None, None
    league = League.objects.filter(join_code=code).first()
    if league:
        return league, "join"
    league = League.objects.filter(spectator_code=code).first()
    if league:
        return league, "watch"
    return None, None


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------
def home(request):
    form = CodeForm(request.GET or None)
    if request.GET.get("code"):
        league, kind = _find_league_by_code(request.GET["code"])
        if kind == "join":
            return redirect("join_league", code=league.join_code)
        if kind == "watch":
            return redirect("watch", code=league.spectator_code)
        messages.warning(request, "We couldn't find that code. Double-check it with your league admin.")
    my_leagues = []
    ids = request.session.get("players", {})
    if ids:
        my_leagues = League.objects.filter(id__in=[int(k) for k in ids])
    return render(request, "leagues/home.html", {"form": form, "my_leagues": my_leagues})


def signup(request):
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Welcome to DinkUp! Create your first league.")
        return redirect("league_create")
    return render(request, "registration/signup.html", {"form": form})


# ---------------------------------------------------------------------------
# Admin: leagues
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    leagues = League.objects.filter(Q(owner=request.user) | Q(co_admins=request.user)).distinct()
    return render(request, "leagues/dashboard.html", {"leagues": leagues})


@login_required
def league_create(request):
    form = LeagueForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        league = form.save(commit=False)
        league.owner = request.user
        league.save()
        messages.success(request, "League created! Next, add your players.")
        return redirect("league_manage", pk=league.pk)
    return render(request, "leagues/league_form.html", {"form": form, "creating": True})


@login_required
def league_edit(request, pk):
    league = _admin_league(request, pk)
    form = LeagueForm(request.POST or None, instance=league)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Settings saved. If you changed players, courts, or games, rebuild the schedule.")
        return redirect("league_manage", pk=league.pk)
    return render(request, "leagues/league_form.html", {"form": form, "league": league, "creating": False})


@login_required
def league_manage(request, pk):
    league = _admin_league(request, pk)
    players = league.players.select_related("team")
    teams = league.teams.prefetch_related("players") if league.is_teams else []
    unpaired = players.filter(team__isnull=True) if league.is_teams else []
    ctx = {
        "league": league,
        "players": players,
        "teams": teams,
        "unpaired": unpaired,
        "preview": preview(league),
        "unscheduled": unscheduled_players(league),
        "player_form": PlayerBulkForm(),
        "coadmin_form": CoAdminForm(),
        "bracket_form": BracketForm(),
        "match_count": league.matches.filter(stage="rr").count(),
        "scored_count": league.matches.filter(stage="rr", score_a__isnull=False).count(),
        "join_url": request.build_absolute_uri(reverse("join_league", args=[league.join_code])),
        "watch_url": request.build_absolute_uri(reverse("watch", args=[league.spectator_code])),
        "tab": request.GET.get("tab", "overview"),
    }
    if ctx["tab"] in ("schedule", "standings", "bracket"):
        board_ctx = _board_context(league, ctx["tab"])
        board_ctx.pop("league")
        board_ctx.pop("tab")
        ctx.update(board_ctx)
    return render(request, "leagues/manage.html", ctx)


@login_required
@require_POST
def league_delete(request, pk):
    league = _admin_league(request, pk)
    if request.POST.get("confirm") != "yes":
        messages.warning(request, "Check the “Yes, delete” box to delete this league.")
        return redirect(reverse("league_manage", args=[pk]) + "?tab=settings")
    league.delete()
    messages.success(request, "League deleted.")
    return redirect("dashboard")


@login_required
@require_POST
def league_action(request, pk, action):
    league = _admin_league(request, pk)
    tab = "overview"
    if action == "generate":
        if league.matches.filter(score_a__isnull=False).exists() and request.POST.get("confirm") != "yes":
            messages.warning(request, "Some games already have scores. Check “Yes, rebuild” to start over.")
        else:
            try:
                n = generate_schedule(league)
                messages.success(request, f"Schedule ready: {n} games across {league.num_weeks} week(s).")
                tab = "schedule"
            except ScheduleError as e:
                messages.warning(request, str(e))
    elif action == "update":
        try:
            n = update_schedule(league)
            messages.success(request, f"Schedule updated. Scores were kept and {n} games were (re)planned so everyone plays.")
            tab = "schedule"
        except ScheduleError as e:
            messages.warning(request, str(e))
    elif action == "lock":
        league.scores_locked = True
        league.save(update_fields=["scores_locked"])
        messages.success(request, "Scores are locked. Players can no longer change them.")
    elif action == "unlock":
        league.scores_locked = False
        league.save(update_fields=["scores_locked"])
        messages.success(request, "Scores are unlocked.")
    elif action == "new_codes":
        league.new_codes()
        messages.success(request, "New join and watch codes created. The old ones no longer work.")
        tab = "share"
    elif action == "bracket":
        form = BracketForm(request.POST)
        tab = "bracket"
        if form.is_valid():
            try:
                create_bracket(league, form.cleaned_data["size"])
                messages.success(request, "Bracket created from the round robin standings.")
            except ScheduleError as e:
                messages.warning(request, str(e))
    elif action == "clear_bracket":
        league.matches.filter(stage="bracket").delete()
        messages.success(request, "Bracket cleared.")
        tab = "bracket"
    return redirect(reverse("league_manage", args=[pk]) + f"?tab={tab}")


# ---------------------------------------------------------------------------
# Admin: players, teams, co-admins
# ---------------------------------------------------------------------------
@login_required
@require_POST
def players_add(request, pk):
    league = _admin_league(request, pk)
    form = PlayerBulkForm(request.POST)
    if form.is_valid():
        added = 0
        existing = {n.lower() for n in league.players.values_list("name", flat=True)}
        for raw in form.cleaned_data["names"].splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.replace("&", "/").replace(",", "/").split("/") if p.strip()]
            if league.is_teams and len(parts) == 2:
                team = Team.objects.create(league=league)
                for name in parts:
                    Player.objects.create(league=league, name=name[:60], team=team)
                    added += 1
            else:
                for name in parts:
                    if name.lower() in existing:
                        continue
                    Player.objects.create(league=league, name=name[:60])
                    existing.add(name.lower())
                    added += 1
        total = league.players.count()
        messages.success(request, f"Added {added} player{'s' if added != 1 else ''}.")
        if total > league.max_players:
            messages.warning(request, f"You now have {total} players, more than your limit of {league.max_players}.")
        if league.schedule_generated_at:
            messages.info(request, "New players aren't on the schedule yet. Use “Add to schedule” on the Overview tab. "
                                   "It keeps the scores already entered.")
    return redirect(reverse("league_manage", args=[pk]) + "?tab=players")


@login_required
@require_POST
def player_remove(request, pk, player_id):
    league = _admin_league(request, pk)
    player = get_object_or_404(Player, pk=player_id, league=league)
    team = player.team
    player.delete()
    if team and team.players.count() == 0:
        team.delete()
    messages.success(request, f"Removed {player.name}.")
    return redirect(reverse("league_manage", args=[pk]) + "?tab=players")


@login_required
@require_POST
def player_reset_pin(request, pk, player_id):
    league = _admin_league(request, pk)
    player = get_object_or_404(Player, pk=player_id, league=league)
    player.pin = ""
    player.save(update_fields=["pin"])
    messages.success(request, f"{player.name}'s PIN was cleared. They'll get a new one the next time they join.")
    return redirect(reverse("league_manage", args=[pk]) + "?tab=players")


@login_required
@require_POST
def pair_players(request, pk):
    """Set-partner leagues: randomly pair anyone who doesn't have a partner yet."""
    import random
    league = _admin_league(request, pk)
    loose = list(league.players.filter(team__isnull=True))
    random.shuffle(loose)
    made = 0
    while len(loose) >= 2:
        a, b = loose.pop(), loose.pop()
        team = Team.objects.create(league=league)
        a.team = b.team = team
        a.save(), b.save()
        made += 1
    messages.success(request, f"Made {made} new team{'s' if made != 1 else ''}."
                     + (f" {loose[0].name} still needs a partner." if loose else ""))
    return redirect(reverse("league_manage", args=[pk]) + "?tab=players")


@login_required
@require_POST
def team_split(request, pk, team_id):
    league = _admin_league(request, pk)
    team = get_object_or_404(Team, pk=team_id, league=league)
    team.players.update(team=None)
    team.delete()
    messages.success(request, "Team split. Both players are now unpaired.")
    return redirect(reverse("league_manage", args=[pk]) + "?tab=players")


@login_required
@require_POST
def coadmin_add(request, pk):
    league = _admin_league(request, pk)
    form = CoAdminForm(request.POST)
    if form.is_valid():
        user = User.objects.filter(username__iexact=form.cleaned_data["username"].strip()).first()
        if not user:
            messages.warning(request, "No account with that username. Ask them to sign up on DinkUp first.")
        elif user == league.owner:
            messages.info(request, "That's already the league owner.")
        else:
            league.co_admins.add(user)
            messages.success(request, f"{user.username} is now a co-admin with full admin rights.")
    return redirect(reverse("league_manage", args=[pk]) + "?tab=settings")


@login_required
@require_POST
def coadmin_remove(request, pk, user_id):
    league = _admin_league(request, pk)
    league.co_admins.remove(user_id)
    messages.success(request, "Co-admin removed.")
    return redirect(reverse("league_manage", args=[pk]) + "?tab=settings")


# ---------------------------------------------------------------------------
# QR codes
# ---------------------------------------------------------------------------
def qr_code(request, pk, kind):
    league = get_object_or_404(League, pk=pk)
    if not league.is_admin(request.user):
        raise Http404
    if kind == "join":
        url = request.build_absolute_uri(reverse("join_league", args=[league.join_code]))
    else:
        url = request.build_absolute_uri(reverse("watch", args=[league.spectator_code]))
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    return HttpResponse(img.to_string(), content_type="image/svg+xml")


# ---------------------------------------------------------------------------
# Players: join + my games + scores
# ---------------------------------------------------------------------------
def join_league(request, code):
    league, kind = _find_league_by_code(code)
    if kind == "watch":
        return redirect("watch", code=league.spectator_code)
    if not league:
        messages.warning(request, "That join code didn't match a league.")
        return redirect("home")

    existing = _session_player(request, league)
    if existing and request.method == "GET" and not request.GET.get("switch"):
        return redirect("player_home", pk=league.pk)

    form = JoinForm(request.POST or None)
    roster = league.players.order_by("name")

    def show_form():
        return render(request, "leagues/join.html", {"league": league, "form": form, "roster": roster,
                                                     "ask_pin": bool(form.errors.get("pin"))})

    if request.method == "POST" and form.is_valid():
        name = form.cleaned_data["name"].strip()
        pin = (form.cleaned_data.get("pin") or "").strip()
        player = league.players.filter(name__iexact=name).first()
        new_pin = False
        if player:
            if player.pin:
                # Someone already joined with this name: they need its PIN, so nobody can pose as them.
                if pin != player.pin:
                    form.add_error("pin", f"{player.name} has already joined. Enter their 4-digit PIN. "
                                          "Forgot it? The league admin can see it on the Players tab.")
                    return show_form()
            else:
                player.set_new_pin()  # first time claiming a name the admin typed in
                new_pin = True
        else:
            if league.players.count() >= league.max_players:
                form.add_error("name", f"This league is full ({league.max_players} players). If you're already "
                                       "on the list, pick your name from the suggestions. Otherwise, talk to the league admin.")
                return show_form()
            player = Player.objects.create(league=league, name=name, self_joined=True)
            player.set_new_pin()
            new_pin = True
            if league.schedule_generated_at:
                messages.info(request, "You're in! The admin will add you to the schedule.")
        partner_name = form.cleaned_data.get("partner_name", "").strip()
        if league.is_teams and partner_name and not player.team:
            partner = league.players.filter(name__iexact=partner_name).first()
            if not partner:
                partner = Player.objects.create(league=league, name=partner_name, self_joined=True)
            if not partner.team:
                team = Team.objects.create(league=league)
                player.team = partner.team = team
                player.save(), partner.save()
        _remember_player(request, player)
        if new_pin:
            request.session["show_pin"] = player.id
        return redirect("player_home", pk=league.pk)

    return show_form()


def player_home(request, pk):
    league = get_object_or_404(League, pk=pk)
    player = _session_player(request, league)
    if not player:
        messages.info(request, "Enter your league code to see your games.")
        return redirect("home")
    matches = [m for m in league.matches.select_related("a1", "a2", "b1", "b2")
               .order_by("stage", "week", "round_number", "court") if player.id in m.player_ids]
    for m in matches:
        side = m.side_of(player.id)
        m.my_side = side
        mine = m.side_a if side == "a" else m.side_b
        m.partner = next((p for p in mine if p.id != player.id), None)
        m.opponents = m.side_b if side == "a" else m.side_a
        m.my_score = m.score_a if side == "a" else m.score_b
        m.their_score = m.score_b if side == "a" else m.score_a
        m.won = m.is_complete and m.winner == side
    up_next = next((m for m in matches if not m.is_complete), None)
    table = standings(league)
    my_row = next((r for r in table if player.id in r["player_ids"]), None)
    show_pin = request.session.pop("show_pin", None) == player.id
    return render(request, "leagues/player_home.html", {
        "league": league, "player": player, "matches": matches, "up_next": up_next,
        "my_row": my_row, "table_size": len(table), "show_pin": show_pin,
    })


def player_leave(request, pk):
    players = request.session.get("players", {})
    players.pop(str(pk), None)
    request.session["players"] = players
    return redirect("home")


@require_POST
def submit_score(request, match_id):
    match = get_object_or_404(Match.objects.select_related("league"), pk=match_id)
    league = match.league
    is_admin = league.is_admin(request.user)
    player = _session_player(request, league)
    back = request.POST.get("next") or (reverse("player_home", args=[league.pk]) if player and not is_admin
                                        else reverse("league_manage", args=[league.pk]) + "?tab=schedule")

    if not is_admin and (not player or player.id not in match.player_ids):
        messages.warning(request, "Only players in this game can enter its score.")
        return redirect(back)
    if match.locked and not is_admin:
        messages.warning(request, "Scores for this game are locked. Ask the league admin to fix it.")
        return redirect(back)
    if request.POST.get("clear") and is_admin:
        clear_score(match)
        messages.success(request, "Score cleared.")
        return redirect(back)

    form = ScoreForm(request.POST)
    if not form.is_valid():
        if "confirm" in form.errors:
            messages.warning(request, "Check the “Yes, this score is correct” box first.")
        else:
            messages.warning(request, "Enter a score for both sides.")
        return redirect(back)

    a, b = form.cleaned_data["score_a"], form.cleaned_data["score_b"]
    # Players enter "us vs them"; flip to match the A/B sides if they're on side B.
    if player and not is_admin and request.POST.get("perspective") == "mine" and match.side_of(player.id) == "b":
        a, b = b, a
    error = validate_score(match, a, b)
    if error:
        messages.warning(request, error)
        return redirect(back)
    reporter = request.user.username if is_admin else player.name
    save_score(match, a, b, reporter)
    messages.success(request, "Score saved!")
    return redirect(back)


# ---------------------------------------------------------------------------
# Shared views: schedule / standings / bracket / spectators
# ---------------------------------------------------------------------------
def watch(request, code):
    league, kind = _find_league_by_code(code)
    if not league:
        messages.warning(request, "That watch code didn't match a league.")
        return redirect("home")
    if kind == "join":
        # Someone used the player code here; still let them watch.
        pass
    watching = request.session.get("watching", [])
    if league.id not in watching:
        watching.append(league.id)
        request.session["watching"] = watching
    return render(request, "leagues/watch.html", _board_context(league, request.GET.get("tab", "scores")))


def _board_context(league, tab):
    matches = league.matches.filter(stage="rr").select_related("a1", "a2", "b1", "b2")
    weeks = sorted({m.week for m in matches})
    rounds, champion = bracket_rounds(league)
    return {
        "league": league,
        "schedule": _schedule_by_round(matches),
        "weeks": weeks,
        "table": standings(league),
        "bracket": rounds,
        "champion": champion,
        "tab": tab,
    }


def board(request, pk):
    """Schedule + standings + bracket for anyone connected to this league."""
    league = get_object_or_404(League, pk=pk)
    if not _can_view(request, league):
        messages.info(request, "Enter your league code first.")
        return redirect("home")
    ctx = _board_context(league, request.GET.get("tab", "standings"))
    ctx["player"] = _session_player(request, league)
    ctx["is_admin"] = league.is_admin(request.user)
    return render(request, "leagues/board.html", ctx)


# ---------------------------------------------------------------------------
# AI assistant
# ---------------------------------------------------------------------------
def assistant_page(request, pk):
    league = get_object_or_404(League, pk=pk)
    if not _can_view(request, league):
        return redirect("home")
    return render(request, "leagues/assistant.html", {
        "league": league, "player": _session_player(request, league),
        "ai_on": assistant.ai_enabled(), "is_admin": league.is_admin(request.user),
    })


@require_POST
def assistant_ask(request, pk):
    league = get_object_or_404(League, pk=pk)
    if not _can_view(request, league):
        return JsonResponse({"error": "Join this league first."}, status=403)
    try:
        question = json.loads(request.body or "{}").get("message", "")
    except ValueError:
        question = ""
    player = _session_player(request, league)
    role = "league admin" if league.is_admin(request.user) else ("player" if player else "spectator")
    reply, source = assistant.answer(question, league, player, role)
    return JsonResponse({"reply": reply, "source": source})
