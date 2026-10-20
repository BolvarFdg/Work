# MySQL 索引失效场景

## MySQL 索引失效场景

---

### 一、11 种常见失效场景

#### 1. 对索引列做运算

```
-- ❌ 失效：索引列做了 +1
SELECT * FROM users WHERE id + 1 = 100;

-- ✅ 改成：把运算移到右边
SELECT * FROM users WHERE id = 99;
```

**原理**：B+ 树是按索引列原始值排序的，列上做了运算，优化器就无法用有序性定位。

---

#### 2. 对索引列用函数

```
-- ❌ 失效
SELECT * FROM orders WHERE DATE(create_time) = '2026-09-30';
SELECT * FROM users  WHERE UPPER(name) = 'TOM';

-- ✅ 改成：范围查询 / 函数建索引
SELECT * FROM orders WHERE create_time >= '2026-09-30'
                      AND create_time < '2026-10-01';
```

---

#### 3. 违反最左前缀原则

联合索引 `(a, b, c)`：

```
-- ✅ 走索引
WHERE a = 1
WHERE a = 1 AND b = 2
WHERE a = 1 AND b = 2 AND c = 3

-- ❌ 失效（没带 a）
WHERE b = 2
WHERE c = 3

-- ⚠️ 部分走索引（a 走了，b 用不上）
WHERE a = 1 AND c = 3
```

**原理**：B+ 树先按 a 排序，a 相同再按 b 排序，b 相同再按 c 排序。跳过 a 直接查 b，索引树的有序性就没了。

---

#### 4. 范围查询右边的列用不上索引

```
-- 联合索引 (a, b, c)
-- ✅ a、b 走索引，c 走不到
WHERE a = 1 AND b > 2 AND c = 3;
```

> 范围查询（`>`、`<`、`BETWEEN`、`LIKE 'xxx%'`）右边的列无法再用索引排序。
> 

---

#### 5. 隐式类型转换

```
-- phone 是 VARCHAR 类型
-- ❌ 失效：字符串字段用数字查，MySQL 会把列转成数字
SELECT * FROM users WHERE phone = 13800138000;

-- ✅ 加引号
SELECT * FROM users WHERE phone = '13800138000';
```

**原理**：`WHERE phone = 13800138000` 等价于 `WHERE CAST(phone AS DECIMAL) = 13800138000`，索引列上做了函数，失效。

---

#### 6. LIKE 以 % 开头

```
-- ❌ 失效
SELECT * FROM users WHERE name LIKE '%tom';

-- ✅ 右边匹配可以走索引
SELECT * FROM users WHERE name LIKE 'tom%';
```

**原理**：B+ 树按从左到右排序，`%tom` 不知道开头是什么，无法定位。

> 如果必须左模糊，用**全文索引**或**ES**。
> 

---

#### 7. OR 条件两边有非索引列

```
-- name 有索引，age 没索引
-- ❌ 失效（age 没索引，整个 OR 都不走索引）
SELECT * FROM users WHERE name = 'tom' OR age = 20;

-- ✅ age 也建索引，或改成 UNION ALL
SELECT * FROM users WHERE name = 'tom'
UNION ALL
SELECT * FROM users WHERE age = 20;
```

---

#### 8. `!=` / `<>` / `NOT IN` / `NOT EXISTS`

```
-- ❌ 通常失效（索引区分度低时优化器放弃）
SELECT * FROM users WHERE status != 1;
SELECT * FROM users WHERE id NOT IN (1, 2, 3);
```

**原理**：不等于要扫大部分数据，优化器觉得全表扫更快。

---

#### 9. IS NULL / IS NOT NULL

```
-- 早期版本可能失效，5.6+ 视数据分布而定
SELECT * FROM users WHERE email IS NULL;
```

如果 NULL 值占比很高，优化器会放弃索引。

---

#### 10. 优化器判断全表扫更快

```
-- 表只有 100 行，优化器觉得走索引还要回表，不如直接全表扫
SELECT * FROM users WHERE name = 'tom';
```

这不是错误，是优化器的合理选择。

---

#### 11. 分页太深

```
-- ❌ 慢：先扫 100000 行再丢弃前 99990 行
SELECT * FROM orders ORDER BY id LIMIT 100000, 10;

-- ✅ 改成游标/子查询
SELECT * FROM orders WHERE id > 100000 ORDER BY id LIMIT 10;
```

---

### 二、一张表总结

| 场景 | 例子 | 修复 |
| --- | --- | --- |
| 索引列运算 | `WHERE id + 1 = 100` | 运算移到右边 |
| 索引列函数 | `WHERE DATE(t) = '...'` | 改范围查询 |
| 违反最左前缀 | 联合索引跳过第一列 | 按顺序写 |
| 范围查询右边列 | `a=1 AND b>2 AND c=3` | c 放范围左边 |
| 隐式类型转换 | VARCHAR 用数字查 | 加引号 |
| LIKE % 开头 | `LIKE '%tom'` | 改右模糊 / 全文索引 |
| OR 有非索引列 | `name='a' OR age=20` | age 建索引 / UNION |
| != / NOT IN | `status != 1` | 改成范围或 IN |
| IS NOT NULL | 大量 NULL 值 | 减少 NULL 占比 |
| 小表全表扫 | 表太小 | 正常现象，不用管 |
| 深分页 | `LIMIT 100000, 10` | 改成游标查询 |

---

### 三、怎么验证索引有没有生效？

```
-- 看 EXPLAIN
EXPLAIN SELECT * FROM users WHERE phone = '13800138000';

-- 重点看：
-- type 是不是 ALL（全表扫）
-- key 是不是 NULL（没用索引）
-- rows 是不是接近全表行数
```

---

### 四、一句话总结

> 索引失效的核心原因就两个：**①索引列上做了操作（运算、函数、类型转换）破坏了 B+ 树的有序性；②违反最左前缀原则，导致优化器无法用索引定位**。生产排查就是看 EXPLAIN 的 type 和 key。
> 

需要我把这份索引失效笔记也写成 Notion 文件吗？