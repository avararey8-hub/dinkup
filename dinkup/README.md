# DinkUp — Pickleball League & Tournament App

A mobile-first Django web app for running pickleball leagues, scrambles, and tournaments. Built for Mrs. Carter (Waco regional director) as a simpler alternative to Swish.

## Run it on your laptop

You need **Python 3.10 or newer**. Check by typing `python --version` (Windows) or `python3 --version` (Mac).

**1. Open a terminal in the `dinkup` folder** (the one with `manage.py` in it).

**2. Create a virtual environment and install Django.**

Mac:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell or Command Prompt):
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**3. Set up the database and load the demo data.**
```bash
python manage.py migrate
python manage.py load_demo
```
This creates an admin login (**demo / pickle123**) and two sample leagues. It also prints their join and watch codes.

**4. Start the site.**
```bash
python manage.py runserver
```
Open **http://127.0.0.1:8000** in Chrome or Safari.

### Try it on your phone

Your phone and laptop need to be on the same Wi-Fi.

1. Start the server with `python manage.py runserver 0.0.0.0:8000`.
2. Find your laptop's IP address. On Mac, use System Settings → Wi-Fi → Details. On Windows, run `ipconfig` and look for the IPv4 Address.
3. On your phone, open `http://YOUR-IP:8000` (for example, `http://192.168.1.25:8000`).

The QR codes on the Share tab point to whichever address you opened the site from. So if you open the admin page from your IP address, phones can scan the QR codes.

> Baylor's campus Wi-Fi may block phone-to-laptop connections. A phone hotspot or home Wi-Fi usually works.

## How Mrs. Carter's requirements map to the app

| What she asked for | Where it is |
|---|---|
| Admin password & login | `/login/`; admins create accounts at `/signup/` |
| Co-admin with the same rights | League → Settings → Co-admins (added by username) |
| League vs. tournament; level (beg/inter/adv); division (women's/men's/mixed/scramble) | "New league" form |
| Join code that's unique by level and division | Auto-generated, for example `INTMIX7K4Q` (level + division + random characters) |
| Spectator code (watch only, can't change scores) | `WATCH…` code. Spectators get a read-only page that refreshes itself |
| QR codes | League → Share & QR (printable) |
| Codes aren't case sensitive | Every code works in upper or lower case |
| Number of players, games, courts (8 max), length of time | League form. You can change them any time under Settings → Edit |
| Admin can enter player names | League → Players. Paste one name per line. For set partners, write `Sam / Jo` |
| Calculate who plays who | "Build the schedule." It uses players, courts, and games per player |
| Everyone plays everyone (fairness) | Rotating partners: everyone partners with everyone and sit-outs are shared. Set partners: full round robin |
| 4-week league, same matchups each week in a new order | "Number of weeks". Week 1's matchups repeat in a shuffled order |
| 4 players per court, doubles or scramble | Every game is 2 vs 2 |
| Players see their round, court, and time, and enter their own score | Player "My games" page with an "Up next" card |
| Scores lock on the night of | "Lock scores now" button, plus optional auto-lock after each play night |
| Wins, losses, total points lost | Standings show W, L, PF, PA (total points lost), and +/- |
| Games to 11, no win by 2 except tournaments | League games end at 11. Tournament and bracket games are win by 2 |
| Round robin, then a separate bracket | League → Bracket seeds the top 2, 4, or 8 from round robin standings |
| AI agent like Swish | **Coach Dink** chat (see below) |
| Mobile, Safari and Chrome | Mobile-first layout with a bottom tab bar. Tested at iPhone size |
| No red, good colors | Court green, neon lime, and white court lines |
| "Yes" checkboxes | Confirming scores, rebuilding a schedule, deleting a league, auto-lock |

## Coach Dink (the AI assistant)

Coach Dink works with no setup. It answers common questions from the live league data:

- "When do I play next?"
- "Who's my partner?"
- "What's my record?"
- "Who's in first?"
- "What are the rules?"
- "How long will it run?"

**Optional: connect a real AI model.** Set one API key before starting the server. Coach Dink then answers any question, using the same league data.

Mac:
```bash
export ANTHROPIC_API_KEY="your-key"      # or: export OPENAI_API_KEY="your-key"
python manage.py runserver
```

Windows:
```bash
set ANTHROPIC_API_KEY=your-key
python manage.py runserver
```

The chat header changes to "AI powered" and AI answers get an "AI" tag. If the AI service can't be reached, Coach Dink falls back to its built-in answers.

## Project layout

```
dinkup/
├── dinkup_site/          settings & main URLs
├── leagues/
│   ├── models.py         League, Team, Player, Match
│   ├── services.py       scheduling, score rules, standings, bracket
│   ├── assistant.py      Coach Dink (built-in + optional AI)
│   ├── views.py          all pages
│   ├── forms.py
│   └── management/commands/load_demo.py
├── templates/            HTML pages
└── static/               style.css, app.js
```

You can also manage raw data at `/django-admin/`. Create a superuser first with `python manage.py createsuperuser`.
