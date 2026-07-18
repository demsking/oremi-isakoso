from typing import Any

import pytest
from fastapi.testclient import TestClient

from isakoso.core.app import create_app
from isakoso.core.devices import Device
from isakoso.core.devices import DeviceCapability
from isakoso.core.devices import DeviceRegistry
from isakoso.core.devices import DeviceState
from isakoso.core.devices import OperationResult
from mcp.server.fastmcp import FastMCP
from isakoso.server.tools import register_mcp_tools
from isakoso.server.prompts import register_mcp_prompts
from isakoso.server.resources import register_mcp_resources
from isakoso.core.settings import Settings


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
    "extract_devices_from_user_request",
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
async def test_mcp_search_devices(mcp_server):
  # Test searching for a device
  results = await mcp_server.call_tool("extract_devices_from_user_request", {"user_request": "lamp"})
  assert results[1]["result"][0]["id"] == "fake:lamp"

  # Test searching for a sensor property
  results = await mcp_server.call_tool("extract_devices_from_user_request", {"user_request": "temp"})
  assert results[1]["result"][0]["id"] == "fake:lamp"

  # Test non-matching query
  results = await mcp_server.call_tool("extract_devices_from_user_request", {"user_request": "nonexistent"})
  assert results[1]["result"] == []

  # Test empty query
  results = await mcp_server.call_tool("extract_devices_from_user_request", {"user_request": ""})
  assert results[1]["result"] == []


@pytest.mark.asyncio
async def test_mcp_hybrid_search(mcp_server):
  # Test searching/extracting with natural language command containing typos
  results = await mcp_server.call_tool("extract_devices_from_user_request", {"user_request": "turn on the lmp please"})
  assert results[1]["result"][0]["id"] == "fake:lamp"


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

  # Test typo matching
  results = await registry.search_devices("turn on livng room lamp")
  assert results == [d1]

  # Test multiple devices extraction and typo matching
  results = await registry.search_devices("turn off kitchn plug and living room lamp 1")
  assert {r.id for r in results} == {d1.id, d2.id}

  # Test another typo
  results = await registry.search_devices("is the bedrom light on?")
  assert results == [d3]

  # Test no match
  results = await registry.search_devices("nothing matches this text")
  assert results == []

  # Test fallback to keyword search index (living room has no noun/lamp, but matches index)
  results = await registry.search_devices("living room")
  assert results == [d1]

  # Test French device extraction
  results = await registry.search_devices("allume la lumière de la chambre")
  assert results == [d4]


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
  assert {str(r.uri) for r in resources} == {"devices:///all"}

  # Test listing resource templates
  templates = await mcp_server.list_resource_templates()
  assert {t.uriTemplate for t in templates} == {"devices:///{device_id}/metadata", "devices:///{device_id}/state"}

  # Test reading devices:///all resource
  contents_all = await mcp_server.read_resource("devices:///all")
  assert len(contents_all) == 1
  import json

  devices = json.loads(contents_all[0].content)
  assert len(devices) == 1
  assert devices[0]["id"] == "fake:lamp"

  # Test reading devices:///{device_id}/metadata resource
  contents_meta = await mcp_server.read_resource("devices:///fake:lamp/metadata")
  assert len(contents_meta) == 1
  metadata = json.loads(contents_meta[0].content)
  assert metadata["id"] == "fake:lamp"
  assert metadata["name"] == "Lamp"

  # Test reading devices:///{device_id}/metadata resource with URL-encoded device ID
  contents_meta_enc = await mcp_server.read_resource("devices:///fake%3Alamp/metadata")
  assert len(contents_meta_enc) == 1
  metadata_enc = json.loads(contents_meta_enc[0].content)
  assert metadata_enc["id"] == "fake:lamp"

  # Test reading devices:///{device_id}/state resource
  contents_state = await mcp_server.read_resource("devices:///fake:lamp/state")
  assert len(contents_state) == 1
  state = json.loads(contents_state[0].content)
  assert state["device_id"] == "fake:lamp"
  assert state["values"]["state"] == "ON"

  # Test reading devices:///{device_id}/state resource with URL-encoded device ID
  contents_state_enc = await mcp_server.read_resource("devices:///fake%3Alamp/state")
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
