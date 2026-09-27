"""
Routing benchmark across every configured city.

For each city, two trips cross the central part of the bbox (one in each
direction) and are routed at 09:00, 22:00 and 00:00. The per-route results
go to evaluation/results/india_benchmark.csv and a summary is printed.

Run from the repository root:
    python evaluation/benchmark_india.py
"""

from pathlib import Path

import pandas as pd

from ingestion.fetch_india_graph import CITY_BBOXES, INDIAN_CITIES
from routing.city_router import route_in_city

RESULTS = Path("evaluation/results")
RESULTS.mkdir(parents=True, exist_ok=True)

TEST_HOURS = [9, 22, 0]
SPAN_SHARE = 0.2   # trip endpoints sit this far (as a share of the bbox) from the centre


def get_test_routes(city_name: str) -> list:
    """Two diagonal trips through the city centre, in opposite directions."""
    bbox = CITY_BBOXES[city_name]
    centre_lat = (bbox["north"] + bbox["south"]) / 2
    centre_lon = (bbox["east"] + bbox["west"]) / 2
    d_lat = (bbox["north"] - bbox["south"]) * SPAN_SHARE
    d_lon = (bbox["east"] - bbox["west"]) * SPAN_SHARE
    south_west = (centre_lat - d_lat, centre_lon - d_lon)
    north_east = (centre_lat + d_lat, centre_lon + d_lon)
    return [(*south_west, *north_east), (*north_east, *south_west)]


def period_label(hour: int) -> str:
    if 6 <= hour < 17:
        return "day"
    if 20 <= hour < 24:
        return "night"
    return "late_night"


def run_benchmark() -> pd.DataFrame:
    rows = []
    for city in INDIAN_CITIES:
        name = city["name"]
        for o_lat, o_lon, d_lat, d_lon in get_test_routes(name):
            for hour in TEST_HOURS:
                try:
                    result = route_in_city(name, o_lat, o_lon, d_lat, d_lon, hour=hour)
                except Exception as exc:
                    print(f"  FAIL {name} {hour:02d}:00 - {exc}")
                    continue
                if "error" in result:
                    continue
                comparison = result["comparison"]
                rows.append({
                    "city": name,
                    "state": city["state"],
                    "hour": hour,
                    "period": period_label(hour),
                    "safe_score": result["safe_route"]["avg_safety_score"],
                    "fast_score": result["fast_route"]["avg_safety_score"],
                    "safety_gain": comparison["safety_gain_points"],
                    "time_cost": comparison["time_penalty_min"],
                    "worth_it": comparison["safer_route_worth_it"],
                })
                print(f"  ok   {name} {hour:02d}:00 - gain {comparison['safety_gain_points']:+.1f}")

    df = pd.DataFrame(rows)
    df.to_csv(RESULTS / "india_benchmark.csv", index=False)
    return df


def print_summary(df: pd.DataFrame) -> None:
    rule = "=" * 60
    print(f"\n{rule}\nALL-INDIA BENCHMARK SUMMARY\n{rule}")
    print(f"Cities tested    : {df['city'].nunique()}")
    print(f"Routes tested    : {len(df)}")
    print(f"Avg safety gain  : +{df['safety_gain'].mean():.2f} pts")
    print(f"Avg time cost    : +{df['time_cost'].mean():.2f} min")
    print(f"Worth it         : {df['worth_it'].mean() * 100:.0f}%")
    print("\nBy time period:")
    for period in ("day", "night", "late_night"):
        subset = df[df["period"] == period]
        if len(subset):
            print(f"  {period:<12}: gain +{subset['safety_gain'].mean():.2f}  "
                  f"cost +{subset['time_cost'].mean():.2f} min  n={len(subset)}")
    print(rule)


if __name__ == "__main__":
    print_summary(run_benchmark())
