# Spring Gateway

## Spring Cloud Gateway 能做什么

### 一、它是什么？

Spring Cloud Gateway 是 Spring 官方推出的**微服务网关**，替代了老版本的 Zuul。基于 **Spring WebFlux + Netty**，异步非阻塞，性能比 Zuul 高一个量级。

它是整个微服务系统的**统一入口**：所有外部请求先到网关，再由网关转发到后端服务。

---

### 二、核心模型：Route + Predicate + Filter

理解 Gateway 只要理解这三个概念：

| 概念 | 作用 | 类比 |
| --- | --- | --- |
| **Route（路由）** | 一条完整的转发规则："满足什么条件，转发到哪个服务" | 快递单 |
| **Predicate（断言）** | 判断请求是否匹配这条路由（路径、Method、Header、参数等） | 收件条件 |
| **Filter（过滤器）** | 在转发前后修改请求/响应（加 Header、鉴权、限流） | 安检/盖章 |

```
请求进来
  → Predicate 判断走哪条 Route
  → Filter 链依次处理请求
  → 转发到后端服务
  → Filter 链再依次处理响应
  → 返回给客户端
```

---

### 三、它能做的 8 件事

#### 1. 路由转发（最基本功能）

把外部请求按规则转发到内部微服务，**对外屏蔽内部服务拓扑**。

```
spring:
  cloud:
    gateway:
      routes:
        - id: user-route
          uri: lb://user-service    # lb = 走负载均衡
          predicates:
            - Path=/api/user/**     # 路径匹配
          filters:
            - StripPrefix=1         # 去掉 /api 前缀再转发
```

#### 2. 负载均衡

配合注册中心（Nacos/Eureka），`uri: lb://user-service` 自动从注册中心拉取服务实例列表做客户端负载均衡。

#### 3. 鉴权认证（统一入口）

在网关层统一校验 Token / JWT / 登录态，**后端服务不用每个都写一遍鉴权逻辑**。

```
@Component
public class AuthFilter implements GlobalFilter {
    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String token = exchange.getRequest().getHeaders().getFirst("Authorization");
        if (!verify(token)) {
            exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
            return exchange.getResponse().setComplete();  // 直接拒绝
        }
        return chain.filter(exchange);  // 放行
    }
}
```

#### 4. 限流

内置基于 Redis 的 RequestRateLimiter，按 IP / 用户 / 接口维度限流，防止突发流量打垮后端。

```
filters:
  - name: RequestRateLimiter
    args:
      redis-rate-limiter.replenishRate: 10   # 每秒 10 个令牌
      redis-rate-limiter.burstCapacity: 20  # 桶容量 20
```

#### 5. 熔断降级

整合 Sentinel / Resilience4j，后端服务超时或异常时，网关直接返回兜底响应，不让故障扩散。

#### 6. 请求/响应改写

- **加 Header**：网关往里塞用户 ID、TraceId，下游服务直接用。
- **改路径**：`StripPrefix`、`PrefixPath` 重写 URL。
- **加参数、改 Host、压缩响应**等。

```
filters:
  - AddRequestHeader=X-Request-Source, gateway
  - AddResponseHeader=X-Response-Time, 100ms
  - PrefixPath=/internal    # 转发前统一加前缀
```

#### 7. 跨域处理（CORS）

统一配置跨域，不用每个服务单独处理浏览器跨域问题。

```
globalcors:
  cors-configurations:
    '[/**]':
      allowedOrigins: "*"
      allowedMethods: "*"
      allowedHeaders: "*"
```

#### 8. 日志、链路追踪

- 统一记录访问日志（谁、什么时候、调了哪个接口、耗时多久）。
- 生成/透传 TraceId，整合 Sleuth/Zipkin 做全链路追踪。

---

### 四、内置常用 Predicate（路由匹配条件）

| Predicate | 作用 | 示例 |
| --- | --- | --- |
| `Path` | 按 URL 路径匹配 | `Path=/api/user/**` |
| `Method` | 按 HTTP 方法匹配 | `Method=GET,POST` |
| `Header` | 按请求头匹配 | `Header=X-Token, \d+` |
| `Query` | 按请求参数匹配 | `Query=userId` |
| `Host` | 按域名匹配 | `Host=**.example.com` |
| `After/Before/Between` | 按时间匹配 | 灰度发布特定时间段 |
| `Cookie` | 按 Cookie 匹配 | `Cookie=session, abc.*` |

---

### 五、内置常用 Filter

| Filter | 作用 |
| --- | --- |
| `StripPrefix` | 转发前去掉路径前缀 |
| `PrefixPath` | 转发前加路径前缀 |
| `AddRequestHeader` / `AddResponseHeader` | 加请求/响应头 |
| `RequestRateLimiter` | 限流 |
| `Retry` | 失败自动重试 |
| `Hystrix` / `CircuitBreaker` | 熔断降级 |
| `RequestSize` | 限制请求体大小 |

---

### 六、Gateway vs Nginx 怎么选？

| 维度 | Nginx | Spring Cloud Gateway |
| --- | --- | --- |
| 定位 | 通用反向服务器 | 微服务业务网关 |
| 负载均衡 | 轮询/加权，静态配置 | 从注册中心动态拉取实例 |
| 鉴权限流 | 需 Lua 脚本，重 | 直接写 Java，和业务代码同生态 |
| 性能 | 极高（C 写的） | 足够用（Netty 异步） |
| 灵活性 | 低 | 高（自定义 Filter 随便写） |

> 实际架构常是：**Nginx 在外层做四层负载均衡 + SSL 卸载，Gateway 在内层做业务路由 + 鉴权 + 限流**。
> 

