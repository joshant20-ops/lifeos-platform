import unittest

from governor.mqtt_churn_audit import classify_packets, classify_records


class MqttChurnAuditTests(unittest.TestCase):
    def test_separates_socket_and_mqtt_connect_lines(self):
        raw = (b"10: New connection from 172.21.0.1:123 on port 1883.\n"
               b"10: New client connected from 172.21.0.1:123 as private-client.\n"
               b"10: Client private-client disconnected.\n"
               b"11: Outgoing messages are being dropped for client secret.\n")
        self.assertEqual(classify_records(raw, {b"172.21.0.1"}), {
            "socket_connections": 1, "gateway_socket_connections": 1,
            "mqtt_connected": 1, "mqtt_disconnected": 1, "outgoing_drop_warnings": 1,
        })

    def test_packet_sources_are_redacted_and_duplicates_collapse(self):
        packet = b"lo In IP 192.168.0.4.1234 > 192.168.0.5.1883: Flags [S]\n"
        gateway = b"br Out IP 172.21.0.1.1234 > 172.21.0.2.1883: Flags [S]\n"
        self.assertEqual(classify_packets(packet * 2 + gateway, {b"172.21.0.1"}, {}),
                         {"other_private_source": 1, "docker_gateway": 1})
