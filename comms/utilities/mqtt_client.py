# Shared MQTT transport for laptop and Ultra96: TLS, background reconnect,
# subscription restoration, live publishing, and optional latency echoes.
import json
import ssl
import time
import uuid
import paho.mqtt.client as mqtt
from .logger_setup import format_packet_for_log
from .constants import (BROKER_HOST, PORT_TLS, TRANSPORT_TLS, CA_CERTS_PATH,
                       TOPIC_SENSOR, TOPIC_RESULTS, TOPIC_HAPTICS,
                       TOPIC_LATENCY_REQUEST, TOPIC_LATENCY_RESPONSE)


class MQTTClientWrapper: 
    """
    Reuseable MQTT client wrapper supporting both TLS (plain) and WSS transports, 
    selected via the `transport` argument.
    """

    def __init__(
            self,
            client_id: str,
            host: str = BROKER_HOST,
            port: int = PORT_TLS,
            transport: str = TRANSPORT_TLS, 
            ca_certs: str = CA_CERTS_PATH,
            username: str = None,
            password: str = None,
            lwt_topic: str = None,
            lwt_payload: str = None,
            logger=None
    ): 
        self.client_id = client_id
        self.host = host
        self.port = port
        self.logger = logger

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            transport=transport,
            protocol=mqtt.MQTTv311
        )

        # TLS layer added separately
        self.client.tls_set(
            ca_certs=ca_certs, 
            tls_version=ssl.PROTOCOL_TLS_CLIENT
        )

        if username and password:
            self.client.username_pw_set(username, password)

        if lwt_topic and lwt_payload:
            self.client.will_set(lwt_topic, payload=lwt_payload, qos=1, retain=False)

        
        self.client.reconnect_delay_set(min_delay=1, max_delay=15)
        self.client.max_queued_messages_set(100)
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        self._message_callbacks = {}  # topic -> callback function
        self._pending_subscriptions = {}  # topic -> QoS, restored on every connect
        self._latency_device = None
        self._latency_targets = ()
        self._latency_session = uuid.uuid4().hex

    def _log(self, level, msg, device=None):
        if self.logger:
            extra = {"device": device} if device else {}
            getattr(self.logger, level)(msg, extra=extra)
        else:
            print(msg)

    def _on_connect_fail(self, client, userdata):
        self._log("warning", f"MQTT broker unavailable at {self.host}:{self.port}; retrying (backoff up to 15s)")

    # Subscribe again after every successful connection, including reconnects.
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc != 0:
            self._log("warning", f"MQTT connection rejected: {rc}; retrying")
            return
        self._log("info", f"Connected to {self.host}:{self.port} - {rc}")
        for topic, qos in list(self._pending_subscriptions.items()):
            self.client.subscribe(topic, qos=qos)

    def _on_disconnect(self, client, userdata, disconnect_flags, rc, properties=None):
        self._log("info" if rc == 0 else "warning", f"Disconnected from {self.host}:{self.port} - {rc}")

    def _on_message(self, client, userdata, msg): 
        # Source follows this application's topic contract, not words in JSON.
        source = {
            TOPIC_SENSOR: "laptop",
            TOPIC_RESULTS: "ultra96", TOPIC_HAPTICS: "ultra96",
        }.get(msg.topic)

        self._log("debug", f"[MQTT -> {self.client_id.upper()}] {msg.topic}: "
                  f"{format_packet_for_log(msg.payload)}", device=source)
        
        if msg.topic in self._message_callbacks:
            self._message_callbacks[msg.topic](msg)

    def subscribe(self, topic: str, callback=None, qos: int = 0):
        if callback:
            self._message_callbacks[topic] = callback
        self._pending_subscriptions[topic] = qos
        if self.client.is_connected():
            self.client.subscribe(topic, qos=qos)
        self._log("info", f"Registered subscription to {topic} (QoS {qos})")

    def publish(self, topic: str, payload: dict, qos: int = 0):
        # Live sensor data/results/commands should not accumulate while offline.
        if not self.client.is_connected():
            return False
        info = self.client.publish(topic, json.dumps(payload), qos=qos)
        if info.rc == mqtt.MQTT_ERR_SUCCESS:
            self._log("debug", f"[MQTT TX] {topic}: {format_packet_for_log(payload)}")
            return True
        return False

    def connect(self):
        # The network loop performs the initial attempt and retries in its thread.
        self.client.connect_async(self.host, self.port)

    def loop_forever(self):
        self.connect()
        self.client.loop_forever(retry_first_connection=True)

    def loop_start(self):
        self.connect()
        self.client.loop_start()

    def loop_stop(self):
        self.disconnect()
        self.client.loop_stop()

    def disconnect(self):
        self.client.disconnect()

    def enable_latency(self, device, targets=()):
        """Echo probes, optionally measuring round trips to peers via the broker."""
        self._latency_device = device
        self._latency_targets = targets
        self.subscribe(TOPIC_LATENCY_REQUEST.format(device=device), self._on_latency_request)
        if targets:
            self.subscribe(TOPIC_LATENCY_RESPONSE.format(device=device), self._on_latency_response)

    def _on_latency_request(self, msg):
        try:
            probe = json.loads(msg.payload.decode())
            if (not isinstance(probe, dict) or not isinstance(probe.get("id"), str)
                    or probe.get("origin") not in ("laptop", "ultra96", "phone")
                    or probe.get("target") != self._latency_device):
                return
        except (ValueError, UnicodeDecodeError):
            return
        self.publish(TOPIC_LATENCY_RESPONSE.format(device=probe["origin"]), probe)

    # sent_ns originated in this process and was echoed unchanged. Never
    # subtract a remote device timestamp to calculate this round-trip time.
    def _on_latency_response(self, msg):
        """Echoed timestamps use this process's clock; no remote clock sync needed."""
        try:
            probe = json.loads(msg.payload.decode())
            if (not isinstance(probe, dict) or probe.get("id") != self._latency_session
                    or probe.get("origin") != self._latency_device
                    or probe.get("target") not in self._latency_targets
                    or type(probe.get("sent_ns")) is not int):
                return
            elapsed_ns = time.monotonic_ns() - probe["sent_ns"]
            if elapsed_ns < 0:
                return
        except (ValueError, UnicodeDecodeError):
            return
        target = probe["target"]
        route = "broker loopback" if target == self._latency_device else f"{target} via broker"
        self._log("debug", f"[LATENCY] {self._latency_device} <-> {route}: RTT={elapsed_ns / 1e6:.2f}ms")

    def send_latency_probes(self):
        """Fire-and-forget timestamp echoes; missing replies produce no RTT line."""
        if not self.client.is_connected():
            return
        for target in self._latency_targets:
            self.publish(TOPIC_LATENCY_REQUEST.format(device=target), {
                "id": self._latency_session, "origin": self._latency_device,
                "target": target, "sent_ns": time.monotonic_ns(),
            })
