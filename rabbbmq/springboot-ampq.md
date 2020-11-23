## Spring AMQP简介
Spring AMQP是Spring对rabbitMQ的api的一个封装,方便操作

Spring AMQP主要包含以下对象:
- RabbitAdmin
- RabbitTemplate
- SimpleMessageListenerContainer
- MessageListenerAdapter
- MessageConverter

## RabbitAdmin
- Spring 整合RabbitMQ需要创建的第一个对象
- 它是用来实现创建队列,交换机,绑定等功能

### Spring整合RabbitMQ并使用RabbitAdmin
#### 1. pom文件
```
    //pom.xml
    <dependency>
      <groupId>com.rabbitmq</groupId>
      <artifactId>amqp-client</artifactId>
      <version>3.5.1</version>
    </dependency>
    <dependency>
        <groupId>org.springframework.amqp</groupId>
        <artifactId>spring-rabbit</artifactId>
        <version>1.4.5.RELEASE</version>
    </dependency>
```
#### 2. 配置类(暂且叫它X)
核心配置就两个:
- 将ConnectionFactory注入spring容器
- 将RabbitMQ注入spring容器
```
@Configuration
@ComponentScan({"com.bfxy.spring.*"})
public class RabbitMQConfig{
    
   /**
     * @Bean注解相当于xml中的<bean></bean> ,方法名相当于id  
     */
    @Bean 
    public ConnectionFactory connectionFactory(){
        CacheingConnectionFactory connectionFactory = new CachingConnectionFactory();
        connectionFactory.setAddresses("192.168.0.1:5627");
        connectionFactory.setUsername("guest");
        connectionFactory.setPassword("guest");
        connectionFactory.setVirtualHost("/");
        return connectionFactory; 
    }
    
    //传入形参时,形参connectionFactory必须和上面的方法名相同
    @Bean
    public RabbitAdmin rabbitAdmin(ConnectionFactory connectionFactory){
        RabbitAdmin rabbitAdmin = new RabbitAdmin(connectionFactory);
        rabbitAdmin.setAutoStartup(true);
        return rabbitAdmin;
    }
}
```

#### 3. 测试
```
@Autowired
private RabbitAdmin rabbitAdmin;

@Test
public void testAdmin() throws Exception{
    //声明三种交换机
    rabbitAdmin.declareExchange(new DirectExchange("test.direct",false,false));
    rabbitAdmin.declareExchange(new TopicExchange("test.topic",false,false));
    rabbitAdmin.declareExchange(new FanoutExchange("test.fanout",false,false));
    
    //创建队列
    rabbitAdmin.declareQueue(new Queue("test.direct.queue",false));
    rabbitAdmin.declareQueue(new Queue("test.topic.queue",false));
    rabbitAdmin.declareQueue(new Queue("test.fanout.queue",false));
    
    //绑定队列和交换机
    //第一种绑定方式:需要提前创建队列和交换机
    rabbitAdmin.declareBinding(new Binding( "test.direct.queue",
                                    Binding.DestinationType.QUEUE,
                                    "test.direct","direct",new HashMap<>()));
    //第二种绑定方式:不需要提前创建队列和交换机
    rabbitAdmin.declareBinding(
        BindingBuilder
        .bind(new Queue("test.topic.queue",false))) //直接创建队列
        .to(new TopicExchange("test.topic",false,false)) //直接创建交换机
        .with("user.#")); //routing key
    //使用第二种方式绑定fanout交换机时,不需要.with来声明routing key
    rabbitAdmin.declareBinding(
        BindingBuilder
        .bind(new Queue("test.fanout.queue",false)))
        .to(new FanoutExchange("test.fanout",false,false));
        
    //清空队列中的消息
    rabbitAdmin.purgeQueue("test.topic.queue",false);
}
```
### 需要注意的几点
- autoStartup必须要设置为true,否则Spring容器不会加载RabbitAdmin
- RabbitAdmin的底层实现就是从Spring容器获取Exchange,Binding,Routingkey以及Queue的@Bean声明,然后使用RabbitTemplate的execute方法执行对应的声明,修改,删除等一系列RabbitMQ基础功能操作


