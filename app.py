import os
import sys
import logging
import mqtt
import json
import fasteners
from flask import Flask, request
from loguru import logger
from mergedeep import merge


# Set variables from env
DEBUG = bool(int(os.getenv("DEBUG", False)))
LISTEN_PORT = int(os.getenv("LISTEN_PORT", 8000))
PRECISION = int(os.getenv("PRECISION", 2))
SEND_HA_DISCOVERY_CONFIG = bool(int(os.getenv("SEND_HA_DISCOVERY_CONFIG", True)))  # (default) If we should send a message to a discovery topic when a new client connects
HA_DISCOVERY_PREFIX = os.getenv("HA_DISCOVERY_PREFIX", "homeassistant")
HA_BIRTH_TOPIC = os.getenv("HA_BIRTH_TOPIC", "homeassistant/status")  # We watch this topic for HA coming online. When it does, we wipe the known_sensors dict so we'll re-send sensor config messages
HA_BIRTH_TOPIC_ONLINE = os.getenv("HA_BIRTH_TOPIC_ONLINE", "online")

MAC_NAME_MAPPING = os.getenv("MAC_NAME_MAPPING", None)  # A comma separated list of mac addresses and their name. Ex: 00:00:00:00:00:00/Weather Station
MQTT_TOPIC_JSON = os.getenv("MQTT_TOPIC_JSON", "sensor")  # What topic should we publish on?

KNOWN_SENSORS_CACHE_FILE = os.getenv("KNOWN_SENSORS_CACHE_FILE", "known_sensors.json")
KNOWN_SENSORS_LOCK_FILE = os.getenv("KNOWN_SENSORS_LOCK_FILE", "known_sensors.lock")


# Logging
log_level = "INFO"
if DEBUG:
    log_level = "DEBUG"

logger.remove()
logger.add(sys.stderr, level=log_level)


# Intercept standard logging library messages:
# https://github.com/Delgan/loguru#entirely-compatible-with-standard-logging
class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Get corresponding Loguru level if it exists.
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message.
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


# Main logic
if os.path.isfile(KNOWN_SENSORS_CACHE_FILE):
    logger.info("Clearing previous KNOWN_SENSORS_CACHE_FILE")
    os.remove(KNOWN_SENSORS_CACHE_FILE)

if os.path.isfile(KNOWN_SENSORS_LOCK_FILE):
    logger.info("Clearing previous KNOWN_SENSORS_LOCK_FILE")
    os.remove(KNOWN_SENSORS_LOCK_FILE)

# As Flask can spawn multiple processes, we need a way to keep the known_sensors known among all threads/processes. As such, I've opted for file locking for now
known_sensors_lock = fasteners.InterProcessLock(KNOWN_SENSORS_LOCK_FILE)
app = Flask(__name__)
mac_names = {}

# Translate the env-set mapping to a dict
if MAC_NAME_MAPPING is not None:
    for mapping in MAC_NAME_MAPPING.split(","):
        mac, name = mapping.split("/")
        mac_names[mac] = name


def __rounded(value):
    """
    Takes a float and returns it rounded to PRECISION
    """
    return round(float(value), PRECISION)


def __convert_battery_to_str(value):
    """
    Converts the battery int value to a human recognizable string
    """
    if int(value) == 1:
        value = "Normal"
    elif int(value) == 0:
        value = "Low"
    else:
        value = "Unknown"
    return value


def __convert_in_to_mm(value):
    """
    Converts inches to mm
    """
    return float(value) * 25.4


def __convert_f_to_c(value):
    """
    Converts farenheit to celcius
    """
    return (float(value) - 32) * 5 / 9


def __convert_inhg_to_hpa(value):
    """
    Converts inHg to hPa
    """
    return float(value) * 33.86389


def __convert_mph_to_kph(value):
    """
    Converts MPH to KPH
    """
    return float(value) * 1.609344


def __convert_mph_to_mps(value):
    """
    Converts MPH to m/s
    """
    return float(value) * 0.44704


def __convert_mph_to_fps(value):
    """
    Converts MPH to ft/s
    """
    return float(value) * 1.466667


def __convert_mph_to_knots(value):
    """
    Converts MPH to knots
    """
    return float(value) * 0.868976


def __convert_wm2_to_lux(value):
    """
    Convert W/m^2 to lux (See https://ambientweather.com/faqs/question/view/id/1452/.)
    """
    return float(value) * 126.7


