"""Run inside the isolated Linux builder, including after a controller restart."""
import argparse
import fcntl
import json
from pathlib import Path
import uuid

import replay_evidence as evidence
import tasks


def build(target, project, out, retry_failed=False):
    platform, _, _ = evidence.checkout_info(project)
    # Claim this prepared Lake cache for a single native toolchain.
    stamp = project / '.lake/build/replay-worker-identity.json'
    stamp.parent.mkdir(parents=True, exist_ok=True)
    with (stamp.parent / 'replay-worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if stamp.exists():
            evidence.require(json.loads(stamp.read_text()) == platform, 'Use a separate native build volume')
        else:
            tmp = stamp.with_suffix('.tmp')
            tmp.write_text(json.dumps(platform))
            tmp.replace(stamp)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt = out / 'receipt.json'
        if receipt.exists() and retry_failed and json.loads(receipt.read_text())['exit_code'] != 0:
            out.rename(out.with_name(out.name + '.failed-' + uuid.uuid4().hex))
        if not receipt.exists():
            if out.exists():
                # A container shutdown can leave a transcript without a finished receipt.
                out.rename(out.with_name(out.name + '.interrupted-' + uuid.uuid4().hex))
            names = set()
            targets = tasks.select(tasks.module_rows(), target, project_modules=names)
            status = tasks.run(targets, project, out, False, True, project_modules=names)
            if status:
                return status
        record = json.loads(receipt.read_text())
        if record['exit_code'] == 0:
            names = set(record['rebuilt_project_modules'])
            ids = set(record['tasks'])
            rows = {r['module']: r for r in tasks.module_rows()
                    if r['module'] in names or r['id'] in ids or target in (r['id'], r['packet'])}
            evidence.verify(out, tasks.select(rows.values(), target), rows, project)
        return record['exit_code']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    probe = commands.add_parser('identity')
    probe.add_argument('checkout', type=Path)
    run = commands.add_parser('build')
    run.add_argument('target')
    run.add_argument('checkout', type=Path)
    run.add_argument('output', type=Path)
    run.add_argument('--retry-failed', action='store_true')
    args = parser.parse_args()
    if args.action == 'identity':
        host, _, _ = evidence.checkout_info(args.checkout.resolve())
        print(json.dumps(host))
        raise SystemExit(0)
    raise SystemExit(build(args.target, args.checkout.resolve(), args.output.resolve(), args.retry_failed))
