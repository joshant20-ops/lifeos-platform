"""Fixed local rehearsal of the owner-selected Paperless recovery checkpoint."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import tarfile
import tempfile
import time
import uuid

from governor.mqtt_live_rotation import connection_inputs, health_checks
from governor.storage_health_gate import HealthGate

HDD = Path("/mnt/docker-data")
CHECKPOINT = HDD / "paperless-recovery/20261116-164147-XuCaRz"
REPORT_DIR = Path("/var/lib/lifeos/paperless-recovery-rehearsal")
ARCHIVES = ("paperless.dump", "media.tar", "configuration.tar", "historical-email.tar", "paperless-iq.tar")
LIMIT = 3 * 1024**3
RESERVE = 8 * 1024**3
CHUNK = 1024**2
DOCKER = "/usr/bin/docker"
TIER0_CHECKS = frozenset(("adguard_running", "household_dns_udp", "household_dns_tcp",
    "household_dns_public", "direct_internet_tls", "github_https", "storage_reserve"))


class RehearsalError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise RehearsalError(code)


def failure_code(exc):
    code = str(exc)
    if isinstance(exc, RehearsalError) and re.fullmatch(r"[A-Z_]{3,48}", code):
        return code
    # Expose only fixed type families, never exception text from private data.
    if isinstance(exc, OSError):
        return "LOCAL_OS_ERROR"
    if isinstance(exc, sqlite3.Error):
        return "SQLITE_ERROR"
    if isinstance(exc, UnicodeError):
        return "LOCAL_ENCODING_ERROR"
    if type(exc).__name__ == "HealthUnavailable":
        return "TIER0_HEALTH_UNAVAILABLE"
    return "LOCAL_OPERATION_FAILED"


@contextmanager
def regular_source(directory, name):
    root = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "SOURCE_TYPE")
            yield source
    finally:
        os.close(root)


def read_manifest(directory):
    with regular_source(directory, "SHA256SUMS") as source:
        lines = source.read(8193).decode("ascii").splitlines()
    require(len(lines) == len(ARCHIVES), "MANIFEST_COUNT")
    hashes = {}
    for line in lines:
        match = re.fullmatch(r"([a-fA-F0-9]{64}) [ *](?:\./)?([a-z.-]+)", line)
        require(match is not None, "MANIFEST_FORMAT")
        digest, name = match.groups()
        require(name in ARCHIVES and name not in hashes, "MANIFEST_NAME")
        hashes[name] = digest.lower()
    return hashes


def file_digest(source, algorithm, guard):
    digest = hashlib.new(algorithm, usedforsecurity=algorithm != "md5")
    while data := source.read(CHUNK):
        guard()
        digest.update(data)
    return digest.hexdigest()


def extract(source, destination, guard, remaining):
    count = size = 0
    with tarfile.open(fileobj=source, mode="r|") as archive:
        for members, member in enumerate(archive, 1):
            guard()
            require(members <= 30000, "TAR_LIMIT")
            parts = PurePosixPath(member.name).parts
            require(not member.name.startswith("/") and ".." not in parts and len(parts) <= 32, "TAR_PATH")
            require(member.isdir() or member.isreg(), "TAR_TYPE")
            if not parts and member.isdir():
                continue
            path = destination.joinpath(*parts)
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            count += 1
            size += member.size
            require(0 <= member.size <= remaining and size <= remaining, "TAR_LIMIT")
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with archive.extractfile(member) as item, path.open("xb") as output:
                while data := item.read(CHUNK):
                    guard()
                    output.write(data)
    return count, size


def command(args, guard, seconds=30, stdin=None, output=None, capture=True):
    guard()
    with tempfile.TemporaryFile() as buffer:
        with subprocess.Popen(args, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                              stdout=output if output is not None else buffer if capture else subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL) as child:
            try:
                deadline = time.monotonic() + seconds
                while child.poll() is None:
                    guard()
                    require(time.monotonic() < deadline, "COMMAND_TIMEOUT")
                    time.sleep(0.25)
            finally:
                if child.poll() is None:
                    child.kill()
            if child.returncode:
                return None
        buffer.seek(0)
        data = buffer.read(1024**2 + 1)
        require(len(data) <= 1024**2, "COMMAND_OUTPUT_LIMIT")
        return data.decode("utf-8").strip()


def iq_verify(extracted, guard, evidence=None):
    found = {}
    for name in ("paperless_iq.db", "chroma.sqlite3"):
        paths = list(extracted.rglob(name))
        require(len(paths) == 1, "IQ_DATABASE_LAYOUT")
        path = paths[0]
        guard()
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            db.set_progress_handler(lambda: guard() or 0, 10000)
            require(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "IQ_SQLITE_INTEGRITY")
            if evidence is not None:
                evidence["iq_sqlite_integrity" if name == "paperless_iq.db" else "chroma_sqlite_integrity"] = "PASS"
            found[name] = db.execute("SELECT count(*) FROM sqlite_schema WHERE type='table'").fetchone()[0]
            if name == "chroma.sqlite3":
                segments = {row[0] for row in db.execute("SELECT id FROM segments WHERE scope='VECTOR'")}
                disk = {p.parent.name for p in path.parent.glob("*/header.bin") if p.stat().st_size > 0}
                if evidence is not None:
                    evidence["chroma_vector_rows"] = len(segments)
                    evidence["chroma_disk_segments"] = len(disk)
                    evidence["chroma_disk_segments_unmapped"] = len(disk - segments)
                    evidence["chroma_vector_rows_without_disk"] = len(segments - disk)
                require(bool(segments) and segments <= disk, "CHROMA_SEGMENT_LAYOUT")
                require(all(all((path.parent / segment / f).is_file()
                                for f in ("data_level0.bin", "length.bin", "link_lists.bin"))
                            for segment in disk), "CHROMA_INDEX_FILES")
                found["vector_segments"] = len(segments)
                found["persisted_vector_segments"] = len(disk)
        db.close()
    return found


def chroma_native_proof(extracted, container, guard, evidence):
    """Load only the staged Chroma copy with its already-installed library."""
    image = command([DOCKER, 'inspect', '--format={{.Image}}', 'paperless-iq'], guard)
    require(image and re.fullmatch(r'sha256:[a-f0-9]{64}', image), 'IQ_IMAGE_IDENTITY')
    roots = list(extracted.rglob('chroma.sqlite3'))
    require(len(roots) == 1, 'IQ_DATABASE_LAYOUT')
    source = '''import json
import chromadb
from chromadb.config import Settings
client = chromadb.PersistentClient(path='/recovery', settings=Settings(anonymized_telemetry=False))
collections = client.list_collections()
assert 0 < len(collections) <= 20
total = tested = 0
for item in collections:
    collection = client.get_collection(item if isinstance(item, str) else item.name, embedding_function=None)
    count = collection.count()
    total += count
    if count:
        sample = collection.get(limit=1, include=['embeddings'])
        assert sample['embeddings'] is not None and len(sample['embeddings']) == 1
        result = collection.query(query_embeddings=sample['embeddings'], n_results=1, include=['distances'])
        assert len(result['ids']) == 1 and len(result['ids'][0]) == 1
        assert abs(float(result['distances'][0][0])) < 0.0001
        tested += 1
assert total > 0 and tested > 0
print('CHROMA_NATIVE_RESULT=' + json.dumps([len(collections), total, tested]))
'''
    name = container + '-iq'
    finished = False
    try:
        raw = command([DOCKER, 'run', '--pull=never', '--name', name, '--network=none',
                       '--restart=no', '--cpus=0.5', '--memory=768m', '--memory-swap=768m',
                       '--pids-limit=64', '--read-only', '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m',
                       '--user=0:0', '--cap-drop=ALL', '--log-driver=none', '--security-opt=no-new-privileges',
                       '--mount', f'type=bind,src={roots[0].parent},dst=/recovery',
                       '-e', 'ANONYMIZED_TELEMETRY=False', '--entrypoint', 'python3',
                       image, '-c', source], guard, seconds=100)
        require(raw is not None, 'CHROMA_NATIVE_LOAD')
        finished = True
        rows = [line.removeprefix('CHROMA_NATIVE_RESULT=') for line in raw.splitlines() if line.startswith('CHROMA_NATIVE_RESULT=')]
        require(len(rows) == 1, 'CHROMA_NATIVE_OUTPUT')
        counts = json.loads(rows[0])
        require(isinstance(counts, list) and len(counts) == 3 and
                all(type(value) is int and 0 < value <= 1000000 for value in counts), 'CHROMA_NATIVE_OUTPUT')
        evidence['chroma_native_collections'], evidence['chroma_native_embeddings'], evidence['chroma_native_query_tests'] = counts
        evidence['chroma_native_restore'] = 'PASS'
    finally:
        # Only this random test container is addressed, including on abort.
        if not finished:
            command([DOCKER, 'stop', '--time=3', name], lambda: None, seconds=15, capture=False)
        removed = command([DOCKER, 'rm', '-v', name], lambda: None, seconds=30, capture=False)
        evidence['iq_temporary_cleanup'] = 'PASS' if removed is not None else 'UNVERIFIED'
        require(removed is not None, 'IQ_TEMPORARY_CLEANUP')


def recover_completed_iq_cleanup(guard):
    """Finish cleanup only for this implementation's recorded successful IQ tests."""
    checked = 0
    for report in REPORT_DIR.glob('*.json'):
        require(checked < 100, 'REPORT_SCAN_LIMIT')
        checked += 1
        if not re.fullmatch(r'[a-f0-9]{32}\.json', report.name):
            continue
        with regular_source(REPORT_DIR, report.name) as source:
            raw = source.read(16385)
        require(len(raw) <= 16384, 'REPORT_SIZE')
        record = json.loads(raw)
        if record.get('chroma_native_restore') != 'PASS' or record.get('iq_temporary_cleanup') == 'PASS':
            continue
        name = 'lifeos-paperless-rehearsal-' + report.stem + '-iq'
        listing = command([DOCKER, 'ps', '--all', '--quiet', '--filter', f'name=^/{name}$'], guard, seconds=30)
        require(listing is not None, 'IQ_PREVIOUS_STATE')
        if not listing:
            continue
        require(re.fullmatch(r'[a-f0-9]{12,64}', listing) is not None, 'IQ_PREVIOUS_IDENTITY')
        state = command([DOCKER, 'inspect', '--format={{.State.Status}}|{{.HostConfig.NetworkMode}}|{{len .HostConfig.PortBindings}}|{{json .Config.Entrypoint}}', name], guard)
        require(state == 'exited|none|0|["python3"]', 'IQ_PREVIOUS_STATE')
        require(command([DOCKER, 'rm', '-v', name], guard, seconds=30, capture=False) is not None, 'IQ_PREVIOUS_CLEANUP')


