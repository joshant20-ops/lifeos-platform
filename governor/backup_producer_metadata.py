"""Producer receipts and bounded, read-only discovery for existing retention.

Receipts attest execution timing, never restore quality or deletion authority.
Legacy directory names and mtimes are deliberately not interpreted as dates.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import stat

RECEIPT = '.lifeos-producer.json'
PRODUCERS = {
    'lifeos-sync-pinned-compose.sh': ('pinned-compose-', 'compose-projects'),
    'lifeos-ha-dashboard-audit-simplify.sh': ('ha-dashboard-simplify-', 'homeassistant'),
    'lifeos-adapt-ha-lifeos-dashboard.sh': ('ha-lifeos-dashboard-', 'homeassistant'),
    'lifeos-adapt-ha-tower-control.sh': ('ha-tower-control-', 'homeassistant'),
    'lifeos-deploy-ha-control-bridge-impl.sh': ('ha-control-bridge-', 'ha-control-bridge'),
}


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def traversal_error(error):
    raise error


def directory(path):
    p = Path(path).absolute()
    if p.is_symlink() or p.resolve() != p or not p.is_dir():
        raise ValueError('noncanonical_generation_directory')
    return p


def read_receipt(p):
    f = p / RECEIPT
    s = f.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_size > 16384:
        raise ValueError('unsafe_receipt')
    value = json.loads(f.read_text())
    if not isinstance(value, dict): raise ValueError('invalid_receipt')
    return value


def begin(path, source):
    p = directory(path)
    src = Path(source).resolve(strict=True)
    if src.name not in PRODUCERS or not p.name.startswith(PRODUCERS[src.name][0]):
        raise ValueError('unknown_producer_or_generation')
    record = dict(schema_version=1, producer=src.name,
                  producer_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
                  generation_id=p.name, service=PRODUCERS[src.name][1],
                  created_at=utc(), completed_at=None, state='active',
                  verification='unverified', references_verified=False,
                  recovery_dependencies=['rollback_dependency_review_required'])
    # Exclusive creation: repeated/colliding runs must not overwrite evidence.
    fd = os.open(p / RECEIPT, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(record, f, sort_keys=True); f.flush(); os.fsync(f.fileno())


def finish(path, status):
    p = directory(path)
    record = read_receipt(p)
    if record['state'] != 'active':
        raise ValueError('already_finalized')
    record.update(completed_at=utc(), state='completed' if status == 0 else 'failed', exit_status=status)
    temp = p / (RECEIPT + '.pending')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(record, f, sort_keys=True); f.flush(); os.fsync(f.fileno())
    os.replace(temp, p / RECEIPT)
    fd = os.open(p, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def retention_generation(receipt, name, files, measured):
    """Normalize receipts into PR2149's schema, preserving unresolved holds.

    The installed trusted evidence adapter must later attest source identity,
    timestamp provenance, reference closure and retained recovery coverage.
    A self-described receipt can never promote itself to deletion authority.
    """
    return dict(service=receipt.get('service', 'unknown'), generation_id=name,
        root_id='automation_backups', category='automation_backup', relative_path=name,
        created_at=receipt.get('created_at'), completed_at=receipt.get('completed_at'),
        timestamp_verified=False, producer_evidence_id=receipt.get('producer_sha256'),
        state=receipt.get('state'), active=receipt.get('state') != 'completed',
        references_verified=False, dependencies=['rollback_dependency_review_required'],
        open_references=None, holds=['producer_receipt_attestation_required'],
        verification='unverified', live_data=False, database_volume=False,
        offhost_required=True, record_class='privileged_transaction', files=files,
        logical_bytes=sum(f['identity']['st_size'] for f in files) if measured else None,
        allocated_bytes=sum(f['allocated_bytes'] for f in files) if measured else None)


def discover(root, limit=100000, private_records=None, normalized=None):
    """No file writes, contents, Docker or service calls. Receiptless = HOLD.

    Reports allocated bytes for *all* regular files only when traversal completed.
    Per-generation limits prevent unexpectedly large trees exhausting the host.
    No recovered timestamps/quality/references are manufactured for old backups.
    """
    root = directory(root)
    counts = collections.Counter(); families = collections.Counter()
    logical = allocated = 0
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            if index >= limit:
                counts['entry_limit_reached'] += 1; break
            counts['entries'] += 1
            if not entry.is_dir(follow_symlinks=False):
                counts['non_directory_hold'] += 1; continue
            p = Path(entry.path)
            family = next((name for name, (prefix, _) in PRODUCERS.items() if p.name.startswith(prefix)), 'unknown_producer')
            families[family] += 1
            receipt = None
            try:
                receipt = read_receipt(p)
                if receipt.get('producer') != family or receipt.get('generation_id') != p.name:
                    raise ValueError('receipt_identity_mismatch')
                counts['receipt_' + ('completed' if receipt.get('state') == 'completed' else 'nonterminal')] += 1
            except FileNotFoundError:
                counts['missing_completion_evidence'] += 1
            except (OSError, ValueError, KeyError):
                counts['invalid_receipt_hold'] += 1; receipt = None
            # Bound traversal; don't follow links, mounts, special or shared files.
            size = blocks = number = 0
            files_index = []
            try:
                device = p.stat().st_dev
                if device != root.stat().st_dev: raise ValueError('mounted_generation_hold')
                for parent, dirs, files in os.walk(p, followlinks=False, onerror=traversal_error):
                    for name in dirs + files:
                        number += 1
                        if number > 2048: raise ValueError('generation_file_limit')
                        s = (Path(parent) / name).lstat()
                        if s.st_dev != device or stat.S_ISLNK(s.st_mode): raise ValueError('unsafe_tree')
                        if stat.S_ISREG(s.st_mode) and s.st_nlink == 1:
                            size += s.st_size; blocks += s.st_blocks * 512
                            if receipt is not None:
                                files_index.append(dict(relative_path=str((Path(parent)/name).relative_to(root)),
                                    allocated_bytes=s.st_blocks * 512,
                                    identity={key: getattr(s, key) for key in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')}))
                        elif not stat.S_ISDIR(s.st_mode): raise ValueError('unsafe_tree')
                logical += size; allocated += blocks
                counts['size_verified_generations'] += 1
                measured = True
            except (OSError, ValueError):
                counts['unmeasured_hold'] += 1; measured = False
            if private_records is not None:
                private_records.append(dict(generation_id=p.name, producer_family=family,
                    logical_bytes=size if measured else None, allocated_file_bytes=blocks if measured else None,
                    receipt=receipt, deletion_disposition='HOLD',
                    reason='active_recovery_and_timestamp_witness_review_required'))
            if normalized is not None and receipt is not None and len(normalized) < 10000:
                normalized.append(retention_generation(receipt, p.name, files_index, measured))
    return dict(schema_version=1, observed_at=utc(), counts=dict(counts), producer_families=dict(families),
                measured_logical_bytes=logical, measured_allocated_file_bytes=allocated,
                eligible_generations=None, eligible_bytes=None, verified_eligible_generations=0,
                verified_eligible_bytes=0, decision='HOLD_RECOVERY_AND_LEGACY_EVIDENCE_REQUIRED',
                limitations=['No recovery/reference attestation; no deletion manifest authorised.',
                             'Directory names and mtimes are not completion evidence.',
                             'Allocated file bytes exclude directory overhead; hardlinks held.'])


def main():
    ap = argparse.ArgumentParser(__doc__)
    sub = ap.add_subparsers(dest='operation', required=True)
    for name in ('begin', 'finish', 'discover'):
        p = sub.add_parser(name); p.add_argument('path')
        if name == 'begin': p.add_argument('source')
        if name == 'finish': p.add_argument('status', type=int)
        if name == 'discover': p.add_argument('--private-report', type=Path)
    args = ap.parse_args()
    if args.operation == 'begin': begin(args.path, args.source)
    elif args.operation == 'finish': finish(args.path, args.status)
    else:
        records = [] if args.private_report else None
        normalized = [] if args.private_report else None
        summary = discover(args.path, private_records=records, normalized=normalized)
        if args.private_report:
            fd = os.open(args.private_report, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as f:
                json.dump(dict(summary=summary, generations=records, retention_inventory=dict(
                    schema_version=1, complete=False, observed_at=summary['observed_at'],
                    generations=normalized, recovery_points=[])), f, sort_keys=True)
                f.flush(); os.fsync(f.fileno())
        print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__': main()
