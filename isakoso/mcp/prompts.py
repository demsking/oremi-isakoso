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

from mcp.server.fastmcp import FastMCP
from mcp.types import PromptMessage
from mcp.types import TextContent
from pydantic import Field


def register_mcp_prompts(mcp: FastMCP) -> None:
  @mcp.prompt()
  def control_devices(
    command: Annotated[
      str,
      Field(description="The command or request to execute on the smart home devices, e.g., 'turn off the living room light'."),
    ],
  ) -> list[PromptMessage]:
    """Assist the user in managing and controlling smart home devices."""
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            f"The user wants to perform the following action: {command}\n\n"
            "Please execute this command by following these steps:\n"
            "1. Resolve any mentioned devices to their IDs using `search_devices`.\n"
            "2. If no devices match, ask the user for clarification.\n"
            "3. For each matched device, check its capabilities and latest state.\n"
            "4. Call the appropriate device-control tool (e.g. `turn_on`, `turn_off`, `set_brightness`, etc.) to execute the action.\n"
            "5. Confirm the action succeeded."
          ),
        ),
      )
    ]

  @mcp.prompt()
  def summarize_devices() -> list[PromptMessage]:
    """Assist in providing a summary of the current status of all smart home devices."""
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "Please provide a comprehensive summary of all smart home devices and their current states.\n\n"
            "To do this:\n"
            "1. Call `list_devices` to discover all registered devices.\n"
            "2. For each device, retrieve its latest state using `get_device_state`.\n"
            "3. Summarize their current status (e.g. which lights are ON, what the sensor readings are) in a clear, friendly format."
          ),
        ),
      )
    ]
