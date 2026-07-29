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
import logging
import os
import warnings
from functools import cached_property
from functools import lru_cache
from pathlib import Path
from typing import Any
from typing import Literal

from fastembed import TextEmbedding
from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from isakoso.core.package import APP_NAME

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
  """Application configuration settings for Oremi Iṣakoso.

  All settings can be configured via environment variables.
  Service URLs are optional - if not provided, the service will run in chat-only mode.
  """

  model_config = SettingsConfigDict(
    env_prefix="OREMI_ISAKOSO_",
    strict=True,
    extra="ignore",
  )

  server_host: str = Field(
    default="127.0.0.1",
    description="Host address to bind the server to. Use '0.0.0.0' to listen on all interfaces.",
  )

  server_port: int = Field(
    default=5089,
    ge=1,
    le=65535,
    description="Port number to bind the server to. Must be between 1 and 65535.",
  )

  api_prefix: str = Field(default="/", description="API prefix for all endpoints.")

  embedding_model: str = Field(
    default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    description="FastEmbed model name used for semantic vector search.",
  )

  embedding_cache_dir: Path | None = Field(
    default=None,
    description="Directory path to store downloaded FastEmbed models. If not set, default system cache is used.",
  )

  mqtt_broker: str | None = Field(
    default=None,
    description="MQTT broker hostname or IP address. If not set, MQTT is disabled.",
  )

  mqtt_port: int = Field(
    default=1883,
    ge=1,
    le=65535,
    description="MQTT broker port. Must be between 1 and 65535. Default: 1883.",
  )

  mqtt_client_id: str | None = Field(
    default=None,
    description="MQTT client identifier. If not set, auto-generated from hostname and process ID.",
  )

  mqtt_username: str | None = Field(
    default=None,
    description="MQTT broker username. Optional - only needed if authentication is required.",
  )

  mqtt_password: str | None = Field(
    default=None,
    description="MQTT broker password. Optional - only needed if authentication is required.",
  )

  mqtt_keepalive: int = Field(
    default=60,
    ge=10,
    description="MQTT keepalive interval in seconds. Must be at least 10. Default: 60.",
  )

  mqtt_tls_ca_cert: str | None = Field(
    default=None,
    description="Path to CA certificate file for MQTT TLS verification.",
  )

  zigbee2mqtt_topic_prefix: str = Field(
    default="zigbee2mqtt/",
    description="Base MQTT topic used by Zigbee2MQTT. A trailing slash is added automatically.",
  )

  log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO", description="Logging level.")  # pyrefly: ignore [bad-assignment]
  log_file: str | None = Field(default=None, description="Path to rotating log file.")

  @cached_property
  def embedding_model_instance(self) -> TextEmbedding:
    """Lazy singleton loader for FastEmbed TextEmbedding model."""
    with warnings.catch_warnings():
      warnings.filterwarnings(
        "ignore",
        category=UserWarning,
        message=".*sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2.*",
      )
      return TextEmbedding(model_name=self.embedding_model, cache_dir=str(self.embedding_cache_dir))

  @field_validator("api_prefix")
  @classmethod
  def validate_api_prefix(cls, value: str) -> str:
    if not value.startswith("/"):
      raise ValueError("OREMI_ISAKOSO_API_PREFIX must start with '/'")

    return value.rstrip("/") or "/"

  @field_validator("embedding_cache_dir", mode="before")
  @classmethod
  def validate_embedding_cache_dir(cls, value: object) -> Path:
    if value is not None:
      if isinstance(value, str) and value:
        return Path(value)

      if isinstance(value, Path):
        return value

      raise ValueError("OREMI_ISAKOSO_EMBEDDING_CACHE_DIR must be a non-empty string")

    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME

  @field_validator("mqtt_broker", mode="before")
  @classmethod
  def validate_mqtt_broker(cls, value: str | None) -> str | None:
    """Normalize the MQTT broker to the hostname expected by Paho."""
    if value and isinstance(value, str):
      value = value.strip().rstrip("/")

      for scheme in ("mqtt://", "tcp://", "ssl://", "ws://", "wss://"):
        if value.startswith(scheme):
          value = value.removeprefix(scheme)
          break

      if not value or any(character in value for character in "/?#@"):
        raise ValueError("OREMI_ISAKOSO_MQTT_BROKER must contain only a hostname or IP address")

    return value

  @field_validator("mqtt_tls_ca_cert")
  @classmethod
  def validate_tls_cert(cls, value: str | None) -> str | None:
    """Validate TLS certificate file exists if provided."""
    if value and not os.path.isfile(value):
      raise ValueError(f"MQTT TLS CA certificate file not found: {value}")

    return value

  @field_validator("zigbee2mqtt_topic_prefix")
  @classmethod
  def validate_zigbee2mqtt_topic_prefix(cls, value: str) -> str:
    prefix = value.strip().strip("/")

    if not prefix or any(character in prefix for character in "#+"):
      raise ValueError("OREMI_ISAKOSO_ZIGBEE2MQTT_TOPIC_PREFIX must be a non-empty MQTT topic without wildcards")

    return f"{prefix}/"


@lru_cache
def get_settings() -> Settings:
  """Return cached application settings."""
  return Settings()


def _format(value: Any) -> str:
  if value is None:
    return "None"

  if isinstance(value, Path):
    return str(value)

  if isinstance(value, list):
    return ",".join(str(item) for item in value)

  return str(value)


SENSITIVE_FIELDS = {"mqtt_password", "mqtt_tls_ca_cert"}


def log_group(settings: Settings, name: str, *fields: str) -> None:
  """Log a group of related settings without exposing sensitive credentials."""
  values: list[str] = []

  for field in fields:
    value = getattr(settings, field)
    if field in SENSITIVE_FIELDS and value:
      formatted_val = "[set]"
    else:
      formatted_val = _format(value)

    values.append(f"{field}={formatted_val}")

  logger.info("%s settings: %s", name, " ".join(values))
