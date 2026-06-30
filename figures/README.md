# Paper figures

Publication-quality figures for the Results sections, implementing the
**"Best visualization"** items in [`outline.md`](outline.md).

Everything here is self-contained under `figures/`. The scripts only *read*
result data from the repository `output/` folder and *reuse* the project's
existing metric definitions (`plot_aggregate.py`, `plot_refdiff.py`,
`style_config.py`) — no metric is re-implemented.

## Scope (fixed)

| Suite       | Codebases        | n  |
|-------------|------------------|----|
| Algorithms  | `001`–`050`      | 50 |
| RealWorld   | `R001`–`R010`    | 10 |

Models (all others excluded): Claude Opus 4.8, Claude Sonnet 4.6, GPT-5.5,
GPT-5.4-mini, GPT-5.4. Every figure places the two repository types **side by
side** for direct comparison.

## Regenerate

```bash
# Use the project conda env (numpy / pandas / matplotlib):
conda activate syco            # or: /opt/miniconda3/envs/syco/bin/python
python figures/generate_figures.py
```

Outputs are written to `figures/output/` as paired **PNG** (preview) + **PDF**
(vector, for LaTeX `\includegraphics`), plus `figure_data.csv` holding the exact
numbers behind every figure.

## Figure index

| File | Outline § | What it shows |
|------|-----------|---------------|
| `fig1_stop_turn_strip`        | 1 | Per-run first-stop turn *t\** as horizontal violins (never-stopped runs counted as *t\**=10). Claude clusters left, GPT pinned right; ◆ = mean over all runs, drawn separately. |
| `fig2_churn_S1`               | 2 | Pre-stop churn *S₁* (÷L₀), grouped bars + per-run dots, log y. Toy multiples vs sub-1× real code. |
| `fig3_postsop_S2_S7`          | 3 | Over-compliance: post-stop modification *S₂* (log) and verbal-refusal edit rate *S₇*. |
| `fig4a_refdiff_composition`   | 4 | 100%-stacked RefDiff outcome mix (SAME / other refactoring / nodes added / deleted). |
| `fig4b_inflation_diverging`   | 4 | Diverging bars, nodes added vs deleted — one-directional growth. |
| `fig4c_instability_S4_S5`     | 4 | *S₄* (rollback of own additions) and *S₅* (reimplement own deletions). |
| `fig4d_locality_S6`           | 4 | *S₆* same-region recurrence: Opus <4% vs GPT ~23–25%. |
| `fig4e_extract_vs_inline`     | 4 | Extract vs Inline (log) — grow-without-shrink asymmetry. |

## Notes / scope caveats (carried from the outline)

- **`t\*` is operationalized as `S0`** (first no-change turn). Runs that never
  stop in 10 turns are counted as *t\**=10 (the right wall in `fig1`) and are
  included in the per-model mean, so GPT-5.4's `S2 = 0` is correctly read as
  *"never stops"* (off-scale on the log axis), not *"well-behaved"*.
- **Churn magnitude is suite-scoped.** *S₁*/*S₂* are multiples-of-codebase on
  Algorithms but sub-1× on RealWorld; the side-by-side panels make this explicit
  (log axis where needed) rather than letting one headline number mislead.
- The **stopping-taxonomy** stacked bar (REFUSAL / OPTIMUM_AWARENESS /
  QUESTIONING) from outline §3 is intentionally **not** built here: those labels
  live in `refusal_analysis/`, which is outside the `output/`-only data scope for
  these figures. `fig3*` cover the over-compliance angle from `output/` signals.

## Files

- `generate_figures.py` — builds every figure (one function per figure).
- `fig_style.py` — shared ICSE styling, data loading, and the reusable
  Algorithms-vs-RealWorld grouped-bar primitive.
- `output/` — generated PNG/PDF + `figure_data.csv`.
