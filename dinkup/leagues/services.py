"""
The "brains" of DinkUp:
  * build a fair schedule (who plays who, on which court, in which round)
  * repeat week 1 matchups for multi-week leagues
  * check scores against the game rules
  * standings (wins, losses, points)
  * playoff bracket seeded from round-robin standings
"""
import math
import random
from collections import Counter

from django.db import transaction
from django.utils import timezone

from .models import Match


class ScheduleError(Exception):
    pass


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
def default_rotating_games(num_players):
    """Partnering everyone once takes (players - 1) games. Cap it so a night stays reasonable."""
    return max(1, min(num_players - 1, 8))


def _rotating_rounds(player_ids, courts, target, rng, played=()):
    """
    Rotating partners: each round fills as many courts as possible with 4 players.
    Players with the fewest games go in first (so sit-outs are shared fairly), then we
    try many groupings and keep the one that repeats partners and opponents the least.
    """
    n = len(player_ids)
    per_round = min(courts, n // 4)
    if per_round == 0:
        raise ScheduleError("You need at least 4 players to make a doubles schedule.")

    games = {pid: 0 for pid in player_ids}
    partners = Counter()
    opponents = Counter()
    rounds = []
    # Games already played tonight (used when late players are added mid-night).
    for (a, b), (c, d) in played:
        for pid in (a, b, c, d):
            if pid in games:
                games[pid] += 1
        partners[frozenset((a, b))] += 1
        partners[frozenset((c, d))] += 1
        for x in (a, b):
            for y in (c, d):
                opponents[frozenset((x, y))] += 1

    def cost(option):
        (a, b), (c, d) = option
        total = partners[frozenset((a, b))] * 10 + partners[frozenset((c, d))] * 10
        for x in (a, b):
            for y in (c, d):
                total += opponents[frozenset((x, y))] * 2
        return total

    while min(games.values()) < target and len(rounds) < 120:
        ids = list(player_ids)
        rng.shuffle(ids)
        ids.sort(key=lambda pid: games[pid])  # fewest games first; ties stay random
        playing = ids[: per_round * 4]

        best, best_cost = None, math.inf
        for _ in range(300):
            rng.shuffle(playing)
            round_matches, round_cost = [], 0
            for k in range(per_round):
                g = playing[k * 4 : k * 4 + 4]
                options = [
                    ((g[0], g[1]), (g[2], g[3])),
                    ((g[0], g[2]), (g[1], g[3])),
                    ((g[0], g[3]), (g[1], g[2])),
                ]
                option = min(options, key=cost)
                round_cost += cost(option)
                round_matches.append(option)
            if round_cost < best_cost:
                best, best_cost = round_matches, round_cost
                if best_cost == 0:
                    break

        for (a, b), (c, d) in best:
            for pid in (a, b, c, d):
                games[pid] += 1
            partners[frozenset((a, b))] += 1
            partners[frozenset((c, d))] += 1
            for x in (a, b):
                for y in (c, d):
                    opponents[frozenset((x, y))] += 1
        rounds.append(best)
    return rounds


def _team_rounds(teams, courts, max_games):
    """
    Set partners: classic round robin ("circle method") so every team plays every
    other team. If a round has more matches than courts, it is split into extra rounds.
    """
    entries = list(teams)
    if len(entries) < 2:
        raise ScheduleError("You need at least 2 complete teams (2 players each).")
    if len(entries) % 2:
        entries.append(None)  # bye
    m = len(entries)
    circle_rounds = []
    for _ in range(m - 1):
        pairs = [(entries[i], entries[m - 1 - i]) for i in range(m // 2)]
        circle_rounds.append([p for p in pairs if p[0] is not None and p[1] is not None])
        entries = [entries[0], entries[-1]] + entries[1:-1]
    if max_games:
        circle_rounds = circle_rounds[:max_games]

    slots = []
    for pairs in circle_rounds:
        for k in range(0, len(pairs), courts):
            slots.append(pairs[k : k + courts])
    return slots


def preview(league):
    """Quick numbers for the admin: rounds per night and how long the night runs."""
    players = league.players.count()
    if league.is_teams:
        teams = sum(1 for t in league.teams.all() if t.players.count() == 2)
        if teams < 2:
            return None
        full = teams - 1 if teams % 2 == 0 else teams  # odd count adds a bye round
        circle = min(league.games_per_player or full, full)
        games = circle if teams % 2 == 0 else circle - (1 if circle == full else 0)
        rounds = circle * math.ceil((teams // 2) / league.num_courts)
        return {"players": players, "teams": teams, "games": games, "rounds": rounds,
                "minutes": rounds * league.game_minutes}
    if players < 4:
        return None
    games = league.games_per_player or default_rotating_games(players)
    per_round = min(league.num_courts, players // 4)
    rounds = math.ceil(players * games / (4 * per_round))
    return {"players": players, "teams": None, "games": games, "rounds": rounds,
            "minutes": rounds * league.game_minutes, "sitting": players - per_round * 4}


def _best_rotating(ids, courts, target, rng, played=()):
    """Try several schedules and keep the fairest: fewest rounds, most different partners, fewest repeats."""
    best, best_score = None, None
    for _ in range(40):
        rounds = _rotating_rounds(ids, courts, target, rng, played)
        pairs = Counter(frozenset(side) for side_a, side_b in played for side in (side_a, side_b))
        for rnd in rounds:
            for side_a, side_b in rnd:
                pairs[frozenset(side_a)] += 1
                pairs[frozenset(side_b)] += 1
        score = (len(rounds), -len(pairs), sum(v - 1 for v in pairs.values()))
        if best_score is None or score < best_score:
            best, best_score = rounds, score
    return best


def _complete_teams(league):
    return [t for t in league.teams.prefetch_related("players") if t.players.count() == 2]


def _team_ids(team):
    ps = list(team.players.all())
    return (ps[0].id, ps[1].id)


def _week_template(league, rng):
    """One week of rounds: [[((a1, a2), (b1, b2)), ...], ...] using player ids."""
    if league.is_teams:
        teams = _complete_teams(league)
        slots = _team_rounds(teams, league.num_courts, league.games_per_player)
        return [[(_team_ids(ta), _team_ids(tb)) for ta, tb in slot] for slot in slots]
    ids = list(league.players.values_list("id", flat=True))
    target = league.games_per_player or default_rotating_games(len(ids))
    return _best_rotating(ids, league.num_courts, target, rng)


def _match_objects(league, week, rounds, first_round=1):
    out = []
    for r_index, rnd in enumerate(rounds, start=first_round):
        for c_index, ((a1, a2), (b1, b2)) in enumerate(rnd, start=1):
            out.append(Match(league=league, stage="rr", week=week, round_number=r_index,
                             court=c_index, a1_id=a1, a2_id=a2, b1_id=b1, b2_id=b2))
    return out


@transaction.atomic
def generate_schedule(league, seed=None):
    """Build the whole schedule from scratch (erases existing games and scores)."""
    rng = random.Random(seed)
    week1 = _week_template(league, rng)
    league.matches.all().delete()
    new = []
    for week in range(1, league.num_weeks + 1):
        rounds = [list(r) for r in week1]
        if week > 1:
            # Same opponents as week 1, just a different order and court.
            rng.shuffle(rounds)
            for r in rounds:
                rng.shuffle(r)
        new += _match_objects(league, week, rounds)
    Match.objects.bulk_create(new)
    league.schedule_generated_at = timezone.now()
    league.save(update_fields=["schedule_generated_at"])
    return len(new)


def unscheduled_players(league):
    """Players (on complete teams, for set-partner leagues) who aren't in any round-robin game yet."""
    if not league.matches.filter(stage="rr").exists():
        return []
    scheduled = set()
    for m in league.matches.filter(stage="rr"):
        scheduled |= m.player_ids
    players = league.players.select_related("team")
    if league.is_teams:
        complete = {t.id for t in _complete_teams(league)}
        players = [p for p in players if p.team_id in complete]
    return [p for p in players if p.id not in scheduled]


def _continue_week(league, kept, rng):
    """New rounds for the rest of a night, given the games being kept, so late players get in fairly."""
    played = [((m.a1_id, m.a2_id), (m.b1_id, m.b2_id)) for m in kept]
    if league.is_teams:
        teams = _complete_teams(league)
        team_of = {}
        for t in teams:
            for pid in _team_ids(t):
                team_of[pid] = t.id
        ids = {t.id: _team_ids(t) for t in teams}
        done, games = set(), Counter()
        for (a1, _), (b1, _) in played:
            ta, tb = team_of.get(a1), team_of.get(b1)
            if ta and tb:
                done.add(frozenset((ta, tb)))
                games[ta] += 1
                games[tb] += 1
        cap = league.games_per_player
        todo = [(x, y) for i, x in enumerate(ids) for y in list(ids)[i + 1:] if frozenset((x, y)) not in done]
        rng.shuffle(todo)
        rounds = []
        while todo:
            busy, slot = set(), []
            for pair in list(todo):
                x, y = pair
                if len(slot) >= league.num_courts:
                    break
                if x in busy or y in busy:
                    continue
                if cap and (games[x] >= cap or games[y] >= cap):
                    todo.remove(pair)
                    continue
                slot.append((ids[x], ids[y]))
                busy |= {x, y}
                games[x] += 1
                games[y] += 1
                todo.remove(pair)
            if not slot:
                break
            rounds.append(slot)
        return rounds
    ids = list(league.players.values_list("id", flat=True))
    target = league.games_per_player or default_rotating_games(len(ids))
    if len(ids) < 4:
        raise ScheduleError("You need at least 4 players to make a doubles schedule.")
    return _best_rotating(ids, league.num_courts, target, rng, played)


@transaction.atomic
def update_schedule(league, seed=None):
    """
    Add new players WITHOUT losing scores:
      * weeks with no scores yet are rebuilt from a fresh week plan that includes everyone
      * on a week that's already started, rounds with scores are kept and the rest of the
        night is rebuilt so the new players get their games
    Returns the number of games added.
    """
    rng = random.Random(seed)
    rr = list(league.matches.filter(stage="rr"))
    if not rr or not any(m.is_complete for m in rr):
        return generate_schedule(league, seed)

    template = _week_template(league, rng)
    new = []
    for week in range(1, league.num_weeks + 1):
        week_matches = [m for m in rr if m.week == week]
        played_rounds = sorted({m.round_number for m in week_matches if m.is_complete})
        if not played_rounds:
            Match.objects.filter(id__in=[m.id for m in week_matches]).delete()
            rounds = [list(r) for r in template]
            rng.shuffle(rounds)
            for r in rounds:
                rng.shuffle(r)
            new += _match_objects(league, week, rounds)
            continue
        kept = [m for m in week_matches if m.round_number in played_rounds]
        Match.objects.filter(id__in=[m.id for m in week_matches if m.round_number not in played_rounds]).delete()
        renumber = {old: i for i, old in enumerate(played_rounds, start=1)}
        for m in kept:
            if m.round_number != renumber[m.round_number]:
                m.round_number = renumber[m.round_number]
                m.save(update_fields=["round_number"])
        new += _match_objects(league, week, _continue_week(league, kept, rng), first_round=len(played_rounds) + 1)
    Match.objects.bulk_create(new)
    league.schedule_generated_at = timezone.now()
    league.save(update_fields=["schedule_generated_at"])
    return len(new)


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------
def validate_score(match, a, b):
    """Return an error message, or None if the score is valid."""
    to = match.league.points_to_win
    if a is None or b is None:
        return "Enter both scores."
    if a == b:
        return "A game can't end in a tie."
    hi, lo = max(a, b), min(a, b)
    if not match.win_by_two:
        if hi != to:
            return f"Games end at {to}. The winning side should have exactly {to} points."
        return None
    if hi < to:
        return f"The winning side needs at least {to} points."
    if hi - lo < 2:
        return "This game is win-by-2. The winner needs to lead by at least 2 points."
    if hi > to and hi - lo != 2:
        return f"Past {to}, the game ends as soon as one side leads by 2."
    return None


def save_score(match, a, b, reported_by):
    match.score_a, match.score_b = a, b
    match.reported_by = reported_by[:60]
    match.reported_at = timezone.now()
    match.save()
    if match.stage == "bracket":
        advance_bracket(match.league)


def clear_score(match):
    match.score_a = match.score_b = None
    match.reported_by = ""
    match.reported_at = None
    match.save()


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------
def standings(league):
    matches = league.matches.filter(stage="rr", score_a__isnull=False, score_b__isnull=False).select_related(
        "a1", "a2", "b1", "b2", "a1__team", "b1__team"
    )
    rows = {}

    def row(key, name, player_ids):
        if key not in rows:
            rows[key] = {"key": key, "name": name, "player_ids": player_ids,
                         "w": 0, "l": 0, "pf": 0, "pa": 0}
        return rows[key]

    if league.is_teams:
        for t in league.teams.prefetch_related("players"):
            ps = list(t.players.all())
            if len(ps) == 2:
                row(f"t{t.id}", t.display, [p.id for p in ps])
    else:
        for p in league.players.all():
            row(f"p{p.id}", p.name, [p.id])

    for m in matches:
        sides = (("a", m.side_a, m.score_a, m.score_b), ("b", m.side_b, m.score_b, m.score_a))
        for _, players, mine, theirs in sides:
            if league.is_teams:
                team = players[0].team if players else None
                keys = [f"t{team.id}"] if team else []
            else:
                keys = [f"p{p.id}" for p in players]
            for k in keys:
                if k not in rows:
                    continue
                r = rows[k]
                r["pf"] += mine
                r["pa"] += theirs
                if mine > theirs:
                    r["w"] += 1
                else:
                    r["l"] += 1

    result = list(rows.values())
    for r in result:
        r["gp"] = r["w"] + r["l"]
        r["diff"] = r["pf"] - r["pa"]
        r["pct"] = round(r["w"] / r["gp"] * 100) if r["gp"] else 0
    result.sort(key=lambda r: (-r["w"], -r["diff"], -r["pf"], r["name"].lower()))
    for i, r in enumerate(result, start=1):
        r["rank"] = i
    return result


# ---------------------------------------------------------------------------
# Bracket (single elimination, seeded from round robin)
# ---------------------------------------------------------------------------
SEED_ORDER = {2: [(1, 2)], 4: [(1, 4), (2, 3)], 8: [(1, 8), (4, 5), (2, 7), (3, 6)]}


@transaction.atomic
def create_bracket(league, size):
    if size not in SEED_ORDER:
        raise ScheduleError("Bracket size must be 2, 4, or 8.")
    table = standings(league)
    if league.is_teams:
        if len(table) < size:
            raise ScheduleError(f"You need at least {size} teams for a {size}-team bracket.")
        entries = [r["player_ids"] for r in table[:size]]
    else:
        need = size * 2
        if len(table) < need:
            raise ScheduleError(f"A {size}-team bracket needs {need} players (they get paired up by rank).")
        top = [r["player_ids"][0] for r in table[:need]]
        # Pair best with worst of the qualifiers: 1+8, 2+7, ... so teams are balanced.
        entries = [[top[i], top[need - 1 - i]] for i in range(size)]

    league.matches.filter(stage="bracket").delete()
    for slot, (s1, s2) in enumerate(SEED_ORDER[size]):
        a, b = entries[s1 - 1], entries[s2 - 1]
        Match.objects.create(
            league=league, stage="bracket", week=league.num_weeks, round_number=1,
            court=(slot % league.num_courts) + 1, bracket_round=1, bracket_slot=slot,
            a1_id=a[0], a2_id=a[1], b1_id=b[0], b2_id=b[1],
        )


def advance_bracket(league):
    """When every match in a bracket round has a score, build the next round from the winners."""
    bracket = list(league.matches.filter(stage="bracket").order_by("bracket_round", "bracket_slot"))
    if not bracket:
        return
    last_round = max(m.bracket_round for m in bracket)
    current = [m for m in bracket if m.bracket_round == last_round]
    if len(current) < 2 or not all(m.is_complete for m in current):
        return
    for i in range(0, len(current), 2):
        m1, m2 = current[i], current[i + 1]
        w1 = (m1.a1_id, m1.a2_id) if m1.winner == "a" else (m1.b1_id, m1.b2_id)
        w2 = (m2.a1_id, m2.a2_id) if m2.winner == "a" else (m2.b1_id, m2.b2_id)
        Match.objects.create(
            league=league, stage="bracket", week=league.num_weeks, round_number=last_round + 1,
            court=(i // 2 % league.num_courts) + 1, bracket_round=last_round + 1, bracket_slot=i // 2,
            a1_id=w1[0], a2_id=w1[1], b1_id=w2[0], b2_id=w2[1],
        )


def bracket_rounds(league):
    """Bracket matches grouped by round for display, plus the champion if decided."""
    matches = list(league.matches.filter(stage="bracket").select_related("a1", "a2", "b1", "b2")
                   .order_by("bracket_round", "bracket_slot"))
    if not matches:
        return [], None
    by_round = {}
    for m in matches:
        by_round.setdefault(m.bracket_round, []).append(m)
    rounds = []
    total = len(by_round)
    first_size = len(by_round[1]) * 2
    total_rounds = int(math.log2(first_size))
    names = {1: "Final", 2: "Semifinals", 4: "Quarterfinals"}
    for r in sorted(by_round):
        remaining = len(by_round[r])
        rounds.append({"number": r, "name": names.get(remaining, f"Round {r}"), "matches": by_round[r]})
    champion = None
    if total == total_rounds and len(by_round[total]) == 1 and by_round[total][0].is_complete:
        f = by_round[total][0]
        champion = f.side_a_names if f.winner == "a" else f.side_b_names
    return rounds, champion
