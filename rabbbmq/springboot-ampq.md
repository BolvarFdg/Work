
## 简述
要使用springboot操作rabbitMQ需要以下几个步骤:
- application.yml
    - 配置连接信息
- 一个配置类
    - 初始化队列,路由器,并将队列和路由器绑定
- 生产者
    - 生产者发送消息使用内置的AmqpTemplate或者RabbitTemplate 来操作消息的发送
    - 使用AmqpTemplate可以直接注入使用
    - 使用RabbitTemplate需要在配置文件中配置bean
- 消费者

## 步骤
### 1. 创建一个springboot项目
### 2. pom文件
```
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-amqp</artifactId>
</dependency>
```
### 3. 在application.yml中配置RabbitMQ
spring 节点下
```
  rabbitmq:
    host: localhost # rabbitmq的连接地址
    port: 5672 # rabbitmq的连接端口号
    virtual-host: /mall # rabbitmq的虚拟host
    username: mall # rabbitmq的用户名
    password: mall # rabbitmq的密码
    publisher-confirms: true #如果对异步消息需要回调必须设置为true
```

### 4. 创建一个rabbitMQ配置类
```
/**
 * FileName: Application
 * Description: 该类初始化创建队列、转发器，并把队列绑定到转发器
 */
package com.example.springboot.rabbitmq;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.connection.CachingConnectionFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.rabbit.support.CorrelationData;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 说明：〈该类初始化创建队列、转发器，并把队列绑定到转发器〉
 *
 */
@Configuration
public class Application {
    private static Logger log = LoggerFactory.getLogger(Application.class);
    @Autowired
    private CachingConnectionFactory connectionFactory;
    final static String queueName = "helloQuery";
    @Bean
    public Queue helloQueue() {
        return new Queue(queueName);
    }

    @Bean
    public Queue userQueue() {
        return new Queue("user");
    }

    @Bean
    public Queue dirQueue() {
        return new Queue("direct");
    }
    //===============以下是验证topic Exchange的队列==========
    // Bean默认的name是方法名
    @Bean(name="message")
    public Queue queueMessage() {
        return new Queue("topic.message");
    }

    @Bean(name="messages")
    public Queue queueMessages() {
        return new Queue("topic.messages");
    }
    //===============以上是验证topic Exchange的队列==========

    //===============以下是验证Fanout Exchange的队列==========
    @Bean(name="AMessage")
    public Queue AMessage() {
        return new Queue("fanout.A");
    }

    @Bean
    public Queue BMessage() {
        return new Queue("fanout.B");
    }

    @Bean
    public Queue CMessage() {
        return new Queue("fanout.C");
    }
    //===============以上是验证Fanout Exchange的队列==========

    /**
     *     exchange是交换机交换机的主要作用是接收相应的消息并且绑定到指定的队列.交换机有四种类型,分别为Direct,topic,headers,Fanout.
     *
     * 　　Direct是RabbitMQ默认的交换机模式,也是最简单的模式.即创建消息队列的时候,指定一个BindingKey.当发送者发送消息的时候,指定对应的Key.当Key和消息队列的BindingKey一致的时候,消息将会被发送到该消息队列中.
     *
     * 　　topic转发信息主要是依据通配符,队列和交换机的绑定主要是依据一种模式(通配符+字符串),而当发送消息的时候,只有指定的Key和该模式相匹配的时候,消息才会被发送到该消息队列中.
     *
     * 　　headers也是根据一个规则进行匹配,在消息队列和交换机绑定的时候会指定一组键值对规则,而发送消息的时候也会指定一组键值对规则,当两组键值对规则相匹配的时候,消息会被发送到匹配的消息队列中.
     *
     * 　　Fanout是路由广播的形式,将会把消息发给绑定它的全部队列,即便设置了key,也会被忽略.
     */
    @Bean
    DirectExchange directExchange(){
        return new DirectExchange("directExchange");
    }
    @Bean
    TopicExchange exchange() {
        // 参数1为交换机的名称
        return new TopicExchange("exchange");
    }

    /**
     * //配置广播路由器
     * @return FanoutExchange
     */
    @Bean
    FanoutExchange fanoutExchange() {
        // 参数1为交换机的名称
        return new FanoutExchange("fanoutExchange");
    }

    @Bean
    Binding bindingExchangeDirect(@Qualifier("dirQueue")Queue dirQueue,DirectExchange directExchange){
        return  BindingBuilder.bind(dirQueue).to(directExchange).with("direct");
    }

    /**
     * 将队列topic.message与exchange绑定，routing_key为topic.message,就是完全匹配
     * @param queueMessage
     * @param exchange
     * @return
     */
    @Bean
    // 如果参数名和上面用到方法名称一样，可以不用写@Qualifier
    Binding bindingExchangeMessage(@Qualifier("message")Queue queueMessage, TopicExchange exchange) {
        return BindingBuilder.bind(queueMessage).to(exchange).with("topic.message");
    }

    /**
     * 将队列topic.messages与exchange绑定，routing_key为topic.#,模糊匹配
     * @param queueMessages
     * @param exchange
     * @return
     */
    @Bean
    Binding bindingExchangeMessages(@Qualifier("messages")Queue queueMessages, TopicExchange exchange) {
        return BindingBuilder.bind(queueMessages).to(exchange).with("topic.#");
    }
    @Bean
    Binding bindingExchangeA(@Qualifier("AMessage")Queue AMessage,FanoutExchange fanoutExchange) {
        return BindingBuilder.bind(AMessage).to(fanoutExchange);
    }

    @Bean
    Binding bindingExchangeB(Queue BMessage, FanoutExchange fanoutExchange) {
        return BindingBuilder.bind(BMessage).to(fanoutExchange);
    }

    @Bean
    Binding bindingExchangeC(Queue CMessage, FanoutExchange fanoutExchange) {
        return BindingBuilder.bind(CMessage).to(fanoutExchange);
    }

    @Bean
    public RabbitTemplate rabbitTemplate(){
        //若使用confirm-callback或return-callback，必须要配置publisherConfirms或publisherReturns为true
        //每个rabbitTemplate只能有一个confirm-callback和return-callback，如果这里配置了，那么写生产者的时候不能再写confirm-callback和return-callback
        //使用return-callback时必须设置mandatory为true，或者在配置中设置mandatory-expression的值为true
        connectionFactory.setPublisherConfirms(true);
        connectionFactory.setPublisherReturns(true);
        RabbitTemplate rabbitTemplate = new RabbitTemplate(connectionFactory);
        rabbitTemplate.setMandatory(true);
//        /**
//         * 如果消息没有到exchange,则confirm回调,ack=false
//         * 如果消息到达exchange,则confirm回调,ack=true
//         * exchange到queue成功,则不回调return
//         * exchange到queue失败,则回调return(需设置mandatory=true,否则不回回调,消息就丢了)
//         */
        rabbitTemplate.setConfirmCallback(new RabbitTemplate.ConfirmCallback() {
            @Override
            public void confirm(CorrelationData correlationData, boolean ack, String cause) {
                if(ack){
                    log.info("消息发送成功:correlationData({}),ack({}),cause({})",correlationData,ack,cause);
                }else{
                    log.info("消息发送失败:correlationData({}),ack({}),cause({})",correlationData,ack,cause);
                }
            }
        });
        rabbitTemplate.setReturnCallback(new RabbitTemplate.ReturnCallback() {
            @Override
            public void returnedMessage(Message message, int replyCode, String replyText, String exchange, String routingKey) {
                log.info("消息丢失:exchange({}),route({}),replyCode({}),replyText({}),message:{}",exchange,routingKey,replyCode,replyText,message);
            }
        });
        return rabbitTemplate;
    }
}
```
### 5. 单生产者对单消费者
##### 生产者
名为helloQueue的队列在配置类创建好了，项目启动的时候会自动创建
```
@Component

public class HelloSender1 {

    /**

     * AmqpTemplate可以说是RabbitTemplate父类，RabbitTemplate实现类RabbitOperations接口，RabbitOperations继承了AmqpTemplate接口

     */

    @Autowired

    private AmqpTemplate rabbitTemplate;

    @Autowired

    private RabbitTemplate rabbitTemplate1;

    /**

     * 用于单生产者-》单消费者测试

     */

    public void send() {

        String sendMsg = "hello1 " + new Date();

        System.out.println("Sender1 : " + sendMsg);

        this.rabbitTemplate1.convertAndSend("helloQueue", sendMsg);

    }
}
```
##### 消费者
```
@Component

@RabbitListener(queues = "helloQueue")

public class HelloReceiver1 {



    @RabbitHandler

    public void process(String hello) {

        System.out.println("Receiver1  : " + hello);

    }

}
```
@RabbitListener注解是监听队列的，当队列有消息的时候，它会自动获取。

