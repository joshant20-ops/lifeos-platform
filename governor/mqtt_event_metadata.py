"""Extract observed MQTT endpoints and GMT times from existing broker log text."""
from datetime import datetime, timezone
import re

STAMP = re.compile(rb"^(\d{1,12}):\s+")
SOCKET = re.compile(r"^New connection from (\S+) on port (\d+)\.")
CONNECT = re.compile(r"^New client connected from (\S+) as (.+?) \(p\d+,")
DISCONNECT = re.compile(r"^Client (.+?) \[(\S+)\] disconnected(?:[:.]|$)")
PUBLISH = re.compile(
    r"^(Received PUBLISH from|Sending PUBLISH to) (.+?) "
    r"\(d\d+, q\d+, r\d+, m\d+, '(.*?)', \.\.\. "
)
DROPPED = re.compile(r"^Outgoing messages are being dropped for client (.+?)\.?$")


def observed_time(raw):
    match = STAMP.match(raw)
    if not match:
        return None
    try:
        return datetime.fromtimestamp(int(match[1]), timezone.utc).strftime("%Y-%m-%d %H:%M:%S GMT")
    except (ValueError, OSError, OverflowError):
        return None


def event_metadata(raw):
    """A null field means the line does not establish that fact."""
    match = STAMP.match(raw)
    message = raw[match.end():] if match else raw
    # Do not send the raw log line, even for an unrecognised event.
    text = message.decode("utf-8", "replace").strip()
    event = {"time_gmt": observed_time(raw), "source": None, "destination": None,
             "topic": None, "event": "unclassified"}
    if match := SOCKET.match(text):
        event.update(event="socket_connection", source={"observed_peer": match[1]},
                     destination={"broker_listener_port": int(match[2])})
    elif match := CONNECT.match(text):
        event.update(event="mqtt_connected", source={"observed_peer": match[1], "client_id": match[2]},
                     destination={"role": "broker"})
    elif match := DISCONNECT.match(text):
        event.update(event="mqtt_disconnected", source={"observed_peer": match[2], "client_id": match[1]},
                     destination={"role": "broker"})
    elif match := PUBLISH.match(text):
        event["topic"] = match[3]
        if match[1] == "Received PUBLISH from":
            event.update(event="publish_received", source={"client_id": match[2]},
                         destination={"role": "broker"})
        else:
            event.update(event="publish_sent", source={"role": "broker"},
                         destination={"client_id": match[2]})
    elif match := DROPPED.match(text):
        event.update(event="outgoing_drop_warning", source={"role": "broker"},
                     destination={"client_id": match[1]})
    return event
