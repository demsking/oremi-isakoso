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
import pytest

from isakoso.core.devices import Device
from isakoso.core.devices import DeviceCapability
from isakoso.core.devices import DeviceRegistry
from isakoso.core.embeddings import VectorSearchEngine
from isakoso.core.settings import get_settings


@pytest.fixture
def sample_devices():
  d1 = Device(
    id="zigbee2mqtt:living-room-lamp-1",
    name="Living Room Lamp 1",
    provider="zigbee2mqtt",
    manufacturer="Philips",
    model="Hue",
    capabilities=[DeviceCapability(property="state", type="binary", readable=True, writable=True)],
  )
  d2 = Device(
    id="zigbee2mqtt:chambre-lumiere",
    name="Lumière de la chambre",
    provider="zigbee2mqtt",
    manufacturer="IKEA",
    model="Tradfri",
    capabilities=[
      DeviceCapability(property="state", type="binary", readable=True, writable=True),
      DeviceCapability(property="brightness", type="numeric", readable=True, writable=True),
    ],
  )
  d3 = Device(
    id="zigbee2mqtt:chambre-thermometre",
    name="Thermomètre de la chambre",
    provider="zigbee2mqtt",
    manufacturer="Sonoff",
    capabilities=[
      DeviceCapability(property="temperature", type="numeric", readable=True, description="Indoor temperature sensor")
    ],
  )
  d4 = Device(
    id="zigbee2mqtt:kitchen-plug",
    name="Kitchen Smart Plug",
    provider="zigbee2mqtt",
    capabilities=[DeviceCapability(property="state", type="binary", readable=True, writable=True)],
  )
  return [d1, d2, d3, d4]


@pytest.fixture
def vector_engine(sample_devices):
  engine = VectorSearchEngine(get_settings().embedding_model_instance)
  engine.sync_devices(sample_devices)
  return engine


def test_vector_search_multilingual_english_to_french(vector_engine):
  results = vector_engine.search("turn on bedroom light")
  assert len(results) > 0
  assert results[0].id == "zigbee2mqtt:chambre-lumiere"


def test_vector_search_multilingual_french_to_english(vector_engine):
  results = vector_engine.search("prise de la cuisine")
  assert len(results) > 0
  assert results[0].id == "zigbee2mqtt:kitchen-plug"


def test_vector_search_typo_resilience(vector_engine):
  results = vector_engine.search("livng room lmp")
  assert len(results) > 0
  assert results[0].id == "zigbee2mqtt:living-room-lamp-1"


def test_vector_search_capability(vector_engine):
  results = vector_engine.search("temperature sensor in bedroom")
  assert len(results) > 0
  assert results[0].id == "zigbee2mqtt:chambre-thermometre"


@pytest.mark.asyncio
async def test_registry_search_devices(sample_devices):
  class DummyProvider:
    provider_id = "zigbee2mqtt"

    def __init__(self):
      self._callback = None

    def on_devices_changed(self, callback):
      self._callback = callback

    async def list_devices(self):
      return sample_devices

    async def get_device(self, device_id):
      pass

    async def get_device_state(self, device_id):
      pass

    async def execute_action(self, device_id, action, value):
      pass

  provider = DummyProvider()
  settings = get_settings()
  registry = DeviceRegistry(settings.embedding_model_instance)
  registry.register(provider)
  await registry.sync_search_index()

  # Search works instantly using vector index populated on sync
  results1 = await registry.search_devices("bedroom light")
  assert len(results1) > 0
  assert results1[0].id == "zigbee2mqtt:chambre-lumiere"

  # Test event trigger when provider device list changes
  cached_matrix = registry._search_engine._cache["zigbee2mqtt:chambre-lumiere"][1]

  # Trigger provider device update event
  assert provider._callback is not None
  provider._callback()
  await registry.sync_search_index()

  results2 = await registry.search_devices("temperature sensor")
  assert len(results2) > 0
  assert results2[0].id == "zigbee2mqtt:chambre-thermometre"
  assert registry._search_engine._cache["zigbee2mqtt:chambre-lumiere"][1] is cached_matrix
