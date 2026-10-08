import Foundation
import Combine

struct FocusTimer: Codable, Equatable {
    enum Phase: String, Codable, CaseIterable {
        case focus, shortBreak, longBreak
        var label: String { switch self { case .focus: "专注"; case .shortBreak: "短休息"; case .longBreak: "长休息" } }
    }
    enum State: String, Codable { case idle, running, paused, completed }
    var focusMinutes = 25
    var shortMinutes = 5
    var longMinutes = 15
    var longEvery = 4
    var sound = true
    var phase: Phase = .focus
    var nextPhase: Phase = .focus
    var state: State = .idle
    var completedFocus = 0
    var remaining: Double = 1500
    var deadline: Date?
    var owner = "hsin"

    func duration(_ phase: Phase) -> Double {
        Double(phase == .focus ? focusMinutes : phase == .shortBreak ? shortMinutes : longMinutes) * 60
    }
    func seconds(at now: Date) -> Int { Int(ceil(max(0, deadline?.timeIntervalSince(now) ?? remaining))) }
    var valid: Bool {
        [focusMinutes, shortMinutes, longMinutes].allSatisfy { (1...180).contains($0) } && (1...12).contains(longEvery)
        && completedFocus >= 0 && completedFocus < 1000000 && remaining.isFinite && (0...10800).contains(remaining)
        && (deadline.map { $0.timeIntervalSince1970.isFinite && (0...4102444800).contains($0.timeIntervalSince1970) } ?? true) && ((state == .running) == (deadline != nil))
        && ["hsin", "aemeath"].contains(owner)
    }
    mutating func start(at now: Date, character: String) {
        guard state == .idle || state == .completed else { return }
        phase = nextPhase; remaining = duration(phase); deadline = now.addingTimeInterval(remaining)
        state = .running; owner = character
    }
    mutating func pause(at now: Date) {
        guard state == .running else { return }
        remaining = max(0, deadline?.timeIntervalSince(now) ?? 0); deadline = nil; state = .paused
    }
    mutating func resume(at now: Date) {
        guard state == .paused else { return }
        deadline = now.addingTimeInterval(remaining); state = .running
    }
    mutating func reset() {
        state = .idle; phase = .focus; nextPhase = .focus; deadline = nil; remaining = duration(.focus)
    }
    mutating func tick(at now: Date) -> Bool {
        guard state == .running, let deadline, now >= deadline else { return false }
        self.deadline = nil; remaining = 0; state = .completed
        if phase == .focus {
            completedFocus += 1
            nextPhase = completedFocus % longEvery == 0 ? .longBreak : .shortBreak
        } else { nextPhase = .focus }
        return true
    }
}

struct CompanionMood: Codable, Equatable {
    var version = 1
    var affection = 30
    var autoExpression = true
    var rewardDay = ""
    var earnedToday = 0
    var lastRewards: [String: Double] = [:]
    var mood = "calm"
    var moodUntil = 0.0
    var lastInteraction = 0.0
    var tier: String { affection >= 80 ? "心意相通" : affection >= 60 ? "信赖" : affection >= 30 ? "相伴" : "相识" }
    var label: String { ["calm":"从容", "happy":"开心", "content":"欢欣", "relaxed":"安心", "shy":"害羞", "fond":"亲近", "lonely":"想念", "tired":"困倦"][mood] ?? "从容" }
    var expression: String { ["calm":"normal", "happy":"happy", "content":"content", "relaxed":"relaxed", "shy":"blush", "fond":"heart_eyes", "lonely":"sad", "tired":"sleepy"][mood] ?? "normal" }
    var valid: Bool {
        version == 1 && (0...100).contains(affection) && (0...20).contains(earnedToday)
        && lastRewards.keys.allSatisfy { ["touch", "chat", "focus"].contains($0) }
        && lastRewards.values.allSatisfy { $0.isFinite && (0...4102444800).contains($0) }
        && ["calm", "happy", "content", "relaxed", "shy", "fond", "lonely", "tired"].contains(mood)
        && moodUntil.isFinite && lastInteraction.isFinite
        && (rewardDay.isEmpty || Self.dayFormatter.date(from: rewardDay) != nil)
    }
    private static var dayFormatter: DateFormatter {
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian); formatter.dateFormat = "yyyy-MM-dd"; formatter.isLenient = false
        return formatter
    }
    func todayEarned(at now: Date) -> Int { Self.dayFormatter.string(from: now) > rewardDay ? 0 : earnedToday }
    mutating func interact(_ event: String, part: String = "", at now: Date, uptime: Double) {
        guard let reward = ["touch": (1, 15.0), "chat": (2, 60.0), "focus": (3, 60.0)][event] else { return }
        let day = Self.dayFormatter.string(from: now)
        if day > rewardDay { rewardDay = day; earnedToday = 0 }
        let wall = now.timeIntervalSince1970
        if wall - (lastRewards[event] ?? -reward.1) >= reward.1 {
            let gain = max(0, min(reward.0, 20 - earnedToday, 100 - affection))
            if gain > 0 { affection += gain; earnedToday += gain; lastRewards[event] = wall }
        }
        lastInteraction = uptime
        if event == "touch" {
            mood = part == "chest" || (affection >= 60 && part == "head") ? "shy" : affection >= 80 && part.contains("hand") ? "fond" : "relaxed"
        } else { mood = event == "chat" ? (affection >= 60 ? "content" : affection >= 30 ? "happy" : "relaxed") : "relaxed" }
        moodUntil = uptime + 45
    }
    mutating func tick(uptime: Double, engaged: Bool) {
        if engaged { lastInteraction = uptime }
        guard uptime >= moodUntil else { return }
        let idle = max(0, uptime - lastInteraction)
        mood = idle >= 3600 ? "tired" : idle >= 1800 ? "lonely" : "calm"
        // Affection never decays while offline or idle.
    }
}

