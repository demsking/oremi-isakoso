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
from typing import Annotated
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..core.devices import ColorValue
from ..core.devices import Device
from ..core.devices import DeviceRegistry
from ..core.devices import DeviceState
from ..core.devices import OperationResult
from ..core.devices import SensorReading
from ..core.devices import UnsupportedOperationError

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True)
MUTATION = ToolAnnotations(destructiveHint=False)


def create_mcp_server(registry: DeviceRegistry) -> FastMCP:
  """Build the MCP transport while keeping tools independent from any radio protocol."""
  server = FastMCP(
    name="Oremi Iṣakoso",
    instructions=(
      "Discover and control smart-home devices. Call list_devices before control operations, "
      "use the returned provider-scoped device id, and inspect capabilities before choosing a tool."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/mcp",
  )

  @server.tool(annotations=READ_ONLY)
  async def list_devices(
    provider: Annotated[
      str | None,
      Field(description="Optional provider filter, for example zigbee2mqtt. Omit to query every provider."),
    ] = None,
  ) -> list[Device]:
    """List devices and their readable and writable capabilities."""
    return await registry.list_devices(provider)

  @server.tool(annotations=READ_ONLY)
  async def get_device(
    device_id: Annotated[str, Field(description="Provider-scoped id returned by list_devices.")],
  ) -> Device:
    """Get metadata and capabilities for one device."""
    return await registry.get_device(device_id)

  @server.tool(annotations=READ_ONLY)
  async def get_device_state(
    device_id: Annotated[str, Field(description="Provider-scoped id returned by list_devices.")],
  ) -> DeviceState:
    """Get the latest state reported by a device."""
    return await registry.get_device_state(device_id)

  async def mutate(device_id: str, action: str, value: Any = None) -> OperationResult:
    return await registry.execute_action(device_id, action, value)

  @server.tool(annotations=MUTATION)
  async def turn_on(device_id: Annotated[str, Field(description="Id of a switchable device.")]) -> OperationResult:
    """Turn on a light, plug, switch, or other switchable device."""
    return await mutate(device_id, "turn_on")

  @server.tool(annotations=MUTATION)
  async def turn_off(device_id: Annotated[str, Field(description="Id of a switchable device.")]) -> OperationResult:
    """Turn off a light, plug, switch, or other switchable device."""
    return await mutate(device_id, "turn_off")

  @server.tool(annotations=MUTATION)
  async def toggle(device_id: Annotated[str, Field(description="Id of a switchable device.")]) -> OperationResult:
    """Toggle a switchable device to its opposite state."""
    return await mutate(device_id, "toggle")

  @server.tool(annotations=MUTATION)
  async def set_brightness(
    device_id: Annotated[str, Field(description="Id of a dimmable light.")],
    brightness: Annotated[int, Field(ge=0, le=100, description="Brightness percentage from 0 to 100.")],
  ) -> OperationResult:
    """Set a dimmable light's brightness as a percentage."""
    return await mutate(device_id, "set_brightness", brightness)

  @server.tool(annotations=MUTATION)
  async def set_color(
    device_id: Annotated[str, Field(description="Id of a color-capable light.")],
    color: Annotated[ColorValue, Field(description="Color as #RRGGBB or complete RGB channels.")],
  ) -> OperationResult:
    """Set a light color using a hex value or RGB channels."""
    return await mutate(device_id, "set_color", color.as_provider_value())

  @server.tool(annotations=MUTATION)
  async def set_color_temperature(
    device_id: Annotated[str, Field(description="Id of a color-temperature-capable light.")],
    temperature_kelvin: Annotated[int, Field(ge=1000, le=10000, description="Color temperature in kelvin.")],
  ) -> OperationResult:
    """Set a light's white color temperature in kelvin."""
    return await mutate(device_id, "set_color_temperature", temperature_kelvin)

  @server.tool(annotations=MUTATION)
  async def set_position(
    device_id: Annotated[str, Field(description="Id of a cover, blind, curtain, or positionable device.")],
    position: Annotated[int, Field(ge=0, le=100, description="Target position percentage from 0 to 100.")],
  ) -> OperationResult:
    """Set a cover, blind, curtain, or other positionable device position."""
    return await mutate(device_id, "set_position", position)

  @server.tool(annotations=MUTATION)
  async def lock(device_id: Annotated[str, Field(description="Id of a lock.")]) -> OperationResult:
    """Lock a lock-capable device."""
    return await mutate(device_id, "lock")

  @server.tool(annotations=MUTATION)
  async def unlock(device_id: Annotated[str, Field(description="Id of a lock.")]) -> OperationResult:
    """Unlock a lock-capable device."""
    return await mutate(device_id, "unlock")

  @server.tool(annotations=READ_ONLY)
  async def read_sensor(
    device_id: Annotated[str, Field(description="Id of a device with readable sensor properties.")],
    sensor: Annotated[str, Field(description="Sensor property to read, such as temperature, humidity, or power.")],
  ) -> SensorReading:
    """Read one sensor property from the latest reported device state."""
    device = await registry.get_device(device_id)
    capability = next((item for item in device.capabilities if item.property == sensor and item.readable), None)
    if capability is None:
      raise UnsupportedOperationError(f"{device.name} does not expose readable sensor {sensor!r}")
    state = await registry.get_device_state(device_id)
    if sensor not in state.values:
      raise UnsupportedOperationError(f"{device.name} has not reported sensor {sensor!r} yet")
    return SensorReading(device_id=device.id, sensor=sensor, value=state.values[sensor], unit=capability.unit)

  @server.tool(annotations=MUTATION)
  async def execute_action(
    device_id: Annotated[str, Field(description="Provider-scoped id returned by list_devices.")],
    action: Annotated[str, Field(description="Writable property advertised in the device capabilities.")],
    value: Annotated[Any, Field(description="Value accepted by the advertised capability.")],
  ) -> OperationResult:
    """Execute an advertised device-specific action not covered by a dedicated tool."""
    return await mutate(device_id, action, value)

  return server
