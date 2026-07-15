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
import logging
import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

import paho.mqtt.client as mqtt

from ..core.devices import Device
from ..core.devices import DeviceCapability
from ..core.devices import DeviceNotFoundError
from ..core.devices import DeviceState
from ..core.devices import OperationResult
from ..core.devices import UnsupportedOperationError
from ..core.mqtt import MQTTService

DEVICES_TOPIC = "zigbee2mqtt/bridge/devices"
DEVICE_MATCH_THRESHOLD = 0.72
DEVICE_SUGGESTION_THRESHOLD = 0.5
DEVICE_MATCH_MARGIN = 0.1
ZIGBEE_GET_ACCESS = 1
ZIGBEE_SET_ACCESS = 2

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ZigbeeOperation:
  property: str
  type: str
  description: str = ""
  values: tuple[Any, ...] = ()
  value_on: Any = None
  value_off: Any = None
  value_min: float | None = None
  value_max: float | None = None
  unit: str | None = None

  def as_catalog(self) -> dict[str, Any]:
    data: dict[str, Any] = {
      "property": self.property,
      "type": self.type,
    }

    if self.description:
      data["description"] = self.description

    if self.values:
      data["values"] = list(self.values)

    if self.value_on is not None:
      data["value_on"] = self.value_on

    if self.value_off is not None:
      data["value_off"] = self.value_off

    if self.value_min is not None:
      data["min"] = self.value_min

    if self.value_max is not None:
      data["max"] = self.value_max

    if self.unit:
      data["unit"] = self.unit

    return data


@dataclass(frozen=True, slots=True)
class ZigbeeState:
  property: str
  type: str
  description: str = ""
  values: tuple[Any, ...] = ()
  unit: str | None = None

  def as_catalog(self) -> dict[str, Any]:
    data: dict[str, Any] = {
      "property": self.property,
      "type": self.type,
    }

    if self.description:
      data["description"] = self.description

    if self.values:
      data["values"] = list(self.values)

    if self.unit:
      data["unit"] = self.unit

    return data


