#!/usr/bin/env python3
"""Build pinned upstream source plus a reviewed patch; no private data is used."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(*args, cwd=None, capture=False):
    return subprocess.check_output(args, cwd=cwd) if capture else subprocess.check_call(args, cwd=cwd)


def main():
    output = Path(sys.argv[1]).resolve()
    pin = json.loads((ROOT / "config/emailops-upstream.json").read_text())
    patch = ROOT / "third_party/emailops/headless-cli.patch"
    assert digest(patch) == pin["patch_sha256"], "patch checksum mismatch"
    with tempfile.TemporaryDirectory(prefix="emailops-build-") as directory:
        source = Path(directory)
        run("git", "init", "-q", str(source))
        run("git", "remote", "add", "origin", pin["repository"], cwd=source)
        run("git", "fetch", "--depth=1", "origin", pin["commit"], cwd=source)
        run("git", "checkout", "--detach", "FETCH_HEAD", cwd=source)
        assert run("git", "rev-parse", "HEAD", cwd=source, capture=True).decode().strip() == pin["commit"]
        assert run("git", "rev-parse", "HEAD^{tree}", cwd=source, capture=True).decode().strip() == pin["tree"]
        archive = run("git", "archive", "HEAD", cwd=source, capture=True)
        assert hashlib.sha256(archive).hexdigest() == pin["archive_sha256"], "upstream archive checksum mismatch"
        assert digest(source / "src-tauri/Cargo.lock") == pin["cargo_lock_sha256"]
        run("git", "apply", "--check", str(patch), cwd=source)
        run("git", "apply", str(patch), cwd=source)
        cargo_args = ("--locked", "--no-default-features", "--features", "cli")
        rust = source / "src-tauri"
        run("cargo", "test", *cargo_args, "--lib", "cli::accounts::tests", cwd=rust)
        run("cargo", "test", *cargo_args, "--lib", "services::emails::spam::tests", cwd=rust)
        run("cargo", "test", *cargo_args, "--lib", "ai::json_shape::tests", cwd=rust)
        run("cargo", "test", *cargo_args, "--lib", "services::tasks::extractor::", cwd=rust)
        run("cargo", "build", *cargo_args, "--config", "profile.dev.debug-assertions=false",
            "--bin", "emailops-cli", cwd=rust)
        output.mkdir(parents=True, exist_ok=True)
        binary = output / "emailops-cli"
        target = Path(os.environ.get("CARGO_TARGET_DIR", rust / "target"))
        shutil.copy2(target / "debug/emailops-cli", binary)
        run("strip", "--strip-debug", str(binary))
        binary.chmod(0o755)
        manifest = {
            "schema": "lifeos_emailops_build_v1",
            "debug_assertions": False,
            "credential_backend": "native_keyring",
            "platform_commit": run("git", "rev-parse", "HEAD", cwd=ROOT, capture=True).decode().strip(),
            "source_commit": pin["commit"],
            "source_archive_sha256": pin["archive_sha256"],
            "patch_sha256": pin["patch_sha256"],
            "binary_sha256": digest(binary),
            "rustc": run("rustc", "--version", capture=True).decode().strip(),
        }
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("EMAILOPS_BUILD=PASS")


if __name__ == "__main__":
    main()
