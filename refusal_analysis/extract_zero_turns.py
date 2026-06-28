#!/usr/bin/env python3
"""Extract all 0-line-edit turns from an experiment output tree and dump JSON.

A 0-line turn = a row in a model's ``*-log.csv`` with ``lines_total == 0``, i.e.
the coding agent made no code change that turn when the prompter asked it to
"refactor the codebase". These are the turns where the agent declined / pushed
back (the sycophancy signal of interest).

Usage:
    python refusal_analysis/extract_zero_turns.py [DATASET_DIR]

DATASET_DIR defaults to ``output/Algorithms`` (relative to repo root). Output is
written to ``refusal_analysis/results/<dataset name>/zero_turns.json`` (the data
lives next to this mechanism, not under ``output/``). Works on any dataset with
the same layout (e.g. ``output/RealWorld``).
"""
import argparse, csv, glob, json, os, re
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_jsonl(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def prompter_prompt(rundir):
    """User (prompter) message text for the turn."""
    txt = []
    for o in load_jsonl(os.path.join(rundir, 'prompter.jsonl')):
        if o.get('event') == 'prompt_out' and o.get('text'):
            txt.append(o['text'].strip())
    return "\n".join(txt)


def claude_extract(rundir):
    """Return (thinking_blocks, message_texts) for a claude run.
    Thinking blocks are captured when the API preserved them; redacted
    (signature-only) blocks come through blank and are dropped."""
    thinking, texts = [], []
    for o in load_jsonl(os.path.join(rundir, 'claude.jsonl')):
        if not isinstance(o, dict) or o.get('type') != 'assistant':
            continue
        for b in o.get('message', {}).get('content', []):
            bt = b.get('type')
            if bt == 'thinking' and b.get('thinking'):
                thinking.append(b['thinking'].strip())
            elif bt == 'text' and b.get('text'):
                texts.append(b['text'].strip())
    return thinking, texts


def codex_extract(rundir):
    """Return (thinking_blocks, message_texts) for a codex/gpt run.
    Codex CLI does not emit reasoning text (only reasoning token counts), so
    thinking is always empty; agent_message items are the agent's messages."""
    texts = []
    for o in load_jsonl(os.path.join(rundir, 'codex.jsonl')):
        if not isinstance(o, dict):
            continue
        if o.get('type') == 'item.completed':
            it = o.get('item', {})
            if it.get('type') == 'agent_message' and it.get('text'):
                texts.append(it['text'].strip())
    return [], texts


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
            if (r.get('lines_total') or '').strip() != '0':
                continue
            run = int(r['run'])
            rundir = os.path.join(rundirbase, f'run_{run:03d}')
            thinking, texts = (claude_extract if is_claude else codex_extract)(rundir)
            records.append({
                'codebase': cb, 'model': model, 'stamp': stamp, 'turn': run,
                'rundir': os.path.relpath(rundir, dataset_dir),
                'files_changed': r.get('files_changed'),
                'duration_s': r.get('duration_s'),
                'exit_code': r.get('exit_code'),
                'timed_out': r.get('timed_out'),
                'user_prompt': prompter_prompt(rundir),
                'thinking': thinking,
                'messages': texts,
            })
    records.sort(key=lambda x: (x['model'], x['codebase'], x['turn']))
    return records


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('dataset_dir', nargs='?', default=os.path.join(REPO_ROOT, 'output', 'Algorithms'),
                    help='Experiment output dir to read from (default: output/Algorithms)')
    ap.add_argument('--out', default=None,
                    help='Output dir (default: refusal_analysis/results/<dataset name>)')
    args = ap.parse_args()
    dataset_dir = os.path.abspath(args.dataset_dir)
    out = os.path.abspath(args.out) if args.out else \
        os.path.join(REPO_ROOT, 'refusal_analysis', 'results', os.path.basename(dataset_dir.rstrip('/')))

    records = build(dataset_dir)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'zero_turns.json'), 'w') as f:
        json.dump(records, f, indent=1, ensure_ascii=False)

    print(f'dataset: {dataset_dir}')
    print('records:', len(records))
    print('by model:', dict(Counter(r['model'] for r in records)))
    print('-> wrote', os.path.join(out, 'zero_turns.json'))


if __name__ == '__main__':
    main()
