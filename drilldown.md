# 板块内下钻功能升级

我先定位并梳理现有“板块内下钻”的实现与节点/映射/打分链路，再据此把方案升级为 GICS 树、产业链图、ETF proxy 与 synthetic node basket 的统一框架，并用 XLK→半导体/软件/硬件→设备/存储/连接/计算→光/铜 这条链路给出可落地示例。

我还确认到几个可复用抓手：现有链路已隐含支持节点作用域、去重刷新和多 ETF 比较。接下来会优先核对可用 ETF proxy 与需用 synthetic basket 补足的细分节点。

我已经把现有实现可复用与必须改造的边界分开了：底层 ETF/holding/stock/score 与比较链路还能复用，但要把“节点”提升为一等对象。接下来会直接落到产品、策略、数据三层的一体化升级，并给出可落地的 XLK 节点方案。

我先给结论：当前这版“板块内下钻”还不是一个真正的“板块下钻引擎”，而是一个\*\*`sector ETF + 同 sector 的 industry ETF 列表` 的二层任务模型\*\*。所以你要的这条路径——

**XLK → 半导体 vs 软件 vs 硬件  
半导体 → 设备 vs 存储 vs 连接 vs 计算  
连接 → 光 vs 铜**

本质上不是“再往现有树里多塞几只 ETF”能解决的，而是要把分析对象从 **ETF** 升级成 **节点（node）**。

1\. 我读完代码后的判断
-------------

当前实现的硬约束非常明确：

*   后端校验把 drilldown/momentum 固定成“必须先指定一个 `sector`，然后只能添加 `type == industry` 且 `parent_sector == sector` 的 ETF”。这在 `backend/app/api/tasks.py:95-158` 写死了。
*   任务详情页的监控列表，对 drilldown 任务也只是“`sector + task.etfs`”平铺出来，仍然是二层逻辑，见 `backend/app/api/tasks.py:189-205`。
*   数据模型里，`ETF` 只有 `type = sector|industry` 和一个 `parent_sector`，`Task` 也只有 `sector + etfs[]`，见 `backend/app/models/database.py:118-179`。
*   ETF API 也只支持 `/sectors` 与 `/industries?sector=...`，没有“节点”“多层子节点”“图关系”这些概念，见 `backend/app/api/etfs.py:1383-1452`。
*   前端 `CreateTaskModal` 里，XLK 子项是硬编码的 `SOXX / SMH / IGV / SKYY / HACK / CLOU`，见 `frontend/src/components/modal/CreateTaskModal.tsx:38-46`。这其实已经把**同一语义的替代 proxy**（SOXX/SMH）、**正式行业**（IGV）和**主题 ETF**（SKYY/CLOU/HACK）混在一起了。
*   `AddTaskETFsModal`、`CoreTerminal`、`TaskDetail`、`stocks.py` 都只认 `sector/industry/stock`，不认“节点 / proxy / synthetic / chain leaf”，见 `frontend/src/components/modal/AddTaskETFsModal.tsx:87-100`、`frontend/src/pages/CoreTerminal.tsx:567-585`、`frontend/src/components/task/TaskDetail.tsx:1449-1464`、`backend/app/api/stocks.py:279-296`。
*   测试也把业务语义固化成了“drilldown 只能加同 sector 的 industry ETF”，见 `backend/tests/test_tasks_api.py:25-33, 81-103`。

所以现在这个功能的真实语义不是“板块下钻”，而是：

**先选一个 sector ETF，然后在同 sector 下，手工挑若干 industry/thematic ETF 做平级对比。**

这也是为什么它天然撑不起你要的三层路径，更撑不起“GICS 树 + 产业链图 + ETF proxy + synthetic node basket”。

2\. 现在最核心的问题，不是深度不够，而是“节点”和“工具”混在一起了
------------------------------------

现有实现把 **分析节点** 和 **市场表达工具** 混成了一件事。

比如在 XLK 下面：

*   `SOXX` 和 `SMH` 其实都在表达“半导体”这个节点；
*   `IGV` 在表达“软件”这个节点；
*   `SKYY / CLOU / HACK` 更像“云 / 安全”这种**证据节点**或**主题确认器**，而不是与“半导体 / 软件 / 硬件”同一层级的主节点。

所以正确的升级方向不是继续扩 `INDUSTRY_ETFS`，而是先把语义拆开：

