# Redis分布式锁

## Redis 分布式锁实现 & 锁提前过期问题

---

### 一、分布式锁的演进（5 个版本）

#### V1：最原始的 `SETNX`（有缺陷）

```
SET lock_key 1 NX          # 不存在才设置，抢到锁
# ... 执行业务 ...
DEL lock_key               # 释放锁
```

**问题**：如果业务执行完之前进程崩了，锁永远不释放 → **死锁**。

#### V2：加过期时间（解决死锁，但有新问题）

```
SET lock_key 1 NX EX 30   # 原子设置 + 30 秒自动过期
```

**问题**：

- 谁都能删这把锁——线程 A 执行慢，锁过期了，线程 B 拿到锁，A 执行完把 B 的锁删了。
- 必须给锁加一个**唯一标识**（如 UUID + 线程 ID）。

#### V3：唯一标识 + Lua 脚本解锁（生产可用的基础版）

**加锁**：

```
SET lock_key {uuid:threadId} NX EX 30
```

**解锁**（必须原子判断"是不是我的锁"再删）：

```
-- Lua 脚本：先 get 比对，再 del，两步必须原子
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
```

**为什么要用 Lua？** `get` 和 `del` 之间如果不原子，可能刚判断完是自己的锁，锁刚好过期被别人拿走，然后 del 把别人的锁删了。

```
String lockValue = UUID.randomUUID() + ":" + Thread.currentThread().getId();
// 加锁
Boolean locked = redisTemplate.opsForValue()
    .setIfAbsent("order:lock:" + orderId, lockValue, 30, TimeUnit.SECONDS);
// 解锁（Lua 脚本）
String script = "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end";
redisTemplate.execute(new DefaultRedisScript<>(script, Long.class),
    Collections.singletonList("order:lock:" + orderId), lockValue);
```

**问题**：如果业务执行超过 30 秒，锁自动过期了，其他线程拿到锁，并发问题又回来了。这就是你问的核心问题。

#### V4：Redisson（生产标准，带看门狗自动续期）

手写 V3 有各种边界问题，生产直接用 **Redisson**，它内置了**看门狗（Watchdog）**机制。

```
RLock lock = redissonClient.getLock("order:lock:" + orderId);
try {
    lock.lock();              // 默认 30 秒过期，看门狗自动续期
    // ... 业务逻辑 ...
} finally {
    lock.unlock();
}
```

**Watchdog 原理**：

1. 加锁时默认 TTL = 30 秒。
2. 启动一个后台定时任务，**每 10 秒（TTL/3）**检查一次：如果当前线程还持有锁，就把 TTL 重置回 30 秒。
3. 业务执行完 → 主动 `unlock()` → 看门狗停止。
4. 进程崩溃 → 看门狗线程也死了 → 没人续期 → 30 秒后锁自动释放，不会死锁。

```
加锁成功（TTL=30s）
  ↓
业务执行中... 10s 时看门狗检查：还持有锁 → 续期到 30s
  ↓
业务执行中... 20s 时看门狗检查：还持有锁 → 续期到 30s
  ↓
业务执行完 → unlock() → 看门狗停止
```

> 注意：如果手动指定了 `lock.lock(10, TimeUnit.SECONDS)`，**看门狗就不会启动**，10 秒后强制释放，必须确保业务能跑完。
> 

#### V5：RedLock（红锁，理论方案，生产很少用）

针对 Redis 主从切换丢锁的问题（Master 宕机，锁还没同步到 Slave，Slave 升级后锁丢了），Redis 作者提出 RedLock：

- 部署 **N 个完全独立的 Redis Master**（不做主从复制）。
- 客户端向**所有 N 个节点**依次请求加锁。
- **超过半数（N/2+1）成功**才算加锁成功。
- 总耗时要小于锁的过期时间。

**争议**：分布式专家 Martin Kleppmann 公开质疑 RedLock 的安全性（时钟跳变、GC 停顿等问题），生产中绝大多数公司用 **Redisson 单节点 + 主从**就够了，真正强一致锁应该用 **ZooKeeper 或 etcd**。

