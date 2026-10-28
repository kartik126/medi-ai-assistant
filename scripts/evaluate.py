"""Live API checks. Text checks are heuristics, NOT entailment judgments."""
import argparse
from contextlib import ExitStack
import json
import hashlib
import re
import platform
from datetime import datetime, timezone
from importlib.metadata import version
from urllib.parse import urlparse
from pathlib import Path
from time import perf_counter
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
import mimetypes
from backend.config import get_settings
from backend.citations import whitespace


def heuristic_failures(case, actual):
    pages = {(c['filename'], c['page_number']) for c in actual['citations']}
    answer = actual['answer'].lower()
    failures = []
    if actual['status'] != case['expected_status']:
        failures.append('wrong_status')
    if not all(tuple(p) in pages for p in case.get('pages', [])):
        failures.append('missing_expected_page')
    if any(not any(tuple(p) in pages for p in group) for group in case.get('page_groups', [])):
        failures.append('missing_acceptable_source_group')
    if not all(f.lower() in answer for f in case.get('facts', [])):
        failures.append('missing_expected_fact')
    if any(f.lower() in answer for f in case.get('forbidden_facts', [])):
        failures.append('forbidden_extra_fact')
    if any(not re.search(p, actual['answer'], re.I) for p in case.get('required_patterns', [])):
        failures.append('missing_required_pattern')
    if any(re.search(p, actual['answer'], re.I) for p in case.get('forbidden_patterns', [])):
        failures.append('forbidden_answer_pattern')
    quotes = ' '.join(whitespace(c['quote']) for c in actual['citations'])
    if any(not re.search(p, quotes, re.I) for p in case.get('quote_patterns', [])):
        failures.append('missing_direct_quote_support')
    allowed = case.get('allowed_citation_files')
    if allowed is not None and any(c['filename'] not in allowed for c in actual['citations']):
        failures.append('unexpected_citation_file')
    allowed_pages = case.get('allowed_citation_pages')
    if allowed_pages is not None and not pages <= {tuple(p) for p in allowed_pages}:
        failures.append('unexpected_citation_page')
    if len(actual['answer']) > case.get('max_answer_chars', float('inf')):
        failures.append('answer_too_long')
    return failures


def heuristic_check(case, actual):
    return not heuristic_failures(case, actual)


def citation_failures(client, sid, selected, actual, cache):
    """Independently check HTTP scope and quotes against stored page text."""
    failures = []
    if set(actual.get('searched_document_ids', [])) != set(selected):
        failures.append('wrong_searched_document_scope')
    for citation in actual['citations']:
        did, page = citation['document_id'], citation['page_number']
        base = f'/sessions/{sid}/documents/{did}'
        if did not in selected:
            failures.append('citation_outside_selection')
            continue
        if citation['file_url'] != f'{base}/file#page={page}' or citation['page_text_url'] != f'{base}/pages/{page}':
            failures.append('incorrect_source_url')
            continue
        key = (did, page)
        if key not in cache:
            response = client.get(citation['page_text_url'])
            response.raise_for_status()
            cache[key] = response.json()['text']
        if whitespace(citation['quote']) not in whitespace(cache[key]):
            failures.append('quote_absent_from_page')
    return list(dict.fromkeys(failures))


