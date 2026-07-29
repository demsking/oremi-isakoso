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
import json
from typing import Any

import pytest

from isakoso.core.devices import DeviceNotFoundError
from isakoso.core.devices import UnsupportedOperationError
from isakoso.providers.zigbee2mqtt import DEVICES_TOPIC
from isakoso.providers.zigbee2mqtt import Zigbee2MQTT


class FakeMQTTService:
  def __init__(self):
    self.client: Any = FakeZigbeeClient()
    self.handlers = {}

  def subscribe(self, topic, handler):
    self.handlers[topic] = handler

  def unsubscribe(self, topic):
    self.handlers.pop(topic, None)


class FakeZigbeeClient:
  def __init__(self):
    self.published = []

  def publish(self, topic, payload):
    self.published.append((topic, payload))
    return type("PublishInfo", (), {"rc": 0})()


def light_device(friendly_name: str) -> dict[str, Any]:
  return {
    "friendly_name": friendly_name,
    "ieee_address": "0xa4c1385960a05c86",
    "definition": {
      "manufacturer": "Test",
      "model": "TS0505B",
      "exposes": [
        {
          "type": "light",
          "features": [
            {
              "type": "binary",
              "property": "state",
              "access": 7,
              "value_on": "ON",
              "value_off": "OFF",
              "description": "Turn the light on or off.",
            },
            {
              "type": "numeric",
              "property": "brightness",
              "access": 7,
              "value_min": 0,
              "value_max": 254,
              "description": "Brightness level.",
            },
            {"type": "composite", "property": "color", "access": 7},
            {"type": "numeric", "property": "color_temp", "access": 7, "value_min": 153, "value_max": 500},
          ],
        }
      ],
    },
  }


def configure(component: Zigbee2MQTT, devices: dict[str, dict[str, Any]]) -> None:
  component.devices = devices
  component.operations = {name: component._extract_operations(device) for name, device in devices.items()}
  component.states = {name: component._extract_states(device) for name, device in devices.items()}
  component.device_states = {name: {} for name in devices}


@pytest.mark.asyncio
async def test_zigbee_discovers_devices_and_subscribes_to_state_topics():
  mqtt = FakeMQTTService()
  component = Zigbee2MQTT(mqtt)
  component.start()

  await mqtt.handlers[DEVICES_TOPIC](
    json.dumps([{"type": "Coordinator", "friendly_name": "Coordinator"}, light_device("Living room")]).encode()
  )

  assert list(component.devices) == ["Living room"]
  assert set(component.operations["Living room"]) == {"state", "brightness", "color", "color_temp"}
  assert "zigbee2mqtt/Living room" in mqtt.handlers

  component.stop()
  assert mqtt.handlers == {}


@pytest.mark.asyncio
async def test_zigbee_uses_configured_topic_prefix_for_discovery_state_and_commands():
  mqtt = FakeMQTTService()
  component = Zigbee2MQTT(mqtt, "home/zigbee/")
  component.start()

  assert "home/zigbee/bridge/devices" in mqtt.handlers
  await mqtt.handlers["home/zigbee/bridge/devices"](json.dumps([light_device("Living room")]).encode())
  assert "home/zigbee/Living room" in mqtt.handlers

  await component.execute_action("zigbee2mqtt:Living room", "turn_on")
  assert mqtt.client.published == [("home/zigbee/Living room/set", '{"state": "ON"}')]


@pytest.mark.asyncio
async def test_provider_returns_strongly_typed_scoped_device_catalog():
  component = Zigbee2MQTT(FakeMQTTService())
  configure(component, {"Living room": light_device("Living room")})

  devices = await component.list_devices()

  assert len(devices) == 1
  assert devices[0].id == "zigbee2mqtt:Living room"
  assert devices[0].provider == "zigbee2mqtt"
  assert devices[0].manufacturer == "Test"
  assert devices[0].model == "TS0505B"
  assert {capability.property for capability in devices[0].capabilities} == {
    "brightness",
    "color",
    "color_temp",
    "state",
  }
  assert next(item for item in devices[0].capabilities if item.property == "brightness").maximum == 254


@pytest.mark.asyncio
async def test_provider_reads_only_advertised_state():
  mqtt = FakeMQTTService()
  component = Zigbee2MQTT(mqtt)
  component.start()
  await mqtt.handlers[DEVICES_TOPIC](json.dumps([light_device("Living room")]).encode())

  mqtt.handlers["zigbee2mqtt/Living room"](json.dumps({"state": "ON", "brightness": 42, "unknown": 1}).encode())
  state = await component.get_device_state("zigbee2mqtt:Living room")

  assert state.device_id == "zigbee2mqtt:Living room"
  assert state.values == {"state": "ON", "brightness": 42}


@pytest.mark.asyncio
async def test_provider_publishes_semantic_operations_and_updates_cache():
  mqtt = FakeMQTTService()
  component = Zigbee2MQTT(mqtt)
  configure(component, {"Living room": light_device("Living room")})

  on = await component.execute_action("zigbee2mqtt:Living room", "turn_on")
  brightness = await component.execute_action("zigbee2mqtt:Living room", "set_brightness", 50)
  color = await component.execute_action("zigbee2mqtt:Living room", "set_color", {"hex": "#336699"})
  temperature = await component.execute_action("zigbee2mqtt:Living room", "set_color_temperature", 4000)

  assert on.state == {"state": "ON"}
  assert brightness.state == {"brightness": 127}
  assert color.state == {"color": {"hex": "#336699"}}
  assert temperature.state == {"color_temp": 250}
  assert mqtt.client.published == [
    ("zigbee2mqtt/Living room/set", '{"state": "ON"}'),
    ("zigbee2mqtt/Living room/set", '{"brightness": 127}'),
    ("zigbee2mqtt/Living room/set", '{"color": {"hex": "#336699"}}'),
    ("zigbee2mqtt/Living room/set", '{"color_temp": 250}'),
  ]
  assert component.device_states["Living room"] == {
    "state": "ON",
    "brightness": 127,
    "color": {"hex": "#336699"},
    "color_temp": 250,
  }


@pytest.mark.asyncio
async def test_toggle_uses_zigbee2mqtt_native_command():
  mqtt = FakeMQTTService()
  component = Zigbee2MQTT(mqtt)
  configure(component, {"Living room": light_device("Living room")})

  result = await component.execute_action("Living room", "toggle")

  assert result.state == {"state": "TOGGLE"}
  assert mqtt.client.published == [("zigbee2mqtt/Living room/set", '{"state": "TOGGLE"}')]


@pytest.mark.asyncio
async def test_provider_rejects_unknown_devices_and_unadvertised_actions():
  component = Zigbee2MQTT(FakeMQTTService())
  configure(component, {"Living room": light_device("Living room")})

  with pytest.raises(DeviceNotFoundError):
    await component.get_device("zigbee2mqtt:Kitchen")

  with pytest.raises(UnsupportedOperationError):
    await component.execute_action("zigbee2mqtt:Living room", "position", 50)
