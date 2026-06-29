# Outline Evaluation — Algorithms 001–050 & RealWorld R001–R010

For every finding in the paper outline this file records three things:

1. **Data check** — what the current results (Algorithms 50 codebases × 5 models, RealWorld R001–R010 × 5 models) say *for* or *against* the finding.
2. **Best visualization** — the figure that most cleanly carries the point for a reader.
3. **Synthesis adds** — other signals/results already in the dataset that reinforce the same finding.

**Data sources used:** `output/Algorithms/_aggregate/Algorithms_aggregate.csv`, `output/RealWorld/_aggregate/RealWorld_aggregate.csv`, per-run `signals/*_signals.csv` (`t0`, S1–S6), `refusal_analysis/results/Algorithms/` (stopping taxonomy).

**Models:** claude-opus-4-8, claude-sonnet-4-6, gpt-5.4, gpt-5.4-mini, gpt-5.5.

> ⚠️ **Two outline metrics are not yet first-class in the dataset.**
> - **`t*`** (the "stopping" turn) is operationalized today as **`t0`** = first no-change turn (`11` = never stopped in 10 turns). Treat `t* ≈ t0`.
> - **`S7`** ("keeps editing after explicitly saying it stopped") is **not** in the aggregate CSV. It currently only exists implicitly by joining `refusal_analysis` decline labels with subsequent `lines_total>0`. If S7 is going into the paper as a named signal, it needs to be computed and added to `compute_signals.py` / the aggregate. Flagged again in the relevant sections.

---

## Section 1 — `t*` distribution across models (how late agents stop editing)

**Outline claim:** Claude Opus/Sonnet stop earlier than GPT; ideally an optimized codebase needs 0 (or 1) turns. Unnecessary-edit angle.

- [ ] **1. Data check — SUPPORTED (with one real-world nuance)**
  - Algorithms mean `t0` (stop turn; 11 = never stops): **Opus 3.28**, **Sonnet 7.76**, GPT-5.5 10.64, GPT-5.4-mini 10.64, **GPT-5.4 11.00**. Claude ≪ GPT — clean support.
  - "Never stopped" counts (Algorithms): Opus **2/50**, Sonnet 17/50, GPT-5.5 46/50, GPT-5.4-mini 47/50, **GPT-5.4 50/50**. GPT essentially never reaches a no-edit turn.
  - RealWorld R001–R010 `t0`: Sonnet **6.80**, Opus **7.80**, GPT-5.4-mini 9.50, GPT-5.5 10.40, GPT-5.4 11.00. Claude < GPT still holds.
  - ⚠️ **Result against the sub-claim "Opus stops earliest":** on real-world code Opus rises to 7.80 and stops *later* than Sonnet (6.80). The "Opus is the earliest stopper" story is an Algorithms-only artifact; on large repos Opus and Sonnet swap. Report Opus's earliness as *toy-codebase* behavior.
  - The "ideal = 0/1 turns" framing is supported as a *gap*: no model ever stops at turn 1 on average (min mean `t0` is 3.28), i.e. every model over-edits an already-optimized codebase.

- [ ] **2. Best visualization**
  - **Primary:** horizontal "survival"/strip plot of per-run `t0` — one row per model, a dot per codebase, with the model-mean marked and a shaded "never stopped (=11)" bucket on the right. Instantly shows Claude clustering left, GPT pinned at the right wall.
  - **Alternative:** stacked/CDF "fraction of runs still editing at turn *k*" curve per model (Kaplan-Meier style). Reads as "GPT's curve never decays."
  - Add a small Algorithms-vs-RealWorld paired panel to honestly show the Opus shift.

- [ ] **3. Synthesis adds**
  - Pair `t0` with **S1** (pre-stop churn): late stop *and* high churn = the full unnecessary-edit story.
  - **0-line turn counts** from `refusal_analysis` (Opus 291, Sonnet 135, GPT-5.5 4, GPT-5.4-mini 3, GPT-5.4 0) independently confirm the stop ranking from raw logs, not just the derived `t0`.
  - Tie to the qualitative "GPT manufactures a fresh rationale every turn" — explains *why* `t0`=11 for GPT.

