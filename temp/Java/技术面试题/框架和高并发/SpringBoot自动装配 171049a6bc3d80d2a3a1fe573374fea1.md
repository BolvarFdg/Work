# SpringBoot自动装配

> [https://javaguide.cn/system-design/framework/spring/spring-boot-auto-assembly-principles.html](https://javaguide.cn/system-design/framework/spring/spring-boot-auto-assembly-principles.html)
> 

![94414ED2-04C6-4CEF-9DE4-E005D649963A.jpeg](SpringBoot%E8%87%AA%E5%8A%A8%E8%A3%85%E9%85%8D/94414ED2-04C6-4CEF-9DE4-E005D649963A.jpeg)

1.启动入口。@SpringBootApplication触发@EnableAutoConfiguration.

2.加载候选配置类：通过SpringFactoriesLoader读取所有MATE-INF/spring.factories中的EnableAutoConfiguration候选类

3.条件过滤：使用@Conditional系列注解动态筛选符合条件的配置类（类路径存在、bean不存在、配置属性匹配等）

4.顺序调整：通过@AutoConfigurationOrder、@AutoConfigurationBefore等注解调整配置类加载顺序。5.配置生效：符合条件的配置类被加载到spring容器中，自动注册Bean或执行

6.用户覆盖：用户自定义的bean或配置属性会覆盖自动配置的默认值。

概念：

         SpringBoot 定义了一套接口规范，这套规范规定：SpringBoot 在启动时会扫描外部引用 jar 包中的  META-INF/spring.factories文件，将文件中配置的类型信息加载到 Spring 容器（此处涉及到 JVM 类加载机制与 Spring 的容器知识），并执行类中定义的各种操作。对于外部 jar 来说，只需要按照 SpringBoot 定义的标准，就能将自己的功能装置进 SpringBoot。

实现：

@**SpringBootApplication**

- @**Configuration**: 允许在上下文中注册额外的 bean 或导入其他配置类
- @**ComponentScan**: 扫描被@Component, @Service, @Controller注解的bean， 可以使用 excludeFilters排除某些bean
- @**EnableAutoConfiguration**: 启用 SpringBoot 的自动配置机制
    - @**Import**({AutoConfigurationAutoSelector.class})
        - **AutoConfigurationAutoSelector.class**  —> 继承  —> **ImportSelector**
            - 实现 **selectImport**方法：方法主要用于**获取所有符合条件的类的全限定类名，这些类需要被加载到 IoC 容器**
                - **getAutoConfigurationEntry**(): 这个方法主要负责加载自动配置类的
                    1. 判断自动装配是否打开
                    2. 获取`EnableAutoConfiguration`注解的 `exclude` 和 `excludeName`
                    3. 获取需要自动装配的所有配置类，读取`META-INF/spring.factories`
                    4. 筛选，`@ConditionalOnXXX` 中的所有条件都满足，该类才会生效