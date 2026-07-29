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
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP

from isakoso.core.app import create_app
from isakoso.core.devices import Device
from isakoso.core.devices import DeviceCapability
from isakoso.core.devices import DeviceRegistry
from isakoso.core.devices import DeviceState
from isakoso.core.devices import OperationResult
from isakoso.core.settings import Settings
from isakoso.mcp.prompts import register_mcp_prompts
from isakoso.mcp.resources import register_mcp_resources
from isakoso.mcp.tools import register_mcp_tools


class FakeProvider:
  provider_id = "fake"

  def __init__(self):
    self.actions: list[tuple[str, str, Any]] = []
    self.device = Device(
      id="fake:lamp",
      name="Lamp",
      provider="fake",
      capabilities=[
        DeviceCapability(property="state", type="binary", readable=True, writable=True),
        DeviceCapability(property="temperature", type="numeric", readable=True, unit="°C"),
      ],
    )

  async def list_devices(self):
    return [self.device]

  async def get_device(self, device_id):
    return self.device

  async def get_device_state(self, device_id):
    return DeviceState(device_id=self.device.id, values={"state": "ON", "temperature": 21.5})

  async def execute_action(self, device_id, action, value):
    self.actions.append((device_id, action, value))
    return OperationResult(device_id=device_id, operation=action, state={action: value})


@pytest.fixture
def mcp_server():
  registry = DeviceRegistry()
  registry.register(FakeProvider())
  mcp = FastMCP(name="Oremi Iṣakoso Test")
  register_mcp_prompts(mcp)
  register_mcp_resources(mcp, registry)
  register_mcp_tools(mcp, registry)
  return mcp


@pytest.mark.asyncio
async def test_mcp_exposes_complete_discoverable_tool_contract(mcp_server):
  tools = await mcp_server.list_tools()

  assert {tool.name for tool in tools} == {
    "list_devices",
    "search_devices",
    "get_device",
    "get_device_state",
    "turn_on",
    "turn_off",
    "toggle",
    "set_brightness",
    "set_color",
    "set_color_temperature",
    "set_position",
    "lock",
    "unlock",
    "read_sensor",
    "execute_action",
  }

  brightness = next(tool for tool in tools if tool.name == "set_brightness")
  assert brightness.inputSchema["properties"]["brightness"]["minimum"] == 0
  assert brightness.inputSchema["properties"]["brightness"]["maximum"] == 100
  assert brightness.outputSchema is not None

  list_devices_tool = next(tool for tool in tools if tool.name == "list_devices")
  provider_schema = list_devices_tool.inputSchema["properties"]["provider"]
  # Ensure the provider schema references the Provider Enum definitions and can be null
  assert any("$ref" in sub and "Provider" in sub["$ref"] for sub in provider_schema.get("anyOf", []))
  assert list_devices_tool.inputSchema["$defs"]["Provider"]["enum"] == ["zigbee2mqtt"]


@pytest.mark.asyncio
async def test_mcp_tools_return_structured_results(mcp_server):
  listed = await mcp_server.call_tool("list_devices", {})
  reading = await mcp_server.call_tool("read_sensor", {"device_id": "fake:lamp", "sensor": "temperature"})
  action = await mcp_server.call_tool("turn_off", {"device_id": "fake:lamp"})

  assert listed[1]["result"][0]["id"] == "fake:lamp"
  assert reading[1] == {"device_id": "fake:lamp", "sensor": "temperature", "value": 21.5, "unit": "°C"}
  assert action[1]["operation"] == "turn_off"


@pytest.mark.asyncio
async def test_mcp_list_devices_compact_and_detailed(mcp_server):
  # Default (detailed=False) returns compact DeviceSummary format
  compact_res = await mcp_server.call_tool("list_devices", {})
  device_summary = compact_res[1]["result"][0]
  assert device_summary["id"] == "fake:lamp"
  assert "capabilities" in device_summary
  assert isinstance(device_summary["capabilities"], list)
  assert "manufacturer" not in device_summary

  # Detailed (detailed=True) returns full Device format
  detailed_res = await mcp_server.call_tool("list_devices", {"detailed": True})
  device_full = detailed_res[1]["result"][0]
  assert device_full["id"] == "fake:lamp"
  assert "manufacturer" in device_full
  assert isinstance(device_full["capabilities"][0], dict)