*   **GICS 树**解决“谁属于谁”；
*   **产业链图**解决“谁驱动谁、谁传导到谁”；
*   **ETF proxy**解决“市场如何交易这个节点”；
*   **synthetic node basket**解决“没有干净 ETF 时，怎么构造可分析的节点”。

也就是说，**ETF 从主角降级为观察器，node 才是主角**。

3\. 建议的完整体系：从 ETF-centric 升级成 Node-centric
------------------------------------------

我建议把“板块下钻”升级成四层体系。

### 第一层：节点层

把所有分析对象统一成“节点”，而不是 ETF。

节点至少分四类：

*   **GICS 节点**：如 `XLK`、`半导体`、`软件`
*   **产业链节点**：如 `设备`、`计算`、`存储（内存）`、`连接`
*   **介质叶子节点**：如 `光`、`铜`
*   **证据/主题节点**：如 `云计算`、`网络安全`，它们不一定是主树节点，但可以作为确认因子

### 第二层：关系层

节点之间不再只有 `parent_sector` 这种单父关系，而是多种边：

*   **classification\_parent**：GICS 父子关系
*   **chain\_parent**：产业链父子关系
*   **proxy\_of**：ETF 是哪个节点的 proxy
*   **corroborates**：哪个主题节点用于确认主节点
*   **overlaps\_with**：两个节点的成分重叠
*   **drives / depends\_on**：上下游驱动关系

这样才能同时表达：

*   `XLK → 半导体 / 软件 / 硬件`（分类视角）
*   `半导体 → 设备 / 计算 / 存储 / 连接`（产业链视角）
*   `连接 → 光 / 铜`（物理介质视角）

### 第三层：市场表达层

每个节点都要有“怎么被市场观察”的定义，但这个定义不是唯一的：

*   有干净 ETF 的，用 **primary ETF proxy**
*   有多个 ETF 都能表达的，用 **primary + secondary corroboration**
*   没有干净 ETF 的，用 **synthetic node basket**
*   跨出父 ETF 成分范围的，打上 **chain extension** 标记

### 第四层：分析输出层

每个节点输出的不是只有一个涨跌分，而是一组标准结果：

*   相对强弱
*   趋势质量
*   成分股广度
*   领导集中度
*   表达纯度 / 置信度
*   上下游确认度
*   与兄弟节点的重叠度
*   推荐下一个 drill 节点

4\. 用 XLK 做完整示例
---------------