@RabbitListener 标注在类上面表示当有收到消息的时候，就交给 @RabbitHandler 的方法处理，具体使用哪个方法处理，根据 MessageConverter 转换后的参数类型

==注意==

- 消息处理方法参数是由 MessageConverter 转化，若使用自定义 MessageConverter 则需要在 RabbitListenerContainerFactory 实例中去设置（默认 Spring 使用的实现是 SimpleRabbitListenerContainerFactory）
- 消息的 content_type 属性表示消息 body 数据以什么数据格式存储，接收消息除了使用 Message 对象接收消息（包含消息属性等信息）之外，还可直接使用对应类型接收消息 body 内容，但若方法参数类型不正确会抛异常：
    - application/octet-stream：二进制字节数组存储，使用 byte[]
    - application/x-java-serialized-object：java 对象序列化格式存储，使用 Object、相应类型（反序列化时类型应该同包同名，否者会抛出找不到类异常）
    - text/plain：文本数据类型存储，使用 String
    - application/json：JSON 格式，使用 Object、相应类型

##### controller
```
/** * 最简单的hello生产和消费实现（单生产者和单消费者） */ 
@RequestMapping("/hello") 
public void hello() { 
    helloSender1.send(); 
}
```
### 6. 单生产者对多消费者
##### 生产者
```
/**

 * 用于单/多生产者-》多消费者测试

 */

public void send(String msg) {

    String sendMsg = msg + new Date();

    System.out.println("Sender1 : " + sendMsg);

    this.rabbitTemplate.convertAndSend("helloQueue", sendMsg);

}
```
##### 消费者1
```
@Component

@RabbitListener(queues = "helloQueue")

public class HelloReceiver1 {



    @RabbitHandler

    public void process(String hello) {

        System.out.println("Receiver1  : " + hello);

    }

}
```
##### 消费者2
```
@Component
@RabbitListener(queues = "helloQueue")
public class HelloReceiver2 {

    @RabbitHandler
    public void process(String hello) {
        System.out.println("Receiver2  : " + hello);
    }
}
```

