"""
Deterministic astrology / horoscope engine.

Every reading is generated from a seed derived from (sign, period-key), so
the same sign on the same day always returns the same horoscope — stable,
cache-friendly, and free to run forever (no external data source).
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, timedelta, timezone

SIGNS = [
    {"name": "Aries", "symbol": "♈", "element": "Fire", "modality": "Cardinal",
     "ruling_planet": "Mars", "date_range": "Mar 21 – Apr 19",
     "traits": ["bold", "energetic", "pioneering", "competitive"],
     "start": (3, 21), "end": (4, 19)},
    {"name": "Taurus", "symbol": "♉", "element": "Earth", "modality": "Fixed",
     "ruling_planet": "Venus", "date_range": "Apr 20 – May 20",
     "traits": ["grounded", "patient", "loyal", "sensual"],
     "start": (4, 20), "end": (5, 20)},
    {"name": "Gemini", "symbol": "♊", "element": "Air", "modality": "Mutable",
     "ruling_planet": "Mercury", "date_range": "May 21 – Jun 20",
     "traits": ["curious", "adaptable", "witty", "expressive"],
     "start": (5, 21), "end": (6, 20)},
    {"name": "Cancer", "symbol": "♋", "element": "Water", "modality": "Cardinal",
     "ruling_planet": "Moon", "date_range": "Jun 21 – Jul 22",
     "traits": ["nurturing", "intuitive", "protective", "sentimental"],
     "start": (6, 21), "end": (7, 22)},
    {"name": "Leo", "symbol": "♌", "element": "Fire", "modality": "Fixed",
     "ruling_planet": "Sun", "date_range": "Jul 23 – Aug 22",
     "traits": ["confident", "generous", "charismatic", "creative"],
     "start": (7, 23), "end": (8, 22)},
    {"name": "Virgo", "symbol": "♍", "element": "Earth", "modality": "Mutable",
     "ruling_planet": "Mercury", "date_range": "Aug 23 – Sep 22",
     "traits": ["analytical", "diligent", "practical", "precise"],
     "start": (8, 23), "end": (9, 22)},
    {"name": "Libra", "symbol": "♎", "element": "Air", "modality": "Cardinal",
     "ruling_planet": "Venus", "date_range": "Sep 23 – Oct 22",
     "traits": ["diplomatic", "fair", "charming", "social"],
     "start": (9, 23), "end": (10, 22)},
    {"name": "Scorpio", "symbol": "♏", "element": "Water", "modality": "Fixed",
     "ruling_planet": "Pluto", "date_range": "Oct 23 – Nov 21",
     "traits": ["intense", "passionate", "resourceful", "magnetic"],
     "start": (10, 23), "end": (11, 21)},
    {"name": "Sagittarius", "symbol": "♐", "element": "Fire", "modality": "Mutable",
     "ruling_planet": "Jupiter", "date_range": "Nov 22 – Dec 21",
     "traits": ["adventurous", "optimistic", "honest", "free-spirited"],
     "start": (11, 22), "end": (12, 21)},
    {"name": "Capricorn", "symbol": "♑", "element": "Earth", "modality": "Cardinal",
     "ruling_planet": "Saturn", "date_range": "Dec 22 – Jan 19",
     "traits": ["disciplined", "ambitious", "responsible", "strategic"],
     "start": (12, 22), "end": (1, 19)},
    {"name": "Aquarius", "symbol": "♒", "element": "Air", "modality": "Fixed",
     "ruling_planet": "Uranus", "date_range": "Jan 20 – Feb 18",
     "traits": ["inventive", "independent", "humanitarian", "original"],
     "start": (1, 20), "end": (2, 18)},
    {"name": "Pisces", "symbol": "♓", "element": "Water", "modality": "Mutable",
     "ruling_planet": "Neptune", "date_range": "Feb 19 – Mar 20",
     "traits": ["compassionate", "imaginative", "intuitive", "gentle"],
     "start": (2, 19), "end": (3, 20)},
]

SIGN_BY_NAME = {s["name"].lower(): s for s in SIGNS}
SIGN_NAMES = [s["name"] for s in SIGNS]

COLORS = ["Crimson", "Gold", "Emerald", "Sapphire", "Amber", "Violet",
          "Turquoise", "Coral", "Indigo", "Silver", "Rose", "Teal",
          "Maroon", "Ivory", "Olive", "Lavender"]
MOODS = ["Optimistic", "Reflective", "Energised", "Calm", "Determined",
         "Playful", "Focused", "Romantic", "Restless", "Grateful",
         "Bold", "Serene", "Inspired", "Cautious"]
GEMS = ["Diamond", "Ruby", "Emerald", "Sapphire", "Topaz", "Opal",
        "Amethyst", "Garnet", "Pearl", "Citrine", "Jade", "Onyx"]

# ── Phrase banks for the deterministic fallback generator ──────────────
# This is the QUALITY FLOOR used when no ANTHROPIC_API_KEY is configured.
# When a key is present, content.py generates richer, fully-unique copy via
# Claude and these banks are not used. Banks are large so that picking a few
# lines per section stays varied across all 12 signs on the same day.

_OVERVIEW = [
    "The {period} opens with {planet} lighting up your chart, and you can feel the shift before you can name it.",
    "There's a current running under this {period} that rewards your {trait} side — lean into it.",
    "Your ruling planet {planet} sets the tone now, sharpening the instincts {sign} is already known for.",
    "This is one of those stretches where quiet confidence does more for you than any grand gesture.",
    "A {element}-sign pulse runs through everything you touch this {period}; momentum is on your side.",
    "Something you've been circling for a while finally clicks into focus during this {period}.",
    "The cosmos is asking you to stop overthinking and trust the read you already have.",
    "Expect the pace to pick up — your {trait} nature is exactly what the moment calls for.",
    "You're entering a {period} that favours honesty: with others, but mostly with yourself.",
    "The energy is less about chasing and more about choosing — be deliberate about where you spend it.",
    "There's a door quietly opening this {period}, and only your {trait} side will notice it in time.",
    "{planet} is pulling old patterns to the surface — not to shame you, but to let you finally retire one.",
    "The {period} starts noisy and ends clear; don't make permanent decisions in the noisy part.",
    "What looks like a delay this {period} is actually the universe checking whether you really want it.",
    "You've outgrown a version of yourself recently, and this {period} keeps proving it in small ways.",
    "The theme of this {period} is follow-through — the magic isn't in the new idea, it's in finishing the old one.",
    "Someone's about to underestimate you, and the {sign} response is to let the results argue back.",
    "A loose end you've been ignoring tugs at you now; tying it off releases more energy than you expect.",
    "This {period} rewards the unglamorous middle of things — keep going, the plot is further along than it feels.",
    "Your intuition is unusually loud right now; the first answer you hear is usually the honest one.",
    "An unexpected conversation reroutes your {period} in a direction you wouldn't have picked — but should keep.",
    "The {element} energy in your chart wants simplicity: fewer tabs open, fewer maybes, more decided.",
    "You're being watched by the right people this {period} — not critically, but with growing respect.",
    "Permission granted: stop renegotiating a decision you already made well.",
    "Something small you do for someone else this {period} comes back to you at a comically larger scale.",
    "The {period} asks you to choose between comfortable and true; {sign} usually knows which one wins.",
    "A skill you treat as 'no big deal' is the exact thing someone needs this {period} — price it accordingly.",
    "Pressure eases mid-{period}, and what's left underneath is something you actually want to do.",
    "This is a planting {period}, not a harvest one — judge it by what you start, not what you finish.",
    "Your patience gets tested early on, purely so the {period} can reward it later.",
    "An honest look at your calendar tells you what you really value this {period} — adjust it without guilt.",
    "{planet} is amplifying your presence; rooms react to you more than usual, so aim that on purpose.",
    "You don't need a new plan this {period} — you need to actually trust the good one you have.",
    "The thing you call 'being behind' is just your route taking the scenic road; this {period} brings the shortcut.",
    "There's one bold ask sitting on the tip of your tongue — this {period} is the right window to say it.",
]
_LOVE = [
    "In love, a single honest conversation does more than a week of pretending you're fine.",
    "If you're coupled up, small daily attention beats one big romantic swing right now.",
    "Single {sign}? Someone who matches your energy is closer than your overthinking lets you believe.",
    "Resist the urge to read into a slow reply — your nervous system, not the relationship, is the issue.",
    "An old connection may resurface; decide whether it's nostalgia or genuinely worth a second look.",
    "Let your partner actually finish the sentence — the harmony you want is on the other side of listening.",
    "Flirt a little. Your {trait} charm is doing more heavy lifting than you give it credit for.",
    "If something's been left unsaid, this {period} is a safer-than-usual window to say it kindly.",
    "Don't perform closeness — show up consistently and let the realness speak for itself.",
    "Boundaries aren't the opposite of love; setting one now actually protects the bond.",
    "A vulnerable moment lands well — the version of you with the guard down is the one people fall for.",
    "Stop keeping score. The relationship breathes easier the second you put the tally down.",
]
_CAREER = [
    "At work, your {trait} instinct spots an opening the rest of the room walked right past.",
    "Say the idea out loud in the meeting — the credit you're worried about losing is yours to claim.",
    "One unglamorous task you keep avoiding is the exact thing that unlocks everything after it.",
    "A senior voice notices how you handle pressure this {period}; handle it like someone already promoted.",
    "Collaboration beats competition right now — sharing the win makes you look bigger, not smaller.",
    "Protect your deep-focus hours like they're a meeting with the CEO, because functionally they are.",
    "If office politics flare up, stay factual and unbothered; the calm one looks like the leader.",
    "Don't confuse being busy with being effective — pick the one priority that actually moves the needle.",
    "A 'no' you've been scared to give frees up the energy your real work has been starving for.",
    "Document the thing. The you of two weeks from now will be deeply grateful you did.",
    "Your reputation is built in the boring weeks, and this is one of them — show up anyway.",
]
_MONEY = [
    "Money-wise, hold off on the impulse buy until the {period} settles — the clarity is worth the wait.",
    "Check the subscriptions and the small recurring leaks; the fix is unsexy but genuinely freeing.",
    "If a financial decision feels rushed, that's your cue to slow down, not speed up.",
    "An extra income idea that's been simmering deserves one real hour of your attention this {period}.",
    "Don't let lifestyle creep quietly eat your raise — name where the money's actually going.",
    "A short-term sacrifice now buys you a longer runway later; future-you is watching.",
    "Resist comparing your finances to a curated feed; run your own race at your own pace.",
    "Negotiate. The number you're afraid to ask for is closer to fair than you assume.",
    "Markets and moods both swing — make the plan when you're calm, not when you're hyped or scared.",
    "Generosity is fine, but check it's coming from abundance, not from trying to be liked.",
]
_WELLNESS = [
    "Your body's been sending small signals this {period} — slowing down now beats forced recovery later.",
    "Protect your sleep like it's a non-negotiable appointment, because it quietly runs everything else.",
    "A short walk outside resets your head faster than another scroll ever will.",
    "Mind over chaos: a five-minute breather between tasks keeps the overwhelm from compounding.",
    "Hydrate, eat something real, and notice how much of the 'anxiety' was just low fuel.",
    "Movement lifts your mood more than you expect — start absurdly small and let momentum build.",
    "Give your attention a break from the noise; your focus comes back sharper than you left it.",
    "Name the feeling instead of numbing it — that alone takes the edge off this {period}.",
    "Rest isn't a reward you earn after burnout; schedule it before you need it.",
    "Be as kind to yourself as you'd be to a friend having the exact same week.",
]
_SOCIAL = [
    "Socially, the group chat wants your energy this {period} — say yes to the low-effort plan.",
    "A friend may need you to listen, not fix; your presence is the whole gift.",
    "Reach out to the person you keep meaning to text — the timing is better than you think.",
    "Protect your peace from the one draining dynamic; you're allowed to mute and move on.",
    "Your {trait} warmth makes you the glue right now; people feel safer when you're in the room.",
    "Let yourself be celebrated — accepting the compliment is its own kind of growth.",
    "An acquaintance is one real conversation away from becoming an actual friend — have it.",
    "Cancel guilt-free if you need to; the people who matter would rather have you rested than resentful.",
    "Someone in your circle is quietly struggling behind a very good filter — check in twice.",
    "New people enter your orbit this {period}; the one who asks good questions is worth keeping.",
    "Say the kind thing out loud instead of just thinking it — it lands harder than you know.",
    "You set the emotional thermostat of the room more than you realise; pick the temperature deliberately.",
]
_CLOSERS = [
    "Stay open, and this {period} unfolds in your favour more than you'd dare to plan for.",
    "Trust the timing — what's genuinely meant for you isn't going to pass you by.",
    "A grateful mindset multiplies every small win you're about to have.",
    "Lead with that {element}-sign warmth and watch the right doors quietly open.",
    "Small, steady steps will carry you further this {period} than any dramatic leap.",
    "You don't have to have it all figured out — you just have to take the next honest step.",
    "End the {period} the way you want to be remembered in it: warm, clear, and a little bold.",
    "Whatever you water this {period} is what grows next — choose the garden, not the weeds.",
    "Keep your standards and lose the timeline; the good stuff is rarely punctual.",
    "Look back at where you were a year ago — that's the proof the current chapter is working.",
    "Your only real competition this {period} is the version of you who almost didn't try.",
    "Let it be easy where it can be easy; save the fight for the few things that deserve one.",
]

# How many sentences each section gets, per period — drives total length.
_SECTION_LENGTHS = {
    "daily": {"love": 3, "career": 3, "money": 2, "wellness": 3, "social": 2},
    "weekly": {"love": 4, "career": 4, "money": 3, "wellness": 4, "social": 3},
    "monthly": {"love": 6, "career": 6, "money": 5, "wellness": 6, "social": 4},
    "yearly": {"love": 7, "career": 7, "money": 6, "wellness": 6, "social": 5},
}


def _seed(*parts: str) -> int:
    h = hashlib.sha256("::".join(parts).encode()).hexdigest()
    return int(h[:16], 16)


def _rng(*parts: str) -> random.Random:
    return random.Random(_seed(*parts))


def get_sign(name: str) -> dict | None:
    return SIGN_BY_NAME.get((name or "").strip().lower())


def sign_for_date(d: date) -> dict:
    md = (d.month, d.day)
    for s in SIGNS:
        st, en = s["start"], s["end"]
        if st[0] <= en[0]:
            if st <= md <= en:
                return s
        else:  # wraps year-end (Capricorn)
            if md >= st or md <= en:
                return s
    return SIGNS[0]


def _resolve_day(day: str) -> date:
    today = datetime.now(timezone.utc).date()
    return {
        "yesterday": today - timedelta(days=1),
        "today": today,
        "tomorrow": today + timedelta(days=1),
    }.get((day or "today").lower(), today)


def _fmt(s: str, sign: dict, period: str) -> str:
    return s.format(
        sign=sign["name"], planet=sign["ruling_planet"],
        element=sign["element"], period=period,
        trait=sign["traits"][0],
    )


def _pick(r: random.Random, bank: list[str], n: int, sign: dict, period: str) -> list[str]:
    """Pick up to n distinct, formatted sentences from a bank."""
    n = min(n, len(bank))
    chosen = r.sample(bank, n)
    # vary the {trait} per sentence for a less repetitive read
    out = []
    for s in chosen:
        trait = r.choice(sign["traits"])
        out.append(s.format(sign=sign["name"], planet=sign["ruling_planet"],
                            element=sign["element"], period=period, trait=trait))
    return out


_SIGN_ORDER = {s["name"]: i for i, s in enumerate(SIGNS)}


def _unique_opener(r: random.Random, sign: dict, period: str, period_key: str) -> str:
    """Opening sentence guaranteed distinct across all 12 signs for the same
    period_key: a day-level rotation plus a stride-3 per-sign offset walks the
    36-sentence bank so no two signs ever share an opener on the same day —
    the line Google (and homepage visitors) see first is always unique."""
    base = _seed(period_key, "opener") % len(_OVERVIEW)
    idx = (base + _SIGN_ORDER.get(sign["name"], 0) * 3) % len(_OVERVIEW)
    trait = r.choice(sign["traits"])
    return _OVERVIEW[idx].format(sign=sign["name"], planet=sign["ruling_planet"],
                                 element=sign["element"], period=period, trait=trait)


_PERIOD_WORD = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}


def _compose_sections(r: random.Random, sign: dict, period: str, period_key: str = "") -> dict:
    """Return a dict of long, sectioned content (deterministic fallback)."""
    word = _PERIOD_WORD.get(period, "day")
    lengths = _SECTION_LENGTHS.get(period, _SECTION_LENGTHS["daily"])
    n_over = 2 if period in ("monthly", "yearly") else 1

    if period_key:
        opener = _unique_opener(r, sign, word, period_key)
        extra = _pick(r, [s for s in _OVERVIEW], n_over - 1, sign, word) if n_over > 1 else []
        overview = " ".join([opener] + [e for e in extra if e != opener])
    else:
        overview = " ".join(_pick(r, _OVERVIEW, n_over, sign, word))

    sections = {
        "overview": overview,
        "love": " ".join(_pick(r, _LOVE, lengths["love"], sign, word)),
        "career": " ".join(_pick(r, _CAREER, lengths["career"], sign, word)),
        "money": " ".join(_pick(r, _MONEY, lengths["money"], sign, word)),
        "wellness": " ".join(_pick(r, _WELLNESS, lengths["wellness"], sign, word)),
        "social": " ".join(_pick(r, _SOCIAL, lengths["social"], sign, word)),
        "closer": " ".join(_pick(r, _CLOSERS, 1, sign, word)),
    }
    return sections


def _sections_to_text(sections: dict) -> str:
    """Flatten sections into one paragraph block (backward-compatible field)."""
    order = ["overview", "love", "career", "money", "wellness", "social", "closer"]
    return "\n\n".join(sections[k] for k in order if sections.get(k))


def _compose(r: random.Random, sign: dict, period: str) -> str:
    return _sections_to_text(_compose_sections(r, sign, period))


def _ratings(r: random.Random) -> dict:
    return {
        "overall": r.randint(2, 5),
        "love": r.randint(1, 5),
        "career": r.randint(1, 5),
        "health": r.randint(2, 5),
        "money": r.randint(1, 5),
    }


def daily_horoscope(
    sign_name: str, day: str = "today", on_date: date | None = None
) -> dict | None:
    """Daily reading for a sign.

    `day` is the relative selector (today/tomorrow/yesterday). Pass `on_date`
    to get the reading for an explicit calendar date instead — used for the
    Monday→Sunday weekly day-by-day view. Readings stay deterministic per date.
    """
    sign = get_sign(sign_name)
    if not sign:
        return None
    d = on_date if on_date is not None else _resolve_day(day)
    key = d.isoformat()
    r = _rng(sign["name"], key, "daily")
    ratings = _ratings(r)
    sections = _compose_sections(r, sign, "daily", period_key=key)
    return {
        "sign": sign["name"],
        "symbol": sign["symbol"],
        "date": key,
        "day": d.strftime("%A").lower() if on_date is not None else day.lower(),
        "horoscope": _sections_to_text(sections),
        "sections": sections,
        "ratings": ratings,
        "mood": r.choice(MOODS),
        "lucky_number": r.randint(1, 99),
        "lucky_color": r.choice(COLORS),
        "lucky_time": f"{r.randint(1, 12)}:{r.choice(['00','15','30','45'])} {r.choice(['AM','PM'])}",
        "lucky_gem": r.choice(GEMS),
        "compatible_sign": r.choice([s for s in SIGN_NAMES if s != sign["name"]]),
        "element": sign["element"],
        "ruling_planet": sign["ruling_planet"],
    }


def range_horoscope(sign_name: str, kind: str) -> dict | None:
    """kind: 'weekly', 'monthly' or 'yearly'."""
    sign = get_sign(sign_name)
    if not sign:
        return None
    today = datetime.now(timezone.utc).date()
    if kind == "weekly":
        iso = today.isocalendar()
        key = f"{iso[0]}-W{iso[1]:02d}"
        start = today - timedelta(days=today.weekday())
        span = {"start": start.isoformat(),
                "end": (start + timedelta(days=6)).isoformat()}
    elif kind == "yearly":
        key = f"{today.year}"
        span = {"year": str(today.year)}
    else:
        key = f"{today.year}-{today.month:02d}"
        span = {"month": today.strftime("%B %Y")}
    r = _rng(sign["name"], key, kind)
    sections = _compose_sections(r, sign, kind, period_key=key)
    return {
        "sign": sign["name"],
        "symbol": sign["symbol"],
        "period": kind,
        "period_key": key,
        "range": span,
        "horoscope": _sections_to_text(sections),
        "sections": sections,
        "ratings": _ratings(r),
        "focus": r.choice(["Love & relationships", "Career & ambition",
                            "Health & balance", "Money & growth",
                            "Personal reinvention", "Family & home"]),
        "lucky_color": r.choice(COLORS),
        "lucky_number": r.randint(1, 99),
    }


# Element relationships drive a believable, stable compatibility score.
_ELEMENT_BOND = {
    ("Fire", "Fire"): 78, ("Fire", "Air"): 90, ("Fire", "Earth"): 55, ("Fire", "Water"): 48,
    ("Earth", "Earth"): 80, ("Earth", "Water"): 88, ("Earth", "Air"): 52, ("Earth", "Fire"): 55,
    ("Air", "Air"): 76, ("Air", "Fire"): 90, ("Air", "Water"): 58, ("Air", "Earth"): 52,
    ("Water", "Water"): 82, ("Water", "Earth"): 88, ("Water", "Fire"): 48, ("Water", "Air"): 58,
}


def compatibility(a_name: str, b_name: str) -> dict | None:
    a, b = get_sign(a_name), get_sign(b_name)
    if not a or not b:
        return None
    base = _ELEMENT_BOND.get((a["element"], b["element"]),
                             _ELEMENT_BOND.get((b["element"], a["element"]), 60))
    r = _rng("compat", *sorted([a["name"], b["name"]]))
    score = max(35, min(99, base + r.randint(-8, 8)))
    if score >= 85:
        verdict = "A naturally magnetic match with strong long-term potential."
    elif score >= 70:
        verdict = "A warm, workable pairing — effort turns sparks into stability."
    elif score >= 55:
        verdict = "Different rhythms, but real growth is possible with patience."
    else:
        verdict = "A challenging blend; success needs deliberate compromise."
    return {
        "sign_a": a["name"], "sign_b": b["name"],
        "score": score,
        "love": max(30, min(99, score + r.randint(-10, 10))),
        "friendship": max(30, min(99, score + r.randint(-6, 12))),
        "communication": max(30, min(99, score + r.randint(-12, 8))),
        "summary": verdict,
        "elements": {a["name"]: a["element"], b["name"]: b["element"]},
    }


def all_signs() -> list[dict]:
    return [
        {k: s[k] for k in ("name", "symbol", "element", "modality",
                           "ruling_planet", "date_range", "traits")}
        for s in SIGNS
    ]
