# Oremi Iṣakoso

[![Buy me a beer](https://img.shields.io/badge/Buy%20me-a%20beer-1f425f.svg)](https://www.buymeacoffee.com/demsking)

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

![Oremi Iṣakoso Logo](https://gitlab.com/demsking/oremi-isakoso/-/raw/main/htdocs/logo.png)

## Documentation

All project documentation—including architecture details, configuration reference, and the Home Assistant integration guide—can be found at:
https://demsking.gitlab.io/oremi-isakoso/

## Development

Oremi Device is built with Python and uses `uv` for dependency management. The
project follows standard Python development practices with type hints, linting,
and automated testing.

For detailed information on setting up your development environment, running
tests, code style guidelines, and the pull request process, please refer to
[CONTRIBUTING.md](https://gitlab.com/demsking/oremi-isakoso/-/blob/main/CONTRIBUTING.md).

## Versioning

This project adheres to [Semantic Versioning](https://semver.org/) (SemVer).
Version numbers follow the `MAJOR.MINOR.PATCH` format:

- **MAJOR** version increments for incompatible API changes
- **MINOR** version increments for backward-compatible new functionality
- **PATCH** version increments for backward-compatible bug fixes

## License

Copyright 2026 Sébastien Demanou. All Rights Reserved.

Licensed under the Apache License, Version 2.0. See the
[LICENSE](https://gitlab.com/demsking/oremi-isakoso/-/blob/main/LICENSE) for the
complete license text.
