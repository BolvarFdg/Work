fc_w = self.model.fc.weight
# Lightweight diagnostic: check first few elements without .float() copy
w_slice = fc_w.data[:2, :5].cpu().tolist()
import logging
logging.getLogger("vllm").info(
    "[DFlash fc diagnose] fc.weight shape=%s, "
    "first_2x5=%s, all_zero=%s, has_nan=%s",
    tuple(fc_w.shape), w_slice,
    (fc_w == 0).all().item(), torch.isnan(fc_w).any().item(),
)