import Foundation
import simd

@main
struct CompanionCareChecks {
    @MainActor static func main() throws {
        let now = Date(timeIntervalSince1970: 1800000000)
        var timer = FocusTimer()
        timer.focusMinutes = 1; timer.longEvery = 2
        timer.start(at: now, character: "aemeath")
        timer.pause(at: now.addingTimeInterval(20))
        precondition(timer.state == .paused && timer.remaining == 40)
        timer.resume(at: now.addingTimeInterval(100))
        precondition(!timer.tick(at: now.addingTimeInterval(139)))
        precondition(timer.tick(at: now.addingTimeInterval(140)))
        precondition(!timer.tick(at: now.addingTimeInterval(150)))
        precondition(timer.completedFocus == 1 && timer.nextPhase == .shortBreak && timer.owner == "aemeath")
        timer.start(at: now, character: "hsin")
        precondition(timer.phase == .shortBreak)
        _ = timer.tick(at: now.addingTimeInterval(301))
        precondition(timer.nextPhase == .focus)
        timer.start(at: now, character: "hsin")
        _ = timer.tick(at: now.addingTimeInterval(61))
        precondition(timer.nextPhase == .longBreak && timer.completedFocus == 2)
        timer.reset(); precondition(timer.state == .idle && timer.remaining == 60 && timer.completedFocus == 2)
        timer.deadline = Date(timeIntervalSince1970: 1e100); timer.state = .running
        precondition(!timer.valid)

        var mood = CompanionMood()
        mood.interact("touch", at: now, uptime: 10)
        mood.interact("touch", at: now.addingTimeInterval(1), uptime: 11)
        precondition(mood.affection == 31)
        for index in 1...30 { mood.interact("touch", at: now.addingTimeInterval(Double(index * 16)), uptime: Double(index)) }
        precondition(mood.earnedToday == 20 && mood.affection == 50)
        precondition(mood.todayEarned(at: now.addingTimeInterval(86400)) == 0)
        mood.interact("chat", at: now.addingTimeInterval(86400), uptime: 500)
        precondition(mood.earnedToday == 2 && mood.affection == 52)
        mood.tick(uptime: 5000, engaged: false)
        precondition(mood.mood == "tired" && mood.affection == 52)
        let restored = try JSONDecoder().decode(CompanionMood.self, from: JSONEncoder().encode(mood))
        precondition(restored.valid && restored == mood)

        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("hsin-care-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let care = CompanionCare(directory: directory)
        care.select("hsin", uptime: 100)
        care.interact("chat", turn: "first", uptime: 100)
        care.interact("chat", turn: "first", uptime: 101)
        precondition(care.mood.affection == 32)
        care.select("aemeath", uptime: 102); precondition(care.mood.affection == 30)
        care.interact("touch", uptime: 103)
        care.select("hsin", uptime: 104); precondition(care.mood.affection == 32 && care.mood.mood == "calm")
        care.configure(focus: 1); care.start(); care.configure(focus: 2)
        precondition(care.timer.remaining == 60 && care.timer.focusMinutes == 2)
        let restarted = CompanionCare(directory: directory)
        precondition(restarted.timer == care.timer)
        var expired = care.timer; expired.deadline = Date().addingTimeInterval(-1); expired.owner = "aemeath"
        try JSONEncoder().encode(expired).write(to: directory.appendingPathComponent("timer.json"))
        let completed = CompanionCare(directory: directory); completed.select("hsin", uptime: 105)
        completed.tick(uptime: 106, engaged: false)
        precondition(completed.timer.state == .completed && completed.mood.affection == 32)
        completed.select("aemeath", uptime: 107)
        precondition(completed.mood.affection == 34)
        completed.tick(uptime: 108, engaged: false)
        precondition(completed.timer.completedFocus == 1 && completed.mood.affection == 34)
        try Data("invalid".utf8).write(to: directory.appendingPathComponent("mood-hsin.json"))
        let corrupt = CompanionCare(directory: directory); corrupt.select("hsin", uptime: 110)
        precondition(!corrupt.storageError.isEmpty)
        corrupt.setAutoExpression(false)
        precondition(!corrupt.mood.autoExpression && corrupt.storageError.isEmpty)
        let savedFiles = try FileManager.default.contentsOfDirectory(atPath: directory.path)
        precondition(savedFiles.contains { $0.hasPrefix("mood-hsin-invalid-") })
        let blocked = directory.appendingPathComponent("blocked"); try Data().write(to: blocked)
        let unavailable = CompanionCare(directory: blocked); unavailable.select("hsin", uptime: 111)
        unavailable.interact("chat", turn: "blocked", uptime: 112)
        precondition(unavailable.mood.affection == 30 && !unavailable.storageError.isEmpty)

        var presentation = CharacterPresentation()
        let standing = presentation.pose(head: SIMD3<Float>(0, 1.6, 0))
        let lying = presentation.pose(head: SIMD3<Float>(0.5, 0.3, 0))
        precondition(standing.scale == lying.scale && standing.position == lying.position)
        presentation.mode = "head_left"
        let close = presentation.pose(head: SIMD3<Float>(0, 1.6, 0))
        precondition(close.scale > standing.scale && close.position.x.isFinite && close.yaw > 0)
        print("Care phase rotation, pause/restart, role isolation, daily/cooldown limits, owner reward, corrupt backup, write failure and fixed presentation passed")
    }
}