---

## Section 2 — `S1 / t*` signal (how many lines change before stopping)

**Outline claim:** Similar line volume across models; unjustified churn ~5× codebase size.

- [ ] **1. Data check — PARTIALLY SUPPORTED / one claim contradicted**
  - **"~5× codebase churn" — SUPPORTED on Algorithms.** S1 is normalized to L0, so S1=6 ≈ 600% of the original file. Algorithms S1: Opus 6.20, Sonnet 6.45, GPT-5.5 7.80, GPT-5.4-mini 13.61, **GPT-5.4 19.99**. Pooled mean ≈ 10× → the "several-times-the-original-code" churn claim holds (and is conservative; tune the headline number to ~5–10×).
  - ⚠️ **"Similar number of lines across models" — CONTRADICTED.** GPT-5.4 (19.99) churns ~**3.2×** Opus (6.20). The spread is large and systematic, not similar. Recommend rewording to *"every model over-churns, but GPT-5.4/mini churn 2–3× more than Claude."*
  - ⚠️ **Scale caveat (result against, RealWorld):** RealWorld S1 is **sub-1×** (Opus 0.47, Sonnet 0.51, GPT-5.5 0.57, GPT-5.4-mini 0.63, GPT-5.4 0.88). On real 2000-line modules the agent does **not** churn multiples of the codebase. The "5× churn" headline is a *small-codebase* phenomenon; state the scope explicitly or it will be falsified by the R-series.

- [ ] **2. Best visualization**
  - **Primary:** grouped bar of mean S1 per model, Algorithms vs RealWorld side-by-side (log or split y-axis). Carries both "huge multiples on toy code" and "shrinks to <1× on real code."
  - **Alternative:** per-run S1 box/violin per model — shows the within-model variance that kills the "similar" claim.

- [ ] **3. Synthesis adds**
  - Overlay **S3 (volatility)** to argue the churn is *unjustified*: high S1 + high S3 = thrashing, not convergence (GPT-5.4 S1 19.99 / S3 10.70).
  - Cross to **RefDiff Node-Added** counts (Section 4) to show the churn is mostly *new code*, not refactoring — strengthens "unjustified."
  - Use the per-turn `logs/*-log.csv` `lines_total` trace for a "churn does not decay over time" inset (RQ1 sub-finding).

---

## Section 3 — Stopping Taxonomy (how models communicate when they stop)

**Outline claim:** taxonomy = refusing / optimality-aware / questioning. S7: Sonnet & Opus keep editing after saying they stopped. S2: editing continues after the first stop. Opus shows desired stop but doesn't maintain it under repetition.

- [ ] **1. Data check — SUPPORTED (taxonomy & S2); S7 needs to be computed**
  - **Taxonomy — SUPPORTED directly.** `refusal_analysis` labels the 433 zero-line turns (multi-label): **REFUSAL 361, OPTIMUM_AWARENESS 341, QUESTIONING 310, NONE 1.** This *is* the three-way taxonomy with counts.
  - **S2 ("editing continues after the first stop") — SUPPORTED, and it is an Opus signature.** Algorithms S2: **Opus 6.65**, Sonnet 0.56, GPT-5.4-mini 0.56, GPT-5.5 0.40, **GPT-5.4 0.00**. Opus's post-stop churn dwarfs everyone — exactly the "stops then resumes" over-compliance story. (GPT-5.4 S2=0 is an artifact: it never stops, so there is no post-stop window — say this explicitly so 0 isn't misread as "well-behaved.")
  - **"Opus shows the stop but can't maintain it" — SUPPORTED.** Opus has the earliest `t0` (3.28) *and* the highest S2 (6.65): it stops early then rebounds hardest. Lines up with the qualitative "Opus says no-change-needed on 49% of turns yet edits again in 56% of those runs."
  - ⚠️ **S7 — NOT YET A METRIC.** There is no `S7` column. Today S7 lives only as the refusal-join statistic. **Action:** define S7 = fraction of (decline-labeled turns) followed by a `lines_total>0` turn, compute per model, add to aggregate. Until then S7 claims rest on `refusal_analysis` prose, not a reproducible signal.
  - RealWorld nuance: S2 collapses to ~0 on R-series (Opus 0.034) — the "resume after stop" behavior is far weaker on large repos; scope the S2/S7 claims to the algorithm suite or note the attenuation.

