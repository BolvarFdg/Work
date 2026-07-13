if not hasattr(self, "_dbg_hs_cnt"):
    self._dbg_hs_cnt = 0
if self._dbg_hs_cnt < 5:
    self._dbg_hs_cnt += 1
    # Check if hidden states differ across positions
    if sample_hidden_states.shape[0] > 1:
        _diff = (sample_hidden_states[0] - sample_hidden_states[1]).abs().max().item()
    else:
        _diff = -1.0
    logger.warning(
        "[DBG][hs] sample_hidden_states shape=%s absmax=%.4f mean=%.6f std=%.6f "
        "pos0_vs_pos1_diff=%.6f (diff=0 means all positions identical!)",
        list(sample_hidden_states.shape),
        sample_hidden_states.abs().max().item(),
        sample_hidden_states.float().mean().item(),
        sample_hidden_states.float().std().item(),
        _diff,
    )
