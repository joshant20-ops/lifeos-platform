"""Protected, fail-closed transaction core for bounded root file changes.

The controller is deliberately independent of Governor.  Its durable state is
the API between the broker, verifier and rollback watchdog.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone

STATE_ROOT = pathlib.Path("/var/lib/lifeos-transactions")
DEFAULT_DEADLINE = 7200
ALLOWED_DESTINATIONS = (pathlib.Path("/usr/local/libexec"),)
PROTECTED = {
    pathlib.Path("/usr/local/sbin/lifeos-transaction-controller"),
    pathlib.Path("/usr/local/sbin/lifeos-rollback"),
    pathlib.Path("/usr/local/lib/lifeos_transaction.py"),
    pathlib.Path("/etc/systemd/system/lifeos-rollback@.service"),
    pathlib.Path("/etc/systemd/system/lifeos-rollback@.timer"),
}
TERMINAL = {"COMMITTED", "ROLLED_BACK", "FAILED"}


class TransactionError(RuntimeError):
    pass


def utcnow():
    return datetime.now(timezone.utc)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def inside(path, parents):
    resolved = path.resolve(strict=False)
    return any(resolved == parent or parent in resolved.parents for parent in parents)


class Controller:
    def __init__(self, state_root=STATE_ROOT, run=None, now=utcnow):
        self.root = pathlib.Path(state_root)
        self.run = run or self._run
        self.now = now

    @staticmethod
    def _run(command, timeout=30):
        return subprocess.run(command, text=True, capture_output=True, timeout=timeout)

    def _dir(self, transaction_id):
        if not transaction_id or len(transaction_id) > 100 or not all(c.isalnum() or c in "._-" for c in transaction_id):
            raise TransactionError("invalid transaction id")
        return self.root / transaction_id

    def _load(self, transaction_id):
        try:
            return json.loads((self._dir(transaction_id) / "manifest.json").read_text())
        except (OSError, ValueError) as exc:
            raise TransactionError(f"transaction unavailable: {exc}") from exc

    def _save(self, manifest):
        manifest["updated_at"] = self.now().isoformat()
        atomic_json(self._dir(manifest["transaction_id"]) / "manifest.json", manifest)

    def _systemctl(self, *arguments, timeout=30):
        result = self.run(["systemctl", *arguments], timeout=timeout)
        if result.returncode:
            raise TransactionError(f"systemctl {' '.join(arguments)} failed")
        return result

    def begin(self, transaction_id, proposal):
        txdir = self._dir(transaction_id)
        if txdir.exists():
            raise TransactionError("transaction already exists")
        if proposal.get("operation") != "replace_file":
            raise TransactionError("operation not allowlisted")
        if proposal.get("risk") not in {"LOW", "MEDIUM"}:
            raise TransactionError("unsupported risk class")
        source = pathlib.Path(proposal.get("source", ""))
        destination = pathlib.Path(proposal.get("destination", ""))
        if not source.is_absolute() or not destination.is_absolute():
            raise TransactionError("paths must be absolute")
        if not source.is_file() or source.is_symlink():
            raise TransactionError("source must be a regular file")
        if not inside(destination, ALLOWED_DESTINATIONS) or destination.resolve(strict=False) in PROTECTED:
            raise TransactionError("destination is not allowlisted")
        expected = proposal.get("sha256")
        if expected != sha256(source):
            raise TransactionError("source checksum mismatch")
        checks = proposal.get("checks")
        if not isinstance(checks, list) or not checks:
            raise TransactionError("measurable verification checks required")
        allowed_checks = {"file_sha256", "service_active"}
        if any(not isinstance(c, dict) or c.get("type") not in allowed_checks for c in checks):
            raise TransactionError("verification check not allowlisted")
        if not any(c.get("type") == "file_sha256" and pathlib.Path(c.get("path", "")).resolve(strict=False) == destination.resolve(strict=False) and c.get("expected") == expected for c in checks):
            raise TransactionError("destination hash verification required")

        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        locks = self.root / "resource-locks"
        locks.mkdir(mode=0o700, exist_ok=True)
        resource = hashlib.sha256(str(destination.resolve(strict=False)).encode()).hexdigest()
        lock_path = locks / resource
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise TransactionError("conflicting transaction active") from exc
        os.close(fd)
        try:
            txdir.mkdir(mode=0o700)
            backup = txdir / "backups" / "target"
            backup.parent.mkdir(mode=0o700)
            existed = destination.exists()
            prior = {"existed": existed}
            if existed:
                if not destination.is_file() or destination.is_symlink():
                    raise TransactionError("destination must be a regular file")
                shutil.copy2(destination, backup, follow_symlinks=False)
                prior.update(sha256=sha256(backup), mode=stat.S_IMODE(destination.stat().st_mode))
            created = self.now()
            manifest = {
                "schema_version": 1, "transaction_id": transaction_id, "state": "PREPARING",
                "operation": "replace_file", "risk": proposal["risk"],
                "component": proposal.get("component", "unspecified"),
                "source": str(source), "destination": str(destination), "intended_sha256": expected,
                "prior": prior, "checks": checks, "resource_lock": str(lock_path),
                "created_at": created.isoformat(), "deadline": (created + timedelta(seconds=DEFAULT_DEADLINE)).isoformat(),
                "timer": f"lifeos-rollback@{transaction_id}.timer", "audit": [],
            }
            self._save(manifest)
            # The watchdog is active while state is still PREPARING.  Only a
            # successful systemd response permits ARMED and later mutation.
            self._systemctl("enable", "--now", manifest["timer"])
            manifest["state"] = "ARMED"
            manifest["audit"].append({"event": "WATCHDOG_ARMED", "at": self.now().isoformat()})
            self._save(manifest)
            return manifest
        except Exception:
            shutil.rmtree(txdir, ignore_errors=True)
            lock_path.unlink(missing_ok=True)
            raise

    def apply(self, transaction_id):
        manifest = self._load(transaction_id)
        if manifest["state"] != "ARMED":
            raise TransactionError("mutation requires ARMED transaction")
        source, destination = pathlib.Path(manifest["source"]), pathlib.Path(manifest["destination"])
        if sha256(source) != manifest["intended_sha256"]:
            raise TransactionError("source changed after arming")
        manifest["state"] = "APPLYING"
        self._save(manifest)
        fd, temporary = tempfile.mkstemp(prefix=".lifeos-transaction-", dir=destination.parent)
        os.close(fd)
        try:
            shutil.copyfile(source, temporary, follow_symlinks=False)
            os.chown(temporary, 0, 0)
            os.chmod(temporary, 0o644 if destination.suffix in {".service", ".timer", ".conf"} else 0o755)
            os.replace(temporary, destination)
        finally:
            pathlib.Path(temporary).unlink(missing_ok=True)
        manifest["state"] = "VERIFYING"
        self._save(manifest)
        return manifest

    def verify(self, transaction_id):
        manifest = self._load(transaction_id)
        if manifest["state"] != "VERIFYING":
            raise TransactionError("verification requires VERIFYING transaction")
        evidence = []
        try:
            for check in manifest["checks"]:
                if check["type"] == "file_sha256":
                    actual = sha256(pathlib.Path(check["path"]))
                    passed = actual == check["expected"]
                    evidence.append({"type": "file_sha256", "passed": passed, "actual": actual})
                elif check["type"] == "service_active":
                    result = self.run(["systemctl", "is-active", "--quiet", check["unit"]], timeout=15)
                    passed = result.returncode == 0
                    evidence.append({"type": "service_active", "unit": check["unit"], "passed": passed})
                if not passed:
                    raise TransactionError("critical verification failed")
        except Exception as exc:
            atomic_json(self._dir(transaction_id) / "verification.json", {"accepted": False, "evidence": evidence, "reason": str(exc)})
            self.rollback(transaction_id, "critical verification failure")
            raise
        proof = {"schema_version": 1, "accepted": True, "derived_by": "protected-controller", "at": self.now().isoformat(), "evidence": evidence}
        atomic_json(self._dir(transaction_id) / "verification.json", proof)
        manifest["state"] = "PROBATION"
        manifest["verification"] = {"accepted": True, "derived_by": "protected-controller"}
        self._save(manifest)
        return proof

    def commit(self, transaction_id):
        manifest = self._load(transaction_id)
        if manifest["state"] != "PROBATION":
            raise TransactionError("commit requires PROBATION")
        try:
            deadline = datetime.fromisoformat(manifest["deadline"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TransactionError("transaction deadline unavailable") from exc
        # The timer is the independent backstop, but its dispatch can be
        # delayed by boot or systemd scheduling.  Never let that delay create
        # a fail-open window in which a stale verification can commit.
        if self.now() >= deadline:
            self.rollback(transaction_id, "health deadline expired")
            raise TransactionError("transaction deadline expired; rolled back")
        try:
            proof = json.loads((self._dir(transaction_id) / "verification.json").read_text())
        except Exception as exc:
            raise TransactionError("independent evidence unavailable") from exc
        if proof.get("accepted") is not True or proof.get("derived_by") != "protected-controller" or not proof.get("evidence") or not all(e.get("passed") is True for e in proof["evidence"]):
            raise TransactionError("independent evidence rejected")
        self._systemctl("disable", "--now", manifest["timer"])
        manifest["state"] = "COMMITTED"
        manifest["committed_at"] = self.now().isoformat()
        self._save(manifest)
        pathlib.Path(manifest["resource_lock"]).unlink(missing_ok=True)
        return manifest

    def rollback(self, transaction_id, reason="requested"):
        manifest = self._load(transaction_id)
        if manifest["state"] in {"COMMITTED", "ROLLED_BACK"}:
            raise TransactionError(f"cannot rollback {manifest['state']}")
        manifest["state"] = "ROLLING_BACK"
        self._save(manifest)
        destination = pathlib.Path(manifest["destination"])
        prior = manifest["prior"]
        if prior["existed"]:
            backup = self._dir(transaction_id) / "backups" / "target"
            if sha256(backup) != prior["sha256"]:
                raise TransactionError("backup checksum mismatch")
            fd, temporary = tempfile.mkstemp(prefix=".lifeos-rollback-", dir=destination.parent)
            os.close(fd)
            try:
                shutil.copyfile(backup, temporary, follow_symlinks=False)
                os.chown(temporary, 0, 0)
                os.chmod(temporary, prior["mode"])
                os.replace(temporary, destination)
            finally:
                pathlib.Path(temporary).unlink(missing_ok=True)
        else:
            destination.unlink(missing_ok=True)
        manifest["state"] = "ROLLED_BACK"
        manifest["rollback"] = {"result": "PASS", "reason": reason, "at": self.now().isoformat()}
        result = self.run(["systemctl", "disable", "--now", manifest["timer"]], timeout=30)
        manifest["rollback"]["watchdog_disarmed"] = result.returncode == 0
        self._save(manifest)
        pathlib.Path(manifest["resource_lock"]).unlink(missing_ok=True)
        return manifest

    def status(self, transaction_id):
        return self._load(transaction_id)
