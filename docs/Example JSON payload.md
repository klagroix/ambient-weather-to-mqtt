# ambient-weather-to-mqtt - Example MQTT payload

The following is sent to the `ambientweather/00-00-00-00-00-00/sensor` topic (where `00-00-00-00-00-00` is the MAC address if your device).    
If `SEND_HA_DISCOVERY_CONFIG` is enabled, the sensors parse the JSON payload to create each sensor (See [Sensors.md](Sensors.md)).

```json
{
    "station": {
        "mac": "00:00:00:00:00:00",
        "type": "AMBWeatherV4.3.3",
        "battery": {
            "outdoor": "Normal",
            "co2": "Normal"
        }
    },
    "temperature": {
        "indoor": {
            "fahrenheit": 68.5,
            "celsius": 20.28
        },
        "outdoor": {
            "fahrenheit": 55.8,
            "celsius": 13.22
        },
        "dewpoint": {
            "fahrenheit": 33.8,
            "celsius": 12.6
        },
        "feelslike": {
            "fahrenheit": 55.8,
            "celsius": 13.22
        }
    },
    "humidity": {
        "indoor": {
            "percentage": 61
        },
        "outdoor": {
            "percentage": 96
        }
    },
    "pressure": {
        "relative": {
            "inhg": 29.74,
            "mmhg": 755.47,
            "hpa": 1007.21
        },
        "absolute": {
            "inhg": 29.84,
            "mmhg": 757.81,
            "hpa": 1010.33
        }
    },
    "wind": {
        "direction": {
            "degrees": 127
        },
        "speed": {
            "mph": 0.0,
            "kph": 0.0,
            "mps": 0.0,
            "ftps": 0.0,
            "knots": 0.0
        },
        "gust": {
            "mph": 0.0,
            "kph": 0.0,
            "mps": 0.0,
            "ftps": 0.0,
            "knots": 0.0
        },
        "daily": {
            "gust": {
                "mph": 6.9,
                "kph": 11.1,
                "mps": 3.08,
                "ftps": 10.12,
                "knots": 6.0
            }
        }
    },
    "rain": {
        "hourlyrate": {
            "inh": 0.0,
            "mmh": 0.0
        },
        "currentstatus": "Not Raining",
        "event": {
            "in": 0.32,
            "mm": 8.2
        },
        "daily": {
            "in": 0.32,
            "mm": 8.2
        },
        "weekly": {
            "in": 0.32,
            "mm": 8.2
        },
        "monthly": {
            "in": 0.32,
            "mm": 8.2
        },
        "total": {
            "in": 0.68,
            "mm": 17.3
        }
    },
    "solarradiation": {
        "wm2": 2.97,
        "lux": 376.3
    },
    "uv": {
        "index": 0
    }
}

```