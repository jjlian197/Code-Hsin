import Foundation

/// The latest requested destination wins, after the current support segment completes.
struct PostureState: Equatable {
    enum Phase: String { case standing, lyingDown, sideLying, gettingUp }
    private(set) var phase: Phase = .standing
    private(set) var wantsLying = false

    mutating func request(lying: Bool) -> String? {
        wantsLying = lying
        switch phase {
        case .standing where lying:
            phase = .lyingDown
            return "lie_down"
        case .sideLying where !lying:
            phase = .gettingUp
            return "get_up"
        default: return nil
        }
    }

    mutating func completed(_ motion: String) -> String? {
        switch (phase, motion) {
        case (.lyingDown, "lie_down"):
            if wantsLying { phase = .sideLying; return "side_lying" }
            phase = .gettingUp
            return "get_up"
        case (.gettingUp, "get_up"):
            if wantsLying { phase = .lyingDown; return "lie_down" }
            phase = .standing
            return "idle"
        default: return nil
        }
    }
}