---

### 七、一句话总结

> Spring Cloud Gateway = **微服务统一入口**，基于 Route + Predicate + Filter 模型，能干路由转发、负载均衡、鉴权认证、限流、熔断降级、请求改写、跨域处理、日志追踪这八件事，把原本散落在各服务的"横切关注点"全部收口到网关层。
> 

---

---

## Spring Gateway 做请求加解密

通过**自定义 GlobalFilter 或 ModifyRequestBody/ResponseBody Filter**，在网关层统一解密请求体、加密响应体，后端服务完全无感知。

---

### 一、加解密放在网关的典型场景

| 场景 | 说明 |
| --- | --- |
| **敏感字段加密** | 客户端传的手机号、身份证、银行卡是密文，网关解密后再转给后端 |
| **国密合规** | 金融类接口要求 SM2/SM4 加解密，统一在网关做 |
| **接口签名验签** | 校验请求签名防篡改，同时解密 body |
| **响应加密** | 后端返回明文 JSON，网关加密后再给 App/H5 |

---

### 二、怎么实现？两种方式

#### 方式一：用官方提供的 ModifyRequestBody/ResponseBody（推荐）

Spring Cloud Gateway 内置了 `ModifyRequestBodyGatewayFilterFactory` 和 `ModifyResponseBodyGatewayFilterFactory`，专门用来改写请求/响应体。

```
@Component
public class EncryptFilter implements GlobalFilter {

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {

        // 1. 解密请求体：读取 body → 解密 → 替换成新的 body
        return chain.filter(exchange.mutate()
                .request(new ServerHttpRequestDecorator(exchange.getRequest()) {
                    @Override
                    public Flux<DataBuffer> getBody() {
                        // 读取原始加密 body，解密后返回明文
                        return super.getBody().map(dataBuffer -> {
                            String encrypted = new String(dataBuffer.toByteBuffer().array(), UTF_8);
                            String plain = SmUtil.decrypt(encrypted);  // SM4 解密
                            return exchange.getResponse()
                                .bufferFactory()
                                .wrap(plain.getBytes(UTF_8));
                        });
                    }
                })
                .build());
    }
}
```

#### 方式二：自定义 GlobalFilter 手动包装

更灵活，但要注意**请求体是 Stream，读一次就没了**，必须用 `DataBufferUtils.join()` 先缓存。

```
@Component
@Order(0)
public class DecryptRequestFilter implements GlobalFilter {

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        return DataBufferUtils.join(exchange.getRequest().getBody())
            .flatMap(dataBuffer -> {
                // 读取加密的请求体
                String encryptedBody = dataBuffer.toString(UTF_8);
                String plainBody = Sm4Util.decrypt(encryptedBody);  // 解密

                // 构造新请求，把明文 body 传下去
                ServerHttpRequest newRequest = exchange.getRequest()
                    .mutate()
                    .header("Content-Type", "application/json")
                    .body(plainBody.getBytes(UTF_8))
                    .build();

                return chain.filter(exchange.mutate().request(newRequest).build());
            });
    }
}
```

**响应加密**同理，写一个 `GlobalFilter` 装饰 `ServerHttpResponse`，把后端返回的明文 body 加密后再写给客户端。

---

### 三、一个完整的加解密 Filter 骨架

```
@Component
@Order(1)
public class EncryptDecryptFilter implements GlobalFilter {

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {

        // ========== 1. 解密请求 ==========
        ServerHttpRequest decryptedRequest = readAndDecrypt(exchange.getRequest());

        // ========== 2. 加密响应 ==========
        ServerHttpResponseEncryptor encryptor = new ServerHttpResponseEncryptor(
            exchange.getResponse());

        return chain.filter(exchange.mutate()
                .request(decryptedRequest)
                .response(encryptor)
                .build());
    }
}
```

---

### 四、几个必须注意的坑

| 坑 | 说明 |
| --- | --- |
| **请求体 Stream 只能读一次** | 必须先用 `DataBufferUtils.join()` 缓存，否则后面转发时 body 是空的 |
| **文件上传/multipart 别解密** | `multipart/form-data` 走单独处理，不要在 JSON 解密 Filter 里拦 |
| **Content-Length 要重算** | 解密后 body 长度变了，要重新设置 `Content-Length` 头，否则后端读不到完整 body |
| **性能开销** | 加解密是 CPU 密集操作，高并发下注意网关实例数和超时配置 |
| **GET 请求没有 body** | 只在 `Content-Type: application/json` 时才解密，别对 GET 请求操作 |
| **WebSocket 不适用** | WebSocket 是长连接二进制流，HTTP 加解密 Filter 拦不到 |

---

### 五、更优雅的做法：做成 Starter

如果多个网关实例都要用，把加解密逻辑封装成一个 `spring-boot-starter`，依赖引入后自动装配 Filter，业务网关只需要配置：

```
gateway:
  crypto:
    enabled: true
    type: SM4
    key: 0123456789abcdef
    include-paths:
      - /api/pay/**
      - /api/user/**
```

---

### 一句话总结

> Gateway 通过自定义 `GlobalFilter` 拦截请求/响应体，配合 `DataBuffer` 缓存和 `ServerHttpRequest/ResponseDecorator` 包装，就能在网关层统一完成 SM2/SM4 加解密和签名验签，后端服务完全无感知；唯一要注意的是请求体 Stream 只能读一次、multipart 和 GET 请求要排除。
> 

需要我把 Gateway 加解密这部分补到刚才那份 Gateway 笔记里一起写成 Notion 文件吗？