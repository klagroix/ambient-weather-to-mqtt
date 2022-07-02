import os
import sys
import paho.mqtt.client as mqtt
from loguru import logger
from app import HA_BIRTH_TOPIC, HA_BIRTH_TOPIC_ONLINE, SEND_HA_DISCOVERY_CONFIG

# Env vars
MQTT_HOST = os.getenv("MQTT_HOST", None)
MQTT_PORT = int(os.getenv("MQTT_PORT", 0))

MQTT_USERNAME = os.getenv("MQTT_USERNAME", None)
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", None)
MQTT_KEEPALIVE_SEC = int(os.getenv("MQTT_KEEPALIVE_SEC", 60))
MQTT_PREFIX = os.getenv("MQTT_PREFIX", "ambientweather")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "ambientweather")

# Topics...
MQTT_TOPIC_ONLINE = os.getenv("MQTT_TOPIC_ONLINE", "online")

# Required var validation
if MQTT_HOST is None or MQTT_HOST == "":
    logger.error("No MQTT_HOST provided")
    sys.exit(1)
if MQTT_PORT == 0:
    logger.error("No MQTT_PORT provided")
    sys.exit(1)


# The global mqtt client
mqtt_client = None


# The callback for when the client receives a CONNACK response from the server.
def __on_connect(client, userdata, flags, rc):
    logger.info("Connected with result code {rc}".format(rc=str(rc)))

    if rc == 0:
        # Set as retain so anyone wondering if the device is online or not knows regardles of whether they were listening at the time
        publish(MQTT_TOPIC_ONLINE, "online", retain=True)

    # We subscribe during the on_connect callback to be more resilient to connect/disconnects
    if bool(SEND_HA_DISCOVERY_CONFIG):
        logger.info("Subscribing to HA Birth topic: {topic}".format(topic=HA_BIRTH_TOPIC))
        subscribe(HA_BIRTH_TOPIC)


# The callback when we receive a message
def __on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode("utf-8")
    logger.debug("Received message on topic: {topic} with payload: {payload}".format(topic=topic, payload=payload))

    if topic == HA_BIRTH_TOPIC:
        logger.debug("Received HA_BIRTH_TOPIC message")
        if payload == HA_BIRTH_TOPIC_ONLINE:
            logger.info("We have a home assistant online message, we're clearing out known sensors")
            from app import clear_known_sensors
            clear_known_sensors()


# Connect to the MQTT server
def connect():
    """
    Connect to the MQTT server
    """
    logger.debug("Attempting to connect to the MQTT server {host}:{port}".format(host=MQTT_HOST, port=MQTT_PORT))
    global mqtt_client
    mqtt_client = mqtt.Client(client_id=MQTT_CLIENT_ID)
    mqtt_client.will_set("{prefix}/{topic}".format(prefix=MQTT_PREFIX, topic=MQTT_TOPIC_ONLINE), "offline", retain=True)
    mqtt_client.on_connect = __on_connect
    mqtt_client.on_message = __on_message

    if MQTT_USERNAME is not None or MQTT_PASSWORD is not None:
        logger.debug("Using auth ({user}:****)".format(user=MQTT_USERNAME))
        mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    mqtt_client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE_SEC)
    mqtt_client.loop_start()

    logger.debug("Done")
    return mqtt_client


def publish(topic, payload, insert_prefix=True, retain=False):
    global mqtt_client

    if mqtt_client is None:
        logger.error("Can't publish message as mqtt client is not established")
        return False, "No mqtt client established"

    if insert_prefix:
        topic = "{prefix}/{topic}".format(prefix=MQTT_PREFIX, topic=topic)

    logger.info("Publishing message to {topic} (payload: {payload})".format(topic=topic, payload=payload))
    mqtt_client.publish(topic, payload, retain=retain)


def subscribe(topic):
    global mqtt_client

    if mqtt_client is None:
        logger.error("Can't subscribe to topic as mqtt client is not established")
        return False, "No mqtt client established"

    logger.info("Subscribing to topic {topic}".format(topic=topic))

    mqtt_client.subscribe(topic)
