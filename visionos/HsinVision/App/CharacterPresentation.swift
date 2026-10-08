import Foundation
import simd

/// Window presentation only. Immersive physical calibration will use a separate transform layer.
struct CharacterPresentation {
    var minimum = SIMD3<Float>(-0.5, 0, -0.4)
    var maximum = SIMD3<Float>(0.5, 1.7, 0.4)
    var size: Float = 1
    var mode = "full"
    func pose(head: SIMD3<Float>?) -> (scale: Float, position: SIMD3<Float>, yaw: Float) {
        let extent = maximum - minimum
        let fit = min(0.35, 0.85 / max(0.01, extent.x), 1.05 / max(0.01, extent.y), 0.70 / max(0.01, extent.z))
        let factor = min(1.25, max(0.8, size))
        guard mode != "full", let head else { return (fit * factor, -(minimum + maximum) * fit * factor / 2, 0) }
        let scale: Float = 0.85 * factor
        let yaw: Float = mode == "head_left" ? 0.38 : mode == "head_right" ? -0.38 : 0
        let rotated = simd_quatf(angle: yaw, axis: SIMD3<Float>(0, 1, 0)).act(head)
        return (scale, -rotated * scale + SIMD3<Float>(0, 0.10, 0), yaw)
    }
}
