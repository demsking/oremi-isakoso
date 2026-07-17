from typing import Any

import pytest
from fastapi.testclient import TestClient

from isakoso.core.app import create_app
from isakoso.core.devices import Device
from isakoso.core.devices import DeviceCapability
from isakoso.core.devices import DeviceRegistry
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
