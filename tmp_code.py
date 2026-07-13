if self._dbg_precompute_cnt <= 5:
    logger.warning(
        "[DBG][precompute] AFTER RMSNorm: absmax=%.4f mean=%.6f std=%.6f "
        "hidden_norm_weight_absmax=%.4f",
        normed_context_states.abs().max().item(),
        normed_context_states.float().mean().item(),
        normed_context_states.float().std().item(),
        self._hidden_norm_weight.abs().max().item(),
    )