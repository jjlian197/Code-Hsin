import AudioToolbox
import AVFoundation
import Foundation
import RealityKit
import Security
import SwiftUI

@MainActor
final class CompanionStore: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published var bridgeURL = UserDefaults.standard.string(forKey: "bridgeURL") ?? "https://bridge.oieasklja.icu" {
        didSet { if bridgeURL != oldValue { stopSpeech(disconnect: true); bridgeToken = credential(for: bridgeURL) ?? "" } }
    }
    @Published var bridgeToken = ""
    @Published var gatewayURL = UserDefaults.standard.string(forKey: "gatewayURL") ?? "" {
        didSet { if gatewayURL != oldValue { stopSpeech(disconnect: true); gatewayToken = credential(for: gatewayURL) ?? "" } }
    }
    @Published var gatewayToken = ""
    @Published var inputText = ""
    @Published var selectedCharacter = UserDefaults.standard.string(forKey: "selectedCharacter") ?? "aemeath" {
        didSet { if selectedCharacter != oldValue { changeCharacter(); UserDefaults.standard.set(selectedCharacter, forKey: "selectedCharacter") } }
    }
    @Published var selectedForm = UserDefaults.standard.string(forKey: "selectedForm") ?? "first" {
        didSet { if selectedForm != oldValue { changeCharacter(); UserDefaults.standard.set(selectedForm, forKey: "selectedForm") } }
    }
    @Published var chatProvider = "default" {
        didSet { if chatProvider != oldValue { stopSpeech(); selectHistory(); UserDefaults.standard.set(chatProvider, forKey: "chatProvider." + selectedCharacter) } }
    }
    var characterName: String { selectedCharacter == "hsin" ? "心" : "爱弥斯" }
    var resourceDirectory: String? { selectedCharacter == "hsin" ? "Characters/Hsin" + (selectedForm == "second" ? "Second" : "First") : nil }
    var modelResource: String { resourceDirectory ?? "Aemeath" }
    private var turnWatchdog: Task<Void, Never>?
    @Published var sttProvider = UserDefaults.standard.string(forKey: "sttProvider") ?? "remote" { didSet { if sttProvider != oldValue { stopSpeech(); UserDefaults.standard.set(sttProvider, forKey: "sttProvider") } } }
    @Published private(set) var transcript = ""
    @Published private(set) var fullReply = ""
    @Published private(set) var isListening = false
    @Published var continuousSpeech = UserDefaults.standard.object(forKey: "continuousSpeech") as? Bool ?? true {
        didSet { if continuousSpeech != oldValue { stopSpeech(); UserDefaults.standard.set(continuousSpeech, forKey: "continuousSpeech") } }
    }
    @Published private(set) var voiceSessionActive = false
    private var resumeListeningTask: Task<Void, Never>?
    var voiceControlLabel: String { voiceSessionActive ? "关闭语音" : busy ? "打断" : isListening ? "结束说话" : "和" + characterName + "说话" }
    var voiceControlIcon: String { voiceSessionActive ? "mic.slash.fill" : busy ? "hand.raised.fill" : isListening ? "stop.fill" : "mic.fill" }
    private let recorder = MicrophoneRecorder()
    private var recordingTask: Task<Void, Never>?
    private var gatewayReader: Task<Void, Never>?
    private var gatewaySocket: URLSessionWebSocketTask?
    private var gatewayInterrupt: Task<Void, Error>?
    private var gatewayTurn: String?
    private var turnFinished = true
    private struct AudioClip { let audio: Data; let text: String; let index: Int; let mouth: SpeechMouthTimeline }
    private var mouthTimeline: SpeechMouthTimeline?
    private var mouthSmoother = SpeechMouthSmoother()
    private var lastFaceUpdate = Date()
    #if DEBUG
    private var mouthProbeCounts: [String: Int] = [:]
    #endif
    private var pendingAudio: [AudioClip] = []
    @Published var language = UserDefaults.standard.string(forKey: "language") ?? "zh" { didSet { if language != oldValue { stopSpeech(); UserDefaults.standard.set(language, forKey: "language") } } }
    @Published private(set) var status = "正在加载角色"
    @Published private(set) var caption = ""
    @Published private(set) var busy = false
    @Published private(set) var modelReady = false
    private var character: Entity?
    private var faces: [Entity] = []
    private var motionRoot: Entity?
    private var motions: [String: AnimationResource] = [:]
    private var motionDurations: [String: Double] = [:]
    private var motionPlayback: AnimationPlaybackController?
    @Published private(set) var posture = PostureState()
    var canChangePosture: Bool { ["lie_down", "side_lying", "get_up"].allSatisfy { motions[$0] != nil } }
    private var motionCompletion: EventSubscription?
    private var activeMotion = "idle"
    var wantsLying: Bool { pendingPosture ?? posture.wantsLying }
    @Published private var pendingPosture: Bool?
    private var pendingGesture: (name: String, label: String)?
    private var modelGeneration = 0
    #if DEBUG
    private var postureProbeTask: Task<Void, Never>?
    private var postureProbeHistory: [String] = []
    private var interactionProbeHistory: [String] = []
    #endif
    @Published private(set) var historyError = ""
    @Published private(set) var conversationMessages: [ConversationMessage] = []
    private var history = ConversationHistory(directory: FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("Conversations"))
    let care = CompanionCare()
    @Published var displaySize = min(1.25, max(0.8, UserDefaults.standard.object(forKey: "displaySize") as? Double ?? 1)) {
        didSet { UserDefaults.standard.set(displaySize, forKey: "displaySize") }
    }
    @Published var viewMode = UserDefaults.standard.string(forKey: "viewMode") ?? "full" {
        didSet { UserDefaults.standard.set(viewMode, forKey: "viewMode") }
    }
    @Published var speechPause = min(1.2, max(0.4, UserDefaults.standard.object(forKey: "speechPause") as? Double ?? 0.55)) {
        didSet { if speechPause != oldValue { stopSpeech(); UserDefaults.standard.set(speechPause, forKey: "speechPause") } }
    }
    @Published private(set) var recognitionTiming = ""
    @Published private(set) var connectionDiagnostics = ""
    @Published private(set) var checkingConnections = false
    private var diagnosticTask: Task<Void, Never>?
    private var recognitionStarted: Double?
    private var presentation = CharacterPresentation()
    private var presentationBaseOrientation = simd_quatf(angle: 0, axis: SIMD3<Float>(0, 1, 0))
    private var manualExpressionUntil = 0.0
    @Published var expression = "normal"
    @Published var breathing = UserDefaults.standard.object(forKey: "breathing") as? Bool ?? true {
        didSet { UserDefaults.standard.set(breathing, forKey: "breathing"); if modelReady && isIdle { _ = playMotion("idle") } }
    }
    @Published var randomLook = UserDefaults.standard.object(forKey: "randomLook") as? Bool ?? true {
        didSet { UserDefaults.standard.set(randomLook, forKey: "randomLook"); if !randomLook { behavior.look("center", at: uptime) } }
    }
    @Published var touchEnabled = UserDefaults.standard.object(forKey: "touchEnabled") as? Bool ?? true {
        didSet { UserDefaults.standard.set(touchEnabled, forKey: "touchEnabled"); touchTargets.forEach { $0.isEnabled = touchEnabled } }
    }
    @Published var automaticRest = UserDefaults.standard.object(forKey: "automaticRest") as? Bool ?? true {
        didSet { UserDefaults.standard.set(automaticRest, forKey: "automaticRest"); noteInteraction() }
    }
    private var behavior = CompanionBehavior()
    private var behaviorResources: SpatialBehaviorResources?
    private var faceOverlay: [String: Float] = [:]
    private var touchTargets: [Entity] = []
    private var sceneVisible = true
    private var uptime: Double { ProcessInfo.processInfo.systemUptime }
    private var isIdle: Bool { ["idle", "idle_breathing"].contains(activeMotion) }
    var canRun: Bool { modelReady && motions["treadmill_running"] != nil }
    var availableExpressions: [String] { ["normal"] + (behaviorResources?.expressions.keys.map { $0 } ?? ["content"]).filter { $0 != "normal" }.sorted() }
    var canLook: Bool { faces.contains { $0.components[BlendShapeWeightsComponent.self]?.weightSet.contains { $0.weightNames.contains("look_left") } == true } }
    private var speechTask: Task<Void, Never>?
    private var player: AVAudioPlayer?
    private var generation = 0
    private var activeRequest: String?
    private var nextBlink = Date().addingTimeInterval(3)
    private var blinkStart: Date?

    override init() {
        super.init()
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--character-aemeath") { selectedCharacter = "aemeath" }
        if ProcessInfo.processInfo.arguments.contains("--form-first") { selectedForm = "first" }
        if ProcessInfo.processInfo.arguments.contains("--character-hsin") { selectedCharacter = "hsin" }
        if ProcessInfo.processInfo.arguments.contains("--form-second") { selectedForm = "second" }
        #endif
        bridgeToken = credential(for: bridgeURL) ?? ""
        gatewayToken = credential(for: gatewayURL) ?? ""
        importInstalledConnection()
        chatProvider = UserDefaults.standard.string(forKey: "chatProvider." + selectedCharacter) ?? "default"
        selectHistory()
        care.select(selectedCharacter, uptime: uptime)
        care.onNotice = { [weak self] _, sound in
            guard let self else { return }
            // A notification sound must not become another utterance in a voice session.
            if sound && !self.voiceSessionActive && !self.busy && !self.isListening { AudioServicesPlaySystemSound(1013) }
        }
        behavior.interact(at: uptime)
        recorder.onLimit = { [weak self] in self?.finishRecording() }
        recorder.onSpeech = { [weak self] in self?.noteInteraction() }
        recorder.onFailure = { [weak self] message in self?.stopSpeech(); self?.status = message }
    }

    private func changeCharacter() {
        modelGeneration += 1
        modelReady = false
        care.select(selectedCharacter, uptime: uptime)
        stopSpeech()
        resetPosture()
        expression = "normal"
        faceOverlay = [:]
        behavior.interact(at: uptime)
        transcript = ""
        caption = ""
        fullReply = ""
        chatProvider = UserDefaults.standard.string(forKey: "chatProvider." + selectedCharacter) ?? "default"
        selectHistory()
        status = "正在加载" + characterName
    }

    private struct InstalledConnection: Decodable {
        let bridgeURL: String
        let gatewayURL: String
        let token: String
    }

    private func importInstalledConnection() {
        let file = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("HsinConnection.json")
        guard FileManager.default.fileExists(atPath: file.path) else { return }
        do {
            let connection = try JSONDecoder().decode(InstalledConnection.self, from: Data(contentsOf: file))
            _ = try endpoint(connection.bridgeURL)
            _ = try endpoint(connection.gatewayURL, allowLocal: true)
            guard connection.token.count >= 32,
                  !connection.token.contains(where: { $0.isWhitespace }) else {
                throw BridgeError.message("安装连接配置无效")
            }
            try storeCredential(connection.token, for: connection.bridgeURL)
            try storeCredential(connection.token, for: connection.gatewayURL)
            bridgeURL = connection.bridgeURL
            gatewayURL = connection.gatewayURL
            bridgeToken = connection.token
            gatewayToken = connection.token
            UserDefaults.standard.set(bridgeURL, forKey: "bridgeURL")
            UserDefaults.standard.set(gatewayURL, forKey: "gatewayURL")
            // This installer-owned file is consumed only after Keychain writes succeed.
            try FileManager.default.removeItem(at: file)
            let receipt: [String: Any] = ["credentialsStored":
                credential(for: bridgeURL) == connection.token && credential(for: gatewayURL) == connection.token,
                "bridgeURL": bridgeURL, "gatewayURL": gatewayURL]
            try JSONSerialization.data(withJSONObject: receipt).write(
                to: file.deletingLastPathComponent().appendingPathComponent("HsinConnectionReceipt.json"),
                options: [.atomic, .completeFileProtection])
        } catch { status = "安装连接配置导入失败，请检查连接设置" }
    }

    private func credentialQuery(for address: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "com.hsin.spatial.bridge",
         kSecAttrAccount as String: address]
    }

    private func credential(for address: String) -> String? {
        var query = credentialQuery(for: address)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let bytes = item as? Data else { return nil }
        return String(data: bytes, encoding: .utf8)
    }

    private func storeCredential(_ token: String, for address: String) throws {
        guard !token.isEmpty else { throw BridgeError.message("请填写访问令牌") }
        let query = credentialQuery(for: address)
        let attributes: [String: Any] = [kSecValueData as String: Data(token.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        var saved = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if saved == errSecItemNotFound {
            saved = SecItemAdd(query.merging(attributes) { _, value in value } as CFDictionary, nil)
        }
        guard saved == errSecSuccess else { throw BridgeError.message("钥匙串保存失败（\(saved)）") }
    }

    func saveConnection() {
        do {
            _ = try endpoint()
            try storeCredential(bridgeToken, for: bridgeURL)
            UserDefaults.standard.set(bridgeURL, forKey: "bridgeURL")
            status = "连接已保存"
        } catch { status = error.localizedDescription }
    }

    func load(into content: RealityViewContent) async {
        modelGeneration += 1
        let requestedGeneration = modelGeneration
        let requestedResource = modelResource
        let directory = resourceDirectory
        modelReady = false
        resetPosture()
        motionRoot = nil
        faces = []
        touchTargets = []
        behaviorResources = nil
        motions.removeAll()
        motionDurations.removeAll()
        guard let url = Bundle.main.url(forResource: selectedCharacter == "hsin" ? "Hsin" : "Aemeath", withExtension: "usdz", subdirectory: directory) else {
            status = "缺少开发模型，请先运行资源准备工具"
            return
        }
        do {
            let loaded = try await Entity(contentsOf: url)
            guard requestedResource == modelResource, requestedGeneration == modelGeneration else { return }
            loaded.scale = SIMD3<Float>(repeating: 0.35)
            loaded.position = SIMD3<Float>(0, -0.53, 0)
            let motionDirectory = directory.map { $0 + "/Motions" } ?? "Motions"
            presentation = CharacterPresentation()
            presentationBaseOrientation = loaded.orientation
            if let envelopeURL = Bundle.main.url(forResource: "posture", withExtension: "json", subdirectory: motionDirectory),
               let envelope = try? JSONDecoder().decode(PostureEnvelope.self, from: Data(contentsOf: envelopeURL)) {
                if envelope.bounds.min.count == 3 && envelope.bounds.max.count == 3 && (envelope.bounds.min + envelope.bounds.max).allSatisfy({ $0.isFinite }) {
                    presentation.minimum = SIMD3<Float>(envelope.bounds.min[0], envelope.bounds.min[1], envelope.bounds.min[2])
                    presentation.maximum = SIMD3<Float>(envelope.bounds.max[0], envelope.bounds.max[1], envelope.bounds.max[2])
                }
            }
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--face-closeup") {
                loaded.scale = SIMD3<Float>(repeating: 1.15)
                loaded.position = SIMD3<Float>(0, -1.65, 0)
            }
            #endif
            character?.removeFromParent()
            content.add(loaded)
            character = loaded
            faces = facialEntities(in: loaded)
            NSLog("[HsinVision] Facial entities %@", faces.map { $0.name }.joined(separator: ","))
            NSLog("[HsinVision] Facial groups %@", faces.flatMap { $0.components[BlendShapeWeightsComponent.self]?.weightSet.map { $0.weightNames.joined(separator: ",") } ?? [] }.joined(separator: " | "))
            // Top-level "global scene animation" is a container animation, not the skinned target.
            // Match the imported bone clip, as the reference's findWaveAnimation does.
            motionRoot = animationBinding(in: loaded, name: "wave")?.entity
            NSLog("[HsinVision] Model animations %@", animationInventory(in: loaded))
            if let manifestURL = Bundle.main.url(forResource: "manifest", withExtension: "json", subdirectory: motionDirectory),
               let manifest = try JSONSerialization.jsonObject(with: Data(contentsOf: manifestURL)) as? [String: [String: Any]] {
                motionDurations = manifest.compactMapValues { $0["duration"] as? Double }
            }
            if let behaviorURL = Bundle.main.url(forResource: "behavior", withExtension: "json", subdirectory: motionDirectory) {
                let resources = try JSONDecoder().decode(SpatialBehaviorResources.self, from: Data(contentsOf: behaviorURL))
                behaviorResources = resources
                for region in resources.touchRegions {
                    let target = Entity()
                    target.name = "HsinTouch_" + region.name
                    target.components.set(CollisionComponent(shapes: [.generateSphere(radius: region.radius)]))
                    target.components.set(InputTargetComponent())
                    target.isEnabled = touchEnabled
                    loaded.addChild(target)
                    touchTargets.append(target)
                }
            }
            for name in motionDurations.keys.sorted() {
                if let clipURL = Bundle.main.url(forResource: name, withExtension: "usdz", subdirectory: motionDirectory) {
                    let clip = try await Entity(contentsOf: clipURL)
                    guard requestedResource == modelResource, requestedGeneration == modelGeneration else { return }
                    NSLog("[HsinVision] %@ animations %@", name, animationInventory(in: clip))
                    motions[name] = animationBinding(in: clip, name: name)?.animation
                }
            }
            NSLog("[HsinVision] Model root %@, motions %@", motionRoot?.name ?? "missing", motions.keys.sorted().joined(separator: ","))
            motionCompletion = content.subscribe(to: AnimationEvents.PlaybackCompleted.self, on: motionRoot) { [weak self] event in
                let completed = event.playbackController
                // Restore after event dispatch; a late event must not interrupt a newer controller.
                Task { @MainActor [weak self] in self?.finishMotion(completed) }
            }
            guard motions["wave"] != nil, playMotion("idle") else {
                status = "骨骼动作未加载，请检查模型与动作资源"
                return
            }
            modelReady = true
            behavior.interact(at: uptime)
            updateTouchTargets()
            status = characterName + "已就位；麦克风关闭"
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--speech-probe") {
                let file = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("SpeechProbe.wav")
                let selectedLanguage = language
                let text = ProcessInfo.processInfo.arguments.contains("--speech-probe-ja") ? "父さん、エイメスはそばにいるよ。" : "父亲，这是外网桥接测试，爱弥斯已经准备好了。"
                speechTask = Task { [weak self] in
                    guard let self else { return }
                    do {
                        let audio = try Data(contentsOf: file)
                        let timeline = await Task.detached { SpeechMouthTimeline(audio: audio, text: text, language: ProcessInfo.processInfo.arguments.contains("--speech-probe-ja") ? "ja" : selectedLanguage) }.value
                        try Task.checkCancellation()
                        mouthTimeline = timeline
                        mouthSmoother.reset()
                        let next = try AVAudioPlayer(data: audio)
                        next.volume = 0
                        next.delegate = self
                        player = next
                        busy = true
                        guard next.play() else { throw BridgeError.message("测试音频未播放") }
                        NSLog("[HsinVision] Speech probe started duration %.3f cues %@", next.duration, Set(timeline.cues).sorted().joined(separator: ","))
                    } catch { status = "测试音频失败" }
                }
            }
            startPostureProbe()
            startInteractionProbe()
            #endif
        } catch { status = "模型加载失败：\(error.localizedDescription)" }
    }

    private func facialEntities(in entity: Entity) -> [Entity] {
        let current = entity.components[BlendShapeWeightsComponent.self] == nil ? [] : [entity]
        return current + entity.children.flatMap { facialEntities(in: $0) }
    }

    private func animationBinding(in entity: Entity, name: String) -> (entity: Entity, animation: AnimationResource)? {
        if let animation = entity.availableAnimations.first(where: {
            ($0.name ?? "").lowercased().contains("/" + name.lowercased())
        }) { return (entity, animation) }
        for child in entity.children {
            if let binding = animationBinding(in: child, name: name) { return binding }
        }
        return nil
    }

    private func animationInventory(in entity: Entity, path: String = "") -> String {
        let currentPath = path + "/" + entity.name
        let names = entity.availableAnimations.map { $0.name ?? "unnamed" }.joined(separator: ",")
        return ([names.isEmpty ? "" : currentPath + ":" + names] + entity.children.map {
            animationInventory(in: $0, path: currentPath)
        }).filter { !$0.isEmpty }.joined(separator: " | ")
    }

    @discardableResult
    private func playMotion(_ requestedName: String) -> Bool {
        let name = requestedName == "idle" && breathing && motions["idle_breathing"] != nil ? "idle_breathing" : requestedName
        guard let root = motionRoot, let animation = motions[name] else {
            status = "动作不可用：\(name)"
            return false
        }
        // Separately imported skeleton clips need the direct handoff used by the reference renderer.
        // Stopping the previous controller after starting the new one can restore the bind pose.
        motionPlayback = root.playAnimation(["idle", "idle_breathing", "side_lying"].contains(name) ? animation.repeat() : animation,
                                             transitionDuration: 0, startsPaused: false)
        activeMotion = name
        NSLog("[HsinVision] Motion playback %@", name)
        return true
    }

    func wave() { gesture("wave", label: "挥手") }

    func gesture(_ name: String, label: String) {
        guard modelReady, motions[name] != nil else { return }
        noteInteraction(wake: false)
        if posture.phase != .standing {
            pendingGesture = (name, label)
            requestPosture(lying: false, preserveGesture: true)
            return
        }
        if activeMotion == "treadmill_running" && name != activeMotion {
            pendingPosture = nil
            pendingGesture = (name, label)
            if !busy && !isListening { status = "跑步结束后" + label }
            return
        }
        guard activeMotion != name, playMotion(name) else { return }
        if !busy && !isListening { status = label + "中" }
    }

    func requestPosture(lying: Bool, preserveGesture: Bool = false) {
        guard modelReady, canChangePosture else { return }
        if !preserveGesture { pendingGesture = nil; behavior.interact(at: uptime) }
        if !isIdle && posture.phase == .standing {
            pendingPosture = lying
            if !busy && !isListening { status = lying ? "当前动作结束后侧躺" : "当前动作结束后保持站立" }
            return
        }
        if let next = posture.request(lying: lying) { _ = playMotion(next) }
        updatePostureStatus()
        #if DEBUG
        writePostureProbeReceipt()
        #endif
    }

    private func finishMotion(_ completed: AnimationPlaybackController) {
        guard completed == motionPlayback, completed.isComplete else { return }
        let finished = activeMotion
        if let next = posture.completed(finished) {
            _ = playMotion(next)
            if next == "idle", let queued = pendingGesture {
                pendingGesture = nil
                gesture(queued.name, label: queued.label)
            } else { updatePostureStatus() }
        } else if posture.phase == .standing, !isIdle {
            _ = playMotion("idle")
            behavior.interact(at: uptime)
            if let destination = pendingPosture {
                pendingPosture = nil
                requestPosture(lying: destination)
            } else if let queued = pendingGesture {
                pendingGesture = nil
                gesture(queued.name, label: queued.label)
            } else if !busy && !isListening { status = "动作完成" }
        }
        NSLog("[HsinVision] Motion completed %@, posture %@, next %@", finished, posture.phase.rawValue, activeMotion)
        #if DEBUG
        writePostureProbeReceipt()
        #endif
    }

    private func updatePostureStatus() {
        guard !busy && !isListening else { return }
        switch posture.phase {
        case .standing: status = "已站立"
        case .lyingDown: status = posture.wantsLying ? "正在躺下" : "躺稳后起身"
        case .sideLying: status = "侧躺休息中"
        case .gettingUp: status = posture.wantsLying ? "站稳后侧躺" : "正在起身"
        }
    }

    private func resetPosture() {
        motionCompletion?.cancel()
        motionCompletion = nil
        motionPlayback = nil
        posture = PostureState()
        activeMotion = "idle"
        pendingGesture = nil
        pendingPosture = nil
        #if DEBUG
        postureProbeTask?.cancel()
        postureProbeTask = nil
        postureProbeHistory = []
        interactionProbeHistory = []
        #endif
    }

    private struct PostureEnvelope: Decodable {
        struct Bounds: Decodable { let min: [Float]; let max: [Float] }
        let floor: Float
        let bounds: Bounds

    }

    #if DEBUG
    private func writePostureProbeReceipt() {
        guard ProcessInfo.processInfo.arguments.contains("--posture-probe") else { return }
        let state = posture.phase.rawValue + ":" + activeMotion
        if postureProbeHistory.last != state { postureProbeHistory.append(state) }
        let receipt: [String: Any] = ["pid": ProcessInfo.processInfo.processIdentifier, "history": postureProbeHistory, "phase": posture.phase.rawValue, "motion": activeMotion,
                                    "wantsLying": posture.wantsLying, "time": motionPlayback?.time ?? 0]
        if let encoded = try? JSONSerialization.data(withJSONObject: receipt) {
            try? encoded.write(to: FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("PostureProbe.json"), options: .atomic)
        }
    }

    private func startInteractionProbe() {
        let arguments = ProcessInfo.processInfo.arguments
        guard arguments.contains("--interaction-probe") else { return }
        setExpression("happy")
        look("look_right")
        if arguments.contains("--interaction-probe-running") {
            gesture("treadmill_running", label: "跑步")
            if let marker = arguments.first(where: { $0.hasPrefix("--interaction-probe-running-phase=") }),
               let fraction = Double(marker.dropFirst("--interaction-probe-running-phase=".count)) {
                postureProbeTask = Task { [weak self] in
                    try? await Task.sleep(for: .milliseconds(300))
                    guard !Task.isCancelled, let self, let playback = self.motionPlayback else { return }
                    playback.pause(); playback.time = playback.duration * min(1, max(0, fraction))
                }
            }
        } else if arguments.contains("--interaction-probe-rest") {
            behavior.interact(at: uptime - 600)
            postureProbeTask = Task { [weak self] in
                while !Task.isCancelled, let self, self.posture.phase != .sideLying {
                    try? await Task.sleep(for: .milliseconds(100))
                }
                guard !Task.isCancelled, let self, let target = self.touchTargets.first else { return }
                self.touch(target)
            }
        }
    }

    private func writeInteractionProbeReceipt() {
        guard ProcessInfo.processInfo.arguments.contains("--interaction-probe") else { return }
        let state = posture.phase.rawValue + ":" + activeMotion
        guard interactionProbeHistory.last != state else { return }
        interactionProbeHistory.append(state)
        let weights = faces.flatMap { $0.components[BlendShapeWeightsComponent.self]?.weightSet.map { entry in
            Dictionary(uniqueKeysWithValues: zip(entry.weightNames, entry.weights))
        } ?? [] }
        let receipt: [String: Any] = ["pid": ProcessInfo.processInfo.processIdentifier, "history": interactionProbeHistory,
            "phase": posture.phase.rawValue, "motion": activeMotion, "faceWeights": weights, "isListening": isListening,
            "touchPositions": touchTargets.map { [$0.position.x, $0.position.y, $0.position.z] }]
        if let encoded = try? JSONSerialization.data(withJSONObject: receipt) {
            try? encoded.write(to: FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("InteractionProbe.json"), options: .atomic)
        }
    }

    private func startPostureProbe() {
        let arguments = ProcessInfo.processInfo.arguments
        if arguments.contains("--motion-smoke-test"), !arguments.contains("--posture-probe") {
            wave()
            let playback = motionPlayback
            postureProbeTask = Task {
                try? await Task.sleep(for: .milliseconds(300))
                guard !Task.isCancelled else { return }
                playback?.pause()
                playback?.time = (motionDurations["wave"] ?? 3) * 0.4
            }
            return
        }
        guard arguments.contains("--posture-probe"), canChangePosture else { return }
        requestPosture(lying: true)
        writePostureProbeReceipt()
        postureProbeTask = Task { [weak self] in
            if let marker = arguments.first(where: { $0.hasPrefix("--posture-probe-phase=") }),
               let phase = Double(marker.dropFirst("--posture-probe-phase=".count)) {
                try? await Task.sleep(for: .milliseconds(300))
                guard !Task.isCancelled, let self else { return }
                self.motionPlayback?.pause()
                self.motionPlayback?.time = (self.motionDurations["lie_down"] ?? 7) * min(0.99, max(0, phase))
                self.writePostureProbeReceipt()
            } else if let command = arguments.first(where: { $0.hasPrefix("--posture-probe-gesture=") }) {
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled else { return }
                let name = String(command.dropFirst("--posture-probe-gesture=".count))
                self?.gesture(name, label: name)
            } else if arguments.contains("--posture-probe-reverse") {
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled else { return }
                self?.requestPosture(lying: false)
            } else if arguments.contains("--posture-probe-roundtrip") || arguments.contains(where: { $0.hasPrefix("--posture-probe-getup-phase=") }) {
                while !Task.isCancelled, let self, self.posture.phase != .sideLying {
                    try? await Task.sleep(for: .milliseconds(100))
                }
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled else { return }
                self?.requestPosture(lying: false)
                if let marker = arguments.first(where: { $0.hasPrefix("--posture-probe-getup-phase=") }),
                   let phase = Double(marker.dropFirst("--posture-probe-getup-phase=".count)) {
                    try? await Task.sleep(for: .milliseconds(300))
                    guard !Task.isCancelled, let self else { return }
                    self.motionPlayback?.pause()
                    self.motionPlayback?.time = (self.motionDurations["get_up"] ?? 7.7) * min(0.99, max(0, phase))
                    self.writePostureProbeReceipt()
                }
            }
        }
    }
    #endif

    func advanceFace() {
        if let playback = motionPlayback, !isIdle, activeMotion != "side_lying", playback.isComplete {
            finishMotion(playback)
        }
        updateTouchTargets()
        updatePresentation()
        care.tick(uptime: uptime, engaged: busy)
        let monotonic = uptime
        if behavior.shouldRest(at: monotonic, enabled: automaticRest, visible: sceneVisible, ready: modelReady && canChangePosture,
                               busy: busy, idle: isIdle, standing: posture.phase == .standing) {
            // A timer requests the transition once; actual animation completion owns its advancement.
            requestPosture(lying: true, preserveGesture: true)
        }
        behavior.tickLook(at: monotonic, enabled: randomLook && canLook, idle: isIdle && !busy && posture.phase == .standing)
        let now = Date()
        if now >= nextBlink && blinkStart == nil { blinkStart = now }
        var blink: Float = 0
        if let start = blinkStart {
            let elapsed = now.timeIntervalSince(start)
            blink = Float(max(0, 1 - abs(elapsed - 0.12) / 0.12))
            if elapsed > 0.24 { blinkStart = nil; nextBlink = now.addingTimeInterval(.random(in: 2...6)) }
        }
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--face-probe-blink") { blink = 1 }
        if ProcessInfo.processInfo.arguments.contains("--face-probe-neutral") { blink = 0 }
        if ProcessInfo.processInfo.arguments.contains("--face-probe-half-blink") { blink = 0.5 }
        #endif
        let elapsed = now.timeIntervalSince(lastFaceUpdate)
        lastFaceUpdate = now
        var target: [String: Float] = [:]
        if let player, player.isPlaying {
            target = mouthTimeline?.weights(at: player.currentTime) ?? [:]
            if mouthTimeline?.levels.isEmpty != false {
                player.updateMeters()
                target = ["a": Float(max(0, min(0.8, (player.averagePower(forChannel: 0) + 48) / 45)))]
            }
        } else { mouthSmoother.reset() }
        var mouthWeights = mouthSmoother.update(target, elapsed: elapsed)
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--speech-probe"), let player, player.isPlaying,
           let dominant = mouthWeights.max(by: { $0.value < $1.value }), dominant.value > 0.01 {
            mouthProbeCounts[dominant.key, default: 0] += 1
        }
        if let argument = ProcessInfo.processInfo.arguments.first(where: { $0.hasPrefix("--face-probe-") }),
           SpeechMouthTimeline.vowels.contains(String(argument.dropFirst("--face-probe-".count))) {
            mouthWeights = [String(argument.dropFirst("--face-probe-".count)): 0.8]
            blink = 0
        }
        #endif
        let chosenExpression = care.mood.autoExpression && uptime >= manualExpressionUntil ? care.mood.expression : expression
        var overlay = behaviorResources?.expressions[chosenExpression] ?? (chosenExpression == "content" ? ["smile": 0.65] : [:])
        if monotonic < behavior.touchUntil {
            for (name, value) in behaviorResources?.expressions[behavior.touchPart == "chest" ? "blush" : "happy"] ?? ["smile": 0.5] {
                overlay[name] = max(overlay[name] ?? 0, value)
            }
        }
        for (name, value) in behavior.gaze { overlay[name] = value }
        for name in Set(faceOverlay.keys).union(overlay.keys) {
            faceOverlay[name, default: 0] += ((overlay[name] ?? 0) - (faceOverlay[name] ?? 0)) * Float(1 - exp(-max(0, min(elapsed, 0.1)) * 10))
        }
        for face in faces {
            guard var component = face.components[BlendShapeWeightsComponent.self] else { continue }
            for entry in component.weightSet {
                var updated = entry
                for (index, name) in entry.weightNames.enumerated() {
                    let manual = faceOverlay[name] ?? 0
                    if name == "blink" {
                        updated.weights[index] = max(manual, (chosenExpression == "wink" ? 0 : blink) * (selectedCharacter == "hsin" ? 1 : 1.12))
                    } else if SpeechMouthTimeline.vowels.contains(name), player != nil {
                        updated.weights[index] = mouthWeights[name] ?? 0
                    } else { updated.weights[index] = max(manual, mouthWeights[name] ?? 0) }
                }
                _ = component.weightSet.set(updated)
            }
            face.components.set(component)
        }
        #if DEBUG
        writeInteractionProbeReceipt()
        #endif
    }

    private func updateHistory(_ operation: (inout ConversationHistory) throws -> Void) {
        do { try operation(&history); conversationMessages = history.messages; historyError = "" }
        catch { conversationMessages = history.messages; historyError = "聊天记录读写失败；当前对话仍可继续" }
    }

    private func selectHistory() {
        guard ["hsin", "aemeath"].contains(selectedCharacter),
              ["default", "deepseek", "openclaw", "hermes", "ollama"].contains(chatProvider) else { return }
        updateHistory { try $0.select(character: selectedCharacter, provider: chatProvider) }
    }

    func setSceneVisible(_ visible: Bool) {
        sceneVisible = visible
        behavior.interact(at: uptime)
        if !visible { stopSpeech() }
    }

    func noteInteraction(wake: Bool = true) {
        behavior.interact(at: uptime)
        if wake, posture.phase != .standing { requestPosture(lying: false) }
    }

    func setExpression(_ name: String) {
        guard availableExpressions.contains(name) else { return }
        noteInteraction(wake: false)
        expression = name
        manualExpressionUntil = uptime + 45
    }

    func look(_ direction: String) {
        guard canLook else { return }
        noteInteraction(wake: false)
        behavior.look(direction, at: uptime)
    }

    func touch(_ entity: Entity) {
        guard touchEnabled, modelReady, entity.name.hasPrefix("HsinTouch_") else { return }
        let part = String(entity.name.dropFirst("HsinTouch_".count))
        let wasResting = behavior.restRequested
        guard behavior.touch(part, at: uptime) else { return }
        care.interact("touch", part: part, uptime: uptime)
        if wasResting { requestPosture(lying: false); return }
        // A touch never forces a manually selected full-body pose to exit.
        guard posture.phase == .standing, !busy, activeMotion != "treadmill_running" else { return }
        let motion = part == "head" ? "finger_heart" : part == "chest" ? "crossed_arms" : part.contains("hand") ? "peace" : "wave"
        gesture(motion, label: "互动")
    }

    private func updateTouchTargets() {
        guard let resources = behaviorResources, let frames = resources.touchFrames[activeMotion], !frames.isEmpty else { return }
        let duration = motionDurations[activeMotion] ?? 0
        let time = max(0, motionPlayback?.time ?? 0)
        let seconds = isIdle || activeMotion == "side_lying" ? (duration > 0 ? time.truncatingRemainder(dividingBy: duration) : 0) : time
        let frame = frames[min(frames.count - 1, Int(seconds * 30))]
        for (target, position) in zip(touchTargets, frame) where position.count == 3 {
            target.position = SIMD3<Float>(position[0], position[1], position[2])
        }
    }

    private func updatePresentation() {
        guard let character, modelReady else { return }
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--face-closeup") { return }
        #endif
        presentation.size = Float(displaySize)
        // Show the full support path during transitions, then restore the chosen close view.
        presentation.mode = posture.phase == .lyingDown || posture.phase == .gettingUp ? "full" :
            (["full", "head_front", "head_left", "head_right"].contains(viewMode) ? viewMode : "full")
        let head = touchTargets.first?.position
        let desired = presentation.pose(head: head)
        let fraction: Float = 0.12
        character.scale += (SIMD3<Float>(repeating: desired.scale) - character.scale) * fraction
        character.position += (desired.position - character.position) * fraction
        character.orientation = simd_slerp(character.orientation, simd_quatf(angle: desired.yaw, axis: SIMD3<Float>(0, 1, 0)) * presentationBaseOrientation, fraction)
    }

    func checkConnections() {
        guard !checkingConnections else { return }
        checkingConnections = true
        connectionDiagnostics = "正在检查连接"
        let pcAddress = bridgeURL, macAddress = gatewayURL, pcToken = bridgeToken, macToken = gatewayToken, role = selectedCharacter
        diagnosticTask = Task { [weak self] in
            guard let self else { return }
            defer { checkingConnections = false; diagnosticTask = nil }
            var lines: [String] = []
            for (label, address, token, service) in [("PC 语音", pcAddress, pcToken, "hsin-pc-voice"), ("Mac 对话", macAddress, macToken, "hsin-vision-gateway")] {
                let started = uptime
                do {
                    guard !token.isEmpty else { throw BridgeError.message("缺少访问令牌") }
                    let base = try endpoint(address, allowLocal: service == "hsin-vision-gateway")
                    var probe = try request(base, path: "health", token: token); probe.timeoutInterval = 8
                    let bytes = try await perform(probe)
                    guard let health = try JSONSerialization.jsonObject(with: bytes) as? [String: Any], health["service"] as? String == service, health["protocol"] as? Int == 1 else { throw BridgeError.message("服务身份或协议不匹配") }
                    if service == "hsin-pc-voice" {
                        guard let voices = health["voices"] as? [String: Any], voices[role] != nil else { throw BridgeError.message("当前角色音色缺失") }
                    }
                    lines.append(String(format: "%@：已连接（%.2f 秒）", label, uptime - started))
                } catch {
                    if let known = error as? BridgeError { lines.append(label + "：" + known.localizedDescription) }
                    else { lines.append(label + "：连接失败或超时") }
                }
            }
            guard pcAddress == bridgeURL, macAddress == gatewayURL, pcToken == bridgeToken, macToken == gatewayToken, role == selectedCharacter else { connectionDiagnostics = "配置已改变，请重新检查"; return }
            connectionDiagnostics = lines.joined(separator: "\n") + "\n连接检查不代表推理或播放已验收"
        }
    }

    private enum BridgeError: LocalizedError {
        case message(String)
        var errorDescription: String? { if case let .message(text) = self { return text }; return nil }
    }
    private struct Health: Decodable {
        struct Voice: Decodable { let fingerprint: String }
        let service: String
        let `protocol`: Int
        let voices: [String: Voice]
    }

    private func endpoint(_ address: String? = nil, allowLocal: Bool = false) throws -> URL {
        let selected = address ?? bridgeURL
        let components = URLComponents(string: selected)
        let octets = components?.host?.split(separator: ".").compactMap { Int($0) } ?? []
        let local = components?.host == "localhost" || (octets.count == 4 && octets.allSatisfy { 0...255 ~= $0 } &&
            (octets[0] == 127 || octets[0] == 10 || (octets[0] == 192 && octets[1] == 168) ||
             (octets[0] == 172 && 16...31 ~= octets[1])))
        guard let components, components.scheme == "https" || (allowLocal && local && components.scheme == "http"),
              components.host != nil, components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil,
              components.path.isEmpty || components.path == "/", let url = components.url else {
            throw BridgeError.message("请填写 HTTPS 域名，不含路径或凭据")
        }
        return url
    }

    private func request(_ base: URL, path: String, token: String, payload: [String: Any]? = nil) throws -> URLRequest {
        var request = URLRequest(url: base.appendingPathComponent(path))
        request.timeoutInterval = 180
        request.setValue("HsinVision/1.0", forHTTPHeaderField: "User-Agent")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let payload {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        }
        return request
    }

    private func perform(_ request: URLRequest) async throws -> Data {
        let (bytes, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw BridgeError.message("桥接请求失败（HTTP \(code)）")
        }
        guard bytes.count <= 24 * 1024 * 1024 else { throw BridgeError.message("音频响应过大") }
        return bytes
    }

    func speakTest() {
        noteInteraction()
        stopSpeech()
        let turn = generation
        let selectedLanguage = language
        let role = selectedCharacter
        let text = role == "hsin"
            ? (selectedLanguage == "zh" ? "御者，心正在空间里陪伴你。" : "御者、心はそばにいるよ。")
            : (selectedLanguage == "zh" ? "父亲，爱弥斯正在空间里陪伴你。" : "父さん、エイメスはそばにいるよ。")
        let token = bridgeToken
        guard !token.isEmpty else { status = "请填写桥接访问令牌"; return }
        busy = true
        status = "正在合成"
        speechTask = Task { [weak self] in
            guard let self else { return }
            do {
                let base = try endpoint()
                let health = try JSONDecoder().decode(Health.self, from: await perform(request(base, path: "health", token: token)))
                guard health.service == "hsin-pc-voice", health.protocol == 1,
                      let voice = health.voices[role] else { throw BridgeError.message("桥接音色或协议不匹配") }
                try Task.checkCancellation()
                let requestID = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
                activeRequest = requestID
                let audio = try await perform(request(base, path: "v1/tts", token: token, payload: [
                    "request_id": requestID, "voice_id": role, "voice_fingerprint": voice.fingerprint,
                    "text": text, "language": selectedLanguage, "speed": 1.0]))
                try Task.checkCancellation()
                guard turn == generation else { return }
                activeRequest = nil
                let timeline = await Task.detached(priority: .userInitiated) {
                    SpeechMouthTimeline(audio: audio, text: text, language: selectedLanguage)
                }.value
                try Task.checkCancellation()
                guard turn == generation else { return }
                let next = try AVAudioPlayer(data: audio)
                next.isMeteringEnabled = true
                next.delegate = self
                guard next.play() else { throw BridgeError.message("音频未能播放") }
                player = next
                mouthTimeline = timeline
                mouthSmoother.reset()
                caption = text
                status = "正在播放"
            } catch {
                guard turn == generation else { return }
                busy = false
                activeRequest = nil
                status = error.localizedDescription
            }
        }
    }


    func saveGatewayConnection() {
        do {
            _ = try endpoint(gatewayURL, allowLocal: true)
            try storeCredential(gatewayToken, for: gatewayURL)
            UserDefaults.standard.set(gatewayURL, forKey: "gatewayURL")
            status = "Mac 网关连接已保存"
        } catch { status = error.localizedDescription }
    }

    private struct GatewayEvent: Decodable {
        let type: String
        let service: String?
        let `protocol`: Int?
        let turn_id: String?
        let index: Int?
        let text: String?
        let reply: String?
        let audio_base64: String?
        let audio_error: String?
        let error: String?
        let recognition_seconds: Double?
    }

    private func connectGateway() async throws {
        try await gatewayInterrupt?.value
        gatewayInterrupt = nil
        if gatewaySocket != nil { return }
        guard !gatewayToken.isEmpty else { throw BridgeError.message("请配置 Mac 对话网关与令牌") }
        let base = try endpoint(gatewayURL, allowLocal: true)
        var components = URLComponents(url: base.appendingPathComponent("ws"), resolvingAgainstBaseURL: false)!
        components.scheme = base.scheme == "https" ? "wss" : "ws"
        var connection = URLRequest(url: components.url!)
        connection.timeoutInterval = 10
        connection.setValue("Bearer \(gatewayToken)", forHTTPHeaderField: "Authorization")
        connection.setValue("HsinVision/1.0", forHTTPHeaderField: "User-Agent")
        let socket = URLSession.shared.webSocketTask(with: connection)
        socket.maximumMessageSize = 24 * 1024 * 1024
        socket.resume()
        do {
            let welcome = try await decodeEvent(socket.receive())
            guard welcome.type == "welcome", welcome.service == "hsin-vision-gateway", welcome.protocol == 1 else {
                throw BridgeError.message("Mac 网关协议不匹配")
            }
            try Task.checkCancellation()
            gatewaySocket = socket
            gatewayReader = Task { [weak self] in
                guard let self else { return }
                do {
                    while !Task.isCancelled {
                        let event = try await decodeEvent(socket.receive())
                        guard gatewaySocket === socket else { return }
                        await applyGatewayEvent(event)
                    }
                } catch {
                    guard gatewaySocket === socket else { return }
                    stopSpeech(disconnect: true)
                    status = "Mac 网关连接中断，请重新连接"
                }
            }
        } catch {
            socket.cancel(with: .goingAway, reason: nil)
            throw error
        }
    }

    private func decodeEvent(_ message: URLSessionWebSocketTask.Message) throws -> GatewayEvent {
        let bytes: Data
        switch message {
        case .data(let content): bytes = content
        case .string(let text): bytes = Data(text.utf8)
        @unknown default: throw BridgeError.message("网关事件无效")
        }
        return try JSONDecoder().decode(GatewayEvent.self, from: bytes)
    }

    func sendText() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !busy, !text.isEmpty, text.count <= 4000 else { return }
        if isListening { recorder.cancel(); isListening = false }
        inputText = ""
        noteInteraction()
        beginConversation(["type": "user_text", "text": text])
    }

    private func beginConversation(_ fields: [String: Any]) {
        guard !busy else { return }
        busy = true
        turnFinished = false
        caption = ""
        fullReply = ""
        transcript = fields["text"] as? String ?? ""
        let turn = generation
        status = fields["type"] as? String == "user_audio" ? "正在识别" : "正在回复"
        speechTask = Task { [weak self] in
            guard let self else { return }
            do {
                try await connectGateway()
                guard turn == generation, let socket = gatewaySocket else { return }
                let identity = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
                gatewayTurn = identity
                updateHistory { try $0.user(self.transcript, turn: identity) }
                var payload = fields.merging(["turn_id": identity, "character_id": selectedCharacter,
                    "language": language, "stt_provider": sttProvider]) { _, value in value }
                if chatProvider != "default" { payload["chat_provider"] = chatProvider }
                let bytes = try JSONSerialization.data(withJSONObject: payload)
                try await socket.send(.string(String(decoding: bytes, as: UTF8.self)))
                armTurnWatchdog(seconds: fields["type"] as? String == "user_audio" ? 105 : 260)
            } catch {
                guard turn == generation else { return }
                stopSpeech()
                status = "无法连接 Mac 网关，请检查地址与令牌"
            }
        }
    }

    private func applyGatewayEvent(_ event: GatewayEvent) async {
        guard event.turn_id == gatewayTurn, gatewayTurn != nil else { return }
        switch event.type {
        case "transcript":
            if let started = recognitionStarted {
                let total = max(0, uptime - started)
                recognitionTiming = String(format: "提交到转写 %.2f 秒", total)
                if let server = event.recognition_seconds { recognitionTiming += String(format: " · 网关识别 %.2f 秒", server) }
                NSLog("[HsinVision] STT completion %.3f seconds, provider %@", total, sttProvider)
                recognitionStarted = nil
            }
            transcript = event.text ?? ""
            if let turn = gatewayTurn { updateHistory { try $0.user(transcript, turn: turn) } }
            noteInteraction()
            status = "正在回复"
            armTurnWatchdog(seconds: 260)
        case "reply_delta":
            fullReply += event.text ?? ""
            if let turn = gatewayTurn { updateHistory { try $0.reply(fullReply, turn: turn, complete: false) } }
        case "sentence_audio":
            if let encoded = event.audio_base64, let audio = Data(base64Encoded: encoded), !audio.isEmpty {
                let text = event.text ?? ""
                let language = self.language
                let timeline = await Task.detached(priority: .userInitiated) {
                    SpeechMouthTimeline(audio: audio, text: text, language: language)
                }.value
                guard event.turn_id == gatewayTurn, gatewayTurn != nil else { return }
                pendingAudio.append(AudioClip(audio: audio, text: text, index: event.index ?? -1, mouth: timeline))
                playNextSentence()
            } else {
                caption = event.text ?? ""
                status = event.audio_error ?? "本句音频无效"
            }
        case "speech_reset":
            pendingAudio.removeAll()
            player?.stop()
            player = nil
            mouthTimeline = nil
            mouthSmoother.reset()
            fullReply = event.reply ?? ""
            caption = fullReply
            if let turn = gatewayTurn { updateHistory { try $0.reply(fullReply, turn: turn, complete: false) } }
        case "turn_done":
            turnWatchdog?.cancel()
            turnWatchdog = nil
            turnFinished = true
            if let turn = gatewayTurn { care.interact("chat", turn: turn, uptime: uptime) }
            fullReply = event.reply ?? fullReply
            if let turn = gatewayTurn { updateHistory { try $0.reply(fullReply, turn: turn, complete: true) } }
            if player == nil && pendingAudio.isEmpty { busy = false; status = "回复完成"; resumeVoiceWhenReady() }
        case "turn_error":
            let message = event.error ?? "对话失败"
            stopSpeech()
            status = message
        default: break
        }
    }

    private func acknowledgePlayback(_ index: Int, discarded: Bool = false) {
        if let socket = gatewaySocket, let identity = gatewayTurn,
           let acknowledgement = try? JSONSerialization.data(withJSONObject: [
                "type": discarded ? "audio_discarded" : "playback_started", "turn_id": identity, "index": index]) {
            Task { try? await socket.send(.string(String(decoding: acknowledgement, as: UTF8.self))) }
        }
    }

    private func armTurnWatchdog(seconds: Double) {
        turnWatchdog?.cancel()
        let identity = gatewayTurn
        let recognition = status == "正在识别"
        turnWatchdog = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(seconds)) } catch { return }
            guard let self, gatewayTurn == identity, !turnFinished else { return }
            stopSpeech()
            status = recognition ? "识别超时，请检查语音服务或切换识别方式" : "回复超时，请检查聊天后端"
        }
    }

    private func playNextSentence() {
        guard player == nil, !pendingAudio.isEmpty else { return }
        let clip = pendingAudio.removeFirst()
        do {
            let next = try AVAudioPlayer(data: clip.audio)
            next.isMeteringEnabled = true
            next.delegate = self
            guard next.play() else { throw BridgeError.message("音频播放失败") }
            player = next
            mouthTimeline = clip.mouth
            mouthSmoother.reset()
            acknowledgePlayback(clip.index)
            caption = clip.text
            status = "正在播放"
        } catch {
            acknowledgePlayback(clip.index, discarded: true)
            status = "本句音频播放失败"
            playNextSentence()
            if player == nil && pendingAudio.isEmpty && turnFinished {
                stopSpeech(); status = "音频播放失败，语音已关闭"
            }
        }
    }

    func toggleRecording() {
        if voiceSessionActive { stopSpeech(); return }
        if isListening { finishRecording(); return }
        guard !busy, recordingTask == nil else { return }
        voiceSessionActive = continuousSpeech
        startRecording()
    }

    private func startRecording() {
        guard !busy, !isListening, recordingTask == nil, sceneVisible else { return }
        noteInteraction()
        let turn = generation
        busy = true
        status = "正在准备麦克风"
        recordingTask = Task { [weak self] in
            guard let self else { return }
            defer { if turn == generation { recordingTask = nil } }
            do {
                try await connectGateway()
                try Task.checkCancellation()
                guard turn == generation else { return }
                try await recorder.start(continuous: voiceSessionActive, pauseSeconds: speechPause)
                // A stale completion must not cancel a newer capture after stop/switch.
                guard turn == generation else { return }
                busy = false
                isListening = true
                transcript = ""
                status = voiceSessionActive ? "语音已开启，等待说话；停顿后自动发送" : "正在收音，再按一次结束（最多 25 秒）"
            } catch {
                guard turn == generation else { return }
                stopSpeech()
                status = "麦克风或网关未就绪，请检查权限与连接"
            }
        }
    }

    private func resumeVoiceWhenReady() {
        guard voiceSessionActive, !busy, player == nil, pendingAudio.isEmpty, turnFinished, sceneVisible else { return }
        resumeListeningTask?.cancel()
        let turn = generation
        // Wait until the actual playback queue is empty and its acoustic tail has faded.
        resumeListeningTask = Task { [weak self] in
            do { try await Task.sleep(for: .milliseconds(350)) } catch { return }
            guard let self, voiceSessionActive, turn == generation, !busy, player == nil,
                  pendingAudio.isEmpty, turnFinished, sceneVisible else { return }
            startRecording()
        }
    }

    func interruptVoiceTurn() {
        guard voiceSessionActive else { stopSpeech(); return }
        stopSpeech(preserveVoiceSession: true)
        resumeVoiceWhenReady()
    }

    private func finishRecording() {
        guard isListening else { return }
        isListening = false
        do {
            let audio = try recorder.finish()
            recognitionStarted = uptime
            recognitionTiming = ""
            beginConversation(["type": "user_audio", "audio_base64": audio.base64EncodedString()])
        } catch { stopSpeech(); status = "未收到有效录音，请检查麦克风" }
    }

    func stopSpeech(disconnect: Bool = false, preserveVoiceSession: Bool = false) {
        if !preserveVoiceSession { voiceSessionActive = false }
        resumeListeningTask?.cancel()
        resumeListeningTask = nil
        updateHistory { try $0.interrupt() }
        generation += 1
        turnWatchdog?.cancel()
        turnWatchdog = nil
        recordingTask?.cancel()
        recordingTask = nil
        recorder.cancel()
        recognitionStarted = nil
        isListening = false
        gatewayTurn = nil
        if disconnect {
            gatewayInterrupt?.cancel()
            gatewayInterrupt = nil
            gatewayReader?.cancel()
            gatewayReader = nil
            gatewaySocket?.cancel(with: .goingAway, reason: nil)
            gatewaySocket = nil
        } else if let socket = gatewaySocket {
            let previous = gatewayInterrupt
            // Preserve character histories while ordering interruption before the next turn.
            gatewayInterrupt = Task {
                try await previous?.value
                try await socket.send(.string("{\"type\":\"interrupt\"}"))
            }
        }
        pendingAudio.removeAll()
        turnFinished = true
        speechTask?.cancel()
        speechTask = nil
        player?.stop()
        player = nil
        mouthTimeline = nil
        mouthSmoother.reset()
        busy = false
        caption = ""
        if let identity = activeRequest, let base = try? endpoint(),
           let cancellation = try? request(base, path: "v1/cancel", token: bridgeToken, payload: ["request_id": identity]) {
            Task { _ = try? await URLSession.shared.data(for: cancellation) }
        }
        activeRequest = nil
        status = modelReady ? "已停止；麦克风关闭" : status
        advanceFace()
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor [weak self] in
            guard let self, self.player === player else { return }
            self.player = nil
            self.mouthTimeline = nil
            self.mouthSmoother.reset()
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--speech-probe") { NSLog("[HsinVision] Speech probe finished success %d mouth reset, counts %@", flag, self.mouthProbeCounts.description) }
            #endif
            if !flag { self.stopSpeech(); self.status = "播放失败，语音已关闭"; return }
            self.playNextSentence()
            if self.player == nil && self.pendingAudio.isEmpty && self.turnFinished {
                self.busy = false
                self.status = flag ? "播放完成" : "播放失败"
                self.resumeVoiceWhenReady()
            }
            self.advanceFace()
        }
    }
}

