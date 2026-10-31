# LifeOS Audiobooks

Audiobookshelf is the maintained player and library; no custom player or AI
narration service is needed. First acceptance: a human-narrated audiobook plays
on Android, remembers its position after closing the app, and survives a server
restart. Modern DRM-free purchases and free human-narrated classics share the
same library. Library loans remain in their provider app. This service does not
supply Audible's catalogue or convert Kindle Unlimited loans.

## Current state

SERVER_PRIVATE_ACCESS_AND_INITIAL_BACKUP_VERIFIED. Private DNS, strict TLS
hostname/chain, initialized backend, unauthorized API rejection, unchanged
HA/Vaultwarden routes and baseline containers passed in runtime run41193852311.
The encrypted initial backup, actual SQLite/manifest decryption comparison,
audiobook restart and scheduled dataset inclusion passed in run41193910338
at 2026-10-31 10:43:48 GMT, after certificate creation.

Overall task: BLOCKED_USER_ACTION_REQUIRED for Android CA installation and
private first login. No books have been added, and actual phone/offline playback
and progress synchronization remain unverified. PHONE.md has the device steps.
The new generic public CA certificate was supplied separately in ChatGPT;
private keys and the administrator password remain on the Pi.

New app state lives at /mnt/docker-data/audiobookshelf, outside public source
snapshot roots. The original failed /opt/stacks/audiobookshelf state is preserved.
Initial install and routing refusals were diagnosed and recovered through reviewed
changes; their resolved attempts do not constitute current outstanding work.

The existing nightly backup now includes the dataset. Only the initial checkpoint
is proven quiesced and restored; later live-copy consistency limits are explicit
in PHONE.md.

The first-install transaction resolves and records an immutable image digest,
checks ARM64, initializes a random-password admin on a dedicated bootstrap
bridge (separate from the shared proxy), then attaches the initialized service to reverse_proxy. Credentials
remain in root-only `/mnt/docker-data/audiobookshelf/initial-admin.json`; never
copy that file to GitHub or include it in logs. Retrieve the password locally
and change it after login. The installer refuses existing audiobook state
rather than upgrading or overwriting it. The recovery path accepts only the
exact root-owned uninitialized bootstrap definition and its existing immutable
image digest; completed or credential-bearing state is refused for review.

Version 2.37.2 was verified against the upstream latest release on 2026-10-31 GMT.
The first-install operation resolves the version tag to an immutable registry
digest and verifies the pulled image is linux/arm64 before starting it. Do not substitute `latest`.

## Installation contract for the reviewed Pi executor

Follow repository AGENTS.md, Watchman and existing broker boundaries. There is
a fixed `install-audiobooks` operation in the deployment allowlist. This folder
is deliberately outside the active Ansible inventory: merging source must not
silently modify running services. Do not invoke Docker through an arbitrary
workflow or expand a privileged gateway without its separate review.

Before activation, establish the current storage migration state and confirm
/opt/stacks resolves to the intended mounted SSD, Docker is healthy, no related
job is in flight, TCP 13378 is unused, and reverse_proxy exists. Record existing
container health and verify local persistent storage has sufficient capacity.
Do not restart Docker or any existing service to install this application.

The approved installer must create only /mnt/docker-data/audiobookshelf and its
config, metadata and audiobooks children, resolve the image digest, validate
Compose, then start only project lifeos-audiobooks. Bootstrap uses an ordinary dedicated
bridge with loopback-only publication: an internal-only Docker network can lose
published port bindings on affected Docker versions. See
https://github.com/moby/moby/discussions/53256. Bind mounts deliberately
refuse automatic directory creation, avoiding accidental data on an unmounted
storage path. Confirm the image architecture and effective write permissions;
no UID/GID or host ownership is assumed by this candidate.

The HTTP port is loopback-only. The installer creates the admin account before
joining the proxy network. Retrieve its password locally using your normal
privileged access, then enter it directly in the application; never put
credentials or account tokens in GitHub or logs.
Then configure Nginx Proxy Manager to proxy a private HTTPS hostname to
lifeos-audiobooks:80 on reverse_proxy, with WebSocket support enabled. Restrict
access to LAN/VPN using the existing network policy. Do not create a public
router port forward. The configured private hostname is audiobooks.lan; PHONE.md documents its local
certificate trust and the private-only proxy policy.

## Books and phone

Create an Audiobooks library pointing to /audiobooks. Store each title as:

    audiobooks/Author/Book title/01 - Chapter.mp3
    audiobooks/Author/Book title/02 - Chapter.mp3

M4B books can be stored as a single file in the title folder. Download a
human-narrated classic from https://librivox.org/ after checking availability
and public-domain status for the UK, extract locally, and scan the library.
Listen to a narrator sample before downloading the full book. Modern titles
must be acquired as licensed DRM-free audio from a source permitting downloads.
No automated downloader, account integration or DRM removal is included.

Connect a compatible Android Audiobookshelf client to the private HTTPS URL
and sign in with a separate non-admin listening account. Test play/pause,
seeking, speed, sleep timer and reconnecting. For remote listening use the
existing VPN; test an offline download and resumption as a separate acceptance
step. Do not infer successful playback from HTTP health alone.

## Verification and evidence

Run verify.py on the Pi through the reviewed diagnostic boundary. It checks
only the fixed loopback endpoint, with no credentials or private book names.
Require AUDIOBOOKS_HTTP=PASS and AUDIOBOOKS_PING=PASS, plus an executor report
that verifies the intended image digest, SSD-backed mounts, private proxy HTTPS,
unauthenticated API rejection, authenticated chapter streaming and saved
progress after reconnecting and restarting only this project. Confirm all
previously running services remain healthy. Record GMT times, commit and image
digest, but never tokens, passwords, private URLs or listening history in public
evidence. Browser/phone acceptance remains outstanding until observed.

## Backup and rollback

Back up config, metadata and audiobook files together, encrypted and outside
this stack. Stop only this project for a consistent initial filesystem backup;
protect any embedded application backup because it contains private state.
Verify restoration in an isolated instance before relying on it.

On failure, recent container logs are saved only in root-private startup.log
before removing the project; those logs must not be copied to public evidence.
For a failed first installation, remove its private proxy route and stop/remove
only project lifeos-audiobooks. Preserve all three data directories for diagnosis.
Never use `down -v` or remove existing backups. Before upgrades, record the prior
image digest and take a consistent full backup. A database migration may prevent
image-only rollback: restore the matching config/metadata snapshot with the
previous image, retaining the failed state separately. Runtime activation and
rollback need the approved fixed operation; this folder grants no execution
permission.

Upstream: https://github.com/advplyr/audiobookshelf
Compose reference: https://github.com/advplyr/audiobookshelf/blob/master/docker-compose.yml
Release: https://github.com/advplyr/audiobookshelf/releases/tag/v2.37.2
