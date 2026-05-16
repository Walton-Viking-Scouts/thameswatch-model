# ThamesWatch: Is the Water Safe for Scouts?

## The Short Answer

We've built a system that checks weather, sewage, and river conditions and tells you whether it's safe to go on the water — **before you get there**. It uses a simple traffic light: RED (don't go), AMBER (test the water first), GREEN (go with confidence).

We tested it against 229 real water quality results from ThamesWatch. When it says GREEN, the water was safe **95% of the time**. When it says RED, the water was unsafe **79% of the time**. It has never given a GREEN when the water was dangerously contaminated.

---

## Why This Matters

E. coli testing takes 24-48 hours in a lab. That's no use when you need to decide this morning whether to put boats on the water. Our system gives an answer in seconds by checking conditions that predict whether the water is contaminated — primarily **sewage discharges** and **rainfall**. It now runs automatically twice a day on live data, so a current RED/AMBER/GREEN for every site is always ready.

---

## What Makes the Water Unsafe

### Sewage overflows are the biggest factor

When it rains heavily, the sewer system overflows and raw sewage is pumped into the rivers that feed the Thames. Thames Water monitors 14 overflow points near our stretch. When sewage is being discharged upstream:

- E. coli levels are **3.4 times higher** than normal
- When overflows are active on both the River Wey and River Mole simultaneously, the water has been **unsafe in every single case** we tested (34 out of 34)
- When 4 or more overflow points are active at the same time, the water has **never been safe**

### But it's not just overflows

Even on dry, sunny days with no overflows, sewage treatment works continuously discharge treated effluent into our rivers. This treated water still contains bacteria — there is no legal limit on E. coli in treated sewage effluent in England. When the river is running low in summer, there isn't enough clean water to dilute it.

### Rainfall drives everything

Heavy rain triggers the sewer overflows. It also washes bacteria from farmland, roads, and bird droppings into the river. The key numbers:

- **Rained today**: only 35% chance the water is safe
- **Heavy rain (>10mm in 48 hours)**: only 5-20% safe
- **3+ dry days, no overflows, summer**: 80-85% safe

---

## Not All Sites Are Equal

This is one of the most important findings. The water quality at our different test sites varies enormously — even on the same day, the same stretch of river can be safe at one point and unsafe 200 metres downstream.

### Our safest sites

**Walton Wharf** — our home base. Safe 93% of the time when conditions look good. The main risk comes from the River Wey, which joins the Thames just upstream at Weybridge and carries sewage from Guildford, Cranleigh, and Woking.

**Chertsey** and **Kingston Half Mile Tree** — consistently clean. Kingston HMT is safe 100% of the time when conditions look good, because it sits just upstream of the Hogsmill sewage works outfall.

### Our problem sites

**Kingston Albany Reach** — just 200m downstream from Kingston HMT, but this site catches the full output of the Hogsmill sewage treatment works. Even on perfect dry summer days, it was only safe 70% of the time. The sewage works creates unpredictable spikes that no weather forecast can predict. **We recommend always testing the water here before any activity.**

**Teddington** — the furthest downstream site, receiving pollution from the entire catchment. In summer 2025, the river flow was so low (just 12-14 cubic metres per second, compared to a normal 30+) that the water was unsafe 75% of the time. **We recommend treating Teddington as unsuitable for water activities unless you test on the day.**

---

## The Scale of the Problem Upstream

We mapped the full extent of sewage discharges feeding into our stretch. The numbers are sobering:

- **River Wey** (joins at Weybridge, above Walton): 15+ overflow points discharged for a combined **2,564 hours** in 2024 — that's 107 days of continuous sewage. Cranleigh sewage works alone: 1,565 hours.
- **River Mole** (joins at East Molesey, above Kingston): 25+ overflow points discharged for a combined **13,100 hours** in 2024. Burstow sewage works near Gatwick was the worst: 1,758 hours.
- **Thames upstream** (Reading, Windsor, Staines): 43 overflow points discharged for 7,309 hours in 2024.

In dry summers, the Wey and Mole make up **over 40% of all the water flowing past Walton**. When those rivers are carrying sewage, there's very little clean Thames water to dilute it.

---

## Watching the Rivers in Real Time

The system now runs by itself. Twice a day — morning and early afternoon — it automatically gathers the latest rainfall, river flow, and sewage-discharge data and publishes a fresh RED/AMBER/GREEN for every site. Nobody has to collect anything by hand.

It also reads the rivers and rain gauges **every 15 minutes**, rather than relying on once-a-day figures — and for upstream rain, that matters a great deal.

Rain that falls on the Wey or Mole headwaters, 20-50 km away, never reaches our stretch as rain. The only warning we get is the tributary rising as that water runs down to us over the following one to three days. A rising river is our early signal for contamination that hasn't arrived yet.

The trouble with once-a-day figures: a daily average can't be calculated until the day is over, and is then published one to three days later. A surge could build for two days before the old approach noticed it.

**A real example — the River Mole, February 2026.** Rain fell across the Mole catchment on 13 February. The river began climbing on the 15th and surged on the 16th, more than doubling — from around 9 to over 20 cubic metres per second. Reading the river every 15 minutes, the system flagged **AMBER for the Kingston and Teddington sites on the 16th — the day the surge happened**. Working from once-a-day averages, the same warning would not have appeared until around the **18th**. That is two full days of earlier warning, on exactly the signal that predicts contamination arriving from upstream.

This is live now: a developing surge on the Wey or Mole flags AMBER the day it begins, not two days later.

---

## How to Use This

The system does the checking for you and publishes a verdict twice a day. The three signals below are what it weighs — useful for understanding a result, or as a manual sense-check.

### The three signals behind every verdict

1. **Has it rained in the last 48 hours?** More than 10mm = RED, don't go. Any rain today = RED.

2. **Are sewage overflows active?** Check the Thames Water storm discharge map. If overflows are active on the Wey (for Walton) or on both Wey and Mole (for Kingston/Teddington) = RED.

3. **How long since the last rain?** 3+ dry days with no overflows in spring/summer = GREEN for Walton, Chertsey, and Kingston HMT.

### Decision framework for leaders

| Signal | What to do |
|---|---|
| **RED** | Do not go on the water. No exceptions. The water is unsafe 79% of the time in these conditions. |
| **AMBER** | Test the water with an R-Card before the activity. If you can't test, don't go. |
| **GREEN** | Go with confidence at Walton, Chertsey, or Kingston HMT. Standard hygiene precautions apply. |

For Kingston Albany Reach and Teddington: the system will never say GREEN because these sites have too much background pollution. Always test.

---

## Recommendations

### This season

1. **Check conditions before every session.** This is now automated. A prediction pipeline runs twice a day — checking rainfall, sewage overflows, and river flow — and publishes a RED/AMBER/GREEN for every site as a machine-readable file (`prediction.json`). A simple leader-facing alert (a web page or text) can be built on top of it as a next step.

2. **Carry R-Card test kits for AMBER days.** The traffic light tells you when conditions are uncertain. A quick test on the day resolves it.

3. **Focus testing where it matters most.** Testing after a sewage overflow event (within 24 hours) gives us far more useful data than testing on a fixed weekly schedule. If leaders can do one extra test when an overflow alert fires, it's worth ten routine tests.

### Longer term

4. **Add two new test sites** at the Wey confluence (below Weybridge) and Mole confluence (below Esher). These tell us exactly what pollution is arriving from each tributary.

5. **Increase sampling at under-tested sites.** Chertsey (11 tests), Teddington (11), and Ditton's Bend (17) all need more data to validate the model, especially outside summer.

6. **Watch the low-flow trend.** Summer 2025 had the lowest Thames flows in our dataset — just 12-14 m3/s for nearly two months. If this becomes the norm with climate change, sites like Teddington will become increasingly difficult to use safely in summer.

---

## How We Built This

We combined three freely available public datasets:

- **ThamesWatch water quality results** — 229 E. coli tests from our monitoring sites (the only source of actual bacteria data on this stretch — the Environment Agency doesn't test for E. coli here)
- **Environment Agency data** — rainfall from 6 gauges across the catchment, river flow from 5 stations (Walton, Wey, Mole, Staines, Reading)
- **Thames Water data** — real-time sewage overflow status from 14 monitored outfalls

All data is free and publicly available. The system runs as a small automated job twice a day — no special software, no laptop, and no manual data-gathering.

We compared our approach against a £5 million government-funded AI project (River Deep Mountain AI) that uses 65 data features and machine learning. Our simple 6-input model matches their accuracy on our stretch — because we include sewage overflow data, which they don't.

---

*Prepared March 2026; updated May 2026 — refreshed dataset, automated twice-daily pipeline, and real-time (15-minute) river and rainfall data.*
*Based on analysis of 229 water quality test results, 800+ days of river flow data, and 14 sewage overflow monitoring points.*
