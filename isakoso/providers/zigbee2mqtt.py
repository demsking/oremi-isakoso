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
from dataclasses import dataclass
from typing import Any
from typing import Callable

import paho.mqtt.client as mqtt

from isakoso.core.devices import Device
from isakoso.core.devices import DeviceCapability
from isakoso.core.devices import DeviceNotFoundError
from isakoso.core.devices import DeviceState
from isakoso.core.devices import OperationResult
from isakoso.core.devices import UnsupportedOperationError
from isakoso.core.mqtt import MQTTService

DEVICES_TOPIC = "zigbee2mqtt/bridge/devices"
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
    self._on_devices_changed_listeners: list[Callable[[], Any]] = []

  def on_devices_changed(self, callback: Callable[[], Any]) -> None:
    """Register a listener callback to be notified when the device list changes."""
    self._on_devices_changed_listeners.append(callback)


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

    raw_definition = raw.get("definition")
    definition: dict[str, Any] = raw_definition if isinstance(raw_definition, dict) else {}
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

      for callback in list(self._on_devices_changed_listeners):
        try:
          callback()
        except Exception as err:
          logger.error(f"Error in on_devices_changed listener: {err}")
    except (json.JSONDecodeError, ValueError, TypeError) as exception:
      logger.warning(f"Ignoring invalid Zigbee device list: {exception}")

  def _resolve_device(self, name: str) -> tuple[str, str]:
    normalized = self._normalize(name)
    self._ensure_device_index()

    for alias, bridge_name, device_name, _ in self._device_aliases:
      if alias == normalized:
        return bridge_name, device_name

    return name, name

  def _invalidate_catalog_indexes(self) -> None:
    self._device_index_key = ()
    self._device_aliases = []

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

    if isinstance(definition, dict):
      def_exposes = definition.get("exposes")

      if isinstance(def_exposes, list):
        return def_exposes

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

      def make_handler(name: str) -> Callable[[bytes], None]:
        def handler(payload: bytes) -> None:
          self._update_device_state(name, payload)

        return handler

      self.mqtt.subscribe(topic, make_handler(device_name))

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
