import Foundation
import simd

struct ClothConfiguration: Codable {
    struct Joint: Codable { let name: String; let bone: String; let parent: Int }
    struct Node: Codable { let joint: Int; let parent: Int; let limit: Float; let radius: Float }
    struct Link: Codable { let a: Int; let b: Int; let stiffness: Float }
    struct Collider: Codable { let a: Int; let b: Int; let radius: Float }
    struct Grant: Codable { let joint: Int; let source: Int; let ratio: Float }
    let version: Int
    let sourceSHA256: String
    let floor: Float
    let joints: [Joint]
    let nodes: [Node]
    let links: [Link]
    let colliders: [Collider]
    let postGrants: [Grant]
    var valid: Bool {
        version == 1 && sourceSHA256.count == 64 && sourceSHA256.allSatisfy(\.isHexDigit)
        && floor.isFinite && abs(floor) < 10 && (1...2000).contains(joints.count)
        && Set(joints.map(\.name)).count == joints.count
        && joints.enumerated().allSatisfy { !$0.element.name.isEmpty && $0.element.parent >= -1 && $0.element.parent < $0.offset }
        && (2...1000).contains(nodes.count) && Set(nodes.map(\.joint)).count == nodes.count
        && nodes.enumerated().allSatisfy { joints.indices.contains($0.element.joint) && $0.element.parent >= -1 && $0.element.parent < $0.offset && $0.element.limit.isFinite && (0.001...0.5).contains($0.element.limit) && $0.element.radius.isFinite && (0.001...0.05).contains($0.element.radius) }
        && links.count < 5000 && links.allSatisfy { nodes.indices.contains($0.a) && nodes.indices.contains($0.b) && $0.a != $0.b && $0.stiffness.isFinite && (0...1).contains($0.stiffness) }
        && colliders.count <= 20 && colliders.allSatisfy { joints.indices.contains($0.a) && joints.indices.contains($0.b) && $0.radius.isFinite && (0.001...0.5).contains($0.radius) }
        && postGrants.count <= 50 && postGrants.allSatisfy { joints.indices.contains($0.joint) && joints.indices.contains($0.source) && $0.joint != $0.source && $0.ratio.isFinite && (0...1).contains($0.ratio) }
    }
}

struct ClothTransform {
    var position: SIMD3<Float>
    var rotation: simd_quatf
    var scale = SIMD3<Float>(repeating: 1)
    var finite: Bool { position.x.isFinite && position.y.isFinite && position.z.isFinite && rotation.vector.x.isFinite && rotation.vector.y.isFinite && rotation.vector.z.isFinite && rotation.vector.w.isFinite && scale.x.isFinite && scale.y.isFinite && scale.z.isFinite && simd_length_squared(rotation.vector) > 0.5 && scale.x > 0 && scale.y > 0 && scale.z > 0 }
    func child(_ local: ClothTransform) -> ClothTransform {
        ClothTransform(position: position + rotation.act(local.position * scale), rotation: simd_normalize(rotation * local.rotation), scale: scale * local.scale)
    }
}

/// Bone PBD secondary motion. Animated body joints and model presentation are never simulated.
struct BoneCloth {
    let configuration: ClothConfiguration
    private let validConfiguration: Bool
    private let nodeForJoint: [Int]
    private let children: [[Int]]
    private var points: [SIMD3<Float>] = []
    private var previous: [SIMD3<Float>] = []
    private var lastTargets: [SIMD3<Float>] = []
    private var accumulator = 0.0
    private var age = 0.0
    private(set) var steps = 0
    private(set) var maximumDisplacement: Float = 0
    private(set) var minimumFreeY: Float = 0
    private(set) var collisionCorrections = 0

