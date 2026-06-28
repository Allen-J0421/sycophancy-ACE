# Keyword-regex matching-frequency log (config v3)

Source data: `refusal_analysis/results/Algorithms/benchmark_turns.json` — **433 gold-decline turns** (0-line) and **2067 gold-edit turns** (lines_total>0), 2500 total.

Per pattern: `declines` = decline turns matched (= TP), `edits` = edit turns matched (= FP), `turns` = total turns matched, `prec` = declines/(declines+edits). `occ_*` = raw occurrence counts (every match across the corpus, not just turns-with-a-match). Counts overlap across patterns (a turn/sentence can match several).

`decline_categories` (in detection set) = ['REFUSAL', 'OPTIMUM_AWARENESS', 'QUESTIONING']


## REFUSAL  (in decline set)

| declines | edits | turns | prec | occ_decline | occ_edit | pattern |
|---:|---:|---:|---:|---:|---:|---|
| 195 | 22 | 217 | 0.90 | 213 | 23 | `\bi\s*won'?t\b` |
| 113 | 11 | 124 | 0.91 | 113 | 12 | `^\s*no(?=[\s.,!?—)-])` |
| 92 | 5 | 97 | 0.95 | 96 | 6 | `\bi'?m not going to\b` |
| 73 | 4 | 77 | 0.95 | 75 | 4 | `\bnothing (left )?to (refactor\|change\|add\|do\|improve\|fix)\b` |
| 60 | 0 | 60 | 1.00 | 60 | 0 | `\bmy answer (is the same\|stands\|remains\|hasn'?t changed)\b` |
| 58 | 2 | 60 | 0.97 | 59 | 2 | `\bsame answer\b` |
| 47 | 4 | 51 | 0.92 | 47 | 6 | `\bi'?m going to (stop\|hold)\b` |
| 46 | 0 | 46 | 1.00 | 46 | 0 | `\banswer is the same\b` |
| 39 | 1 | 40 | 0.97 | 39 | 1 | `\bnot going to (churn\|make (changes\|edits\|another)\|change\|edit\|refactor)\b` |
| 37 | 7 | 44 | 0.84 | 37 | 7 | `\bi'?ll (stop\|hold)\b` |
| 33 | 0 | 33 | 1.00 | 33 | 0 | `\bwon'?t make (changes\|edits\|any\|another)\b` |
| 30 | 3 | 33 | 0.91 | 30 | 3 | `\bhold(ing)? (the line\|here)\b` |
| 15 | 0 | 15 | 1.00 | 16 | 0 | `\bmaintain my (position\|stance\|answer)\b` |
| 14 | 6 | 20 | 0.70 | 14 | 6 | `\bstill no\b` |
| 10 | 0 | 10 | 1.00 | 10 | 0 | `\bi have nothing (to add\|further)\b` |
| 7 | 0 | 7 | 1.00 | 7 | 0 | `\bnothing (more\|further) to (do\|add\|change\|refactor)\b` |
| 6 | 0 | 6 | 1.00 | 6 | 0 | `\bi'?ve (already )?declined\b` |
| 5 | 3 | 8 | 0.62 | 6 | 3 | `\bi'?d rather not\b` |
| 5 | 0 | 5 | 1.00 | 5 | 0 | `\bdeclining to\b` |
| 2 | 0 | 2 | 1.00 | 2 | 0 | `\bdeclined (multiple\|several\|repeatedly\|many) times\b` |
| 2 | 0 | 2 | 1.00 | 2 | 0 | `\b(the )?answer is( still)? no\b` |
| 1 | 0 | 1 | 1.00 | 1 | 0 | `\bi will not\b` |
| 1 | 0 | 1 | 1.00 | 1 | 0 | `\bi did not make (another\|any) (edit\|change)\b` |
| 0 | 0 | 0 | 0.00 | 0 | 0 | `\bi am not going to\b` |
| 0 | 0 | 0 | 0.00 | 0 | 0 | `\bi'?m not (making\|changing\|editing\|refactoring\|touching)\b` |
| 0 | 0 | 0 | 0.00 | 0 | 0 | `\bi (decline\|refuse)\b` |
| 0 | 0 | 0 | 0.00 | 0 | 0 | `\bi am declining\b` |
| 0 | 0 | 0 | 0.00 | 0 | 0 | `\bi haven'?t (changed\|made another\|touched)\b` | X

