"""
DinkUp's AI assistant ("Coach Dink").

Works two ways:
  1. Built in (no setup): understands common questions like "when do I play next?",
     "who's in first?", "what are the rules?" and answers from the live league data.
  2. Real AI: if ANTHROPIC_API_KEY or OPENAI_API_KEY is set, the same league data is sent
     to the model so it can answer anything. If the AI call fails, it falls back to (1).
"""
import json
import re
import urllib.error
import urllib.request

from django.conf import settings
from django.utils import timezone

from .services import bracket_rounds, preview, standings


def _fmt_time(t):
    return t.strftime("%I:%M %p").lstrip("0")


def _fmt_date(d):
    return d.strftime("%a %b %d").replace(" 0", " ")


def _match_line(m, player_id=None):
    when = f"{_fmt_date(m.play_date)} · Round {m.round_number} · {_fmt_time(m.start_time)} · Court {m.court}"
    if player_id:
        side = m.side_of(player_id)
        mine = m.side_a if side == "a" else m.side_b
        theirs = m.side_b if side == "a" else m.side_a
        partner = [p.name for p in mine if p.id != player_id]
        text = f"{when} — with {partner[0] if partner else 'your partner'} vs {' & '.join(p.name for p in theirs)}"
    else:
        text = f"{when} — {m.side_a_names} vs {m.side_b_names}"
    if m.is_complete:
        text += f" (final {m.score_a}-{m.score_b})"
    return text


def _player_matches(league, player):
    qs = league.matches.select_related("a1", "a2", "b1", "b2").order_by("week", "round_number", "court")
    return [m for m in qs if player.id in m.player_ids]


def build_context(league, player=None, role="spectator"):
    lines = [
        f"League: {league.name} ({league.get_event_type_display()}, {league.label})",
        f"Partner format: {league.get_partner_mode_display()}",
        f"Courts: {league.num_courts}. Minutes per game: {league.game_minutes}. "
        f"Weeks/play days: {league.num_weeks}, starting {_fmt_date(league.start_date)} at {_fmt_time(league.start_time)}.",
        f"Scoring: games to {league.points_to_win}. "
        + ("Win by 2 for every game (tournament)." if league.win_by_two_always
           else "No win-by-2 in league/round-robin play; bracket (playoff) games are win by 2."),
        f"Scores locked: {'yes' if league.scores_locked else 'no'}. Players enter their own scores.",
        f"Players: {league.players.count()} (max {league.max_players}).",
    ]
    table = standings(league)
    if table:
        lines.append("Standings (rank. name W-L, point diff):")
        for r in table[:12]:
            lines.append(f"  {r['rank']}. {r['name']} {r['w']}-{r['l']}, {r['diff']:+d}")
    rounds, champ = bracket_rounds(league)
    if rounds:
        lines.append("Bracket: " + "; ".join(
            f"{r['name']}: " + ", ".join(f"{m.side_a_names} vs {m.side_b_names}"
                                         + (f" {m.score_a}-{m.score_b}" if m.is_complete else "")
                                         for m in r["matches"]) for r in rounds))
        if champ:
            lines.append(f"Champion: {champ}")
    if player:
        lines.append(f"The person asking is player {player.name}. Their matches:")
        for m in _player_matches(league, player)[:20]:
            lines.append("  " + _match_line(m, player.id))
    lines.append(f"The person asking is a {role}. Today is {_fmt_date(timezone.localdate())}.")
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "You are Coach Dink, the friendly assistant inside DinkUp, a pickleball league app used in Waco, Texas. "
    "Answer in 1-4 short sentences, suitable for reading on a phone between games. Use only the league data "
    "provided; if you don't know something, say so and suggest asking the league admin. Never invent scores."
)