def verified_recovery_record(record):
    return (isinstance(record, dict) and record.get('archives_verified') == 5
            and record.get('postgres_restore') == 'PASS'
            and type(record.get('originals_checked')) is int and record['originals_checked'] > 0
            and record.get('originals_missing') == 0
            and record.get('originals_checksum_mismatch') == 0
            and record.get('temporary_stop') == 'PASS')


def validated_test_stage(source):
    stage = Path(source).parent
    require(Path(source).name == 'db' and stage.parent == HDD and
            re.fullmatch(r'\.paperless-restore-[a-z0-9_]{8}', stage.name), 'CLEANUP_STAGE_PATH')
    require(not stage.is_symlink(), 'CLEANUP_STAGE_IDENTITY')
    if not stage.exists():
        return stage
    require(stage.resolve() == stage and stage.stat().st_uid == 0
            and not stage.stat().st_mode & 0o077
            and stage.stat().st_dev == HDD.stat().st_dev, 'CLEANUP_STAGE_IDENTITY')
    expected = {'db', 'paperless.dump', 'media', 'configuration', 'historical-email', 'paperless-iq'}
    require({path.name for path in stage.iterdir()} <= expected, 'CLEANUP_STAGE_CONTENTS')
    with Path('/proc/self/mountinfo').open() as mounts:
        require(not any(len(fields := row.split()) >= 5 and
                        (fields[4] == str(stage) or fields[4].startswith(str(stage) + '/'))
                        for row in mounts), 'CLEANUP_STAGE_MOUNT')
    return stage