def __create_dict(elements, value):
    """
    Creates a dictionary from a given list of elements
    """
    result = dict()
    if len(elements) > 1:
        result[elements[0]] = __create_dict(elements[1:], value)
    else:
        result[elements[0]] = value
    return result


def __translate_topic_to_dict(data, key, value):
    """
    Takes an json path (ex: rain.total.mm) and adds it into a dict (ex: dict["rain"]["total"]["mm"])
    :param data: the dict to update
    :param key: the MQTT topic key (ex: rain/total/mm)
    :param value: the value to save to the dict (ex: 12)
    """
    single_dict = __create_dict(key.split("."), value)
    return merge(data, single_dict)


def send_ha_sensor_config(send_config, mac, stationtype, sensorname, uniqueid, value_template, unit_of_measurement=None, device_class=None, icon=None, state_class=None):
    """
    Sends the configuration of the sensor to HA if we haven't already
    :param mac: MAC address of the device
    :param stationtype: Station Type of the device (usually pulled from request params)
    :param sensorname: The name of the sensor as it should show in Home Assistant (ex: "Outdoor Temperature")
    :param uniqueid: The unique ID to suffix behind mac
    :param value_template: The lookup string for HA to parse the value from json (ex: "{{ value_json.temperature.outdoor.celsius }}")
    :param unit_of_measurement: The Unit of Measurement (ex: °C)
    :param device_class: HA device class
    :param icon: Icon to use (to override device class)
    :param state_class: HA state class
    """

    if bool(send_config) is not True:
        return

    if mac is None:
        logger.debug("Not sending sensor config as mac is None")
        return

    # The topic can't handle colons. As such, we use hyphens instead
    # Reference: https://www.home-assistant.io/docs/mqtt/discovery/
    mac_sanitized = mac.replace(':', '-')
    sensor_unique_id = "{mac_sanitized}_{uniqueid_sanitized}".format(mac_sanitized=mac_sanitized, uniqueid_sanitized=uniqueid.replace(".", "-"))

    if is_known_sensor(sensor_unique_id):
        logger.debug("Already sent config for {sensor} to HA. Skipping".format(sensor=sensor_unique_id))
        return

    # If we're here, we have to send the device config to HA
    discovery_topic = "{prefix}/sensor/{sensor_unique_id}/config".format(prefix=HA_DISCOVERY_PREFIX, sensor_unique_id=sensor_unique_id)

    devicename = ""
    if mac in mac_names:
        devicename = mac_names[mac]

    config_payload = {
        "name": sensorname,  # Outdoor Temperatre
        "object_id": "{devicename} - {sensorname}".format(devicename=devicename, sensorname=sensorname),
        "unique_id": sensor_unique_id,
        "state_topic": "{prefix}/{mac}/sensor".format(prefix=mqtt.MQTT_PREFIX, mac=mac_sanitized),
        "value_template": value_template,
        "device": {
            "connections": [["mac", mac]],
            "identifiers": [stationtype],
            "manufacturer": "Ambient Weather",
            "name": devicename
        },
        "availability": [
            {"topic": "{prefix}/online".format(prefix=mqtt.MQTT_PREFIX)}
        ],
        "payload_available": "online",
        "payload_not_available": "offline"
    }

    if unit_of_measurement is not None:
        config_payload["unit_of_measurement"] = unit_of_measurement

    if device_class is not None:
        config_payload["device_class"] = device_class

    if icon is not None:
        config_payload["icon"] = icon

    if state_class is not None:
        config_payload["state_class"] = state_class

    logger.info("Sending {sensorname} config to discovery topic for MAC: {mac}".format(sensorname=sensorname, mac=mac_sanitized))
    mqtt.publish(discovery_topic, json.dumps(config_payload), insert_prefix=False)
    add_known_sensor(sensor_unique_id)
    logger.debug("Done sending {sensorname} config to HA".format(sensorname=sensorname))