/// Native format capture stays on the audio thread; only copied samples cross to the main actor.
@MainActor
private final class MicrophoneRecorder {
    private let engine = AVAudioEngine()
    private var capturedSamples: [Float] = []
    private var inputFormat: AVAudioFormat?
    private var captureGeneration = 0
    private var tapInstalled = false
    private var receivedInput = false
    private var deadline: Task<Void, Never>?
    var onLimit: (() -> Void)?
    var onSpeech: (() -> Void)?
    private var activity = SpeechActivity()
    private var continuous = false
    var onFailure: ((String) -> Void)?

    func start(continuous: Bool = false, pauseSeconds: Double = 0.55) async throws {
        cancel()
        self.continuous = continuous
        activity.pauseSeconds = pauseSeconds
        guard await AVAudioApplication.requestRecordPermission() else { throw CaptureError.permission }
        try Task.checkCancellation()
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0, format.commonFormat == .pcmFormatFloat32 else {
            throw CaptureError.format
        }
        inputFormat = format
        let identity = captureGeneration
        input.installTap(onBus: 0, bufferSize: 2048, format: format) { [weak self] buffer, _ in
            guard let channels = buffer.floatChannelData else { return }
            let count = Int(buffer.frameLength)
            let channelCount = Int(buffer.format.channelCount)
            var copied = [Float](repeating: 0, count: count)
            for index in 0..<count {
                for channel in 0..<channelCount { copied[index] += channels[channel][index] / Float(channelCount) }
            }
            Task { @MainActor [weak self] in
                guard let self, self.captureGeneration == identity else { return }
                self.receivedInput = true
                if self.continuous {
                    switch self.activity.consume(copied, sampleRate: format.sampleRate) {
                    case .waiting: break
                    case .began: self.onSpeech?()
                    case .utterance(let samples):
                        self.capturedSamples = samples
                        self.onLimit?()
                    }
                } else {
                    let remaining = max(0, Int(format.sampleRate * 25) - self.capturedSamples.count)
                    self.capturedSamples.append(contentsOf: copied.prefix(remaining))
                    if remaining <= copied.count { self.onLimit?() }
                }
            }
        }
        tapInstalled = true
        do { engine.prepare(); try engine.start() }
        catch { cancel(); throw error }
        deadline = Task { [weak self] in
            try? await Task.sleep(for: .seconds(5))
            guard !Task.isCancelled, let self, self.captureGeneration == identity else { return }
            if !self.receivedInput { self.onFailure?("未收到麦克风输入"); return }
            if self.continuous { return }
            try? await Task.sleep(for: .seconds(20))
            guard !Task.isCancelled, self.captureGeneration == identity else { return }
            self.onLimit?()
        }
    }

