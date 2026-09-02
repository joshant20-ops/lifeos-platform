#!/usr/bin/env python3
import pathlib
import re
import sys
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE_ROOT = ROOT / "ansible" / "desired" / "compose"


def classify(image: str | None, build_present: bool) -> str:
    if build_present and not image:
        return "LOCAL_BUILD"
    if not image:
        return "NO_IMAGE"
    if "@sha256:" in image:
        return "DIGEST_PINNED"
    # Registry ports complicate naive colon splitting; tag is only after final slash.
    tail = image.rsplit("/", 1)[-1]
    if ":" not in tail:
        return "UNTAGGED_LATEST"
    tag = tail.rsplit(":", 1)[-1]
    if tag == "latest":
        return "LATEST"
    # Stable semver-like exact tag, allowing v-prefix and suffixes.
    if re.fullmatch(r"v?\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9._-]+)?", tag):
        return "VERSION_PINNED"
    # Major-only / moving channels / named branches / distro channels.
    return "FLOATING_TAG"


def recommendation(kind: str) -> str:
    return {
        "DIGEST_PINNED": "KEEP",
        "VERSION_PINNED": "KEEP",
        "LOCAL_BUILD": "REVIEW_BUILD_REPRODUCIBILITY",
        "LATEST": "PIN_CANDIDATE",
        "UNTAGGED_LATEST": "PIN_CANDIDATE",
        "FLOATING_TAG": "REVIEW_PINNING",
        "NO_IMAGE": "REVIEW",
    }[kind]


def main() -> int:
    if not COMPOSE_ROOT.is_dir():
        print(f"ERROR=compose_root_missing path={COMPOSE_ROOT}")
        return 2

    rows = []
    for path in sorted([*COMPOSE_ROOT.rglob("*.yml"), *COMPOSE_ROOT.rglob("*.yaml")]):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            continue
        services = data.get("services") or {}
        if not isinstance(services, dict):
            continue
        project = path.parent.name
        for service, cfg in sorted(services.items()):
            cfg = cfg or {}
            if not isinstance(cfg, dict):
                continue
            image = cfg.get("image")
            build_present = "build" in cfg
            kind = classify(str(image) if image is not None else None, build_present)
            rows.append((project, service, str(image or "-"), kind, recommendation(kind), str(path.relative_to(ROOT))))

    if not rows:
        print("ERROR=no_services_found")
        return 3

    widths = [
        max(len(h), max(len(r[i]) for r in rows))
        for i, h in enumerate(("PROJECT", "SERVICE", "IMAGE", "CLASS", "RECOMMENDATION", "FILE"))
    ]
    headers = ("PROJECT", "SERVICE", "IMAGE", "CLASS", "RECOMMENDATION", "FILE")
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * widths[i] for i in range(len(widths))))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(row))))

    counts = {}
    for row in rows:
        counts[row[3]] = counts.get(row[3], 0) + 1

    print()
    print("IMAGE_TAG_AUDIT=PASS")
    print(f"SERVICES={len(rows)}")
    for key in sorted(counts):
        print(f"{key}={counts[key]}")
    print(f"PIN_CANDIDATES={sum(1 for r in rows if r[4] == 'PIN_CANDIDATE')}")
    print(f"REVIEW_CANDIDATES={sum(1 for r in rows if r[4].startswith('REVIEW'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
