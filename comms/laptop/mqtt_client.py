import ssl
import json
import paho.mqtt.client as mqtt
from constants import BROKER_HOST, PORT_TLS, TRANSPORT_TLS, CA_CERTS_PATH


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

    def _log(self, level, msg):
        if self.logger:
            getattr(self.logger, level)(msg)
        else:
            print(msg)

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self._log("info", f"[{self.client_id}] Connected to {self.host}:{self.port} - {rc}")

        for topic, qos in self._pending_subscriptions:
            self.client.subscribe(topic, qos=qos)
            self._log("info", f"[{self.client_id}] Subscribed to {topic} (QoS {qos})")

    def _on_disconnect(self, client, userdata, disconnect_flags, rc, properties=None):
        self._log("warning", f"[{self.client_id}] Disconnected from {self.host}:{self.port} - {rc}")

    def _on_message(self, client, userdata, msg): 
        self._log("debug", f"[{self.client_id}] {msg.topic}: {msg.payload.decode()}")
        if msg.topic in self._message_callbacks:
            self._message_callbacks[msg.topic](msg)

    def subscribe(self, topic: str, callback=None, qos: int = 0):
        self.client.subscribe(topic, qos=qos)
        if callback:
            self._message_callbacks[topic] = callback
            self._log("info", f"[{self.client_id}] Subscribed to {topic} (Qos {qos})")
        self._pending_subscriptions.append((topic, qos))

    def publish(self, topic: str, payload: dict, qos: int = 0):
        payload_str = json.dumps(payload)
        self.client.publish(topic, payload_str, qos=qos)
        self._log("debug", f"[{self.client_id}] Published to {topic}: {payload_str}")

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
        self.client.disconnect()