## SpringAMQP声明和普通Java声明的区别
#### 普通Javaapi如何声明一个Exchange,队列,绑定?
```
channel.exchangeDeclare(exchangeName,exchangeType,true,false,false,null);
channel.queueDeclare(queueName,false,false,false,null);
channel.queueBind(queueName,exchangeName,routingKey);
```

#### SpringAMQP 如何声明?
在配置文件中(@Configuration),使用@Bean的方式声明
```
    @Bean
     public TopicExchange exchange001(){
        return new TopicExchange("topic001",true,false);
     }
     
     @Bean
     public Queue queue001(){
        return new Queue("queue001",true);//队列持久
     }
     
     @Bean
     public Binding binding001(){
        return BindingBuilder
            .bind(queue001())
            .to(exchange001())
            .with("spring.*");
     }
```

### 使用新的声明方式拓展配置类X
```
@Configuration
@ComponentScan({"com.bfxy.spring.*"})
public class RabbitMQConfig{
    
   /**
     * @Bean注解相当于xml中的<bean></bean> ,方法名相当于id  
     */
    @Bean 
    public ConnectionFactory connectionFactory(){
        CacheingConnectionFactory connectionFactory = new CachingConnectionFactory();
        connectionFactory.setAddresses("192.168.0.1:5627");
        connectionFactory.setUsername("guest");
        connectionFactory.setPassword("guest");
        connectionFactory.setVirtualHost("/");
        return connectionFactory; 
    }
    
    //传入形参时,形参connectionFactory必须和上面的方法名相同
    @Bean
    public RabbitAdmin rabbitAdmin(ConnectionFactory connectionFactory){
        RabbitAdmin rabbitAdmin = new RabbitAdmin(connectionFactory);
        rabbitAdmin.setAutoStartup(true);
        return rabbitAdmin;
    }
    
    /**
     * 针对消费者配置
     * 1. 设置交换机类型
     * 2. 将队列绑定到交换机
        FanoutExchange: 将消息分发到所有绑定队列,无routingKey概念
        HeadersExchange: 通过添加属性key-value匹配
        DirectExchange: 按照routingkey分发到指定队列
        TopicExchange: 多关键字匹配
     */
     @Bean
     public TopicExchange exchange001(){
        return new TopicExchange("topic001",true,false);
     }
     
     @Bean
     public Queue queue001(){
        return new Queue("queue001",true);//队列持久
     }
     
     @Bean
     public Binding binding001(){
        return BindingBuilder
            .bind(queue001())
            .to(exchange001())
            .with("spring.*");
     }
     
     @Bean
     public TopicExchange exchange002(){
         return new TopicExchange("topic002",true,false);
     }
     
     @Bean
     public Queue queue002(){
         return new Queue("queue002",true);
     }
     
     @Bean
     public Binding binding002(){
         return BindingBuilder
            .bind(queue002())
            .to(exchange002())
            .with("rabbit.*");
     }
}
```
## RabbitTemplate
### 简述
- 一个消息模板
- 发送消息的关键类
- 该类包括的方法有:
    - 可靠性投递消息方法
    - 回调监听消息接口ConfirmCallback
    - 返回值确认接口ReturnCallback
- 整合相关
    - 与Spring整合时需要实例化
    - 与Springboot整合时,在配置文件里添加配置即可