def cleanup_verified_staging(guard, evidence):
    """Reclaim disposable copies only after verified data restoration and stopped DB."""
    recover_completed_iq_cleanup(guard)
    removed = 0
    reports = list(REPORT_DIR.glob('*.json'))
    require(len(reports) <= 100, 'REPORT_SCAN_LIMIT')
    for report in reports:
        if not re.fullmatch(r'[a-f0-9]{32}\.json', report.name):
            continue
        with regular_source(REPORT_DIR, report.name) as source:
            raw = source.read(16385)
        require(len(raw) <= 16384, 'REPORT_SIZE')
        if not verified_recovery_record(json.loads(raw)):
            continue
        name = 'lifeos-paperless-rehearsal-' + report.stem
        listing = command([DOCKER, 'ps', '--all', '--quiet', '--filter', f'name=^/{name}$'], guard)
        require(listing is not None, 'CLEANUP_CONTAINER_LIST')
        if not listing:
            continue
        require(re.fullmatch(r'[a-f0-9]{12,64}', listing) is not None, 'CLEANUP_CONTAINER_ID')
        raw_info = command([DOCKER, 'inspect', '--format={{json .}}', listing], guard)
        require(raw_info is not None, 'CLEANUP_INSPECT')
        info = json.loads(raw_info)
        require(info['State']['Status'] == 'exited' and not info['State']['Running']
                and info['HostConfig']['NetworkMode'] == 'none'
                and not info['HostConfig']['PortBindings']
                and info['Config']['Labels'].get('lifeos.paperless-rehearsal') == 'true', 'CLEANUP_CONTAINER_IDENTITY')
        mounts = info['Mounts']
        binds = [mount for mount in mounts if mount['Type'] == 'bind']
        require(len(binds) == 1 and binds[0]['Destination'] == '/rehearsal'
                and all(mount['Type'] == 'bind' or
                        (mount['Type'] == 'volume' and mount['Destination'] == '/var/lib/postgresql/data'
                         and re.fullmatch(r'[a-f0-9]{64}', mount.get('Name', '')))
                        for mount in mounts), 'CLEANUP_CONTAINER_MOUNT')
        stage = validated_test_stage(binds[0]['Source'])
        # Reject a staging tree referenced by any other container, including stopped ones.
        ids = command([DOCKER, 'ps', '--all', '--quiet'], guard)
        require(ids is not None and len(ids.splitlines()) <= 100
                and all(re.fullmatch(r'[a-f0-9]{12,64}', value) for value in ids.splitlines()), 'CLEANUP_REFERENCE_LIST')
        raw_refs = command([DOCKER, 'inspect', '--format={{.Id}}|{{json .Mounts}}', *ids.splitlines()], guard)
        require(raw_refs is not None, 'CLEANUP_REFERENCE_INSPECT')
        for row in raw_refs.splitlines():
            identifier, raw_mounts = row.split('|', 1)
            if identifier == info['Id']:
                continue
            for mount in json.loads(raw_mounts):
                source = Path(mount.get('Source', '/'))
                # Broad read-only host observers do not own this private test tree.
                # Exact/descendant references and writable/unknown ancestors still block.
                if (mount.get('Type') == 'bind' and mount.get('RW') is False
                        and source != stage and stage.is_relative_to(source)):
                    evidence['cleanup_readonly_ancestor_references'] = evidence.get('cleanup_readonly_ancestor_references', 0) + 1
                    continue
                if source.is_relative_to(stage) or stage.is_relative_to(source):
                    evidence['cleanup_reference_relationship'] = ('STAGE_OR_DESCENDANT' if source.is_relative_to(stage) else 'ANCESTOR')
                    evidence['cleanup_reference_access'] = 'READ_ONLY' if mount.get('RW') is False else 'WRITABLE_OR_UNKNOWN'
                    evidence['cleanup_reference_type'] = mount.get('Type') if mount.get('Type') in ('bind', 'volume') else 'OTHER'
                    raise RehearsalError('CLEANUP_OTHER_REFERENCE')
        guard()
        # Keep the stopped container as a reference until its private staging is gone.
        existed = stage.exists()
        if existed:
            shutil.rmtree(stage)
        require(command([DOCKER, 'rm', '-v', info['Id']], guard, seconds=30, capture=False) is not None,
                'CLEANUP_CONTAINER_REMOVE')
        removed += int(existed)
    evidence['verified_test_stages_removed'] = removed


