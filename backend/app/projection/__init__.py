"""投影层包（R4-M8 物理迁移）。

## 为什么有这个包

D-93/D-100/D-101 把四个域各收敛成"一份真实实现 + 一份薄委托"，但**权威实现本身**
仍散在原生位置（graph/scene 在 `modules/*/legacy.py`，evaluation/qa 在
`schemas/adapters.py`），并由两层门禁（双读一致性、薄委托）防漂移。
`CONTRACT.md` 里也一直登记着这条欠账：**"逻辑上唯一，物理上不在同一个包里"**。

本包就是那个"同一个包"。迁移是**纯机械**的：函数体原样搬入，原位置改薄委托，
行为一字不变（由双读一致性测试兜底 —— 它是防"搬丢字段"的网）。

## 纪律（迁移与新增都必须遵守）

1. **投影只有一个家**：`def to_legacy_*` 只允许出现在本包内
   （`test_projection_dual_read.py::ALLOWED_PROJECTION_FILES`）；
2. **原位置只许薄委托**：≤45 行且必须有转发调用
   （`test_projection_thin_delegation.py`）；
3. **props 整体透传**，不在投影层做白名单筛选 —— 白名单漏字段时 API 表面看不出异常，
   功能却整块失效（ADR-0058 / D-48 的真实前科）。
"""
