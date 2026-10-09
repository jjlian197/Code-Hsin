import Foundation
import simd

@main
struct BoneClothChecks {
    static func main() throws {
        let configuration = ClothConfiguration(version: 1, sourceSHA256: String(repeating: "a", count: 64), floor: 0,
            joints: [.init(name: "body", bone: "body", parent: -1), .init(name: "body/root", bone: "HairRoot", parent: 0), .init(name: "body/root/tip", bone: "HairTip", parent: 1), .init(name: "body/helper", bone: "helper", parent: 0)],
            nodes: [.init(joint: 1, parent: -1, limit: 0.12, radius: 0.008), .init(joint: 2, parent: 0, limit: 0.12, radius: 0.008)],
            links: [.init(a: 0, b: 1, stiffness: 1)], colliders: [.init(a: 0, b: 1, radius: 0.06)],
            postGrants: [.init(joint: 3, source: 0, ratio: 0.4)])
        precondition(configuration.valid)
        func pose(_ seconds: Float) -> [ClothTransform] {
            [.init(position: SIMD3<Float>(sin(seconds * 4) * 0.08, 0.4, 0), rotation: simd_quatf(angle: sin(seconds) * 0.12, axis: SIMD3<Float>(0, 1, 0))),
             .init(position: SIMD3<Float>(0.1, 0, 0), rotation: simd_quatf(ix: 0, iy: 0, iz: 0, r: 1)),
             .init(position: SIMD3<Float>(0.05, -0.3, 0), rotation: simd_quatf(ix: 0, iy: 0, iz: 0, r: 1)),
             .init(position: SIMD3<Float>(0, 0.1, 0), rotation: simd_quatf(ix: 0, iy: 0, iz: 0, r: 1))]
        }
        var final: [SIMD3<Float>] = []
        for rate in [30, 60, 120] {
            var solver = BoneCloth(configuration: configuration)
            var changed = false
            var corrected = pose(0)
            for frame in 0..<(rate * 6) {
                let base = pose(Float(frame) / Float(rate))
                corrected = solver.update(base, delta: 1 / Double(rate))
                precondition(corrected.allSatisfy(\.finite))
                precondition(corrected[0].position == base[0].position)
                precondition(simd_length(corrected[0].rotation.vector - base[0].rotation.vector) < 1e-5)
                precondition(solver.maximumDisplacement < 0.13)
                precondition(solver.minimumFreeY >= configuration.floor + 0.008 - 1e-5)
                let expected = simd_slerp(simd_quatf(ix: 0, iy: 0, iz: 0, r: 1), base[0].rotation, 0.4)
                precondition(simd_length(corrected[3].rotation.vector - expected.vector) < 1e-5)
                if simd_distance(corrected[2].position, base[2].position) > 0.001 || simd_length(corrected[1].rotation.vector - base[1].rotation.vector) > 0.001 { changed = true }
            }
            FileHandle.standardError.write(Data("rate \(rate): changed \(changed), steps \(solver.steps), displacement \(solver.maximumDisplacement)\n".utf8))
            precondition(changed && solver.steps >= 710 && solver.steps <= 725)
            final.append(corrected[2].position)
            solver.reset(); _ = solver.update(pose(0), delta: 0.5)
            precondition(solver.maximumDisplacement < 0.13)
            var invalid = pose(0); invalid[0].position.x = .nan
            _ = solver.update(invalid, delta: .nan)
            let reset = solver.update(pose(0), delta: 1 / Double(rate))
            precondition(reset.allSatisfy(\.finite))
        }
        precondition(simd_distance(final[0], final[2]) < 0.015)
        var contact = BoneCloth(configuration: configuration)
        var low = pose(0); low[0].position.y = 0.15
        for _ in 0..<120 {
            let corrected = contact.update(low, delta: 1.0 / 120)
            precondition(corrected.allSatisfy(\.finite))
            precondition(contact.minimumFreeY >= 0.008 - 1e-5)
        }
        precondition(contact.collisionCorrections > 0)
        let chestConfiguration = ClothConfiguration(chestSprings: [.init(joint: 4, tip: [0, 0, 0.12], limitAngle: 0.22)],
            version: configuration.version, sourceSHA256: configuration.sourceSHA256, floor: configuration.floor,
            joints: configuration.joints + [.init(name: "body/chest", bone: "左胸", parent: 0), .init(name: "body/chest/tip", bone: "左胸先", parent: 4)],
            nodes: configuration.nodes, links: configuration.links, colliders: configuration.colliders,
            postGrants: [.init(joint: 3, source: 4, ratio: 0.4)])
        precondition(chestConfiguration.valid)
        for rate in [30, 60, 120] {
            var solver = BoneCloth(configuration: chestConfiguration)
            var peak: Float = 0
            func chestPose(_ seconds: Float) -> [ClothTransform] {
                var joints = pose(0)
                joints[0].position.y += sin(seconds * 12) * 0.03
                return joints + [.init(position: SIMD3(0.03, 0.1, 0), rotation: simd_quatf(ix: 0, iy: 0, iz: 0, r: 1)),
                                 .init(position: SIMD3(0, 0, 0.12), rotation: simd_quatf(ix: 0, iy: 0, iz: 0, r: 1))]
            }
            for frame in 0..<(rate * 4) {
                let base = chestPose(Float(frame) / Float(rate))
                let solved = solver.update(base, delta: 1 / Double(rate))
                precondition(solved.allSatisfy(\.finite) && solved[0].position == base[0].position)
                precondition(solved[4].position == base[4].position && solved[4].scale == base[4].scale)
                precondition(solver.maximumChestAngle <= 0.2201)
                let expected = simd_slerp(simd_quatf(ix: 0, iy: 0, iz: 0, r: 1), solved[4].rotation, 0.4)
                precondition(simd_length(solved[3].rotation.vector - expected.vector) < 1e-5)
                peak = max(peak, solver.maximumChestAngle)
            }
            precondition(peak > 0.03)
            for _ in 0..<(rate * 5) { _ = solver.update(chestPose(0), delta: 1 / Double(rate)) }
            precondition(solver.maximumChestAngle < 0.005)
            solver.reset(); _ = solver.update(chestPose(0), delta: 1 / Double(rate))
            precondition(solver.maximumChestAngle < 0.001)
            print("Chest acceleration, angle limit, auxiliary follow, settling and reset passed at \(rate) Hz; peak \(peak)")
        }
        // A moving garment should lag more than hair under the same anchor motion.
        func response(_ material: ClothConfiguration.Material) -> Float {
            let config = ClothConfiguration(version: configuration.version, sourceSHA256: configuration.sourceSHA256, floor: configuration.floor,
                joints: configuration.joints, nodes: configuration.nodes.map { .init(joint: $0.joint, parent: $0.parent, limit: $0.limit, radius: $0.radius, material: material) },
                links: configuration.links, colliders: configuration.colliders, postGrants: [])
            var solver = BoneCloth(configuration: config), accumulated: Float = 0
            for frame in 0..<720 {
                let base = pose(Float(frame) / 120), solved = solver.update(base, delta: 1.0 / 120)
                precondition(solved.allSatisfy(\.finite))
                if frame > 240 {
                    accumulated += simd_distance(base[0].child(base[1]).child(base[2]).position, solved[0].child(solved[1]).child(solved[2]).position)
                }
            }
            return accumulated / 479
        }
        let hairLag = response(.hair), garmentLag = response(.garment)
        precondition(garmentLag > hairLag * 1.2)
        print("Material response: hair \(hairLag), garment \(garmentLag)")
        // Entering a fixed body volume must not reduce its exclusion radius.
        let bodyContact = ClothConfiguration(version: configuration.version, sourceSHA256: configuration.sourceSHA256, floor: configuration.floor,
            joints: configuration.joints, nodes: configuration.nodes, links: configuration.links,
            colliders: [.init(a: 0, b: 0, radius: 0.06)], postGrants: [])
        var contactSolver = BoneCloth(configuration: bodyContact)
        var contactPose = pose(0)
        for frame in 0..<360 {
            contactPose[2].position = frame < 120 ? SIMD3(-0.05, -0.01, 0) : SIMD3(-0.07, -0.005, 0)
            let solved = contactSolver.update(contactPose, delta: 1.0 / 120)
            let freePoint = solved[0].child(solved[1]).child(solved[2]).position
            if frame > 90 { precondition(simd_distance(freePoint, solved[0].position) >= 0.068 - 1e-5) }
            precondition(solved.allSatisfy(\.finite) && solved[0].position == contactPose[0].position)
        }
        precondition(contactSolver.collisionCorrections > 0)
        print("Fixed body volume, deeper target penetration and finite contact passed")
        if CommandLine.arguments.count > 1 {
            for path in CommandLine.arguments.dropFirst() {
                let bytes = try Data(contentsOf: URL(fileURLWithPath: path))
                let decoded = try JSONDecoder().decode(ClothConfiguration.self, from: bytes)
                precondition(decoded.valid)
                print("Validated asset configuration: \(decoded.joints.count) joints, \(decoded.nodes.count) particles, \(decoded.postGrants.count) post grants")
            }
        }
        print("PBD finite poses, animation isolation, 30/60/120 Hz, bounded inertia, floor, reset and post-physics grants passed")
    }
}