def restore_reserve_from_verified_tests(resolver, public, evidence):
    """Only reclaim stopped, verified disposable restores while reserve is low.

    Network, AdGuard and resource checks stay mandatory. Storage reserve is
    rechecked by the full health gate before any new staging or restoration.
    """
    def cleanup_probe():
        checks = health_checks(resolver, public)
        return {key: value for key, value in checks.items() if key != 'storage_reserve'}
    gate = HealthGate(cleanup_probe, interval=3, max_age=16)
    try:
        gate.start()
        def guard():
            gate.guard()
            stats = os.statvfs(HDD)
            require(stats.f_bavail * stats.f_frsize >= RESERVE and stats.f_favail >= 50000, 'CLEANUP_RESERVE')
            require(resource_ready(evidence=evidence), 'PI_RESOURCE_LIMIT')
        # Prove the original checkpoint is readable and intact before discarding copies.
        hashes = read_manifest(CHECKPOINT)
        for name in ARCHIVES:
            with regular_source(CHECKPOINT, name) as source:
                require(file_digest(source, 'sha256', guard) == hashes[name], 'ARCHIVE_CHECKSUM')
        evidence['cleanup_checkpoint_hashes_verified'] = len(hashes)
        cleanup_verified_staging(guard, evidence)
    finally:
        evidence['cleanup_health_diagnostic'] = gate.diagnostics(TIER0_CHECKS)
        gate.close()


def postgres_image(guard):
    raw = command([DOCKER, "ps", "-q", "--filter", "label=com.docker.compose.project=paperless",
                   "--filter", "label=com.docker.compose.service=db"], guard)
    require(raw and re.fullmatch(r"[a-f0-9]{12,64}", raw), "POSTGRES_CONTAINER_IDENTITY")
    image = command([DOCKER, "inspect", "--format={{.Image}}", raw], guard)
    require(image and re.fullmatch(r"sha256:[a-f0-9]{64}", image), "POSTGRES_IMAGE_IDENTITY")
    return image


def historical_email_inventory(directory, guard):
    """Describe extracted recovery files without assuming their format."""
    counts = {"eml": 0, "mbox": 0, "zip": 0, "tar": 0, "gzip": 0, "other": 0}
    for path in directory.rglob("*"):
        guard()
        if not path.is_file():
            continue
        family = {".eml": "eml", ".mbox": "mbox", ".zip": "zip", ".tar": "tar",
                  ".gz": "gzip", ".tgz": "gzip"}.get(path.suffix.lower(), "other")
        counts[family] += 1
    return {"historical_" + family + "_files": count for family, count in counts.items()}


def resource_ready(*, initial=False, evidence=None):
    memory = Path('/proc/meminfo').read_text()
    available = re.search(r'^MemAvailable:\s+([0-9]+) kB$', memory, re.MULTILINE)
    temperature = int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())
    minimum = (2 if initial else 1) * 1024**2
    load = os.getloadavg()[0]
    if evidence is not None:
        evidence['resource_available_mib'] = int(available[1]) // 1024 if available else 0
        evidence['resource_temperature_millicelsius'] = temperature
        evidence['resource_load_milli'] = round(load * 1000)
    return bool(available and int(available[1]) >= minimum
                and 0 < temperature < 75000 and load < 4)


