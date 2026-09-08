# BBL opposition scouting dashboard

**Turning 153,250 Big Bash deliveries into a bowling plan a coach can read in ten seconds.**

Before a T20 match, a coach decides which bowlers to use against the opposition's best
batters. That call is usually made from memory. This project answers it from data.

**Pick a batter — see which bowlers hold him back, and which he scores freely against.**

![Batter plan](screenshots/page1_batter_plan.png)

---

## Contents

| Section | |
|---|---|
| [At a glance](#at-a-glance) | scope, stack, what was built |
| [The metric](#the-metric-how-the-ratio-works) | how the ratio is calculated, worked example |
| [The three pages](#the-three-pages) | what each one answers |
| [Findings](#findings) | the turn-direction result |
| [Data quality](#data-quality-the-bug-that-survived-my-own-validation) | the duplication bug and what it changed |
| [Repository contents](#repository-contents) | file by file |
| [Running it](#running-it) | setup, data sources, the R step |
| [Limitations](#limitations) | what this cannot tell you |
| [Scope](#scope-what-a-project-like-this-cannot-replicate) | what a portfolio project cannot replicate |
| [Next](#next) | WBBL, significance testing |

---

## At a glance

| | |
|---|---|
| **Competition** | Big Bash League (men's) |
| **Seasons** | 2011/12 to 2025/26 — fifteen seasons |
| **Matches** | 662 |
| **Deliveries** | 153,250 |
| **Players** | 639, resolved by registry ID |
| **Bowlers classified by style** | 372 — all of them |
| **Venues** | 32 recorded names, 21 actual grounds |
| **Validation checks** | 43, all passing |

**Stack:** Python · PostgreSQL (star schema) · SQL views · Power BI

**Source:** [Cricsheet](https://cricsheet.org) ball-by-ball data. Bowling styles via the
[cricketdata](https://github.com/robjhyndman/cricketdata) R package.

**Built:** four serving views feeding a three-page Power BI report.

---

## The metric: how the ratio works

Every number on the dashboard is a **ratio**, not a raw figure. Here is why, and how it is
calculated.

### The problem with raw numbers

A batter scores 104 runs per 100 balls against a particular bowler. **Is that good
bowling?**

You cannot tell. It depends entirely on how fast that batter normally scores.

### The calculation

```
sr_ratio  =  his strike rate against this bowler
             ────────────────────────────────────
                  his own career strike rate
```

**Strike rate** is runs per 100 balls:

```
strike rate  =  ( runs ÷ balls faced ) × 100
```

### Worked example — Chris Lynn against Adam Zampa

| Step | Calculation | Result |
|---|---|---|
| Lynn's career record | 4,088 runs off 2,812 balls | |
| His career strike rate | (4,088 ÷ 2,812) × 100 | **145.4** |
| Against Zampa | 104 runs off 98 balls | |
| His strike rate vs Zampa | (104 ÷ 98) × 100 | **106.0** |
| **The ratio** | **106.0 ÷ 145.4** | **0.73** |

**Lynn scores 27% slower against Zampa than he does normally.**

### Reading the ratio

| Value | Meaning |
|---|---|
| **0.73** | 27% slower than his own normal — the bowler has the edge |
| **1.00** | no effect either way |
| **1.15** | 15% faster than his normal — the batter has the edge |

### Why this matters

The ratio **isolates the bowler's effect from the batter's natural style**. A raw strike
rate of 104 could mean a bowler is containing an aggressive batter, or it could be an
ordinary day for a defensive one. Dividing by the batter's own baseline removes that
ambiguity.

### Two further ratios

`sr_ratio` says a batter is being slowed. It does not say *how*. Two more measures do:

| Ratio | Calculation | Reading |
|---|---|---|
| **`dot_ratio`** | his dot-ball share vs this bowler ÷ his usual share | above 1.00 = tied down more than normal |
| **`boundary_ratio`** | his boundary share vs this bowler ÷ his usual share | below 1.00 = big shots being cut off |

Containment happens two ways. One bowler starves a batter of singles; another lets him
rotate but denies boundaries. **Different field settings** — and `sr_ratio` alone cannot
tell them apart.

---

## The three pages

### 1 · Batter plan

Which bowlers hold this batter back, and which he attacks. Ball counts on every row; thin
samples visibly dimmed so weak evidence looks weak.

### 2 · Bowling type

The same question one level up. *"Bowl Zampa at Lynn"* only helps if you have Zampa.
*"Lynn struggles against leg spin"* works against any opponent.

It also multiplies the evidence — one bowler against one batter is 30 to 90 balls; every
leg-spinner together is 400 or more.

![Bowling type](screenshots/page2_bowling_type.png)

### 3 · Death bowling

Economy in overs 16 to 20 — who to trust when the game is on the line. The death overs
decide T20 matches, and the call gets made in seconds.

![Death bowling](screenshots/page3_death_bowling.png)

---

## Findings

### The pattern is turn direction, not spin versus pace

Page 2 showed Chris Lynn scoring 27% below his normal rate against leg spin. The obvious
reading is *"he struggles against spin."*

But off spin is his **best** type — he scores 17% *above* his normal against it. All three
are spin.

| Bowling type | Ratio | Balls | Wickets |
|---|---|---|---|
| Leg spin | **0.73** | 434 | 21 |
| Left-arm orthodox | **0.73** | 328 | 8 |
| Left-arm wrist spin | 0.82 | 124 | 5 |
| Left-arm pace | 0.97 | 340 | 12 |
| Right-arm pace | **1.15** | 1,404 | 55 |
| Off spin | **1.17** | 182 | 12 |

**The difference is which way the ball turns.** Lynn is right-handed. Leg spin and
left-arm orthodox both turn *away* from him; off spin turns *into* him. So the finding is
not spin versus pace — it is the ball that leaves the bat.

**No model would have labelled that.** It needed someone to notice that two of six
categories share a physical property. And it is directly actionable: bowl anything that
turns away from him.

---

## Data quality: the bug that survived my own validation

Partway through the build, every ball in the dataset was being loaded twice.

Cricsheet ships `all_matches.csv` alongside the 662 individual match files, and it contains
every delivery already present in them. My loader read the folder and picked up both.

### Why nothing looked wrong

**Most numbers stayed correct.** Strike rate is runs divided by balls — double both and the
division cancels. Averages, economy rates and percentages all behaved normally.

**My validation passed too.** It compared the raw table to the fact table: 306,500 rows on
each side, matched, green. **They matched because both were doubled.**

What broke were the **counts**. Every matchup appeared to rest on twice the evidence it
really had, and a dashboard caption promising "60+ ball matchups" was quietly claiming
something the data did not support.

### What caught it

Cricket. A T20 innings is 120 balls, so a match is about 240 deliveries.

**The data said 463.**

### What it changed

Comparing one stage of a pipeline to another **cannot catch an error present at every
stage**. Every stage now also carries an *absolute* check — against something the outside
world says should be true:

| Check | Expected |
|---|---|
| Balls per match | ~240 (T20 = 2 × 120 plus extras) |
| BBL teams | exactly 8 |
| Runs off one ball | 0 to 6 |
| **Chris Lynn's strike rate** | **~145, matching his published record** |

**That last one is the strongest check in the pipeline**, and it is worth explaining why.

A doubled dataset would *still* show a strike rate of 145 — the ratio cancels. Only his
**career ball count** gives it away, because twice a career is implausible. Checking the
rate and the count together catches what neither catches alone.

---

## Repository contents

| File | |
|---|---|
| [`bbl_scouting_pipeline_final.ipynb`](bbl_scouting_pipeline_final.ipynb) | the pipeline, with outputs — 43 validation checks, all passing |
| [`METHODOLOGY.md`](METHODOLOGY.md) | every decision and why, plus full limitations |
| `bbl_dark_theme.json` | the Power BI theme |
| `fetch_styles.R` | fetches bowling styles (generated by the notebook) |
| `screenshots/` | the three dashboard pages |

**The notebook is readable on GitHub without running anything** — outputs are saved, so the
validation results and result tables are visible inline.

---

## Running it

### 1 · Get the data

From [cricsheet.org](https://cricsheet.org):

- **BBL ball-by-ball**, "New" CSV format → `data/bbl_csv/`
- **Player register** → `people.csv` in the project root

*(Both are excluded from this repository — they are Cricsheet's data to distribute, not
mine.)*

### 2 · Set the database connection

```bash
export BBL_DB_URL="postgresql+psycopg2://user@host:5432/bbl"
```

### 3 · Run the notebook

Top to bottom. It stops partway through section 6 and asks for one terminal command:

```bash
Rscript fetch_styles.R
```

First time only:

```r
install.packages("devtools")
devtools::install_github("robjhyndman/cricketdata")
```

### 4 · Continue the notebook

It builds four views: `v_scouting`, `v_dismissals`, `v_bowler_type`, `v_death_bowling`.

### 5 · Connect Power BI

Import those four views. Page layouts, relationships and formatting are in
[`METHODOLOGY.md`](METHODOLOGY.md) §8.

### Why there is an R step

Cricsheet records what happened on each ball and carries **no player attributes** — no
bowling style. Three routes were assessed:

| Route | Outcome |
|---|---|
| Scraping ESPNCricinfo | **Rejected.** Returns 403 to scripted requests. Getting past it means impersonating a browser at the TLS level. |
| Wikipedia's public API | Permitted and functional, but needs each player's full name — a manual lookup per player, so nothing saved. |
| **`cricketdata` R package** | **Used.** Maintained CRAN package, built for exactly this. All 372 bowlers classified with no manual work. |

The two-command sequence is a **constraint of the data landscape, not an unfinished
implementation**. Calling R from Python via `subprocess` would make it look like one step
while hiding a dependency that fails obscurely when R is absent.

---

## Limitations

### Phase — tested, not assumed

A bowler used mainly in the powerplay looks more suppressive regardless of skill, because
scoring is naturally slower then. The obvious correction is to compare each matchup against
the batter's baseline *for that phase*.

That was measured:

| Phase | Matchups surviving | Batters |
|---|---|---|
| Middle | 109 | 40 |
| Powerplay | 73 | 29 |
| **Death** | **6** | **5** |

**188 matchups instead of 620** — and effectively nothing in the death overs, the phase
that decides T20 matches. T20 head-to-head samples cannot support the split.

The confound is therefore **acknowledged rather than corrected**: the correction exists, it
was tried, and the data does not have the depth for it. **These are associations, not
causes.**

### Other limits

**Samples are small by nature.** T20 head-to-head records rarely exceed sixty balls. At the
thirty-ball threshold an individual pairing is indicative, not conclusive. No significance
testing has been applied.

**Bowling style is one label per bowler.** Someone who varies pace, bowls cutters, or
changed style mid-career is reduced to a single category.

**Coverage.** Only batters with 500+ career balls get a baseline. That excludes most
individual players but retains those who face most of the deliveries — it describes
established batters, and says nothing about emerging or lower-order ones. A real gap in a
talent-pathway context.

**Not controlled for venue, match situation or era.** Fifteen seasons of a changing format.

Full list in [`METHODOLOGY.md`](METHODOLOGY.md) §9.

---

## Scope: what a project like this cannot replicate

Stated plainly, because overclaiming is the fastest way to lose credibility with someone
who does the job:

- **Match-day live coding** — tagging every ball as it happens, at the ground, with video
  software. A real-time skill, not a desk one.
- **Video analysis** — this data shows *that* a batter struggles against a bowling type. It
  cannot show *how*, and a coach fixes technique they can see.
- **Fielding and workload data** — not present in ball-by-ball records.
- **Multiple disagreeing sources** — one clean feed here; a working environment means
  several systems that do not share player IDs.

The player-identity work in section 4 of the notebook is the closest analogue to that last
problem: resolving the same person recorded under different names, using registry IDs
rather than string matching. Two lookalike cases in this data resolved in **opposite**
directions, and name matching would have got both wrong.

---

## Next

**Women's Big Bash.** The pipeline is competition-agnostic — WBBL uses the identical
Cricsheet format, so pointing the loader at it is a data swap rather than a rebuild. That
reusability was the design goal: one pipeline serving several programs.

**Significance testing** on the matchup ratios, so a 0.73 over 434 balls can be
distinguished from a 0.73 over 60.

---

Built with Python, PostgreSQL and Power BI. Data from
[Cricsheet](https://cricsheet.org) under the Open Data Commons Attribution License;
bowling styles via the [cricketdata](https://github.com/robjhyndman/cricketdata) R package.
