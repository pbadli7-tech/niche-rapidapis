"""
Static IPL / T20 / international cricket player roster.
Used as a guaranteed fallback when external APIs are unavailable.

Each entry: {id, name, country, team, role, batting_style, bowling_style}
"""

PLAYERS = [
    # --- Indian / IPL stars ---
    {"id": "kohli", "name": "Virat Kohli", "country": "India", "team": "RCB", "role": "Batsman", "batting_style": "Right-handed", "bowling_style": "Right-arm medium"},
    {"id": "rohit", "name": "Rohit Sharma", "country": "India", "team": "MI", "role": "Batsman", "batting_style": "Right-handed", "bowling_style": "Right-arm off-break"},
    {"id": "gill", "name": "Shubman Gill", "country": "India", "team": "GT", "role": "Batsman", "batting_style": "Right-handed", "bowling_style": "Right-arm off-break"},
    {"id": "klrahul", "name": "KL Rahul", "country": "India", "team": "LSG", "role": "Wicketkeeper-Batsman", "batting_style": "Right-handed", "bowling_style": "Right-arm off-break"},
    {"id": "gaikwad", "name": "Ruturaj Gaikwad", "country": "India", "team": "CSK", "role": "Batsman", "batting_style": "Right-handed", "bowling_style": "Right-arm off-break"},
    {"id": "iyer", "name": "Shreyas Iyer", "country": "India", "team": "KKR", "role": "Batsman", "batting_style": "Right-handed", "bowling_style": "Right-arm leg-break"},
    {"id": "yadav", "name": "Suryakumar Yadav", "country": "India", "team": "MI", "role": "Batsman", "batting_style": "Right-handed", "bowling_style": "Right-arm off-break"},
    {"id": "samson", "name": "Sanju Samson", "country": "India", "team": "RR", "role": "Wicketkeeper-Batsman", "batting_style": "Right-handed", "bowling_style": "Right-arm off-break"},
    {"id": "pant", "name": "Rishabh Pant", "country": "India", "team": "DC", "role": "Wicketkeeper-Batsman", "batting_style": "Left-handed", "bowling_style": "—"},
    {"id": "kishan", "name": "Ishan Kishan", "country": "India", "team": "MI", "role": "Wicketkeeper-Batsman", "batting_style": "Left-handed", "bowling_style": "—"},
    {"id": "dhoni", "name": "MS Dhoni", "country": "India", "team": "CSK", "role": "Wicketkeeper-Batsman", "batting_style": "Right-handed", "bowling_style": "Right-arm medium"},
    {"id": "karthik", "name": "Dinesh Karthik", "country": "India", "team": "RCB", "role": "Wicketkeeper-Batsman", "batting_style": "Right-handed", "bowling_style": "—"},
    {"id": "jaiswal", "name": "Yashasvi Jaiswal", "country": "India", "team": "RR", "role": "Batsman", "batting_style": "Left-handed", "bowling_style": "Right-arm leg-break"},

    # --- Indian all-rounders ---
    {"id": "hardik", "name": "Hardik Pandya", "country": "India", "team": "MI", "role": "All-rounder", "batting_style": "Right-handed", "bowling_style": "Right-arm fast-medium"},
    {"id": "jadeja", "name": "Ravindra Jadeja", "country": "India", "team": "CSK", "role": "All-rounder", "batting_style": "Left-handed", "bowling_style": "Slow left-arm orthodox"},
    {"id": "axar", "name": "Axar Patel", "country": "India", "team": "DC", "role": "All-rounder", "batting_style": "Left-handed", "bowling_style": "Slow left-arm orthodox"},
    {"id": "ashwin", "name": "Ravichandran Ashwin", "country": "India", "team": "RR", "role": "All-rounder", "batting_style": "Right-handed", "bowling_style": "Right-arm off-break"},
    {"id": "krunal", "name": "Krunal Pandya", "country": "India", "team": "LSG", "role": "All-rounder", "batting_style": "Left-handed", "bowling_style": "Slow left-arm orthodox"},
    {"id": "sundar", "name": "Washington Sundar", "country": "India", "team": "SRH", "role": "All-rounder", "batting_style": "Left-handed", "bowling_style": "Right-arm off-break"},

    # --- Indian bowlers ---
    {"id": "bumrah", "name": "Jasprit Bumrah", "country": "India", "team": "MI", "role": "Bowler", "batting_style": "Right-handed", "bowling_style": "Right-arm fast"},
    {"id": "shami", "name": "Mohammed Shami", "country": "India", "team": "GT", "role": "Bowler", "batting_style": "Right-handed", "bowling_style": "Right-arm fast"},
    {"id": "siraj", "name": "Mohammed Siraj", "country": "India", "team": "RCB", "role": "Bowler", "batting_style": "Right-handed", "bowling_style": "Right-arm fast-medium"},
    {"id": "chahal", "name": "Yuzvendra Chahal", "country": "India", "team": "RR", "role": "Bowler", "batting_style": "Right-handed", "bowling_style": "Right-arm leg-break"},
    {"id": "kuldeep", "name": "Kuldeep Yadav", "country": "India", "team": "DC", "role": "Bowler", "batting_style": "Left-handed", "bowling_style": "Slow left-arm chinaman"},
    {"id": "natarajan", "name": "T Natarajan", "country": "India", "team": "SRH", "role": "Bowler", "batting_style": "Left-handed", "bowling_style": "Left-arm fast-medium"},
    {"id": "umran", "name": "Umran Malik", "country": "India", "team": "SRH", "role": "Bowler", "batting_style": "Right-handed", "bowling_style": "Right-arm fast"},
    {"id": "arshdeep", "name": "Arshdeep Singh", "country": "India", "team": "PBKS", "role": "Bowler", "batting_style": "Left-handed", "bowling_style": "Left-arm fast-medium"},
    {"id": "khaleel", "name": "Khaleel Ahmed", "country": "India", "team": "DC", "role": "Bowler", "batting_style": "Left-handed", "bowling_style": "Left-arm fast-medium"},

    # --- International stars in IPL ---
    {"id": "buttler", "name": "Jos Buttler", "country": "England", "team": "RR", "role": "Wicketkeeper-Batsman", "batting_style": "Right-handed", "bowling_style": "—"},
    {"id": "stoinis", "name": "Marcus Stoinis", "country": "Australia", "team": "LSG", "role": "All-rounder", "batting_style": "Right-handed", "bowling_style": "Right-arm medium"},
    {"id": "maxwell", "name": "Glenn Maxwell", "country": "Australia", "team": "RCB", "role": "All-rounder", "batting_style": "Right-handed", "bowling_style": "Right-arm off-break"},
    {"id": "warner", "name": "David Warner", "country": "Australia", "team": "DC", "role": "Batsman", "batting_style": "Left-handed", "bowling_style": "Right-arm leg-break"},
    {"id": "head", "name": "Travis Head", "country": "Australia", "team": "SRH", "role": "Batsman", "batting_style": "Left-handed", "bowling_style": "Right-arm off-break"},
    {"id": "cummins", "name": "Pat Cummins", "country": "Australia", "team": "SRH", "role": "Bowler", "batting_style": "Right-handed", "bowling_style": "Right-arm fast"},
    {"id": "starc", "name": "Mitchell Starc", "country": "Australia", "team": "KKR", "role": "Bowler", "batting_style": "Left-handed", "bowling_style": "Left-arm fast"},
    {"id": "narine", "name": "Sunil Narine", "country": "West Indies", "team": "KKR", "role": "All-rounder", "batting_style": "Left-handed", "bowling_style": "Right-arm off-break"},
    {"id": "russell", "name": "Andre Russell", "country": "West Indies", "team": "KKR", "role": "All-rounder", "batting_style": "Right-handed", "bowling_style": "Right-arm fast-medium"},
    {"id": "pooran", "name": "Nicholas Pooran", "country": "West Indies", "team": "LSG", "role": "Wicketkeeper-Batsman", "batting_style": "Left-handed", "bowling_style": "—"},
    {"id": "rashid", "name": "Rashid Khan", "country": "Afghanistan", "team": "GT", "role": "Bowler", "batting_style": "Right-handed", "bowling_style": "Right-arm leg-break"},
    {"id": "nabi", "name": "Mohammad Nabi", "country": "Afghanistan", "team": "MI", "role": "All-rounder", "batting_style": "Right-handed", "bowling_style": "Right-arm off-break"},
    {"id": "boult", "name": "Trent Boult", "country": "New Zealand", "team": "MI", "role": "Bowler", "batting_style": "Right-handed", "bowling_style": "Left-arm fast-medium"},
    {"id": "williamson", "name": "Kane Williamson", "country": "New Zealand", "team": "GT", "role": "Batsman", "batting_style": "Right-handed", "bowling_style": "Right-arm off-break"},
    {"id": "conway", "name": "Devon Conway", "country": "New Zealand", "team": "CSK", "role": "Wicketkeeper-Batsman", "batting_style": "Left-handed", "bowling_style": "—"},
    {"id": "rabada", "name": "Kagiso Rabada", "country": "South Africa", "team": "PBKS", "role": "Bowler", "batting_style": "Right-handed", "bowling_style": "Right-arm fast"},
    {"id": "miller", "name": "David Miller", "country": "South Africa", "team": "GT", "role": "Batsman", "batting_style": "Left-handed", "bowling_style": "—"},
    {"id": "klaasen", "name": "Heinrich Klaasen", "country": "South Africa", "team": "SRH", "role": "Wicketkeeper-Batsman", "batting_style": "Right-handed", "bowling_style": "—"},
    {"id": "stubbs", "name": "Tristan Stubbs", "country": "South Africa", "team": "DC", "role": "Batsman", "batting_style": "Right-handed", "bowling_style": "Right-arm leg-break"},
    {"id": "livingstone", "name": "Liam Livingstone", "country": "England", "team": "PBKS", "role": "All-rounder", "batting_style": "Right-handed", "bowling_style": "Right-arm leg-break"},
    {"id": "salt", "name": "Phil Salt", "country": "England", "team": "RCB", "role": "Wicketkeeper-Batsman", "batting_style": "Right-handed", "bowling_style": "—"},
    {"id": "curran", "name": "Sam Curran", "country": "England", "team": "PBKS", "role": "All-rounder", "batting_style": "Left-handed", "bowling_style": "Left-arm medium-fast"},
    {"id": "stokes", "name": "Ben Stokes", "country": "England", "team": "CSK", "role": "All-rounder", "batting_style": "Left-handed", "bowling_style": "Right-arm fast-medium"},
    {"id": "shakib", "name": "Shakib Al Hasan", "country": "Bangladesh", "team": "KKR", "role": "All-rounder", "batting_style": "Left-handed", "bowling_style": "Slow left-arm orthodox"},
    {"id": "mustafizur", "name": "Mustafizur Rahman", "country": "Bangladesh", "team": "DC", "role": "Bowler", "batting_style": "Left-handed", "bowling_style": "Left-arm fast-medium"},

    # --- Pakistan / international (T20I) ---
    {"id": "babar", "name": "Babar Azam", "country": "Pakistan", "team": "Pakistan", "role": "Batsman", "batting_style": "Right-handed", "bowling_style": "Right-arm off-break"},
    {"id": "rizwan", "name": "Mohammad Rizwan", "country": "Pakistan", "team": "Pakistan", "role": "Wicketkeeper-Batsman", "batting_style": "Right-handed", "bowling_style": "—"},
    {"id": "shaheen", "name": "Shaheen Afridi", "country": "Pakistan", "team": "Pakistan", "role": "Bowler", "batting_style": "Left-handed", "bowling_style": "Left-arm fast"},
    {"id": "naseem", "name": "Naseem Shah", "country": "Pakistan", "team": "Pakistan", "role": "Bowler", "batting_style": "Right-handed", "bowling_style": "Right-arm fast"},
]


def search_static(name: str) -> list:
    """Substring match across name, country, team, role."""
    q = (name or "").lower().strip()
    if not q:
        return []
    out = []
    for p in PLAYERS:
        if (
            q in p["name"].lower()
            or q in p["country"].lower()
            or q in p["team"].lower()
            or q in p["role"].lower()
        ):
            out.append(p)
    return out


def get_static(player_id: str) -> dict | None:
    pid = (player_id or "").lower().strip()
    for p in PLAYERS:
        if p["id"] == pid:
            return p
    return None