def database_proof(stage, container, guard, evidence):
    evidence["phase"] = "POSTGRES_IMAGE"
    image = postgres_image(guard)
    data = stage / "db"
    data.mkdir(mode=0o700)
    evidence["postgres_start_attempted"] = True
    evidence["phase"] = "POSTGRES_START"
    require(command([DOCKER, "run", "-d", "--pull=never", "--name", container,
                     "--label=lifeos.paperless-rehearsal=true", "--network=none",
                     "--restart=no", "--cpus=0.50", "--memory=768m", "--memory-swap=768m",
                     "--pids-limit=64", "--log-driver=none", "--security-opt=no-new-privileges",
                     "--mount", f"type=bind,src={data},dst=/rehearsal",
                     "-e", "PGDATA=/rehearsal", "-e", "POSTGRES_USER=rehearsal",
                     "-e", "POSTGRES_DB=rehearsal", "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
                     image, "postgres", "-c", "listen_addresses=", "-c", "max_connections=10",
                     "-c", "unix_socket_directories=/var/run/postgresql,/rehearsal"],
                    guard, seconds=70) is not None, "POSTGRES_START")
    evidence["phase"] = "POSTGRES_ISOLATION"
    proof = command([DOCKER, "inspect", "--format={{.HostConfig.NetworkMode}}|{{len .HostConfig.PortBindings}}|{{.Config.Image}}",
                     container], guard)
    require(proof == f"none|0|{image}", "POSTGRES_ISOLATION")
    evidence["phase"] = "POSTGRES_READY"
    for _ in range(50):
        # The entrypoint's initialization server may answer pg_isready briefly.
        if command([DOCKER, "exec", container, "cat", "/proc/1/comm"], guard, seconds=5) == "postgres" and command([DOCKER, "exec", container, "pg_isready", "-h", "/var/run/postgresql", "-U", "rehearsal"], guard,
                   seconds=5) is not None:
            break
        time.sleep(1)
    else:
        raise RehearsalError("POSTGRES_NOT_READY")
    evidence["phase"] = "POSTGRES_RESTORE"
    with (stage / "paperless.dump").open("rb") as dump:
        require(command([DOCKER, "exec", "-i", container, "pg_restore", "--host=/var/run/postgresql",
                         "--username=rehearsal", "--dbname=rehearsal", "--no-owner", "--no-privileges",
                         "--exit-on-error", "--single-transaction"], guard, seconds=450,
                        stdin=dump, capture=False) is not None, "POSTGRES_RESTORE")
    def query(sql):
        rows = command([DOCKER, "exec", container, "psql", "-XAt", "--host=/var/run/postgresql",
                        "--username=rehearsal", "--dbname=rehearsal", "--set=ON_ERROR_STOP=1", "-c", sql], guard)
        require(rows is not None, "POSTGRES_QUERY")
        return rows
    evidence["phase"] = "POSTGRES_SCHEMA"
    schema = json.loads(query("""SELECT json_build_array(
        (SELECT count(*) FROM pg_tables WHERE schemaname='public'),
        (SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid
         JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND i.indisvalid),
        (SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
         WHERE n.nspname='public' AND c.convalidated),
        (SELECT count(*) FROM documents_document WHERE root_document_id IS NULL),
        (SELECT count(*) FROM documents_document WHERE content <> ''),
        (SELECT count(*) FROM auth_user WHERE is_active))"""))
    require(len(schema) == 6 and all(type(n) is int and n > 0 for n in schema), "POSTGRES_SCHEMA")
    evidence["postgres_tables"], evidence["postgres_indexes"], evidence["postgres_constraints"], evidence["root_documents"], evidence["stored_text_rows"], evidence["active_users"] = schema
    evidence["postgres_restore"] = "PASS"
    evidence["phase"] = "ORIGINAL_MEDIA"
    rows = query("SELECT json_build_array(id, filename, checksum) FROM documents_document ORDER BY id LIMIT 10001")
    originals = list((stage / "media").rglob("originals"))
    require(len(originals) == 1 and originals[0].is_dir(), "MEDIA_ORIGINALS_LAYOUT")
    base = originals[0]
    missing = mismatch = checked = 0
    records = rows.splitlines()
    require(0 < len(records) <= 10000, "MEDIA_ROW_LIMIT")
    for row in records:
        guard()
        identifier, filename, checksum = json.loads(row)
        require(type(identifier) is int and identifier > 0 and isinstance(checksum, str)
                and re.fullmatch(r"(?:[a-fA-F0-9]{32}|[a-fA-F0-9]{64})", checksum), "MEDIA_ROW_FORMAT")
        if not filename:
            candidates = list(base.glob(f"{identifier:07}.*"))
            path = candidates[0] if len(candidates) == 1 else None
        else:
            relative = PurePosixPath(filename)
            require(not relative.is_absolute() and ".." not in relative.parts, "MEDIA_ROW_PATH")
            path = base.joinpath(*relative.parts)
        if path is None or not path.is_file():
            missing += 1
        else:
            with path.open("rb") as source:
                algorithm = "md5" if len(checksum) == 32 else "sha256"
                mismatch += file_digest(source, algorithm, guard) != checksum.lower()
            checked += 1
    evidence.update(originals_checked=checked, originals_missing=missing, originals_checksum_mismatch=mismatch)
    require(not missing and not mismatch, "DOCUMENT_MEDIA_INCONSISTENT")



