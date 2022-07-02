# ambient-weather-to-mqtt

Small application to listen locally for events from an Ambient Weather station and forward them to MQTT

This has only been tested with the 'Ambient Weather WS-2902C' Weather Station. Other stations may have other sensors. Feel free to file an issue with an example log (it should show the request parameters)

I'm sure there are other (read: better) solutions out there for this but I (a) wanted to build something myself and (b) the one project I did look at only did imperial measurements - I want my rain in mm!

## How it works

Once the container is [running](#running) and the weather station is [configured](#configure-the-weather-station), The weather station sends a request to ambient-weather-to-mqtt periodically. On a new request, ambient-weather-to-mqtt will send a MQTT messages to Home Asistant notifying it of all the available sensors. Every subsequent request, ambient-weather-to-mqtt sends a json payload containing all the sensor data to MQTT. Home Assistant will parse this into individual sensor data.    
If you're not using Home Assistant or don't want the device/sensors to show automaitcally, set the `SEND_HA_DISCOVERY_CONFIG` environment variable to `0`.

For many sensors, Home Asistant supports selecting the unit type:    
![Home Assistant entity with multiple units](https://github.com/klagroix/ambient-weather-to-mqtt/blob/main/docs/ha-unit-select.png?raw=true)

Unfortuntely for others, there is no unit type selection for things like speed (kph/mph) and volume (mm/in):    
![Home Assistant entity with no unit selection](https://github.com/klagroix/ambient-weather-to-mqtt/blob/main/docs/ha-no-unit-select.png?raw=true)

To combat this, ambient-weather-to-mqtt creates a multiple sensors for measurements that Home Assistant can't automatically convert:    
![Home Assistant multiple entities for different units](https://github.com/klagroix/ambient-weather-to-mqtt/blob/main/docs/ha-multiple-entities-units.png?raw=true)


<details>
  <summary>Example Home Assistant Device</summary>

  ![Home Assistant example device](https://github.com/klagroix/ambient-weather-to-mqtt/blob/main/docs/ha-example-device.png?raw=true)
</details>

## Running

Currently the only supported way of running ambient-weather-to-mqtt is in a Docker container. For your convenience, a container image is auto-published to [lagroix/ambient-weather-to-mqtt](https://hub.docker.com/repository/docker/lagroix/ambient-weather-to-mqtt) on Docker Hub.

### Prerequisites

1. You must have [MQTT](https://www.home-assistant.io/integrations/mqtt/) installed and running
2. You must have a way of running docker containers
3. You must have an Ambient Weather weather station (tested with WS-2902C)

### Docker

The following command can be used to run the docker container locally. Update the environment variables to suit your environment. A full list of environment variables can be seen below.

```shell
docker run --rm \
 --name=test-ambient-weather \
 -p 80:8000 \
 -e MQTT_HOST=192.168.1.x \
 -e MQTT_PORT=1883 \
 -e MQTT_USERNAME=yyyyyyyyyyyyyy \
 -e MQTT_PASSWORD=xxxxxxxxxxxxxx \
 -e MAC_NAME_MAPPING="00:00:00:00:00:00/Backyard Weather Station" \
 lagroix/ambient-weather-to-mqtt:latest
```

### Kubernetes

<details>
  <summary>Example Kubernetes configuration</summary>

  **NOTES:**
  * Don't put your secret unencrypted in code. The Secret should be created by other means (manually, Bitnami Sealed Secrets, etc)
  * Change the ConfigMap variables to suit your environment
  
  ```
  apiVersion: v1
  kind: ConfigMap
  metadata:
    creationTimestamp: null
    name: ambient-weather-to-mqtt-env
  data:
    MQTT_HOST: "192.168.1.1"
    MQTT_PORT: "1883"
    MAC_NAME_MAPPING: "00:00:00:00:00:00/Backyard Weather Station"
  ---
  apiVersion: v1
  data:
    MQTT_PASSWORD: ZXhhbXBsZXBhc3M=
    MQTT_USERNAME: ZXhhbXBsZXVzZXI=
  kind: Secret
  metadata:
    creationTimestamp: null
    name: ambient-weather-to-mqtt-secret
  ---
  apiVersion: apps/v1
  kind: Deployment
  metadata:
    name: ambient-weather-to-mqtt
  spec:
    replicas: 1
    revisionHistoryLimit: 3
    selector:
      matchLabels:
        name: ambient-weather-to-mqtt
    template:
      metadata:
        labels:
          name: ambient-weather-to-mqtt
      spec:
        containers:
        - name: ambient-weather-to-mqtt
          image: lagroix/ambient-weather-to-mqtt:latest
          imagePullPolicy: Always
          livenessProbe:
            failureThreshold: 10
            httpGet:
              httpHeaders:
              - name: Accept
                value: text/plain
              path: /health
              port: http
            initialDelaySeconds: 30
            periodSeconds: 60
            successThreshold: 1
            timeoutSeconds: 1
          envFrom:
          - configMapRef:
              name: ambient-weather-to-mqtt-env
          - secretRef:
              name: ambient-weather-to-mqtt-secret
          ports:
          - containerPort: 8000
            name: http
            protocol: TCP
          resources:
            limits:
              cpu: "1"
              memory: 128Mi
            requests:
              cpu: "1"
              memory: 64Mi
  ---
  apiVersion: v1
  kind: Service
  metadata:
    name: ambient-weather-to-mqtt
  spec:
    type: NodePort
    ports:
      - name: http
        port: 80
        targetPort: http
    selector:
      name: ambient-weather-to-mqtt
  ---
  apiVersion: networking.k8s.io/v1
  kind: Ingress
  metadata:
    name: ambient-weather-to-mqtt-ingress
    annotations:
      nginx.ingress.kubernetes.io/ssl-redirect: "false"
  spec:
    tls:
    - hosts:
      - ambient-weather-to-mqtt.example.com
      secretName: ambient-weather-to-mqtt-ingress-tls
    rules:
      - host: ambient-weather-to-mqtt.example.com
        http:
          paths:
            - path: /
              pathType: ImplementationSpecific
              backend:
                service:
                  name: ambient-weather-to-mqtt
                  port:
                    name: http
  ```
</details>


## Configure the Weather Station

To configure your weather station to send to ambient-weather-to-mqtt, open the awnet app and set the customized config as follows:    
![awnet configuration](https://github.com/klagroix/ambient-weather-to-mqtt/blob/main/docs/awnet-config.png?raw=true)

**NOTE:** The trailing questionmark is required! If you don't include it, ambient-weather-to-mqtt won't work. 

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

## Future items
* Stop using the flask development server (i.e. use something like Gunicorn)
