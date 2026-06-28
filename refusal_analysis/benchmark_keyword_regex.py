#!/usr/bin/env python3
"""Benchmark the stopping-keyword regex dictionary against the labeled turns.

Loads ``keyword_regex_config.json`` and ``benchmark_turns.json`` and measures
how well keyword matching reproduces the structural ground-truth label
(label=1 -> 0-line decline turn; label=0 -> edited turn).

A turn is predicted DECLINE if any regex in a category listed under
``options.decline_categories`` matches the agent text (thinking + messages).

Reports confusion matrix (TP/FP/TN/FN), precision/recall/F1/accuracy, a
per-model and per-category breakdown, and writes the misclassified turns
(false negatives + false positives) to ``results/<ds>/step5_*`` for inspection.

Usage:
    python refusal_analysis/benchmark_keyword_regex.py \
        [--data results/Algorithms/benchmark_turns.json] \
        [--config refusal_analysis/keyword_regex_config.json] \
        [--errors-out PATH] [--report-out PATH] [--quiet]
"""
import argparse, json, os, re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
FLAG_MAP = {'IGNORECASE': re.I, 'MULTILINE': re.M, 'DOTALL': re.S, 'VERBOSE': re.X}


def load_config(path):
    cfg = json.load(open(path))
    flags = 0
    for f in cfg.get('options', {}).get('flags', ['IGNORECASE']):
        flags |= FLAG_MAP[f]
    compiled = {}
    for cat, pats in cfg['categories'].items():
        compiled[cat] = [(p, re.compile(p, flags)) for p in pats]
    decline_cats = cfg['options'].get('decline_categories', list(cfg['categories']))
    return cfg, compiled, decline_cats


def agent_text(r):
    return "\n".join(r.get('thinking', []) + r.get('messages', []))


def matched_categories(text, compiled):
    """Return {category: [matching pattern strings]} for a piece of text."""
    hits = {}
    for cat, pats in compiled.items():
        m = [p for p, rx in pats if rx.search(text)]
        if m:
            hits[cat] = m
    return hits


def evaluate(records, compiled, decline_cats):
    rows = []
    for r in records:
        text = agent_text(r)
        hits = matched_categories(text, compiled)
        predicted = any(c in hits for c in decline_cats)
        rows.append({'r': r, 'text': text, 'hits': hits, 'pred': predicted,
                     'gold': bool(r['label'])})
    return rows


def confusion(rows):
    tp = fp = tn = fn = 0
    for x in rows:
        if x['gold'] and x['pred']:
            tp += 1
        elif x['gold'] and not x['pred']:
            fn += 1
        elif (not x['gold']) and x['pred']:
            fp += 1
        else:
            tn += 1
    return tp, fp, tn, fn


def metrics(tp, fp, tn, fn):
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    acc = (tp + tn) / (tp + fp + tn + fn) if (tp + fp + tn + fn) else 0.0
    spec = tn / (tn + fp) if (tn + fp) else 0.0
    return {'precision': prec, 'recall': rec, 'f1': f1, 'accuracy': acc, 'specificity': spec}


