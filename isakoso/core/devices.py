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

import re
from typing import Any
from typing import Protocol
from typing import runtime_checkable

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from rapidfuzz import fuzz


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


_STOP_WORDS = {
  # French stop words
  "de",
  "la",
  "le",
  "les",
  "un",
  "une",
  "des",
  "du",
  "en",
  "dans",
  "par",
  "pour",
  "avec",
  "et",
  "ou",
  "sur",
  "sous",
  "ce",
  "cette",
  "ces",
  "mon",
  "ma",
  "mes",
  "ton",
  "ta",
  "tes",
  "son",
  "sa",
  "ses",
  "notre",
  "votre",
  "leur",
  "nos",
  "vos",
  "leurs",
  "au",
  "aux",
  "d",
  "l",
  # English stop words
  "of",
  "the",
  "a",
  "an",
  "in",
  "on",
  "at",
  "for",
  "to",
  "and",
  "or",
  "with",
  "by",
  "from",
  "up",
  "about",
  "into",
  "over",
  "after",
  "is",
  "are",
  "was",
  "were",
  "be",
  "been",
  "being",
  "my",
  "your",
  "his",
  "her",
  "its",
  "our",
  "their",
}


def _tokenize_with_accents(text: str | None) -> list[str]:
  if not text:
    return []
  normalized = re.sub(r"[^a-zA-Z0-9àâäéèêëîïôöùûüç]", " ", text.lower())
  return [t for t in normalized.split() if t]


def _tokenize(text: str | None) -> list[str]:
  if not text:
    return []
  normalized = re.sub(r"[^a-zA-Z0-9]", " ", text.lower())
  return [t for t in normalized.split() if t]


class DeviceSearchIndex:
  """An in-memory search index for devices offering tokenized, weighted search."""

  def __init__(self, devices: list[Device]) -> None:
    self.devices = devices
    self._index = []
    for device in devices:
      # Map field names to their tokenized values
      fields = {
        "name": _tokenize(device.name),
        "id": _tokenize(device.id),
        "model": _tokenize(device.model),
        "manufacturer": _tokenize(device.manufacturer),
        "provider": _tokenize(device.provider),
        "cap_property": [t for cap in device.capabilities for t in _tokenize(cap.property)],
        "cap_type": [t for cap in device.capabilities for t in _tokenize(cap.type)],
        "cap_desc": [t for cap in device.capabilities for t in _tokenize(cap.description)],
      }
      self._index.append((device, fields))

  def search(self, query: str) -> list[Device]:
    query_tokens = _tokenize(query)
    if not query_tokens:
      return []

    results = []
    # Weights for different fields
    weights = {
      "name": 10,
      "id": 8,
      "model": 5,
      "manufacturer": 4,
      "provider": 3,
      "cap_property": 3,
      "cap_type": 1,
      "cap_desc": 1,
    }

    for device, fields in self._index:
      device_matches_all_query_tokens = True
      device_score = 0

      for q_token in query_tokens:
        token_matched = False
        best_token_score = 0

        # Check each field for matches with this query token
        for field_name, tokens in fields.items():
          field_weight = weights[field_name]
          for token in tokens:
            if q_token == token:
              # Exact match
              score = field_weight * 3
              best_token_score = max(best_token_score, score)
              token_matched = True
            elif token.startswith(q_token):
              # Prefix match
              score = field_weight * 2
              best_token_score = max(best_token_score, score)
              token_matched = True
            elif q_token in token:
              # Substring match
              score = field_weight * 1
              best_token_score = max(best_token_score, score)
              token_matched = True

        if not token_matched:
          device_matches_all_query_tokens = False
          break

        device_score += best_token_score

      if device_matches_all_query_tokens:
        results.append((device, device_score))

    # Sort results by score (descending), then by name (ascending)
    results.sort(key=lambda item: (-item[1], item[0].name))
    return [item[0] for item in results]


class DeviceRegistry:
  """Routes provider-neutral operations to independently pluggable providers."""

  def __init__(self) -> None:
    self._providers: dict[str, DeviceProvider] = {}

  def register(self, provider: DeviceProvider) -> None:
    if provider.provider_id in self._providers:
      raise ValueError(f"device provider already registered: {provider.provider_id}")

    self._providers[provider.provider_id] = provider

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
    """Extract devices whose names are mentioned in the text, allowing for typo errors."""
    devices = await self.list_devices()
    text_tokens = _tokenize_with_accents(query)
    if not text_tokens:
      return []

    matched_devices = []
    for device in devices:
      name_tokens = _tokenize_with_accents(device.name)
      K = len(name_tokens)
      if K == 0:
        continue

      # Filter out stop words for content-matching
      content_tokens = [t for t in name_tokens if t not in _STOP_WORDS]
      if not content_tokens:
        content_tokens = name_tokens

      # Find how many content words have a high-similarity match in the input text
      matched_content_count = 0
      for ct in content_tokens:
        for tt in text_tokens:
          if fuzz.ratio(ct, tt) >= 80.0:
            matched_content_count += 1
            break

      match_ratio = matched_content_count / len(content_tokens)
      required_ratio = 1.0 if len(content_tokens) == 1 else 0.6

      # Check the last word/penultimate word of the device name specifically
      last_word_ok = False
      check_words = [name_tokens[-1]]
      if len(name_tokens) >= 2 and name_tokens[-1].isdigit():
        check_words.append(name_tokens[-2])

      for cw in check_words:
        for tt in text_tokens:
          if fuzz.ratio(cw, tt) >= 80.0:
            last_word_ok = True
            break
        if last_word_ok:
          break

      # Compute overall sliding window match ratio for ranking
      best_ratio = 0.0
      min_size = max(1, K - 1)
      if K >= 3:
        min_size = max(1, K - 2)

      for w_size in range(min_size, min(len(text_tokens) + 1, K + 2)):
        for i in range(len(text_tokens) - w_size + 1):
          window = text_tokens[i : i + w_size]
          window_str = " ".join(window)
          name_str = " ".join(name_tokens)
          ratio = fuzz.ratio(window_str, name_str)
          if ratio > best_ratio:
            best_ratio = ratio

      if match_ratio >= required_ratio and last_word_ok:
        matched_devices.append((device, best_ratio))

    matched_devices.sort(key=lambda x: (-x[1], x[0].name))

    results = [device for device, _ in matched_devices]

    if not results:
      index = DeviceSearchIndex(devices)
      return index.search(query)

    return results