    func cancel() {
        captureGeneration += 1
        deadline?.cancel()
        deadline = nil
        engine.stop()
        if tapInstalled { engine.inputNode.removeTap(onBus: 0); tapInstalled = false }
        capturedSamples.removeAll(keepingCapacity: false)
        inputFormat = nil
        receivedInput = false
        activity = SpeechActivity()
        continuous = false
    }

    func finish() throws -> Data {
        let samples = capturedSamples
        let format = inputFormat
        cancel()
        guard let format, !samples.isEmpty,
              let mono = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: format.sampleRate,
                                       channels: 1, interleaved: false),
              let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true),
              let input = AVAudioPCMBuffer(pcmFormat: mono, frameCapacity: AVAudioFrameCount(samples.count)),
              let converter = AVAudioConverter(from: mono, to: target),
              let output = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: 4096) else { throw CaptureError.format }
        input.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBufferPointer { source in
            if let pointer = source.baseAddress { input.floatChannelData![0].update(from: pointer, count: samples.count) }
        }
        var supplied = false
        var pcm = Data()
        // The input-block API drains the resampler; convenience conversion cannot change sample rates.
        while true {
            var conversionError: NSError?
            output.frameLength = 0
            let conversion = converter.convert(to: output, error: &conversionError) { _, state in
                if supplied { state.pointee = .endOfStream; return nil }
                supplied = true
                state.pointee = .haveData
                return input
            }
            guard conversionError == nil else { throw CaptureError.format }
            if output.frameLength > 0, let channel = output.int16ChannelData?[0] {
                pcm.append(Data(bytes: channel, count: Int(output.frameLength) * 2))
            }
            if conversion == .endOfStream { break }
            guard conversion == .haveData else { throw CaptureError.format }
        }
        guard !pcm.isEmpty, pcm.count <= 25 * 16000 * 2 else { throw CaptureError.format }
        var wav = Data("RIFF".utf8)
        func append<T: FixedWidthInteger>(_ value: T) { withUnsafeBytes(of: value.littleEndian) { wav.append(contentsOf: $0) } }
        append(UInt32(36 + pcm.count)); wav.append(Data("WAVEfmt ".utf8))
        append(UInt32(16)); append(UInt16(1)); append(UInt16(1)); append(UInt32(16000))
        append(UInt32(32000)); append(UInt16(2)); append(UInt16(16)); wav.append(Data("data".utf8))
        append(UInt32(pcm.count)); wav.append(pcm)
        return wav
    }

    private enum CaptureError: Error { case permission, format }
}
