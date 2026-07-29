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
from __future__ import annotations

import asyncio
from typing import Any
from typing import Protocol
from typing import runtime_checkable

from fastembed import TextEmbedding
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from isakoso.core.embeddings import VectorSearchEngine


class DeviceError(RuntimeError):
  """Base error returned by a smart-home provider."""


class DeviceNotFoundError(DeviceError):
  """Raised when no provider owns the requested device."""


class UnsupportedOperationError(DeviceError):
  """Raised when a device does not expose an operation."""


class DeviceCapability(BaseModel):
  """A readable or writable property exposed by a device."""

  model_config = ConfigDict(extra="forbid")

  property: str = Field(description="Provider-native property name.")
  type: str = Field(description="Value type, such as binary, numeric, enum, text, or composite.")
  readable: bool = Field(default=False, description="Whether the property can be read.")
  writable: bool = Field(default=False, description="Whether the property can be changed.")
  description: str | None = None
  unit: str | None = None
  values: list[Any] = Field(default_factory=list)
  minimum: float | None = None
  maximum: float | None = None


class DeviceSummary(BaseModel):
  """Lightweight summary of a smart-home device for quick listing."""

  model_config = ConfigDict(extra="forbid")

  id: str = Field(description="Stable provider-scoped identifier accepted by all device tools.")
  name: str = Field(description="Human-readable device name.")
  provider: str = Field(description="Provider that owns this device, for example zigbee2mqtt.")
  capabilities: list[str] = Field(
    default_factory=list,
    description="List of capability property names exposed by the device, e.g. ['state', 'brightness'].",
  )


class Device(BaseModel):
  """Protocol-neutral description of a smart-home device."""

  model_config = ConfigDict(extra="forbid")

  id: str = Field(description="Stable provider-scoped identifier accepted by all device tools.")
  name: str = Field(description="Human-readable device name.")
  provider: str = Field(description="Provider that owns this device, for example zigbee2mqtt.")
  manufacturer: str | None = None
  model: str | None = None
  capabilities: list[DeviceCapability] = Field(default_factory=list)

  def to_summary(self) -> DeviceSummary:
    return DeviceSummary(
      id=self.id,
      name=self.name,
      provider=self.provider,
      capabilities=[cap.property for cap in self.capabilities],
    )


class DeviceState(BaseModel):
  """Latest state reported by a device."""

  model_config = ConfigDict(extra="forbid")

  device_id: str
  values: dict[str, Any]


class OperationResult(BaseModel):
  """Result of a device mutation."""

  model_config = ConfigDict(extra="forbid")

  device_id: str
  operation: str
  accepted: bool = True
  state: dict[str, Any] = Field(default_factory=dict)


class SensorReading(BaseModel):
  """One sensor measurement and its optional unit."""

  model_config = ConfigDict(extra="forbid")

  device_id: str
  sensor: str
  value: Any
  unit: str | None = None


class ColorValue(BaseModel):
  """A color expressed as a hex value or RGB channels."""

  model_config = ConfigDict(extra="forbid")

  hex: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$", description="Color in #RRGGBB form.")
  red: int | None = Field(default=None, ge=0, le=255)
  green: int | None = Field(default=None, ge=0, le=255)
  blue: int | None = Field(default=None, ge=0, le=255)

  def as_provider_value(self) -> dict[str, Any]:
    if self.hex is not None:
      return {"hex": self.hex}
    if None not in (self.red, self.green, self.blue):
      return {"r": self.red, "g": self.green, "b": self.blue}
    raise ValueError("color requires either hex or all red, green, and blue channels")


@runtime_checkable
class DeviceProvider(Protocol):
  """Extension point implemented by Zigbee2MQTT, Matter, Z-Wave, Wi-Fi, and BLE adapters."""

  provider_id: str

  async def list_devices(self) -> list[Device]: ...
  async def get_device(self, device_id: str) -> Device: ...
  async def get_device_state(self, device_id: str) -> DeviceState: ...
  async def execute_action(self, device_id: str, action: str, value: Any) -> OperationResult: ...


class DeviceRegistry:
  """Routes provider-neutral operations to independently pluggable providers."""

  def __init__(self, model: TextEmbedding) -> None:
    self._providers: dict[str, DeviceProvider] = {}
    self._search_engine = VectorSearchEngine(model)
    self._background_tasks: set[asyncio.Task[None]] = set()

  def register(self, provider: DeviceProvider) -> None:
    if provider.provider_id in self._providers:
      raise ValueError(f"device provider already registered: {provider.provider_id}")

    self._providers[provider.provider_id] = provider

    if hasattr(provider, "on_devices_changed") and callable(getattr(provider, "on_devices_changed")):
      provider.on_devices_changed(self._handle_devices_changed)

    self._schedule_sync_search_index()

  def _handle_devices_changed(self) -> None:
    """Callback triggered when a provider's device list changes."""
    self._schedule_sync_search_index()

  def _schedule_sync_search_index(self) -> None:
    """Schedule background synchronization of vector search index."""
    try:
      loop = asyncio.get_running_loop()
      task = loop.create_task(self.sync_search_index())

      self._background_tasks.add(task)
      task.add_done_callback(self._background_tasks.discard)
    except RuntimeError:
      pass

  async def sync_search_index(self) -> None:
    """Synchronize vector search index with current registered devices."""
    devices = await self.list_devices()
    self._search_engine.sync_devices(devices)

  async def list_devices(self, provider: str | None = None) -> list[Device]:
    if provider is not None:
      selected = self._providers.get(provider)

      if selected is None:
        raise DeviceNotFoundError(f"unknown device provider: {provider}")

      return await selected.list_devices()

    devices: list[Device] = []

    for selected in self._providers.values():
      devices.extend(await selected.list_devices())

    return devices

  def provider_for(self, device_id: str) -> DeviceProvider:
    provider_id, separator, _ = device_id.partition(":")

    if separator:
      provider = self._providers.get(provider_id)

      if provider is not None:
        return provider

      raise DeviceNotFoundError(f"unknown device provider in id: {device_id}")

    # Native names remain accepted while only one provider is installed.
    if len(self._providers) == 1:
      return next(iter(self._providers.values()))

    raise DeviceNotFoundError("device_id must be provider-scoped, for example zigbee2mqtt:living-room")

  async def get_device(self, device_id: str) -> Device:
    return await self.provider_for(device_id).get_device(device_id)

  async def get_device_state(self, device_id: str) -> DeviceState:
    return await self.provider_for(device_id).get_device_state(device_id)

  async def execute_action(self, device_id: str, action: str, value: Any = None) -> OperationResult:
    return await self.provider_for(device_id).execute_action(device_id, action, value)

  async def search_devices(self, query: str) -> list[Device]:
    """Search registered devices using multilingual semantic vector embeddings."""
    if not query.strip():
      return []

    return self._search_engine.search(query)