def generate_sensor_dict(args, send_ha_config=False):
    """
    Generates a dict containing each value provided
    """

    logger.info("Generating a single dict containing each value provided...")
    logger.debug("send_ha_config: {send_ha_config}".format(send_ha_config=send_ha_config))

    data_dict = {}
    mac = None
    stationtype = "UNKNOWN"

    # Parse MAC and type separately as we want these pre-set before we wend HA configs
    if "mac" in args:
        mac = args["mac"]
        __translate_topic_to_dict(data_dict, "station.mac", str(mac))
    elif "PASSKEY" in args:
        mac = args["PASSKEY"]
        __translate_topic_to_dict(data_dict, "station.mac", str(mac))
    if "stationtype" in args:
        stationtype = args["stationtype"]
        __translate_topic_to_dict(data_dict, "station.type", str(stationtype))

    # Process each arg. If known, lets's process it
    for key, value in args.items():
        logger.debug("Processing argument {key}:{value}".format(key=key, value=value))

        # TODO - make an elegant definition for these. For now, hack it together with if statements

        if key == "stationtype":
            pass  # This was set previously outside of the loop
        elif key == "PASSKEY" or key == "mac":
            pass  # This was set previously outside of the loop
        elif key == "battout":
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Outdoor Battery", "station.battery.outdoor", "{{ value_json.station.battery.outdoor }}", device_class="battery", icon="mdi:battery")
            __translate_topic_to_dict(data_dict, "station.battery.outdoor", __convert_battery_to_str(value))
        elif key == "batt_co2":
            send_ha_sensor_config(send_ha_config, mac, stationtype, "CO2 Battery", "station.battery.co2", "{{ value_json.station.battery.co2 }}", device_class="battery", icon="mdi:battery")
            __translate_topic_to_dict(data_dict, "station.battery.co2", __convert_battery_to_str(value))
        elif key == "humidityin":
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Indoor Humidity", "humidity.indoor.percentage", "{{ value_json.humidity.indoor.percentage }}", unit_of_measurement="%", device_class="humidity")
            __translate_topic_to_dict(data_dict, "humidity.indoor.percentage", int(value))
        elif key == "humidity":
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Outdoor Humidity", "humidity.outdoor.percentage", "{{ value_json.humidity.outdoor.percentage }}", unit_of_measurement="%", device_class="humidity")
            __translate_topic_to_dict(data_dict, "humidity.outdoor.percentage", int(value))
        elif key == "tempinf":
            # Only send once as HA supports conversion (https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes)
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Indoor Temperature", "temperature.indoor.celsius", "{{ value_json.temperature.indoor.celsius }}", unit_of_measurement="°C", device_class="temperature")
            __translate_topic_to_dict(data_dict, "temperature.indoor.fahrenheit", __rounded(float(value)))
            __translate_topic_to_dict(data_dict, "temperature.indoor.celsius", __rounded(__convert_f_to_c(value)))  # Convert F to C
        elif key == "tempf":
            # Only send once as HA supports conversion (https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes)
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Outdoor Temperature", "temperature.outdoor.celsius", "{{ value_json.temperature.outdoor.celsius }}", unit_of_measurement="°C", device_class="temperature")
            __translate_topic_to_dict(data_dict, "temperature.outdoor.fahrenheit", __rounded(float(value)))
            __translate_topic_to_dict(data_dict, "temperature.outdoor.celsius", __rounded(__convert_f_to_c(value)))  # Convert F to C
        elif key == "baromrelin":
            # Only send once as HA supports conversion (https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes)
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Relative Pressure", "pressure.relative.mmhg", "{{ value_json.pressure.relative.mmhg }}", unit_of_measurement="mmHg", device_class="pressure")
            __translate_topic_to_dict(data_dict, "pressure.relative.inhg", __rounded(float(value)))
            __translate_topic_to_dict(data_dict, "pressure.relative.mmhg", __rounded(__convert_in_to_mm(value)))  # Convert inHg to mmHg
            __translate_topic_to_dict(data_dict, "pressure.relative.hpa", __rounded(__convert_inhg_to_hpa(value)))  # Convert inHg to hPa
        elif key == "baromabsin":
            # Only send once as HA supports conversion (https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes)
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Absolute Pressure", "pressure.absolute.mmhg", "{{ value_json.pressure.absolute.mmhg }}", unit_of_measurement="mmHg", device_class="pressure")
            __translate_topic_to_dict(data_dict, "pressure.absolute.inhg", __rounded(float(value)))
            __translate_topic_to_dict(data_dict, "pressure.absolute.mmhg", __rounded(__convert_in_to_mm(value)))  # Convert inHg to mmHg
            __translate_topic_to_dict(data_dict, "pressure.absolute.hpa", __rounded(__convert_inhg_to_hpa(value)))  # Convert inHg to hPa
        elif key == "winddir":
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Direction", "wind.direction.degrees", "{{ value_json.wind.direction.degrees }}", unit_of_measurement="°", icon="mdi:compass")
            __translate_topic_to_dict(data_dict, "wind.direction.degrees", int(value))
        elif key == "windspeedmph":
            # HA doesnt support conversion natively in the entity UI. As such, we send multiple and users can choose
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Speed (mph)", "wind.speed.mph", "{{ value_json.wind.speed.mph }}", unit_of_measurement="mph", icon="mdi:weather-windy")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Speed (kph)", "wind.speed.kph", "{{ value_json.wind.speed.kph }}", unit_of_measurement="kph", icon="mdi:weather-windy")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Speed (m/s)", "wind.speed.mps", "{{ value_json.wind.speed.mps }}", unit_of_measurement="m/s", icon="mdi:weather-windy")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Speed (ft/s)", "wind.speed.ftps", "{{ value_json.wind.speed.ftps }}", unit_of_measurement="ft/s", icon="mdi:weather-windy")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Speed (knots)", "wind.speed.knots", "{{ value_json.wind.speed.knots }}", unit_of_measurement="knots", icon="mdi:weather-windy")
            __translate_topic_to_dict(data_dict, "wind.speed.mph", __rounded(float(value)))
            __translate_topic_to_dict(data_dict, "wind.speed.kph", __rounded(__convert_mph_to_kph(value)))  # Convert mph to kph
            __translate_topic_to_dict(data_dict, "wind.speed.mps", __rounded(__convert_mph_to_mps(value)))  # Convert mph to m/s
            __translate_topic_to_dict(data_dict, "wind.speed.ftps", __rounded(__convert_mph_to_fps(value)))  # Convert mph to ft/s
            __translate_topic_to_dict(data_dict, "wind.speed.knots", __rounded(__convert_mph_to_knots(value)))  # Convert mph to knots
        elif key == "windgustmph":
            # HA doesnt support conversion natively in the entity UI. As such, we send multiple and users can choose
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Gust (mph)", "wind.gust.mph", "{{ value_json.wind.gust.mph }}", unit_of_measurement="mph", icon="mdi:weather-windy")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Gust (kph)", "wind.gust.kph", "{{ value_json.wind.gust.kph }}", unit_of_measurement="kph", icon="mdi:weather-windy")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Gust (m/s)", "wind.gust.mps", "{{ value_json.wind.gust.mps }}", unit_of_measurement="m/s", icon="mdi:weather-windy")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Gust (ft/s)", "wind.gust.ftps", "{{ value_json.wind.gust.ftps }}", unit_of_measurement="ft/s", icon="mdi:weather-windy")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Gust (knots)", "wind.gust.knots", "{{ value_json.wind.gust.knots }}", unit_of_measurement="knots", icon="mdi:weather-windy")
            __translate_topic_to_dict(data_dict, "wind.gust.mph", __rounded(float(value)))
            __translate_topic_to_dict(data_dict, "wind.gust.kph", __rounded(__convert_mph_to_kph(value)))  # Convert mph to kph
            __translate_topic_to_dict(data_dict, "wind.gust.mps", __rounded(__convert_mph_to_mps(value)))  # Convert mph to m/s
            __translate_topic_to_dict(data_dict, "wind.gust.ftps", __rounded(__convert_mph_to_fps(value)))  # Convert mph to ft/s
            __translate_topic_to_dict(data_dict, "wind.gust.knots", __rounded(__convert_mph_to_knots(value)))  # Convert mph to knots
        elif key == "maxdailygust":
            # HA doesnt support conversion natively in the entity UI. As such, we send multiple and users can choose
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Max. Daily Gust (mph)", "wind.daily.gust.mph", "{{ value_json.wind.daily.gust.mph }}", unit_of_measurement="mph", icon="mdi:weather-windy")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Max. Daily Gust (kph)", "wind.daily.gust.kph", "{{ value_json.wind.daily.gust.kph }}", unit_of_measurement="kph", icon="mdi:weather-windy")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Max. Daily Gust (m/s)", "wind.daily.gust.mps", "{{ value_json.wind.daily.gust.mps }}", unit_of_measurement="m/s", icon="mdi:weather-windy")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Max. Daily Gust (ft/s)", "wind.daily.gust.ftps", "{{ value_json.wind.daily.gust.ftps }}", unit_of_measurement="ft/s", icon="mdi:weather-windy")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Wind Max. Daily Gust (knots)", "wind.daily.gust.knots", "{{ value_json.wind.daily.gust.knots }}", unit_of_measurement="knots", icon="mdi:weather-windy")
            __translate_topic_to_dict(data_dict, "wind.daily.gust.mph", __rounded(float(value)))
            __translate_topic_to_dict(data_dict, "wind.daily.gust.kph", __rounded(__convert_mph_to_kph(value)))  # Convert mph to kph
            __translate_topic_to_dict(data_dict, "wind.daily.gust.mps", __rounded(__convert_mph_to_mps(value)))  # Convert mph to m/s
            __translate_topic_to_dict(data_dict, "wind.daily.gust.ftps", __rounded(__convert_mph_to_fps(value)))  # Convert mph to ft/s
            __translate_topic_to_dict(data_dict, "wind.daily.gust.knots", __rounded(__convert_mph_to_knots(value)))  # Convert mph to knots
        elif key == "hourlyrainin":
            # HA doesnt support conversion natively in the entity UI. As such, we send multiple and users can choose
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Hourly Rain (in)", "rain.hourly.in", "{{ value_json.rain.hourly.in }}", unit_of_measurement="in", icon="mdi:water")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Hourly Rain (mm)", "rain.hourly.mm", "{{ value_json.rain.hourly.mm }}", unit_of_measurement="mm", icon="mdi:water")
            __translate_topic_to_dict(data_dict, "rain.hourly.in", __rounded(float(value)))
            __translate_topic_to_dict(data_dict, "rain.hourly.mm", __rounded(__convert_in_to_mm(value)))  # Convert inches to mm
        elif key == "eventrainin":
            # HA doesnt support conversion natively in the entity UI. As such, we send multiple and users can choose
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Event Rain (in)", "rain.event.in", "{{ value_json.rain.event.in }}", unit_of_measurement="in", icon="mdi:water")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Event Rain (mm)", "rain.event.mm", "{{ value_json.rain.event.mm }}", unit_of_measurement="mm", icon="mdi:water")
            __translate_topic_to_dict(data_dict, "rain.event.in", __rounded(float(value)))
            __translate_topic_to_dict(data_dict, "rain.event.mm", __rounded(__convert_in_to_mm(value)))  # Convert inches to mm
        elif key == "dailyrainin":
            # HA doesnt support conversion natively in the entity UI. As such, we send multiple and users can choose
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Daily Rain (in)", "rain.daily.in", "{{ value_json.rain.daily.in }}", unit_of_measurement="in", icon="mdi:water")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Daily Rain (mm)", "rain.daily.mm", "{{ value_json.rain.daily.mm }}", unit_of_measurement="mm", icon="mdi:water")
            __translate_topic_to_dict(data_dict, "rain.daily.in", __rounded(float(value)))
            __translate_topic_to_dict(data_dict, "rain.daily.mm", __rounded(__convert_in_to_mm(value)))  # Convert inches to mm
        elif key == "weeklyrainin":
            # HA doesnt support conversion natively in the entity UI. As such, we send multiple and users can choose
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Weekly Rain (in)", "rain.weekly.in", "{{ value_json.rain.weekly.in }}", unit_of_measurement="in", icon="mdi:water")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Weekly Rain (mm)", "rain.weekly.mm", "{{ value_json.rain.weekly.mm }}", unit_of_measurement="mm", icon="mdi:water")
            __translate_topic_to_dict(data_dict, "rain.weekly.in", __rounded(float(value)))
            __translate_topic_to_dict(data_dict, "rain.weekly.mm", __rounded(__convert_in_to_mm(value)))  # Convert inches to mm
        elif key == "monthlyrainin":
            # HA doesnt support conversion natively in the entity UI. As such, we send multiple and users can choose
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Monthly Rain (in)", "rain.monthly.in", "{{ value_json.rain.monthly.in }}", unit_of_measurement="in", icon="mdi:water")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Monthly Rain (mm)", "rain.monthly.mm", "{{ value_json.rain.monthly.mm }}", unit_of_measurement="mm", icon="mdi:water")
            __translate_topic_to_dict(data_dict, "rain.monthly.in", __rounded(float(value)))
            __translate_topic_to_dict(data_dict, "rain.monthly.mm", __rounded(__convert_in_to_mm(value)))  # Convert inches to mm
        elif key == "totalrainin":
            # HA doesnt support conversion natively in the entity UI. As such, we send multiple and users can choose
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Total Rain (in)", "rain.total.in", "{{ value_json.rain.total.in }}", unit_of_measurement="in", icon="mdi:water", state_class="total")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Total Rain (mm)", "rain.total.mm", "{{ value_json.rain.total.mm }}", unit_of_measurement="mm", icon="mdi:water", state_class="total")
            __translate_topic_to_dict(data_dict, "rain.total.in", __rounded(float(value)))
            __translate_topic_to_dict(data_dict, "rain.total.mm", __rounded(__convert_in_to_mm(value)))  # Convert inches to mm
        elif key == "solarradiation":
            # HA doesnt support conversion natively in the entity UI. As such, we send multiple and users can choose
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Solar Radiation (W/m²)", "solarradiation.wm2", "{{ value_json.solarradiation.wm2 }}", unit_of_measurement="W/m²", icon="mdi:white-balance-sunny")
            send_ha_sensor_config(send_ha_config, mac, stationtype, "Solar Radiation (lux)", "solarradiation.lux", "{{ value_json.solarradiation.lux }}", unit_of_measurement="lux", icon="mdi:white-balance-sunny")
            __translate_topic_to_dict(data_dict, "solarradiation.wm2", __rounded(float(value)))
            __translate_topic_to_dict(data_dict, "solarradiation.lux", __rounded(__convert_wm2_to_lux(value)))  # Convert W/m^2 to lux (See https://ambientweather.com/faqs/question/view/id/1452/.)
        elif key == "uv":
            send_ha_sensor_config(send_ha_config, mac, stationtype, "UV Index", "uv.index", "{{ value_json.uv.index }}", unit_of_measurement="Index", icon="mdi:white-balance-sunny")
            __translate_topic_to_dict(data_dict, "uv.index", int(value))

    logger.info("Done generating dict")
    return data_dict


