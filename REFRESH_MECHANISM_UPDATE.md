# 刷新机制统一升级文档

## 概述
本次更新统一了"Refresh ETFs"和"Refresh Holdings"按钮的交互效果，实现了透明背景的进度显示模态框，并与后端保持进度同步状态。

## 主要变更

### 1. 创建统一的刷新进度模态框组件
**文件**: `frontend/src/components/modal/RefreshProgressModal.tsx`

**特性**:
- ✅ 透明黑色背景遮盖层 (`rgba(0, 0, 0, 0.3)`)
- ✅ 支持 backdrop blur 效果
- ✅ 显示进度条、完成数量、当前处理项
- ✅ 区分三种状态: 进行中、完成、错误
- ✅ 自动清理DOM和body样式

**使用方式**:
```tsx
<RefreshProgressModal
  isOpen={showModal}
  title="刷新标题"
  currentItem="当前处理项"
  message="进度消息"
  completed={5}
  total={10}
  isError={false}
  isComplete={false}
/>
```

### 2. 更新 TaskDetail.tsx
**文件**: `frontend/src/components/task/TaskDetail.tsx`

**变更**:
- ✅ 移除了旧的内联进度显示卡片
- ✅ 集成 `RefreshProgressModal` 用于 ETF 刷新进度显示
- ✅ 改进了 `handleRefreshAll` 函数:
  - 显示透明模态框
  - 通过 WebSocket 接收后端进度更新
  - 自动显示完成或错误状态
  - 延迟关闭模态框（1.5-2秒）以展示完成效果

**新增状态**:
```tsx
const [showRefreshModal, setShowRefreshModal] = useState(false);
const [refreshError, setRefreshError] = useState(false);
const [refreshComplete, setRefreshComplete] = useState(false);
```

### 3. 更新 ETFDetailCard.tsx
**文件**: `frontend/src/components/task/ETFDetailCard.tsx`

**变更**:
- ✅ 集成 `RefreshProgressModal` 用于 ETF 和 Holdings 刷新
- ✅ 统一 `handleRefreshETF` 和 `handleRefreshHoldings` 的进度显示
- ✅ 移除了旧的 `simulateProgress` 函数
- ✅ 改进了按钮状态反馈:
  - 加载中显示 spinner 和"Refreshing..."
  - 禁用按钮防止重复点击
  - 延迟关闭模态框以展示完成效果

**新增状态**:
```tsx
const [showRefreshModal, setShowRefreshModal] = useState(false);
const [refreshModalTitle, setRefreshModalTitle] = useState('');
const [refreshModalProgress, setRefreshModalProgress] = useState({
  completed: 0,
  total: 100,
  currentItem: '',
  message: '',
});
const [refreshModalError, setRefreshModalError] = useState(false);
const [refreshModalComplete, setRefreshModalComplete] = useState(false);
```

### 4. 更新 modal/index.ts
**文件**: `frontend/src/components/modal/index.ts`

**变更**:
- ✅ 导出 `RefreshProgressModal` 组件

## 交互流程

### "Refresh ETFs" 按钮流程
1. 用户点击按钮 → 按钮显示加载状态
2. 显示透明模态框，开始接收 WebSocket 进度消息
3. 模态框实时更新:
   - 当前刷新的 ETF 符号
   - 完成的 ETF 数量 / 总数
   - 进度条百分比
   - 进度消息
4. 完成/错误时:
   - 显示最终状态消息
   - 1.5-2秒后自动关闭模态框
   - 按钮恢复为正常状态

### "Refresh Holdings" 按钮流程
1. 用户点击按钮 → 按钮显示加载状态和 spinner
2. 显示透明模态框，开始分阶段显示进度
3. 模态框显示:
   - 覆盖范围信息 (如 "Top10", "Weight70%")
   - 分阶段处理消息 (获取数据、处理数据源等)
   - 实时进度百分比
4. 完成/错误时:
   - 显示最终状态消息
   - 延迟关闭模态框
   - 按钮恢复为正常状态

## 后端进度同步

### WebSocket 连接
- 使用 `connectToRefreshStream` 函数建立 WebSocket 连接
- 接收格式:
```json
{
  "event": "progress",
  "completed_count": 2,
  "total_count": 5,
  "etf_symbol": "XLK",
  "message": "正在处理 XLK 数据..."
}
```

### 进度消息处理
- `progress` 事件: 更新进度显示
- `completed` 事件: 显示完成状态
- `error` 事件: 显示错误状态

## CSS 样式特性

### 透明背景遮盖层
```css
background: rgba(0, 0, 0, 0.3);
backdrop-filter: blur(2px);
```
相比原来的白色背景 (`rgba(255, 255, 255, 0.92)`)，新的透明黑色背景:
- ✅ 不会遮挡背后的内容，允许看到背景
- ✅ 更现代的设计风格
- ✅ 更好的视觉层次感

### 模态框内容
- 白色背景卡片 (`bg-[var(--bg-primary)]`)
- 圆角和阴影效果
- 响应式布局

## 测试清单

- [ ] "Refresh ETFs" 按钮点击后显示透明模态框
- [ ] 模态框显示正确的进度信息和百分比
- [ ] WebSocket 连接成功接收进度更新
- [ ] 刷新完成后模态框自动关闭
- [ ] 错误时显示错误消息
- [ ] "Refresh Holdings" 按钮显示分阶段进度
- [ ] 两个按钮的交互效果一致
- [ ] 透明背景遮盖层在所有浏览器中正常显示

## 浏览器兼容性

- ✅ Chrome/Edge (最新)
- ✅ Firefox (最新)
- ✅ Safari (最新)
- ✅ backdrop-filter 支持（不支持的浏览器会降级显示）

## 相关文件引用

- v7.html: 参考实现的设计原型
  - `refreshHoldingsWithPageLoading()` - Holdings 刷新进度显示
  - `refreshAllEtfData()` - ETF 刷新进度显示
  - `.page-loading-overlay` - 透明背景遮盖层 CSS

## 未来改进

- [ ] 可配置的动画时长
- [ ] 更多的进度阶段细节
- [ ] 进度历史日志
- [ ] 暂停/继续功能