### 如何使用
继续扩展上面配置类X
```
@Configuration
@ComponentScan({"com.bfxy.spring.*"})
public class RabbitMQConfig{
    
   /**
     * @Bean注解相当于xml中的<bean></bean> ,方法名相当于id  
     */
    @Bean 
    public ConnectionFactory connectionFactory(){
        CacheingConnectionFactory connectionFactory = new CachingConnectionFactory();
        connectionFactory.setAddresses("192.168.0.1:5627");
        connectionFactory.setUsername("guest");
        connectionFactory.setPassword("guest");
        connectionFactory.setVirtualHost("/");
        return connectionFactory; 
    }
    
    //传入形参时,形参connectionFactory必须和上面的方法名相同
    @Bean
    public RabbitAdmin rabbitAdmin(ConnectionFactory connectionFactory){
        RabbitAdmin rabbitAdmin = new RabbitAdmin(connectionFactory);
        rabbitAdmin.setAutoStartup(true);
        return rabbitAdmin;
    }
    
    /**
     * 针对消费者配置
     * 1. 设置交换机类型
     * 2. 将队列绑定到交换机
        FanoutExchange: 将消息分发到所有绑定队列,无routingKey概念
        HeadersExchange: 通过添加属性key-value匹配
        DirectExchange: 按照routingkey分发到指定队列
        TopicExchange: 多关键字匹配
     */
     @Bean
     public TopicExchange exchange001(){
        return new TopicExchange("topic001",true,false);
     }
     
     @Bean
     public Queue queue001(){
        return new Queue("queue001",true);//队列持久
     }
     
     @Bean
     public Binding binding001(){
        return BindingBuilder
            .bind(queue001())
            .to(exchange001())
            .with("spring.*");
     }
     
     @Bean
     public TopicExchange exchange002(){
         return new TopicExchange("topic002",true,false);
     }
     
     @Bean
     public Queue queue002(){
         return new Queue("queue002",true);
     }
     
     @Bean
     public Binding binding002(){
         return BindingBuilder
            .bind(queue002())
            .to(exchange002())
            .with("rabbit.*");
     }
     
     //配置RabbitTemplate的bean
     @Bean
     public RabbitTemplate rabbitTemplate(ConnectionFactory connectionFactory){
         RabbitTemplate rabbitTemplate = new RabbitTemplate(connectionFactory);
         return rabbitTemplate;
     }
}
```
注入RabbitTemplate
```
@Autowired
private RabbitTemplate rabbitTemplate;

// 发送消息方式 1
@Test
public void testSendMessage() throws Exception{
    // 1. 创建消息
    MessageProperties messageProperties = new MessageProperties();
    messageProperties.getHeaders().put("desc","信息描述");
    messageProperties.getHeaders().put("type","自定义消息类型");
    Message message = new Message("Hello RabbitMQ".getBytes(),messageProperties);
    
    // 2. 发送消息
    rabbitTemplate.convertAndSend("topic001","spring.amqp",message,new messagePotProcessor(){
        @Override
        public Message postProcessMessage(Message message) throws AmqpException{
            System.err.println("---额外添加的设置---");
            message.getMessageProperties.getHeaders().put("desc","额外修改的信息描述");
            message.getMessageProperties.getHeaders().put("attr","额外新加的属性");
            return message;
        }
    });
}

// 发送消息方式 2
@Test
public void testSendMessage2() throws Exception{
    rabbitTemplate.convertAndSend("topic001","spring.amqp","hello object message send");
    rabbitTemplate.convertAndSend("topic002","rabbit.abc","hello object message send");
}

// 发送消息方式 3
@Test
public void testSendMessage3() throws Exception{
    // 1. 创建消息
    MessageProperties messageProperties = new MessageProperties();
    messageProperties.setContentType("text/plain");
    Message message = new Message("mq 消息1234".getBytes(),messageProperties);
    
    rabbitTemplate.send("topic001","spring.abc",message);
}
```

