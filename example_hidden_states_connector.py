"""Ascend NPU adaptation of vLLM's ``ExampleHiddenStatesConnector``.

The upstream connector uses ``torch.cuda.Stream`` / ``torch.cuda.Event``
for async D-to-H copies of hidden states. This subclass replaces those
with ``torch.npu`` equivalents so that the speculators training-data
generation pipeline (``extract_hidden_states`` spec-decode method) works
on Ascend NPU.
"""

import os
from typing import TYPE_CHECKING, Any

import torch
from vllm.config import VllmConfig
from vllm.distributed.kv_transfer.kv_connector.v1.base import KVConnectorRole
from vllm.distributed.kv_transfer.kv_connector.v1.example_hidden_states_connector import (  # noqa: E501
    ExampleHiddenStatesConnector,
)
from vllm.logger import logger

if TYPE_CHECKING:
    from vllm.v1.kv_cache_interface import KVCacheConfig


class AscendExampleHiddenStatesConnector(ExampleHiddenStatesConnector):
    """NPU-flavored ``ExampleHiddenStatesConnector``.

    Inherits all scheduler-side logic and the file-lock / thread-pool
    plumbing from upstream. Only the CUDA stream/event primitives used
    for async D-to-H copies are swapped for ``torch.npu`` equivalents.
    """

    def __init__(
        self,
        vllm_config: "VllmConfig",
        role: KVConnectorRole,
        kv_cache_config: "KVCacheConfig | None" = None,
    ) -> None:
        super().__init__(vllm_config, role, kv_cache_config)
        # Replace the CUDA stream placeholder with an NPU one (lazy init).
        self._copy_stream: torch.npu.Stream | None = None

    def _get_copy_stream(self) -> torch.npu.Stream:
        """Lazily create the copy stream (NPU must be initialized)."""
        if self._copy_stream is None:
            self._copy_stream = torch.npu.Stream()
        return self._copy_stream

    @staticmethod
    def _write_tensors(
        tensors: dict[str, torch.Tensor],
        event: torch.npu.Event,
        filename: str,
        lock_fd: int | None,
    ) -> None:
        """Thread worker: wait for async D-to-H copy, write to disk."""
        try:
            event.synchronize()
            from safetensors.torch import save_file

            save_file(tensors, filename)
        finally:
            if lock_fd is not None:
                os.close(lock_fd)

    def save_kv_layer(
        self,
        layer_name: str,
        kv_layer: torch.Tensor,
        attn_metadata: Any,
        **kwargs: Any,
    ) -> None:
        """Start saving the KV cache of the layer to the connector.

        Launches an async D-to-H copy on a dedicated NPU stream.
        Mirrors the upstream implementation but uses ``torch.npu``
        stream/event primitives.
        """
        if layer_name not in self.cache_layers:
            return

        from vllm.model_executor.models.extract_hidden_states import (
            CacheOnlyAttentionMetadata,
        )

        assert isinstance(attn_metadata, CacheOnlyAttentionMetadata), (
            "AscendExampleHiddenStatesConnector only supports "
            "CacheOnlyAttentionBackend"
        )

        from vllm.forward_context import get_forward_context

        connector_metadata = self._get_connector_metadata()
        assert isinstance(
            connector_metadata, type(self)._metadata_cls()
        ), "Connector metadata type mismatch"

        os.makedirs(self._storage_path, exist_ok=True)

        copy_stream = self._get_copy_stream()

        # Ensure the copy stream sees all prior writes on the default stream.
        ready_event = torch.npu.Event()
        ready_event.record()
        copy_stream.wait_event(ready_event)

        slot_mapping = get_forward_context().slot_mapping[layer_name]  # type: ignore
        offset = 0
        for request in connector_metadata.requests:
            num_tokens = request.token_ids.shape[0]
            with torch.npu.stream(copy_stream):
                req_slot_mapping_gpu = slot_mapping[offset : offset + num_tokens]
                assert req_slot_mapping_gpu.device == kv_layer.device
                offset += num_tokens

                hidden_states_gpu = self._extract_from_kv_cache(
                    kv_layer, req_slot_mapping_gpu, num_tokens
                )
                # Async D-to-H copy into host memory.
                pinned_hs = torch.empty_like(
                    hidden_states_gpu, device="cpu"
                )
                pinned_hs.copy_(hidden_states_gpu, non_blocking=True)

            # Record completion of this copy on the copy stream.
            copy_done = torch.npu.Event()
            copy_done.record(copy_stream)

            tensors = {
                "hidden_states": pinned_hs,
                "token_ids": request.token_ids.clone(),
            }
            self._pending_copies.append(
                (tensors, copy_done, request.filename, request.req_id)
            )

    @staticmethod
    def _metadata_cls():
        """Return the connector metadata class from upstream."""
        from vllm.distributed.kv_transfer.kv_connector.v1.example_hidden_states_connector import (  # noqa: E501
            ExampleHiddenStatesConnectorMetadata,
        )

        return ExampleHiddenStatesConnectorMetadata

    @staticmethod
    def _extract_from_kv_cache(
        kv_layer: torch.Tensor,
        slot_mapping: torch.Tensor,
        num_tokens: int,
    ) -> torch.Tensor:
        """Extract hidden states from the KV cache for the given slots."""
        block_size = kv_layer.shape[1]
        return kv_layer[slot_mapping // block_size, slot_mapping % block_size][:num_tokens]
