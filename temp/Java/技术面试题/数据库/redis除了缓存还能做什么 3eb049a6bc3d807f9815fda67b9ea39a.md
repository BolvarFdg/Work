# redis除了缓存还能做什么

## Redis 除了缓存还能做什么

Redis 不只是缓存，它是一个**基于内存的多数据结构存储系统**，下面按数据结构和实际场景分类。

---

### 一、分布式锁（前面讲过）

`SET key NX EX` + Lua 解锁 + Redisson 看门狗。这是 Redis 最经典的非缓存用途。

---

### 二、计数器 / 限流

利用 Redis 的原子自增 `INCR`：

| 场景 | 命令 |
| --- | --- |
| 接口防刷（每分钟限 100 次） | `INCR rate:user:1001:minute`，超过阈值拒绝 |
| 商品库存扣减 | `DECR stock:123`，原子扣减 |
| 点赞数、阅读量实时统计 | `INCR article:99:likes` |
| 全局唯一 ID | `INCR global:seq` |

```
-- 简易限流：1 分钟内最多 100 次
INCR rate:user:1001
EXPIRE rate:user:1001 60
```

> 配合 Lua 脚本可以实现**令牌桶/漏桶**限流，比 Guava RateLimiter 支持分布式。
> 

---

### 三、排行榜（ZSET）

`ZSET`（有序集合）天然适合做排序：

```
ZADD rank:game 1200 "player1" 800 "player2" 2000 "player3"
ZREVRANGE rank:game 0 9 WITHSCORES    -- Top 10
ZRANK rank:game "player1"              -- 查我的排名
ZINCRBY rank:game 100 "player1"       -- 加分
```

**典型场景**：游戏排行、热搜榜、商品销量榜、音乐排行榜。

---

### 四、社交关系（Set）

`Set` 自动去重 + 集合交并差运算：

| 场景 | 命令 |
| --- | --- |
| 点赞 | `SADD like:article:99 user:1001` |
| 共同好友 | `SINTER friends:u1 friends:u2` |
| 关注/粉丝 | `SADD follow:u1 u2`、`SADD fans:u2 u1` |
| 标签系统 | `SADD tag:hot user:1001 user:1002` |
| 抽奖 | `SRANDMEMBER user:pool 3` |

---

### 五、消息队列

Redis 三种方式做 MQ：

| 方式 | 特点 | 适用场景 |
| --- | --- | --- |
| **List（lpush/rpop）** | 简单队列，先进先出 | 简单异步任务，不要求可靠 |
| **Pub/Sub（发布订阅）** | 广播模式，发出去就完，消费者离线收不到 | 实时通知、聊天室 |
| **Stream（5.0+）** | 支持消费者组、ACK、持久化、回溯 | 轻量级 MQ，可替代 RabbitMQ |

```
-- List 队列
LPUSH queue:order "order_json"
RPOP queue:order

-- Stream 消费者组
XADD stream:orders * orderId 1001
XGROUP CREATE stream:orders g1 $
XREADGROUP GROUP g1 c1 COUNT 10 STREAMS stream:orders >
```

> 生产环境不建议用 Redis 替代 Kafka/RocketMQ，但简单业务完全够用。
> 

---

### 六、延迟队列

用 `ZSET` 的 score 存**执行时间戳**，消费者轮询到点的任务：

```
-- 下单后 30 分钟未支付自动取消
ZADD delay:queue 1727000000 "order:1001"
-- 后台轮询
ZRANGEBYSCORE delay:queue 0 当前时间 LIMIT 0 10
```

**场景**：订单超时取消、优惠券到期提醒、延迟发送短信。

---

### 七、Bitmap —— 极节省空间的位操作

每个用户占 1 bit，1 亿用户只占 ~12MB：

| 场景 | 命令 |
| --- | --- |
| 用户签到 | `SETBIT sign:u1:202609 28 1` |
| 在线状态 | `SETBIT online:20260929 1001 1` |
| 连续签到统计 | `BITCOUNT sign:u1:202609` |
| 未读消息数 | BitField 操作 |

---

### 八、HyperLogLog —— 海量去重计数

**用 12KB 内存统计亿级 UV，误差 0.81%**：

```
PFADD uv:20260929 user1 user2 user3
PFCOUNT uv:20260929    -- 返回去重后的 UV 数
```

**场景**：页面 UV、独立访客统计。不关心具体是谁，只关心数量。

---

### 九、Geo —— 地理位置

```
GEOADD shops:xi'an 108.94 34.34 "回民街"
GEOADD shops:xi'an 108.95 34.35 "大雁塔"
GEORADIUS shops:xi'an 108.94 34.34 5 km ASC   -- 附近 5km 的店
```

**场景**：附近的人、附近的店、外卖配送范围、打车附近车辆。

---

### 十、Bloom Filter（布隆过滤器）

**解决缓存穿透**：判断一个元素**一定不存在**（可能误判存在）。

```
// Redisson 内置 RBloomFilter
RBloomFilter<String> bloom = redisson.getBloomFilter("userBloom");
bloom.tryInit(1000000L, 0.03);   // 100万数据，误判率 3%
bloom.add("user1001");
bloom.contains("user1001");      // false 一定不存在，true 可能存在
```

**场景**：

- 缓存穿透防护（非法请求直接拦截，不查 DB）
- 邮箱/手机号注册查重
- 爬虫 URL 去重

---

### 十一、分布式 Session

多实例部署时，Session 存在 Redis 里，所有服务共享：

```
用户登录 → 生成 token 存 Redis（key=token, value=用户信息, TTL=2h）
后续请求带 token → 网关/拦截器查 Redis 校验
```

Spring Session + Redis 开箱即用。

---

### 十二、购物车（Hash）

```
HSET cart:user1001 sku100 2 sku200 1    -- 商品ID:数量
HINCRBY cart:user1001 sku100 1          -- 加数量
HGETALL cart:user1001                   -- 查购物车
```

---

### 十三、配置中心 / 服务注册发现（轻量）

- Pub/Sub 做配置热更新。
- Redis 也能做简易服务注册中心（不推荐生产用 Nacos）。

---

### 十四、一张表速查

| Redis 用途 | 核心数据结构 | 典型场景 |
| --- | --- | --- |
| 缓存 | 所有 | 热点数据 |
| **分布式锁** | String（SET NX） | 并发控制 |
| **计数器/限流** | String（INCR） | 库存、防刷、限流 |
| **排行榜** | ZSET | 游戏榜、热搜 |
| **社交关系** | Set | 点赞、共同好友、关注 |
| **消息队列** | List / PubSub / Stream | 异步任务、通知 |
| **延迟队列** | ZSET | 订单超时取消 |
| **签到/在线状态** | Bitmap | 签到、在线人数 |
| **UV 统计** | HyperLogLog | 页面访客数 |
| **附近的人/店** | Geo | LBS 服务 |
| **缓存穿透防护** | Bloom Filter | 非法请求拦截 |
| **分布式 Session** | String/Hash | 多实例登录态共享 |
| **购物车** | Hash | 电商购物车 |

---

### 一句话总结

> Redis 本质是**内存数据结构服务器**：String 做计数器和锁，ZSET 做排行榜和延迟队列，Set 做社交关系，List/Stream 做消息队列，Bitmap 做签到和在线状态，HyperLogLog 做 UV，Geo 做附近的人，Bloom Filter 防穿透，Hash 做购物车——缓存只是它最广为人知的一个用途。
> 

需要我把这份 Redis 全景笔记也写成 Notion 文件吗？