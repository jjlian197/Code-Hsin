import Foundation

/// Monotonic inactivity policy; merely waiting for microphone input is not activity.
struct CompanionBehavior {
    private(set) var lastInteraction: Double = 0
    private(set) var restRequested = false
    private(set) var nextLook: Double = 18
    private(set) var lookUntil: Double = 0
    private(set) var gaze: [String: Float] = [:]
    private(set) var touchUntil: Double = 0
    private(set) var touchPart = ""

    mutating func interact(at now: Double) {
        lastInteraction = now
        restRequested = false
        nextLook = now + Double.random(in: 18...45)
    }
    mutating func shouldRest(at now: Double, enabled: Bool, visible: Bool, ready: Bool,
                             busy: Bool, idle: Bool, standing: Bool) -> Bool {
        guard enabled, visible, ready, !busy else { interact(at: now); return false }
        guard idle, standing, !restRequested, now - lastInteraction >= 600 else { return false }
        restRequested = true
        return true
    }
    mutating func look(_ direction: String, at now: Double) {
        gaze = direction == "center" ? [:] : [direction: 0.45]
        lookUntil = now + 3
    }
    mutating func tickLook(at now: Double, enabled: Bool, idle: Bool) {
        if now >= lookUntil { gaze = [:] }
        if enabled, idle, now >= nextLook {
            look(["look_left", "look_right", "look_up"].randomElement()!, at: now)
            nextLook = now + Double.random(in: 18...45)
        }
    }
    mutating func touch(_ part: String, at now: Double) -> Bool {
        guard now >= touchUntil else { return false }
        touchPart = part
        touchUntil = now + 2
        interact(at: now)
        return true
    }
}

struct SpatialBehaviorResources: Decodable {
    struct TouchRegion: Decodable { let name: String; let radius: Float }
    let expressions: [String: [String: Float]]
    let touchRegions: [TouchRegion]
    let touchFrames: [String: [[[Float]]]]
}
