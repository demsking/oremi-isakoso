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
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

from isakoso.api import docs
from isakoso.api import health
from isakoso.core.devices import DeviceRegistry
from isakoso.core.mqtt import MQTTService
from isakoso.core.package import APP_DESCRIPTION
from isakoso.core.package import APP_DOCUMENTATION_URL
from isakoso.core.package import APP_NAME
from isakoso.core.package import APP_VERSION
from isakoso.core.settings import Settings
from isakoso.mcp.prompts import register_mcp_prompts
from isakoso.mcp.resources import register_mcp_resources
from isakoso.mcp.tools import register_mcp_tools
from isakoso.providers.zigbee2mqtt import Zigbee2MQTT
from isakoso.utils.context import set_app_context_mqtt
from isakoso.utils.logger import configure_logging


logger = logging.getLogger(__name__)


def log_startup_settings(settings: Settings) -> None:
  """Log every configured application setting without exposing secrets."""
  for name in settings.__class__.model_fields:
    value = getattr(settings, name)
    display_value = "[set]" if name in {"mqtt_password", "mqtt_tls_ca_cert"} and value else value
    logger.info("Setting %s: %s", name, display_value)


def create_app(settings: Settings) -> FastAPI:
  mqtt = MQTTService(settings)
  zigbee = Zigbee2MQTT(mqtt, settings.zigbee2mqtt_topic_prefix)

  device_registry = DeviceRegistry()
  device_registry.register(zigbee)

  @asynccontextmanager
  async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    startup_started = perf_counter()
    ready = False

    configure_logging(settings.log_level, settings.log_file)

    logger.info(f"{APP_NAME} v{APP_VERSION}")
    log_startup_settings(settings)

    set_app_context_mqtt(app, mqtt)

    zigbee_started = False

    try:
      mqtt_ready = await mqtt.start()

      if mqtt_ready:
        zigbee.start()
        zigbee_started = True
      else:
        logger.info("Zigbee startup skipped: MQTT is disabled")

      _ = mcp.streamable_http_app()
      async with mcp.session_manager.run():
        ready = True
        logger.info(
          f"Oremi Iṣakoso ready: "
          f"mqtt={'connected' if mqtt_ready else 'disabled'} "
          f"duration_ms={(perf_counter() - startup_started) * 1000:.1f}"
        )

        yield
    finally:
      shutdown_started = perf_counter()

      if ready:
        logger.info("Shutting down Oremi Iṣakoso")
      else:
        logger.warning("Oremi Iṣakoso startup aborted; cleaning up resources")

      if zigbee_started:
        zigbee.stop()

      mqtt.stop()
      logger.info(f"Oremi Iṣakoso stopped: duration_ms={(perf_counter() - shutdown_started) * 1000:.1f}")

  app = FastAPI(
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
    title="Oremi Iṣakoso",
    version=APP_VERSION,
    description=APP_DESCRIPTION,
    root_path=settings.api_prefix,
    servers=[
      {"url": settings.api_prefix},
    ],
    license_info={
      "name": "Apache 2.0",
      "url": "http://www.apache.org/licenses/LICENSE-2.0.html",
    },
    openapi_tags=[
      health.API_TAG_METADATA,
    ],
  )

  mcp = FastMCP(
    name="Oremi Iṣakoso",
    instructions=(
      "Discover and control smart-home devices. Call list_devices before control operations, "
      "use the returned provider-scoped device id, and inspect capabilities before choosing a tool."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/mcp",
    website_url=APP_DOCUMENTATION_URL,
  )

  @app.exception_handler(Exception)
  async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application error")
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "error": str(exc)})

  @app.get("/", include_in_schema=False)
  async def redirect_to_docs() -> HTMLResponse:
    return HTMLResponse(status_code=307, headers={"Location": prefix + docs.router.prefix})

  prefix = "" if settings.api_prefix == "/" else settings.api_prefix

  app.include_router(health.router, prefix=prefix)
  app.include_router(docs.router, prefix=prefix)

  register_mcp_prompts(mcp)
  register_mcp_resources(mcp, device_registry)
  register_mcp_tools(mcp, device_registry)

  app.mount(settings.api_prefix, mcp.streamable_http_app(), name="mcp")

  return app
