import Foundation

@main
struct PostureChecks {
    static func main() {
        var posture = PostureState()
        precondition(posture.request(lying: true) == "lie_down")
        precondition(posture.request(lying: true) == nil)
        precondition(posture.completed("get_up") == nil)
        precondition(posture.completed("lie_down") == "side_lying")
        precondition(posture.request(lying: true) == nil)
        precondition(posture.request(lying: false) == "get_up")
        precondition(posture.completed("get_up") == "idle")
        precondition(posture.phase == .standing)

        // Reverse requests wait for the current support segment, never reverse the clip.
        precondition(posture.request(lying: true) == "lie_down")
        precondition(posture.request(lying: false) == nil)
        precondition(posture.phase == .lyingDown)
        precondition(posture.completed("lie_down") == "get_up")
        precondition(posture.request(lying: true) == nil)
        precondition(posture.phase == .gettingUp)
        precondition(posture.completed("get_up") == "lie_down")
        precondition(posture.request(lying: false) == nil)
        precondition(posture.request(lying: true) == nil)
        precondition(posture.completed("lie_down") == "side_lying")
        precondition(posture.completed("lie_down") == nil)
        precondition(posture.request(lying: false) == "get_up")
        precondition(posture.completed("get_up") == "idle")
        for _ in 0..<50 {
            precondition(posture.request(lying: true) == "lie_down")
            precondition(posture.completed("lie_down") == "side_lying")
            precondition(posture.request(lying: false) == "get_up")
            precondition(posture.completed("get_up") == "idle")
        }
        print("PASS: posture cycle, duplicate/stale requests, safe reversal and latest destination")
    }
}
