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


def require(condition, code):
    if not condition:
        raise ValueError(code)


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


def iq_verify(extracted, guard):
    found = {}
    for name in ("paperless_iq.db", "chroma.sqlite3"):
        paths = list(extracted.rglob(name))
        require(len(paths) == 1, "IQ_DATABASE_LAYOUT")
        path = paths[0]
        guard()
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            db.set_progress_handler(lambda: guard() or 0, 10000)
            require(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "IQ_SQLITE_INTEGRITY")
            found[name] = db.execute("SELECT count(*) FROM sqlite_schema WHERE type='table'").fetchone()[0]
            if name == "chroma.sqlite3":
                segments = {row[0] for row in db.execute("SELECT id FROM segments WHERE scope='VECTOR'")}
                disk = {p.parent.name for p in path.parent.glob("*/header.bin") if p.stat().st_size > 0}
                require(bool(segments) and disk <= segments, "CHROMA_SEGMENT_LAYOUT")
                require(all(all((path.parent / segment / f).is_file()
                                for f in ("data_level0.bin", "length.bin", "link_lists.bin"))
                            for segment in disk), "CHROMA_INDEX_FILES")
                found["vector_segments"] = len(segments)
                found["persisted_vector_segments"] = len(disk)
        db.close()
    return found


def postgres_image(guard):
    raw = command([DOCKER, "ps", "-q", "--filter", "label=com.docker.compose.project=paperless",
                   "--filter", "label=com.docker.compose.service=db"], guard)
    require(raw and re.fullmatch(r"[a-f0-9]{12,64}", raw), "POSTGRES_CONTAINER_IDENTITY")
    image = command([DOCKER, "inspect", "--format={{.Image}}", raw], guard)
    require(image and re.fullmatch(r"sha256:[a-f0-9]{64}", image), "POSTGRES_IMAGE_IDENTITY")
    return image


def resource_ready():
    memory = Path('/proc/meminfo').read_text()
    available = re.search(r'^MemAvailable:\s+([0-9]+) kB$', memory, re.MULTILINE)
    temperature = int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())
    return bool(available and int(available[1]) >= 2 * 1024**2
                and 0 < temperature < 75000 and os.getloadavg()[0] < 4)


def database_proof(stage, container, guard, evidence):
    image = postgres_image(guard)
    data = stage / "db"
    data.mkdir(mode=0o700)
    require(command([DOCKER, "run", "-d", "--pull=never", "--name", container,
                     "--label=lifeos.paperless-rehearsal=true", "--network=none",
                     "--restart=no", "--cpus=0.50", "--memory=768m", "--memory-swap=768m",
                     "--pids-limit=64", "--log-driver=none", "--security-opt=no-new-privileges",
                     "--mount", f"type=bind,src={data},dst=/rehearsal",
                     "-e", "PGDATA=/rehearsal/data", "-e", "POSTGRES_USER=rehearsal",
                     "-e", "POSTGRES_DB=rehearsal", "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
                     image, "postgres", "-c", "listen_addresses=", "-c", "max_connections=10"],
                    guard, seconds=70) is not None, "POSTGRES_START")
    proof = command([DOCKER, "inspect", "--format={{.HostConfig.NetworkMode}}|{{len .HostConfig.PortBindings}}|{{.Config.Image}}",
                     container], guard)
    require(proof == f"none|0|{image}", "POSTGRES_ISOLATION")
    for _ in range(50):
        # The entrypoint's initialization server may answer pg_isready briefly.
        if command([DOCKER, "exec", container, "cat", "/proc/1/comm"], guard, seconds=5) == "postgres" and command([DOCKER, "exec", container, "pg_isready", "-h", "/var/run/postgresql", "-U", "rehearsal"], guard,
                   seconds=5) is not None:
            break
        time.sleep(1)
    else:
        raise ValueError("POSTGRES_NOT_READY")
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
                and re.fullmatch(r"[a-fA-F0-9]{32}", checksum), "MEDIA_ROW_FORMAT")
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
                mismatch += file_digest(source, "md5", guard) != checksum.lower()
            checked += 1
    evidence.update(originals_checked=checked, originals_missing=missing, originals_checksum_mismatch=mismatch)
    require(not missing and not mismatch, "DOCUMENT_MEDIA_INCONSISTENT")