APPLICATION_PROBE = r"""
import json, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'paperless.settings')
probe_stage = 'DJANGO_SETUP'
import django
django.setup()
from django.contrib.auth import get_user_model
from django.core.management import call_command
from documents.models import Document
from rest_framework.test import APIClient
probe_stage = 'DATABASE_MODELS'
user = get_user_model().objects.filter(is_active=True, is_superuser=True).first()
assert user is not None
count = Document.objects.filter(root_document__isnull=True).count()
assert count > 0
client = APIClient()
probe_stage = 'ACCESS_CONTROL'
unauth = client.get('/api/documents/')
assert unauth.status_code in (401, 403)
client.force_authenticate(user=user)
probe_stage = 'DOCUMENT_LIST'
listing = client.get('/api/documents/?page_size=1')
assert listing.status_code == 200 and listing.data['count'] == count
first = Document.objects.filter(root_document__isnull=True).order_by('id').first()
assert first.original_path.is_file()
probe_stage = 'ORIGINAL_RETRIEVAL'
response = client.get('/api/documents/%d/download/?original=true' % first.pk)
assert response.status_code == 200
retrieved = sum(len(chunk) for chunk in response.streaming_content)
assert retrieved == first.original_path.stat().st_size and retrieved > 0
# Rebuild a disposable native search index; no live index or ingestion worker runs.
import contextlib, io
probe_stage = 'INDEX_REBUILD'
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    call_command('document_index', 'reindex', verbosity=0)
probe_stage = 'NATIVE_SEARCH'
import re
terms = re.findall(r'[A-Za-z]{7,40}', first.content or first.title)
assert terms
query = client.get('/api/documents/', {'query': terms[0], 'page_size': 1})
assert query.status_code == 200 and query.data['count'] > 0
print(json.dumps({'application_documents': count, 'application_list': 'PASS',
 'application_access_control': 'PASS', 'application_original_retrieval': 'PASS',
 'application_retrieved_files': 1, 'application_index_rebuild': 'PASS',
 'application_search_endpoint': 'PASS'}))
"""

APPLICATION_PROBE = 'import json\ntry:\n' + ''.join('    ' + line + '\n' for line in APPLICATION_PROBE.splitlines()) + \
    "except Exception:\n    print(json.dumps({'application_failure_phase': globals().get('probe_stage', 'BOOTSTRAP')}))\n"


