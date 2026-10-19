"""Compare the public dsh-ltm CLI with Sumika's synthetic retrieval baseline.

Creates a fresh run directory; never opens user databases or installs packages.
CLI startup is included in latency. This is retrieval research, not a provider.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.evaluate_memory_quality import FACTS, CASES, evaluate
from extensions.memory.embedded_memory import EmbeddedMemory
from extensions.memory.semantic_memory import SemanticMemory
from extensions.memory.embedding_runtime import installed_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', required=True, type=Path)
    parser.add_argument('--runs', type=Path, default=Path('.sumika-next/community-memory'))
    parser.add_argument('--semantic', action='store_true')
    args = parser.parse_args()
    cli = args.cli.resolve(strict=True)
    package = cli.parent.parent / 'package.json'
    metadata = json.loads(package.read_text(encoding='utf8'))
    run = args.runs.resolve() / uuid.uuid4().hex
    run.mkdir(parents=True, exist_ok=False)
    calls = []

    def invoke(db, *command, allow_failure=False):
        started = time.perf_counter()
        result = subprocess.run(
            ['node', str(cli), '--db', str(db), '--json', *command],
            capture_output=True, text=True, encoding='utf8', timeout=30,
        )
        receipt = dict(command=list(command), database=db.name,
                       returncode=result.returncode, stdout=result.stdout,
                       stderr=result.stderr,
                       milliseconds=round((time.perf_counter()-started)*1000, 2))
        calls.append(receipt)
        (run/'calls.json').write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding='utf8')
        if result.returncode and not allow_failure:
            raise RuntimeError(f'CLI failed; see {run / "calls.json"}')
        return json.loads(result.stdout), receipt['milliseconds']

    db = run/'scope-role.db'
    seed = run/'seed.json'
    seed.write_text(json.dumps(dict(format='dsh-ltm-export/2', records=[
        dict(id=i+1, text=text, tags='', scope='role:test', pinned=False,
             createdAt=0, updatedAt=0, lastConfirmedAt=0, revision=1)
        for i, text in enumerate(FACTS)
    ]), ensure_ascii=False), encoding='utf8')
    invoke(db, 'import', str(seed))
    cases = []
    for query, expected in CASES:
        response, ms = invoke(db, 'search', query, '--limit', '1')
        rows = response.get('results', response.get('records'))
        if not isinstance(rows, list):
            raise RuntimeError('Unexpected CLI search response; inspect raw receipt')
        texts = [row['text'] for row in rows]
        passed = not rows if expected is None else bool(texts and texts[0] == FACTS[expected])
        cases.append(dict(query=query, expected=expected, retrieved=texts,
                          passed=passed, milliseconds=ms))
    # Destructive checks use only the synthetic DB created in this run.
    corrected = '用户现在住在杭州，不再居住成都。'
    edited, _ = invoke(db, 'edit', '3', '--text', corrected, '--expected-revision', '1')
    stale, _ = invoke(db, 'edit', '3', '--text', '旧弹窗不应覆盖',
                      '--expected-revision', '1', allow_failure=True)
    stale_rejected = calls[-1]['returncode'] != 0
    shown, _ = invoke(db, 'show', '3')
    exported = run/'before-forget.json'
    invoke(db, 'export', '--out', str(exported))
    invoke(db, 'forget', '3', '--expected-revision', str(edited['record']['revision']))
    after_forget, _ = invoke(db, 'list', '--limit', '100')
    invoke(db, 'import', str(exported))
    after_restore, _ = invoke(db, 'list', '--limit', '100')
    governance = dict(
        correction_persisted=shown['record']['text'] == corrected,
        stale_revision_rejected=bool(stale.get('error')) and stale_rejected,
        forgotten_absent_from_list=not any(r['text'] == corrected for r in after_forget['records']),
        pre_forget_export_reintroduces_fact=any(r['text'] == corrected for r in after_restore['records']),
        boundary='Restore observation is not a plugin bug claim: Sumika requires durable purge '
                 'guards beyond ordinary backup restoration. Public search has no scope argument.',
    )
    report = dict(
        dataset='sumika-chinese-regression-v1',
        boundary='14 synthetic retrieval cases; no answer model; no product/default changes; '
                 'one database for one scope, NOT proof of plugin-native scope isolation; '
                 'CLI subprocess latency is not comparable with in-process query latency',
        package=dict(name=metadata['name'], version=metadata['version'],
                     cli=str(cli), cli_sha256=hashlib.sha256(cli.read_bytes()).hexdigest()),
        community=dict(cases=cases, passed=sum(row['passed'] for row in cases), total=len(cases)),
        community_governance=governance,
        keyword=evaluate(EmbeddedMemory),
    )
    if args.semantic:
        python, cache = installed_runtime()
        report['semantic'] = evaluate(lambda path: SemanticMemory(
            path, cache_dir=cache, embedding_python=python))
    target = run/'report.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(dict(report=str(target), scores={
        name: f'{report[name]["passed"]}/{report[name]["total"]}'
        for name in ('community', 'keyword', 'semantic') if name in report
    }), ensure_ascii=False))


if __name__ == '__main__':
    main()
