import Foundation
import simd

struct ClothConfiguration: Codable {
    struct Joint: Codable { let name: String; let bone: String; let parent: Int }
    enum Material: String, Codable { case hair, garment }
    struct Node: Codable { let joint: Int; let parent: Int; let limit: Float; let radius: Float; var material: Material? = nil }
    struct Link: Codable { let a: Int; let b: Int; let stiffness: Float }
    struct Collider: Codable { let a: Int; let b: Int; let radius: Float }
    struct ChestSpring: Codable { let joint: Int; let tip: [Float]; let limitAngle: Float }
    var chestSprings: [ChestSpring]? = nil
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
        && (chestSprings ?? []).count <= 2 && (chestSprings ?? []).allSatisfy {
            joints.indices.contains($0.joint) && ["左胸", "右胸"].contains(joints[$0.joint].bone)
            && $0.tip.count == 3 && $0.tip.allSatisfy(\.isFinite)
            && (0.02...0.3).contains(simd_length(SIMD3<Float>($0.tip[0], $0.tip[1], $0.tip[2])))
            && $0.limitAngle.isFinite && (0.01...0.3).contains($0.limitAngle)
        }
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
    private struct Profile {
        let follow: Float; let damping: Double; let restoring: Double
        static let hair = Profile(follow: 0.65, damping: 7, restoring: 2.4)
        static let garment = Profile(follow: 0.5, damping: 5.5, restoring: 0.6)
    }
    private let profiles: [Profile]
    private let linkStiffness: [Float]
    private var points: [SIMD3<Float>] = []
    private var previous: [SIMD3<Float>] = []
    private var lastTargets: [SIMD3<Float>] = []
    private var chestPoints: [SIMD3<Float>] = []
    private var chestPrevious: [SIMD3<Float>] = []
    private var chestTargets: [SIMD3<Float>] = []
    private(set) var maximumChestAngle: Float = 0
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
        // Old version-1 resources retain a name-based fallback; new exports label material.
        let materials = configuration.nodes.map { node -> ClothConfiguration.Material in
            if let material = node.material { return material }
            let name = configuration.joints.indices.contains(node.joint) ? configuration.joints[node.joint].bone : ""
            return ["Hair", "Daimao", "髪", "髮", "发"].contains(where: name.contains) ? .hair : .garment
        }
        profiles = materials.map { $0 == .hair ? .hair : .garment }
        linkStiffness = configuration.links.map { link in
            guard configuration.nodes.indices.contains(link.a), configuration.nodes.indices.contains(link.b) else { return link.stiffness }
            let chain = configuration.nodes[link.b].parent == link.a || configuration.nodes[link.a].parent == link.b
            // Keep chain length rigid; only garment cross-links loosen to permit local bending.
            return !chain && (materials[link.a] == .garment || materials[link.b] == .garment) ? min(link.stiffness, 0.25) : link.stiffness
        }
    }
    mutating func reset() { points = []; previous = []; lastTargets = []; accumulator = 0; age = 0; chestPoints = []; chestPrevious = []; chestTargets = []; maximumChestAngle = 0 }
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
            // Fixed body volumes must not shrink when an animated garment target enters
            // the body. Two passes handle adjacent/overlapping anatomical capsules.
            for _ in 0..<2 {
                for collider in configuration.colliders {
                    let start = body[collider.a].position, end = body[collider.b].position
                    let radius = collider.radius + node.radius
                    let contact = nearest(points[index], start, end)
                    offset = points[index] - contact
                    if simd_length_squared(offset) < radius * radius {
                        if simd_length_squared(offset) < 1e-10 { offset = targets[index] - contact }
                        if simd_length_squared(offset) < 1e-10 { offset = SIMD3<Float>(0, 0, 1) }
                        let normal = simd_normalize(offset), before = points[index]
                        points[index] = contact + normal * radius
                        // Preserve tangential travel, remove inward velocity and add light
                        // contact friction rather than turning a projection into a bounce.
                        previous[index] += points[index] - before
                        let velocity = points[index] - previous[index]
                        previous[index] += normal * min(0, simd_dot(velocity, normal))
                        previous[index] += (velocity - normal * simd_dot(velocity, normal)) * 0.015
                        collisionCorrections += 1
                    }
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
            reset()
            points = targets; previous = targets; lastTargets = targets; accumulator = 0; age = 0
        }
        for index in targets.indices {
            // Free particles retain world-space inertia; following 92% of every animated
            // target shift erased nearly all running acceleration before the solver saw it.
            let shift = (targets[index] - lastTargets[index]) * profiles[index].follow
            points[index] += shift; previous[index] += shift
            if configuration.nodes[index].parent < 0 { points[index] = targets[index]; previous[index] = targets[index] }
        }
        lastTargets = targets
        let springs = configuration.chestSprings ?? []
        let nextChestTargets = springs.map { spring in
            body[spring.joint].child(ClothTransform(position: SIMD3(spring.tip[0], spring.tip[1], spring.tip[2]), rotation: simd_quatf(ix: 0, iy: 0, iz: 0, r: 1))).position
        }
        if chestPoints.count != springs.count {
            chestPoints = nextChestTargets; chestPrevious = nextChestTargets; chestTargets = nextChestTargets
        }
        for index in springs.indices {
            let shift = (nextChestTargets[index] - chestTargets[index]) * 0.4
            chestPoints[index] += shift; chestPrevious[index] += shift
        }
        chestTargets = nextChestTargets
        accumulator += min(delta, 1.0 / 15)
        let timestep = 1.0 / 120
        let lengths = configuration.links.map { simd_distance(targets[$0.a], targets[$0.b]) }
        var substeps = 0
        while accumulator >= timestep && substeps < 8 {
            for index in points.indices where configuration.nodes[index].parent >= 0 {
                let damping = Float(exp(-profiles[index].damping * timestep))
                let shape = Float(1 - exp(-profiles[index].restoring * timestep))
                let velocity = (points[index] - previous[index]) * damping
                previous[index] = points[index]
                points[index] += velocity + SIMD3<Float>(0, -2.2 * Float(timestep * timestep), 0)
                points[index] += (targets[index] - points[index]) * shape
            }
            // Two virtual chest tips retain acceleration, with a restoring spring and damping.
            // Rotations are applied to chest bones before the trial's auxiliary rotation grants.
            for index in springs.indices {
                let velocity = (chestPoints[index] - chestPrevious[index]) * Float(exp(-8.5 * timestep))
                chestPrevious[index] = chestPoints[index]
                chestPoints[index] += velocity + (nextChestTargets[index] - chestPoints[index]) * Float(120 * timestep * timestep)
                let origin = body[springs[index].joint].position
                let direction = chestPoints[index] - origin
                if simd_length_squared(direction) > 1e-9 {
                    chestPoints[index] = origin + simd_normalize(direction) * simd_distance(origin, nextChestTargets[index])
                }
            }
            for iteration in 0..<4 {
                for (slot, link) in configuration.links.enumerated() {
                    let offset = points[link.b] - points[link.a], length = simd_length(offset)
                    let a: Float = configuration.nodes[link.a].parent < 0 ? 0 : 1
                    let b: Float = configuration.nodes[link.b].parent < 0 ? 0 : 1
                    if length < 1e-7 || a + b == 0 { continue }
                    let correction = offset * ((length - lengths[slot]) / length / (a + b) * linkStiffness[slot])
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
        maximumChestAngle = 0
        for (index, spring) in springs.enumerated() {
            let joint = spring.joint, parent = configuration.joints[joint].parent
            let from = nextChestTargets[index] - body[joint].position, to = chestPoints[index] - body[joint].position
            guard simd_length_squared(from) > 1e-9, simd_length_squared(to) > 1e-9 else { continue }
            var turn = simd_quatf(from: simd_normalize(from), to: simd_normalize(to))
            let angle = abs(turn.angle)
            if angle > spring.limitAngle { turn = simd_slerp(simd_quatf(ix: 0, iy: 0, iz: 0, r: 1), turn, spring.limitAngle / angle) }
            turn = simd_slerp(simd_quatf(ix: 0, iy: 0, iz: 0, r: 1), turn, blend)
            maximumChestAngle = max(maximumChestAngle, abs(turn.angle))
            let rotation = simd_normalize(turn * body[joint].rotation)
            corrected[joint].rotation = parent >= 0 ? simd_normalize(body[parent].rotation.inverse * rotation) : rotation
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