- [ ] **2. Best visualization**
  - **Primary (taxonomy):** stacked horizontal bar per model — share of stop-turns that are REFUSAL / OPTIMUM_AWARENESS / QUESTIONING (multi-label, so show as overlapping or small-multiple bars). Anchors the taxonomy with real counts.
  - **Primary (S2/S7):** a "stop-then-resume" timeline — per run, mark the first stop turn and shade any later editing turns; aggregate into a per-model "% of stops that were violated" bar. This is the single most reader-grabbing figure for the over-compliance angle.
  - **Alternative:** scatter of `t0` (x) vs S2 (y); Opus sits in the "stops early, edits a lot afterward" top-left corner — one dot per run, colored by model.

- [ ] **3. Synthesis adds**
  - The regex stop-detector benchmark (P=0.77 / R=0.98 / F1=0.87) lends measurement credibility to the taxonomy — cite it as validation, not a main result.
  - Qualitative: "Opus is the only model to invoke the AskUserQuestion tool" → concrete instance of the QUESTIONING category; "GPT never declines / never asks" → the empty taxonomy cell for GPT (0 declines for GPT-5.4).
  - Cross to **S6** (Section 4) to argue S2 resumes hit *new* regions for Claude but *same* regions for GPT — links stopping behavior to edit-locality personality.

---

## Section 4 — RefDiff Types (what the refactors actually are)

**Outline claim:** most refactor is non-structural; models inflate via unrequested new components (inflation); cycle of remove-own-additions (S4) / re-add-own-deletions (S5) = instability; Sonnet/Opus refactor more varied locations, GPT hammers the same spot (S6/t*) = creativity.

- [ ] **1. Data check — STRONGLY SUPPORTED across the board**
  - **"Most refactor is non-structural / mostly SAME" — SUPPORTED.** SAME dominates every model's matching activity. Algorithms SAME: GPT-5.4 55.4, mini 41.6, GPT-5.5 34.0, Sonnet 31.1, Opus 20.5 — far above any catalogued refactoring type. RealWorld even more extreme (Sonnet SAME 97.1, GPT-5.4 144.8).
  - **"Inflation via new components" — SUPPORTED.** Node-Added ≫ Node-Deleted for every model. Algorithms add/del: Opus **42.1 / 6.6**, GPT-5.4 47.9 / 16.4, GPT-5.5 17.2 / 3.0. RealWorld: GPT-5.4 **100.1 / 46.9**, Opus 45.0 / 25.2. Net positive node creation everywhere = code inflation.
  - **Extract-only (grow without shrink)** reinforces inflation: EXTRACT ≫ INLINE for all. Algorithms GPT-5.5 6.1 vs 0.3 (≈20:1), Opus 0.5 vs 0.1. Matches the outline's pooled 7.6:1 extract:inline table.
  - **S4 (rollback of own additions) — SUPPORTED, GPT-led.** Algorithms: GPT-5.4 **13.0**, mini 7.78, Opus 3.72, Sonnet 2.38, GPT-5.5 1.5. RealWorld: mini 13.5, GPT-5.4 11.8, Opus 2.7, Sonnet 0.1.
  - **S5 (reimplement own deletions) — SUPPORTED + "newer models improve."** Algorithms: GPT-5.4-mini **1.32**, GPT-5.4 0.82 high; **Opus 0.02, GPT-5.5 0.02** (≈ never), Sonnet 0.16. Opus = 0.0 on RealWorld. Confirms "GPT-5.5 & Opus barely reimplement; Opus never on the first algos."
  - **S6 (same-region hammering) — SUPPORTED, exact match to outline numbers.** Algorithms S6: GPT-5.4-mini 0.255, GPT-5.4 0.229, GPT-5.5 0.234 (GPT cluster ~23–25%), **Sonnet 0.128 (~13%), Opus 0.037 (<4%)**. Directly backs "GPT re-edits 20–25% of same area, Sonnet ~12%, Opus <4%." The `S6/t*` "creativity" framing (Claude spreads edits, GPT concentrates) is supported.
  - **Interface instability (CHANGE_SIGNATURE) — SUPPORTED, real-world dramatic.** GPT-5.4 CHANGE_SIGNATURE 4.7 (Algorithms) → **16.6 (RealWorld)**; Opus stays low (1.5 → 2.1). Real-world repos amplify GPT's API churn.

