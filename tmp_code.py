fc_w = self.model.fc.weight
import logging
logging.getLogger("vllm").info(
    "[DFlash fc diagnose] fc.weight shape=%s, mean=%s, std=%s, has_nan=%s, "
    "all_zero=%s, input_shape=%s, input_mean=%s",
    tuple(fc_w.shape), fc_w.float().mean().item(), fc_w.float().std().item(),
    torch.isnan(fc_w).any().item(), (fc_w == 0).all().item(),
    tuple(hidden_states.shape), hidden_states.float().mean().item(),
)