##### controller
```
/**
 * 单生产者-多消费者
 */
@RequestMapping("/oneToMany")
public void oneToMany() {
    for(int i=0;i<10;i++){
        helloSender1.send("hellomsg:"+i);
    }
}
```

### 7.实体类传输,必须格式化
##### 实体类
```
public class User implements Serializable {

    private String name;

    private String pass;

    public String getName() {

        return name;

    }

    public void setName(String name) {

        this.name = name;

    }

    public String getPass() {

        return pass;

    }

    public void setPass(String pass) {

        this.pass = pass;

    }

    @Override

    public String toString() {

        return "User{" +

                "name='" + name + '\'' +

                ", pass='" + pass + '\'' +

                '}';
    }
}
```
##### 生产者
```
/**

 * 实体类的传输（springboot完美的支持对象的发送和接收，不需要格外的配置。实体类必须序列化）

 * @param user

 */

public void send(User user) {

    System.out.println("user send : " + user.getName()+"/"+user.getPass());

    this.rabbitTemplate.convertAndSend("userQueue", user);

}
```
##### 消费者
```
@Component

@RabbitListener(queues = "userQueue")

public class HelloReceiver3 {



    @RabbitHandler

    public void process(User user){

        System.out.println("user receive  : " + user.getName()+"/"+user.getPass());

    }

}
```
##### controller
```
/**

 * 实体列的传输

 */

@RequestMapping("/userTest")

public void userTest(){

    User user=new User();

    user.setName("韩旭杰");

    user.setPass("123456");

    userSender.send(user);

}
```
### directExchange
##### 配置类
```
@Bean

public Queue dirQueue() {

    return new Queue("direct");

}
@Bean

DirectExchange directExchange(){

    return new DirectExchange("directExchange");

}
/**

 * 将队列dirQueue与directExchange交换机绑定，routing_key为direct

 * @param dirQueue

 * @param directExchange

 * @return

 */

@Bean

Binding bindingExchangeDirect(@Qualifier("dirQueue")Queue dirQueue,DirectExchange directExchange){

    return  BindingBuilder.bind(dirQueue).to(directExchange).with("direct");

}
```
##### 生产者
```
@Component

public class DirectSender {

    @Autowired

    private AmqpTemplate rabbitTemplate;

    public void send() {

        String msgString="directSender :hello i am hzb";

        System.out.println(msgString);

        this.rabbitTemplate.convertAndSend("direct", msgString);

    }

}
```
##### 消费者
```
@Component

@RabbitListener(queues = "direct")

public class DirectReceiver {

    @RabbitHandler

    public void process(String msg) {

        System.out.println("directReceiver  : " + msg);

    }

}
```
##### controller
```
@RequestMapping("/directTest") 
public void directTest() {
    directSender.send();
}
```
### topicExchange
##### 配置类
```
// Bean默认的name是方法名
@Bean(name="message")
public Queue queueMessage() {

    return new Queue("topic.message");

}

@Bean(name="messages")
public Queue queueMessages() {

    return new Queue("topic.messages");

}

@Bean
TopicExchange exchange() {

    // 参数1为交换机的名称

    return new TopicExchange("exchange");
}
/**

 * 将队列topic.message与exchange绑定，routing_key为topic.message,就是完全匹配

 * @param queueMessage

 * @param exchange

 * @return

 */

@Bean
// 如果参数名和上面用到方法名称一样，可以不用写@Qualifier
Binding bindingExchangeMessage(@Qualifier("message")Queue queueMessage, TopicExchange exchange) {

    return BindingBuilder.bind(queueMessage).to(exchange).with("topic.message");

}

/**

 * 将队列topic.messages与exchange绑定，routing_key为topic.#,模糊匹配

 * @param queueMessages

 * @param exchange

 * @return

 */

@Bean
Binding bindingExchangeMessages(@Qualifier("messages")Queue queueMessages, TopicExchange exchange) {

    return BindingBuilder.bind(queueMessages).to(exchange).with("topic.#");

}
```
##### 生产者
```
@Component

public class TopicSender {



    @Autowired

    private AmqpTemplate rabbitTemplate;



    public void send() {

        String msg1 = "I am topic.mesaage msg======";

        System.out.println("sender1 : " + msg1);

        this.rabbitTemplate.convertAndSend("exchange", "topic.message", msg1);



        String msg2 = "I am topic.mesaages msg########";

        System.out.println("sender2 : " + msg2);

        this.rabbitTemplate.convertAndSend("exchange", "topic.messages", msg2);
    }
}
```
##### 消费者1
```
@Component

@RabbitListener(queues = "topic.message")

public class TopicMessageReceiver {

    @RabbitHandler

    public void process(String msg) {

        System.out.println("topicMessageReceiver  : " +msg);

    }

}
```
##### 消费者2
```
@Component

@RabbitListener(queues = "topic.messages")

public class TopicMessagesReceiver {

    @RabbitHandler

    public void process(String msg) {

        System.out.println("topicMessagesReceiver  : " +msg);

    }
}
```
##### controller
```
/** * topic exchange类型rabbitmq测试 */ 
@RequestMapping("/topicTest") 
public void topicTest() { 
    topicSender.send(); 
}
```
### fanoutExchange
##### 配置类
```
//===============以下是验证Fanout Exchange的队列==========

@Bean(name="AMessage")
public Queue AMessage() {

    return new Queue("fanout.A");

}

@Bean
public Queue BMessage() {

    return new Queue("fanout.B");

}

@Bean
public Queue CMessage() {

    return new Queue("fanout.C");

}
@Bean
FanoutExchange fanoutExchange() {

    // 参数1为交换机的名称

    return new FanoutExchange("fanoutExchange");

}
@Bean
Binding bindingExchangeA(@Qualifier("AMessage")Queue AMessage,FanoutExchange fanoutExchange) {

    return BindingBuilder.bind(AMessage).to(fanoutExchange);

}

@Bean
Binding bindingExchangeB(Queue BMessage, FanoutExchange fanoutExchange) {

    return BindingBuilder.bind(BMessage).to(fanoutExchange);

}

@Bean
Binding bindingExchangeC(Queue CMessage, FanoutExchange fanoutExchange) {

    return BindingBuilder.bind(CMessage).to(fanoutExchange);

}
```
##### 生产者
```
@Component
public class FanoutSender {

    @Autowired
    private AmqpTemplate rabbitTemplate;
    public void send() {
        String msgString="fanoutSender :hello i am hzb";
        System.out.println(msgString);
        // 参数2被忽略
        this.rabbitTemplate.convertAndSend("fanoutExchange","", msgString);
    }
}
```
##### 消费者1
```
@Component
@RabbitListener(queues = "fanout.A")
public class FanoutReceiverA {

    @RabbitHandler
    public void process(String msg) {
        System.out.println("FanoutReceiverA  : " + msg);
    }
}
```
##### 消费者2
```
@Component
@RabbitListener(queues = "fanout.B")
public class FanoutReceiverB {

    @RabbitHandler

    public void process(String msg) {
        System.out.println("FanoutReceiverB  : " + msg);
    }
}
```
##### 消费者3
```
@Component
@RabbitListener(queues = "fanout.C")
public class FanoutReceiverC {

    @RabbitHandler
    public void process(String msg) {
        System.out.println("FanoutReceiverC  : " + msg);
    }
}
```
##### controller
```
/** * fanout exchange类型rabbitmq测试 */ 
@RequestMapping("/fanoutTest") 
public void fanoutTest() { 
    fanoutSender.send(); 
}
```



