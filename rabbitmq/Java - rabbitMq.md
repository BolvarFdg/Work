## RabbitMQ 的五种队列
- 不需要路由器
    - 简单队列
    - work模式
- 需要路由器
    - 发布/订阅模式
    - 路由模式
    - 主题模式
> 路由模式架构图
![image](https://upload-images.jianshu.io/upload_images/5630287-3e93765463df95df.png?imageMogr2/auto-orient/strip|imageView2/2/w/1200/format/webp)
使用路由模式时,需要设定三个参数:
> 1. Exchange type: 即上图的type = direct , 这个值有四个 , 对应4种队列模式
> 2. Rounting Key:发送消息时附加的匹配信息,用来和binding key匹配,匹配成功则发送到对应的queue
> 3. Bingding key:即上图的error , info ,warning,即exchange 对应特别queue的名称
## 基本概念简述
- API
    - Connection Factory、Connection、Channel都是RabbitMQ对外提供的API中最基本的对象
    - Connection是RabbitMQ的socket链接，它封装了socket协议相关部分逻辑。Connection Factory则是Connection的制造工厂
    - Channel是我们与RabbitMQ打交道的最重要的一个接口，我们大部分的业务操作是在Channel这个接口中完成的，包括定义Queue、定义Exchange、绑定Queue与Exchange、发布消息等
- Queue
    - Queue（队列）是RabbitMQ的内部对象，用于存储消息，如下图表示
    
![image](https://upload-images.jianshu.io/upload_images/292448-0e8ca2da28338ecf?imageMogr2/auto-orient/strip|imageView2/2/w/129/format/webp)

![image](https://upload-images.jianshu.io/upload_images/292448-6fb89efa4849a293?imageMogr2/auto-orient/strip|imageView2/2/w/392/format/webp)

![image](https://upload-images.jianshu.io/upload_images/292448-74f89d2c9be248a8?imageMogr2/auto-orient/strip|imageView2/2/w/332/format/webp)

- Message acknowledgment
    - 回执消息 , 在实际应用中，可能会发生消费者收到Queue中的消息，但没有处理完成就宕机（或出现其他意外）的情况，这种情况下就可能会导致消息丢失。为了避免这种情况发生，我们可以要求消费者在消费完消息后发送一个回执给RabbitMQ，RabbitMQ收到消息回执（Message acknowledgment）后才将该消息从Queue中移除
    - 如果RabbitMQ没有收到回执并检测到消费者的RabbitMQ连接断开，则RabbitMQ会将该消息发送给其他消费者（如果存在多个消费者）进行处理。这里不存在timeout，一个消费者处理消息时间再长也不会导致该消息被发送给其他消费者，除非它的RabbitMQ连接断开。

    - 这里会产生另外一个问题，如果我们的开发人员在处理完业务逻辑后，忘记发送回执给RabbitMQ，这将会导致严重的bug——Queue中堆积的消息会越来越多。消费者重启后会重复消费这些消息并重复执行业务逻辑。

    - 另外publish message 是没有ACK的

- Message durability
    - 如果我们希望即使在RabbitMQ服务重启的情况下，也不会丢失消息，我们可以将Queue与Message都设置为可持久化的（durable），这样可以保证绝大部分情况下我们的RabbitMQ消息不会丢失

- Perfetch count
    - 前面我们讲到如果有多个消费者同时订阅同一个Queue中的消息，Queue中的消息会被平摊给多个消费者。这时如果每个消息的处理时间不同，就有可能会导致某些消费者一直在忙，而另外一些消费者很快就处理完手头工作并一直空闲的情况。我们可以通过设置Prefetch count来限制Queue每次发送给每个消费者的消息数，比如我们设置prefetchCount=1，则Queue每次给每个消费者发送一条消息；消费者处理完这条消息后Queue会再给该消费者发送一条消息

![image](https://upload-images.jianshu.io/upload_images/292448-ecefb4068795154c?imageMogr2/auto-orient/strip|imageView2/2/w/396/format/webp)

- Exchange
    -  在上一节我们看到生产者将消息投递到Queue中，实际上这在RabbitMQ中这种事情永远都不会发生。实际的情况是，生产者将消息发送到Exchange（交换器，下图中的X），由Exchange将消息路由到一个或多个Queue中（或者丢弃）
    - Exchange是按照什么逻辑将消息路由到Queue的？
        - 和Binding有关
    - RabbitMQ中的Exchange有四种类型，不同的类型有着不同的路由策略,和Exchange Types有关

![image](https://upload-images.jianshu.io/upload_images/292448-60ad41ccb0ed03cc?imageMogr2/auto-orient/strip|imageView2/2/w/332/format/webp)


    
   

- Rounting Key

生产者在将消息发送给Exchange的时候，一般会指定一个Routing Key，来指定这个消息的路由规则，而这个Routing Key需要与Exchange Type及Binding key联合使用才能最终生效

在Exchange Type与Binding key固定的情况下（在正常使用时一般这些内容都是固定配置好的），我们的生产者就可以在发送消息给Exchange时，通过指定Routing Key来决定消息流向哪里

RabbitMQ为Routing Key设定的长度限制为255 bytes

- Bingding

RabbitMQ中通过Binding将Exchange与Queue关联起来，这样RabbitMQ就知道如何正确地将消息路由到指定的Queue了

- Binding key

在绑定（Binding）Exchange与Queue的同时，一般会指定一个Binding key。消费者将消息发送给Exchange时，一般会指定一个Routing Key。当Binding key与Routing Key相匹配时，消息将会被路由到对应的Queue中

- Exchange Types

RabbitMQ常用的Exchange Type有fanout、direct、topic、headers这四种（AMQP规范里还提到两种Exchange Type，分别为system与自定义，这里不予以描述）

> 1. fanout-发布订阅模式

> fanout类型的Exchange路由规则非常简单，它会把所有发送到该Exchange的消息路由到所有与它绑定的Queue中
    
 ![image](https://upload-images.jianshu.io/upload_images/292448-ab0f7fd29cc3a574?imageMogr2/auto-orient/strip|imageView2/2/w/329/format/webp)

> 2. direct-路由模式

> direct类型的Exchange路由规则也很简单，它会把消息路由到那些Binding key与Routing key完全匹配的Queue中
    
![image](https://upload-images.jianshu.io/upload_images/292448-a61c59324f50930a?imageMogr2/auto-orient/strip|imageView2/2/w/423/format/webp)

> 以上图的配置为例，我们以routingKey="error"发送消息到Exchange，则消息会路由到Queue1
    （amqp.gen-S9b…，这是由RabbitMQ自动生成的Queue名称）和Queue2
    
> 如果我们以Routing Key="info"或routingKey="warning"来发送消息，
    则消息只会路由到Queue2。如果我们以其他Routing Key发送消息，则消息不会路由到这两个Queue中

> 3.topic-主题模式

> 前面讲到direct类型的Exchange路由规则是完全匹配Binding Key与Routing Key，但这种严格的匹配方式在很多情况下不能满足实际业务需求。topic类型的Exchange在匹配规则上进行了扩展，它与direct类型的Exchage相似，也是将消息路由到Binding Key与Routing Key相匹配的Queue中，但这里的匹配规则有些不同，它约定：

> Routing Key为一个句点号“.”分隔的字符串（我们将被句点号". "分隔开的每一段独立的字符串称为一个单词），如"stock.usd.nyse"、"nyse.vmw"、"quick.orange.rabbit"。Binding Key与Routing Key一样也是句点号“. ”分隔的字符串。

> Binding Key中可以存在两种特殊字符"*"与"#"，用于做模糊匹配，其中"*"用于匹配一个单词，"#"用于匹配多个单词（可以是零个）
    
![image](https://upload-images.jianshu.io/upload_images/292448-ec33660c97e14d21?imageMogr2/auto-orient/strip|imageView2/2/w/424/format/webp)

> 以上图中的配置为例，routingKey=”quick.orange.rabbit”的消息会同时路由到Q1与Q2，routingKey=”lazy.orange.fox”的消息会路由到Q1，routingKey=”lazy.brown.fox”的消息会路由到Q2，routingKey=”lazy.pink.rabbit”的消息会路由到Q2（只会投递给Q2一次，虽然这个routingKey与Q2的两个bindingKey都匹配）；

> routingKey=”quick.brown.fox”、routingKey=”orange”、routingKey=”quick.orange.male.rabbit”的消息将会被丢弃，因为它们没有匹配任何bindingKey

> 4. headers

> headers类型的Exchange不依赖于Routing Key与Binding Key的匹配规则来路由消息，而是根据发送的消息内容中的headers属性进行匹配

> 在绑定Queue与Exchange时指定一组键值对；当消息发送到Exchange时，RabbitMQ会取到该消息的headers（也是一个键值对的形式），对比其中的键值对是否完全匹配Queue与Exchange绑定时指定的键值对。如果完全匹配则消息会路由到该Queue，否则不会路由到该Queue

> 该类型的Exchange没有用到过（不过也应该很少有用武之地），所以不做介绍

***

## 简单队列
### 模型

![image](https://images2018.cnblogs.com/blog/1120165/201807/1120165-20180701235656495-1545126593.png)

一个生产者对应一个消费者,生产者将消息发送到“hello”队列,消费者从该队列接收消息
- P:消息的生产者
- 红色:队列
- c:消费者

3个对象:生产者 , 队列 , 消费者
### 实例
1. pom文件
```
<dependency>
    <groupId>com.rabbitmq</groupId>
    <artifactId>amqp-client</artifactId>
    <version>3.4.1</version>
</dependency>
```
2. 工具类
```
package com.ys.utils;

import com.rabbitmq.client.Connection;
import com.rabbitmq.client.ConnectionFactory;

/**
 * Create by hadoop
 */
public class ConnectionUtil {

    public static Connection getConnection(String host,int port,String vHost,String userName,String passWord) throws Exception{
        //1、定义连接工厂
        ConnectionFactory factory = new ConnectionFactory();
        //2、设置服务器地址
        factory.setHost(host);
        //3、设置端口
        factory.setPort(port);
        //4、设置虚拟主机、用户名、密码
        factory.setVirtualHost(vHost);
        factory.setUsername(userName);
        factory.setPassword(passWord);
        //5、通过连接工厂获取连接
        Connection connection = factory.newConnection();
        return connection;
    }
}
```
3. 生产者
```
package com.ys.simple;

import com.rabbitmq.client.Channel;
import com.rabbitmq.client.Connection;
import com.ys.utils.ConnectionUtil;

/**
 * Create by YSOcean
 */
public class Producer {
    private final static String QUEUE_NAME = "hello";

    public static void main(String[] args) throws Exception{
        //1、获取连接
        Connection connection = ConnectionUtil.getConnection("192.168.146.251",5672,"/","guest","guest");
        //2、声明信道
        Channel channel = connection.createChannel();
        //3、声明(创建)队列
        channel.queueDeclare(QUEUE_NAME, false, false, false, null);
        //4、定义消息内容
        String message = "hello rabbitmq ";
        //5、发布消息
        channel.basicPublish("",QUEUE_NAME,null,message.getBytes());
        System.out.println("[x] Sent'"+message+"'");
        //6、关闭通道
        channel.close();
        //7、关闭连接
        connection.close();
    }
}
```
4. 消费者
```
package com.ys.simple;

import com.rabbitmq.client.Channel;
import com.rabbitmq.client.Connection;
import com.rabbitmq.client.QueueingConsumer;
import com.ys.utils.ConnectionUtil;


/**
 * Create by YSOcean
 */
public class Consumer {

    private final static String QUEUE_NAME = "hello";

    public static void main(String[] args) throws Exception{
        //1、获取连接
        Connection connection = ConnectionUtil.getConnection("192.168.146.251",5672,"/","guest","guest");
        //2、声明通道
        Channel channel = connection.createChannel();
        //3、声明队列
        channel.queueDeclare(QUEUE_NAME, false, false, false, null);
        //4、定义队列的消费者
        QueueingConsumer queueingConsumer = new QueueingConsumer(channel);
        //5、监听队列
        /*
            true:表示自动确认，只要消息从队列中获取，无论消费者获取到消息后是否成功消费，都会认为消息已经成功消费
            false:表示手动确认，消费者获取消息后，服务器会将该消息标记为不可用状态，等待消费者的反馈，
                   如果消费者一直没有反馈，那么该消息将一直处于不可用状态，并且服务器会认为该消费者已经挂掉，不会再给其
                   发送消息，直到该消费者反馈。
         */

        channel.basicConsume(QUEUE_NAME,true,queueingConsumer);
        //6、获取消息
        while (true){
            QueueingConsumer.Delivery delivery = queueingConsumer.nextDelivery();
            String message = new String(delivery.getBody());
            System.out.println(" [x] Received '" + message + "'");
        }
    }

}
```
### 简单队列的不足
- 耦合性高,一个生产者对应一个消费者,如果有多个消费者就不行了
- 队列名变更时得同时变更,耦合性高

*** 

## work queues 工作队列

### 为什么会出现工作队列?
因为简单队列是一对一的 , 而实际开发中,生产者发送消息是毫不费力的,而消费者一般是要跟业务相结合的,消费这接收到消息需要处理花费时间,会造成队列堵塞,work模式解决了这个问题

### 模型

![image](https://images2018.cnblogs.com/blog/1120165/201807/1120165-20180717220023680-448688747.png)

一个生产者对应多个消费者

### 两种工作模式
1. Round-robin（轮询分发）
2. Fair dispatch（公平分发）

### Round-robin(轮询分发)
轮询分发结果就是不管服务器谁忙或清闲，都不会给谁多一个任务或少一个任务，任务总是你一个我一个的分
##### 实例
1. 生产者
```
package com.hrabbit.rabbitmq.send;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.Channel;
import com.rabbitmq.client.Connection;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-27 下午2:37
 * @Description:
 */
public class Send {

    private final static String QUEUE_NAME = "hrabbit_queue_work";

    public static void main(String[] args) throws IOException, TimeoutException, InterruptedException {
        // 获取到连接以及mq通道
        Connection connection = ConnectionUtils.getConnection();
        Channel channel = connection.createChannel();
        // 声明队列
        channel.queueDeclare(QUEUE_NAME, false, false, false, null);
        for (int i = 0; i < 50; i++) {
            // 消息内容
            String message = "." + i;
            channel.basicPublish("", QUEUE_NAME, null, message.getBytes());
            System.out.println(" [x] Sent '" + message + "'");
            Thread.sleep(i * 10);
        }
        channel.close();
        connection.close();
    }
}
```
2. 消费者一号
```
package com.hrabbit.rabbitmq.recover;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.*;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-27 下午2:42
 * @Description:
 */
public class Received {

    private final static String QUEUE_NAME = "hrabbit_queue_work";

    public static void main(String[] args) throws IOException, TimeoutException {
        Connection connection = ConnectionUtils.getConnection();
        final Channel channel = connection.createChannel();
        // 声明队列，主要为了防止消息接收者先运行此程序，队列还不存在时创建队列。
        channel.queueDeclare(QUEUE_NAME, false, false, false, null);
        //定义一个消息的消费者
        final Consumer consumer = new DefaultConsumer(channel) {
            @Override
            public void handleDelivery(String consumerTag, Envelope envelope, AMQP.BasicProperties properties, byte[] body) throws IOException {
                String message = new String(body, "UTF-8");
                System.out.println(" [1] 消费消息: '" + message + "'");
                try {
                    doWork(message);
                } catch (Exception e) {
                    e.printStackTrace();
                } finally {
                    System.out.println(" [1] 消费消息结束");
                }
            }
        };
        boolean autoAck = true;
        //消息的确认模式自动应答
        channel.basicConsume(QUEUE_NAME, autoAck, consumer);
    }


    private static void doWork(String task) throws InterruptedException {
        Thread.sleep(1000);
    }
}
```
3. 消费者二号
```
package com.hrabbit.rabbitmq.recover;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.*;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-27 下午2:42
 * @Description:
 */
public class Received2 {

    private final static String QUEUE_NAME = "hrabbit_queue_work";

    public static void main(String[] args) throws IOException, TimeoutException {
        Connection connection = ConnectionUtils.getConnection();
        final Channel channel = connection.createChannel();
        // 声明队列，主要为了防止消息接收者先运行此程序，队列还不存在时创建队列。
        channel.queueDeclare(QUEUE_NAME, false, false, false, null);
        //定义一个消息的消费者
        final Consumer consumer = new DefaultConsumer(channel) {
            @Override
            public void handleDelivery(String consumerTag, Envelope envelope, AMQP.BasicProperties properties, byte[] body) throws IOException {
                String message = new String(body, "UTF-8");
                System.out.println(" [2] 消费消息: '" + message + "'");
                try {
                    doWork(message);
                } catch (Exception e) {
                    e.printStackTrace();
                } finally {
                    System.out.println(" [2] 消费消息结束");
                }
            }
        };
        boolean autoAck = true;
        //消息的确认模式自动应答
        channel.basicConsume(QUEUE_NAME, autoAck, consumer);
    }


    private static void doWork(String task) throws InterruptedException {
        Thread.sleep(2000);
    }
}
```
**运行结果:**

消费者1 我们处理时间是1s ;而消费者2中处理时间是2s; 但是我们看到的现象并不是 1处理的多 消费者2处理的少，消费者1中将偶数部分处理掉了 ，消费者2中将基数部分处理掉了,两者一样多

**结论:**

1. 消费者1和消费者2获取到的消息内容是不同的,同一个消息只能被一个消费者获取
2. 消费者1和消费者2货到的消息数量是一样的 一个奇数一个偶数 按道理消费者1 获取的比消费者2要多,
这种方式叫做轮询分发 结果就是不管谁忙或清闲，都不会给谁多一个任务或少一个任务，任务总是你一个我一个的分


### Fair dispatch(公平分发)
##### 模型

![image](https://upload-images.jianshu.io/upload_images/5630287-eed8f69fefab7859.png?imageMogr2/auto-orient/strip|imageView2/2/w/1200/format/webp)

轮询的问题是浪费了生产力,理想情况下应该是能者多劳,所以有了公平分发模式

我们使用basicQos( prefetchCount = 1)方法，来限制RabbitMQ只发不超过1条的消息给同一个消费者。当消息处理完毕后，有了反馈ack，才会进行第二次发送。(也就是说需要手动反馈给Rabbitmq ) 还有一点需要注意，使用公平分发，必须关闭自动应答，改为手动应答
##### 实例
1. 生产者

代码基本不用修改，只需要添加一行代码：channel.basicQos(1);
```
package com.hrabbit.rabbitmq.send;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.Channel;
import com.rabbitmq.client.Connection;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-27 下午2:37
 * @Description:
 */
public class Send {

    private final static String QUEUE_NAME = "hrabbit_queue_work";

    private static Integer prefetchCount=1;

    public static void main(String[] args) throws IOException, TimeoutException, InterruptedException {
        // 获取到连接以及mq通道
        Connection connection = ConnectionUtils.getConnection();
        Channel channel = connection.createChannel();

        //每个消费者发送确认信号之前，消息队列不发送下一个消息过来，一次只处理一个消息
        //限制发给同一个消费者不得超过1条消息
        channel.basicQos(prefetchCount);

        // 声明队列
        channel.queueDeclare(QUEUE_NAME, false, false, false, null);
        for (int i = 0; i < 50; i++) {
            // 消息内容
            String message = "." + i;
            channel.basicPublish("", QUEUE_NAME, null, message.getBytes());
            System.out.println(" [x] Sent '" + message + "'");
            Thread.sleep(i * 10);
        }
        channel.close();
        connection.close();
    }
}
```
2. 消费者一号
```
package com.hrabbit.rabbitmq.recover;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.*;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-27 下午2:42
 * @Description:
 */
public class Received {

    private final static String QUEUE_NAME = "hrabbit_queue_work";

    public static void main(String[] args) throws IOException, TimeoutException {
        Connection connection = ConnectionUtils.getConnection();
        final Channel channel = connection.createChannel();
        // 声明队列，主要为了防止消息接收者先运行此程序，队列还不存在时创建队列。
        channel.queueDeclare(QUEUE_NAME, false, false, false, null);
        channel.basicQos(1);//保证一次只分发一个
        //定义一个消息的消费者
        final Consumer consumer = new DefaultConsumer(channel) {
            @Override
            public void handleDelivery(String consumerTag, Envelope envelope, AMQP.BasicProperties properties, byte[] body) throws IOException {
                String message = new String(body, "UTF-8");
                System.out.println(" [1] 消费消息: '" + message + "'");
                try {
                    doWork(message);
                } catch (Exception e) {
                    e.printStackTrace();
                } finally {
                    System.out.println(" [1] 消费消息结束");
                    //手动应答
                    channel.basicAck(envelope.getDeliveryTag(), false);
                }
            }
        };
        boolean autoAck = false;
        //消息的确认模式关闭自动
        channel.basicConsume(QUEUE_NAME, autoAck, consumer);
    }


    private static void doWork(String task) throws InterruptedException {
        Thread.sleep(1000);
    }
}
```
3. 消费者二号
```
package com.hrabbit.rabbitmq.recover;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.*;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-27 下午2:42
 * @Description:
 */
public class Received2 {

    private final static String QUEUE_NAME = "hrabbit_queue_work";

    public static void main(String[] args) throws IOException, TimeoutException {
        Connection connection = ConnectionUtils.getConnection();
        final Channel channel = connection.createChannel();
        // 声明队列，主要为了防止消息接收者先运行此程序，队列还不存在时创建队列。
        channel.queueDeclare(QUEUE_NAME, false, false, false, null);
        channel.basicQos(1);//保证一次只分发一个
        //定义一个消息的消费者
        final Consumer consumer = new DefaultConsumer(channel) {
            @Override
            public void handleDelivery(String consumerTag, Envelope envelope, AMQP.BasicProperties properties, byte[] body) throws IOException {
                String message = new String(body, "UTF-8");
                System.out.println(" [2] 消费消息: '" + message + "'");
                try {
                    doWork(message);
                } catch (Exception e) {
                    e.printStackTrace();
                } finally {
                    System.out.println(" [2] 消费消息结束");
                    channel.basicAck(envelope.getDeliveryTag(), false);
                }
            }
        };
        boolean autoAck = false;
        //消息的确认模式自动应答关闭
        channel.basicConsume(QUEUE_NAME, autoAck, consumer);
    }


    private static void doWork(String task) throws InterruptedException {
        //消息的处理时间为2000
        Thread.sleep(2000);
    }
}
```
这时候结果就是消费者1 速度大于消费者2

*** 

## 订阅模式Publish/Subscribe
> 后面这三种模式都需要一个Exchange(路由器) 

### 简介
简单队列和工作队列都是一个消息只能由一个消费者消费,那么如果我想发一个消息能被多个消费者消费,这时候怎么办? 这时候我们就得用到了消息中的发布订阅模型

类似微信订阅号 发布文章消息 就可以广播给所有的接收者

### 模型
work模式 是不是同一个队列 多个消费者,而ps这种模式呢,是一个队列对应一个消费者,Publish模式还多了一个exchange(交换机 转发器) ,这时候我们要获取消息 就需要队列绑定到交换机上,交换机把消息发送到队列 , 消费者才能获取队列的消息

![image](https://upload-images.jianshu.io/upload_images/5630287-a3fede28a15f4c9e.png?imageMogr2/auto-orient/strip|imageView2/2/w/329/format/webp)

解读：
1. 1个生产者，多个消费者
2. 每一个消费者都有自己的一个队列
3. 生产者没有将消息直接发送到队列，而是发送到了交换机(转发器)
4. 每个队列都要绑定到交换机
5. 生产者发送的消息，经过交换机，到达队列，实现，一个消息被多个消费者获取的目的

### 实例
1. 生产者
```
package com.hrabbit.rabbitmq.publish.send;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.Channel;
import com.rabbitmq.client.Connection;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-28 下午2:40
 * @Description:
 */
public class Send {
    //交换机名称
    private final static String EXCHANGE_NAME = "hrabbit_exchange_fanout";

    public static void main(String[] args) throws IOException, TimeoutException, InterruptedException {
        // 获取到连接以及mq通道
        Connection connection = ConnectionUtils.getConnection();
        Channel channel = connection.createChannel();
        //声明一个交换机，一个参数为交换机名称，第二个参数为模式
        channel.exchangeDeclare(EXCHANGE_NAME, "fanout"); //fanout 分裂
        // 消息内容
        String message = "hello rabbitMQ!";
        //发送消息
        channel.basicPublish(EXCHANGE_NAME, "", null, message.getBytes());
        System.out.println("Send '" + message + "'");
        channel.close();
        connection.close();
    }
}
```
> 发送消息之前交换机需要绑定队列,消息发送到了一个没有绑定队列的交换机时,消息就会丢失!

2. 消费者1

声明队列为hrabbit_queue_fanout_phone,将队列也绑定到交换机hrabbit_exchange_fanout,代码如下:
```
package com.hrabbit.rabbitmq.publish.recove;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.*;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-28 下午2:41
 * @Description:
 */
public class Recover {

    private final static String QUEUE_NAME = "hrabbit_queue_fanout_phone";
    private final static String EXCHANGE_NAME = "hrabbit_exchange_fanout";

    public static void main(String[] args) throws IOException, TimeoutException {
        // 获取到连接以及mq通道
        Connection connection = ConnectionUtils.getConnection();
        final Channel channel = connection.createChannel();

        // 声明队列
        channel.queueDeclare(QUEUE_NAME, false, false, false, null);
        // 绑定队列到交换机
        channel.queueBind(QUEUE_NAME, EXCHANGE_NAME, "");
        //------------下面逻辑和work模式一样-----
        // 同一时刻服务器只会发一条消息给消费者
        channel.basicQos(1);

        Consumer consumer = new DefaultConsumer(channel){
            @Override
            public void handleDelivery(String consumerTag, Envelope envelope, AMQP.BasicProperties properties, byte[] body) throws IOException {
                // 消息到达 触发这个方法
                String msg = new String(body, "utf-8");
                System.out.println("消费者1号:" + msg);
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException e) {
                    e.printStackTrace();
                } finally {
                    System.out.println("消费者1号执行完毕！");
                    // 手动回执
                    channel.basicAck(envelope.getDeliveryTag(), false);
                }
            }
        };

        boolean autoAck = false;
        channel.basicConsume(QUEUE_NAME,autoAck,consumer);
    }
}
```
3. 消费者2

声明队列为hrabbit_queue_fanout_email,并且将队列也绑定到交换机hrabbit_exchange_fanout,代码如下:
```
package com.hrabbit.rabbitmq.publish.recove;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.*;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-28 下午2:41
 * @Description:
 */
public class Recove2 {


    private final static String QUEUE_NAME = "hrabbit_queue_fanout_email";
    private final static String EXCHANGE_NAME = "hrabbit_exchange_fanout";

    public static void main(String[] args) throws IOException, TimeoutException {
        // 获取到连接以及mq通道
        Connection connection = ConnectionUtils.getConnection();
        final Channel channel = connection.createChannel();

        // 声明队列
        channel.queueDeclare(QUEUE_NAME, false, false, false, null);
        // 绑定队列到交换机
        channel.queueBind(QUEUE_NAME, EXCHANGE_NAME, "");
        //------------下面逻辑和work模式一样-----
        // 同一时刻服务器只会发一条消息给消费者
        channel.basicQos(1);

        Consumer consumer = new DefaultConsumer(channel){
            @Override
            public void handleDelivery(String consumerTag, Envelope envelope, AMQP.BasicProperties properties, byte[] body) throws IOException {
                // 消息到达 触发这个方法
                String msg = new String(body, "utf-8");
                System.out.println("消费者2号:" + msg);
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException e) {
                    e.printStackTrace();
                } finally {
                    System.out.println("消费者2号执行完毕！");
                    // 手动回执
                    channel.basicAck(envelope.getDeliveryTag(), false);
                }
            }
        };

        boolean autoAck = false;
        channel.basicConsume(QUEUE_NAME,autoAck,consumer);
    }

}
```

***

## 路由模式Routing
### 模型
路由模式的作用是: 分类接收, 通过给不同队列命名来区分类别,添加一个特性只接收部分消息。

例如: 将log文件分类处理,打印所有log , 但是只存储错误log
![image](https://upload-images.jianshu.io/upload_images/5630287-3e93765463df95df.png?imageMogr2/auto-orient/strip|imageView2/2/w/1200/format/webp)

### 绑定
在发布/订阅模式中我们已经创建了一个binding:
```
channel.queueBind(queueName, EXCHANGE_NAME, "");
```
一个binding就是exchange和Queue之间的一个关系。可以简单的理解为：这个Queue对其相对于的exchange的消息之间建立了一个关系, 而这个binding中没有binding key,因为fanout类型的exchange不需要这个参数

Binding可以使用一个已经存在的routingKey参数。为了避免和basic_publish参数混淆，我们称之为binding key。路由模式下来创建一个binding：
```
channel.queueBind(queueName, EXCHANGE_NAME, "black");
```
binding key的意义有时候取决于exchange的类型 ,这个binding中的binding key 是 black

### Direct类型的exchange
之前使用的fanout类型的exchange就不能实现这个功能,因为fanout模式会把所有队列发送给所有人

Direct类型exchange的路由算法是很简单的：要想一个消息能到达这个队列，需要binding key和routing key正好能匹配得上

![image](https://upload-images.jianshu.io/upload_images/5630287-86c290e9e65970cc.jpg?imageMogr2/auto-orient/strip|imageView2/2/w/408/format/webp)

在这样的结构中，我们可以看到direct类型的exchange X，有两个queue绑定到它。第一个queue是以orange为binding key绑定到exchange X上的，第二个queue是由两个binding key（black和green）绑定到exchange X的

在这样的设置中，一条消息被推送到exchange，如果使用的routing key是orange，那么消息就会被路由到Q1中；如果使用的routing key是black或者green，那么该消息将会被路由到Q2中。其它的消息都将会被丢弃掉

### 多重绑定

![image](https://upload-images.jianshu.io/upload_images/5630287-e55eea2b7c8fbf69.png?imageMogr2/auto-orient/strip|imageView2/2/w/398/format/webp)

用一个binding 把多个queue绑定到一个exchange上

### 实例-发送日志
使用direct 类型的路由器来实现日志分级,将日志级别作为routing key

1. 生产者
```
package com.hrabbit.rabbitmq.routing.send;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.Channel;
import com.rabbitmq.client.Connection;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-30 下午7:41
 * @Description:
 */
public class Send {

    //交换机名称
    private final static String EXCHANGE_NAME = "hrabbit_exchange_direct";

    public static void main(String[] args) throws IOException, TimeoutException {

        // 获取到连接以及mq通道
        Connection connection = ConnectionUtils.getConnection();
        Channel channel = connection.createChannel();
        //声明一个交换机，一个参数为交换机名称，第二个参数为模式
        channel.exchangeDeclare(EXCHANGE_NAME, "direct");
        // 消息内容
        String message = "id=1的商品删除了";

        channel.basicPublish(EXCHANGE_NAME, "info", null, message.getBytes());
        System.out.println(" [x] Sent '" + message + "'");

        channel.close();
        connection.close();
    }
}
```
2. 消费者一号
一号的routingKey定义为error
```
package com.hrabbit.rabbitmq.routing.recover;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.*;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-30 下午7:42
 * @Description:
 */
public class Recover {

    //队列名称
    private final static String QUEUE_NAME = "hrabbit_queue_direct_1";
    //交换机名称
    private final static String EXCHANGE_NAME = "hrabbit_exchange_direct";

    public static void main(String[] args) throws IOException, TimeoutException {
        // 获取到连接以及mq通道
        Connection connection = ConnectionUtils.getConnection();
        final Channel channel = connection.createChannel();

        // 声明队列
        channel.queueDeclare(QUEUE_NAME, false, false, false, null);
        // 绑定队列到交换机
        channel.queueBind(QUEUE_NAME, EXCHANGE_NAME, "error");
        //------------下面逻辑和work模式一样-----
        // 同一时刻服务器只会发一条消息给消费者
        channel.basicQos(1);

        Consumer consumer = new DefaultConsumer(channel){
            @Override
            public void handleDelivery(String consumerTag, Envelope envelope, AMQP.BasicProperties properties, byte[] body) throws IOException {
                // 消息到达 触发这个方法
                String msg = new String(body, "utf-8");
                System.out.println("[error]:" + msg);
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException e) {
                    e.printStackTrace();
                } finally {
                    System.out.println("error消息执行完毕！");
                    // 手动回执
                    channel.basicAck(envelope.getDeliveryTag(), false);
                }
            }
        };

        boolean autoAck = false;
        channel.basicConsume(QUEUE_NAME,autoAck,consumer);

    }
}
```
3. 消费者二号
routingKey定义为:error,info,warning
```
package com.hrabbit.rabbitmq.routing.recover;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.*;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-30 下午7:42
 * @Description:
 */
public class Recover2 {

    //队列名称
    private final static String QUEUE_NAME = "hrabbit_queue_direct_2";
    //交换机名称
    private final static String EXCHANGE_NAME = "hrabbit_exchange_direct";

    public static void main(String[] args) throws IOException, TimeoutException {
        // 获取到连接以及mq通道
        Connection connection = ConnectionUtils.getConnection();
        final Channel channel = connection.createChannel();

        // 声明队列
        channel.queueDeclare(QUEUE_NAME, false, false, false, null);
        // 绑定队列到交换机
        channel.queueBind(QUEUE_NAME, EXCHANGE_NAME, "warning");
        channel.queueBind(QUEUE_NAME, EXCHANGE_NAME, "error");
        channel.queueBind(QUEUE_NAME, EXCHANGE_NAME, "info");
        //------------下面逻辑和work模式一样-----
        // 同一时刻服务器只会发一条消息给消费者
        channel.basicQos(1);

        Consumer consumer = new DefaultConsumer(channel){
            @Override
            public void handleDelivery(String consumerTag, Envelope envelope, AMQP.BasicProperties properties, byte[] body) throws IOException {
                // 消息到达 触发这个方法
                String msg = new String(body, "utf-8");
                System.out.println("[info]:" + msg);
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException e) {
                    e.printStackTrace();
                } finally {
                    System.out.println("info消息执行完毕！");
                    // 手动回执
                    channel.basicAck(envelope.getDeliveryTag(), false);
                }
            }
        };

        boolean autoAck = false;
        channel.basicConsume(QUEUE_NAME,autoAck,consumer);

    }
}
```

## 主题模式
Topic类型的exchange ,相比direct类型的exchange又有进一步提升

direct不能基于多重因素来分发消息,而topic可以

### 模型
![image](https://upload-images.jianshu.io/upload_images/5630287-e8f2462526906e6d.png?imageMogr2/auto-orient/strip|imageView2/2/w/424/format/webp)

- *（星号）：可以（只能）匹配一个单词
- #（井号）：可以匹配多个单词（或者零个）

由图中可知 , topic模式的binding key 是一种模糊匹配机制,不像redirect模式是写死的,所以可以匹配更多类型的rounting key

上图的 binding key可以总结为:
- Q1对所有橘色的（orange）的动物感兴趣；
- Q2希望能拿到所有兔子的（rabbit）信息，还有比较懒惰的（lazy.#）动物信息

> 一条以” quick.orange.rabbit”为routing key的消息将会推送到Q1和Q2两个queue上，routing key为“lazy.orange.elephant”的消息同样会被推送到Q1和Q2上

> 但如果routing key为”quick.orange.fox”的话，消息只会被推送到Q1上；routing key为”lazy.brown.fox”的消息会被推送到Q2上，routing key为"lazy.pink.rabbit”的消息也会被推送到Q2上，但同一条消息只会被推送到Q2上一次

### 和其他类型相比
Topic类型的exchange是很强大的，也可以实现其它类型的exchange

- 当一个队列被绑定为binding key为”#”时，它将会接收所有的消息，此时和fanout类型的exchange很像。
- 当binding key不包含”*”和”#”时，这时候就很像direct类型的exchange。

### 实例
1. 生产者
设置不同的rounting key
```
package com.hrabbit.rabbitmq.toptic.send;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.Channel;
import com.rabbitmq.client.Connection;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-30 下午7:41
 * @Description:
 */
public class Send {

    //交换机名称
    private final static String EXCHANGE_NAME = "hrabbit_exchange_topic";

    public static void main(String[] args) throws IOException, TimeoutException {

        // 获取到连接以及mq通道
        Connection connection = ConnectionUtils.getConnection();
        Channel channel = connection.createChannel();
        //声明一个交换机，一个参数为交换机名称，第二个参数为模式
        channel.exchangeDeclare(EXCHANGE_NAME, "topic");
        //待发送的消息
        String[] routingKeys=new String[]{
                "quick.orange.rabbit",
                "lazy.orange.elephant",
                "quick.orange.fox",
                "lazy.brown.fox",
                "quick.brown.fox",
                "quick.orange.male.rabbit",
                "lazy.orange.male.rabbit"
        };
        //发送消息
        for(String severity :routingKeys){
            String message = "From "+severity+" routingKey' s message!";
            channel.basicPublish(EXCHANGE_NAME, severity, null, message.getBytes());
            System.out.println("Send: '" + severity + "':'" + message + "'");
        }
        channel.close();
        connection.close();
    }
}
```

2. 消费者1
此类型数据的规则匹配的是以orange为中间的，头与尾为任意类型的数据
```
channel.queueBind(QUEUE_NAME, EXCHANGE_NAME, "*.orange.*");
```
```
package com.hrabbit.rabbitmq.toptic.recover;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.*;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-30 下午7:42
 * @Description:
 */
public class Recover {

    //队列名称
    private final static String QUEUE_NAME = "hrabbit_queue_topic_1";
    //交换机名称
    private final static String EXCHANGE_NAME = "hrabbit_exchange_topic";

    public static void main(String[] args) throws IOException, TimeoutException {
        // 获取到连接以及mq通道
        Connection connection = ConnectionUtils.getConnection();
        final Channel channel = connection.createChannel();

        // 声明队列
        channel.queueDeclare(QUEUE_NAME, false, false, false, null);
        // 绑定队列到交换机
        channel.queueBind(QUEUE_NAME, EXCHANGE_NAME, "*.orange.*");
        //------------下面逻辑和work模式一样-----
        // 同一时刻服务器只会发一条消息给消费者
        channel.basicQos(1);

        Consumer consumer = new DefaultConsumer(channel){
            @Override
            public void handleDelivery(String consumerTag, Envelope envelope, AMQP.BasicProperties properties, byte[] body) throws IOException {
                // 消息到达 触发这个方法
                String msg = new String(body, "utf-8");
                System.out.println("[*消息]:" + msg);
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException e) {
                    e.printStackTrace();
                } finally {
                    System.out.println("error消息执行完毕.！");
                    // 手动回执
                    channel.basicAck(envelope.getDeliveryTag(), false);
                }
            }
        };

        boolean autoAck = false;
        channel.basicConsume(QUEUE_NAME,autoAck,consumer);

    }
}
```
3. 消费者2
两个匹配规则:
- 以rabbit结尾，前面有任意两种格式的数据
```
channel.queueBind(QUEUE_NAME, EXCHANGE_NAME, "*.*.rabbit");
```
- 以lazy开始的任意规则的数据
```
channel.queueBind(QUEUE_NAME, EXCHANGE_NAME, "lazy.#");
```
```
package com.hrabbit.rabbitmq.toptic.recover;

import com.hrabbit.rabbitmq.utils.ConnectionUtils;
import com.rabbitmq.client.*;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/**
 * @Auther: hrabbit
 * @Date: 2018-06-30 下午7:42
 * @Description:
 */
public class Recover2 {

    //队列名称
    private final static String QUEUE_NAME = "hrabbit_queue_topic_2";
    //交换机名称
    private final static String EXCHANGE_NAME = "hrabbit_exchange_topic";

    public static void main(String[] args) throws IOException, TimeoutException {
        // 获取到连接以及mq通道
        Connection connection = ConnectionUtils.getConnection();
        final Channel channel = connection.createChannel();

        // 声明队列
        channel.queueDeclare(QUEUE_NAME, false, false, false, null);
        // 绑定队列到交换机
        channel.queueBind(QUEUE_NAME, EXCHANGE_NAME, "*.*.rabbit");
        channel.queueBind(QUEUE_NAME, EXCHANGE_NAME, "lazy.#");
        //------------下面逻辑和work模式一样-----
        // 同一时刻服务器只会发一条消息给消费者
        channel.basicQos(1);

        Consumer consumer = new DefaultConsumer(channel){
            @Override
            public void handleDelivery(String consumerTag, Envelope envelope, AMQP.BasicProperties properties, byte[] body) throws IOException {
                // 消息到达 触发这个方法
                String msg = new String(body, "utf-8");
                System.out.println("[info]:" + msg);
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException e) {
                    e.printStackTrace();
                } finally {
                    System.out.println("info消息执行完毕.！");
                    // 手动回执
                    channel.basicAck(envelope.getDeliveryTag(), false);
                }
            }
        };
        boolean autoAck = false;
        channel.basicConsume(QUEUE_NAME,autoAck,consumer);
    }
}
```