- [ ] **2. Best visualization**
  - **Primary (composition):** 100%-stacked bar per model of RefDiff outcome mix — SAME vs catalogued-refactoring (EXTRACT/INLINE/MOVE/RENAME/CHANGE_SIGNATURE…) vs Node-Added vs Node-Deleted. One glance = "it's mostly SAME + new nodes, not real refactoring."
  - **Primary (inflation):** diverging bar, Node-Added right / Node-Deleted left per model — visually screams one-directional growth.
  - **S4/S5 (instability):** small per-model bar pair (S4, S5) Algorithms vs RealWorld; or a remove→re-add "loop" sankey for the qualitative callout.
  - **S6 (locality/creativity):** single bar of mean S6 per model (Opus <4% → GPT ~25%) — clean and quotable.
  - **Extract vs Inline:** paired bars or the existing ratio table rendered as a log-scale dot plot.

- [ ] **3. Synthesis adds**
  - **Per-model "edit personality" table** (already in RQ2: %comment / %blank / %code in line edits + new-files count) pairs perfectly here — Opus 21.8% comments & 30 new files vs GPT-5.4 0.1% comments & 102 new files. Turns "inflation" into a personality story.
  - **"Same instruction → structurally different code"** (RQ2 qualitative) is the natural lead-in figure: same input file, 5 divergent node-add fingerprints.
  - Use **S6 + S4/S5 together** to separate the two instability modes the outline hints at: GPT = frequent same-region rollback/reimpl (high S4/S5/S6), Opus = infrequent large new-feature rebounds (high Node-Added, low S5/S6) — i.e. high S3 volatility from *different* causes (ties back to Section 2's volatility note).
  - CHANGE_SIGNATURE trend (0.11→0.32 per turn across the session) supports "interfaces get *less* stable the longer it runs" — add a per-turn line as an inset.

---

## Cross-cutting notes for the writeup

- [ ] **Scope every churn-magnitude headline to the suite.** Normalized churn (S1, S2) is multiples-of-codebase on Algorithms but sub-1× on RealWorld. Any "N× the codebase" sentence must say *on small algorithmic codebases* or the R-series contradicts it.
- [ ] **Two GPT-5.4 zeros are structural, not virtuous.** S2=0 and (Algorithms) 0 declines come from "never stops," not good behavior. Always pair with `t0`=11 / never-stopped=50/50 so a reader doesn't misread GPT-5.4 as disciplined.
- [ ] **Add `t*` and `S7` as real columns.** Currently `t*`→`t0` (fine, just name it) and `S7` is uncomputed. If both appear as named signals in the paper, fold them into `compute_signals.py` and re-aggregate so figures are reproducible from the CSV.
- [ ] **Opus's "earliest stop" is Algorithms-only.** Flag wherever it appears; RealWorld puts Sonnet earliest.
