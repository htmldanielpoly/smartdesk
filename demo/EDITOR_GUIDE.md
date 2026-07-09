# SmartDesk — Grid Incident Demo · Editor Guide

**The story (30-second pitch):** a utility company is hit by *two* grid
incidents at once — a downtown substation blackout in **Westbrook** and a
storm knocking down lines in **Riverton**. Customers flood the support line
with 50 complaints. SmartDesk automatically **prioritizes** each complaint,
**clusters** them into the two real incidents, filters out the noise, and hands
the manager a clear overview with a recommended action per incident.

This folder gives you everything to cut a ~75–90 second video: a self-playing
animated dashboard (your main footage), six poster frames (title cards / photos),
and the real simulation script (optional "authentic product" B-roll).

---

## 1. Asset inventory

| File | What it is | How you use it |
|---|---|---|
| **`dashboard.html`** | Self-playing animated "Grid Operations Center". Auto-runs ~45s: complaints stream in, get triaged + clustered live, counters tick, ends on the manager overview. | **Primary video footage.** Screen-record it (see §4). |
| **`scenes.html`** | 6 full-screen **poster frames**: `#cover`, `#chaos`, `#incident-a`, `#incident-b`, `#overview`, `#how`. | **Photos / title cards / cutaways.** Screenshot each frame, or screen-record while pressing → to advance. |
| **`simulate_incidents.py`** | The real simulation: generates the 50 complaints and clusters them with SmartDesk's actual duplicate-detection logic. Prints a clean console summary. | Optional **B-roll**: record the terminal running it. With `--live` it creates the tickets in the *real* SmartDesk app so you can film the actual product UI. |
| **`data/timeline.json`**, **`data/incidents.json`** | The generated complaint stream + manager rollup. | Source of truth for on-screen numbers. Nothing to film; reference only. |

All numbers below come from the simulation and match the on-screen values:
**50 complaints → 41 clustered into 2 incidents · 9 filtered as noise · 98% clustering accuracy · ~4,060 customers affected.**
Incident A (Westbrook): **URGENT, 25 reports, ~3,500 customers.**
Incident B (Riverton): **HIGH, 16 reports, ~560 customers.**

---

## 2. Storyboard & shot list (target ~1:20)

| # | Time | Source | Shot | On-screen / caption |
|---|---|---|---|---|
| 1 | 0:00–0:05 | `scenes.html#cover` | Title card, hold. Slow push-in if you want motion. | *Two grid incidents. One flood of complaints.* |
| 2 | 0:05–0:13 | `scenes.html#chaos` | The problem: a wall of raw, unsorted complaints; big red **50**. | Caption: *"50 complaints in minutes — which are the same incident?"* |
| 3 | 0:13–0:52 | `dashboard.html` | **Hero shot.** Full screen-recording of the live triage: complaints stream into the feed, flash cyan ("AI classifying"), snap into Incident A / B / noise; counters climb; SLA bars fill. | Let it breathe — this is the payoff of *watching* it work. |
| 4 | 0:52–1:02 | `dashboard.html` end state (or `scenes.html#overview`) | Hold on the settled board: two incident cards, "Manager overview ready" banner, KPI strip. | Caption: *"From chaos to 2 incidents — automatically."* |
| 5 | 1:02–1:16 | `scenes.html#how` | The three steps: Triage → Cluster → Overview. | — |
| 6 | 1:16–1:22 | `scenes.html#cover` (or logo) | Outro / logo, fade. | *SmartDesk · runs locally, no API keys.* |

**Optional authenticity insert (10–15s, anywhere after shot 4):** run
`python demo/simulate_incidents.py --live http://localhost:8080` against a
running stack, then screen-record the real SmartDesk **agent queue** at
`http://localhost:8080` showing the same tickets triaged by priority. This
proves the demo reflects the real product, not just a mockup.

---

## 3. Voiceover / narration script

Timed to the storyboard. Conversational, ~135 wpm.

