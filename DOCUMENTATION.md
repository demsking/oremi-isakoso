## Oremi Iṣakoso

**Oremi Iṣakoso** is an MCP server for smart home control. It exposes
Zigbee2MQTT devices through the Model Context Protocol (MCP), enabling AI
assistants and autonomous agents to discover, monitor, and control connected
devices using a standardized interface.

Built with FastAPI and designed to run in Docker, Oremi Iṣakoso provides
secure, reliable, and real-time access to lights, switches, sensors, plugs,
thermostats, and other Zigbee devices without requiring agents to interact
directly with Zigbee2MQTT.

The name **Oremi Iṣakoso** comes from the Yoruba language. _Oremi_ means
_"my friend"_, reflecting the project's goal of building a helpful and
trustworthy AI ecosystem. _Iṣakoso_ means _"control"_ or _"management"_,
representing the service's responsibility for managing and controlling smart
home devices through a unified MCP interface.

Project repository: https://gitlab.com/demsking/oremi-isakoso

![Oremi Iṣakoso Logo](./static/logo.png)

## Core Capabilities

- Expose Zigbee2MQTT devices through the Model Context Protocol (MCP).
- Discover and inspect connected smart home devices.
- Read the current state and attributes of supported devices.
- Control lights, switches, plugs, locks, covers, and other actuators.
- Retrieve sensor measurements, including temperature, humidity, power,
  occupancy, and more.
- Execute device-specific actions through a unified interface.
- Automatically reflect changes reported by Zigbee2MQTT.
- Provide a consistent API regardless of the underlying Zigbee device.
- Support AI assistants and autonomous agents with structured MCP tools.
- Secure access to smart home devices using configurable authentication.
- Run as a lightweight Docker container with simple deployment.
- Integrate seamlessly with the Oremi ecosystem and other MCP-compatible
  clients.

## Deployment

Oremi Iṣakoso is distributed as a multi-platform Docker image for
`linux/amd64` and `linux/arm64`. It can be deployed as a standalone service or
integrated into the Oremi ecosystem alongside services such as Oremi Isinmi,
Oremi Ojọ, Oremi Rediyo, and Oremi Kansa.

The following sections describe the available Docker image, persistent storage
requirements, and example deployments using both Docker and Docker Compose.

### Command Line

Before installing Oremi Iṣakoso from PyPI, ensure the following requirements are
met:

- Python 3.12 or later.
- `uv` (recommended) or `pip` for package installation.

Oremi Iṣakoso can be installed either as a standalone command-line application
or as a Python package.

#### Install with uv

```sh
uv tool install oremi-isakoso
```

#### Install with pip

```sh
python -m pip install oremi-isakoso
```

#### Usage

```text
oremi-isakoso [-h] [-v]
```

When started without arguments, Oremi Iṣakoso launches the HTTP server using the
configured environment variables.

#### Options

- `-h`, `--help`: Display the command-line help and exit.
- `-v`, `--version`: Display the installed version and exit.

### Docker Image