@pytest.mark.asyncio
async def test_device_search_accuracy():
  d1 = Device(
    id="zigbee2mqtt:living-room-lamp-1",
    name="Living Room Lamp 1",
    provider="zigbee2mqtt",
  )
  d2 = Device(
    id="zigbee2mqtt:kitchen-smart-plug",
    name="Kitchen Smart Plug",
    provider="zigbee2mqtt",
  )
  d3 = Device(
    id="zigbee2mqtt:bedroom-light",
    name="Bedroom Light",
    provider="zigbee2mqtt",
  )
  d4 = Device(
    id="zigbee2mqtt:Lumière de la chambre",
    name="Lumière de la chambre",
    provider="zigbee2mqtt",
  )
  d5 = Device(
    id="zigbee2mqtt:Thermomètre de la chambre",
    name="Thermomètre de la chambre",
    provider="zigbee2mqtt",
  )
  d6 = Device(
    id="zigbee2mqtt:Interrupteur de la chambre",
    name="Interrupteur de la chambre",
    provider="zigbee2mqtt",
  )

  class TestProvider:
    provider_id = "zigbee2mqtt"

    async def list_devices(self):
      return [d1, d2, d3, d4, d5, d6]

    async def get_device(self, device_id):
      pass

    async def get_device_state(self, device_id):
      pass

    async def execute_action(self, device_id, action, value):
      pass

  registry = DeviceRegistry()
  registry.register(TestProvider())


@pytest.mark.asyncio
async def test_mcp_prompts(mcp_server):
  prompts = await mcp_server.list_prompts()
  assert {prompt.name for prompt in prompts} == {"control_devices", "summarize_devices"}

  # Test control_devices prompt
  result_control = await mcp_server.get_prompt("control_devices", {"command": "turn on the lamp"})
  assert len(result_control.messages) == 1
  assert result_control.messages[0].role == "user"
  assert "turn on the lamp" in result_control.messages[0].content.text

  # Test summarize_devices prompt
  result_summary = await mcp_server.get_prompt("summarize_devices", {})
  assert len(result_summary.messages) == 1
  assert result_summary.messages[0].role == "user"
  assert "list_devices" in result_summary.messages[0].content.text


@pytest.mark.asyncio
async def test_mcp_resources(mcp_server):
  # Test listing resources (only static ones appear in list_resources)
  resources = await mcp_server.list_resources()
  assert {str(r.uri) for r in resources} == {"device:///all"}

  # Test listing resource templates
  templates = await mcp_server.list_resource_templates()
  assert {t.uriTemplate for t in templates} == {"device:///{device_id}/metadata", "device:///{device_id}/state"}

  # Test reading device:///all resource
  contents_all = await mcp_server.read_resource("device:///all")
  assert len(contents_all) == 1
  import json

  devices = json.loads(contents_all[0].content)
  assert len(devices) == 1
  assert devices[0]["id"] == "fake:lamp"

  # Test reading device:///{device_id}/metadata resource
  contents_meta = await mcp_server.read_resource("device:///fake:lamp/metadata")
  assert len(contents_meta) == 1
  metadata = json.loads(contents_meta[0].content)
  assert metadata["id"] == "fake:lamp"
  assert metadata["name"] == "Lamp"

  # Test reading device:///{device_id}/metadata resource with URL-encoded device ID
  contents_meta_enc = await mcp_server.read_resource("device:///fake%3Alamp/metadata")
  assert len(contents_meta_enc) == 1
  metadata_enc = json.loads(contents_meta_enc[0].content)
  assert metadata_enc["id"] == "fake:lamp"

  # Test reading device:///{device_id}/state resource
  contents_state = await mcp_server.read_resource("device:///fake:lamp/state")
  assert len(contents_state) == 1
  state = json.loads(contents_state[0].content)
  assert state["device_id"] == "fake:lamp"
  assert state["values"]["state"] == "ON"

  # Test reading device:///{device_id}/state resource with URL-encoded device ID
  contents_state_enc = await mcp_server.read_resource("device:///fake%3Alamp/state")
  assert len(contents_state_enc) == 1
  state_enc = json.loads(contents_state_enc[0].content)
  assert state_enc["device_id"] == "fake:lamp"


def test_streamable_http_mcp_endpoint_is_mounted():

  with TestClient(create_app(Settings()), base_url="http://127.0.0.1:5089") as client:
    response = client.post(
      "/mcp",
      headers={"Accept": "application/json, text/event-stream"},
      json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
          "protocolVersion": "2025-06-18",
          "capabilities": {},
          "clientInfo": {"name": "test", "version": "1"},
        },
      },
    )

  assert response.status_code == 200
  assert response.json()["result"]["serverInfo"]["name"] == "Oremi Iṣakoso"