def __read_known_sensors_cache_file():
    """
    Reads the known_sensors dict from the cache file
    """
    __create_known_sensors_cache_file()
    with open(KNOWN_SENSORS_CACHE_FILE, 'r') as f:
        known_sensors = json.load(f)
    return known_sensors


def __write_known_sensors_cache_file(known_sensors):
    """
    Writes the known_sensors dict to the cache file
    """
    with open(KNOWN_SENSORS_CACHE_FILE, 'w') as f:
        json.dump(known_sensors, f)


def __create_known_sensors_cache_file():
    """
    Initializes the KNOWN_SENSORS_CACHE_FILE if it doesn't exist
    """
    if os.path.isfile(KNOWN_SENSORS_CACHE_FILE):
        logger.debug("known sensors cache file already exists")
        return
    # We need to create the dict file
    known_sensors = {}
    __write_known_sensors_cache_file(known_sensors)


def clear_known_sensors():
    """
    Clears out the known sensors dict so the config will be sent to Home Assistant next message
    """
    global known_sensors_lock
    logger.info("Clearing out known sensors")
    with known_sensors_lock:
        known_sensors = __read_known_sensors_cache_file()
        known_sensors.clear()
        __write_known_sensors_cache_file(known_sensors)


def add_known_sensor(sensor_id):
    """
    Adds a known sensor to the global dict
    """
    global known_sensors_lock
    with known_sensors_lock:
        known_sensors = __read_known_sensors_cache_file()
        known_sensors[sensor_id] = True
        __write_known_sensors_cache_file(known_sensors)


