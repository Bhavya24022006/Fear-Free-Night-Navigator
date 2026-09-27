# Recording the demo video

A 2½-minute walkthrough of the prototype. Set the app up with the [quick start in the README](README.md#quick-start-run-the-demo) first.

## Before you record

1. Start the backend and the frontend (README quick start, steps 2 and 3) and open http://localhost:3000.
2. Wait until the coloured dots of the risk map appear on Bengaluru.
3. Set the browser window to the size you will record, and close other heavy apps.
4. Do a dry run of every scene below once.

Only use the place buttons under **Start from** and **Go to**. These trips answer instantly. Clicking elsewhere on the map, or **My location**, starts a full route calculation that takes minutes on a laptop.

## Script

| Time | On screen | Voiceover |
|---|---|---|
| 0:00–0:15 | App open on the Bengaluru risk map | "Navigation apps find the fastest route. But at 10 PM, the fastest road can be a dark, empty lane. Fear-Free Navigator shows a safer route next to the fastest one, and exactly what it costs." |
| 0:15–0:35 | Zoom gently over the dots | "This is Bengaluru: over 930,000 road segments from OpenStreetMap. An XGBoost model scores every segment from 32 features: NASA night-time lights, nearby shops, police and transit, and crime zones. Each dot is a road, coloured from the city's safest quarter to its riskiest." |
| 0:35–1:10 | Start from **MG Road**, Go to **Majestic**, mode **Car**. Time slider at **14:00**, then move it to **22:00** | "MG Road to Majestic by car. At 2 PM, the safer and fastest routes are the same road; by day the quickest road is fine. Now move the clock to 10 PM. Crime counts more, and dark streets and closed shops lose points. The routes split: the green route scores 51 per km against 41, and cuts high-risk road from 2.2 km to 1 km, for 1.6 extra minutes." |
| 1:10–1:35 | Start from **Indiranagar**, Go to **Majestic**, time **22:00**. Safety slider to **0**, then to **0.3** | "You choose the trade-off. At zero, only time matters, so both routes match. Raise the safety preference to 0.3 and the route switches: high-risk distance drops from 3.1 km to 1.3 km, for under a minute more." |
| 1:35–1:55 | Start from **Majestic**, Go to **MG Road**, 22:00. Switch **Car**, then **Cycle** | "Modes change the rules. Cycling and walking avoid highways and always weigh safety heavily. By bike, the safer route scores 44 against 30, for about a minute more." |
| 1:55–2:10 | Turn on **Women Safety Mode** | "Women Safety Mode locks in the strongest safety weighting and offers live-location sharing on WhatsApp." |
| 2:10–2:25 | **Start trip on the safer route**, show the Directions tab, then point at **Report unsafe area** | "Start the trip for turn-by-turn directions, each step coloured by how safe that stretch is. And anyone can report a spot that feels unsafe." |
| 2:25–2:40 | Closing slide | "Under the hood: open data, a safety score that changes with the hour, and two shortest-path searches, one for safety and one for speed. Today's scores are our own safety index; validating them against real incident reports is next. Fear-Free Navigator: a safer route, for about a minute." |

## What the screen should show

If a number differs from these, the stored routes were rebuilt with different data; update the voiceover to match the screen.

| Scene | Safer route | Faster route |
|---|---|---|
| MG Road → Majestic, car, 14:00 | 68.0 | 68.0 (same road) |
| MG Road → Majestic, car, 22:00 | 50.8, 1.0 km high-risk | 40.6, 2.2 km high-risk, 1.6 min faster |
| Indiranagar → Majestic, car, 22:00, slider 0 | 46.4 | 46.4 (same road) |
| Indiranagar → Majestic, car, 22:00, slider 0.3 | 52.6, 1.3 km high-risk | 46.4, 3.1 km high-risk, 0.8 min faster |
| Majestic → MG Road, cycle, 22:00 | 44.1 | 29.9, 1.2 min faster |

## Trips to avoid

- **Indiranagar ↔ Koramangala, Koramangala ↔ Whitefield, Whitefield → Indiranagar, Whitefield → Majestic and MG Road → Koramangala.** The fastest road is already the safest (or nearly), so both routes show the same score.
- **The safety slider above 0.3.** Most trips have switched to their safer route by then.
- **High-risk distance at 02:00.** Almost every road scores under 40 late at night, so both routes show most of their length as high-risk.
- **The safety slider in Walk and Cycle modes.** It is locked, because those modes always use a fixed safety weight.