@MainActor
final class CompanionCare: ObservableObject {
    @Published private(set) var timer = FocusTimer()
    @Published private(set) var mood = CompanionMood()
    @Published private(set) var storageError = ""
    @Published private(set) var clock = Date()
    @Published var notice = ""
    var onNotice: ((String, Bool) -> Void)?
    private let directory: URL
    private var character = "hsin"
    private var invalidFiles: Set<URL> = []
    private var lastTick = -1.0
    private var lastRewardedTurn: String?

    init(directory: URL = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("CompanionCare")) {
        self.directory = directory
        timer = load("timer", fallback: FocusTimer(), valid: { $0.valid })
    }
    func select(_ role: String, uptime: Double) {
        guard ["hsin", "aemeath"].contains(role) else { return }
        character = role; lastRewardedTurn = nil
        mood = load("mood-" + role, fallback: CompanionMood(), valid: { $0.valid })
        mood.mood = "calm"; mood.moodUntil = 0; mood.lastInteraction = uptime
    }
    private func load<State: Codable>(_ name: String, fallback: State, valid: (State) -> Bool) -> State {
        let url = directory.appendingPathComponent(name + ".json")
        guard FileManager.default.fileExists(atPath: url.path) else { return fallback }
        do {
            let restored = try JSONDecoder().decode(State.self, from: Data(contentsOf: url))
            guard valid(restored) else { throw CocoaError(.coderReadCorrupt) }
            return restored
        } catch { invalidFiles.insert(url); storageError = "陪伴状态读取失败，保存前会备份原文件"; return fallback }
    }
    @discardableResult private func save<State: Codable>(_ value: State, name: String) -> Bool {
        let url = directory.appendingPathComponent(name + ".json")
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            if invalidFiles.contains(url) {
                try FileManager.default.copyItem(at: url, to: directory.appendingPathComponent(name + "-invalid-" + UUID().uuidString + ".json"))
                invalidFiles.remove(url)
            }
            try JSONEncoder().encode(value).write(to: url, options: .atomic)
            #if os(visionOS)
            try FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: url.path)
            #endif
            storageError = ""; return true
        } catch { storageError = "陪伴状态保存失败；原记录保留"; return false }
    }
    var earnedToday: Int { mood.todayEarned(at: clock) }
    var countdown: String { let seconds = timer.seconds(at: clock); return String(format: "%02d:%02d", seconds / 60, seconds % 60) }
    func configure(focus: Int? = nil, short: Int? = nil, long: Int? = nil, every: Int? = nil, sound: Bool? = nil) {
        var proposed = timer
        if let focus { proposed.focusMinutes = focus }; if let short { proposed.shortMinutes = short }
        if let long { proposed.longMinutes = long }; if let every { proposed.longEvery = every }; if let sound { proposed.sound = sound }
        if proposed.state == .idle { proposed.remaining = proposed.duration(proposed.phase) }
        guard proposed.valid, save(proposed, name: "timer") else { return }; timer = proposed
    }
    func start() { updateTimer { $0.start(at: Date(), character: character) } }
    func pause() { tick(uptime: ProcessInfo.processInfo.systemUptime, engaged: false); updateTimer { $0.pause(at: Date()) } }
    func resume() { updateTimer { $0.resume(at: Date()) } }
    func reset() { updateTimer { $0.reset() }; notice = "" }
    private func updateTimer(_ change: (inout FocusTimer) -> Void) {
        var proposed = timer; change(&proposed)
        if proposed.valid, save(proposed, name: "timer") { timer = proposed; clock = Date() }
    }
    func setAutoExpression(_ enabled: Bool) {
        var proposed = mood; proposed.autoExpression = enabled
        if save(proposed, name: "mood-" + character) { mood = proposed }
    }
    func interact(_ event: String, part: String = "", turn: String? = nil, uptime: Double) {
        if event == "chat", let turn { guard turn != lastRewardedTurn else { return }; lastRewardedTurn = turn }
        var proposed = mood
        proposed.interact(event, part: part, at: Date(), uptime: uptime)
        if proposed.valid, save(proposed, name: "mood-" + character) { mood = proposed }
    }
    func tick(uptime: Double, engaged: Bool) {
        guard uptime - lastTick >= 1 || lastTick < 0 else { return }; lastTick = uptime; clock = Date()
        var proposed = timer
        if proposed.tick(at: clock), proposed.valid, save(proposed, name: "timer") {
            timer = proposed
            if timer.phase == .focus {
                if timer.owner == character { interact("focus", uptime: uptime) }
                else {
                    var ownerMood = load("mood-" + timer.owner, fallback: CompanionMood(), valid: { $0.valid })
                    ownerMood.interact("focus", at: clock, uptime: uptime); save(ownerMood, name: "mood-" + timer.owner)
                }
            }
            notice = timer.phase == .focus ? "专注完成，准备\(timer.nextPhase.label) \(Int(timer.duration(timer.nextPhase) / 60)) 分钟" : "休息结束，可以开始下一轮专注"
            onNotice?(notice, timer.sound)
        }
        var updated = mood; updated.tick(uptime: uptime, engaged: engaged || (timer.state == .running && timer.phase == .focus))
        if updated != mood { mood = updated }
    }
}