def application_proof(stage, container, guard, evidence):
    """Use the installed native app against restored PostgreSQL/media only."""
    raw = command([DOCKER, 'ps', '-q', '--filter', 'label=com.docker.compose.project=paperless',
                   '--filter', 'label=com.docker.compose.service=paperless'], guard)
    require(raw and re.fullmatch(r'[a-f0-9]{12,64}', raw), 'APPLICATION_CONTAINER_IDENTITY')
    image = command([DOCKER, 'inspect', '--format={{.Image}}', raw], guard)
    require(image and re.fullmatch(r'sha256:[a-f0-9]{64}', image), 'APPLICATION_IMAGE_IDENTITY')
    originals = list((stage / 'media').rglob('originals'))
    require(len(originals) == 1, 'MEDIA_ORIGINALS_LAYOUT')
    name = container + '-app'
    args = [DOCKER, 'run', '--pull=never', '--name', name, '--network=none', '--restart=no',
            '--read-only', '--user=0:0', '--cap-drop=ALL', '--security-opt=no-new-privileges',
            '--cpus=0.50', '--memory=1024m', '--memory-swap=1024m', '--pids-limit=64', '--log-driver=none',
            '--mount', f'type=bind,src={stage / "db"},dst=/restore-db,readonly',
            '--mount', f'type=bind,src={originals[0].parent},dst=/usr/src/paperless/media,readonly',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m',
            '--tmpfs', '/usr/src/paperless/data:rw,nosuid,nodev,size=256m',
            '--entrypoint=python3']
    environment = {'PAPERLESS_SECRET_KEY': uuid.uuid4().hex + uuid.uuid4().hex,
                   'PAPERLESS_ALLOWED_HOSTS': 'testserver', 'PYTHONDONTWRITEBYTECODE': '1',
                   'PAPERLESS_DBHOST': '/restore-db', 'PAPERLESS_DBNAME': 'rehearsal',
                   'PAPERLESS_DBUSER': 'rehearsal', 'PAPERLESS_DBPASS': '',
                   'PAPERLESS_URL': 'http://testserver',
                   'PAPERLESS_REDIS': 'redis://127.0.0.1:1',
                   'HOME': '/tmp', 'PAPERLESS_TASK_WORKERS': '1', 'PAPERLESS_THREADS_PER_WORKER': '1'}
    for key, value in environment.items():
        args.extend(['-e', key + '=' + value])
    args.insert(2, '--label=lifeos.paperless-rehearsal=true')
    args.extend([image, '-c', APPLICATION_PROBE])
    finished = False
    try:
        result = command(args, guard, seconds=450)
        require(result is not None, 'APPLICATION_PROBE')
        finished = True
        proof = json.loads(result)
        if set(proof) == {'application_failure_phase'}:
            require(proof['application_failure_phase'] in {'BOOTSTRAP', 'DJANGO_SETUP', 'DATABASE_MODELS', 'ACCESS_CONTROL', 'DOCUMENT_LIST', 'ORIGINAL_RETRIEVAL', 'INDEX_REBUILD', 'NATIVE_SEARCH'}, 'APPLICATION_PROOF')
            evidence.update(proof)
            raise RehearsalError('APPLICATION_PROBE')
        expected = {'application_list', 'application_access_control', 'application_original_retrieval',
                    'application_index_rebuild', 'application_search_endpoint'}
        require(set(proof) == expected | {'application_documents', 'application_retrieved_files'}
                and all(proof[key] == 'PASS' for key in expected)
                and proof['application_documents'] == evidence['root_documents']
                and proof['application_retrieved_files'] == 1, 'APPLICATION_PROOF')
        evidence.update(proof)
        evidence['application_restore'] = 'PASS'
    finally:
        if not finished:
            command([DOCKER, 'stop', '--time=3', name], lambda: None, seconds=15, capture=False)
        removed = command([DOCKER, 'rm', '-v', name], lambda: None, seconds=30, capture=False)
        evidence['application_temporary_cleanup'] = 'PASS' if removed is not None else 'UNVERIFIED'
        require(removed is not None, 'APPLICATION_TEMPORARY_CLEANUP')


