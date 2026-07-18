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
from urllib.parse import unquote

from mcp.server.fastmcp import FastMCP

from isakoso.core.devices import Device
from isakoso.core.devices import DeviceRegistry
from isakoso.core.devices import DeviceState


def register_mcp_resources(mcp: FastMCP, registry: DeviceRegistry) -> None:
  @mcp.resource("devices:///all", mime_type="application/json")
  async def list_devices_resource() -> list[Device]:
    """Get the list of all registered devices and their capabilities."""
    return await registry.list_devices()

  @mcp.resource("devices:///{device_id}/metadata", mime_type="application/json")
  async def get_device_resource(device_id: str) -> Device:
    """Get metadata and capabilities for one device."""
    return await registry.get_device(unquote(device_id))

  @mcp.resource("devices:///{device_id}/state", mime_type="application/json")
  async def get_device_state_resource(device_id: str) -> DeviceState:
    """Get the current state for a specific device."""
    return await registry.get_device_state(unquote(device_id))
