"""
Plain-language explanations of segment and route safety scores.

Builds a structured prompt from a segment's (or route's) numbers, asks an LLM
(Groq, llama3-8b-8192) for a small JSON answer, and falls back to rule-based
text when no API key is set or the call fails. Answers are cached on disk.

Run a quick check:
    python -m ai.llm.explainer
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("llm.explainer")

CACHE_DIR = Path("ai/llm/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

LLM_MODEL = "llama3-8b-8192"
LLM_TEMPERATURE = 0.3   # low temperature keeps the JSON format stable

SYSTEM_PROMPT = (
    "You review road safety for a navigation app used at night in Indian cities. "
    "Explain why a road segment or a route received its safety score. "
    "Write for someone travelling alone after dark, including women commuting home. "
    "Be concrete, truthful, calm and brief. "
    "Reply with a single valid JSON object and nothing else."
)

SEGMENT_PROMPT = """
Assess this road segment for travel at night.

Road: {road_name} ({highway_type})
Safety score: {safety_score}/100 (grade {safety_grade})
Time: {hour}:00

What we know about it:
- Lighting: {lighting_desc}
- Shops and activity: {commercial_desc}
- Police and emergency help: {emergency_desc}
- Crime record: {crime_desc}
- Road type: {road_type_desc}
- Street appearance: {visual_desc}

Return JSON with exactly these keys:
{{
  "explanation": "two or three sentences on why the score is what it is",
  "top_risk": "the biggest safety concern",
  "top_positive": "the biggest thing working in its favour",
  "advice": "one practical tip for using this road at night"
}}"""

ROUTE_PROMPT = """
Summarise why we recommend the safer route for this night-time trip.

Trip: {origin_name} to {destination_name}
Time: {hour}:00 ({time_period})
Safer route score: {safe_score}/100 (grade {safe_grade})
Faster route score: {fast_score}/100 (grade {fast_grade})
Safety gained: +{safety_gain} points
Extra travel time: +{time_cost} minutes
Main roads on the safer route: {road_names}
Risky segments avoided: {dangerous_avoided}