def main():
    os.umask(0o077)
    REPORT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    require(REPORT_DIR.is_dir() and not REPORT_DIR.is_symlink() and REPORT_DIR.stat().st_uid == 0
            and not REPORT_DIR.stat().st_mode & 0o077, "REPORT_DIRECTORY")
    suffix = uuid.uuid4().hex
    evidence = {"result": "FAILED", "application_restore": "NOT_RUN", "iq_application_compatibility": "NOT_RUN"}
    gate = None
    stage = None
    container = f"lifeos-paperless-rehearsal-{suffix}"
    def interrupted(*_):
        raise ValueError("INTERRUPTED")
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    with (REPORT_DIR / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            require(os.geteuid() == 0 and HDD.is_mount() and CHECKPOINT.resolve() == CHECKPOINT
                    and CHECKPOINT.stat().st_dev == HDD.stat().st_dev, "CHECKPOINT_MOUNT")
            blocks = os.statvfs(HDD)
            require(blocks.f_bavail * blocks.f_frsize >= RESERVE + LIMIT and blocks.f_favail >= 100000,
                    "STAGING_CAPACITY")
            require(resource_ready(), "PI_RESOURCE_PRECHECK")
            resolver, public = connection_inputs()
            gate = HealthGate(lambda: health_checks(resolver, public), interval=3, max_age=16).start()
            def guard():
                gate.guard()
                usage = os.statvfs(HDD)
                require(usage.f_bavail * usage.f_frsize >= RESERVE and usage.f_favail >= 50000, "STAGING_RESERVE")
            hashes = read_manifest(CHECKPOINT)
            stage = Path(tempfile.mkdtemp(prefix=".paperless-restore-", dir=HDD))
            remaining = LIMIT
            for name in ARCHIVES:
                with regular_source(CHECKPOINT, name) as source:
                    require(0 < os.fstat(source.fileno()).st_size <= LIMIT, "ARCHIVE_SIZE")
                    require(file_digest(source, "sha256", guard) == hashes[name], "ARCHIVE_CHECKSUM")
                    source.seek(0)
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
            evidence["archives_verified"] = len(hashes)
            config = stage / "configuration"
            require(any(p.is_file() and p.stat().st_size > 0 for basename in ("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml")
                        for p in config.rglob(basename)), "COMPOSE_MISSING")
            require(any(p.is_file() and p.stat().st_size > 0 for p in config.rglob(".env")), "ENV_MISSING")
            evidence["historical_eml_files"] = sum(p.is_file() for p in (stage / "historical-email").rglob("*.eml"))
            require(evidence["historical_eml_files"] > 0, "HISTORICAL_EMAIL_MISSING")
            evidence.update(iq_verify(stage / "paperless-iq", guard))
            database_proof(stage, container, guard, evidence)
            gate.sample()
            gate.guard()
            evidence["tier0"] = "PASS"
            evidence["result"] = "DATA_RESTORE_PASS"
        except Exception as exc:
            code = str(exc)
            evidence["failure"] = code if isinstance(exc, ValueError) and re.fullmatch(r"[A-Z_]{3,48}", code) else "LOCAL_OPERATION_FAILED"
        finally:
            if gate is not None:
                gate.close()
            # Stop only this run's random container, even when health gates abort.
            if stage is not None:
                try:
                    stopped = command([DOCKER, "stop", "--time=5", container], lambda: None, seconds=15, capture=False)
                    if stopped is None and "postgres_restore" in evidence:
                        evidence["temporary_stop"] = "UNVERIFIED"
                except Exception:
                    evidence["temporary_stop"] = "UNVERIFIED"
            report = REPORT_DIR / (suffix + ".json")
            with report.open("x") as output:
                json.dump(evidence, output, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
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