def fmt_block(tp, fp, tn, fn):
    m = metrics(tp, fp, tn, fn)
    lines = [
        f"  Confusion: TP={tp}  FP={fp}  TN={tn}  FN={fn}  (N={tp+fp+tn+fn})",
        f"  Precision={m['precision']:.4f}  Recall={m['recall']:.4f}  "
        f"F1={m['f1']:.4f}  Specificity={m['specificity']:.4f}  Accuracy={m['accuracy']:.4f}",
    ]
    return "\n".join(lines), m


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data', default=os.path.join(HERE, 'results', 'Algorithms', 'benchmark_turns.json'))
    ap.add_argument('--config', default=os.path.join(HERE, 'keyword_regex_config.json'))
    ap.add_argument('--errors-out', default=None)
    ap.add_argument('--report-out', default=None)
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    cfg, compiled, decline_cats = load_config(args.config)
    records = json.load(open(args.data))
    rows = evaluate(records, compiled, decline_cats)

    tp, fp, tn, fn = confusion(rows)
    overall, m = fmt_block(tp, fp, tn, fn)

    out = []
    out.append(f"# Keyword-regex stop/decline benchmark (config v{cfg['meta'].get('version','?')})")
    out.append("")
    out.append("## Methodology")
    out.append(
        "Ground truth is the structural signal `lines_total` from each turn's run log:\n"
        "  - **gold DECLINE (positive)** = `lines_total == 0` — the agent made no code edit\n"
        "    when asked to refactor (this is exactly the step2_raw set, 433 turns).\n"
        "  - **gold EDIT (negative)** = `lines_total > 0` — the agent edited code (2067 turns).\n"
        "Prediction: a turn is predicted DECLINE if any regex in a `decline_categories` "
        "category matches the agent text (Claude thinking + all emitted messages).\n"
        "  - TP = decline turn the regex flagged · FN = decline turn it missed\n"
        "  - FP = edit turn it wrongly flagged · TN = edit turn it correctly ignored\n"
        "Caveat: GPT/codex turns expose only emitted messages (no reasoning text), and 0-line\n"
        "GPT turns are rare (7 total) and often 'I'll refactor now' narration that yields 0 net\n"
        "lines — so GPT per-model recall is noisy/low and not the optimization target.\n"
        "Regenerate: `python3 refusal_analysis/benchmark_keyword_regex.py --report-out <this file>`.")
    out.append("")
    out.append(f"decline_categories = {decline_cats}")
    out.append(f"N turns = {len(rows)}  (gold decline={sum(x['gold'] for x in rows)}, "
               f"gold edit={sum(not x['gold'] for x in rows)})\n")
    out.append("## OVERALL")
    out.append(overall)

    # Per-model breakdown
    out.append("\n## PER-MODEL")
    by_model = defaultdict(list)
    for x in rows:
        by_model[x['r']['model']].append(x)
    for model in sorted(by_model):
        b, _ = fmt_block(*confusion(by_model[model]))
        out.append(f"\n[{model}]  (n={len(by_model[model])})")
        out.append(b)

    # Per-category recall contribution (how often each category fires on golds/edits)
    out.append("\n## PER-CATEGORY FIRING (share of turns where the category matches)")
    for cat in compiled:
        g = sum(1 for x in rows if x['gold'] and cat in x['hits'])
        e = sum(1 for x in rows if (not x['gold']) and cat in x['hits'])
        ng = sum(x['gold'] for x in rows)
        ne = sum(not x['gold'] for x in rows)
        used = " (in decline set)" if cat in decline_cats else " (NOT in decline set)"
        out.append(f"  {cat:18s}{used}: fires on {g}/{ng} declines, {e}/{ne} edits")

    # Top false-positive patterns: which pattern most often fires on edited turns
    out.append("\n## TOP FALSE-POSITIVE PATTERNS (fire on edited turns, by pattern)")
    fp_pat = defaultdict(int)
    for x in rows:
        if (not x['gold']) and x['pred']:
            for cat in decline_cats:
                for p in x['hits'].get(cat, []):
                    fp_pat[(cat, p)] += 1
    for (cat, p), c in sorted(fp_pat.items(), key=lambda kv: -kv[1])[:25]:
        out.append(f"  {c:4d}  [{cat}] {p}")

    report = "\n".join(out)
    if not args.quiet:
        print(report)
    if args.report_out:
        open(args.report_out, 'w').write(report + "\n")

    # Dump misclassifications for inspection
    if args.errors_out:
        def snippet(x):
            t = re.sub(r'\s+', ' ', x['text']).strip()
            return t[:400]
        err = {'false_negatives': [], 'false_positives': []}
        for x in rows:
            rec = {'model': x['r']['model'], 'codebase': x['r']['codebase'],
                   'turn': x['r']['turn'], 'lines_total': x['r']['lines_total'],
                   'hits': x['hits'], 'text': snippet(x)}
            if x['gold'] and not x['pred']:
                err['false_negatives'].append(rec)
            elif (not x['gold']) and x['pred']:
                err['false_positives'].append(rec)
        json.dump(err, open(args.errors_out, 'w'), ensure_ascii=False, indent=1)
        if not args.quiet:
            print(f"\n-> wrote errors to {args.errors_out} "
                  f"(FN={len(err['false_negatives'])}, FP={len(err['false_positives'])})")

    return {'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn, **m}


if __name__ == '__main__':
    main()
