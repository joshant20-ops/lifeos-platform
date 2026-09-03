#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
SEMAPHORE_BASE=${SEMAPHORE_BASE:-http://192.168.0.203:3000/api}
DISPATCHER=/home/joshan/automation/queues/lifeos_engineer_dispatcher.py
MAINT=/home/joshan/automation/queues/lifeos_engineer_maintenance.py

fail(){ echo "ERROR: $*" >&2; exit 1; }

cd "$PLATFORM"
echo 'SEMAPHORE_DISPATCHER_CAPABILITY_PROOF_VERSION=3'
echo 'MUTATIONS=SEMAPHORE_CATALOGUE_AND_NON_DESTRUCTIVE_PROOF_TASK_HISTORY_ONLY'
echo "PLATFORM_HEAD=$(git rev-parse HEAD)"

for p in "$DISPATCHER" "$MAINT"; do [[ -f "$p" ]] || fail "missing legacy capability source: $p"; done
[[ "$(systemctl is-active lifeos-engineer-dispatcher.timer 2>/dev/null || true)" == inactive ]] || fail 'legacy dispatcher timer must remain inactive'

curl -fsS "$SEMAPHORE_BASE/ping" >/dev/null || curl -fsS "${SEMAPHORE_BASE%/api}/api/ping" >/dev/null || fail 'Semaphore API unavailable'

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

BEFORE_STATUS=$(git status --porcelain)
BEFORE_HEAD=$(git rev-parse HEAD)

cat >"$TMP/canary.yml" <<'YAML'
- name: LifeOS Semaphore autonomy canary proof
  hosts: localhost
  gather_facts: false
  connection: local
  tasks:
    - name: Fixed canary execution
      ansible.builtin.command:
        argv:
          - /usr/bin/python3
          - -c
          - >-
            import json,platform,socket;
            print(json.dumps({'kind':'autonomy_canary','host':socket.gethostname(),'machine':platform.machine(),'python':platform.python_version()},sort_keys=True))
      changed_when: false
      register: canary
    - name: Emit canary proof marker
      ansible.builtin.debug:
        msg: "SEMAPHORE_AUTONOMY_CANARY=PASS {{ canary.stdout }}"
YAML

cat >"$TMP/maintenance.yml" <<'YAML'
- name: LifeOS Semaphore self-maintenance proof
  hosts: localhost
  gather_facts: false
  connection: local
  tasks:
    - name: Repository status read-only
      ansible.builtin.command:
        argv: [/usr/bin/git, -c, safe.directory=/workspace/lifeos-platform, -C, /workspace/lifeos-platform, status, --short]
      changed_when: false
      register: status
    - name: Repository branch read-only
      ansible.builtin.command:
        argv: [/usr/bin/git, -c, safe.directory=/workspace/lifeos-platform, -C, /workspace/lifeos-platform, branch, --show-current]
      changed_when: false
      register: branch
    - name: Repository fsck read-only
      ansible.builtin.command:
        argv: [/usr/bin/git, -c, safe.directory=/workspace/lifeos-platform, -C, /workspace/lifeos-platform, fsck, --no-progress]
      changed_when: false
      register: fsck
    - name: Verify platform mount is read-only
      ansible.builtin.shell: |
        probe=/workspace/lifeos-platform/.semaphore-maintenance-write-probe
        err=$(mktemp)
        if : >"$probe" 2>"$err"; then
          rm -f "$probe" "$err"
          echo writable
          exit 9
        fi
        rc=$?
        if grep -Eqi 'read-only file system|permission denied' "$err"; then
          rm -f "$err"
          echo readonly
          exit 0
        fi
        cat "$err" >&2
        rm -f "$err"
        exit "$rc"
      args:
        executable: /bin/sh
      changed_when: false
      register: ro
    - name: Emit self-maintenance proof marker
      ansible.builtin.debug:
        msg: "SEMAPHORE_ENGINEER_SELF_MAINTENANCE=PASS branch={{ branch.stdout | trim }} mount={{ ro.stdout | trim }} status_bytes={{ status.stdout | length }} fsck_rc={{ fsck.rc }}"
YAML

RUNTIME=/var/lib/lifeos-semaphore-shadow/input/dispatcher-capability-proof
install -d -o root -g root -m 0755 "$RUNTIME"
install -o root -g root -m 0644 "$TMP/canary.yml" "$RUNTIME/canary.yml"
install -o root -g root -m 0644 "$TMP/maintenance.yml" "$RUNTIME/maintenance.yml"

CONTAINER=lifeos-semaphore-shadow-semaphore-1
MOUNT=/runtime/lifeos-shadow/input/dispatcher-capability-proof

ANSIBLE_PLAYBOOK=$(docker exec "$CONTAINER" sh -lc '
  if command -v ansible-playbook >/dev/null 2>&1; then
    command -v ansible-playbook
    exit 0
  fi
  for p in /opt/semaphore/apps/ansible/*/venv/bin/ansible-playbook; do
    if [ -x "$p" ]; then printf "%s\n" "$p"; exit 0; fi
  done
  exit 1
') || fail 'Semaphore managed ansible-playbook not found'
[[ -n "$ANSIBLE_PLAYBOOK" ]] || fail 'Semaphore managed ansible-playbook path empty'
echo "SEMAPHORE_ANSIBLE_PLAYBOOK=$ANSIBLE_PLAYBOOK"

docker exec "$CONTAINER" "$ANSIBLE_PLAYBOOK" -i localhost, "$MOUNT/canary.yml" | tee "$TMP/canary.out"
grep -q 'SEMAPHORE_AUTONOMY_CANARY=PASS' "$TMP/canary.out" || fail 'autonomy canary marker absent'

docker exec "$CONTAINER" "$ANSIBLE_PLAYBOOK" -i localhost, "$MOUNT/maintenance.yml" | tee "$TMP/maintenance.out"
grep -q 'SEMAPHORE_ENGINEER_SELF_MAINTENANCE=PASS' "$TMP/maintenance.out" || fail 'self-maintenance marker absent'

AFTER_STATUS=$(git status --porcelain)
AFTER_HEAD=$(git rev-parse HEAD)
[[ "$AFTER_HEAD" == "$BEFORE_HEAD" ]] || fail 'platform HEAD changed during proof'
[[ "$AFTER_STATUS" == "$BEFORE_STATUS" ]] || fail 'platform worktree changed during proof'
[[ "$(systemctl is-active lifeos-engineer-dispatcher.timer 2>/dev/null || true)" == inactive ]] || fail 'legacy dispatcher timer changed state'

echo
echo 'RESULT=PASS'
echo 'SEMAPHORE_AUTONOMY_CANARY=PASS'
echo 'SEMAPHORE_ENGINEER_SELF_MAINTENANCE=PASS'
echo 'LEGACY_DISPATCHER_TIMER_CHANGED=NO'
echo 'PLATFORM_MUTATION=NONE'
echo 'GITHUB_MUTATION=NONE'
echo 'NEXT_ACTION=create_gated_dispatcher_file_retirement_after_template_catalogue_is_committed'
