export NCCL_ASYNC_ERROR_HANDLING=1      # 检测到错误立刻中断，不再干等
export TORCH_NCCL_ASYNC_ERROR_HANDLING=1
export TORCH_DISTRIBUTED_DEBUG=DETAIL    # 打印 rank/进程映射，方便认 device 4
export NCCL_DEBUG=INFO
export TORCH_NCCL_BLOCKING_WAIT=0
export NCCL_TIMEOUT=1200                 # 别太早 timeout 把真错误盖掉（单位秒）
export TORCH_COMPILE_DISABLE=1           # ★ 关掉 torch.compile，排除编译因素+让栈真实

torchrun --standalone --nproc_per_node 8 \
  --redirects 3 --log-dir ./logs scripts/train.py ... 2> >(tee all.log)