1. **(cover)** "It's 2 PM, and a utility company just lost power in two cities at once."
2. **(chaos)** "Within minutes, fifty complaints pour in — outages, brownouts, billing questions, even a spam message. Which ones are the same incident? A human dispatcher is already drowning."
3. **(dashboard — as it runs)** "SmartDesk reads every complaint as it arrives. It scores the urgency… and groups reports that describe the same event. Watch: the Westbrook blackout builds on the left, the Riverton storm on the right — and the noise gets filtered out."
4. **(overview)** "In seconds, fifty complaints become two clear incidents — ranked by severity, with the number of customers affected and a recommended crew to dispatch."
5. **(how)** "It's three steps: prioritize, cluster, brief the manager. It runs locally, needs no API keys, and falls back to safe rules if the AI is offline."
6. **(outro)** "SmartDesk. Turning the flood into a plan."

---

## 4. How to record the footage

**Dashboard (main footage):**
1. Open `demo/dashboard.html` in Chrome or Edge (double-click the file).
2. Press **F11** for fullscreen. Best at **1920×1080** (set display scale to 100%).
3. It auto-plays after a ~2.5s intro and runs ~45s, ending on the overview.
   Press **R** to restart for a clean take, **Space** to pause on a good frame.
4. Record with **OBS Studio** (free) or Windows **Game Bar** (`Win`+`G` → record).
   Capture the browser window/monitor at 1080p, 30 or 60 fps.
5. Do 2–3 takes; the run is deterministic, so takes are identical — pick the cleanest capture.

**Poster frames (photos / title cards):**
- Open `demo/scenes.html`, F11 fullscreen. Use **→ / ←** or number keys **1–6**
  to move between frames, or open a frame directly (e.g. `scenes.html#overview`).
- For stills: screenshot each frame (`Win`+`Shift`+`S`) at 1920×1080.
- For motion title cards: screen-record and hold each frame 3–4s.

**Tips:** hide the browser bookmarks bar and use a clean profile; the pages are
pure dark so no light-mode surprises; both pages respect *reduced motion* if the
OS setting is on (turn it **off** to get the animations).

---

## 5. Editing notes

- **Pacing/music:** a tense, building bed under shots 1–3 that *resolves* on
  shot 4 (the overview) sells the "chaos → clarity" arc. Cut shot transitions on
  the beat. A subtle riser into shot 3 works well.
- **Transitions:** hard cuts fit the control-room tone. Avoid flashy wipes. A
  quick 4–6 frame dip-to-black between the poster frames and the live dashboard
  is enough.
- **Lower-thirds/captions:** keep them in the same palette — cyan `#38e0ff`
  accent, red `#ff5a4d` for URGENT, amber `#ffb020` for HIGH, on the dark
  ground `#0a0f1c`. Monospace font for numbers matches the UI.
- **Emphasis:** consider a punch-in (scale 105–110%) on the KPI strip when
  "98% accuracy" and "~4,060 customers" land.
- **Length:** 60–90s is ideal for a presentation. If you need 30s, keep shots
  2 → 3 → 4 only.

## 6. Export settings

- **Resolution:** 1920×1080 (1080p). **Frame rate:** 30 fps (60 if your capture is 60).
- **Codec:** H.264, MP4 container. **Bitrate:** 12–20 Mbps for crisp text.
- **Audio:** -14 LUFS if there's voiceover + music; duck music under narration.
- Name it e.g. `smartdesk_grid_incident_demo_v1.mp4`.

---

## 7. Reproduce / customize the data

Change the complaints, cities, or counts by editing the corpus at the top of
`simulate_incidents.py`, then regenerate:

```bash
python demo/simulate_incidents.py           # rewrites data/ + prints the summary
```

If you change the numbers, update the embedded `DATA` array in `dashboard.html`
(copy from `data/timeline.json`) and the figures in `scenes.html` so the footage
stays consistent. To drive the *real* product instead of the animation:

```bash
docker compose up -d                                        # start SmartDesk
python demo/simulate_incidents.py --live http://localhost:8080
# then screen-record the queue/tickets at http://localhost:8080
```

> **Honesty note for the presentation:** the clustering in the animation uses
> SmartDesk's real *duplicate-detection* approach (token-overlap similarity —
> the model-free fallback that ships in `ai-service`). With the local embedding
> model loaded, the same logic runs on semantic vectors and clusters even
> better. The category vocabulary is configurable; for a utility you'd define
> power/outage/voltage categories instead of the default IT-support set.