class Zigbee2MQTT:
  provider_id = "zigbee2mqtt"

  def __init__(self, mqtt_service: MQTTService, topic_prefix: str = "zigbee2mqtt/") -> None:
    self.mqtt = mqtt_service
    self.client = mqtt_service.client
    self.topic_prefix = topic_prefix.rstrip("/") + "/"
    self.devices_topic = f"{self.topic_prefix}bridge/devices"
    self.devices: dict[str, dict[str, Any]] = {}
    self.operations: dict[str, dict[str, ZigbeeOperation]] = {}
    self.states: dict[str, dict[str, ZigbeeState]] = {}
    self.device_states: dict[str, dict[str, Any]] = {}
    self._state_topics: dict[str, str] = {}
    self._device_index_key: tuple[Any, ...] = ()
    self._device_aliases: list[tuple[str, str, str, str]] = []
    self._device_catalog_key: tuple[Any, ...] = ()
    self._device_catalog_cache: list[dict[str, Any]] = []
    self._command_decision_cache: OrderedDict[str, Any] = OrderedDict()

  def start(self) -> None:
    self.mqtt.subscribe(self.devices_topic, self._update_devices)
    logger.info(f"Zigbee device discovery subscribed: topic={self.devices_topic}")

  def stop(self) -> None:
    self.mqtt.unsubscribe(self.devices_topic)

    for topic in list(self._state_topics):
      self.mqtt.unsubscribe(topic)

    self._state_topics = {}
    logger.info("Zigbee device discovery stopped")

  async def list_devices(self) -> list[Device]:
    """Return all discovered devices using provider-scoped stable identifiers."""
    return [self._as_device(name) for name in sorted(self.devices)]

  async def get_device(self, device_id: str) -> Device:
    """Return one discovered Zigbee2MQTT device."""
    return self._as_device(self._device_name(device_id))

  async def get_device_state(self, device_id: str) -> DeviceState:
    """Return the latest state received from the device's MQTT topic."""
    name = self._device_name(device_id)
    return DeviceState(device_id=self._scoped_id(name), values=dict(self.device_states.get(name, {})))

  async def execute_action(self, device_id: str, action: str, value: Any = None) -> OperationResult:
    """Validate and publish a provider-native action to Zigbee2MQTT."""
    name = self._device_name(device_id)
    requested_action = action.strip()
    operation = requested_action

    if requested_action in {"turn_on", "turn_off"}:
      operation = "state"
      value = "ON" if requested_action == "turn_on" else "OFF"
    elif requested_action == "set_brightness":
      operation = "brightness"
      exposed = self.operations.get(name, {}).get(operation)
      if exposed and exposed.value_max and exposed.value_max > 100:
        value = round(float(value) * exposed.value_max / 100)
    elif requested_action == "set_color":
      operation = "color"
    elif requested_action == "set_color_temperature":
      operation = "color_temp"
      value = round(1_000_000 / float(value))
    elif requested_action == "set_position":
      operation = "position"
    elif requested_action in {"lock", "unlock"}:
      operation = "state"
      value = "LOCK" if requested_action == "lock" else "UNLOCK"

    if requested_action == "toggle":
      state_operation = self.operations.get(name, {}).get("state")
      if state_operation is None:
        raise UnsupportedOperationError(f"{name} does not support toggle")
      payload = {"state": "TOGGLE"}
    else:
      payload = self._validate_payload(name, {operation: value})
      if not payload:
        raise UnsupportedOperationError(f"{name} does not support {operation!r} with value {value!r}")

    bridge_name = str(self.devices[name].get("friendly_name") or name)
    topic = f"{self.topic_prefix}{bridge_name}/set"
    result = self.client.publish(topic, json.dumps(payload, ensure_ascii=False))

    if result.rc != mqtt.MQTT_ERR_SUCCESS:
      raise RuntimeError(f"could not publish Zigbee2MQTT action: {mqtt.error_string(result.rc)}")

    self._merge_device_state(name, payload)
    return OperationResult(device_id=self._scoped_id(name), operation=requested_action, state=payload)

  def _device_name(self, device_id: str) -> str:
    native_id = device_id.removeprefix(f"{self.provider_id}:")
    _, resolved_name = self._resolve_device(native_id)
    if resolved_name not in self.devices:
      raise DeviceNotFoundError(f"Zigbee2MQTT device not found: {device_id}")
    return resolved_name

  def _scoped_id(self, name: str) -> str:
    return f"{self.provider_id}:{name}"

  def _as_device(self, name: str) -> Device:
    raw = self.devices.get(name)
    if raw is None:
      raise DeviceNotFoundError(f"Zigbee2MQTT device not found: {name}")

    definition: dict = raw.get("definition") if isinstance(raw.get("definition"), dict) else {}  # pyright: ignore
    capabilities = []
    properties = sorted(set(self.operations.get(name, {})) | set(self.states.get(name, {})))

    for property_name in properties:
      operation = self.operations.get(name, {}).get(property_name)
      state = self.states.get(name, {}).get(property_name)
      source = operation or state
      if source is None:
        continue
      capabilities.append(
        DeviceCapability(
          property=property_name,
          type=source.type,
          readable=state is not None,
          writable=operation is not None,
          description=source.description or None,
          unit=source.unit,
          values=list(getattr(source, "values", ())),
          minimum=getattr(operation, "value_min", None),
          maximum=getattr(operation, "value_max", None),
        )
      )

    return Device(
      id=self._scoped_id(name),
      name=name,
      provider=self.provider_id,
      manufacturer=raw.get("manufacturer") or definition.get("manufacturer"),
      model=raw.get("model") or raw.get("model_id") or definition.get("model"),
      capabilities=capabilities,
    )

  async def _update_devices(self, payload: bytes) -> None:
    try:
      device_list = json.loads(payload)

      if not isinstance(device_list, list):
        raise ValueError("device list must be an array")

      bridge_devices = []

      for device in device_list:
        if not isinstance(device, dict) or device.get("type") == "Coordinator":
          continue

        friendly_name = device.get("friendly_name")

        if isinstance(friendly_name, str) and friendly_name.strip():
          bridge_devices.append((friendly_name, device))

      devices = {}
      operations = {}
      states = {}

      for friendly_name, device in bridge_devices:
        if friendly_name in devices:
          logger.warning(f"Duplicate Zigbee device name ignored: {friendly_name}")
          continue

        devices[friendly_name] = device
        operations[friendly_name] = self._extract_operations(device)
        states[friendly_name] = self._extract_states(device)

        logger.info(
          f"Zigbee device found: name={friendly_name!r} ieee_address={device.get('ieee_address', 'unknown')!r} "
          f"operations={sorted(operations[friendly_name])} states={sorted(states[friendly_name])}"
        )

      self.devices = devices
      self.operations = operations
      self.states = states
      self.device_states = {name: self.device_states.get(name, {}) for name in devices}
      self._invalidate_catalog_indexes()

      self._sync_state_subscriptions(devices)
      logger.info(f"Loaded {len(devices)} Zigbee devices")
    except (json.JSONDecodeError, ValueError, TypeError) as exception:
      logger.warning(f"Ignoring invalid Zigbee device list: {exception}")

  def _resolve_device(self, name: str) -> tuple[str, str]:
    normalized = self._normalize(name)
    self._ensure_device_index()

    for alias, bridge_name, device_name, _ in self._device_aliases:
      if alias == normalized:
        return bridge_name, device_name

    return name, name

  def _device_catalog(self) -> list[dict[str, Any]]:
    key = self._catalog_key()

    if self._device_catalog_key == key:
      return list(self._device_catalog_cache)

    catalog = []

    for device_name, device in self.devices.items():
      friendly_name = str(device.get("friendly_name", ""))
      operation_catalog = [operation.as_catalog() for operation in self.operations.get(device_name, {}).values()]
      state_catalog = [state.as_catalog() for state in self.states.get(device_name, {}).values()]

      if not operation_catalog and not state_catalog:
        continue

      catalog.append(
        {
          "name": device_name,
          "mqtt_topic": friendly_name,
          "model": device.get("model") or device.get("model_id"),
          "manufacturer": device.get("manufacturer"),
          "operations": operation_catalog,
          "states": state_catalog,
        }
      )

    self._device_catalog_key = key
    self._device_catalog_cache = catalog

    return list(catalog)

  def _device_catalog_for(self, device_name: str) -> list[dict[str, Any]]:
    normalized = self._normalize(device_name)

    return [
      device
      for device in self._device_catalog()
      if self._normalize(str(device.get("name") or "")) == normalized
      or self._normalize(str(device.get("mqtt_topic") or "")) == normalized
    ]

  def _invalidate_catalog_indexes(self) -> None:
    self._device_index_key = ()
    self._device_aliases = []
    self._device_catalog_key = ()
    self._device_catalog_cache = []
    self._command_decision_cache.clear()

  def _index_key(self) -> tuple[Any, ...]:
    return tuple(
      sorted(
        (
          name,
          str(device.get("friendly_name") or ""),
          str(device.get("ieee_address") or ""),
        )
        for name, device in self.devices.items()
      )
    )

  def _catalog_key(self) -> tuple[Any, ...]:
    return tuple(
      sorted(
        (
          name,
          tuple(sorted(self.operations.get(name, {}))),
          tuple(sorted(self.states.get(name, {}))),
        )
        for name in self.devices
      )
    )

  def _ensure_device_index(self) -> None:
    key = self._index_key()

    if self._device_index_key == key:
      return

    aliases: list[tuple[str, str, str, str]] = []

    for device_name, device in self.devices.items():
      friendly_name = str(device.get("friendly_name") or "")
      ieee_address = str(device.get("ieee_address") or "")
      bridge_name = friendly_name or device_name

      for alias_type, alias in (("name", device_name), ("mqtt_topic", friendly_name), ("ieee_address", ieee_address)):
        normalized = self._normalize(alias) if alias_type != "ieee_address" else alias.casefold()

        if normalized:
          aliases.append((normalized, bridge_name, device_name, alias_type))

    self._device_index_key = key
    self._device_aliases = aliases

  def _extract_operations(self, device: dict[str, Any]) -> dict[str, ZigbeeOperation]:
    operations: dict[str, ZigbeeOperation] = {}
    exposes = self._device_exposes(device)

    if not isinstance(exposes, list):
      return operations

    for expose in exposes:
      self._collect_operations(expose, operations, inherited_access=None)

    return operations

  def _extract_states(self, device: dict[str, Any]) -> dict[str, ZigbeeState]:
    states: dict[str, ZigbeeState] = {}
    exposes = self._device_exposes(device)

    if not isinstance(exposes, list):
      return states

    for expose in exposes:
      self._collect_states(expose, states, inherited_access=None)

    return states

  @staticmethod
  def _device_exposes(device: dict[str, Any]) -> list[Any] | None:
    exposes = device.get("exposes")

    if isinstance(exposes, list):
      return exposes

    definition = device.get("definition")

    if isinstance(definition, dict) and isinstance(definition.get("exposes"), list):
      return definition["exposes"]

    return None

  def _collect_operations(
    self,
    expose: Any,
    operations: dict[str, ZigbeeOperation],
    *,
    inherited_access: Any,
  ) -> None:
    if not isinstance(expose, dict):
      return

    access = expose.get("access", inherited_access)
    features = expose.get("features")

    if isinstance(features, list):
      for feature in features:
        self._collect_operations(feature, operations, inherited_access=access)

    property_name = expose.get("property")

    if not isinstance(property_name, str) or not property_name:
      return

    if not self._is_settable(access):
      return

    operation = self._operation_from_expose(property_name, expose)

    if operation is not None:
      operations[property_name] = operation

  def _collect_states(
    self,
    expose: Any,
    states: dict[str, ZigbeeState],
    *,
    inherited_access: Any,
  ) -> None:
    if not isinstance(expose, dict):
      return

    access = expose.get("access", inherited_access)
    features = expose.get("features")

    if isinstance(features, list):
      for feature in features:
        self._collect_states(feature, states, inherited_access=access)

    property_name = expose.get("property")

    if not isinstance(property_name, str) or not property_name:
      return

    if not self._is_readable(access):
      return

    state = self._state_from_expose(property_name, expose)

    if state is not None:
      states[property_name] = state

  @staticmethod
  def _is_readable(access: Any) -> bool:
    if isinstance(access, bool):
      return access

    if isinstance(access, int):
      return bool(access & ZIGBEE_GET_ACCESS)

    return False

  @staticmethod
  def _is_settable(access: Any) -> bool:
    if isinstance(access, bool):
      return access

    if isinstance(access, int):
      return bool(access & ZIGBEE_SET_ACCESS)

    return False

  def _state_from_expose(self, property_name: str, expose: dict[str, Any]) -> ZigbeeState | None:
    expose_type = str(expose.get("type") or "unknown")
    description = str(expose.get("description") or "").strip()
    values = expose.get("values")

    return ZigbeeState(
      property=property_name,
      type=expose_type,
      description=description,
      values=tuple(values) if isinstance(values, list) else (),
      unit=str(expose.get("unit")) if expose.get("unit") is not None else None,
    )

  def _operation_from_expose(self, property_name: str, expose: dict[str, Any]) -> ZigbeeOperation | None:
    expose_type = str(expose.get("type") or "unknown")
    description = str(expose.get("description") or "").strip()

    if expose_type == "binary":
      return ZigbeeOperation(
        property=property_name,
        type=expose_type,
        description=description,
        value_on=expose.get("value_on"),
        value_off=expose.get("value_off"),
      )

    if expose_type == "enum":
      values = expose.get("values")
      if not isinstance(values, list) or not values:
        return None
      return ZigbeeOperation(
        property=property_name,
        type=expose_type,
        description=description,
        values=tuple(values),
      )

    if expose_type == "numeric":
      return ZigbeeOperation(
        property=property_name,
        type=expose_type,
        description=description,
        value_min=self._number_or_none(expose.get("value_min")),
        value_max=self._number_or_none(expose.get("value_max")),
        unit=str(expose.get("unit")) if expose.get("unit") is not None else None,
      )

    if expose_type in {"text", "composite"}:
      return ZigbeeOperation(property=property_name, type=expose_type, description=description)

    return None

  def _extract_device(self, texts: list[str]) -> tuple[str, str, str, float] | None:
    normalized_texts = [self._normalize(text) for text in texts if text]
    exact_matches = []
    self._ensure_device_index()

    for normalized_alias, bridge_name, device_name, alias_type in self._device_aliases:
      if alias_type == "ieee_address":
        continue

      if any(self._contains_phrase(text, normalized_alias) for text in normalized_texts):
        exact_matches.append((len(normalized_alias), bridge_name, device_name, f"{alias_type} exact", 1.0))

    if exact_matches:
      _, bridge_name, device_name, reason, score = max(exact_matches)
      return bridge_name, device_name, reason, score

    fuzzy_matches = self._device_candidates(normalized_texts)

    if not fuzzy_matches or fuzzy_matches[0][0] < DEVICE_MATCH_THRESHOLD:
      return None

    best_score, bridge_name, device_name = fuzzy_matches[0]
    runner_up_score = fuzzy_matches[1][0] if len(fuzzy_matches) > 1 else 0.0

    logger.debug(f"Zigbee fuzzy device candidates: best={device_name!r}:{best_score:.2f} runner_up={runner_up_score:.2f}")

    if best_score - runner_up_score < DEVICE_MATCH_MARGIN:
      logger.warning(
        f"Ambiguous Zigbee device name: best={device_name!r} score={best_score:.2f} runner_up_score={runner_up_score:.2f}"
      )
      return None

    return bridge_name, device_name, "fuzzy", best_score

  def _suggest_devices(self, texts: list[str]) -> list[str]:
    candidates = self._device_candidates([self._normalize(text) for text in texts if text])

    if not candidates or candidates[0][0] < DEVICE_SUGGESTION_THRESHOLD:
      return []

    best_score = candidates[0][0]

    return [
      device_name
      for score, _, device_name in candidates[:3]
      if score >= DEVICE_SUGGESTION_THRESHOLD and best_score - score <= DEVICE_MATCH_MARGIN
    ]

  def _device_candidates(self, normalized_texts: list[str]) -> list[tuple[float, str, str]]:
    candidates = []
    self._ensure_device_index()

    by_device: dict[str, tuple[str, set[str]]] = {}

    for alias, bridge_name, device_name, alias_type in self._device_aliases:
      if alias_type == "ieee_address":
        continue

      _, aliases = by_device.setdefault(device_name, (bridge_name, set()))
      aliases.add(alias)

    for device_name, (bridge_name, aliases) in by_device.items():
      score = max(
        (self._device_similarity(text, alias) for text in normalized_texts for alias in aliases if alias),
        default=0.0,
      )
      candidates.append((score, bridge_name, device_name))

    return sorted(candidates, reverse=True)

  def _device_similarity(self, text: str, alias: str) -> float:
    ignored_words = {
      "a",
      "an",
      "the",
      "to",
      "on",
      "off",
      "turn",
      "switch",
      "light",
      "lamp",
      "up",
      "allume",
      "allumer",
      "de",
      "du",
      "la",
      "lampe",
      "lampes",
      "le",
      "les",
      "lumiere",
      "lumieres",
    }
    text_tokens = {word for word in text.split() if word not in ignored_words}
    alias_tokens = {word for word in alias.split() if word not in ignored_words}
    token_score = len(text_tokens & alias_tokens) / len(alias_tokens) if alias_tokens else 0.0
    sequence_score = SequenceMatcher(None, text, alias).ratio()
    return max(token_score, sequence_score)

  def _device_exists(self, device_name: str) -> bool:
    normalized = self._normalize(device_name)
    self._ensure_device_index()

    return any(alias == normalized for alias, _, _, alias_type in self._device_aliases if alias_type != "ieee_address")

  def _available_device_names(self) -> list[str]:
    return sorted(self.devices)

  def _has_device_reference(self, texts: list[str]) -> bool:
    device_words = {
      "device",
      "heater",
      "interrupteur",
      "lamp",
      "lampe",
      "light",
      "lights",
      "lumiere",
      "lumieres",
      "plug",
      "prise",
      "radiateur",
      "switch",
      "thermostat",
    }

    return any(set(self._normalize(text).split()) & device_words for text in texts if text)

  def _requested_device_hint(self, texts: list[str]) -> str | None:
    for text in texts:
      if self._normalize(text):
        return text

    return None

  @staticmethod
  def _normalize(value: str) -> str:
    ascii_value = "".join(
      character for character in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", ascii_value).strip()

  @staticmethod
  def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
      return None

    try:
      return float(value)
    except (TypeError, ValueError):
      return None

  @staticmethod
  def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "

  def _sync_state_subscriptions(self, devices: dict[str, dict[str, Any]]) -> None:
    next_topics = {}

    for device_name, device in devices.items():
      friendly_name = str(device.get("friendly_name") or device_name)

      if not self.states.get(device_name):
        continue

      topic = f"{self.topic_prefix}{friendly_name}"
      next_topics[topic] = device_name

      if self._state_topics.get(topic) == device_name:
        continue

      self.mqtt.subscribe(topic, lambda payload, name=device_name: self._update_device_state(name, payload))

    for topic in set(self._state_topics) - set(next_topics):
      self.mqtt.unsubscribe(topic)

    self._state_topics = next_topics

  def _update_device_state(self, device_name: str, payload: bytes) -> None:
    try:
      state = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exception:
      logger.warning(f"Ignoring invalid Zigbee state payload: device={device_name!r} error={exception}")
      return

    if not isinstance(state, dict):
      logger.warning(f"Ignoring non-object Zigbee state payload: device={device_name!r}")
      return

    known_states = self.states.get(device_name, {})

    if not known_states:
      return

    cached = dict(self.device_states.get(device_name, {}))

    for property_name, value in state.items():
      if str(property_name) in known_states:
        cached[str(property_name)] = value

    self.device_states[device_name] = cached
    logger.debug(f"Zigbee state updated: device={device_name!r} keys={sorted(cached)}")

  async def _read_device_state(self, display_name: str, state_properties: Any) -> dict[str, Any]:
    readable_states = self.states.get(display_name, {})
    cached_state = self.device_states.get(display_name, {})
    requested = self._validate_state_properties(display_name, state_properties)

    if not requested:
      requested = [property_name for property_name in readable_states if property_name in cached_state]

    values = {property_name: cached_state[property_name] for property_name in requested if property_name in cached_state}

    if not values:
      return {"device": display_name, "required": ["state"]}

    return {"device": display_name, "state": values}

  def _validate_state_properties(self, display_name: str, state_properties: Any) -> list[str]:
    if not isinstance(state_properties, list):
      return []

    readable_states = self.states.get(display_name, {})
    requested = []

    for property_name in state_properties:
      normalized_property = str(property_name)

      if normalized_property in readable_states and normalized_property not in requested:
        requested.append(normalized_property)
      else:
        logger.warning(f"Ignoring unsupported Zigbee state for {display_name}: {property_name}")

    return requested

  def _merge_device_state(self, display_name: str, values: dict[str, Any]) -> None:
    known_states = self.states.get(display_name, {})

    if not known_states:
      return

    cached = dict(self.device_states.get(display_name, {}))

    for property_name, value in values.items():
      if property_name in known_states:
        cached[property_name] = value

    self.device_states[display_name] = cached

  def _validate_payload(self, display_name: str, payload: Any) -> dict[str, Any]:
    if not display_name or not isinstance(payload, dict):
      return {}

    operations = self.operations.get(display_name, {})
    validated = {}

    for property_name, value in payload.items():
      operation = operations.get(str(property_name))

      if operation is None:
        logger.warning(f"Ignoring unsupported Zigbee property for {display_name}: {property_name}")
        continue

      normalized_value = self._validate_value(operation, value)

      if normalized_value is not None:
        validated[operation.property] = normalized_value
      else:
        logger.warning(
          f"Ignoring invalid Zigbee value for {display_name}: property={operation.property} "
          f"value={value!r} operation={operation.as_catalog()!r}"
        )

    return validated

  def _validate_value(self, operation: ZigbeeOperation, value: Any) -> Any:
    if operation.type == "binary":
      if value in (operation.value_on, operation.value_off):
        return value

      if isinstance(value, bool):
        return operation.value_on if value else operation.value_off

      if isinstance(value, str):
        if isinstance(operation.value_on, str) and value.casefold() == operation.value_on.casefold():
          return operation.value_on

        if isinstance(operation.value_off, str) and value.casefold() == operation.value_off.casefold():
          return operation.value_off

      return None

    if operation.type == "enum":
      if value in operation.values:
        return value

      if isinstance(value, str):
        for option in operation.values:
          if isinstance(option, str) and value.casefold() == option.casefold():
            return option

      return None

    if operation.type == "numeric":
      if isinstance(value, bool):
        return None

      try:
        number = float(value)
      except (TypeError, ValueError):
        return None

      if operation.value_min is not None and number < operation.value_min:
        return None

      if operation.value_max is not None and number > operation.value_max:
        return None

      return int(number) if number.is_integer() else number

    if operation.type == "text":
      return value if isinstance(value, str) else None

    if operation.type == "composite":
      return value if isinstance(value, dict) else None

    return None