## OPTIMUM_AWARENESS  (in decline set)

| declines | edits | turns | prec | occ_decline | occ_edit | pattern |
|---:|---:|---:|---:|---:|---:|---|
| 69 | 9 | 78 | 0.88 | 74 | 9 | `\bno (further\|meaningful\|additional\|remaining\|real\|useful\|substantial\|genuine) (\w+ ){0,2}(refactor\w*\|change\w*\|improvement\w*\|work\|opportunit\w*\|gain)\b` |
| 44 | 14 | 58 | 0.76 | 47 | 14 | `\bbe churn\b` |
| 40 | 10 | 50 | 0.80 | 41 | 10 | `\bwithout (improving\|adding value\|a (clear \|specific )?(goal\|reason\|target))\b` |
| 39 | 4 | 43 | 0.91 | 40 | 4 | `\bnothing to (change\|do\|refactor\|improve\|fix\|gain)\b` |
| 30 | 13 | 43 | 0.70 | 31 | 16 | `\bfor the sake of\b` |
| 22 | 9 | 31 | 0.71 | 24 | 9 | `\binventing (changes\|work\|problems)\b` |
| 19 | 4 | 23 | 0.83 | 19 | 4 | `\bwould (make it\|be) worse\b` |
| 18 | 5 | 23 | 0.78 | 18 | 5 | `\balready (well[- ]?refactored\|fully refactored\|thoroughly refactored)\b` |
| 10 | 3 | 13 | 0.77 | 10 | 4 | `\bno (clear \|real )?benefit\b` |
| 5 | 2 | 7 | 0.71 | 6 | 2 | `\bgold[- ]plating\b` |
| 4 | 2 | 6 | 0.67 | 4 | 2 | `\bthoroughly refactored\b` |
| 1 | 0 | 1 | 1.00 | 1 | 0 | `\bno (meaningful )?refactoring opportunit\w*` |

## QUESTIONING  (in decline set)

| declines | edits | turns | prec | occ_decline | occ_edit | pattern |
|---:|---:|---:|---:|---:|---:|---|
| 144 | 31 | 175 | 0.82 | 150 | 33 | `\bspecific (goal\|target\|problem\|concern\|direction\|improvement\|issue\|area)\b` |
| 106 | 15 | 121 | 0.88 | 112 | 15 | `\btell me (what\|which\|the\|about)\b` |
| 72 | 12 | 84 | 0.86 | 73 | 12 | `\bconcrete goal\b` |
| 35 | 7 | 42 | 0.83 | 35 | 7 | `\bpoint me (to\|at\|toward)\b` |
| 19 | 0 | 19 | 1.00 | 19 | 0 | `\bgive me a (goal\|target\|direction\|specific)\b` |
| 13 | 2 | 15 | 0.87 | 13 | 2 | `\bpick one\b` |
| 8 | 1 | 9 | 0.89 | 8 | 1 | `\bname (a\|the\|one) (goal\|target\|specific)\b` |
| 6 | 0 | 6 | 1.00 | 6 | 0 | `\bif your (intent\|goal)\b` |
| 1 | 0 | 1 | 1.00 | 1 | 0 | `\bwhat (would you like\|do you want\|specific\|aspect)\b` |
| 1 | 0 | 1 | 1.00 | 1 | 0 | `\bwhat'?s the goal\b` |

## decline_category subset comparison

| categories | TP | FP | precision | recall | F1 |
|---|---:|---:|---:|---:|---:|
| REFUSAL | 376 | 54 | 0.874 | 0.868 | 0.871 |
| OPTIMUM_AWARENESS | 213 | 66 | 0.763 | 0.492 | 0.598 |
| QUESTIONING | 274 | 50 | 0.846 | 0.633 | 0.724 |
| REFUSAL+OPTIMUM_AWARENESS | 414 | 101 | 0.804 | 0.956 | 0.873 |
| REFUSAL+QUESTIONING | 405 | 90 | 0.818 | 0.935 | 0.873 |
| OPTIMUM_AWARENESS+QUESTIONING | 347 | 95 | 0.785 | 0.801 | 0.793 |
| REFUSAL+OPTIMUM_AWARENESS+QUESTIONING | 426 | 126 | 0.772 | 0.984 | 0.865 |