截至 **2026-04-15**，XLK 官方行业分布大致是：**半导体及半导体设备 44.81%、软件 24.91%、技术硬件/存储/外设 16.66%、通信设备 5.53%、电子设备仪器元件 4.61%、IT 服务 3.49%**；前十大持仓里也已经包含 NVDA、AAPL、MSFT、AVGO、MU、AMD、LRCX、CSCO、AMAT 等。这说明把 XLK 顶层压缩成“半导体 / 软件 / 硬件”是合理的，但其中“硬件”并不是官方单一 GICS 桶，而应当是一个**产品化聚合节点**。[State Street Global Advisors](https://www.ssga.com/us/en/intermediary/etfs/the-technology-select-sector-spdr-fund-xlk)

### 顶层结构

我建议 XLK 的默认主树这样定义：

*   **XLK**
    *   **半导体**
    *   **软件**
    *   **硬件**
    *   （高级模式下显示 `IT Services / Other` residual node，不放默认主界面）

这里的关键是：

*   **半导体**：节点
    *   Primary proxy：`SOXX`
    *   Secondary corroboration：`SMH`
*   **软件**：节点
    *   Primary proxy：`IGV`
*   **硬件**：节点
    *   不是单一 ETF proxy，而是 **synthetic aggregate**
    *   由 `Technology Hardware, Storage & Peripherals + Communications Equipment + Electronic Equipment` 聚合而成
    *   `IT Services` 作为 residual 或高级模式单独显示

SOXX 的官方定义就是定向暴露于美国半导体公司；IGV 的官方定义是北美软件公司定向暴露；SMH 的持仓同时覆盖 NVDA、AMD、MU、LRCX、KLAC、ASML、AMAT、MRVL 等，天然横跨计算、内存、设备和连接相关半导体链条。相反，像 IGM 这类科技 ETF 暴露更宽，同时覆盖 hardware、software、internet marketing 和 interactive media，更适合作为旁证，而不是“硬件”节点的一手 proxy。基于这些官方口径，我认为**半导体 / 软件应采用 ETF proxy，硬件应采用 synthetic node**。[BlackRock+3BlackRock+3BlackRock+3](https://www.ishares.com/us/products/239705/SOXX)

### 半导体二级结构

`半导体` 节点下面，我建议拆成四个主子节点：

*   **设备**
*   **计算**
*   **存储（内存）**
*   **连接**

这四个节点里：

*   `设备` 是产业链节点，不是 GICS 原生 node；
*   `计算` 是应用/需求驱动节点；
*   `存储（内存）` 是技术/供给节点；
*   `连接` 是跨半导体与网络基础设施的桥接节点。

更重要的是，这四个节点**不是互斥的 ETF 产品类别**，而是**同一半导体产业链的可分析语义层**。

### 连接三级结构

`连接` 节点下再拆：

*   **光**
*   **铜**

这是这次升级最需要“图”而不是“树”的地方，因为 `光 / 铜` 严格说并不都属于 XLK 的单一 GICS 子行业，它们是**高速连接产业链叶子节点**。

更合理的做法是：

*   在 Hybrid 视图里，把它们显示成 `半导体 → 连接 → 光/铜`
*   但底层关系允许 `光/铜` 同时挂在 `连接` 与 `通信设备 / 电子元件` 之下
*   这就是“显示是树，底层是图”

5\. 节点定义的具体示例
-------------

下面是我建议的 XLK 半导体链条定义口径。

### 1) 半导体节点

语义：XLK 内最强、最标准化、最有 ETF 代表性的一级节点。  
表达方式：`SOXX` 为主，`SMH` 为辅。  
用途：一级排名、与 XLK / SPY / QQQ 做相对强弱比较。[BlackRock+1](https://www.ishares.com/us/products/239705/SOXX)

### 2) 软件节点

语义：XLK 内的软件主线。  
表达方式：`IGV` 为主 proxy。  
用途：与半导体、硬件做一级横比。  
注意：`SKYY / CLOU / HACK` 不再与它平级，而改成它的**证据节点**或专题确认器。[BlackRock](https://www.ishares.com/us/products/239771/ishares-north-american-techsoftware-etf)

### 3) 硬件节点

语义：面向产品和设备的科技硬件集合。  
表达方式：synthetic basket。  
构造原则：优先用 XLK 内属于 hardware / communications equipment / electronic equipment 的成分，按父 ETF 权重起步，再做单名上限约束。  
注意：这不是官方单一 GICS 桶，所以一定要给一个 **representation confidence** 标签。[State Street Global Advisors+1](https://www.ssga.com/us/en/intermediary/etfs/the-technology-select-sector-spdr-fund-xlk)

### 4) 设备节点

语义：半导体制造设备。  
表达方式：synthetic basket。  
示例：AMAT、LRCX、KLAC、ASML、TER。  
理由：Applied Materials 官方口径本身就是广义半导体制造设备能力；而 SMH 的持仓也天然把设备公司放在同一个半导体 ETF 篮子里。[Applied Materials+1](https://www.appliedmaterials.com/us/en/semiconductor/products.html)

### 5) 存储（内存）节点

语义：以内存为核心的半导体节点。  
表达方式：synthetic basket，建议做两个版本：

*   **Memory Core**：更纯，但广度窄
*   **Memory/Storage Extended**：更宽，但纯度下降

示例核心：MU。  
理由：Micron 官方产品线覆盖 DRAM、LPDDR、HBM、NAND、数据中心内存/存储，所以它是这个节点最自然的 core name。[Micron Technology+1](https://www.micron.com/products/memory)

### 6) 计算节点

语义：AI / HPC / accelerated compute 相关芯片。  
表达方式：synthetic basket。  
示例：NVDA、AMD，可按需要加入 AVGO/ARM 等。  
理由：NVIDIA 官方强调 accelerated computing；AMD 官方强调 end-to-end compute, acceleration, and networking solutions for the AI-ready data center。这个节点是半导体内部最容易形成趋势领涨的核心。[NVIDIA+2AMD+2](https://www.nvidia.com/en-us/data-center/solutions/accelerated-computing/)

### 7) 连接节点

语义：高速互连，不是纯 GICS 行业，而是 AI 基础设施链条节点。  
表达方式：synthetic basket，且允许 chain extension。  
建议拆两层：

*   **interconnect silicon**：更偏芯片，如 MRVL/部分 AVGO
*   **physical interconnect**：更偏模块/器件/线缆/连接器

理由：Marvell 官方已经直接把 AI 数据中心的瓶颈表述为从 compute 转向 connectivity，这正说明“连接”应该是产业链节点，而不是 ETF 目录节点。[Marvell Technology](https://www.marvell.com/company/newsroom/marvell-ai-data-center-connectivity-ofc-2026.html)

### 8) 光节点

语义：高速连接里的 optical leaf。  
表达方式：synthetic basket，带 chain extension。  
示例：CIEN、COHR、LITE 等。  
理由：Coherent 官方给的是 optical transceivers / optical communication products，Ciena 官方给的是 optical interconnects，这些都更接近“连接-光”而不是传统 GICS 子行业。[Coherent Inc+1](https://www.coherent.com/networking/transceivers)

### 9) 铜节点

语义：高速连接里的 copper leaf。  
表达方式：synthetic basket，带 chain extension。  
示例：APH、TEL 等。  
理由：Amphenol 官方强调 connectors / interconnect systems / high-speed cable，TE 官方强调 pluggable I/O copper high speed cable assemblies。这个节点非常适合作为“光 vs 铜”结构性切换的观测器。[Amphenol+1](https://www.amphenol.com/products)

6\. 分析策略应该怎么升级
--------------

我建议不要推倒重来，而是**保留现在 ETF 打分的主干**，把它升级成“节点打分”。

现有 `ETFScoreCalculator` 的主权重是：

*   `rel_mom 0.45`
*   `trend_quality 0.25`
*   `breadth 0.20`
*   `options_confirm 0.10`

这一套不需要废掉，反而应该保留为**节点行情核**。真正新增的是两个 overlay：

*   **representation confidence**：这个节点被 proxy / synthetic 表达得有多纯
*   **chain confirmation**：上下游是否共振

所以节点分数可以理解成：

**旧 ETF 核心分数 + 纯度/置信度修正 + 产业链确认修正**

这样做的好处是，现有图表、排序、历史分数逻辑大部分都能复用，只要你先把 node 的价格序列、广度序列、成分篮子准备好。

### 具体策略上，板块下钻要回答 4 个问题

1.  **一级节点谁最强？**  
    XLK 下先看：半导体 vs 软件 vs 硬件
2.  **最强节点内部是广还是窄？**  
    进入半导体后看：设备 / 计算 / 存储 / 连接，究竟是全面扩散，还是只是 NVDA/AMD 这类计算股单点拉动
3.  **上下游是否开始确认？**  
    如果计算强，但设备、连接、内存都不确认，那是“强但窄”；  
    如果设备和连接也开始抬头，就是“主线扩散”
4.  **应该继续往哪一层 drill？**  
    比如 `连接` 明显转强，就再 drill 到 `光 vs 铜`

### 用 XLK 举一个你要的完整策略例子

假设下钻结果是：

*   一级：**半导体 > 软件 > 硬件**
*   二级：**计算 > 设备 > 连接 > 存储**
*   三级（连接内）：**光 > 铜**

这套结果的策略含义就很明确：

*   XLK 的强势来自半导体，而不是软件全面接棒；
*   半导体内部仍由计算端领跑，说明 AI 主线没变；
*   设备和连接开始跟上，意味着从“算力芯片”向“资本开支 + 网络基础设施”扩散；
*   光强于铜，说明市场更偏向 scale-out、DCI、光模块、光互连这一段，而不是仅仅停留在机架内、背板、连接器和短距铜缆的升级；
*   如果这时存储（内存）仍明显落后，就说明行情还没走到“全链条同步景气”，更像是 AI 主线的中段扩散，而不是完整周期共振。

反过来，如果出现：

*   一级：半导体强
*   二级：计算极强，设备/连接一般，存储很弱
*   三级：铜强于光

那就更像是“短周期补基础布线 / 机架内连接”，而不是“全网光互连的大级别扩散”。

7\. 怎么落到你这版代码上，才是最低风险路径
-----------------------

我建议按下面顺序改，而不是一次把所有页面重做。

### 第一步：先加“节点层”，不要先删 ETF 层

在 `database.py` 旁边新增一套节点注册表即可，ETF 表保留。

最少需要四类对象：

*   `AnalyticNode`
*   `NodeEdge`
*   `NodeProxy`
*   `SyntheticBasketDefinition`

这样旧任务和旧 ETF 功能还能跑，新下钻功能开始走节点。

### 第二步：把 Task 从 `sector + etfs[]` 改成 `root_node + selected_nodes`

当前 `Task` 的 `sector` 与 `etfs[]` 不够表达层级。  
升级后建议任务保存：

*   `root_node`
*   `view_mode`（GICS / Chain / Hybrid）
*   `selected_nodes`
*   `benchmarks`
*   `max_depth`
*   `pinned_evidence_nodes`

旧任务可以自动迁移成：

*   `root_node = XLK`
*   `selected_nodes = 旧的 ETF 对应 node`

### 第三步：把现有的 ETF API 旁路成 Node API

现在 `/etfs/sectors`、`/etfs/industries` 不够了。  
应增加一组节点接口：

*   获取根节点
*   获取子节点
*   获取图关系
*   获取节点的 proxy / basket / constituents
*   获取节点排名与 drill 建议

ETF API 继续保留，但从“主入口”降级为“底层数据入口”。

### 第四步：前端把“创建任务”和“详情页”改成 node-first

重点改这几个地方：

*   `CreateTaskModal.tsx`：不要再硬编码 `INDUSTRY_ETFS`
*   `AddTaskETFsModal.tsx`：改成“添加 node / evidence node”
*   `CoreTerminal.tsx`：从按 `parentSector` 过滤，改成按 node tree / graph 渲染
*   `TaskDetail.tsx`：`trendSymbolRoleMap` 里增加 `root/node/proxy/synthetic/evidence`

### 第五步：把数据标签补齐

当前 `finviz_parser.py` 只有 `Sector / Industry`。  
要支持你的方案，至少要补：

*   `chain_role`：compute / memory / equipment / connectivity
*   `medium`：optical / copper
*   `representation_scope`：in\_parent / extension
*   `purity_confidence`
*   `overlap_group`

这部分不一定全靠自动解析，完全可以先做一份**可维护的人工 taxonomy 配置**，再逐步自动化。

### 第六步：把现有 holdings 去重逻辑升级成 node-scope 去重

你现在已经有一个不错的雏形：`related_etf_symbols` 会在刷新 holdings 时做同任务范围内的重叠跳过。  
这个能力很适合直接升成：

*   `related_node_scope`
*   `overlap-aware refresh`
*   `same constituent, multi-node dedupe`

这样在刷新 `计算`、`设备`、`连接` 时，不会反复刷新重复成分。

8\. 我对这次升级的最终建议
---------------

最关键的一点只有一句话：

**不要再把“板块内下钻”建成 ETF 列表，而要把它建成节点图谱；ETF 只是节点的 proxy，不是节点本身。**

对应到 XLK，正确的产品语义应该是：

*   **主节点**：`半导体 / 软件 / 硬件`
*   **半导体子节点**：`设备 / 计算 / 存储（内存） / 连接`
*   **连接叶子节点**：`光 / 铜`
*   **ETF proxy**：`SOXX / SMH / IGV`
*   **synthetic node basket**：`硬件 / 设备 / 计算 / 存储 / 连接 / 光 / 铜`
*   **evidence nodes**：`云 / 安全 / DCI / optical module` 等专题确认器

这样一来，你得到的不只是 XLK 的一个特例，而是一整套可复制到 XLE、XLF、XLV、工业链、AI 基建链的通用“板块下钻”框架。

---

**Sources:**

- [https://www.ssga.com/us/en/intermediary/etfs/the-technology-select-sector-spdr-fund-xlk](https://www.ssga.com/us/en/intermediary/etfs/the-technology-select-sector-spdr-fund-xlk)
- [https://www.ishares.com/us/products/239705/SOXX](https://www.ishares.com/us/products/239705/SOXX)
- [https://www.appliedmaterials.com/us/en/semiconductor/products.html](https://www.appliedmaterials.com/us/en/semiconductor/products.html)
- [https://www.micron.com/products/memory](https://www.micron.com/products/memory)
- [https://www.nvidia.com/en-us/data-center/solutions/accelerated-computing/](https://www.nvidia.com/en-us/data-center/solutions/accelerated-computing/)
- [https://www.marvell.com/company/newsroom/marvell-ai-data-center-connectivity-ofc-2026.html](https://www.marvell.com/company/newsroom/marvell-ai-data-center-connectivity-ofc-2026.html)
- [https://www.coherent.com/networking/transceivers](https://www.coherent.com/networking/transceivers)
- [https://www.amphenol.com/products](https://www.amphenol.com/products)



---
Powered by [ChatGPT Exporter](https://www.chatgptexporter.com)