## TTL
### 什么是TTL
- TTL 是Time To Live的缩写,也就是生存时间
### TTL能干什么?
- 支持==消息==的过期时间,在消息发送时可以进行指定
- 支持==队列==的过期时间,从消息入队列开始计算,只要超过了队列的超时时间配置,那么消息就会自动清除

## 死信队列
### 什么是死信队列?
- DLX , Dead-Letter-Exchange
- 利用DLX,当消息在一个队列中变成死信(dead message)之后,它能被重新publish到另一个Exchange,这个Exchange就是DLX
### 死信队列如何产生?
- 消息被拒绝(basic.reject/basic.nack)并且requeue=false(重回队列为false)
- 消息TTL过期
- 队列达到最大长度

### DLX和正常Exchange有什么区别?
- DLX也是一个正常的Exchange,和一般的Exchange没有区别,它能在任何的队列上被指定,实际上就是设置某个队列的属性
- 当这个队列中有死信时,RabbitMQ就会自动的将这个消息重新发布到设置的Exchange上去,进而被路由收到另一个队列
- 可以监听这个队列中消息做相应的处理,这个特性可以弥补RabbitMQ3.0以前支持的immediate参数的功能

### 如何设置死信队列?
1. 首先需要设置死信队列的exchange和queue,然后进行绑定:
- Exchange: dlx.exchange
- Queue: dlx.queue
- RoutingKey: #

2. 然后我们正常声明交换机,队列,绑定,只不过我们需要在队列上加上一个参数即可:
```
arguments.put("x-dead-letter-exchange","dlx.exchange");
```


