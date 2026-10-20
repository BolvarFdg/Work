# SpringCloud组件

## Spring Cloud 与 Spring Cloud Alibaba 组件全景

---

### 一、先搞清楚两者关系

| 框架 | 背景 | 现状 |
| --- | --- | --- |
| **Spring Cloud Netflix** | 早期 Spring Cloud 官方推荐，Netflix 开源组件 | 大部分组件已停更（Eureka 2.0、Hystrix、Zuul 进入维护模式） |
| **Spring Cloud Alibaba** | 阿里开源，接替 Netflix 成为主流 | **当前生产首选**，Nacos/Sentinel/Seata 一套打通 |

---

### 二、Spring Cloud（Netflix 时代）核心组件

| 组件 | 作用 | 现状 |
| --- | --- | --- |
| **Eureka** | 服务注册与发现 | 停更，被 Nacos 取代 |
| **Ribbon** | 客户端负载均衡 | 停更，被 Spring Cloud LoadBalancer 取代 |
| **Feign / OpenFeign** | 声明式 HTTP 客户端（前面讲过） | 仍在使用 |
| **Hystrix** | 熔断器 / 降级 | 停更，被 Sentinel 取代 |
| **Zuul** | 早期网关 | 停更，被 Gateway 取代 |
| **Config** | 配置中心（Git 存储） | 仍在用，但生产多用 Nacos/Apollo |
| **Sleuth** | 链路追踪 | 被 Micrometer Tracing 取代 |
| **Gateway** | 新一代网关（前面讲过） | 仍在使用 |
| **Stream** | 消息驱动抽象（屏蔽 MQ 差异） | 仍在使用 |
| **Bus** | 消息总线，配置热更新 | 配合 MQ 使用 |

---

### 三、Spring Cloud Alibaba 核心组件（重点）

| 组件 | 作用 | 对应 Netflix 组件 |
| --- | --- | --- |
| **Nacos** | **服务注册发现 + 配置中心**（二合一） | Eureka + Config |
| **Sentinel** | **流量控制、熔断降级、系统保护** | Hystrix |
| **Seata** | **分布式事务框架** | 无（Netflix 时代没有） |
| **RocketMQ** | 消息队列（事务消息、延迟消息） | 无 |
| **Spring Cloud Alibaba Cloud** | 阿里云服务集成（OSS、SMS 等） | 无 |

---

### 四、逐个讲清楚

#### 1. Nacos —— 注册中心 + 配置中心

**两个功能合一**：

| 功能 | 说明 |
| --- | --- |
| **服务注册发现** | 服务启动时把自己的 IP/端口注册到 Nacos；消费方从 Nacos 拉取服务列表，做负载均衡 |
| **配置中心** | 配置统一存 Nacos，修改后**实时推送到各服务**，不用重启 |

**对比 Eureka**：

- Nacos 支持 AP/CP 切换（Eureka 只有 AP）。
- Nacos 自带控制台，可视化管理服务和配置。
- Nacos 同时支持 DNS 和 HTTP 协议。

```
服务 A 启动 → 注册到 Nacos
服务 B 启动 → 从 Nacos 拉取服务 A 列表 → 调用
配置修改 → Nacos 推送到 A、B → 热更新
```

#### 2. Sentinel —— 熔断限流

比 Hystrix 强大得多：

| 功能 | 说明 |
| --- | --- |
| **流量控制** | 按 QPS/线程数限流，支持冷启动、匀速排队 |
| **熔断降级** | 慢调用比例、异常比例、异常数触发降级 |
| **系统保护** | 按 CPU、 Load、入口 QPS 整体保护 |
| **热点参数限流** | 按某个参数值限流（如某个商品 ID 限购） |
| **控制台** | 可视化配置规则，实时生效，不用重启 |

**对比 Hystrix**：Hystrix 只有熔断器，Sentinel 是限流+熔断+系统保护全套，还有控制台。

#### 3. Seata —— 分布式事务

解决跨库/跨服务的数据一致性问题。

**四种模式**：

| 模式 | 全称 | 适用场景 |
| --- | --- | --- |
| **AT** | 自动补偿型 | 默认模式，业务无侵入，基于本地事务 + Undo Log |
| **TCC** | Try-Confirm-Cancel | 高一致性场景，业务要写三个接口 |
| **Saga** | 长事务 | 跨多个微服务的长流程 |
| **XA** | 强一致性 | 数据库支持 XA 协议时 |

**AT 模式原理**：

```
1. 每个分支事务先开本地事务，记录 Undo Log
2. 全部成功 → 全局事务提交，删除 Undo Log
3. 任一失败 → 根据 Undo Log 反向回滚
```

#### 4. RocketMQ —— 消息队列

| 特性 | 说明 |
| --- | --- |
| **事务消息** | 保证本地事务和发消息的最终一致性 |
| **延迟消息** | 18 个延迟级别（1s/5s/1min...） |
| **顺序消息** | 严格顺序消费 |
| **消息回溯** | 按时间戳重新消费 |

---

### 五、一套完整 Spring Cloud Alibaba 技术栈

```
客户端请求
   ↓
Spring Cloud Gateway（网关：路由 + 鉴权 + 限流）
   ↓
业务微服务（订单、用户、商品...）
   ├── Nacos（注册发现 + 配置中心）
   ├── OpenFeign（服务间调用）
   ├── Sentinel（限流 + 熔断降级）
   ├── Seata（分布式事务）
   └── RocketMQ（异步消息）
```

---

### 六、组件对照速查表

| 功能 | Netflix 时代 | 现在主流（Spring Cloud Alibaba） |
| --- | --- | --- |
| 注册中心 | Eureka | **Nacos** |
| 配置中心 | Spring Cloud Config | **Nacos** |
| 负载均衡 | Ribbon | Spring Cloud LoadBalancer |
| 服务调用 | Feign / OpenFeign | OpenFeign |
| 熔断降级 | Hystrix | **Sentinel** |
| 网关 | Zuul | Spring Cloud Gateway |
| 分布式事务 | 无 | **Seata** |
| 消息队列 | 无 | **RocketMQ** |
| 链路追踪 | Sleuth | Micrometer Tracing + SkyWalking |

---

### 七、一句话总结

> Spring Cloud Alibaba 核心四大件：**Nacos（注册+配置中心）、Sentinel（限流熔断）、Seata（分布式事务）、RocketMQ（消息队列）**；配合 Gateway 做网关、OpenFeign 做服务调用，组成当前主流微服务技术栈，全面接替已停更的 Netflix 组件。
> 

需要我把这份微服务组件全景笔记也写成 Notion 文件吗？