import SwiftUI

struct CompanionCareView: View {
    @ObservedObject var care: CompanionCare
    var expanded: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if care.timer.state != .idle || expanded {
                HStack {
                    Text(care.timer.phase.label).font(.caption)
                    Text(care.countdown).monospacedDigit()
                    if care.timer.state == .paused { Text("已暂停").font(.caption2) }
                    if care.timer.state == .completed { Text("已完成").font(.caption2) }
                    Spacer()
                    timerControls
                }
            }
            if !care.notice.isEmpty { Text(care.notice).font(.caption2).foregroundStyle(.secondary) }
            if expanded {
                Text("情绪：\(care.mood.label) · \(care.mood.tier) · 好感度 \(care.mood.affection)/100").font(.caption)
                Text("今日增加 \(care.earnedToday)/20；两位角色分别保存。已完成 \(care.timer.completedFocus) 轮专注。")
                    .font(.caption2).foregroundStyle(.secondary)
                Toggle("情绪自动表情", isOn: Binding(get: { care.mood.autoExpression }, set: { care.setAutoExpression($0) }))
                DisclosureGroup("番茄钟设置") {
                    Stepper("专注 \(care.timer.focusMinutes) 分钟", value: Binding(get: { care.timer.focusMinutes }, set: { care.configure(focus: $0) }), in: 1...180)
                    Stepper("短休息 \(care.timer.shortMinutes) 分钟", value: Binding(get: { care.timer.shortMinutes }, set: { care.configure(short: $0) }), in: 1...180)
                    Stepper("长休息 \(care.timer.longMinutes) 分钟", value: Binding(get: { care.timer.longMinutes }, set: { care.configure(long: $0) }), in: 1...180)
                    Stepper("每 \(care.timer.longEvery) 轮长休息", value: Binding(get: { care.timer.longEvery }, set: { care.configure(every: $0) }), in: 1...12)
                    Toggle("完成提示音", isOn: Binding(get: { care.timer.sound }, set: { care.configure(sound: $0) }))
                    Text("到时后手动开始下一阶段。修改时长从下一阶段生效；退出后仍按截止时间恢复。语音对话期间仅显示完成提示。")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                if !care.storageError.isEmpty { Text(care.storageError).font(.caption2).foregroundStyle(.orange) }
            }
        }.frame(width: expanded ? 400 : nil)
    }

    @ViewBuilder private var timerControls: some View {
        switch care.timer.state {
        case .idle: Button("开始专注") { care.start() }
        case .running: Button("暂停") { care.pause() }
        case .paused: Button("继续") { care.resume() }
        case .completed: Button("开始\(care.timer.nextPhase.label)") { care.start() }
        }
        if care.timer.state != .idle { Button("重置") { care.reset() } }
    }
}
