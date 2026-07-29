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
from typing import TYPE_CHECKING

import numpy as np
from fastembed import TextEmbedding

if TYPE_CHECKING:
  from isakoso.core.devices import Device


def get_device_passages(device: Device) -> list[str]:
  """Generate candidate passages for a device to maximize vector search recall."""
  passages: list[str] = [device.name]

  # Normalized ID passage (replace separators with spaces)
  normalized_id = device.id.replace(":", " ").replace("-", " ").replace("_", " ")

  if normalized_id.lower() != device.name.lower():
    passages.append(normalized_id)

  # Full combination passage
  passages.append(f"{device.name} ({normalized_id})")

  # Capability properties and descriptions
  cap_terms = []

  for cap in device.capabilities:
    if cap.property:
      cap_terms.append(cap.property)

    if cap.description:
      cap_terms.append(cap.description)

  if cap_terms:
    passages.append(" ".join(cap_terms))

  if device.manufacturer:
    passages.append(device.manufacturer)

  if device.model:
    passages.append(device.model)

  # Return unique non-empty passages
  unique_passages = []

  for p in passages:
    cleaned = p.strip()

    if cleaned and cleaned not in unique_passages:
      unique_passages.append(cleaned)

  return unique_passages


def _tokenize(text: str) -> set[str]:
  return set(re.findall(r"\w+", text.lower()))


class VectorSearchEngine:
  """High-performance vector search engine for smart home devices using semantic embeddings."""

  def __init__(self, model: TextEmbedding) -> None:
    self.model = model
    self._cache: dict[str, tuple[Device, np.ndarray, set[str]]] = {}

  def sync_devices(self, devices: list[Device]) -> None:
    """Synchronize the device vector index with a list of devices, embedding only new/changed devices."""
    current_ids = {d.id for d in devices}

    # Remove cached devices that are no longer present
    for cached_id in list(self._cache.keys()):
      if cached_id not in current_ids:
        del self._cache[cached_id]

    # Find devices that need embedding (either new ID or modified Device object)
    devices_to_embed: list[Device] = []

    for d in devices:
      cached_entry = self._cache.get(d.id)

      if cached_entry is None or cached_entry[0] != d:
        devices_to_embed.append(d)

    if not devices_to_embed:
      return

    all_passages: list[str] = []
    passage_counts: list[int] = []

    for d in devices_to_embed:
      passages = get_device_passages(d)
      passage_counts.append(len(passages))
      all_passages.extend(passages)

    if all_passages:
      embeddings_list = list(self.model.embed(all_passages))
      raw_matrix = np.array(embeddings_list, dtype=np.float32)

      # Normalize norms
      norms = np.linalg.norm(raw_matrix, axis=1, keepdims=True)
      norms[norms == 0] = 1.0
      normalized_matrix = raw_matrix / norms

      offset = 0

      for idx, d in enumerate(devices_to_embed):
        count = passage_counts[idx]
        d_matrix = normalized_matrix[offset : offset + count]
        offset += count

        dev_tokens = _tokenize(f"{d.name} {d.id} {d.manufacturer or ''} {d.model or ''}")
        self._cache[d.id] = (d, d_matrix, dev_tokens)

  def search(self, query: str, threshold: float = 0.25, top_k: int = 10) -> list[Device]:
    """Search for devices using semantic vector similarity and exact token boosting."""
    query = query.strip()

    if not self._cache or not query:
      return []

    query_embedding_list = list(self.model.embed([query]))
    q_vec = np.array(query_embedding_list[0], dtype=np.float32)
    q_norm = np.linalg.norm(q_vec)

    if q_norm > 0:
      q_vec = q_vec / q_norm

    query_tokens = _tokenize(query)
    scored_results: list[tuple[Device, float]] = []

    for device, d_matrix, dev_tokens in self._cache.values():
      # Max cosine similarity across all device candidate passages
      cos_sims = np.dot(d_matrix, q_vec)
      max_sim = float(np.max(cos_sims))

      # Token overlap boost
      overlap = query_tokens.intersection(dev_tokens)
      boost = 0.0

      if overlap and query_tokens:
        boost += 0.15 * (len(overlap) / len(query_tokens))

      q_lower = query.lower()

      if q_lower in device.name.lower() or q_lower in device.id.lower():
        boost += 0.20

      final_score = max_sim + boost

      if final_score >= threshold:
        scored_results.append((device, final_score))

    # Sort descending by score, then ascending by device name
    scored_results.sort(key=lambda item: (-item[1], item[0].name))

    return [device for device, _ in scored_results[:top_k]]
