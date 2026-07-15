# DFlash 模型训练调用链流程图

下面按**执行顺序**给出完整调用链，每一步标注 `文件:方法:行号` 并用中文说明作用。

```
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 0：Shell 脚本启动（examples/train/dflash_qwen3_8b_sharegpt_online_5k.sh） │
└─────────────────────────────────────────────────────────────────────────┘
│
├─ dflash_*.sh:64-71   Step 1：数据预处理
│  python scripts/prepare_data.py --model Qwen/Qwen3-8B --data sharegpt ...
│  → 生成 Arrow 格式数据集到 $OUTPUT_DIR（含 input_ids/loss_mask/token_freq.pt）
│
├─ dflash_*.sh:73-92   Step 2：后台启动 vLLM 服务
│  CUDA_VISIBLE_DEVICES=0,1 python scripts/launch_vllm.py "$MODEL" \
│      --target-layer-ids 2 18 33 -- --data-parallel-size 2 --port 8000 &
│  → 训练时按需向 vLLM 请求 hidden states（第 2/18/33 层辅助隐状态）
│  → 轮询 http://localhost:8000/health 直到 vLLM 就绪
│
└─ dflash_*.sh:94-113  Step 3：torchrun 启动训练（2 GPU）
   CUDA_VISIBLE_DEVICES=2,3 torchrun --standalone --nproc_per_node 2 scripts/train.py \
       --speculator-type dflash --num-layers 5 --block-size 8 --max-anchors 3072 \
       --draft-vocab-size 32000 --target-layer-ids 2 18 33 \
       --on-missing generate --on-generate delete ...
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 1：入口 & 参数解析                                                 │
└─────────────────────────────────────────────────────────────────────────┘
│
├─ scripts/train.py:1286-1288   __main__
│    args = parse_args()        # 解析命令行参数
│    main(args)                 # 进入主流程
│
├─ scripts/train.py:746-1283   parse_args()
│    ├─ 定义全部 CLI 参数（dflash 关键参数见下）
│    │   :1051  --block-size 8            # DFlash 块大小（每个 anchor 预测的 token 数-1）
│    │   :1064  --max-anchors 3072         # 单 batch 最大 anchor 数
│    │   :1071  --dflash-decay-gamma 4.0  # loss 按 position 衰减的 gamma
│    │   :898   --num-layers 5            # draft decoder 层数
│    │   :948   --draft-vocab-size 32000  # draft 裁剪后词表大小
│    │   :1227  --optimizer muon          # 默认用 Muon+AdamW 混合优化器
│    │   :1207  --scheduler-type linear   # 默认线性 LR 调度
│    ├─ :1263-1271  默认值修正
│    │   非 eagle3 → draft_arch="qwen3"；muon_lr=10*lr
│    ├─ :1273       explicitly_provided_dests()   # 探测用户显式传了哪些 decoder-shaping flag
│    │                → speculators/utils/argparse_utils.py
│    ├─ :1274       validate_draft_init_args()    # 校验三选一互斥：--from-pretrained / --draft-config / shaping flags
│    │                → scripts/train.py:691-743
│    └─ :1275       resolve_loss_config(args.loss_fn)  # 解析 "--loss-fn kl_div" 成 LossConfig
│                     → speculators/models/metrics.py
│
   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 2：环境初始化（scripts/train.py:main 505-527）                     │
└─────────────────────────────────────────────────────────────────────────┘
│
├─ train.py:507   set_seed(args.seed, args.deterministic_cuda)
│    → train.py:55-65   设置 random / numpy / torch / cuda 随机种子，保证可复现
│
├─ train.py:510   setup_root_logger()
│    → speculators/train/logger.py   配置根日志格式与级别
│
├─ train.py:511-513  setup_metric_logger(loggers, run_name, log_dir)
│    → speculators/train/logger.py   配置指标日志（wandb/tensorboard/trackio/mlflow）
│
├─ train.py:516   maybe_setup_distributed()
│    → distributed.py:131-167
│    │   ├─ :142-143  读 LOCAL_RANK 环境变量判断是否分布式（torchrun 启动→是）
│    │   ├─ :151-156  torch.accelerator.set_device_index(local_rank)
│    │   │              dist.init_process_group(...)    # 初始化 NCCL 进程组
│    │   ├─ :158-159  _rank = dist.get_rank(); _world_size = 2
│    │   └─ :161      _init_sp_process_groups(_rank, _world_size, sp_size=1)
│    │       → distributed.py:88-128   建立 SP/DP 进程组（sp_size=1 时全为 DP）
│    │           SP 组连续 rank {0,1}；DP 组跨步 rank（sp_size=1 时每 rank 自成 SP 组）
│
├─ train.py:519-524  install_partial_neox_rotary()  （仅 draft_mrope_full_head_hack=False 时）
│    → speculators/models/eagle3/rotary_partial.py   安装 RoPE 补丁对齐 HF/vLLM
│
└─ train.py:526-527  if get_rank()==0: save_train_command(args.save_path)
     → speculators/train/utils.py   rank0 把完整训练命令写入 save_path 备查
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 3：词表映射解析（scripts/train.py:529-555）                        │
└─────────────────────────────────────────────────────────────────────────┘
│
├─ train.py:529-533  解析 hidden_states_dtype
│    getattr(torch, "bfloat16") → torch.bfloat16   # 模型权重和数据 dtype
│
└─ train.py:535-555  dflash 非 mtp 分支 →
   d2t, t2d, draft_vocab_size = parse_vocab_mappings(args)
   │  → train.py:306-360
   │
   ├─ 优先级1：显式 --d2t-path / --t2d-path
   │   → _load_mappings()  train.py:291-303
   │       torch.from_numpy(np.load(...))   # 加载 draft→target / target→draft 映射
   │
   ├─ 优先级2：data_path 下已有的 d2t.npy / t2d.npy
   │   → _load_mappings()  train.py:321-322
   │
   ├─ 优先级3：用 token_freq.pt + --draft-vocab-size 重新生成
   │   → train.py:326-348
   │   │   token_freq_dict = torch.load(token_freq.pt)
   │   │   target_vocab_size = get_target_vocab_size(None, verifier_name_or_path)
   │   │       → speculators/train/vocab_mapping.py   获取 verifier 全词表大小
   │   │   d2t, t2d = build_vocab_mappings_from_distribution(...)
   │   │       → speculators/train/vocab_mapping.py:60+
   │   │           # 按高频 token 裁剪到 32000 个 draft token，建立双向映射
   │   │   np.save(d2t.npy); np.save(t2d.npy)   # 缓存
   │
   └─ 优先级4：都没有 → 用 verifier 全词表（draft_vocab_size = verifier vocab_size）
       → train.py:351-360
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 4：解析模型注册表 & 拿到 DFlashDraftModel（scripts/train.py:557-564）│
└─────────────────────────────────────────────────────────────────────────┘
│
├─ train.py:557   registry = SpeculatorModel.registry
│    → model.py:202  SpeculatorModel(ClassRegistryMixin, PreTrainedModel)
│    │   ├─ :222  auto_package = "speculators.models"   # 自动发现目录
│    │   └─ :223  registry_auto_discovery = True         # 导入时自动注册子类
│    │
│    └─ DFlashDraftModel 在 dflash/core.py:33 装饰 @SpeculatorModel.register("dflash")
│       → 导入 speculators.models 包时自动发现并注册到 registry
│
└─ train.py:564   model_class = registry["dflash"]   # → DFlashDraftModel 类
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 5：构建 draft 模型（scripts/train.py:566 → build_draft_model）     │
└─────────────────────────────────────────────────────────────────────────┘
│
└─ train.py:398-502  build_draft_model(args, model_class, t2d, d2t, draft_vocab_size)
   │
   │  ── 无 --from-pretrained 且非 mtp，走"合成"分支（train.py:463-502）──
   │
   ├─ train.py:464-487  create_transformer_layer_config(...)
   │    → train.py:109-238
   │    │   ├─ :132      config_class = DRAFT_ARCH_CONFIGS["qwen3"] = Qwen3Config
   │    │   ├─ :133      verifier_config = AutoConfig.from_pretrained("Qwen/Qwen3-8B")
   │    │   ├─ :139-148  解析 hidden_act（默认 "silu"，vLLM 要求）
   │    │   ├─ :150-162  解析 head_dim / num_attention_heads / num_key_value_heads
   │    │   ├─ :164-174  构造 layer_types（默认全 "sliding_attention"）
   │    │   ├─ :176-192  构造 Qwen3Config（vocab/hidden/num_hidden_layers=5/sliding_window=2048...）
   │    │   └─ :194-236  处理 rope_parameters（transformers 5.0+）或 rope_scaling（旧版）
   │    │                  _maybe_apply_mrope_full_head_hack()  train.py:68-106
   │    └─ 返回 transformer_layer_config（一个 Qwen3Config，num_hidden_layers=5）
   │
   ├─ train.py:489-494  resolve_mask_token_id(verifier, vocab_size, mask_token_id)
   │    → speculators/train/utils.py:17   # 从 tokenizer 解析 mask token id（用于 dflash 块预测）
   │
   ├─ train.py:496      args.draft_vocab_size = 32000
   │
   └─ train.py:497-502  model_class.from_training_args(verifier_config=..., t2d=..., d2t=..., **vars(args))
        │
        ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │  DFlashDraftModel.from_training_args()  dflash/core.py:131-166      │
   └─────────────────────────────────────────────────────────────────────┘
   │
   ├─ core.py:159-161  _build_base_config_kwargs("dflash", verifier_config, **kwargs)
   │    → dflash/core.py:168-225
   │    │   ├─ :186-188  resolve_target_layer_ids([2,18,33], verifier_name_or_path)
   │    │   │              → speculators/models/utils.py:30   # 校验/填充 target 层 id
   │    │   ├─ :189-191  verifier_config._attn_implementation = "simple_flex_attention"
   │    │   ├─ :192      block_size = 8
   │    │   ├─ :194-200  sample_from_anchor = False（dflash 默认）
   │    │   ├─ :205      speculative_tokens = block_size - 1 = 7  # 每 anchor 投机 7 个 token
   │    │   └─ :207-225  返回 dict 含：
   │    │       transformer_layer_config / draft_vocab_size=32000 / block_size=8 /
   │    │       aux_hidden_state_layer_ids=[2,18,33] / mask_token_id /
   │    │       speculators_config(算法=dflash, greedy proposal, verifier 路径)
   │
   ├─ core.py:159      config = DFlashSpeculatorConfig(**kwargs)
   │                     → speculators/models/dflash/config.py
   │
   ├─ core.py:163      model = cls(config=config)
   │    │
   │    ▼
   │  ┌─────────────────────────────────────────────────────────────────┐
   │  │  DFlashDraftModel.__init__()  dflash/core.py:54-124              │
   │  └─────────────────────────────────────────────────────────────────┘
   │  │
   │  ├─ core.py:59-63   设置 _attn_impl = "simple_flex_attention"
   │  ├─ core.py:64-70   _create_mask_fn = _compiled_create_block_mask（编译版 block mask）
   │  ├─ core.py:71      super().__init__(config)   → SpeculatorModel.__init__  model.py:545-569
   │  ├─ core.py:72      self._init_vocab(config)    → model.py:37-79 (DraftVocabMixin)
   │  │   │   ├─ model.py:44-55   注册 t2d/d2t buffer（draft→32000 / verifier→全词表）
   │  │   ├─ model.py:58-63   embed_tokens = nn.Embedding(verifier_vocab, hidden)，冻结
   │  │   ├─ model.py:66-69   lm_head = nn.Linear(hidden, 32000)，冻结（从 verifier 加载）
   │  │   ├─ model.py:67-69   verifier_lm_head = nn.Linear(hidden, 32000)，冻结
   │  │   └─ model.py:74-79   权重初始化为 NaN（便于后续检测未加载）
   │  │
   │  ├─ core.py:74-83   self.layers = ModuleList[5 × Qwen3DFlashDecoderLayer(...)]
   │  │   → dflash/model_definitions.py:158-207
   │  │      ├─ :162  self_attn = Qwen3DFlashAttention(config, layer_idx)
   │  │      │        → dflash/model_definitions.py:47-155
   │  │      │           关键：forward(:97-155) 把 verifier hidden states 注入 KV cache
   │  │      │           k = cat[k_ctx, k_noise]   # context + noise 两段
   │  │      ├─ :163  mlp = Qwen3MLP(config)
   │  │      └─ :164-168 input_layernorm / post_attention_layernorm = Qwen3RMSNorm
   │  │
   │  ├─ core.py:84-92   sliding_window / sliding_window_indices / uses_full_attn 等
   │  ├─ core.py:94-97   self.norm = Qwen3RMSNorm
   │  ├─ core.py:98      self.rotary_emb = Qwen3RotaryEmbedding(config)
   │  ├─ core.py:100-104 self.fc = nn.Linear(3*hidden, hidden, bias=False)  # 3 个 target 层拼接后投影
   │  ├─ core.py:105-108 self.hidden_norm = Qwen3RMSNorm
   │  ├─ core.py:109-112 self.verifier_norm = Qwen3RMSNorm（冻结）
   │  ├─ core.py:114     self.block_size = 8
   │  └─ core.py:124    self.post_init()
   │
   ├─ core.py:164   model.load_vocab_mappings(t2d, d2t)
   │    → model.py:81-121  # 校验 shape 后 load_state_dict({"t2d":..,"d2t":..})
   │
   └─ core.py:165   model.load_verifier_weights()
        → model.py:123-199
        │   ├─ :145-152  weights_to_load = ["embed_tokens.weight","lm_head.weight","model.norm.weight"]
        │   │            load_model_layers(...)  → speculators/utils/loading.py  # 从 Qwen3-8B 加载权重
        │   ├─ :158-159  embed_tokens.load_state_dict(原始 embed)
        │   ├─ :167-169  lm_head_weight = lm_head_weight[t2d]   # 按草稿词表裁剪
        │   ├─ :171-177  lm_head.load_state_dict(裁剪后权重)；verifier_lm_head 同样
        │   ├─ :190-191  verifier_norm.load_state_dict(model.norm.weight)
        │   └─ :195-199  重新冻结 embed_tokens/lm_head/verifier_lm_head/verifier_norm
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 6：dry-run 短路（scripts/train.py:568-595）                         │
└─────────────────────────────────────────────────────────────────────────┘
│  num_target_layers = len(draft_model.target_layer_ids)   # = 3
│  if args.dry_run:
│      draft_model.to(bfloat16); save_pretrained(save_path); return  # 保存即退出
│  （本例未开 dry_run，继续）
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 7：构建 DataLoader（scripts/train.py:599-626）                      │
└─────────────────────────────────────────────────────────────────────────┘
│
├─ train.py:600-605  preprocess_fns = {"eagle3":shift_batch,"peagle":shift_batch,"mtp":...}
│    dflash 不在表中 → preprocess = None
│
└─ train.py:607-626  create_train_val_loaders(...)
     → speculators/train/dataloader.py:64-163
     │
     ├─ dataloader.py:92   noise_transform = AddUniformNoise(std=0.05)  # 加噪声增强
     │                      → speculators/train/noise_transforms.py
     │
     ├─ dataloader.py:116-129  train_dataset = ArrowDataset(datapath, ...)
     │    → speculators/train/data.py  ArrowDataset
     │       在线模式：样本无缓存 hidden states 时 → 调 vLLM 端点 generate_hidden_states()
     │       → speculators/data_generation/vllm_client.py
     │
     ├─ dataloader.py:130-142  val_dataset = ArrowDataset(..., split_ratio=train_data_ratio-1.0)
     │
     └─ dataloader.py:144-161  对 train/val 各调 _setup_dataloader()
          → dataloader.py:31-61
          │   ├─ :40-45  batch_sampler = MultipackDistributedBatchSamplerV2(
          │   │              batch_max_length=8192, num_replicas=dp_size, rank=dp_rank)
          │   │              → speculators/train/distributed_batch_sampler.py  # 多包+分布式采样
          │   └─ :47-61  DataLoader(dataset, batch_sampler, num_workers=12, prefetch_factor=4,
          │                      collate_fn=create_collate_fn(total_seq_len, hidden_size,
                          num_target_layers=3, dtype=bf16, preprocess=None))
          │                      → speculators/train/data.py  create_collate_fn  # 拼批+pad
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 8：获取 trainer kwargs（scripts/train.py:629）                      │
└─────────────────────────────────────────────────────────────────────────┘
│
└─ train_call_kwargs, val_call_kwargs = model_class.get_trainer_kwargs(**vars(args))
     → dflash/core.py:228-251  DFlashDraftModel.get_trainer_kwargs()
        ├─ loss_config = resolve_loss_config("kl_div")
        ├─ gamma = 4.0；max_anchors = 3072
        ├─ per_position_loss_weight = "fixed-exp-decay"；dpace_alpha = 0.5
        └─ 返回 ({loss_config, gamma, max_anchors, ...}, {同上})
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 9：构建 TrainerConfig & Trainer（scripts/train.py:631-655）         │
└─────────────────────────────────────────────────────────────────────────┘
│
├─ train.py:631-654  trainer_config = TrainerConfig(
│      num_epochs=5, save_path, lr=3e-4, resume_from_checkpoint=True,
│      train_call_kwargs, val_call_kwargs, optimizer="muon",
│      muon_lr=3e-3, scheduler_type="linear", checkpoint_freq=1.0,
│      hidden_states_dtype=bfloat16, log_freq=1, ...)
│    → speculators/train/trainer.py:96-118  (NamedTuple)
│
└─ train.py:655  trainer = Trainer(draft_model, trainer_config, train_loader, val_loader)
     │
     ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │  Trainer.__init__()  trainer.py:160-182                              │
   └─────────────────────────────────────────────────────────────────────┘
   │
   ├─ :169-170  self.local_rank / self.rank = get_local_rank/get_rank
   ├─ :173-174  self.is_distributed = is_distributed()  → distributed.py:55-56
   ├─ :175-178  checkpointer = DistributedCheckpointer(save_path)  # FSDP 用分布式 checkpointer
   │              → speculators/train/checkpointer.py
   │
   ├─ :180  self.setup_trainer()
   │    → trainer.py:210-267
   │    │   ├─ :211-213  检查 previous_epoch，决定 current_epoch（恢复或 0）
   │    │   ├─ :214-240  若 resume_from_checkpoint：
   │    │   │   ├─ _load_training_state()  trainer.py:198-208  # 读 training_state.json
   │    │   │   └─ 判断是否 mid-epoch 恢复 → 设 _resume_local_step / _resume_global_step
   │    │   ├─ :258  self.global_step = _resume_global_step
   │    │   ├─ :259  self.best_val_loss = inf
   │    │   └─ :261-267  从 checkpoint 恢复 best_val_loss
   │
   ├─ :181  self.setup_model()
   │    → trainer.py:269-307
   │    │   ├─ :271  SpeculatorModel.verify_training_compatible(model)
   │    │   │        → model.py:436-470  # 校验是 SpeculatorModel 实例 + 已注册 + 有 layers 属性
   │    │   ├─ :273  model.to(bfloat16)  # 权重转 bf16
   │    │   ├─ :278-283  单机分支：model.to(local_rank)，若恢复则 load_model_state_dict
   │    │   └─ :285-307  分布式分支：
   │    │       ├─ :288-289  rank0 捕获 full_state_dict（新训练时）
   │    │       ├─ :291     apply_fully_sharded(model)
   │    │       │           → distributed.py:197-213
   │    │       │              ├─ :204-210  对每层 fully_shard(layer, mp_policy=bf16/fp32 reduce)
   │    │       │              └─ :212     fully_shard(model)   # 整体 FSDP2 分片
   │    │       ├─ :293-294  若恢复 → load_model_state_dict
   │    │       └─ :296-307  否则 set_model_state_dict(broadcast_from_rank0)  # rank0 广播
   │
   └─ :182  self.setup_optimizer()
        → trainer.py:309-347
        │   ├─ :312  self.optimizers = build_optimizers(model, config)
        │   │        → speculators/train/optimizers.py:57-106
        │   │           ├─ optimizer="muon" → split_named_params_for_muon()  optimizers.py:32-54
        │   │           │   # 2D 权重矩阵（非 embed/lm_head）→ Muon；其余 → AdamW
        │   │           └─ 返回 [Muon(...), AdamW(...)]  两个优化器
        │   ├─ :313-316  若恢复 → load_optimizer_state_dict
        │   ├─ :320-322  scheduler_type="none" → 不建 scheduler
        │   ├─ :324-326  _resolve_scheduler_steps(config, len(train_loader))
        │   │           → trainer.py:121-156  # 算 warmup_steps / total_steps
        │   ├─ :328-342  make_scheduler()：linear → get_linear_schedule_with_warmup
        │   └─ :344-347  self.schedulers = [每优化器一个]；若恢复则 load_scheduler_state_dict
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 10：训练主循环（scripts/train.py:658 → trainer.run_training）       │
└─────────────────────────────────────────────────────────────────────────┘
│
└─ train.py:658  trainer.run_training()
     │
     ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │  Trainer.run_training()  trainer.py:586-617  (@with_graceful_shutdown)│
   └─────────────────────────────────────────────────────────────────────┘
   │   # @with_graceful_shutdown → speculators/train/graceful_shutdown.py
   │   # 捕获 SIGTERM/SIGINT 优雅保存 interrupted checkpoint
   │
   └─ for epoch in range(current_epoch, 5):    # trainer.py:589
        │
        ├─ trainer.py:591  train_epoch(epoch)      # 训练一个 epoch
        ├─ trainer.py:595  dist.barrier()          # 同步
        ├─ trainer.py:597  maybe_save_checkpoint(epoch)
        ├─ trainer.py:608  val_metrics = val_epoch(epoch)   # 验证
        ├─ trainer.py:612  dist.barrier()
        └─ trainer.py:614  maybe_update_best(epoch, val_metrics)
        │
        ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │  A. train_epoch(epoch)  trainer.py:395-485                           │
   └─────────────────────────────────────────────────────────────────────┘
   │
   ├─ :396  self.model.train()
   ├─ :397-398  batch_sampler.set_epoch(epoch)   # 采样器按 epoch 洗牌
   ├─ :401  num_steps = len(train_loader)
   ├─ :404  skip_steps = self._prepare_resume_skip(epoch)
   │        → trainer.py:361-393  # mid-epoch 恢复时切片 sampler 跳过已训 batch
   ├─ :407-408  rank0 用 tqdm 包裹 train_loader 显示进度
   ├─ :410-414  step_interval = ...  # 子 epoch checkpoint 间隔（checkpoint_freq<1 时）
   │
   └─ :417-485  for local_step_rel, batch in enumerate(train_loader, 1):
        │
        ├─ :419  local_step = local_step_rel + skip_steps
        ├─ :420  timer.reset(...)   # _StepTimer trainer.py:42-89  性能计时
        ├─ :423-428  gpu_batch = {k: v.to(local_rank, non_blocking=True)}
        │           # 把 batch 各 tensor 搬到 GPU
        ├─ :430  timer.mark("fetch")
        │
        ├─ :431-433  ★前向★  _draft_tokens, loss, metrics = self.model(
        │              **gpu_batch, **self.config.train_call_kwargs)
        │   │
        │   ▼
        │  ┌─────────────────────────────────────────────────────────────┐
        │  │  DFlashDraftModel.forward()  dflash/core.py:424-461          │
        │  │  @conditional_torch_compile                                 │
        │  └─────────────────────────────────────────────────────────────┘
        │  │
        │  ├─ core.py:440-449  _backbone_forward(hidden_states, input_ids,
        │  │                              loss_mask, verifier_last_hidden,
        │  │                              document_ids, position_ids, max_anchors)
        │  │   │
        │  │   ▼
        │  │  ┌──────────────────────────────────────────────────────────┐
        │  │  │  _backbone_forward()  dflash/core.py:321-422             │
        │  │  └──────────────────────────────────────────────────────────┘
        │  │  │
        │  │  ├─ core.py:346-348  _build_attention_mask(loss_mask, max_anchors, document_ids, device)
        │  │  │   → core.py:290-319
        │  │  │   │   ├─ :294-296  select_anchors(loss_mask, 3072, block_size=8)
        │  │  │   │   │              → speculators/models/dflash/utils.py  # 选 anchor 位置
        │  │  │   │   ├─ :299-306  full_attn_mask = _create_attention_mask(...)
        │  │  │   │   │   → core.py:263-288
        │  │  │   │   │   │   ├─ :273-280  create_anchor_block_mask_mod(...)
        │  │  │   │   │   │   │   → speculators/models/dflash/attention.py  # block-sparse mask
        │  │  │   │   │   │   └─ :281-288  _compiled_create_block_mask(mask_mod, ...)  # torch.compile
        │  │  │   │   └─ :309-317  sliding_window_attn_mask 同上（window=2048）
        │  │  │   └─ 返回 (full_mask, sliding_mask, anchor_positions, anchor_valid)
        │  │  │
        │  │  ├─ core.py:350-359  构造 mask token 嵌入：
        │  │  │   mask_token_ids = full((1, 3072*8), mask_token_id)
        │  │  │   mask_token_ids[:, ::8] = input_ids[:, anchor_positions]  # 每 block 首位放真实 token
        │  │  │   noise_embedding = self.embed_tokens(mask_token_ids)  # [1, 24576, hidden]
        │  │  │
        │  │  ├─ core.py:362-363  fc_output = self.hidden_norm(self.fc(hidden_states))
        │  │  │   # 3 层拼接隐状态 → fc 投影 → norm  → [1, seq, hidden]
        │  │  │
        │  │  ├─ core.py:366-369  position_ids 拼接 anchor block 的位置 id
        │  │  │
        │  │  ├─ core.py:374  position_embeddings = self.rotary_emb(hidden_states, position_ids)
        │  │  │
        │  │  ├─ core.py:376-378  anchored_block_indices = get_base_indices_for_anchored_blocks(...)
        │  │  │   → speculators/models/dflash/utils.py
        │  │  │
        │  │  ├─ core.py:380-389  ★verifier target 计算★（no_grad）
        │  │  │   verifier_logits = self.verifier_lm_head(
        │  │  │       self.verifier_norm(verifier_last_hidden_states))
        │  │  │   if not sample_from_anchor: verifier_logits = roll(logits, 1, dim=1)  # 右移1
        │  │  │   targets = verifier_logits[:, anchored_block_indices]  # 取 anchor 对应位
        │  │  │
        │  │  ├─ core.py:391-402  ★逐层 forward★
        │  │  │   for layer_idx, layer in enumerate(self.layers):  # 5 层
        │  │  │       noise_embedding = layer(
        │  │  │           hidden_states=noise_embedding,
        │  │  │           target_hidden=fc_output,        # verifier 隐状态注入 KV
        │  │  │           attention_mask=sliding_window_attn_mask or full_attn_mask,
        │  │  │           position_ids=..., position_embeddings=...)
        │  │  │       │
        │  │  │       ▼
        │  │  │      ┌──────────────────────────────────────────────────────────┐
        │  │  │      │ Qwen3DFlashDecoderLayer.forward()                        │
        │  │  │      │ dflash/model_definitions.py:170-207                       │
        │  │  │      └──────────────────────────────────────────────────────────┘
        │  │  │      ├─ :189-190  h = input_layernorm(hidden_states)
        │  │  │      ├─ :191-202  h = self.self_attn(hidden=h, target_hidden=target_hidden,
        │  │  │      │                                attention_mask, position_embeddings)
        │  │  │      │   │
        │  │  │      │   ▼
        │  │  │      │  ┌──────────────────────────────────────────────────────┐
        │  │  │      │  │ Qwen3DFlashAttention.forward()                       │
        │  │  │      │  │ dflash/model_definitions.py:97-155                     │
        │  │  │      │  └──────────────────────────────────────────────────────┘
        │  │  │      │  │  ★核心★ 把 verifier 隐状态注入 KV cache：
        │  │  │      │  ├─ :112-114  q = q_proj(hidden_states)  # draft 噪声侧 query
        │  │  │      │  ├─ :116-119  k_ctx = k_proj(target_hidden); k_noise = k_proj(hidden)
        │  │  │      │  │            v_ctx = v_proj(target_hidden); v_noise = v_proj(hidden)
        │  │  │      │  ├─ :120-126  k = cat[k_ctx, k_noise]  # ctx_len + block_size
        │  │  │      │  │            v = cat[v_ctx, v_noise]
        │  │  │      │  ├─ :127-128  k = k_norm(k).transpose; v = v.transpose
        │  │  │      │  ├─ :129-130  apply_rotary_pos_emb(q, k, cos, sin)  # :29-44
        │  │  │      │  └─ :142-152  attn_fn(...)  # flex_attention/sdpa/eager
        │  │  │      │              → attn_output; o_proj(attn_output)
        │  │  │      ├─ :203       residual + attn
        │  │  │      ├─ :205       h = post_attention_layernorm(h)
        │  │  │      ├─ :206       h = self.mlp(h)  # Qwen3MLP
        │  │  │      └─ :207       return residual + h
        │  │  │
        │  │  ├─ core.py:404-405  hidden = self.norm(noise_embedding)
        │  │  │                     logits = self.lm_head(hidden)  # [1, num_anchors*8, 32000]
        │  │  ├─ core.py:408-416  aligned_loss_mask = loss_mask[:, anchored_block_indices]
        │  │  │                     * anchor_valid（清零 padding block）
        │  │  ├─ core.py:419-420  sample_from_anchor=False → mask 掉每 block 第 0 位（anchor 本身不训）
        │  │  └─ core.py:422  return hidden, logits, targets, aligned_loss_mask, anchored_block_indices
        │  │
        │  ├─ core.py:450-460  compute_metrics(logits, targets, aligned_loss_mask, block_size=8,
        │  │                              gamma=4.0, loss_config, per_position_loss_weight,
        │  │                              dpace_alpha, sample_from_anchor)
        │  │   → speculators/models/dflash/metrics.py:20-106
        │  │   │   ├─ 用 dflash_loss_decay(gamma=4.0)  # 按 block 内位置指数衰减权重
        │  │   │   │   → speculators/models/metrics.py
        │  │   │   ├─ compound_loss(loss_config)  # kl_div 等
        │  │   │   └─ compute_accuracy_multi_step(...)  # full_acc / position_i_acc / eal
        │  │   └─ 返回 (loss, metrics_dict)
        │  │
        │  └─ core.py:461  return None, loss, metrics
        │
        ├─ :435  timer.mark("fwd")
        ├─ :436  self._optimizers_zero_grad()   # trainer.py:349-351  Muon+AdamW 都 zero_grad
        ├─ :437  loss.backward()                # 反向传播（FSDP 下自动 all_reduce 梯度）
        ├─ :438  torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)  # 梯度裁剪
        ├─ :440  timer.mark("bwd")
        ├─ :441  self._optimizers_step()        # trainer.py:353-355  Muon+AdamW 都 step
        │           Muon: Newton-Schulz 正交化更新 2D 权重；AdamW 更新其余
        ├─ :443-445  current_lrs = {Muon: lr, AdamW: lr}  # 记录当前学习率
        ├─ :446  self._schedulers_step()        # trainer.py:357-359  两个 scheduler 各 step
        ├─ :447  timer.mark("opt")
        ├─ :450-475  若 timer.enabled：
        │           ├─ :454-456  分布式 dist.reduce(metrics, dst=0)
        │           ├─ :460      normalize_counted_metrics(...)  → train/utils.py
        │           └─ :466-475  metric_logger.info({"train":..., "lr":..., "global_step":...})
        ├─ :476  self.global_step += 1
        └─ :478-485  子 epoch checkpoint（step_interval 命中时 maybe_save_checkpoint）
        │
        ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │  B. maybe_save_checkpoint(epoch)  trainer.py:530-560                   │
   └─────────────────────────────────────────────────────────────────────┘
   ├─ :531-540  判断是否该存（save_best 或 checkpoint_freq 整数倍）
   ├─ :543      checkpointer.save_checkpoint(model, optimizers, epoch)
   │            → speculators/train/checkpointer.py  DistributedCheckpointer
   │              FSDP 下用 get_model_state_dict(sharded→gather) 保存
   ├─ :544-545  save_scheduler_state_dict(schedulers, epoch)
   ├─ :546-547  _save_training_state(epoch, local_step)  trainer.py:187-196
   └─ :550-559  建 epoch{N}_end 软链指向 {N}/
   │
   ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │  C. val_epoch(epoch)  trainer.py:487-528  (@torch.no_grad())         │
   └─────────────────────────────────────────────────────────────────────┘
   ├─ :491  self.model.eval()
   ├─ :500-517  for batch in val_loader:
   │   ├─ gpu_batch 搬 GPU
   │   ├─ :508-510  _draft, _loss, metrics = model(**gpu_batch, **val_call_kwargs)
   │   │            # 同 train 但用 val_call_kwargs（无噪声等差异）
   │   └─ :512-514  dist.all_reduce(metrics, SUM)  # 跨 rank 汇总
   ├─ :519-522  求均值 + normalize_counted_metrics
   └─ :524-527  metric_logger.info({"val":..., "epoch":...})
   │
   ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │  D. maybe_update_best(epoch, val_metrics)  trainer.py:562-584        │
   └─────────────────────────────────────────────────────────────────────┘
   ├─ :565-566  val_metrics["loss_epoch"] >= best_val_loss → 不更新
   ├─ :568-571  save_best 模式 → 存 checkpoint
   ├─ :577      best_val_loss = val_metrics["loss_epoch"]
   ├─ :578      save_val_metrics(epoch, val_metrics)
   ├─ :579      update_best_symlink(epoch)   # checkpoint_best -> {epoch}
   └─ :583-584  save_best → cleanup_keep_only_best(best_epoch)
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  阶段 11：训练结束清理（scripts/train.py:660-665）                        │
└─────────────────────────────────────────────────────────────────────────┘
│
├─ train.py:661  del trainer, draft_model
├─ train.py:662  gc.collect()
├─ train.py:663-664  if cuda: torch.cuda.empty_cache()   # 释放显存
└─ train.py:665  maybe_destroy_distributed()
                  → distributed.py:170-194
                     dist.destroy_process_group()  # 销毁 NCCL 进程组，重置全局拓扑状态
   │
   ▼
   dflash_*.sh  trap cleanup EXIT → kill vLLM_PID   # 脚本退出时杀掉 vLLM 服务
   echo "Done. Checkpoints saved to $OUTPUT_DIR/checkpoints/"
```

---

## 数据流一句话总结

```
vLLM(在线生成 Qwen3-8B 第2/18/33层隐状态)
  → ArrowDataset 加载 + AddUniformNoise 噪声
  → MultipackDistributedBatchSamplerV2 多包分布式拼批(total_seq_len=8192)
  → DFlashDraftModel.forward:
      select_anchors 选 3072 个 anchor
      → 5 层 Qwen3DFlashDecoderLayer（每层把 verifier 隐状态注入 KV cache 做 block 注意力）
      → lm_head 出 draft logits
      → verifier_lm_head 出 target logits
  → compute_metrics: KL-div loss + dflash_loss_decay(gamma=4.0 按 block 内位置衰减) + EAL/acc 指标
  → Muon(2D权重) + AdamW(其余) 混合优化器 + linear warmup LR
  → FSDP2 fully_shard 分布式训练 → 每 epoch checkpoint + best 模型
```