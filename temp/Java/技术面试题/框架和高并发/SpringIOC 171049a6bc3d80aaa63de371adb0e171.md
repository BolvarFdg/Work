# SpringIOC

# IOC 概述

Spring IoC（控制反转）容器是 Spring 框架的核心，负责管理应用中对象的生命周期、依赖注入和配置。它通过将对象的创建和依赖关系的控制权从代码转移到容器，提高了代码的灵活性和可维护性。以下是 Spring IoC 容器的核心概念和工作原理：

---

### **1. IoC（控制反转）**

- **传统方式**：开发者直接通过 `new` 关键字创建对象，并手动管理对象间的依赖。
- **IoC 方式**：对象（Bean）的创建、配置和依赖关系由容器管理，开发者只需定义 Bean 的元数据（如 XML、注解或 Java 配置），容器负责实例化并注入依赖。
- **依赖注入（DI）**：IoC 的实现方式，通过构造函数、Setter 方法或字段注入依赖对象。

---

### **2. Spring 容器的核心接口**

- **`BeanFactory`**：基础容器接口，提供 Bean 的注册、获取和管理功能（延迟初始化）。
- **`ApplicationContext`**：扩展了 `BeanFactory`，提供更高级功能（如国际化、事件发布、资源加载等），是实际开发中常用的容器（默认立即初始化 Bean）。

---

### **3. 容器的核心功能**

### **(1) Bean 的生命周期管理**

- **实例化**：容器根据配置创建 Bean 实例。
- **属性注入**：通过依赖注入（DI）设置 Bean 的属性和依赖。
- **初始化**：调用 `init-method` 或 `@PostConstruct` 注解的方法。
- **销毁**：调用 `destroy-method` 或 `@PreDestroy` 注解的方法。

### **(2) 依赖注入方式**

- **构造器注入**：通过构造函数传递参数。
- **Setter 注入**：通过 Setter 方法设置属性。
- **字段/方法注入**：使用 `@Autowired` 或 `@Resource` 注解直接注入字段或方法。

### **(3) 配置元数据**

- **XML 配置**：传统方式，通过 `<bean>` 标签定义 Bean。
    
    ```xml
    <bean id="userService" class="com.example.UserService">
      <property name="userDao" ref="userDao"/>
    </bean>
    
    ```
    
- **注解配置**：使用 `@Component`, `@Service`, `@Repository`, `@Controller` 等注解标记 Bean，并通过 `@Autowired` 注入依赖。
- **Java 配置**：使用 `@Configuration` 和 `@Bean` 注解定义 Bean。
    
    ```java
    @Configuration
    public class AppConfig {
      @Bean
      public UserService userService() {
        return new UserServiceImpl(userDao());
      }
    }
    
    ```
    

### **(4) Bean 的作用域**

- **Singleton（默认）**：每个容器中只有一个 Bean 实例。
- **Prototype**：每次请求都创建新实例。
- **Request/Session/application**：Web 应用中特定作用域。

### **(5) 自动装配（Autowiring）**

- 容器根据类型（`byType`）、名称（`byName`）或构造函数自动注入依赖。
- 常用注解：`@Autowired`, `@Qualifier`, `@Primary`。

---

### **4. 示例代码**

### 通过注解配置 Bean：

```java
@Component
public class UserService {
  @Autowired
  private UserDao userDao;
}

```

### 启动容器并获取 Bean：

```java
public class Main {
  public static void main(String[] args) {
    ApplicationContext context = new AnnotationConfigApplicationContext("com.example");
    UserService userService = context.getBean(UserService.class);
  }
}

```

---

### **5. 常见问题**

- **循环依赖**：Spring 通过三级缓存解决单例 Bean 的循环依赖（构造器注入无法解决）。
- **Bean 的作用域错误**：例如在单例 Bean 中注入原型 Bean，需使用 `@Scope(proxyMode=...)` 或方法注入。
- **配置错误**：如未扫描到注解、Bean 名称冲突等。

---

### 6. IOC解决了什么问题？

IoC 的思想就是两方之间不互相依赖，由第三方容器来管理相关资源。这样有什么好处呢？

1. 对象之间的耦合度或者说依赖程度降低；
2. 资源变的容易管理；比如你用 Spring 容器提供的话很容易就可以实现一个单例

---

### **7. 总结**

Spring IoC 容器通过管理对象创建和依赖关系，降低了代码耦合度，提升了可测试性和扩展性。结合 XML、注解或 Java 配置，开发者可以灵活定义 Bean 的行为，而容器则负责处理复杂的生命周期和依赖逻辑。理解 IoC 和 DI 是掌握 Spring 框架的基础。

# 如何访问某个Bean

在Spring IoC容器中，可以通过多种方式访问某个Bean。以下是几种常见的方法：

---

### **1. 通过`ApplicationContext`或`BeanFactory`获取Bean**

Spring IoC容器提供了`ApplicationContext`和`BeanFactory`接口，用于管理和访问Bean。可以通过以下方式从容器中获取Bean：

