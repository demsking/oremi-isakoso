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
pip install oremi-isakoso
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

The interactive documentation can be accessed at `http://localhost:5089/docs/`
and allows testing available endpoints directly from the browser.

### Docker Volume

The Docker image defines a persistent volume at `/oremi/data`.

This directory is used as the default storage location for:

- **FastEmbed Model Cache**: Downloaded model weights for semantic vector search
  (`OREMI_ISAKOSO_EMBEDDING_CACHE_DIR`). Mounting this volume prevents
  re-downloading model files when the container is recreated.
- **Application Logs**: Rotating log files if `OREMI_ISAKOSO_LOG_FILE` is
  configured to write to a path inside `/oremi/data` (e.g.,
  `/oremi/data/isakoso.log`).

Mounting a volume or host directory to `/oremi/data` is recommended to maintain
cache persistence across container restarts.

### Deploy with Docker

Use the official Docker image
[`demsking/oremi-isakoso`](https://hub.docker.com/r/demsking/oremi-isakoso)
to run Oremi Iṣakoso:

```sh
docker run -d \
  --name oremi-isakoso \
  --env-file <path_to_env_file> \
  -p 5089:5089 \
  -v oremi-isakoso-data:/oremi/data \
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
    volumes:
      - oremi-isakoso-data:/oremi/data
    environment:
      OREMI_ISAKOSO_MQTT_BROKER: mosquitto

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
  oremi-isakoso-data:
  zigbee2mqtt-data:
```

Start the services with:

```sh
docker compose up -d
```

Once started, open the interactive documentation at:

```txt
http://localhost:5089/docs/
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

- `list_devices(provider?, detailed?)`: discover registered devices in a compact summary format (or detailed format if `detailed=True`).
- `search_devices(query)`: search registered devices using multilingual semantic vector embeddings (FastEmbed ONNX vector similarity + token boosting).
- `get_device(device_id)`: inspect one device and its capability constraints.
- `get_device_state(device_id)`: read the latest state received over MQTT.
- `turn_on(device_id)`, `turn_off(device_id)`, `toggle(device_id)`: control switchable devices.
- `set_brightness(device_id, brightness)`: set brightness from 0 to 100 percent.
- `set_color(device_id, color)`: set `#RRGGBB` or complete RGB channels.
- `set_color_temperature(device_id, temperature_kelvin)`: set 1000-10000 K.
- `set_position(device_id, position)`: set a cover or blind from 0 to 100 percent.
- `lock(device_id)`, `unlock(device_id)`: control lock-capable devices.
- `read_sensor(device_id, sensor)`: read one advertised sensor with its unit.
- `execute_action(device_id, action, value)`: invoke another writable capability.

Tool inputs and outputs have generated JSON schemas. Mutations are validated
against the capabilities advertised by Zigbee2MQTT before MQTT publication.

### Available MCP Resources

- `device:///all`: list all registered devices and their capabilities.
- `device:///{device_id}/metadata`: inspect metadata and capabilities for a specific device.
- `device:///{device_id}/state`: read the current state of a specific device.

### Available MCP Prompts

- `turn_on_device(command)`: guide an agent through resolving, checking, and turning on a device.
- `turn_off_device(command)`: guide an agent through resolving, checking, and turning off a device.
- `toggle_device(command)`: guide an agent through resolving, checking, and toggling a device state.
- `set_device_brightness(command)`: guide an agent through setting the brightness of a device.
- `set_device_color(command)`: guide an agent through setting the color of a device.
- `set_device_color_temperature(command)`: guide an agent through setting the color temperature of a device.
- `read_sensor(command)`: guide an agent through resolving and reading a sensor value.
- `execute_action(command)`: guide an agent through executing an action on a device.
- `summarize_devices()`: guide an agent through fetching device states and generating a status summary report.

## Configuration

All environment variables use the `OREMI_ISAKOSO_` prefix and may be placed in
a `.env` file.

### Server

- `OREMI_ISAKOSO_SERVER_HOST`: bind address; default `0.0.0.0`.
- `OREMI_ISAKOSO_SERVER_PORT`: bind port; default `5089`.
- `OREMI_ISAKOSO_API_PREFIX`: optional route prefix; default `/`.

### Search & Embeddings

- `OREMI_ISAKOSO_EMBEDDING_MODEL`: FastEmbed model name for semantic vector search; default `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
- `OREMI_ISAKOSO_EMBEDDING_CACHE_DIR`: optional directory path to store downloaded FastEmbed model weights; default `/oremi/data`.

### MQTT

MQTT is disabled when `OREMI_ISAKOSO_MQTT_BROKER` is unset.

- `OREMI_ISAKOSO_MQTT_BROKER`: broker hostname or IP address, without a URL path.
- `OREMI_ISAKOSO_MQTT_PORT`: broker port; default `1883`.
- `OREMI_ISAKOSO_MQTT_CLIENT_ID`: optional client identifier.
- `OREMI_ISAKOSO_MQTT_USERNAME` and `OREMI_ISAKOSO_MQTT_PASSWORD`: optional credentials.
- `OREMI_ISAKOSO_MQTT_KEEPALIVE`: keepalive in seconds; default `60`.
- `OREMI_ISAKOSO_MQTT_TLS_CA_CERT`: optional CA certificate path.

### Zigbee2MQTT

- `OREMI_ISAKOSO_ZIGBEE2MQTT_TOPIC_PREFIX`: Zigbee2MQTT base topic; default `zigbee2mqtt/`.
  Leading and trailing slashes are normalized, and MQTT wildcards are rejected.

### Logging

- `OREMI_ISAKOSO_LOG_LEVEL`: Optional. Defaults to `INFO`. Logging level:
  `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`.
- `OREMI_ISAKOSO_LOG_FILE`: Optional. Defaults to unset (console logging only). Path to
  the rotating application log file.

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
