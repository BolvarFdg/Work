        # Check ALL critical draft weights
        _m = self.model.model  # DFlashQwen3Model
        _w_checks = {}
        # hidden_norm
        _w_checks["hidden_norm"] = (_m.hidden_norm.weight.data, "ones?")
        # final norm
        if hasattr(_m, "norm"):
            _w_checks["norm"] = (_m.norm.weight.data, "ones?")
        # first layer attention + mlp
        if len(_m.layers) > 0:
            _lyr = _m.layers[0]
            if hasattr(_lyr.self_attn, "qkv_proj"):
                _w_checks["qkv_proj"] = (_lyr.self_attn.qkv_proj.weight.data, "random?")
            if hasattr(_lyr.self_attn, "o_proj"):
                _w_checks["o_proj"] = (_lyr.self_attn.o_proj.weight.data, "random?")
            if hasattr(_lyr.mlp, "gate_up_proj"):
                _w_checks["gate_up_proj"] = (_lyr.mlp.gate_up_proj.weight.data, "random?")
            if hasattr(_lyr.mlp, "down_proj"):
                _w_checks["down_proj"] = (_lyr.mlp.down_proj.weight.data, "random?")
            if hasattr(_lyr, "input_layernorm"):
                _w_checks["input_layernorm"] = (_lyr.input_layernorm.weight.data, "ones?")
            if hasattr(_lyr, "post_attention_layernorm"):
                _w_checks["post_attn_norm"] = (_lyr.post_attention_layernorm.weight.data, "ones?")
        # lm_head
        if hasattr(self.model, "lm_head"):
            _w_checks["lm_head"] = (self.model.lm_head.weight.data, "random?")
        # fused_kv_weight (built in _build_fused_kv_buffers)
        if hasattr(_m, "_fused_kv_weight"):
            _w_checks["fused_kv"] = (_m._fused_kv_weight.data, "random?")
        for _name, (_w, _hint) in _w_checks.items():
            logger.warning(
                "[DBG][weights] %-20s shape=%s absmax=%.6f mean=%.6f std=%.6f (%s)",
                _name, list(_w.shape),
                _w.abs().max().item(),
                _w.float().mean().item(),
                _w.float().std().item(),
                _hint,
            )