## SimpleMessageListenerContainer
### 简述
- 这个类非常强大,我们可以对他进行很多设置,对于消费者的配置项,这个类都可以满足
- 监听队列(多个队列),自动启动,自动声明功能
- 设置事务特性,事务管理器,事务属性,事务容量,是否开启事务,回滚消息等
- 设置消费者数量,最小最大数量,批量消费
- 设置消息确认和自动确认模式,是否重回队列,异常捕获handler函数
- 设置消费者标签生成策略,是否独占模式,消费者属性等
- 设置具体的监听器,消息转换器等等
- SimpleMessageListenerContainer可以进行动态设置,比如在运行中的应用可以动态的修改其消费者数量的大小,接收消息的模式等
- 很多基于RabbitMQ的自制定化后端管控台在进行动态设置的时候,也是根据动态配置这一特性去实现的

### 实现
继续扩展配置X
```
@Bean
public SimpleMessageListenerContainer messageContainer(ConnectionFactory connectionFactory){
    SimpleMessageListenerContainer container = new SimpleMessageListenerContainer(connectionFactory);
    container.setQueues(queue001(),queue()002);
    container.setConcurrenConsumers(1);
    container.setDefaultRequeueRejected(false);
    container.setAcknowledgeMode(AcknowledgeMode.AUTO);
    container.setConsumerTagStrategy(new ConsumerTagStrategy(){
        @Override
        public String createConsumerTag(String queue){
            return queue + "_" + UUID.randomUUID().toString();
        }
    });
    container.setMessageListener(new ChannelAwareMessageListener(){
        @Override
        pubblic void onMessage(Message message,Channel channel) throws Exception{
            String msg = new String(message.getBody());
            System.err.println("-----消费者: " + msg);
        }
    });
    return container;
}
```
## MessageListenerAdapter
### 简述
- MessageListenerAdapter即消息监听适配器
- defaultListenerMethod默认监听方法名称:用于设置监听方法名称
- Delegate 委托对象: 实际真实的委托对象,用于处理消息
- queueOrTagToMethodName 队列标识与方法名称组成的集合
- 可以一一进行队列与方法名称的匹配
- 队列和方法名称绑定,即指定队列里的消息会被绑定的方法所接受处理

### 实现
修改SimpleMessageListenerContainer
```
@Bean
public SimpleMessageListenerContainer messageContainer(ConnectionFactory connectionFactory){
    SimpleMessageListenerContainer container = new SimpleMessageListenerContainer(connectionFactory);
    container.setQueues(queue001(),queue()002);
    container.setConcurrenConsumers(1);
    container.setDefaultRequeueRejected(false);
    container.setAcknowledgeMode(AcknowledgeMode.AUTO);
    container.setConsumerTagStrategy(new ConsumerTagStrategy(){
        @Override
        public String createConsumerTag(String queue){
            return queue + "_" + UUID.randomUUID().toString();
        }
    });
   /* container.setMessageListener(new ChannelAwareMessageListener(){
        @Override
        pubblic void onMessage(Message message,Channel channel) throws Exception{
            String msg = new String(message.getBody());
            System.err.println("-----消费者: " + msg);
        }
    });
    */
    // 适配器方式1:默认有自己的方法名:handleMessage
    // 也可以自己指定一个方法名:conumeMessage
    // 也可以添加一个转换器: 从字节数组转换为String
  /**  MessageListenerAdapter adapter = new MessageListenerAdaptere(new MessageDelegate());
    adapter.setDefaultListenerMethod("consumeMessage");
    adpater.setMessageConverter(new TextMessageConverter());
    container.setMessageListener(adapter);
    return container;
    */
    
    /**
     * 适配器方式2: 队列名称和方法名称也可以一一匹配
     *
     */
     MessageListenerAdapter adapter = new MessageListenerAdapter(new MessageDelegate());
     Map<String,String> queueOrTagToMethodName = new HashMap<>();
     queueOrTagToMethodName.put("queue001","mehtod1");
     queueOrTagToMethodName.put("queue002","mehtod2");
     adapter.setQueueOrTagTomethodName(queueOrTagMethodName);
     container.setMessageListener(adapter);
     return container;
}
```

