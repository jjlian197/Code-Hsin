import Foundation
import RealityKit

/// Animation events refresh moving targets; a scene clock sustains constant resting poses.
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
    private var heldPose: SkeletalPose?
    private var lastAnimationPose: SkeletalPose?
    private var lastStaticTick: Double?
    private(set) var staticFrames = 0
    private(set) var lastBase: [ClothTransform] = []
    private(set) var lastSolved: [ClothTransform] = []
    var snapshot: [String: Any] {
        var receipt: [String: Any] = ["sourceSHA256": solver.configuration.sourceSHA256, "frames": frames, "steps": solver.steps, "particles": solver.configuration.nodes.count,
         "links": solver.configuration.links.count, "postGrants": solver.configuration.postGrants.count, "chestSprings": solver.configuration.chestSprings?.count ?? 0, "maximumChestAngle": solver.maximumChestAngle,
         "maximumDisplacement": solver.maximumDisplacement, "minimumFreeY": solver.minimumFreeY,
         "floor": solver.configuration.floor, "collisionCorrections": solver.collisionCorrections,
         "milliseconds": lastMilliseconds, "maxMilliseconds": maximumMilliseconds, "enabled": wasEnabled,
         "pose": poseID, "status": status, "staticFrames": staticFrames, "holdingStaticPose": heldPose != nil]
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
    // Preserve the neutral resting pose across off/on and scene hide/resume: a constant
    // animation might emit no new event to reconstruct it after re-enabling physics.
    func reset() { solver.reset(); wasEnabled = false; lastStaticTick = nil }
    func beginStaticPose() {
        // The calibrated lie_down endpoint equals side_lying. Seed from its last
        // animation target before starting the constant clip, which may delay events.
        heldPose = lastAnimationPose; lastStaticTick = nil
    }
    func leaveStaticPose() { heldPose = nil; lastStaticTick = nil }
    private func staticDelta(_ fallback: Double) -> Double {
        let now = ProcessInfo.processInfo.systemUptime
        let elapsed = lastStaticTick.map { now - $0 } ?? min(fallback, 1.0 / 30)
        lastStaticTick = now
        return max(1e-6, elapsed)
    }
    func advanceStaticFrame(delta: Double, enabled: Bool) {
        guard let heldPose else { return }
        staticFrames += 1
        apply(pose: heldPose, delta: staticDelta(delta), enabled: enabled)
    }
    func update(delta: Float, enabled: Bool, staticPose: Bool = false) {
        guard let rig, let component = rig.components[SkeletalPosesComponent.self], let pose = component.poses[poseID] ?? component.poses.default else { status = "衣发骨架不可用"; return }
        // USD import starts with a path ID; playback exposes the same rig as the default pose.
        guard pose.jointNames == jointNames else { status = "衣发动画骨架不匹配"; reset(); return }
        poseID = pose.id
        if staticPose {
            // side_lying is an identical-frame clip. Capture its neutral pose once;
            // subsequent events may expose our own physics writes as the current pose.
            if heldPose == nil { heldPose = pose }
            if let heldPose { apply(pose: heldPose, delta: staticDelta(Double(delta)), enabled: enabled) }
        } else {
            lastAnimationPose = pose
            leaveStaticPose()
            apply(pose: pose, delta: Double(delta), enabled: enabled)
        }
    }
    private func apply(pose originalPose: SkeletalPose, delta: Double, enabled: Bool) {
        guard rig != nil else { return }
        var pose = originalPose
        // The exported clips reset all simulated bones, so the incoming pose is animation only.
        // Disabled/hidden/switching state discards momentum; it never drives the microphone or Agent.
        guard enabled else {
            if wasEnabled { reset() }
            // A constant resting clip cannot restore the neutral palette for us.
            if heldPose != nil { writePose(pose) }
            status = "实时衣发已关闭"; return
        }
        if !wasEnabled { solver.reset() }; wasEnabled = true
        let started = ProcessInfo.processInfo.systemUptime
        let base = pose.jointTransforms.map { ClothTransform(position: $0.translation, rotation: $0.rotation, scale: $0.scale) }
        guard base.allSatisfy(\.finite) else { reset(); status = "动画骨骼含非法变换，未写回物理"; return }
        let corrected = solver.update(base, delta: delta)
        guard corrected.count == pose.jointTransforms.count else { reset(); status = "衣发骨骼数量不匹配"; return }
        for index in corrected.indices {
            pose.jointTransforms[index] = Transform(scale: corrected[index].scale, rotation: corrected[index].rotation, translation: corrected[index].position)
        }
        writePose(pose)
        frames += 1
        lastMilliseconds = (ProcessInfo.processInfo.systemUptime - started) * 1000
        maximumMilliseconds = max(maximumMilliseconds, lastMilliseconds)
        #if DEBUG
        lastBase = base; lastSolved = corrected
        #endif
        status = (solver.configuration.chestSprings ?? []).isEmpty ? "实时衣发已开启" : "实时衣发与胸部动态已开启"
    }
    private func writePose(_ pose: SkeletalPose) {
        guard let rig, var component = rig.components[SkeletalPosesComponent.self] else { return }
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
    }
}
