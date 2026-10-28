"""Render a live-run audit without turning heuristic passes into clinical claims."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


def response_hash(actual):
    return hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()


def summarize(path, reviews_path=None):
    report = json.loads(path.read_text())
    reviews = json.loads(reviews_path.read_text()).get('cases', {}) if reviews_path else {}
    cases = report['cases']
    valid = {c['id']: reviews[c['id']] for c in cases if c['id'] in reviews
             and reviews[c['id']].get('actual_sha256') == response_hash(c.get('actual'))}
    passed = sum(c['heuristic_pass'] for c in cases)
    times = sorted(c['seconds'] for c in cases)
    def percentile(p):
        if not times:
            return 0
        position = (len(times)-1)*p
        lower = math.floor(position)
        upper = math.ceil(position)
        return round(times[lower] + (times[upper]-times[lower])*(position-lower), 3)
    counts = Counter(c['expected'].get('category', 'legacy') for c in cases)
    lines = ['# Medical PDF edge-case audit', '',
             f"Run: `{path.name}`. Complete: **{report.get('complete', False)}**.", '',
             f'- Automatic checks: **{passed}/{len(cases)} passed**; {len(cases)-passed} failed.',
             f'- Response-bound coding-agent reviews: **{len(valid)}/{len(cases)}** recorded.',
             f"- Human review: **{sum(c.get('human_support_review') == 'pass' for c in cases)}/{len(cases)} approved**; coding-agent review is separate.",
             f'- Observed end-to-end case time: median **{percentile(.5)} s**, p95 **{percentile(.95)} s**, max **{max(times) if times else 0} s**.',
             f"- Isolated test session deleted: **{report.get('test_session_deleted', False)}**.", '',
             'These are development regressions and new challenges, not an untouched held-out or clinical benchmark. '
             'Pattern checks can reject a harmless paraphrase or miss an unsupported extra claim. '
             'A coding-agent review is not clinician validation. A failed absent-information status may still contain a correct explanation; severity notes distinguish this from fabricated patient facts.', '',
             '## High-priority findings', '']
    high = [(c, valid[c['id']]) for c in cases if c['id'] in valid and valid[c['id']]['severity'] == 'high']
    for case, review in high:
        lines.append(f"- **{case['id']}**: {review['note']}")
    if not high:
        lines.append('No reviewed high-priority findings recorded yet; this is not a claim that none exist.')
    lines += ['', '## Full case matrix', '',
              '| Case | Automatic | Agent review | Issue / severity | Seconds |',
              '|---|---|---|---|---:|']
    for case in cases:
        review = valid.get(case['id'], {})
        issue = review.get('issue', ', '.join(case.get('failures', [])) or 'none')
        lines.append(f"| {case['id']} | {'PASS' if case['heuristic_pass'] else 'FAIL'} | {review.get('verdict', 'pending')} | {issue} / {review.get('severity', 'unreviewed')} | {case['seconds']} |")
    lines += ['', '## Review notes', '']
    for case in cases:
        if case['id'] in valid and valid[case['id']]['verdict'] == 'fail':
            review = valid[case['id']]
            lines += [f"### {case['id']}", '', review['note'], '',
                      f"Automatic failure labels: `{', '.join(case.get('failures', []))}`.", '']
    lines += ['## Reproduce and extend', '',
              'The manifest is `evaluation/edge_cases.json`; corpus files remain in ignored `data/edge-corpus/`. '
              'The JSON run preserves every actual response, expected checks, selected filenames, model digests, document hashes and timing. '
              'The separate review JSON binds judgments to SHA-256 hashes of those exact responses. Earlier responses are never overwritten by a retry.', '',
              '```bash',
              'python scripts/evaluate.py --live --fixtures data/edge-corpus --manifest evaluation/edge_cases.json --output docs/evaluations/new-run.json',
              'python scripts/evaluate.py --live --fixtures data/edge-corpus --manifest evaluation/edge_cases.json --case-id cdc-no-personal-a1c --output docs/evaluations/new-single-case.json',
              '```', '',
              'The CLI remains nonzero until its separate human-review requirement is met. Automatic failures are retained. '
              'Use a new output filename for every run. Only the runner-created session is deleted after evaluation.', '',
              '## Coverage still needed', '',
              '- Public or fully de-identified completed forms, paired with blank versions.',
              '- Lab reports with values, units, reference ranges, dates and explicit missing fields.',
              '- Multi-page tables, rotated/poor text exports, mixed text/image and scanned PDFs.',
              '- Different named documents sharing the same topic, revised versions and conflicting statements.',
              '- Independent held-out questions and human/clinical support review before any clinical use.', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('results', type=Path)
    parser.add_argument('--agent-reviews', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(summarize(args.results, args.agent_reviews))
