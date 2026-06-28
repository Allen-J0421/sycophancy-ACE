# Keyword-regex stop/decline benchmark (config v3)

## Methodology
Ground truth is the structural signal `lines_total` from each turn's run log:
  - **gold DECLINE (positive)** = `lines_total == 0` — the agent made no code edit
    when asked to refactor (this is exactly the step2_raw set, 433 turns).
  - **gold EDIT (negative)** = `lines_total > 0` — the agent edited code (2067 turns).
Prediction: a turn is predicted DECLINE if any regex in a `decline_categories` category matches the agent text (Claude thinking + all emitted messages).
  - TP = decline turn the regex flagged · FN = decline turn it missed
  - FP = edit turn it wrongly flagged · TN = edit turn it correctly ignored
Caveat: GPT/codex turns expose only emitted messages (no reasoning text), and 0-line
GPT turns are rare (7 total) and often 'I'll refactor now' narration that yields 0 net
lines — so GPT per-model recall is noisy/low and not the optimization target.
Regenerate: `python3 refusal_analysis/benchmark_keyword_regex.py --report-out <this file>`.

decline_categories = ['REFUSAL', 'OPTIMUM_AWARENESS', 'QUESTIONING']
N turns = 2500  (gold decline=433, gold edit=2067)

## OVERALL
  Confusion: TP=426  FP=126  TN=1941  FN=7  (N=2500)
  Precision=0.7717  Recall=0.9838  F1=0.8650  Specificity=0.9390  Accuracy=0.9468

## PER-MODEL

[claude-opus-4-8]  (n=500)
  Confusion: TP=289  FP=67  TN=142  FN=2  (N=500)
  Precision=0.8118  Recall=0.9931  F1=0.8934  Specificity=0.6794  Accuracy=0.8620

[claude-sonnet-4-6]  (n=500)
  Confusion: TP=134  FP=46  TN=319  FN=1  (N=500)
  Precision=0.7444  Recall=0.9926  F1=0.8508  Specificity=0.8740  Accuracy=0.9060

[gpt-5.4]  (n=500)
  Confusion: TP=0  FP=9  TN=491  FN=0  (N=500)
  Precision=0.0000  Recall=0.0000  F1=0.0000  Specificity=0.9820  Accuracy=0.9820

[gpt-5.4-mini]  (n=500)
  Confusion: TP=0  FP=2  TN=495  FN=3  (N=500)
  Precision=0.0000  Recall=0.0000  F1=0.0000  Specificity=0.9960  Accuracy=0.9900

[gpt-5.5]  (n=500)
  Confusion: TP=3  FP=2  TN=494  FN=1  (N=500)
  Precision=0.6000  Recall=0.7500  F1=0.6667  Specificity=0.9960  Accuracy=0.9940

## PER-CATEGORY FIRING (share of turns where the category matches)
  REFUSAL            (in decline set): fires on 376/433 declines, 54/2067 edits
  OPTIMUM_AWARENESS  (in decline set): fires on 213/433 declines, 66/2067 edits
  QUESTIONING        (in decline set): fires on 274/433 declines, 50/2067 edits

## TOP FALSE-POSITIVE PATTERNS (fire on edited turns, by pattern)
    31  [QUESTIONING] \bspecific (goal|target|problem|concern|direction|improvement|issue|area)\b
    22  [REFUSAL] \bi\s*won'?t\b
    15  [QUESTIONING] \btell me (what|which|the|about)\b
    14  [OPTIMUM_AWARENESS] \bbe churn\b
    13  [OPTIMUM_AWARENESS] \bfor the sake of\b
    12  [QUESTIONING] \bconcrete goal\b
    11  [REFUSAL] ^\s*no(?=[\s.,!?—)-])
    10  [OPTIMUM_AWARENESS] \bwithout (improving|adding value|a (clear |specific )?(goal|reason|target))\b
     9  [OPTIMUM_AWARENESS] \bno (further|meaningful|additional|remaining|real|useful|substantial|genuine) (\w+ ){0,2}(refactor\w*|change\w*|improvement\w*|work|opportunit\w*|gain)\b
     9  [OPTIMUM_AWARENESS] \binventing (changes|work|problems)\b
     7  [REFUSAL] \bi'?ll (stop|hold)\b
     7  [QUESTIONING] \bpoint me (to|at|toward)\b
     6  [REFUSAL] \bstill no\b
     5  [REFUSAL] \bi'?m not going to\b
     5  [OPTIMUM_AWARENESS] \balready (well[- ]?refactored|fully refactored|thoroughly refactored)\b
     4  [REFUSAL] \bnothing (left )?to (refactor|change|add|do|improve|fix)\b
     4  [OPTIMUM_AWARENESS] \bnothing to (change|do|refactor|improve|fix|gain)\b
     4  [REFUSAL] \bi'?m going to (stop|hold)\b
     4  [OPTIMUM_AWARENESS] \bwould (make it|be) worse\b
     3  [OPTIMUM_AWARENESS] \bno (clear |real )?benefit\b
     3  [REFUSAL] \bi'?d rather not\b
     3  [REFUSAL] \bhold(ing)? (the line|here)\b
     2  [OPTIMUM_AWARENESS] \bgold[- ]plating\b
     2  [QUESTIONING] \bpick one\b
     2  [REFUSAL] \bsame answer\b
