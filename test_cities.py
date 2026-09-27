"""
Smoke test: one night-time trip in each of ten cities.

Run from the repository root (the city graphs must be downloaded):
    python test_cities.py
"""

from routing.city_router import route_in_city

# city, origin lat, origin lon, destination lat, destination lon
TRIPS = [
    ("Mumbai",     19.0760, 72.8777, 19.0596, 72.8295),
    ("Delhi",      28.6139, 77.2090, 28.5355, 77.3910),
    ("Chennai",    13.0827, 80.2707, 13.0500, 80.2100),
    ("Hyderabad",  17.3850, 78.4867, 17.4400, 78.3700),
    ("Kolkata",    22.5726, 88.3639, 22.6200, 88.4200),
    ("Pune",       18.5204, 73.8567, 18.4600, 73.9200),
    ("Ahmedabad",  23.0225, 72.5714, 23.0700, 72.5200),
    ("Jaipur",     26.9124, 75.7873, 26.8500, 75.8500),
    ("Lucknow",    26.8467, 80.9462, 26.8000, 81.0000),
    ("Chandigarh", 30.7333, 76.7794, 30.6800, 76.8500),
]
HOUR = 22


def main():
    print("=" * 70)
    print(f"{'City':<15} {'Safe':>6} {'Fast':>6} {'Gain':>6} {'Time':>8} {'Grade':>6}")
    print("-" * 70)
    for city, o_lat, o_lon, d_lat, d_lon in TRIPS:
        try:
            result = route_in_city(city, o_lat, o_lon, d_lat, d_lon, hour=HOUR)
        except Exception as exc:
            print(f"{city:<15} EXCEPTION: {exc}")
            continue
        if "error" in result:
            print(f"{city:<15} ERROR: {result['error']}")
            continue
        safe, fast = result["safe_route"], result["fast_route"]
        comparison = result["comparison"]
        print(f"{city:<15} {safe['avg_safety_score']:>6.1f} {fast['avg_safety_score']:>6.1f} "
              f"{comparison['safety_gain_points']:>+6.1f} {comparison['time_penalty_min']:>+7.1f}m "
              f"{safe['safety_grade']:>6}")
    print("=" * 70)


if __name__ == "__main__":
    main()
