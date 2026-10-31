# Phone access and offline listening

The fixed private address is https://audiobooks.lan on home Wi-Fi or the existing
VPN with home DNS. The proxy permits private client addresses only, validates
the upstream application, supports WebSockets and leaves ha.lan/vaultwarden.lan
routes unchanged. No router port forwarding is added.

If the existing Vaultwarden local CA is available for issuance, reuse it only
after proving it verifies the existing Vaultwarden certificate. Otherwise the
Pi generates a dedicated local CA and an audiobooks.lan server certificate. The
CA private key remains root-private on the Pi, outside public source snapshots.
Only that new generic public CA certificate may be exported for a secure phone
download. Do not export an existing personal CA or any private key. The server
certificate is issued for one year; future renewal must use the same reviewed
local boundary before expiry.

On Android, install the supplied public CA certificate through Settings' CA
certificate installation, then connect the Audiobookshelf app to the HTTPS
address. The upstream Android network security configuration supports user and
system CAs. Phone certificate trust still requires observation on the phone;
server-side TLS validation does not prove Android trust.

The initial administrator username is lifeos-admin. Retrieve its generated
password only from the Pi terminal using:

    sudo cat /mnt/docker-data/audiobookshelf/initial-admin.json

Do not paste that output into ChatGPT or GitHub. Change the password in the
application after signing in, and create a non-admin listening account.

Download a book in the Android app while connected at home. Before relying on
it away from home, enable airplane mode and check that a downloaded chapter
plays and seeking works; reconnect and confirm listening progress syncs. Remove
only the phone download when finished to retain the server copy.

## Backup evidence scope

The separate fixed backup operation creates a consistent initial encrypted
Restic snapshot with only the audiobook container stopped, then decrypts and
compares the actual SQLite databases and installation manifest before restarting
that container. It includes the data directory in the existing nightly backup
helper only after those checks pass. This proves the initial checkpoint and
scheduled dataset inclusion; later live nightly copies retain the existing
backup system's consistency limitations and are not represented as quiesced
SQLite snapshots. No books or phone playback are verified merely by installation.
