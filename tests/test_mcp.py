from typing import Any

import pytest
from fastapi.testclient import TestClient

from isakoso.core.app import create_app
from isakoso.core.devices import Device
from isakoso.core.devices import DeviceCapability
from isakoso.core.devices import DeviceRegistry
from isakoso.core.devices import DeviceSearchIndex
from isakoso.core.devices import DeviceState
from isakoso.core.devices import OperationResult
from isakoso.core.server import create_mcp_server
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
  return create_mcp_server(registry)


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
async def test_mcp_search_devices(mcp_server):
  # Test searching for a device
  results = await mcp_server.call_tool("search_devices", {"query": "lamp"})
  assert results[1]["result"][0]["id"] == "fake:lamp"

  # Test searching for a sensor property
  results = await mcp_server.call_tool("search_devices", {"query": "temp"})
  assert results[1]["result"][0]["id"] == "fake:lamp"

  # Test non-matching query
  results = await mcp_server.call_tool("search_devices", {"query": "nonexistent"})
  assert results[1]["result"] == []

  # Test empty query
  results = await mcp_server.call_tool("search_devices", {"query": ""})
  assert results[1]["result"] == []


def test_device_search_index_accuracy():
  d1 = Device(
    id="zigbee2mqtt:living-room-lamp",
    name="Living Room Lamp",
    provider="zigbee2mqtt",
    manufacturer="IKEA",
    model="TRADFRI bulb E27",
    capabilities=[
      DeviceCapability(property="state", type="binary", description="Turn light on/off"),
      DeviceCapability(property="brightness", type="numeric"),
    ],
  )
  d2 = Device(
    id="zigbee2mqtt:kitchen-plug",
    name="Kitchen Smart Plug",
    provider="zigbee2mqtt",
    manufacturer="Philips",
    model="Hue plug",
    capabilities=[
      DeviceCapability(property="state", type="binary", description="Control outlet state"),
    ],
  )

  index = DeviceSearchIndex([d1, d2])

  # Multi-token search (both words must match in any field of the device)
  results = index.search("living room")
  assert results == [d1]

  results = index.search("ikea lamp")
  assert results == [d1]

  # Prefix and case insensitive matching
  results = index.search("trad")
  assert results == [d1]

  # Capability property and type match
  results = index.search("numeric")
  assert results == [d1]

  # No matches
  results = index.search("bedroom")
  assert results == []

  # Weight ranking: name matches rank higher than model/description matches
  d3 = Device(
    id="zigbee2mqtt:test-device",
    name="Hue Bulb",
    provider="zigbee2mqtt",
    manufacturer="Philips",
    model="TRADFRI E14",
    capabilities=[],
  )
  # d1 model is "TRADFRI bulb E27", d3 name is "Hue Bulb"
  # Let's search "bulb"
  index_ranking = DeviceSearchIndex([d1, d3])
  results_ranking = index_ranking.search("bulb")
  # d3 has "Bulb" in the name (weight 10 * 3 = 30), d1 has "bulb" in model (weight 5 * 3 = 15).
  # d3 should be ranked first!
  assert results_ranking == [d3, d1]


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
