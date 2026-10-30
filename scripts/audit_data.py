#!/usr/bin/env python3
"""Audit private handouts and prepare a training-only, unlabeled annotation sample.

Outputs contain private data or aggregate reports and MUST stay outside Git/CI.
No administrator reply or derived outcome is exposed to an annotator or predictor.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.cli import to_inference


def records(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8-sig') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def fingerprint(row):
    text = ' '.join(m.get('text', '') for m in row.get('messages', []) if m.get('role') == 'player')
    text = ' '.join(text.casefold().split())
    return hashlib.sha256(text.encode()).hexdigest() if text else None


def audit(train_path, valid_path, sample_size=120, seed=20261031):
    valid = list(records(valid_path))
    valid_users = {r['reporter_hash'] for r in valid if r.get('reporter_hash')}
    valid_texts = {fingerprint(r) for r in valid} - {None}
    train_users, train_texts = set(), set()
    train_counts, train_langs, labels = Counter(), Counter(), Counter()
    # Reservoirs per heuristic language/kind group. No validation rows enter samples.
    rng = random.Random(seed)
    reservoirs, seen = defaultdict(list), Counter()
    for row in records(train_path):
        train_counts[row.get('kind', 'unknown')] += 1
        train_langs[row.get('lang', 'und')] += 1
        for name in ('category', 'priority'):
            labels[name] += int(bool(row.get(name)))
        user, text = row.get('reporter_hash'), fingerprint(row)
        if user: train_users.add(user)
        if text: train_texts.add(text)
        if (user and user in valid_users) or (text and text in valid_texts):
            continue
        key = (row.get('kind', 'report'), row.get('lang', 'und'))
        seen[key] += 1
        bucket = reservoirs[key]
        if len(bucket) < sample_size:
            bucket.append(row)
        else:
            pick = rng.randrange(seen[key])
            if pick < sample_size: bucket[pick] = row
    # Round-robin preserves minority strata without claiming representative prevalence.
    sample, keys = [], sorted(reservoirs)
    for bucket in reservoirs.values(): rng.shuffle(bucket)
    while len(sample) < sample_size and keys:
        for key in keys[:]:
            if len(sample) >= sample_size: break
            if not reservoirs[key]: keys.remove(key); continue
            row = reservoirs[key].pop()
            request = to_inference(row).model_dump(mode='json', exclude_none=True)
            sample.append({'annotation_id': f'manual-{len(sample)+1:04d}', 'source_split': 'train',
                           'stratum_hint_not_gold': {'kind': key[0], 'language': key[1]},
                           'input': request, 'labels': {'lang': None, 'category': None, 'priority': None,
                           'mandatory_human': None, 'mandatory_reasons': [], 'relevant_rule_uids': [],
                           'duplicate_group': None}, 'annotator': None, 'adjudicator': None,
                           'notes': '', 'status': 'unlabeled'})
    summary = {'schema_version': 1, 'seed': seed,
               'train': {'count': sum(train_counts.values()), 'kinds': dict(train_counts),
                         'heuristic_languages': dict(train_langs), 'nonempty_labels': dict(labels)},
               'valid': {'count': len(valid), 'kinds': dict(Counter(r.get('kind') for r in valid)),
                         'nonempty_labels': {k: sum(bool(r.get(k)) for r in valid) for k in ('category','priority')}},
               'overlap': {'reporters': len(valid_users & train_users),
                           'unique_nonempty_normalized_player_texts': len(valid_texts & train_texts),
                           'valid_rows_with_train_reporter': sum(r.get('reporter_hash') in train_users for r in valid),
                           'valid_rows_with_train_text': sum(fingerprint(r) in train_texts for r in valid)},
               'annotation_sample': {'count': len(sample), 'split': 'train only; excludes validation users/texts',
                                     'labels': 'none; manual annotation required',
                                     'sampling': 'seeded stratified reservoirs, minority-balanced; not prevalence estimate'},
               'metrics': {'category_accuracy': None, 'priority_macro_f1': None},
               'limitations': ['Organizer lang is heuristic, not ground truth.',
                               'Outcomes and administrator replies are excluded from annotation inputs.',
                               'Do not train on validation; split labeled training by user and duplicate-text groups.']}
    return summary, sample


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--train', required=True); p.add_argument('--valid', required=True)
    p.add_argument('--output', required=True); p.add_argument('--annotation-output', required=True)
    p.add_argument('--sample-size', type=int, default=120); p.add_argument('--seed', type=int, default=20261031)
    a=p.parse_args()
    if not 1 <= a.sample_size <= 5000: p.error('sample-size must be 1..5000')
    destinations=[Path(a.output).resolve(),Path(a.annotation_output).resolve()]
    if len(set(destinations)) != 2 or any(x in {Path(a.train).resolve(),Path(a.valid).resolve()} for x in destinations):
        p.error('outputs must be distinct from inputs and each other')
    summary,sample=audit(a.train,a.valid,a.sample_size,a.seed)
    from app.private_files import restrict_private_file, restrict_private_directory
    import os
    import tempfile
    for target,content in zip(destinations,[json.dumps(summary,ensure_ascii=False,indent=2)+'\n',
                                           ''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in sample)]):
        target.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, delete=False) as temporary:
            temp_path=Path(temporary.name)
            try:
                restrict_private_file(temp_path)
                temporary.write(content)
                temporary.flush(); os.fsync(temporary.fileno())
            except BaseException:
                temporary.close(); temp_path.unlink(missing_ok=True); raise
        os.replace(temp_path,target)
    print(json.dumps({'train_count': summary['train']['count'], 'valid_count': summary['valid']['count'],
                      'annotation_rows': len(sample), 'gold_labels': 0}))


if __name__ == '__main__': main()