### **(1) 使用`getBean()`方法**

这是最直接的方式，通过`ApplicationContext`或`BeanFactory`的`getBean()`方法获取Bean。`getBean()`方法有多种重载形式，可以根据Bean的名称、类型或两者的组合来获取Bean。

```jsx
import org.springframework.context.ApplicationContext;
import org.springframework.context.support.ClassPathXmlApplicationContext;

public class Main {
    public static void main(String[] args) {
        // 加载Spring容器
        ApplicationContext context = new ClassPathXmlApplicationContext("applicationContext.xml");

        // 根据Bean的名称获取Bean
        MyService serviceByName = context.getBean("myService", MyService.class);

        // 根据Bean的类型获取Bean
        MyService serviceByType = context.getBean(MyService.class);

        // 使用Bean
        serviceByName.doSomething();
        serviceByType.doSomething();
    }
}
```

**注意：**

- 如果容器中有多个相同类型的Bean，通过类型获取Bean时可能会抛出`NoUniqueBeanDefinitionException`。
- 如果Bean的名称或类型不存在，会抛出`NoSuchBeanDefinitionException`。

---

### **(2) 使用`@Autowired`注解**

在Spring管理的Bean中，可以通过`@Autowired`注解自动注入依赖的Bean。这种方式是最常用的，因为它可以减少代码的侵入性。

```jsx
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

@Component
public class MyController {
    @Autowired
    private MyService myService;

    public void handleRequest() {
        myService.doSomething();
    }
}
```

在这种方式中，Spring容器会自动根据类型查找并注入依赖的Bean。如果存在多个相同类型的Bean，可以通过`@Qualifier`注解指定具体的Bean名称。

---

### **(3) 使用`@Resource`或`@Inject`注解**

除了`@Autowired`，Spring还支持`@Resource`（JSR-250）和`@Inject`（JSR-330）注解来注入Bean。

```jsx
import javax.annotation.Resource;
import org.springframework.stereotype.Component;

@Component
public class MyController {
    @Resource(name = "myService")
    private MyService myService;

    public void handleRequest() {
        myService.doSomething();
    }
}
```

`@Resource`注解可以通过`name`属性指定Bean的名称，而`@Inject`注解则依赖于类型匹配。

---

### **2. 通过`ApplicationContext`的`getBeansOfType()`方法**

如果需要获取容器中所有某个类型的Bean，可以使用`ApplicationContext`的`getBeansOfType()`方法。这会返回一个`Map`，其中键是Bean的名称，值是Bean的实例。

### java复制

```jsx
import org.springframework.context.ApplicationContext;
import org.springframework.context.support.ClassPathXmlApplicationContext;

import java.util.Map;

public class Main {
    public static void main(String[] args) {
        ApplicationContext context = new ClassPathXmlApplicationContext("applicationContext.xml");

        // 获取所有MyService类型的Bean
        Map<String, MyService> services = context.getBeansOfType(MyService.class);

        // 遍历并使用Bean
        for (Map.Entry<String, MyService> entry : services.entrySet()) {
            System.out.println("Bean Name: " + entry.getKey());
            entry.getValue().doSomething();
        }
    }
}
```

---

### **3. 使用`BeanFactory`的`containsBean()`方法**

如果只是需要检查容器中是否存在某个Bean，可以使用`BeanFactory`的`containsBean()`方法。

### java复制

```jsx
import org.springframework.beans.factory.BeanFactory;
import org.springframework.context.support.ClassPathXmlApplicationContext;

public class Main {
    public static void main(String[] args) {
        BeanFactory factory = new ClassPathXmlApplicationContext("applicationContext.xml");

        // 检查容器中是否存在某个Bean
        boolean exists = factory.containsBean("myService");
        System.out.println("Bean 'myService' exists: " + exists);
    }
}
```

---

### **4. 使用`@Configuration`类和`@Bean`注解**

在基于Java配置的场景中，可以通过`@Configuration`类和`@Bean`注解显式定义Bean，并在需要的地方获取它们。

```jsx
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AppConfig {
    @Bean
    public MyService myService() {
        return new MyService();
    }
}
```

然后通过`ApplicationContext`获取Bean：

### java复制

```jsx
ApplicationContext context = 
                 new AnnotationConfigApplicationContext(AppConfig.class);
MyService service = context.getBean(MyService.class);
```

---

### **5. 总结**

Spring IoC容器提供了多种方式来访问Bean：

- **通过`ApplicationContext`或`BeanFactory`的`getBean()`方法**：适合直接从容器中获取Bean。
- **通过`@Autowired`、`@Resource`或`@Inject`注解**：适合在Spring管理的Bean中自动注入依赖。
- **通过`getBeansOfType()`方法**：适合获取容器中所有某个类型的Bean。
- **通过`containsBean()`方法**：适合检查容器中是否存在某个Bean。

选择哪种方式取决于你的具体需求和使用场景。