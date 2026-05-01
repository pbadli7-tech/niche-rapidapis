"""
Dream11-style fantasy point calculator.
Rules based on standard T20 fantasy scoring.
"""
from typing import Optional


# T20 scoring rules (Dream11 style)
BATTING = {
    "run": 1,
    "boundary_4": 1,      # bonus per 4
    "boundary_6": 2,      # bonus per 6
    "duck": -2,
    "sr_bonus_170": 6,    # strike rate > 170
    "sr_bonus_150": 4,    # strike rate 150-170
    "sr_bonus_130": 2,    # strike rate 130-150
    "sr_penalty_50": -4,  # strike rate < 50 (min 10 balls)
    "sr_penalty_60": -2,  # strike rate 50-60
    "milestone_30": 4,
    "milestone_50": 8,
    "milestone_100": 16,
}

BOWLING = {
    "wicket": 25,
    "bonus_lbw_bowled": 8,  # extra for LBW/Bowled
    "maiden_over": 12,
    "economy_bonus_4": 6,    # economy < 4
    "economy_bonus_5": 4,    # economy 4-5
    "economy_bonus_6": 2,    # economy 5-6
    "economy_penalty_10": -4,
    "economy_penalty_9": -2,
    "3_wicket_haul": 4,
    "4_wicket_haul": 8,
    "5_wicket_haul": 16,
}

FIELDING = {
    "catch": 8,
    "stumping": 12,
    "run_out_direct": 12,
    "run_out_indirect": 6,
    "3_catches_bonus": 4,
}

BASE_POINTS = 4  # for playing XI


def calculate_batting_points(
    runs: int,
    balls: int,
    fours: int,
    sixes: int,
    dismissed: bool,
    dismissal_type: Optional[str] = None,
) -> dict:
    points = BASE_POINTS
    breakdown = {}

    # Runs
    run_pts = runs * BATTING["run"]
    points += run_pts
    breakdown["runs"] = run_pts

    # Boundaries bonus
    four_pts = fours * BATTING["boundary_4"]
    six_pts = sixes * BATTING["boundary_6"]
    points += four_pts + six_pts
    breakdown["boundaries"] = four_pts + six_pts

    # Duck
    if runs == 0 and dismissed:
        points += BATTING["duck"]
        breakdown["duck"] = BATTING["duck"]

    # Milestones
    if runs >= 100:
        points += BATTING["milestone_100"]
        breakdown["century_bonus"] = BATTING["milestone_100"]
    elif runs >= 50:
        points += BATTING["milestone_50"]
        breakdown["fifty_bonus"] = BATTING["milestone_50"]
    elif runs >= 30:
        points += BATTING["milestone_30"]
        breakdown["thirty_bonus"] = BATTING["milestone_30"]

    # Strike rate (min 10 balls)
    if balls >= 10:
        sr = (runs / balls) * 100
        if sr > 170:
            points += BATTING["sr_bonus_170"]
            breakdown["sr_bonus"] = BATTING["sr_bonus_170"]
        elif sr > 150:
            points += BATTING["sr_bonus_150"]
            breakdown["sr_bonus"] = BATTING["sr_bonus_150"]
        elif sr > 130:
            points += BATTING["sr_bonus_130"]
            breakdown["sr_bonus"] = BATTING["sr_bonus_130"]
        elif sr < 50:
            points += BATTING["sr_penalty_50"]
            breakdown["sr_penalty"] = BATTING["sr_penalty_50"]
        elif sr < 60:
            points += BATTING["sr_penalty_60"]
            breakdown["sr_penalty"] = BATTING["sr_penalty_60"]

    return {"total": points, "breakdown": breakdown}


def calculate_bowling_points(
    wickets: int,
    overs: float,
    runs_conceded: int,
    maidens: int,
    lbw_bowled_wickets: int = 0,
) -> dict:
    points = 0
    breakdown = {}

    # Wickets
    wicket_pts = wickets * BOWLING["wicket"]
    points += wicket_pts
    breakdown["wickets"] = wicket_pts

    # LBW/Bowled bonus
    if lbw_bowled_wickets:
        lb_pts = lbw_bowled_wickets * BOWLING["bonus_lbw_bowled"]
        points += lb_pts
        breakdown["lbw_bowled_bonus"] = lb_pts

    # Maiden overs
    if maidens:
        maiden_pts = maidens * BOWLING["maiden_over"]
        points += maiden_pts
        breakdown["maidens"] = maiden_pts

    # Wicket haul bonuses
    if wickets >= 5:
        points += BOWLING["5_wicket_haul"]
        breakdown["five_wicket_haul"] = BOWLING["5_wicket_haul"]
    elif wickets >= 4:
        points += BOWLING["4_wicket_haul"]
        breakdown["four_wicket_haul"] = BOWLING["4_wicket_haul"]
    elif wickets >= 3:
        points += BOWLING["3_wicket_haul"]
        breakdown["three_wicket_haul"] = BOWLING["3_wicket_haul"]

    # Economy rate (min 2 overs)
    if overs >= 2 and runs_conceded is not None:
        economy = runs_conceded / overs
        if economy < 4:
            points += BOWLING["economy_bonus_4"]
            breakdown["economy_bonus"] = BOWLING["economy_bonus_4"]
        elif economy < 5:
            points += BOWLING["economy_bonus_5"]
            breakdown["economy_bonus"] = BOWLING["economy_bonus_5"]
        elif economy < 6:
            points += BOWLING["economy_bonus_6"]
            breakdown["economy_bonus"] = BOWLING["economy_bonus_6"]
        elif economy >= 10:
            points += BOWLING["economy_penalty_10"]
            breakdown["economy_penalty"] = BOWLING["economy_penalty_10"]
        elif economy >= 9:
            points += BOWLING["economy_penalty_9"]
            breakdown["economy_penalty"] = BOWLING["economy_penalty_9"]

    return {"total": points, "breakdown": breakdown}


def calculate_fielding_points(
    catches: int,
    stumpings: int,
    run_outs_direct: int,
    run_outs_indirect: int,
) -> dict:
    points = 0
    breakdown = {}

    if catches:
        catch_pts = catches * FIELDING["catch"]
        points += catch_pts
        breakdown["catches"] = catch_pts
        if catches >= 3:
            points += FIELDING["3_catches_bonus"]
            breakdown["three_catch_bonus"] = FIELDING["3_catches_bonus"]

    if stumpings:
        st_pts = stumpings * FIELDING["stumping"]
        points += st_pts
        breakdown["stumpings"] = st_pts

    if run_outs_direct:
        ro_pts = run_outs_direct * FIELDING["run_out_direct"]
        points += ro_pts
        breakdown["run_outs_direct"] = ro_pts

    if run_outs_indirect:
        ro_pts = run_outs_indirect * FIELDING["run_out_indirect"]
        points += ro_pts
        breakdown["run_outs_indirect"] = ro_pts

    return {"total": points, "breakdown": breakdown}


def total_fantasy_points(batting: dict, bowling: dict, fielding: dict) -> int:
    return BASE_POINTS + batting.get("total", 0) + bowling.get("total", 0) + fielding.get("total", 0)
