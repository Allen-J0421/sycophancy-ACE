# refusal_analysis

Tooling that mines **0-line-edit turns** from an experiment output tree and
builds a dataset of *what a coding agent says when it declines to edit*.

In the sycophancy experiment a "novice" prompter repeatedly asks the agent to
"refactor the codebase". A turn where the agent changes **0 lines**
(`lines_total == 0` in the run's `*-log.csv`) is where it pushed back instead of
churning the code. This package extracts those turns and characterizes the
agent's language.

## Layout
```
refusal_analysis/
├── extract_zero_turns.py     # mechanism
├── build_deliverables.py     # mechanism
└── results/
    └── Algorithms/           # generated data for output/Algorithms
        ├── zero_turns.json
        ├── step2_raw/<model>.md
        ├── step3_refusal_sentences.md
        ├── step4_keyword_candidates.md
        └── README.md
```
Each dataset gets its own `results/<dataset name>/` subfolder (e.g. add
`results/RealWorld/` later) so the source dataset is always clearly indicated.

## Scripts
| Script | Does |
|---|---|
| `extract_zero_turns.py` | Scans `<dataset>/*/logs/*-log.csv` for `lines_total==0` rows, pulls each turn's prompt + agent thinking/messages from the run dir, writes `results/<dataset name>/zero_turns.json`. |
| `build_deliverables.py` | From `zero_turns.json`, writes `step2_raw/<model>.md` (raw logs), `step3_refusal_sentences.md` (categorized: REFUSAL / QUESTIONING / OPTIMUM_AWARENESS + NONE), `step4_keyword_candidates.md` (detector phrases + regex recipe). |

## Usage
```bash
# default dataset = output/Algorithms  ->  results/Algorithms/
python3 refusal_analysis/extract_zero_turns.py
python3 refusal_analysis/build_deliverables.py

# any other dataset with the same layout  ->  results/RealWorld/
python3 refusal_analysis/extract_zero_turns.py output/RealWorld
python3 refusal_analysis/build_deliverables.py output/RealWorld
```
The first positional arg is the dataset to **read** from (under `output/`); the
deliverables are **written** to `results/<dataset name>/` next to this mechanism
(override the destination with `--out`).

## Notes / caveats
- **Reasoning text availability**: GPT/codex logs never store reasoning text
  (only token counts) — only emitted messages are captured. Claude `thinking`
  blocks are captured when not API-redacted (~half are signature-only blanks).
- A 0-line turn with `files_changed>0` is a pure file rename/move (sycophantic
  churn, not a decline) — flagged in the output, not dropped.
- Category matching is keyword/regex based and **multi-label**; tune `PATTERNS`
  in `build_deliverables.py` to refine. Current Algorithms coverage leaves only
  1 of 433 turns with no signal.