    init(configuration: ClothConfiguration) {
        self.configuration = configuration
        validConfiguration = configuration.valid
        var mapping = Array(repeating: -1, count: configuration.joints.count)
        var descendants = Array(repeating: [Int](), count: configuration.nodes.count)
        if validConfiguration {
            for (index, node) in configuration.nodes.enumerated() {
                mapping[node.joint] = index
                if node.parent >= 0 { descendants[node.parent].append(index) }
            }
        }
        nodeForJoint = mapping; children = descendants
    }
    mutating func reset() { points = []; previous = []; lastTargets = []; accumulator = 0; age = 0 }
    private func worlds(_ local: [ClothTransform]) -> [ClothTransform] {
        var transforms: [ClothTransform] = []; transforms.reserveCapacity(local.count)
        for index in local.indices {
            let parent = configuration.joints[index].parent
            transforms.append(parent >= 0 ? transforms[parent].child(local[index]) : local[index])
        }
        return transforms
    }
    private func nearest(_ point: SIMD3<Float>, _ start: SIMD3<Float>, _ end: SIMD3<Float>) -> SIMD3<Float> {
        let segment = end - start
        let fraction = min(1, max(0, simd_dot(point - start, segment) / max(1e-9, simd_length_squared(segment))))
        return start + segment * fraction
    }
    private mutating func project(_ index: Int, targets: [SIMD3<Float>], body: [ClothTransform], collide: Bool) {
        let node = configuration.nodes[index]
        guard node.parent >= 0 else { points[index] = targets[index]; return }
        var offset = points[index] - targets[index]
        let length = simd_length(offset)
        let limit = max(node.limit, configuration.floor + node.radius - targets[index].y + 0.02)
        if length > limit { points[index] = targets[index] + offset * (limit / length) }
        if collide {
            for collider in configuration.colliders {
                let start = body[collider.a].position, end = body[collider.b].position
                let restDistance = simd_distance(targets[index], nearest(targets[index], start, end))
                // Preserve the asset's original close-fitting clearance rather than inflating clothes.
                let radius = min(collider.radius + node.radius, max(node.radius, restDistance - 0.002))
                let contact = nearest(points[index], start, end)
                offset = points[index] - contact
                if simd_length_squared(offset) < radius * radius {
                    if simd_length_squared(offset) < 1e-10 { offset = targets[index] - contact }
                    if simd_length_squared(offset) < 1e-10 { offset = SIMD3<Float>(0, 0, 1) }
                    points[index] = contact + simd_normalize(offset) * radius
                    collisionCorrections += 1
                }
            }
        }
        // A fixed model-space floor is separate from the volumetric window's camera/size transforms.
        let clearance = configuration.floor + node.radius
        if points[index].y < clearance { points[index].y = clearance; collisionCorrections += 1 }
    }
    mutating func update(_ base: [ClothTransform], delta: Double) -> [ClothTransform] {
        guard validConfiguration, base.count == configuration.joints.count, base.allSatisfy(\.finite), delta.isFinite, delta > 0 else { reset(); return base }
        let body = worlds(base), targets = configuration.nodes.map { body[$0.joint].position }
        // Resume/loading stalls reset momentum; bounded fixed steps avoid giant impulses or catch-up loops.
        if points.count != targets.count || delta > 0.2 || zip(targets, lastTargets).contains(where: { simd_distance($0, $1) > 0.3 }) {
            points = targets; previous = targets; lastTargets = targets; accumulator = 0; age = 0
        }
        for index in targets.indices {
            let shift = (targets[index] - lastTargets[index]) * 0.92
            points[index] += shift; previous[index] += shift
            if configuration.nodes[index].parent < 0 { points[index] = targets[index]; previous[index] = targets[index] }
        }
        lastTargets = targets
        accumulator += min(delta, 1.0 / 15)
        let timestep = 1.0 / 120
        let lengths = configuration.links.map { simd_distance(targets[$0.a], targets[$0.b]) }
        var substeps = 0
        while accumulator >= timestep && substeps < 8 {
            let damping = Float(exp(-7 * timestep)), shape = Float(1 - exp(-2.4 * timestep))
            for index in points.indices where configuration.nodes[index].parent >= 0 {
                let velocity = (points[index] - previous[index]) * damping
                previous[index] = points[index]
                points[index] += velocity + SIMD3<Float>(0, -2.2 * Float(timestep * timestep), 0)
                points[index] += (targets[index] - points[index]) * shape
            }
            for iteration in 0..<4 {
                for (slot, link) in configuration.links.enumerated() {
                    let offset = points[link.b] - points[link.a], length = simd_length(offset)
                    let a: Float = configuration.nodes[link.a].parent < 0 ? 0 : 1
                    let b: Float = configuration.nodes[link.b].parent < 0 ? 0 : 1
                    if length < 1e-7 || a + b == 0 { continue }
                    let correction = offset * ((length - lengths[slot]) / length / (a + b) * link.stiffness)
                    points[link.a] += correction * a; points[link.b] -= correction * b
                }
                for index in points.indices { project(index, targets: targets, body: body, collide: iteration == 3) }
            }
            accumulator -= timestep; age += timestep; substeps += 1; steps += 1
        }
        maximumDisplacement = zip(points, targets).map { simd_distance($0, $1) }.max() ?? 0
        minimumFreeY = points.indices.filter { configuration.nodes[$0].parent >= 0 }.map { points[$0].y }.min() ?? configuration.floor
        let blend = Float(min(1, age / 0.35))
        var desired = body
        var corrected = base
        for joint in base.indices {
            let parent = configuration.joints[joint].parent
            let index = nodeForJoint[joint]
            if index >= 0 {
                let original = body[joint]
                desired[joint].position = original.position + (points[index] - original.position) * blend
                // Direction bends the chain while the animated twist is preserved, with a bounded angle.
                if let child = children[index].max(by: { simd_distance(targets[$0], targets[index]) < simd_distance(targets[$1], targets[index]) }) {
                    let from = targets[child] - targets[index], to = points[child] - points[index]
                    if simd_length_squared(from) > 1e-9 && simd_length_squared(to) > 1e-9 {
                        var turn = simd_quatf(from: simd_normalize(from), to: simd_normalize(to))
                        let angle = abs(turn.angle)
                        if angle > 0.6 { turn = simd_slerp(simd_quatf(ix: 0, iy: 0, iz: 0, r: 1), turn, 0.6 / angle) }
                        desired[joint].rotation = simd_slerp(original.rotation, turn * original.rotation, blend)
                    }
                }
                if parent >= 0 {
                    corrected[joint].position = desired[parent].rotation.inverse.act(desired[joint].position - desired[parent].position) / desired[parent].scale
                    corrected[joint].rotation = simd_normalize(desired[parent].rotation.inverse * desired[joint].rotation)
                } else { corrected[joint] = desired[joint] }
            } else { desired[joint] = parent >= 0 ? desired[parent].child(corrected[joint]) : corrected[joint] }
        }
        // The trial auxiliary rig inherits the current chest AFTER secondary-motion writes.
        // Only verified rotation grants are represented; generic PMX IK/Grant is not implied.
        for grant in configuration.postGrants {
            corrected[grant.joint].rotation = simd_slerp(simd_quatf(ix: 0, iy: 0, iz: 0, r: 1), corrected[grant.source].rotation, grant.ratio)
        }
        guard corrected.allSatisfy(\.finite) else { reset(); return base }
        return corrected
    }
}
