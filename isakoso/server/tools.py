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

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from isakoso.core.devices import ColorValue
from isakoso.core.devices import Device
from isakoso.core.devices import DeviceRegistry
from isakoso.core.devices import DeviceState
from isakoso.core.devices import OperationResult
from isakoso.core.devices import SensorReading
from isakoso.core.devices import UnsupportedOperationError


class Provider(str, Enum):
  ZIGBEE2MQTT = "zigbee2mqtt"


READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True)
MUTATION = ToolAnnotations(destructiveHint=False)


def register_mcp_tools(mcp: FastMCP, registry: DeviceRegistry) -> None:
  """Build the MCP transport while keeping tools independent from any radio protocol."""

  @mcp.tool(annotations=READ_ONLY)
  async def list_devices(
    provider: Annotated[
      Provider | None,
      Field(description="Optional provider filter, for example zigbee2mqtt. Omit to query every provider."),
    ] = None,
  ) -> list[Device]:
    """List all registered devices and their readable/writable capabilities.

    Call this only when the user wants to list all devices or when you need to see the
    entire home layout. Avoid calling this for targeting specific devices; instead,
    use extract_devices_from_user_request to look up devices mentioned in user requests.
    """
    provider_val = provider.value if provider is not None else None
    return await registry.list_devices(provider_val)

  @mcp.tool(annotations=READ_ONLY)
  async def extract_devices_from_user_request(
    user_request: Annotated[
      str,
      Field(
        description=(
          "The user's raw request text, verbatim or lightly summarized. "
          "Use the complete initial input when available to provide additional "
          "context for device matching and disambiguation."
        )
      ),
    ],
  ) -> list[Device]:
    """Resolve device names/descriptions mentioned in a user request to registered devices.

    Call this before any tool that acts on a device (turning it on/off, reading its
    state, changing settings, etc.) whenever the user refers to a device by name,
    room, or description rather than by an exact device ID you already have.

    Matching is fuzzy: it handles partial names, room references, aliases, and
    natural-language phrasing (e.g. "the lamp near the couch" or "bedroom fan").
    A single call can return matches for multiple devices mentioned in the same
    request, so pass the full request text as the user_request argument.

    Returns a list of matching `Device` objects ordered by relevance (best match
    first). Returns an empty list if no devices match — in that case, ask the user
    to clarify or list available devices rather than guessing an ID.
    """
    return await registry.search_devices(user_request)

  @mcp.tool(annotations=READ_ONLY)
  async def get_device(
    device_id: Annotated[str, Field(description="Provider-scoped id returned by list_devices.")],
  ) -> Device:
    """Get metadata and capabilities for one device."""
    return await registry.get_device(device_id)

  @mcp.tool(annotations=READ_ONLY)
  async def get_device_state(
    device_id: Annotated[str, Field(description="Provider-scoped id returned by list_devices.")],
  ) -> DeviceState:
    """Get the latest state reported by a device."""
    return await registry.get_device_state(device_id)

  async def mutate(device_id: str, action: str, value: Any = None) -> OperationResult:
    return await registry.execute_action(device_id, action, value)

  @mcp.tool(annotations=MUTATION)
  async def turn_on(device_id: Annotated[str, Field(description="Id of a switchable device.")]) -> OperationResult:
    """Turn on a light, plug, switch, or other switchable device."""
    return await mutate(device_id, "turn_on")

  @mcp.tool(annotations=MUTATION)
  async def turn_off(device_id: Annotated[str, Field(description="Id of a switchable device.")]) -> OperationResult:
    """Turn off a light, plug, switch, or other switchable device."""
    return await mutate(device_id, "turn_off")

  @mcp.tool(annotations=MUTATION)
  async def toggle(device_id: Annotated[str, Field(description="Id of a switchable device.")]) -> OperationResult:
    """Toggle a switchable device to its opposite state."""
    return await mutate(device_id, "toggle")

  @mcp.tool(annotations=MUTATION)
  async def set_brightness(
    device_id: Annotated[str, Field(description="Id of a dimmable light.")],
    brightness: Annotated[int, Field(ge=0, le=100, description="Brightness percentage from 0 to 100.")],
  ) -> OperationResult:
    """Set a dimmable light's brightness as a percentage."""
    return await mutate(device_id, "set_brightness", brightness)

  @mcp.tool(annotations=MUTATION)
  async def set_color(
    device_id: Annotated[str, Field(description="Id of a color-capable light.")],
    color: Annotated[ColorValue, Field(description="Color as #RRGGBB or complete RGB channels.")],
  ) -> OperationResult:
    """Set a light color using a hex value or RGB channels."""
    return await mutate(device_id, "set_color", color.as_provider_value())

  @mcp.tool(annotations=MUTATION)
  async def set_color_temperature(
    device_id: Annotated[str, Field(description="Id of a color-temperature-capable light.")],
    temperature_kelvin: Annotated[int, Field(ge=1000, le=10000, description="Color temperature in kelvin.")],
  ) -> OperationResult:
    """Set a light's white color temperature in kelvin."""
    return await mutate(device_id, "set_color_temperature", temperature_kelvin)

  @mcp.tool(annotations=MUTATION)
  async def set_position(
    device_id: Annotated[str, Field(description="Id of a cover, blind, curtain, or positionable device.")],
    position: Annotated[int, Field(ge=0, le=100, description="Target position percentage from 0 to 100.")],
  ) -> OperationResult:
    """Set a cover, blind, curtain, or other positionable device position."""
    return await mutate(device_id, "set_position", position)

  @mcp.tool(annotations=MUTATION)
  async def lock(device_id: Annotated[str, Field(description="Id of a lock.")]) -> OperationResult:
    """Lock a lock-capable device."""
    return await mutate(device_id, "lock")

  @mcp.tool(annotations=MUTATION)
  async def unlock(device_id: Annotated[str, Field(description="Id of a lock.")]) -> OperationResult:
    """Unlock a lock-capable device."""
    return await mutate(device_id, "unlock")

  @mcp.tool(annotations=READ_ONLY)
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

  @mcp.tool(annotations=MUTATION)
  async def execute_action(
    device_id: Annotated[str, Field(description="Provider-scoped id returned by list_devices.")],
    action: Annotated[str, Field(description="Writable property advertised in the device capabilities.")],
    value: Annotated[Any, Field(description="Value accepted by the advertised capability.")],
  ) -> OperationResult:
    """Execute an advertised device-specific action not covered by a dedicated tool."""
    return await mutate(device_id, action, value)
