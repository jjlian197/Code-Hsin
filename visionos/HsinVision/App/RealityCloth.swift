import Foundation
import RealityKit

/// Writes only after RealityKit has evaluated the animated skeleton, once per rendered frame.
@MainActor
final class RealityCloth {
    private weak var rig: Entity?
    private var poseID: String
    private let jointNames: [String]
    private var solver: BoneCloth
    private(set) var frames = 0
    private(set) var lastMilliseconds = 0.0
    private(set) var maximumMilliseconds = 0.0
    private(set) var status = "实时衣发未初始化"
    private var wasEnabled = false
    private(set) var lastBase: [ClothTransform] = []
    private(set) var lastSolved: [ClothTransform] = []
    var snapshot: [String: Any] {
        var receipt: [String: Any] = ["sourceSHA256": solver.configuration.sourceSHA256, "frames": frames, "steps": solver.steps, "particles": solver.configuration.nodes.count,
         "links": solver.configuration.links.count, "postGrants": solver.configuration.postGrants.count, "chestSprings": solver.configuration.chestSprings?.count ?? 0, "maximumChestAngle": solver.maximumChestAngle,
         "maximumDisplacement": solver.maximumDisplacement, "minimumFreeY": solver.minimumFreeY,
         "floor": solver.configuration.floor, "collisionCorrections": solver.collisionCorrections,
         "milliseconds": lastMilliseconds, "maxMilliseconds": maximumMilliseconds, "enabled": wasEnabled,
         "pose": poseID, "status": status]
        #if DEBUG
        if let model = rig as? ModelEntity, model.jointTransforms.count == lastSolved.count, !lastSolved.isEmpty {
            receipt["renderRigReadbackMaximumError"] = zip(model.jointTransforms, lastSolved).map {
                max(simd_distance($0.translation, $1.position), min(simd_length($0.rotation.vector - $1.rotation.vector), simd_length($0.rotation.vector + $1.rotation.vector)))
            }.max() ?? 0
            receipt["basePose"] = lastBase.map { [$0.position.x, $0.position.y, $0.position.z, $0.rotation.vector.x, $0.rotation.vector.y, $0.rotation.vector.z, $0.rotation.vector.w] }
            receipt["solvedPose"] = lastSolved.map { [$0.position.x, $0.position.y, $0.position.z, $0.rotation.vector.x, $0.rotation.vector.y, $0.rotation.vector.z, $0.rotation.vector.w] }
        }
        #endif
        return receipt
    }
    init?(character: Entity, configuration: ClothConfiguration) {
        guard configuration.valid else { return nil }
        let expected = configuration.joints.map(\.name)
        func find(_ entity: Entity) -> (Entity, String)? {
            if let poses = entity.components[SkeletalPosesComponent.self] {
                for pose in poses.poses where pose.jointNames == expected && pose.jointTransforms.count == expected.count {
                    return (entity, pose.id)
                }
            }
            for child in entity.children { if let found = find(child) { return found } }
            return nil
        }
        guard let (entity, identifier) = find(character) else { return nil }
        rig = entity; poseID = identifier; jointNames = expected; solver = BoneCloth(configuration: configuration)
        status = "衣发骨架已匹配"
    }
    func reset() { solver.reset(); wasEnabled = false }
    func update(delta: Float, enabled: Bool) {
        guard let rig, var component = rig.components[SkeletalPosesComponent.self], var pose = component.poses[poseID] ?? component.poses.default else { status = "衣发骨架不可用"; return }
        // USD import starts with a path ID; playback exposes the same rig as the default pose.
        guard pose.jointNames == jointNames else { status = "衣发动画骨架不匹配"; reset(); return }
        poseID = pose.id
        // The exported clips reset all simulated bones, so the incoming pose is animation only.
        // Disabled/hidden/switching state discards momentum; it never drives the microphone or Agent.
        guard enabled else { if wasEnabled { reset() }; status = "实时衣发已关闭"; return }
        if !wasEnabled { solver.reset() }; wasEnabled = true
        let started = ProcessInfo.processInfo.systemUptime
        let base = pose.jointTransforms.map { ClothTransform(position: $0.translation, rotation: $0.rotation, scale: $0.scale) }
        guard base.allSatisfy(\.finite) else { reset(); status = "动画骨骼含非法变换，未写回物理"; return }
        let corrected = solver.update(base, delta: Double(delta))
        guard corrected.count == pose.jointTransforms.count else { reset(); status = "衣发骨骼数量不匹配"; return }
        for index in corrected.indices {
            pose.jointTransforms[index] = Transform(scale: corrected[index].scale, rotation: corrected[index].rotation, translation: corrected[index].position)
        }
        var writesDefaultPalette = pose.id.isEmpty
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--physics-probe-component-write") { writesDefaultPalette = false }
        #endif
        if let model = rig as? ModelEntity, writesDefaultPalette {
            // Imported USD clips animate the ModelEntity default joint palette. Write
            // that palette directly so the rendered skin and the exposed pose agree.
            model.jointTransforms = Array(pose.jointTransforms)
        } else {
            component.poses.set(pose); rig.components.set(component)
        }
        frames += 1
        lastMilliseconds = (ProcessInfo.processInfo.systemUptime - started) * 1000
        maximumMilliseconds = max(maximumMilliseconds, lastMilliseconds)
        #if DEBUG
        lastBase = base; lastSolved = corrected
        #endif
        status = (solver.configuration.chestSprings ?? []).isEmpty ? "实时衣发已开启" : "实时衣发与胸部动态已开启"
    }
}
