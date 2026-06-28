#!/usr/bin/env python3
"""Per-pattern ablation / matching-frequency log for the keyword-regex dictionary.

For every regex in ``keyword_regex_config.json`` this reports, against the
labeled benchmark (``results/<ds>/benchmark_turns.json``):
  - turns matched among the gold DECLINE set (0-line turns)  -> TP
  - turns matched among the gold EDIT set (lines_total>0)     -> FP
  - turns matched total, and precision = TP/(TP+FP)
  - raw occurrence counts (total regex matches across the corpus, decline/edit)
Plus a category-subset confusion comparison (which decline_categories combo
gives the best F1). Writes a markdown log and also prints to stdout.

Usage:
    python refusal_analysis/ablate_patterns.py [--config ...] [--data ...]
        [--report-out PATH] [--quiet]
Default report -> results/<ds>/step5_keyword_regex_frequency.md
"""
import argparse, json, os, re
from itertools import combinations

HERE = os.path.dirname(os.path.abspath(__file__))
FLAG_MAP = {'IGNORECASE': re.I, 'MULTILINE': re.M, 'DOTALL': re.S, 'VERBOSE': re.X}


def agent_text(r):
    return "\n".join(r.get('thinking', []) + r.get('messages', []))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', default=os.path.join(HERE, 'keyword_regex_config.json'))
    ap.add_argument('--data', default=os.path.join(HERE, 'results', 'Algorithms', 'benchmark_turns.json'))
    ap.add_argument('--report-out', default=os.path.join(HERE, 'results', 'Algorithms',
                                                         'step5_keyword_regex_frequency.md'))
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    cfg = json.load(open(args.config))
    flags = 0
    for f in cfg['options'].get('flags', ['IGNORECASE']):
        flags |= FLAG_MAP[f]
    records = json.load(open(args.data))
    texts = [(bool(r['label']), agent_text(r)) for r in records]
    ng = sum(g for g, _ in texts)
    ne = sum(not g for g, _ in texts)
    decline_cats = cfg['options'].get('decline_categories', list(cfg['categories']))

    out = []
    out.append(f"# Keyword-regex matching-frequency log (config v{cfg['meta'].get('version','?')})")
    out.append("")
    out.append(f"Source data: `{os.path.relpath(args.data, os.path.dirname(HERE))}` — "
               f"**{ng} gold-decline turns** (0-line) and **{ne} gold-edit turns** "
               f"(lines_total>0), {ng+ne} total.")
    out.append("")
    out.append("Per pattern: `declines` = decline turns matched (= TP), `edits` = edit "
               "turns matched (= FP), `turns` = total turns matched, `prec` = "
               "declines/(declines+edits). `occ_*` = raw occurrence counts (every match "
               "across the corpus, not just turns-with-a-match). Counts overlap across "
               "patterns (a turn/sentence can match several).")
    out.append(f"\n`decline_categories` (in detection set) = {decline_cats}\n")

    for cat, pats in cfg['categories'].items():
        used = "in decline set" if cat in decline_cats else "NOT in decline set"
        out.append(f"\n## {cat}  ({used})\n")
        out.append("| declines | edits | turns | prec | occ_decline | occ_edit | pattern |")
        out.append("|---:|---:|---:|---:|---:|---:|---|")
        rows = []
        for p in pats:
            rx = re.compile(p, flags)
            tp = fp = occ_d = occ_e = 0
            for g, t in texts:
                n = len(rx.findall(t))
                if g:
                    occ_d += n
                    tp += 1 if n else 0
                else:
                    occ_e += n
                    fp += 1 if n else 0
            prec = tp / (tp + fp) if (tp + fp) else 0.0
            rows.append((tp, fp, prec, occ_d, occ_e, p))
        for tp, fp, prec, occ_d, occ_e, p in sorted(rows, key=lambda x: -x[0]):
            esc = p.replace('|', '\\|')
            out.append(f"| {tp} | {fp} | {tp+fp} | {prec:.2f} | {occ_d} | {occ_e} | `{esc}` |")

    # Category-subset confusion
    comp = {c: [re.compile(p, flags) for p in ps] for c, ps in cfg['categories'].items()}
    def fires(cat, t):
        return any(rx.search(t) for rx in comp[cat])
    out.append("\n## decline_category subset comparison\n")
    out.append("| categories | TP | FP | precision | recall | F1 |")
    out.append("|---|---:|---:|---:|---:|---:|")
    cats = list(cfg['categories'])
    subsets = []
    for k in range(1, len(cats) + 1):
        subsets.extend(combinations(cats, k))
    for sub in subsets:
        tp = fp = 0
        for g, t in texts:
            pred = any(fires(c, t) for c in sub)
            if g and pred: tp += 1
            elif (not g) and pred: fp += 1
        fn = ng - tp
        prec = tp / (tp + fp) if tp + fp else 0
        rec = tp / (tp + fn) if tp + fn else 0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
        out.append(f"| {'+'.join(sub)} | {tp} | {fp} | {prec:.3f} | {rec:.3f} | {f1:.3f} |")

    report = "\n".join(out) + "\n"
    if not args.quiet:
        print(report)
    if args.report_out:
        open(args.report_out, 'w').write(report)
        print(f"-> wrote {args.report_out}")


if __name__ == '__main__':
    main()
