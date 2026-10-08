import Foundation

@main
struct CompanionBehaviorChecks {
    static func main() throws {
        var behavior = CompanionBehavior()
        behavior.interact(at: 100)
        precondition(!behavior.shouldRest(at: 699, enabled: true, visible: true, ready: true, busy: false, idle: true, standing: true))
        precondition(behavior.shouldRest(at: 700, enabled: true, visible: true, ready: true, busy: false, idle: true, standing: true))
        precondition(!behavior.shouldRest(at: 701, enabled: true, visible: true, ready: true, busy: false, idle: true, standing: true))
        precondition(behavior.touch("head", at: 702))
        precondition(!behavior.restRequested)
        precondition(!behavior.touch("body", at: 703))
        precondition(behavior.touch("body", at: 704))
        precondition(!behavior.shouldRest(at: 1400, enabled: true, visible: false, ready: true, busy: false, idle: true, standing: true))
        precondition(!behavior.shouldRest(at: 1999, enabled: true, visible: true, ready: true, busy: false, idle: true, standing: true))
        precondition(!behavior.shouldRest(at: 2100, enabled: true, visible: true, ready: true, busy: true, idle: true, standing: true))
        precondition(!behavior.shouldRest(at: 2699, enabled: true, visible: true, ready: true, busy: false, idle: true, standing: true))
        behavior.look("look_right", at: 2700)
        behavior.tickLook(at: 2701, enabled: false, idle: true)
        precondition(behavior.gaze["look_right"] == 0.45)
        behavior.tickLook(at: 2703, enabled: false, idle: true)
        precondition(behavior.gaze.isEmpty)

        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        var history = ConversationHistory(directory: directory)
        try history.select(character: "hsin", provider: "default")
        try history.user("测试", turn: "one")
        try history.user("测试", turn: "one")
        try history.reply("部分", turn: "one", complete: false)
        try history.interrupt()
        precondition(history.messages.count == 2)
        precondition(history.messages.last?.state == .interrupted)
        try history.select(character: "aemeath", provider: "default")
        precondition(history.messages.isEmpty)
        try history.user("你好", turn: "two")
        try history.reply("改写前", turn: "two", complete: false)
        try history.reply("最终回复", turn: "two", complete: true)
        precondition(history.messages.last?.text == "最终回复")
        try history.select(character: "hsin", provider: "default")
        precondition(history.messages.count == 2 && history.messages.last?.text == "部分")
        try history.select(character: "hsin", provider: "deepseek")
        precondition(history.messages.isEmpty)
        try history.select(character: "aemeath", provider: "default")
        precondition(history.messages.last?.state == .complete)
        let blockedDirectory = directory.appendingPathComponent("blocked")
        try Data().write(to: blockedDirectory)
        var blocked = ConversationHistory(directory: blockedDirectory)
        try blocked.select(character: "hsin", provider: "default")
        do { try blocked.user("私有旧记录", turn: "old"); preconditionFailure("Expected I/O failure") } catch {}
        try blocked.reply("未存回复", turn: "old", complete: false)
        do { try blocked.select(character: "aemeath", provider: "default"); preconditionFailure("Expected I/O failure") } catch {}
        precondition(blocked.context == "aemeath-default" && blocked.messages.isEmpty)
        print("History isolation, persistence, cancellation, rest gating and touch cooldown passed")
    }
}