def main():
    os.umask(0o077)
    started = time.monotonic()
    REPORT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    require(REPORT_DIR.is_dir() and not REPORT_DIR.is_symlink() and REPORT_DIR.stat().st_uid == 0
            and not REPORT_DIR.stat().st_mode & 0o077, "REPORT_DIRECTORY")
    suffix = uuid.uuid4().hex
    evidence = {"result": "FAILED", "application_restore": "NOT_RUN", "iq_application_compatibility": "NOT_RUN"}
    gate = None
    stage = None
    container = f"lifeos-paperless-rehearsal-{suffix}"
    def interrupted(*_):
        raise RehearsalError("INTERRUPTED")
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    with (REPORT_DIR / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            require(os.geteuid() == 0 and HDD.is_mount() and CHECKPOINT.resolve() == CHECKPOINT
                    and CHECKPOINT.stat().st_dev == HDD.stat().st_dev, "CHECKPOINT_MOUNT")
            blocks = os.statvfs(HDD)
            evidence['hdd_available_bytes'] = blocks.f_bavail * blocks.f_frsize
            evidence['hdd_tier0_reserve_bytes'] = max(10 * 1024**3, blocks.f_blocks * blocks.f_frsize // 10)
            evidence['hdd_available_inodes'] = blocks.f_favail
            require(blocks.f_bavail * blocks.f_frsize >= RESERVE + LIMIT and blocks.f_favail >= 100000,
                    "STAGING_CAPACITY")
            require(resource_ready(initial=True, evidence=evidence), "PI_RESOURCE_PRECHECK")
            resolver, public = connection_inputs()
            if evidence['hdd_available_bytes'] < evidence['hdd_tier0_reserve_bytes'] + LIMIT:
                evidence['phase'] = 'VERIFIED_TEST_CLEANUP'
                restore_reserve_from_verified_tests(resolver, public, evidence)
                after_cleanup = os.statvfs(HDD)
                evidence['hdd_available_after_cleanup_bytes'] = after_cleanup.f_bavail * after_cleanup.f_frsize
            gate = HealthGate(lambda: health_checks(resolver, public), interval=3, max_age=16)
            gate.start()
            next_resource_check = 0
            def guard():
                nonlocal next_resource_check
                gate.guard()
                now = time.monotonic()
                if now >= next_resource_check:
                    usage = os.statvfs(HDD)
                    require(usage.f_bavail * usage.f_frsize >= RESERVE and usage.f_favail >= 50000, "STAGING_RESERVE")
                    require(resource_ready(evidence=evidence), "PI_RESOURCE_LIMIT")
                    next_resource_check = now + 3
            recover_completed_iq_cleanup(guard)
            hashes = read_manifest(CHECKPOINT)
            for name in ARCHIVES:
                with regular_source(CHECKPOINT, name) as source:
                    require(0 < os.fstat(source.fileno()).st_size <= LIMIT, "ARCHIVE_SIZE")
                    require(file_digest(source, "sha256", guard) == hashes[name], "ARCHIVE_CHECKSUM")
            evidence["archives_verified"] = len(hashes)
            stage = Path(tempfile.mkdtemp(prefix=".paperless-restore-", dir=HDD))
            remaining = LIMIT
            for name in ARCHIVES:
                with regular_source(CHECKPOINT, name) as source:
                    require(0 < os.fstat(source.fileno()).st_size <= LIMIT, "ARCHIVE_SIZE")
                    if name == "paperless.dump":
                        with (stage / name).open("xb") as output:
                            while data := source.read(CHUNK):
                                guard()
                                remaining -= len(data)
                                require(remaining >= 0, "STAGING_LIMIT")
                                output.write(data)
                    else:
                        target = stage / name.removesuffix(".tar")
                        target.mkdir(mode=0o700)
                        count, size = extract(source, target, guard, remaining)
                        require(count > 0, "ARCHIVE_EMPTY")
                        remaining -= size
                        evidence[name.removesuffix(".tar").replace("-", "_") + "_files"] = count
                    source.seek(0)
                    require(file_digest(source, "sha256", guard) == hashes[name], "ARCHIVE_CHANGED")
            require(hashes == read_manifest(CHECKPOINT), "MANIFEST_CHANGED")
            config = stage / "configuration"
            require(any(p.is_file() and p.stat().st_size > 0 for basename in ("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml")
                        for p in config.rglob(basename)), "COMPOSE_MISSING")
            require(any(p.is_file() and p.stat().st_size > 0 for p in config.rglob(".env")), "ENV_MISSING")
            evidence.update(historical_email_inventory(stage / "historical-email", guard))
            evidence["historical_email_recovery"] = "UNVERIFIED"
            try:
                evidence.update(iq_verify(stage / "paperless-iq", guard, evidence))
                evidence["iq_files"] = "PASS"
            except RehearsalError as exc:
                code = failure_code(exc)
                if code not in {"IQ_DATABASE_LAYOUT", "IQ_SQLITE_INTEGRITY", "CHROMA_SEGMENT_LAYOUT", "CHROMA_INDEX_FILES"}:
                    raise
                evidence["iq_files"] = code
            database_proof(stage, container, guard, evidence)
            if evidence["iq_files"] == "PASS":
                evidence['phase'] = 'CHROMA_NATIVE_LOAD'
                chroma_native_proof(stage / 'paperless-iq', container, guard, evidence)
            evidence['phase'] = 'APPLICATION_RECOVERY'
            application_proof(stage, container, guard, evidence)
            gate.sample()
            gate.guard()
            evidence["tier0"] = "PASS"
            evidence["result"] = "DATA_RESTORE_PASS" if evidence["iq_files"] == "PASS" else "PARTIAL"
            evidence["phase"] = "DATA_CHECKS_COMPLETE"
        except Exception as exc:
            evidence["failure"] = failure_code(exc)
        finally:
            # Stop only this run's random container, even when health gates abort.
            if evidence.get("postgres_start_attempted"):
                try:
                    stopped = command([DOCKER, "stop", "--time=5", container], lambda: None, seconds=15, capture=False)
                    if stopped is None:
                        # A resource guard may abort before docker run executes.
                        remaining = command([DOCKER, 'ps', '--all', '--quiet', '--filter',
                                             f'name=^/{container}$'], lambda: None, seconds=10)
                        evidence["temporary_stop"] = "ABSENT" if remaining == '' else "UNVERIFIED"
                    else:
                        evidence["temporary_stop"] = "PASS"
                except Exception:
                    evidence["temporary_stop"] = "UNVERIFIED"
            report = REPORT_DIR / (suffix + ".json")
            if gate is not None:
                evidence['tier0_diagnostic'] = gate.diagnostics(TIER0_CHECKS)
            evidence["elapsed_seconds"] = round(time.monotonic() - started)
            with report.open("x") as output:
                json.dump(evidence, output, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            if gate is not None:
                gate.close()
            if evidence["result"] == "DATA_RESTORE_PASS":
                try:
                    require(command([DOCKER, "rm", "-v", container], lambda: None, capture=False) is not None, "CLEANUP_CONTAINER")
                    shutil.rmtree(stage)
                    print("PAPERLESS_RECOVERY_TEMPORARY_CLEANUP=PASS", flush=True)
                except Exception:
                    print("PAPERLESS_RECOVERY_TEMPORARY_CLEANUP=UNVERIFIED", flush=True)
                    return 2
            print("PAPERLESS_RECOVERY_EVIDENCE=" + json.dumps(evidence, sort_keys=True), flush=True)
            return 0 if evidence["result"] == "DATA_RESTORE_PASS" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("PAPERLESS_RECOVERY_RESULT=BOOTSTRAP_FAILED", flush=True)
        raise SystemExit(2)

