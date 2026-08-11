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
from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field


def register_mcp_prompts(mcp: MCPServer) -> None:
  @mcp.prompt(
    name="turn_on_device",
    title="Turn On a Device",
    description="Assist the user in turning on a device.",
  )
  def turn_on_device(
    command: Annotated[
      str,
      Field(description="The command or request to turn on the device."),
    ],
  ) -> str:
    return (
      f"The user wants to perform the following action: {command}\n\n"
      "Please execute this command directly:\n"
      "1. Resolve any mentioned devices to their IDs using `search_devices`.\n"
      "2. Call the `turn_on` tool with the matched `device_id` to turn on the device.\n"
      "3. Confirm to the user that the action succeeded."
    )

  @mcp.prompt(
    name="turn_off_device",
    title="Turn Off a Device",
    description="Assist the user in turning off a device.",
  )
  def turn_off_device(
    command: Annotated[
      str,
      Field(description="The command or request to turn off the device."),
    ],
  ) -> str:
    return (
      f"The user wants to perform the following action: {command}\n\n"
      "Please execute this command directly:\n"
      "1. Resolve any mentioned devices to their IDs using `search_devices`.\n"
      "2. Call the `turn_off` tool with the matched `device_id` to turn off the device.\n"
      "3. Confirm to the user that the action succeeded."
    )

  @mcp.prompt(
    name="toggle_device",
    title="Toggle Device",
    description="Assist the user in toggling a device.",
  )
  def toggle_device(
    command: Annotated[
      str,
      Field(description="The command or request to toggle the device."),
    ],
  ) -> str:
    return (
      f"The user wants to perform the following action: {command}\n\n"
      "Please execute this command directly:\n"
      "1. Resolve any mentioned devices to their IDs using `search_devices`.\n"
      "2. Call the `toggle` tool with the matched `device_id` to toggle the device.\n"
      "3. Confirm to the user that the action succeeded."
    )

  @mcp.prompt(
    name="set_device_brightness",
    title="Set Device Brightness",
    description="Assist the user in setting the brightness of a device.",
  )
  def set_device_brightness(
    command: Annotated[
      str,
      Field(description="The command or request to set the brightness of the device."),
    ],
  ) -> str:
    return (
      f"The user wants to perform the following action: {command}\n\n"
      "Please execute this command directly:\n"
      "1. Resolve any mentioned devices to their IDs using `search_devices`.\n"
      "2. Call the `set_brightness` tool with the matched `device_id` and the brightness level.\n"
      "3. Confirm to the user that the action succeeded."
    )

  @mcp.prompt(
    name="set_device_color",
    title="Set Device Color",
    description="Assist the user in setting the color of a device.",
  )
  def set_device_color(
    command: Annotated[
      str,
      Field(description="The command or request to set the color of the device."),
    ],
  ) -> str:
    return (
      f"The user wants to perform the following action: {command}\n\n"
      "Please execute this command directly:\n"
      "1. Resolve any mentioned devices to their IDs using `search_devices`.\n"
      "2. Call the `set_color` tool with the matched `device_id` and requested color.\n"
      "3. Confirm to the user that the action succeeded."
    )

  @mcp.prompt(
    name="set_device_color_temperature",
    title="Set Device Color Temperature",
    description="Assist the user in setting the color temperature of a device.",
  )
  def set_device_color_temperature(
    command: Annotated[
      str,
      Field(description="The command or request to set the color temperature of the device."),
    ],
  ) -> str:
    return (
      f"The user wants to perform the following action: {command}\n\n"
      "Please execute this command directly:\n"
      "1. Resolve any mentioned devices to their IDs using `search_devices`.\n"
      "2. Call the `set_color_temperature` tool with the matched `device_id` and requested color temperature.\n"
      "3. Confirm to the user that the action succeeded."
    )

  @mcp.prompt(
    name="read_sensor",
    title="Read Sensor",
    description="Assist the user in reading a sensor.",
  )
  def read_sensor(
    command: Annotated[
      str,
      Field(description="The command or request to read a sensor."),
    ],
  ) -> str:
    return (
      f"The user wants to perform the following action: {command}\n\n"
      "Please execute this command directly:\n"
      "1. Resolve any mentioned devices to their IDs using `search_devices`.\n"
      "2. Call the `read_sensor` tool with the matched `device_id` and requested sensor.\n"
      "3. Report the sensor reading value to the user."
    )

  @mcp.prompt(
    name="execute_action",
    title="Execute Action",
    description="Assist the user in executing an action on a device.",
  )
  def execute_action(
    command: Annotated[
      str,
      Field(description="The command or request to execute an action on a device."),
    ],
  ) -> str:
    return (
      f"The user wants to perform the following action: {command}\n\n"
      "Please execute this command directly:\n"
      "1. Resolve any mentioned devices to their IDs using `search_devices`.\n"
      "2. Call the `execute_action` tool with the matched `device_id` and requested action.\n"
      "3. Confirm to the user that the action succeeded."
    )

  @mcp.prompt(
    name="summarize_devices",
    title="Summarize Devices",
    description="Assist in providing a summary of the current status of all smart home devices.",
  )
  def summarize_devices() -> str:
    return (
      "Please provide a comprehensive summary of all smart home devices and their current states.\n\n"
      "To do this:\n"
      "1. Call `list_devices` to discover all registered devices.\n"
      "2. For each device, retrieve its latest state using `get_device_state`.\n"
      "3. Summarize their current status (e.g. which lights are ON, what the sensor readings are) in a clear, friendly format."
    )