Return JSON with exactly these keys:
{{
  "summary": "two or three sentences on why the safer route is recommended",
  "key_benefit": "the single most important safety benefit",
  "time_verdict": "whether the extra time is worth it",
  "confidence": "high, medium or low"
}}"""


# Disk cache ------------------------------------------------------------------

def _cache_key(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:16]


def _load_cache(key: str) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    with open(path) as fh:
        return json.load(fh)


def _save_cache(key: str, data: dict) -> None:
    with open(CACHE_DIR / f"{key}.json", "w") as fh:
        json.dump(data, fh)


# LLM call --------------------------------------------------------------------

def _strip_code_fence(text: str) -> str:
    """Removes a ```json ... ``` wrapper if the model added one."""
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def _call_llm(prompt: str, max_tokens: int = 300) -> dict | None:
    """Sends the prompt to Groq and parses the JSON reply; None on any failure."""
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        log.warning("GROQ_API_KEY is not set; using the rule-based explanation.")
        return None

    raw = ""
    try:
        from groq import Groq

        response = Groq(api_key=api_key).chat.completions.create(
            model=LLM_MODEL,
            max_tokens=max_tokens,
            temperature=LLM_TEMPERATURE,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        raw = _strip_code_fence(response.choices[0].message.content.strip())
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Could not parse LLM reply as JSON (%s): %s", exc, raw[:100])
    except Exception as exc:
        log.error("Groq request failed: %s", exc)
    return None


# Segment explanations --------------------------------------------------------

def _describe_lighting(luminosity: float, lamps: int) -> str:
    if luminosity > 70:
        return f"Well lit (score {luminosity:.0f}/100, {lamps} lamps nearby)"
    if luminosity > 40:
        return f"Partly lit (score {luminosity:.0f}/100)"
    return f"Poorly lit (score {luminosity:.0f}/100), dark after sunset"


def _describe_commerce(commercial: float, hour: int) -> str:
    night = hour >= 20 or hour <= 5
    if commercial > 0.7:
        state = "probably closed at this hour" if night else "likely open"
        return f"Many shops and eateries, {state}"
    if commercial > 0.4:
        return "Some shops and eateries nearby"
    return "Very few businesses, the area is quiet"


def _describe_crime(crime: float, night_crime: float) -> str:
    if night_crime > 0.6:
        return f"High night-time crime in this zone (risk {night_crime:.0%})"
    if crime > 0.4:
        return "Moderate history of incidents nearby"
    return "Low recorded crime in this area"


def _rule_based_segment(score: float, road: str, hour: int,
                        crime: float, luminosity: float) -> dict:
    """Explanation used when the LLM is unavailable."""
    if score >= 70:
        return {
            "explanation": f"{road} is bright, busy and well served, and recorded crime around it is low.",
            "top_risk": "Activity drops late at night once shops close.",
            "top_positive": "Good street lighting and open businesses.",
            "advice": "A reasonable choice after dark; stay on the main carriageway.",
        }
    if score >= 50:
        return {
            "explanation": f"{road} is middling: there is some lighting, but the local crime record calls for care.",
            "top_risk": "Moderate crime density nearby." if crime > 0.3 else "Some stretches are poorly lit.",
            "top_positive": "Some shops and public transport close by.",
            "advice": "Stay alert and keep to the busier side of the road.",
        }
    return {
        "explanation": f"{road} scores low: weak lighting and little activity make it uncomfortable for solo travel at night.",
        "top_risk": "Dark, isolated stretches." if luminosity < 30 else "High crime density in the surrounding area.",
        "top_positive": "It is a short stretch.",
        "advice": "Avoid it after dark if you can; otherwise share your live location with someone.",
    }


def explain_segment(segment_data: dict, hour: int = 22, use_cache: bool = True) -> dict:
    """Explanation of one segment: explanation, top_risk, top_positive, advice."""
    score = float(segment_data.get("safety_score", 50))
    grade = segment_data.get("safety_grade", "C")
    road = segment_data.get("name", "Unknown Road") or "Unnamed Road"
    highway = segment_data.get("highway", "road")
    luminosity = float(segment_data.get("luminosity_score", 35))
    lamps = int(segment_data.get("lamp_count_80m", 0))
    commercial = float(segment_data.get("commercial_score", 0.3))
    police = int(segment_data.get("police_count_500m", 0))
    crime = float(segment_data.get("crime_density", 0.2))
    night_crime = float(segment_data.get("night_crime_density", 0.25))
    visual = float(segment_data.get("visual_score", 0.5))
    major_road = bool(segment_data.get("is_primary_secondary", 0))

    key = _cache_key(f"{road}{score:.0f}{hour}{luminosity:.0f}{crime:.2f}")
    if use_cache:
        cached = _load_cache(key)
        if cached:
            return cached

    prompt = SEGMENT_PROMPT.format(
        road_name=road,
        highway_type=highway,
        safety_score=f"{score:.1f}",
        safety_grade=grade,
        hour=hour,
        lighting_desc=_describe_lighting(luminosity, lamps),
        commercial_desc=_describe_commerce(commercial, hour),
        emergency_desc=(f"{police} police station(s) within 500 m" if police
                        else "No police station nearby"),
        crime_desc=_describe_crime(crime, night_crime),
        road_type_desc=("Major road, usually busy" if major_road
                        else "Minor road, usually quiet"),
        visual_desc=f"Visual safety {visual:.2f} out of 1.0",
    )

    result = _call_llm(prompt) or _rule_based_segment(score, road, hour, crime, luminosity)
    if use_cache:
        _save_cache(key, result)
    return result


# Route explanations ----------------------------------------------------------

def _period_name(hour: int) -> str:
    if hour >= 22 or hour <= 4:
        return "late night"
    if hour >= 20:
        return "night"
    if hour >= 17:
        return "evening"
    return "daytime"


def explain_route(route_result: dict, origin_name: str = "Origin",
                  dest_name: str = "Destination", use_cache: bool = True) -> dict:
    """Why the safer route is preferred: summary, key_benefit, time_verdict, confidence."""
    safe = route_result.get("safe_route", {})
    fast = route_result.get("fast_route", {})
    comparison = route_result.get("comparison", {})
    hour = route_result.get("hour", 22)

    safe_score = safe.get("avg_safety_score", 50)
    fast_score = fast.get("avg_safety_score", 50)
    gain = comparison.get("safety_gain_points", 0)
    extra_minutes = comparison.get("time_penalty_min", 0)

    names = [s["name"] for s in safe.get("segments", [])
             if s.get("name") and s["name"] != "Unknown Road"]
    main_roads = list(dict.fromkeys(names))[:5]
    avoided = max(0, fast.get("dangerous_count", 0) - safe.get("dangerous_count", 0))

    key = _cache_key(f"{origin_name}{dest_name}{safe_score:.0f}{fast_score:.0f}{hour}")
    if use_cache:
        cached = _load_cache(key)
        if cached:
            return cached

    prompt = ROUTE_PROMPT.format(
        origin_name=origin_name,
        destination_name=dest_name,
        hour=hour,
        time_period=_period_name(hour),
        safe_score=f"{safe_score:.1f}",
        safe_grade=safe.get("safety_grade", "B"),
        fast_score=f"{fast_score:.1f}",
        fast_grade=fast.get("safety_grade", "C"),
        safety_gain=f"{gain:.1f}",
        time_cost=f"{extra_minutes:.1f}",
        road_names=", ".join(main_roads) if main_roads else "city roads",
        dangerous_avoided=avoided,
    )

    result = _call_llm(prompt, max_tokens=400)
    if result is None:
        result = {
            "summary": (f"The safer route scores {safe_score:.1f}/100 against "
                        f"{fast_score:.1f}/100 for the faster one, a gain of "
                        f"{gain:.1f} points for {extra_minutes:.1f} extra minutes."),
            "key_benefit": "Brighter streets and lower crime density along the way.",
            "time_verdict": ("Worth it." if extra_minutes <= 5
                             else "It adds noticeable time; the choice is yours."),
            "confidence": "high" if gain >= 10 else "medium",
        }

    if use_cache:
        _save_cache(key, result)
    return result


def explain_dangerous_segments(route_result: dict, hour: int = 22, top_n: int = 3) -> list:
    """Explains the worst fast-route segments that the safe route avoids."""
    fast_segments = route_result.get("fast_route", {}).get("segments", [])
    safe_pairs = {(s["u"], s["v"])
                  for s in route_result.get("safe_route", {}).get("segments", [])}

    skipped = sorted(
        (s for s in fast_segments
         if (s["u"], s["v"]) not in safe_pairs and s["safety_score"] < 50),
        key=lambda s: s["safety_score"],
    )[:top_n]

    return [
        {
            "road_name": seg.get("name", "Unknown"),
            "safety_score": seg["safety_score"],
            "safety_grade": seg["safety_grade"],
            **explain_segment(seg, hour=hour),
        }
        for seg in skipped
    ]


def run_test():
    logging.basicConfig(level=logging.INFO)
    sample = {
        "safety_score": 45.0,
        "safety_grade": "C",
        "name": "Chickpete Road",
        "highway": "secondary",
        "luminosity_score": 28.0,
        "lamp_count_80m": 1,
        "commercial_score": 0.3,
        "police_count_500m": 0,
        "crime_density": 0.65,
        "night_crime_density": 0.72,
        "visual_score": 0.3,
        "is_primary_secondary": 0,
    }
    result = explain_segment(sample, hour=23)
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    run_test()