---

### 二、核心问题：锁的 key 过期了但任务没完怎么办？

这是手写分布式锁最容易踩的坑，有 4 种解法：

#### 方案 1：看门狗自动续期（推荐，Redisson 默认）

就是上面 V4 讲的：业务没执行完，后台线程自动给锁续命，直到业务主动释放。

```
// Redisson 不用手动设过期时间，走默认看门狗
lock.lock();
```

#### 方案 2：延长过期时间 = 预估业务最大耗时

如果不用 Redisson，手动把 TTL 设成"业务最大执行时间 × 2"。

```
SET lock_key uuid NX EX 60   -- 预估业务最多跑 20s，设 60s 兜底
```

**缺点**：靠拍脑袋，设短了照样过期，设长了宕机后锁释放慢。

#### 方案 3：分两段锁（锁粒度拆分）

把长任务拆成小步骤，每步用不同的锁，避免一个大锁持有太久。

```
处理订单：
  步骤1：加锁扣库存（短）
  步骤2：释放库存锁
  步骤3：加锁创建订单（短）
  步骤4：释放订单锁
```

#### 方案 4：业务幂等 + 定时任务兜底

锁过期后即使并发进来了，业务本身做幂等（数据库唯一键、状态机），第二个请求进来发现"已经处理过了"直接返回。

---

### 三、手写分布式锁的完整骨架（面试答题版）

```
public boolean tryLock(String key, String requestId, int expireSeconds) {
    String script = "if redis.call('set',KEYS[1],ARGV[1],'NX','EX',ARGV[2]) then return 1 else return 0 end";
    Long result = redisTemplate.execute(
        new DefaultRedisScript<>(script, Long.class),
        Collections.singletonList(key),
        requestId, String.valueOf(expireSeconds));
    return result != null && result == 1;
}

public boolean unlock(String key, String requestId) {
    String script = "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end";
    Long result = redisTemplate.execute(
        new DefaultRedisScript<>(script, Long.class),
        Collections.singletonList(key), requestId);
    return result != null && result == 1;
}

// 使用
String requestId = UUID.randomUUID().toString();
try {
    if (tryLock("order:lock:" + orderId, requestId, 30)) {
        // 执行业务
    }
} finally {
    unlock("order:lock:" + orderId, requestId);
}
```

---

### 四、一张表总结

| 方案 | 加锁 | 解锁 | 续期 | 一致性 | 生产推荐度 |
| --- | --- | --- | --- | --- | --- |
| `SETNX` | ✅ | ✅ | ❌ | 弱 | ❌ 死锁 |
| `SET NX EX` | ✅ | 谁都能删 | ❌ | 弱 | ❌ 误删 |
| `SET NX EX` + 唯一值 + Lua | ✅ | 原子判断 | ❌ | 弱 | ⚠️ 锁过期问题 |
| **Redisson** | ✅ | ✅ | **Watchdog 自动续** | 弱（主从切换可能丢） | ✅ 生产首选 |
| RedLock | N 节点投票 | N 节点 | 自动续 | 理论强实际弱 | ⚠️ 极少用 |
| ZooKeeper/etcd | 临时节点 + Watch | 会话断开自动释放 | 会话保活 | **强一致** | 金融级场景 |

---

### 五、一句话总结

> Redis 分布式锁标准实现：`SET key 唯一值 NX EX 30` 加锁 + Lua 脚本原子判断解锁；锁提前过期的问题用 **Redisson 看门狗自动续期**解决（后台每 10 秒检查一次，业务没完就把 TTL 重置回 30 秒，进程崩溃则停止续期自然过期）；真正强一致场景用 ZooKeeper 而非 Redis。
> 

需要我把 Redis 分布式锁这份笔记也写成 Notion 文件，和前面的线程池、Kafka、OpenFeign、Gateway 放一起吗？