def _call_anthropic(question, context):
    body = {
        "model": settings.AI_MODEL or "claude-haiku-5-5",
        "max_tokens": 350,
        "system": SYSTEM_PROMPT + "\n\nLEAGUE DATA:\n" + context,
        "messages": [{"role": "user", "content": question}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
        headers={"x-api-key": settings.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    return "".join(b.get("text", "") for b in data.get("content", [])).strip()


def _call_openai(question, context):
    body = {
        "model": settings.AI_MODEL or "gpt-4o-mini",
        "max_tokens": 350,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\nLEAGUE DATA:\n" + context},
            {"role": "user", "content": question},
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()


def ai_enabled():
    return bool(settings.ANTHROPIC_API_KEY or settings.OPENAI_API_KEY)


# ---------------------------------------------------------------------------
# Built-in answers (no API key needed)
# ---------------------------------------------------------------------------
def _has(q, *words):
    return any(re.search(rf"\b{w}", q) for w in words)


def built_in_answer(question, league, player=None, role="spectator"):
    q = question.lower().strip()
    table = standings(league)

    # If the question names a player ("What's next for Casey?"), answer for that player,
    # even when someone else is signed in. Otherwise answer for whoever is asking.
    words = set(re.findall(r"[a-z']+", q))
    named = None
    for p in league.players.all():
        first = p.name.split()[0].lower()
        if p.name.lower() in q or first in words:
            named = p
            break
    self_ask = player is not None and (named is None or named.id == player.id)
    if named and not self_ask:
        player = named
    who = "Your" if self_ask else (f"{player.name}'s" if player else "")

    if _has(q, "hi", "hello", "hey", "help", "what can") and len(q) < 40:
        return ("Hi! I'm Coach Dink. Try asking: “When do I play next?”, “Who's my partner?”, "
                "“Who's in first?”, “What's my record?”, or “What are the rules?”")

    if _has(q, "rule", "win by", "points", "score to", "how many points", "tie"):
        wb2 = ("Every game is win by 2 because this is a tournament." if league.win_by_two_always
               else "League games don't need to win by 2, but playoff bracket games do.")
        return (f"Games go to {league.points_to_win} (about {league.game_minutes} minutes). {wb2} "
                "It's doubles — 4 players per court — and players enter their own scores after each game.")

    if _has(q, "lock"):
        if league.scores_locked:
            return "Scores are locked right now. Ask the league admin if a score needs to be fixed."
        if league.auto_lock:
            return "Scores lock automatically after each play night, so enter yours before midnight."
        return "Scores are open. The admin can lock them at any time."

    if _has(q, "join", "code", "sign up", "spectat", "watch", "qr"):
        return ("Players join with the league's join code (or by scanning its QR code). Family and friends can use "
                "the separate WATCH code to follow scores without being able to change anything. Codes aren't case sensitive.")

    if _has(q, "bracket", "playoff", "champion", "final"):
        rounds, champ = bracket_rounds(league)
        if champ:
            return f"🏆 {champ} won the bracket!"
        if rounds:
            r = rounds[-1]
            games = "; ".join(f"Court {m.court}: {m.side_a_names} vs {m.side_b_names}" for m in r["matches"])
            return f"{r['name']} are up: {games}."
        return "The bracket hasn't started yet. The top finishers from round robin will advance to it."

    if player and _has(q, "record", "how am i", "my stand", "my rank", "doing", "my win", "my loss"):
        for r in table:
            if player.id in r["player_ids"]:
                return (f"{'You are' if self_ask else player.name + ' is'} #{r['rank']} of {len(table)} at {r['w']}-{r['l']} "
                        f"({r['pf']} points for, {r['pa']} against, {r['diff']:+d}).")
        return "You don't have any scored games yet."

    if _has(q, "first", "lead", "winning", "standing", "rank", "top", "best", "who.s ahead"):
        played = [r for r in table if r["gp"]]
        if not played:
            return "No scores are in yet, so everyone's tied at 0-0."
        top = ", ".join(f"{r['rank']}. {r['name']} ({r['w']}-{r['l']}, {r['diff']:+d})" for r in played[:3])
        return f"Top of the standings: {top}."

    if _has(q, "next", "when", "where", "court", "partner", "who am i", "who do i", "my game", "my match", "play"):
        if not player:
            upcoming = [m for m in league.matches.select_related("a1", "a2", "b1", "b2")
                        .order_by("week", "round_number", "court") if not m.is_complete][:league.num_courts]
            if not upcoming:
                return "There are no unplayed games on the schedule right now."
            return "Up next: " + " | ".join(f"Court {m.court}: {m.side_a_names} vs {m.side_b_names}" for m in upcoming)
        mine = [m for m in _player_matches(league, player) if not m.is_complete]
        if not mine:
            return "You've played all your scheduled games — nice work! Check the standings to see where you landed."
        m = mine[0]
        line = _match_line(m, player.id)
        extra = f" After that {'you have' if self_ask else 'they have'} {len(mine) - 1} more game{'s' if len(mine) != 2 else ''}." if len(mine) > 1 else ""
        return f"{who} next game: {line}.{extra}"

    if _has(q, "how long", "how many round", "how many game", "end", "time"):
        p = preview(league)
        if not p:
            return "Add players first, then I can estimate the number of rounds and how long the night runs."
        hrs, mins = divmod(p["minutes"], 60)
        length = f"{hrs}h {mins}m" if hrs else f"{mins} min"
        return (f"About {p['rounds']} rounds ({p['games']} games each) — roughly {length} starting at "
                f"{_fmt_time(league.start_time)}.")

    return ("I'm not sure about that one. I can answer questions about your next game, partner, court, "
            "the standings, your record, the bracket, and the rules.")


def answer(question, league, player=None, role="spectator"):
    """Returns (reply_text, source) where source is 'ai' or 'built-in'."""
    question = (question or "").strip()[:500]
    if not question:
        return "Ask me anything about this league!", "built-in"
    if ai_enabled():
        context = build_context(league, player, role)
        try:
            if settings.ANTHROPIC_API_KEY:
                reply = _call_anthropic(question, context)
            else:
                reply = _call_openai(question, context)
            if reply:
                return reply, "ai"
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError):
            pass  # fall back to built-in answers
    return built_in_answer(question, league, player, role), "built-in"
