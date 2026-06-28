#!/usr/bin/env python3
"""Build a labeled benchmark dataset for keyword-regex stop/decline detection.

Ground truth comes from the structural signal ``lines_total``:
  - label=1 (DECLINE / stop) : a turn with ``lines_total == 0`` — the agent made
    no code edit when asked to refactor (this is exactly the step2_raw set).
  - label=0 (EDIT / non-stop): a turn with ``lines_total > 0`` — the agent edited
    code, so it did NOT stop/decline.

For every turn we capture the same agent text the rest of the pipeline uses
(Claude thinking blocks + emitted messages; codex/gpt messages only). The regex
benchmark then measures how well keyword matching reproduces the structural
label, giving TP / FP / TN / FN.

Usage:
    python refusal_analysis/build_benchmark_dataset.py [DATASET_DIR]

DATASET_DIR defaults to output/Algorithms. Output ->
refusal_analysis/results/<dataset name>/benchmark_turns.json
"""
import argparse, csv, glob, json, os, re
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Reuse the exact extraction primitives from extract_zero_turns so the agent
# text for every turn is captured identically to step2_raw.
from extract_zero_turns import prompter_prompt, claude_extract, codex_extract  # noqa: E402


def build(dataset_dir):
    records = []
    for lc in sorted(glob.glob(os.path.join(dataset_dir, '*', 'logs', '*-log.csv'))):
        cb = os.path.basename(os.path.dirname(os.path.dirname(lc)))
        m = re.match(r'(\d{8}T\d{6}Z)-(.+)-log\.csv$', os.path.basename(lc))
        if not m:
            continue
        stamp, model = m.group(1), m.group(2)
        is_claude = model.startswith('claude')
        rundirbase = os.path.join(dataset_dir, cb, f'{stamp}-{model}')
        for r in csv.DictReader(open(lc)):
            lt = (r.get('lines_total') or '').strip()
            if lt == '':
                continue
            try:
                lines_total = int(lt)
            except ValueError:
                continue
            run = int(r['run'])
            rundir = os.path.join(rundirbase, f'run_{run:03d}')
            thinking, texts = (claude_extract if is_claude else codex_extract)(rundir)
            records.append({
                'codebase': cb, 'model': model, 'stamp': stamp, 'turn': run,
                'rundir': os.path.relpath(rundir, dataset_dir),
                'lines_total': lines_total,
                'files_changed': r.get('files_changed'),
                'label': 1 if lines_total == 0 else 0,   # 1 = decline/stop, 0 = edit
                'user_prompt': prompter_prompt(rundir),
                'thinking': thinking,
                'messages': texts,
            })
    records.sort(key=lambda x: (x['model'], x['codebase'], x['turn']))
    return records


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('dataset_dir', nargs='?',
                    default=os.path.join(REPO_ROOT, 'output', 'Algorithms'))
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    dataset_dir = os.path.abspath(args.dataset_dir)
    out = os.path.abspath(args.out) if args.out else \
        os.path.join(REPO_ROOT, 'refusal_analysis', 'results',
                     os.path.basename(dataset_dir.rstrip('/')))
    os.makedirs(out, exist_ok=True)

    records = build(dataset_dir)
    path = os.path.join(out, 'benchmark_turns.json')
    with open(path, 'w') as f:
        json.dump(records, f, ensure_ascii=False)

    pos = sum(r['label'] for r in records)
    print(f'dataset: {dataset_dir}')
    print(f'turns: {len(records)} | decline(0-line)={pos} | edit={len(records)-pos}')
    print('decline by model:', dict(Counter(r['model'] for r in records if r['label'] == 1)))
    print('-> wrote', path)


if __name__ == '__main__':
    main()
