# 心的番茄钟

右键心或托盘图标，选择 **番茄钟…**。默认专注 25 分钟、短休息 5 分钟，每完成四轮专注后安排 15 分钟长休息。面板可以调整时长、长休息间隔和提示音，点“保存设置”后下一轮生效；当前计时保持原截止时间。

点“开始专注”，头顶显示倒计时；支持暂停、继续和重置本轮。到时显示气泡和托盘提醒，可选系统提示音，下一阶段需要手动开始。重置取消本轮，不计为完成，也不清除本次启动已完成的轮次。到时提醒不发起聊天、不合成语音、不打断正在朗读的回复。

关闭面板或隐藏角色后计时继续；角色隐藏时不显示气泡和头顶徽标，仍尝试托盘提醒及可选提示音。Windows 通知设置、勿扰模式及系统声音设置可能影响提示。重新打开面板可以看到完成状态。穿透模式下可从托盘打开独立面板；徽标本身不接收鼠标、不抢焦点，会跟随移动、缩放和双形态的头部投影。气泡与徽标重叠时气泡优先，气泡消失后徽标恢复。

计时根据单调时钟的截止时间计算，不靠回调次数减秒。界面卡顿或电脑恢复时，下一次刷新只完成当前阶段一次，不自动累计后续专注或休息。退出程序结束本次计时，重启不会自动开始；时长设置保存在独立的 `.runtime/pomodoro.json`，轮次仅统计本次启动。

## 本地接口

HTTP `POST /api/pomodoro` 使用下方 data 对象作为请求体；WebSocket 使用标准 type/data：

```json
{"type":"pomodoro","data":{"action":"configure","focus_minutes":25,"short_break_minutes":5,"long_break_minutes":15,"long_break_every":4,"sound":true}}
{"type":"pomodoro","data":{"action":"start"}}
{"type":"pomodoro","data":{"action":"pause"}}
{"type":"pomodoro","data":{"action":"resume"}}
{"type":"pomodoro","data":{"action":"status"}}
{"type":"pomodoro","data":{"action":"reset"}}
```

`start` 可显式传入 `phase: focus/short_break/long_break`；进行中或暂停时不能覆盖已有计时，需先重置。`open` 打开面板。各时长接受 1–180 的整数分钟，长休息间隔接受 1–12 的整数轮次，sound 为布尔值。设置先完整验证并原子写入，失败不修改内存设置。

响应为 `pomodoro_status`，包含 state（idle/running/paused/completed）、phase、label、remaining_seconds、completed_focus、next_phase、settings。`get_status.data.pomodoro` 同样提供快照；应用向 WebSocket 客户端广播变化的 `pomodoro_status`。其他生活助手功能按用户要求暂缓。

## 验证

Python 测试覆盖暂停小数余量、迟到回调只提醒一次、四轮后的长休息、取消不累计、设置保存失败、重启不自动计时，以及面板/隐藏/穿透和真实本地 HTTP/WS 控制。`python -m tools.verify_pomodoro` 在原生 Qt/WebGL 中检查双形态徽标、面板、暂停/隐藏与结束提醒，使用模拟时间，不联网、不开麦。

参考交互来自 Aemeath `src/ui/assistant_panel.py` 的番茄钟部分和 `src/ui/pomodoro_overlay.py`；独立计时服务、长休息轮换及 PMX 头部投影在本项目实现。