def is_known_sensor(sensor_id):
    global known_sensors_lock
    with known_sensors_lock:
        known_sensors = __read_known_sensors_cache_file()
        if sensor_id in known_sensors and known_sensors[sensor_id] is True:
            return True
    return False


# Data receiver
@app.route("/ambientweather", methods=['GET'])
def receive():
    """
    Flask endpoint for listening for requests from the local Ambient Weather weather station
    Reference: https://ambientweather.com/faqs/question/view/id/1857/
    """
    logger.debug("Received request")
    logger.debug(request.args)

    json_payload = generate_sensor_dict(request.args, send_ha_config=SEND_HA_DISCOVERY_CONFIG)

    mac_sanitized = json_payload["station"]["mac"].replace(':', '-')
    mqtt.publish("{mac}/{topic}".format(mac=mac_sanitized, topic=MQTT_TOPIC_JSON), json.dumps(json_payload))

    return "OK"


# Healthcheck
@app.route("/health", methods=['GET'])
def health():
    """
    Flask endpoint for returning status 200
    """
    return "OK"


# Entrypoint
def main():
    logger.info("Starting ambient-weather-to-mqtt server")
    logger.debug("Debug is enabled")
    mqtt.connect()

    if bool(SEND_HA_DISCOVERY_CONFIG):
        logger.info("Subscribing to HA Birth topic: {topic}".format(topic=HA_BIRTH_TOPIC))
        mqtt.subscribe(HA_BIRTH_TOPIC)
    app.run(host='0.0.0.0', port=LISTEN_PORT)


if __name__ == '__main__':
    main()