## @RabbitListener简述
生产者主要使用工具: RabbitTemplate

生产者的两个重要属性:
- publisher-confirms , 实现一个监听器用于监听Broker端给我们返回的确认请求:RabbitTemplate.ConfirmCallback
- publisher-returns,保证消息对Broker端是可达的,如果出现路由键不可达的情况,则使用监听器对不可达的消息进行后续的处理,保证消息的路由成功:RabbitTemplate.ReturnCallback

消费者主要使用注解: @RabbitMQListener,@RabbitHandler
- @RabbitMQListener 是一个组合注解,里面可以注解配置 @QueueBinding,@Queue,@Exchange直接通过这个组合注解一次搞定消费端交换机,队列,绑定,路由,并且配置监听功能等
- @RabbitMQListener的简单使用
    - 一般把实际内容写在yml配置文件里,再使用${}方式调用实际值

![image](https://note.youdao.com/yws/public/resource/4587f0e796714c620937b7e2b29ba248/xmlnote/6B101E18ACA6468B8D0F9982BDAD1874/6932)


- @RabbitHandler
一般和@RabbitMQListener一起使用,作用是具体方法具体处理

### 实现1

#### yml 配置
```
rabbitmq:
    host: localhost # rabbitmq的连接地址
    port: 5672 # rabbitmq的连接端口号
    virtual-host: /mall # rabbitmq的虚拟host
    username: mall # rabbitmq的用户名
    password: mall # rabbitmq的密码
    
    # 生产端配置
    publisher-confirms:true#如果对异步消息需要回调必须设置为true
    publisher-returns:true #返回
    template:
        mandatory:true
    
    # 消费端配置
    listener:
        simple:
            acknowledge-mode:manual
            concurrency:5
            max-concurrency:10
            
        
```

#### 生产者
```
public class RabbitSender{
    @Autowired
    private RabbitTemplate rabbitTemplate;
    
    //确认模式
    final ConfirmCallback confirmCallback = new RabbitTemplate.ConfirmCallback(){
        @Override
        public void confirm(CorrelationData correlationData, boolean ack, String cause){
            System.err.println("correlationData: "+ correlationData);
            System.err.println("ack: "+ack);
            if(!ack){
                System.err.println("异常处理.....");
            }
        }
    };
    //返回模式
    final ReturnCallback returnCallback = new RabbitTemplate.ReturnCallback(){
        @Override
        public void returnedMessage(org.springframework.amqp.core.Message message, int replyCode, String replyText, String exchange, String routingKey){
            System.err.println("reutrn exchange: "+ exchange + ", routingKey: " 
            + routingKey + ",replyCode: " + replyCode + ", replyText: " + replyText);
        }
    };
    
    // 发送方法
    public void send(Object message, Map<String, Object> properties) throws Exception{
        MessageHeaders mhs = new MessageHeaders(properties);
        Message msg = MessageBuilder.createMessage(message,mhs);
        rabbitTemplate.setConfirmCallback(confirmCallback);
        rabbitTemplate.setReturnCallback(returnCallback);
        //id + 时间戳 , 全局唯一
        CorrelationData correlationData = new CorrelationData("123456789");
        rabbitTemplate.convertAndSend("exchange-1","springboot.hello",msg);
    }
}

```
#### 消费者
```
@Component
public class RabbitReceiver{
    @RabbitListener(binding = @QueueBinding(
        value = @Queue(value="queue-1",durable="true"),exchange = @Exchange(value = "exchange-1",durable="true",
        type="topic",
        ignoreDeclarationExceptions = "true"),
        key = "springboot.*"
    ))
    @RabbitHandler
    public void onMessage(Message message, Channel channel) throws Exception{
        System.err.println("消费端: "+ message.getPayload());
        Long deliveryTag= (Long)message.getHeaders().get(AmqpHeaders.DELIVERY_TAG);
        //手工ack
        channel.basicAck(deliveryTag, false);
    }
}
```
#### 测试方法
```
@Autowired
private RabbitSender rabbitSender;

private static SimpleDateFormat simpleDateFormat = new SimpleDateFormat("yyyy-MM--dd HH:mm:ss");

@Test
public void testSender1() throws Exception(){
    Map<String, Object> properties = new HashMap<>();
    properties.put("number", "12345");
    properties.put("send_time", simpleDateFormat.format(new Date()));
    rabbitSender.send("Hello RabbitMQ For Spring Boot!", properties);
}
```

### 实现2
使用yml注解代替@Queue中的值
```
rabbitmq:
    host: localhost # rabbitmq的连接地址
    port: 5672 # rabbitmq的连接端口号
    virtual-host: /mall # rabbitmq的虚拟host
    username: mall # rabbitmq的用户名
    password: mall # rabbitmq的密码
    
    # 生产端配置
    publisher-confirms:true#如果对异步消息需要回调必须设置为true
    publisher-returns:true #返回
    template:
        mandatory:true
    
    # 消费端配置
    listener:
        simple:
            acknowledge-mode:manual
            concurrency:5
            max-concurrency:10
        order:
            queue:
                name:queue-2
                durable:true
            exchange:
                name:exchange-2
                durable:true
                type:topic
                ignoreDeclarationExcetptions:true
            key:springboot.*
```

在消费者中,使用${}方式调用yml中的值
```
@RabbitListener(binding = @QueueBinding(
        value = @Queue(value="${spring.rabbitmq.listener.order.queue.name}",
        durable="${spring.rabbitmq.listener.order.queue.durable}"),
        exchange = @Exchange(value = "spring.rabbitmq.listener.order.excahnge.name",
        durable="${spring.rabbitmq.listener.order.excahnge.durable}",
        type="${spring.rabbitmq.listener.order.excahnge.name}",
        ignoreDeclarationExceptions = "${spring.rabbitmq.listener.order.excahnge.ignoreDeclarationExcetptions}"),
        key = "${spring.rabbitmq.listener.order.key}")
```