def evaluate(base, fixtures, output, manifest=None, case_ids=None):
    if urlparse(base).hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Live PDF evaluation is restricted to the local API')
    if output.exists():
        raise ValueError('Output already exists; choose a new path to preserve previous responses')
    spec = json.loads((manifest or fixtures / 'expected.json').read_text())
    cases = spec['cases'] if isinstance(spec, dict) else spec
    names = spec.get('documents', []) if isinstance(spec, dict) else ['training-a.pdf', 'training-b.pdf']
    if not names or any(Path(name).name != name for name in names):
        raise ValueError('Manifest documents must be filenames within the corpus directory')
    if len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Case IDs must be unique')
    if case_ids:
        if set(case_ids) - {c['id'] for c in cases}:
            raise ValueError('Unknown case ID')
        cases = [c for c in cases if c['id'] in case_ids]
    for case in cases:
        if set(case.get('selected', names)) - set(names):
            raise ValueError('Case selects a document not listed in the corpus')
        for key in ['required_patterns', 'forbidden_patterns', 'quote_patterns']:
            for pattern in case.get(key, []):
                re.compile(pattern)
    corpus = {name: hashlib.sha256((fixtures / name).read_bytes()).hexdigest() for name in names}
    results, sid = [], None
    report = {'mode': 'live', 'started_at': datetime.now(timezone.utc).isoformat(),
              'suite': spec.get('name', 'legacy') if isinstance(spec, dict) else 'legacy',
              'platform': platform.platform(), 'packages': {p: version(p) for p in ['httpx', 'pymupdf', 'psycopg']},
              'corpus_sha256': corpus, 'cases': results, 'complete': False,
              'note': 'Automatic checks are necessary, not entailment judgments. Human review remains separate.'}
    def save():
        report['complete'] = len(results) == len(cases)
        report['automatic_summary'] = {'passed': sum(r['heuristic_pass'] for r in results),
                                       'failed': sum(not r['heuristic_pass'] for r in results),
                                       'total': len(cases), 'executed': len(results)}
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + '.tmp')
        temporary.write_text(json.dumps(report, indent=2))
        temporary.replace(output)
    try:
        with httpx.Client(base_url=base, timeout=300, trust_env=False) as client:
            health = client.get('/health')
            health.raise_for_status()
            report['health_before'] = health.json()
            config = report['health_before'].get('config', {})
            settings = get_settings()
            with httpx.Client(base_url=settings.ollama_base_url, trust_env=False, timeout=15) as model_client:
                tags = model_client.get('/api/tags')
                tags.raise_for_status()
                report['models'] = [{k: m.get(k) for k in ['name', 'digest', 'size']}
                                    for m in tags.json().get('models', [])
                                    if m.get('name') in [config.get('chat_model'), config.get('embedding_model')]]
            response = client.post("/sessions")
            response.raise_for_status()
            sid = response.json()["session_id"]
            with ExitStack() as stack:
                files = [("files", (name, stack.enter_context((fixtures / name).open("rb")), mimetypes.guess_type(name)[0] or "application/octet-stream")) for name in names]
                ingestion_start = perf_counter()
                response = client.post(f"/sessions/{sid}/documents", files=files)
                response.raise_for_status()
            uploads = response.json()
            report['ingestion_seconds'] = round(perf_counter() - ingestion_start, 3)
            report['uploads'] = uploads
            if any(r["status"] != "ready" for r in uploads):
                raise RuntimeError("Fixture ingestion failed; inspect API/model readiness")
            ids = {r["document"]["filename"]: r["document"]["document_id"] for r in uploads}
            cache = {}
            save()
            for index, case in enumerate(cases):
                start = perf_counter()
                selected = [ids[n] for n in case.get('selected', list(ids))]
                entry = {'id': case['id'], 'question': case['question'], 'expected': case,
                         'selected_filenames': case.get('selected', list(ids)),
                         'human_support_review': 'pending', 'agent_support_review': 'pending'}
                response = None
                try:
                    response = client.post(f'/sessions/{sid}/chat', json={'question': case['question'], 'document_ids': selected})
                    response.raise_for_status()
                    actual = response.json()
                    failures = heuristic_failures(case, actual) + citation_failures(client, sid, selected, actual, cache)
                    entry.update(actual=actual, failures=failures, heuristic_pass=not failures)
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    entry.update(actual=None, heuristic_pass=False, failures=['request_or_response_error'],
                                 error_type=type(exc).__name__, http_status=response.status_code if response is not None else None)
                entry['seconds'] = round(perf_counter()-start, 3)
                results.append(entry)
                save()
                print(f'[{index+1}/{len(cases)}] {case["id"]}: {"PASS" if entry["heuristic_pass"] else "FAIL"} ({entry["seconds"]}s)', flush=True)
    finally:
        if sid:
            try:
                with httpx.Client(base_url=base, timeout=15, trust_env=False) as client:
                    cleanup = client.delete(f"/sessions/{sid}")
                    report['test_session_deleted'] = cleanup.status_code in (204, 404)
            except httpx.HTTPError:
                report['test_session_deleted'] = False
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        save()
    return bool(results) and all(r["heuristic_pass"] and r["human_support_review"] == "pass" for r in results)


def apply_reviews(results_path, reviews_path):
    """Annotate an existing run, never regenerate responses after review."""
    report = json.loads(results_path.read_text())
    judgments = json.loads(reviews_path.read_text())
    if report.get("mode") != "live" or not report.get("complete") or not report.get("cases"):
        raise ValueError("Only a complete recorded live run can be reviewed")
    ids = {case["id"] for case in report["cases"]}
    if not isinstance(judgments, dict) or set(judgments) != ids or any(value not in ("pass", "fail") for value in judgments.values()):
        raise ValueError("Review JSON must map every recorded case ID to pass or fail")
    for case in report["cases"]:
        case["human_support_review"] = judgments[case["id"]]
    results_path.write_text(json.dumps(report, indent=2))
    return all(case["heuristic_pass"] and case["human_support_review"] == "pass" for case in report["cases"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--review-results", type=Path, help="Annotate the saved run without making model calls")
    parser.add_argument("--fixtures", type=Path, default=Path("data/fixtures"))
    parser.add_argument("--output", type=Path, default=Path("docs/evaluation.json"))
    parser.add_argument('--manifest', type=Path, help='JSON suite with documents and cases; --fixtures supplies its corpus directory')
    parser.add_argument('--case-id', action='append', help='Run only these case IDs; use a new output path')
    parser.add_argument("--reviews", type=Path, help="JSON mapping each saved case ID to pass/fail after manual review")
    args = parser.parse_args()
    if args.review_results and not args.reviews:
        parser.error("--review-results requires --reviews")
    if args.live and args.reviews:
        parser.error("Apply reviews to recorded results, not to a fresh run")
    try:
        passed = apply_reviews(args.review_results, args.reviews) if args.review_results else evaluate(get_settings().api_base_url, args.fixtures, args.output, args.manifest, args.case_id)
        print("Validation passed." if passed else "Validation failed or manual support review remains pending.")
        sys.exit(0 if passed else 1)
    except (httpx.HTTPError, RuntimeError, OSError, ValueError) as exc:
        print(f"Validation could not finish: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
