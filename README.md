# ambient-weather-to-mqtt

Small application to listen locally for events from an Ambient Weather station and forward them to MQTT

I'm sure there are other (read: better) solutions out there for this but I (a) wanted to build something myself and (b) the one project I did look at only did imperial measurements - I want my rain in mm!

## Install / Run the container

### Docker

TODO

### Kubernetes

TODO



## Configure the Weather Station
TODO
* The trailing questionmark is a must!

## Environment Variables

| Environment Varaible                                 | Description                                                                                                                         | Required              | Expected Values                                             |
|------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------|-----------------------|-------------------------------------------------------------|
| `MQTT_HOST`                                          | The MQTT Hostname/IP address                                                                                                        | True                  | string                                                      |
| `MQTT_PORT`                                          | The MQTT Port                                                                                                                       | True                  | int                                                         |
| `MQTT_USERNAME`                                      | If the MQTT server requires authentication, this is the username to use for auth.                                                   | False                 | string (default: None)                                      |
| `MQTT_PASSWORD`                                      | If the MQTT server requires authentication, this is the password to use for auth.                                                   | False                 | string (default: None)                                      |
| `MQTT_KEEPALIVE_SEC`                                 | MQTT Keepalive value (in seconds)                                                                                                   | False                 | int (default: `60`)                                         |
| `MQTT_PREFIX`                                        | The prefix to use in MQTT topics                                                                                                    | False                 | string (default: `ambientweather`)                          |
| `MQTT_CLIENT_ID`                                     | The Client ID to use when connecting to MQTT                                                                                        | False                 | string (default: `ambientweather`)                          |
| `MAC_NAME_MAPPING`                                   | A comma separated list of mac addresses and their name. Ex: `00:00:00:00:00:00/Weather Station`. Used to name the device in HA.     | False                 | string (default: None)                                      |
| `DEBUG`                                              | Whether to enable DEBUG logging                                                                                                     | False                 | `0` (normal logging) or `1` (debug logging) (default: `0`)  |
| `LISTEN_PORT`                                        | Port to listen on in the container                                                                                                  | False                 | int (default: `8000`)                                       |
| `PRECISION`                                          | Number of decimal places to round floats to when reporting over MQTT                                                                | False                 | int (default: `2`)                                          |
| `SEND_HA_DISCOVERY_CONFIG`                           | Whether we should send a message to a discovery topic when a new client connects                                                    | False                 | `0` (don't send config) or `1` (send config) (default: `1`) |
| `HA_DISCOVERY_PREFIX`                                | The prefix that Home Assistant listens on for auto discovering sensors                                                              | False                 | string (default: `homeassistant`)                           |
| `HA_BIRTH_TOPIC`                                     | The MQTT topic that Home Assistant notifies when HA comes online or goes offline                                                    | False                 | string (default: `homeassistant/status`)                    |
| `HA_BIRTH_TOPIC_ONLINE`                              | The value that's sent to `HA_BIRTH_TOPIC` when Home Assistant comes online                                                          | False                 | string (default: `online`)                                  |

## Build

To build the container, simply build the docker image: `docker build -t ambient-weather-to-mqtt .`

## Resources

The Ambient Weather spec is defined here: https://ambientweather.com/faqs/question/view/id/1857/

## Known Issues
* Development server - not gunicorn


# TODO:
* Add Dockerfile
* Lint
* Github CI - publish to docker
* Document poss. env vars