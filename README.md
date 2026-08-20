# astrbot_plugin_buff_cs2

CS 饰品 · BUFF 平台商品询价插件。在 QQ 群里查询 CS2 饰品价格、30 天走势、同品类值得关注的商品。

## 功能

- `/buff [枪名] [皮肤名] [磨损]`：查询饰品基础信息（官方名称、图标）、当前**在售最低价**、**最高求购价**（含求购附带条件）、30 天价格走势与一句购买建议。
- 未写磨损时自动列出该皮肤的全部磨损与底价，让用户补充磨损后查询。
- **武器类**（步枪/手枪/冲锋枪/霰弹枪/机枪/刀/手套）自动追加消息二：扫描同品类 Top 商品，按 **低印花溢价率(SP<30%) > 低价格 > 低磨损** 排序，推荐最值得关注的三件。
- 印花溢价率 SP% = (出售价格 − 区间底价 − 挂件价格) ÷ 印花总价。

## 示例

```
/buff ak 燃料喷射器 久经
/buff AK-47 燃料喷射器 fn
/buff awp 二西莫夫
/buff 蝴蝶刀 多普勒
```

磨损写法（中文或缩写均可）：崭新出厂/fn、略有磨损/mw、久经沙场/ft、破损不堪/ww、战痕累累/bs。

## 安装与配置

1. 把本插件目录放入 `data/plugins/` 并安装依赖 `aiohttp`。
2. 在插件配置中填写 `buff_cookie`（必填）：
   - Chrome 登录 `buff.163.com` → F12 → Application → Cookies → `buff.163.com` → 复制名为 `session` 的 Value 填入。
   - BUFF 接口必须登录才可访问，Cookie 是硬性必需。
3. 其余配置项（均有默认值）：
   - `cooldown_seconds`：同一用户指令冷却，默认 5 秒
   - `request_delay`：每次 BUFF 请求间隔，默认 0.8 秒（防 429 限流）
   - `scan_num`：同品类扫描商品数量，默认 30
   - `cache_ttl`：同品类扫描结果缓存秒数，默认 600
   - `max_retries`：失败重试次数，默认 3

## 数据与规则说明

- 价格来源：网易 BUFF 官方接口（`buff.163.com/api/market/*`），需登录 Cookie。
- 走势：近 30 天 `sell_min_price_history`（BUFF 人民币在售最低价），非 Steam 美元价。
- 求购：BUFF 求购单可能附带指定条件（磨损区间/印花等），消息一会在顶格求购上注明。
- 分类：同品类过滤使用 `category_group`（rifle/pistol/knife/hands/smg/shotgun/machinegun），`category` 参数无效。

## 目录结构

```
astrbot_plugin_buff_cs2/
├── metadata.yaml       # 插件元数据
├── _conf_schema.json   # 插件配置项
├── requirements.txt
├── main.py             # Star 插件入口（指令、冷却、缓存、进度）
├── buff_client.py      # BUFF 异步接口客户端（UA/节流/重试）
├── parser.py           # 枪名别名表 / 磨损解析
├── analysis.py         # 走势总结 / SP 计算 / 品类排序
└── service.py          # 搜索匹配 / 消息组装
```

## 开发

```bash
git init
git add -A
git commit -m "feat: BUFF CS2 饰品询价插件 v0.1.0"
gh repo create astrbot_plugin_buff_cs2 --public --source=. --push
```