## MessageConverter
### 简述
- 消息转换器
- 我们在发送消息时,正常情况下消息体为二进制的数据方式进行传输,如果希望内部帮我们进行转换,或者指定自定义的转换器,就需要用到MessageConverter
- 实现MessageConverter这个接口
- 重写下面两个方法:
    - toMessage: java对象转换为Message
    - fromMessage: Message对象转换为java对象
- 其他形式的转换器
    - Json转换器: Jackson2JsonMessageConverter,可以进行Java对象的转换功能
    - DefaultJackson2JavaTypeMapper映射器:可以进行Java对象的映射关系
    - 自定义二进制转换器: 比如图片类型,pdf,ppt,流媒体

### 实现
1. 支持json格式的转换器
```
@Bean
public SimpleMessageListenerContainer messageContainer(ConnectionFactory connectionFactory){
    MessageListenerAdapter adapter = new MessageListenerAdapter(new MessageDelegate());
    adapter.setDefaultListenerMethod("consumeMessage");
    
    Jackson2JsonMessageConverter jackson2JsonMessageConverter = new Jackson2JsonMessageConverter();
    adapter.setMessageConverter(jackson2JsonMessageConverter);
    container.setMessageListener(adapter);
}
```
2. 支持Java对象转换
```
@Bean
public SimpleMessageListenerContainer messageContainer(ConnectionFactory connectionFactory){
    MessageListenerAdapter adapter = new MessageListenerAdapter(new MesssageDelegatee());
    Jackson2JsonMessageConverter jackson2JsonMessageConverter = new Jackson2JsonMessageConverter();
    DefaultJackson2JavaTypeMapper javaTypeMapper = new DefaultJackson2JavaTypeMapper();
    jackson2JsonMessageConverter.setJavaTypeMapper(javaTypeMapper);
    
    adapter.setMessageConverter(jackson2JsonMessageConverter);
    container.setMessageListener(adapter);
}
```
3. 支持Java对象多映射转换
```
@Bean
public SimpleMessageListenerContainer messageContainer(ConnectionFactory connectionFactory){
    MessageListenerAdapter adapter = new MessageListenerAdapter(new MesssageDelegatee());
    adapter.setDefaultListenerMethod("consumeMessage");
    Jackson2JsonMessageConverter jackson2JsonMessageConverter = new Jackson2JsonMessageConverter();
    DefaultJackson2JavaTypeMapper javaTypeMapper = new DefaultJackson2JavaTypeMapper();
    Map<String, Class<?>> idClassMapping = new HashMap<String, Class<?>>();
    idClassMapping.put("order",Order.class);
    idClassMapping.put("packaged",com.bfxy.spring.entity.Packaged.class);
    javaTypeMapper.setIdClassMapping(idClassMapping);
    jackson2JsonMessageConverter.setJavaTypeMapper(javaTypeMapper);
    
    adapter.setMessageConverter(jackson2JsonMessageConverter);
    container.setMessageListener(adapter);
}
```
4. ext全局转换器
```
@Bean
public SimpleMessageListenerContainer messageContainer(ConnectionFactory connectionFactory){
    ContentTypeDelegationgMessageConverter convert = new ContentTypeDelegatingMessageConverter();
    
    TextMessageConverter textConvert = new TextMessageConverter();
    convert.addDelegate("text",textConvert);
    convert.addDelegate("html/text",textConvert);
    convert.addDelegate("xml/text",textConvert);
    convert.addDelegate("text/plain",textConvert);
    
    Jackson2JsonMessageConverter jsonConvert = new Jackson2JsonMessageConverter();
    convert.addDelegate("json",textConvert);
    convert.addDelegate("application/json",textConvert);
    
    ImageMessageConverter imageConverter = new ImageMessageConverter();
    convert.addDelegate("image/png",textConvert);
    convert.addDelegate("image",textConvert);
    
    PDFMessageConverter pdfConverter = new PDFMessageConverter();
    convert.addDelegate("application/pdf",textConvert);
    
    adapter.setMessageConverter(convert);
    container.setMessageListener(adapter);
    
    return container;
}
```
