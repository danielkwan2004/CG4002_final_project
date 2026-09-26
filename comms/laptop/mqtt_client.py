import ssl
import json
import paho.mqtt.client as mqtt
from constants import (BROKER_HOST, PORT_TLS, TRANSPORT_TLS, CA_CERTS_PATH,
                       TOPIC_SENSOR, TOPIC_RELAY, TOPIC_RESULTS, TOPIC_HAPTICS)


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

        
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        self._message_callbacks = {}  # topic -> callback function
        self._pending_subscriptions = [] # (topic, qos) tuples to subscribe once connected

    def _log(self, level, msg, device=None):
        if self.logger:
            extra = {"device": device} if device else {}
            getattr(self.logger, level)(msg, extra=extra)
        else:
            print(msg)

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self._log("info", f"Connected to {self.host}:{self.port} - {rc}")

        for topic, qos in self._pending_subscriptions:
            self.client.subscribe(topic, qos=qos)

    def _on_disconnect(self, client, userdata, disconnect_flags, rc, properties=None):
        self._log("info" if rc == 0 else "warning", f"Disconnected from {self.host}:{self.port} - {rc}")

    def _on_message(self, client, userdata, msg): 
        # Source follows this application's topic contract, not words in JSON.
        source = {
            TOPIC_SENSOR: "laptop", TOPIC_RELAY: "laptop",
            TOPIC_RESULTS: "ultra96", TOPIC_HAPTICS: "ultra96",
        }.get(msg.topic)

        self._log("debug", f"[MQTT -> {self.client_id.upper()}] {msg.topic}: "
                  f"{msg.payload.decode(errors='replace')}", device=source)
        
        if msg.topic in self._message_callbacks:
            self._message_callbacks[msg.topic](msg)

    def subscribe(self, topic: str, callback=None, qos: int = 0):
        self.client.subscribe(topic, qos=qos)
        if callback:
            self._message_callbacks[topic] = callback
            self._log("info", f"Subscribed to {topic} (Qos {qos})")
        self._pending_subscriptions.append((topic, qos))

    def publish(self, topic: str, payload: dict, qos: int = 0):
        payload_str = json.dumps(payload)
        self.client.publish(topic, payload_str, qos=qos)
        self._log("debug", f"Published to {topic}: {payload_str}")

    def connect(self):
        self.client.connect(self.host, self.port)

    def loop_forever(self):
        self.connect()
        self.client.loop_forever()

    def loop_start(self):
        self.connect()
        self.client.loop_start()

    def loop_stop(self):
        self.client.loop_stop()
        self.disconnect()

    def disconnect(self):
        self.client.disconnect()