The [`demsking/oremi-isakoso`](https://hub.docker.com/r/demsking/oremi-isakoso)
Docker image is officially available on Docker Hub, supporting both
`linux/amd64` and `linux/arm64` platforms. The image exposes port `5089`, which
serves the REST API and the interactive documentation.

The interactive documentation can be accessed at `http://localhost:5089/docs`
and allows testing available endpoints directly from the browser.

### Volumes

Oremi Iṣakoso is largely stateless and does not require persistent storage for
normal operation.

The Docker image does not define any persistent volumes. If you configure file
logging by setting `OREMI_ISAKOSO_LOG_FILE` to a location inside the container,
mount a host directory to preserve log files across container recreation.

### Deploy with Docker

Use the official Docker image
[`demsking/oremi-isakoso`](https://hub.docker.com/r/demsking/oremi-isakoso)
to run Oremi Iṣakoso:

```sh
docker run -d \
  --name oremi-isakoso \
  --env-file <path_to_env_file> \
  -p 5089:5089 \
  demsking/oremi-isakoso
```

Replace `<path_to_env_file>` with the path to your
[environment variables](#environment-variables) file containing the desired
configuration.

### Deploy with Docker Compose

Create a `compose.yaml` file:

```yaml
services:
  isakoso:
    image: demsking/oremi-isakoso
    restart: unless-stopped
    depends_on:
      - mosquitto
    ports:
      - 5089:5089
    environment:
      OREMI_ISAKOSO_MQTT_BROKER: mosquitto
    env_file:
      - .env

  mosquitto:
    image: eclipse-mosquitto
    restart: unless-stopped
    volumes:
      - ./config/mosquitto.conf:/mosquitto/config/mosquitto.conf

  zigbee2mqtt:
    image: koenkk/zigbee2mqtt
    restart: unless-stopped
    volumes:
      - /run/udev:/run/udev:ro
      - zigbee2mqtt-data:/app/data
    devices:
      - /dev/ttyUSB0:/dev/ttyUSB0
    group_add:
      - dialout

volumes:
  zigbee2mqtt-data:
```

Start the services with:

```sh
docker compose up -d
```

Once started, open the interactive documentation at:

```txt
http://localhost:35089/docs/
```

## Model Context Protocol

Oremi Isakoso implements the Model Context Protocol (MCP) using a strongly-typed
server. It exposes its core functionality as a set of tools, resources and
prompts that LLM agents can call directly.

The MCP server uses the **Streamable HTTP transport** protocol and is mounted at:

```txt
/mcp
```

### Available MCP Tools

- `list_devices(provider?)`: discover devices and readable/writable capabilities.
- `search_devices(query)`: search for devices using a hybrid of natural language
  keyword extraction (handling typos/synonyms) and weighted keyword index search.
- `get_device(device_id)`: inspect one device and its capability constraints.
- `get_device_state(device_id)`: read the latest state received over MQTT.
- `turn_on`, `turn_off`, `toggle`: control switchable devices.
- `set_brightness(device_id, brightness)`: set brightness from 0 to 100 percent.
- `set_color(device_id, color)`: set `#RRGGBB` or complete RGB channels.
- `set_color_temperature(device_id, temperature_kelvin)`: set 1000-10000 K.
- `set_position(device_id, position)`: set a cover or blind from 0 to 100 percent.
- `lock`, `unlock`: control lock-capable devices.
- `read_sensor(device_id, sensor)`: read one advertised sensor with its unit.
- `execute_action(device_id, action, value)`: invoke another writable capability.

Tool inputs and outputs have generated JSON schemas. Mutations are validated
against the capabilities advertised by Zigbee2MQTT before MQTT publication.

## Configuration

All environment variables use the `OREMI_ISAKOSO_` prefix and may be placed in
a `.env` file.

### Server

- `SERVER_HOST`: bind address; default `0.0.0.0`.
- `SERVER_PORT`: bind port; default `5089`.
- `API_PREFIX`: optional route prefix; default `/`.

### MQTT

MQTT is disabled when `MQTT_BROKER` is unset.

- `MQTT_BROKER`: broker hostname or IP address, without a URL path.
- `MQTT_PORT`: broker port; default `1883`.
- `ZIGBEE2MQTT_TOPIC_PREFIX`: Zigbee2MQTT base topic; default `zigbee2mqtt/`.
  Leading and trailing slashes are normalized, and MQTT wildcards are rejected.
- `MQTT_CLIENT_ID`: optional client identifier.
- `MQTT_USERNAME` and `MQTT_PASSWORD`: optional credentials.
- `MQTT_KEEPALIVE`: keepalive in seconds; default `60`.
- `MQTT_TLS_ENABLED`: enable TLS; default `false`.
- `MQTT_TLS_CA_CERT`: optional CA certificate path.

### Logging

- `OREMI_ISAKOSO_LOG_LEVEL`: Optional. Defaults to `INFO`. Logging level:
  `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`.
- `OREMI_ISAKOSO_LOG_FILE`: Optional. Defaults to `oremi_isakoso.log`. Path to
  the rotating application log file.

Example:

```env
OREMI_ISAKOSO_SERVER_HOST=0.0.0.0
OREMI_ISAKOSO_SERVER_PORT=5089
OREMI_ISAKOSO_MQTT_BROKER=mosquitto
OREMI_ISAKOSO_MQTT_PORT=1883
OREMI_ISAKOSO_ZIGBEE2MQTT_TOPIC_PREFIX=zigbee2mqtt/
OREMI_ISAKOSO_LOG_LEVEL=INFO
```

## Development

See the [contribution guide](https://gitlab.com/demsking/oremi-isakoso/-/blob/main/CONTRIBUTING.md)
for development environment and contribution guidance.

## Versioning

Oremi Iṣakoso project adheres to [Semantic Versioning](https://semver.org/)
(SemVer). Version numbers follow the `MAJOR.MINOR.PATCH` format:

- **MAJOR** version increments for incompatible API changes
- **MINOR** version increments for backward-compatible new functionality
- **PATCH** version increments for backward-compatible bug fixes

The current version can be found by running:

```bash
oremi-isakoso --version
```

## License

Copyright 2026 Sébastien Demanou. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://gitlab.com/demsking/oremi-isakoso/-/blob/main/LICENSE

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
