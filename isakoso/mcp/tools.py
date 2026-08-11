# Copyright 2026 Sébastien Demanou. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
from enum import Enum
from typing import Annotated
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from isakoso.core.devices import ColorValue
from isakoso.core.devices import Device
from isakoso.core.devices import DeviceRegistry
from isakoso.core.devices import DeviceState
from isakoso.core.devices import DeviceSummary
from isakoso.core.devices import OperationResult
from isakoso.core.devices import SensorReading
from isakoso.core.devices import UnsupportedOperationError


class Provider(str, Enum):
  ZIGBEE2MQTT = "zigbee2mqtt"


READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True)
MUTATION = ToolAnnotations(destructive_hint=False)


def register_mcp_tools(mcp: MCPServer, registry: DeviceRegistry) -> None:
  """Build the MCP transport while keeping tools independent from any radio protocol."""

  @mcp.tool(
    name="list_devices",
    title="List Devices",
    description="List all registered devices in a compact summary format (or detailed format if detailed=True).",
    annotations=READ_ONLY,
  )
  async def list_devices(
    provider: Annotated[
      Provider | None,
      Field(description="Optional provider filter, for example zigbee2mqtt. Omit to query every provider."),
    ] = None,
    detailed: Annotated[
      bool,
      Field(description="If True, return full device metadata and detailed capabilities. Defaults to False for a compact summary."),
    ] = False,
  ) -> list[DeviceSummary] | list[Device]:
    provider_val = provider.value if provider is not None else None
    devices = await registry.list_devices(provider_val)

    if not detailed:
      return [device.to_summary() for device in devices]

    return devices

  @mcp.tool(
    name="search_devices",
    title="Search Devices",
    description="Search for registered devices using natural language or multilingual semantic vector queries.",
    annotations=READ_ONLY,
  )
  async def search_devices(
    query: Annotated[
      str,
      Field(
        description="Natural language device query, description, or room name (e.g. 'bedroom light' or 'allumer la lumière')."
      ),
    ],
  ) -> list[DeviceSummary]:
    devices = await registry.search_devices(query)
    return [device.to_summary() for device in devices]



  @mcp.tool(
    name="get_device",
    title="Get Device",
    description="Get metadata and capabilities for a specific device.",
    annotations=READ_ONLY,
  )
  async def get_device(
    device_id: Annotated[str, Field(description="Provider-scoped id returned by list_devices.")],
  ) -> Device:
    return await registry.get_device(device_id)

  @mcp.tool(
    name="get_device_state",
    title="Get Device State",
    description="Get the latest state reported by a specific device.",
    annotations=READ_ONLY,
  )
  async def get_device_state(
    device_id: Annotated[str, Field(description="Provider-scoped id returned by list_devices.")],
  ) -> DeviceState:
    return await registry.get_device_state(device_id)

  async def mutate(device_id: str, action: str, value: Any = None) -> OperationResult:
    return await registry.execute_action(device_id, action, value)

  @mcp.tool(
    name="turn_on",
    title="Turn On",
    description="Turn on a light, plug, switch, or other switchable device.",
    annotations=MUTATION,
  )
  async def turn_on(device_id: Annotated[str, Field(description="Id of a switchable device.")]) -> OperationResult:
    return await mutate(device_id, "turn_on")

  @mcp.tool(
    name="turn_off",
    title="Turn Off",
    description="Turn off a light, plug, switch, or other switchable device.",
    annotations=MUTATION,
  )
  async def turn_off(device_id: Annotated[str, Field(description="Id of a switchable device.")]) -> OperationResult:
    return await mutate(device_id, "turn_off")

  @mcp.tool(
    name="toggle",
    title="Toggle",
    description="Toggle a switchable device to its opposite state.",
    annotations=MUTATION,
  )
  async def toggle(device_id: Annotated[str, Field(description="Id of a switchable device.")]) -> OperationResult:
    return await mutate(device_id, "toggle")

  @mcp.tool(
    name="set_brightness",
    title="Set Brightness",
    description="Set a dimmable light's brightness as a percentage.",
    annotations=MUTATION,
  )
  async def set_brightness(
    device_id: Annotated[str, Field(description="Id of a dimmable light.")],
    brightness: Annotated[int, Field(ge=0, le=100, description="Brightness percentage from 0 to 100.")],
  ) -> OperationResult:
    return await mutate(device_id, "set_brightness", brightness)

  @mcp.tool(
    name="set_color",
    title="Set Color",
    description="Set a light color using a hex value or RGB channels.",
    annotations=MUTATION,
  )
  async def set_color(
    device_id: Annotated[str, Field(description="Id of a color-capable light.")],
    color: Annotated[ColorValue, Field(description="Color as #RRGGBB or complete RGB channels.")],
  ) -> OperationResult:
    return await mutate(device_id, "set_color", color.as_provider_value())

  @mcp.tool(
    name="set_color_temperature",
    title="Set Color Temperature",
    description="Set a light's white color temperature in kelvin.",
    annotations=MUTATION,
  )
  async def set_color_temperature(
    device_id: Annotated[str, Field(description="Id of a color-temperature-capable light.")],
    temperature_kelvin: Annotated[int, Field(ge=1000, le=10000, description="Color temperature in kelvin.")],
  ) -> OperationResult:
    return await mutate(device_id, "set_color_temperature", temperature_kelvin)

  @mcp.tool(
    name="set_position",
    title="Set Position",
    description="Set a cover, blind, curtain, or other positionable device position.",
    annotations=MUTATION,
  )
  async def set_position(
    device_id: Annotated[str, Field(description="Id of a cover, blind, curtain, or positionable device.")],
    position: Annotated[int, Field(ge=0, le=100, description="Target position percentage from 0 to 100.")],
  ) -> OperationResult:
    return await mutate(device_id, "set_position", position)

  @mcp.tool(
    name="lock",
    title="Lock",
    description="Lock a lock-capable device.",
    annotations=MUTATION,
  )
  async def lock(device_id: Annotated[str, Field(description="Id of a lock.")]) -> OperationResult:
    return await mutate(device_id, "lock")

  @mcp.tool(
    name="unlock",
    title="Unlock",
    description="Unlock a lock-capable device.",
    annotations=MUTATION,
  )
  async def unlock(device_id: Annotated[str, Field(description="Id of a lock.")]) -> OperationResult:
    return await mutate(device_id, "unlock")

  @mcp.tool(
    name="read_sensor",
    title="Read Sensor",
    description="Read one sensor property from the latest reported device state.",
    annotations=READ_ONLY,
  )
  async def read_sensor(
    device_id: Annotated[str, Field(description="Id of a device with readable sensor properties.")],
    sensor: Annotated[str, Field(description="Sensor property to read, such as temperature, humidity, or power.")],
  ) -> SensorReading:
    device = await registry.get_device(device_id)
    capability = next((item for item in device.capabilities if item.property == sensor and item.readable), None)

    if capability is None:
      raise UnsupportedOperationError(f"{device.name} does not expose readable sensor {sensor!r}")

    state = await registry.get_device_state(device_id)

    if sensor not in state.values:
      raise UnsupportedOperationError(f"{device.name} has not reported sensor {sensor!r} yet")

    return SensorReading(device_id=device.id, sensor=sensor, value=state.values[sensor], unit=capability.unit)

  @mcp.tool(
    name="execute_action",
    title="Execute Action",
    description="Execute an advertised device-specific action not covered by a dedicated tool.",
    annotations=MUTATION,
  )
  async def execute_action(
    device_id: Annotated[str, Field(description="Provider-scoped id returned by list_devices.")],
    action: Annotated[str, Field(description="Writable property advertised in the device capabilities.")],
    value: Annotated[Any, Field(description="Value accepted by the advertised capability.")],
  ) -> OperationResult:
    return await mutate(device_id, action, value)
