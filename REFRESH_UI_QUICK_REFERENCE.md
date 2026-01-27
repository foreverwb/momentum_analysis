# 刷新机制 UI 快速参考

## 视觉效果

### 前后对比

**之前**:
- ❌ 白色不透明背景遮盖层 (rgba(255, 255, 255, 0.92))
- ❌ 卡片式进度显示（占用页面空间）
- ❌ 两个按钮的进度显示方式不一致

**现在**:
- ✅ 透明黑色背景遮盖层 (rgba(0, 0, 0, 0.3))
- ✅ 居中模态框（不阻挡背景）
- ✅ 两个按钮使用统一的进度显示

## 透明背景说明

### 背景层配置
```
rgba(0, 0, 0, 0.3)  - 透明度 30% 的黑色
blur(2px)          - 2像素模糊效果
```

### 效果
- 能看到背后的页面内容（透明）
- 使用黑色确保文本可读性
- 模糊效果提升现代感

## 按钮交互变化

### "Refresh ETFs" 按钮
```
默认状态：  "Refresh ETFs"
加载状态：  "🔄 Refreshing..." (按钮禁用，显示spinner)
完成状态：  隐藏模态框，按钮恢复
```

### "Refresh Holdings" 按钮
```
默认状态：  "Refresh Top10 Holdings"
加载状态：  "🔄 Refreshing..." (按钮禁用，显示spinner)
完成状态：  隐藏模态框，按钮恢复
```

## 进度显示内容

### 模态框显示的信息
- **标题**: "正在刷新 XLK 数据" 或 "正在刷新 XLK Top10 Holdings"
- **进度条**: 0% → 100%
- **计数**: "已完成 2/5"
- **当前项**: "XLK" 或 "Top10"
- **状态消息**: "准备刷新数据..." → "刷新完成！"

## 状态指示器

### 进度中 (蓝色)
- 旋转的加载图标
- 蓝色进度条

### 完成 (绿色)
- ✓ 完成图标
- 绿色进度条
- "刷新完成！" 消息

### 错误 (红色)
- ⚠️ 错误图标
- 红色进度条
- 错误消息

## 代码集成示例

### 在组件中使用
```tsx
import { RefreshProgressModal } from '../modal';

export function MyComponent() {
  const [showModal, setShowModal] = useState(false);
  const [progress, setProgress] = useState({
    completed: 0,
    total: 100,
    currentItem: '',
    message: '',
  });

  return (
    <>
      <button onClick={() => handleRefresh()}>
        Refresh Data
      </button>

      <RefreshProgressModal
        isOpen={showModal}
        title="正在刷新数据"
        currentItem={progress.currentItem}
        message={progress.message}
        completed={progress.completed}
        total={progress.total}
        isError={false}
        isComplete={false}
      />
    </>
  );
}
```

## 性能考虑

- 模态框只在需要时渲染
- 自动清理 DOM 和样式
- 支持 body overflow 管理防止滚动

## 浏览器支持

| 浏览器 | 支持 | 备注 |
|--------|------|------|
| Chrome 88+ | ✅ | 完全支持 |
| Firefox 89+ | ✅ | 完全支持 |
| Safari 15+ | ✅ | 完全支持 |
| Edge 88+ | ✅ | 完全支持 |

## 常见问题

**Q: 为什么使用透明背景而不是白色?**
A: 透明背景允许用户看到背后的内容，提供更好的上下文，同时保持现代的设计风格。

**Q: 模态框何时自动关闭?**
A: 完成或错误时，延迟 1.5-2 秒自动关闭，给用户查看结果的时间。

**Q: 如何取消刷新?**
A: 当前版本不支持取消。可以通过关闭浏览器标签页中断 WebSocket 连接。

**Q: 进度信息从哪里来?**
A: 从后端通过 WebSocket 发送，实时更新进度。

## 相关文件

- `frontend/src/components/modal/RefreshProgressModal.tsx` - 模态框组件
- `frontend/src/components/task/TaskDetail.tsx` - 任务详情页面
- `frontend/src/components/task/ETFDetailCard.tsx` - ETF 卡片组件
