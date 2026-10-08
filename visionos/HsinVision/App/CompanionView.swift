import Combine
import RealityKit
import SwiftUI

struct CompanionView: View {
    @EnvironmentObject private var companion: CompanionStore
    @Environment(\.scenePhase) private var scenePhase
    @State private var showConnection = false
    @State private var showChat = false
    #if DEBUG
    @State private var showCare = ProcessInfo.processInfo.arguments.contains("--care-panel-probe")
    #else
    @State private var showCare = false
    #endif
    private let animationClock = Timer.publish(every: 1.0 / 30, on: .main, in: .common).autoconnect()

    var body: some View {
        RealityView { content in
            await companion.load(into: content)
        }
        .id(companion.modelResource)
        .gesture(SpatialTapGesture().targetedToAnyEntity().onEnded { hit in companion.touch(hit.entity) })
        .ornament(attachmentAnchor: .scene(.trailing)) {
            if !companion.caption.isEmpty || showChat {
                VStack(alignment: .leading, spacing: 10) {
                    Text(companion.characterName).font(.caption).foregroundStyle(.secondary)
                    if !companion.caption.isEmpty { Text(companion.caption).lineLimit(5) }
                    if showChat { chatPanel }
                }
                .padding(14).frame(width: 320, alignment: .leading).glassBackgroundEffect()
            }
        }
        .ornament(attachmentAnchor: .scene(.bottom)) {
            VStack(spacing: 8) {
                controlBar
                if showConnection { ScrollView { connectionPanel }.frame(maxHeight: 360) }
                CompanionCareView(care: companion.care, expanded: showCare)
                if !companion.transcript.isEmpty {
                    Text("你：\(companion.transcript)").font(.caption).lineLimit(2)
                }
                Text(companion.status).font(.caption2).foregroundStyle(.secondary)
            }
            .padding(12).glassBackgroundEffect()
        }
        .onReceive(animationClock) { _ in companion.advanceFace() }
        .onAppear { companion.setSceneVisible(scenePhase == .active) }
        .onChange(of: scenePhase) { _, phase in companion.setSceneVisible(phase == .active) }
        .onChange(of: companion.inputText) { _, _ in companion.noteInteraction() }
        .onDisappear { companion.setSceneVisible(false) }
    }

    private var controlBar: some View {
        HStack(spacing: 10) {
            Button("挥手", systemImage: "hand.wave") { companion.wave() }
                .disabled(!companion.modelReady)
            Menu("互动", systemImage: "figure.wave") {
                if companion.modelReady {
                    Button("点头") { companion.gesture("nod", label: "点头") }
                    Button("比耶") { companion.gesture("peace", label: "比耶") }
                    Button("比心") { companion.gesture("finger_heart", label: "比心") }
                    Button("双臂交叉") { companion.gesture("crossed_arms", label: "双臂交叉") }
                    Button("跑步（半速）") { companion.gesture("treadmill_running", label: "跑步") }
                        .disabled(!companion.canRun)
                    Button(companion.wantsLying ? "站起来" : "侧躺休息") {
                        companion.requestPosture(lying: !companion.wantsLying)
                    }.disabled(!companion.canChangePosture)
                    Divider()
                }
                Menu("表情") {
                    ForEach(companion.availableExpressions, id: \.self) { name in
                        Button(expressionLabel(name)) { companion.setExpression(name) }
                    }
                }
                if companion.canLook {
                    Menu("视线") {
                        Button("向左看") { companion.look("look_left") }
                        Button("向右看") { companion.look("look_right") }
                        Button("向上看") { companion.look("look_up") }
                        Button("向下看") { companion.look("look_down") }
                        Button("回正") { companion.look("center") }
                    }
                }
            }.disabled(!companion.modelReady)
            Button(companion.voiceControlLabel, systemImage: companion.voiceControlIcon) {
                companion.noteInteraction()
                if companion.voiceSessionActive { companion.stopSpeech() }
                else if companion.busy { companion.stopSpeech() }
                else { companion.toggleRecording() }
            }
            if companion.voiceSessionActive && companion.busy {
                Button("打断回复", systemImage: "hand.raised") { companion.interruptVoiceTurn() }
            }
            Button("聊天", systemImage: "text.bubble") { companion.noteInteraction(); showChat.toggle() }
            Button("陪伴", systemImage: "heart") { companion.noteInteraction(wake: false); showCare.toggle(); if showCare { showConnection = false } }
            Button("设置", systemImage: "gearshape") { companion.noteInteraction(wake: false); showConnection.toggle(); if showConnection { showCare = false } }
        }
    }

    private var chatPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !companion.historyError.isEmpty { Text(companion.historyError).font(.caption2).foregroundStyle(.secondary) }
            ScrollViewReader { scroll in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        ForEach(companion.conversationMessages) { message in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(message.role == "user" ? "你" : companion.characterName)
                                    .font(.caption).foregroundStyle(.secondary)
                                Text(message.text).textSelection(.enabled)
                                if message.state == .interrupted {
                                    Text("已中断").font(.caption2).foregroundStyle(.secondary)
                                }
                            }.id(message.id)
                        }
                    }
                }.frame(maxHeight: 220)
                .onChange(of: companion.conversationMessages) { _, messages in
                    if let last = messages.last { scroll.scrollTo(last.id, anchor: .bottom) }
                }
            }
            HStack {
                TextField("输入对话", text: $companion.inputText).onSubmit { companion.sendText() }
                Button("发送", systemImage: "arrow.up") { companion.sendText() }
                    .labelStyle(.iconOnly).disabled(companion.busy)
            }
        }
    }

    private func expressionLabel(_ name: String) -> String {
        ["normal": "自然", "happy": "开心", "sad": "难过", "angry": "生气", "surprised": "惊讶",
         "wink": "眨单眼", "sleepy": "困倦", "relaxed": "放松", "blush": "害羞",
         "content": "微笑", "star_eyes": "星星眼", "heart_eyes": "爱心眼"][name] ?? name
    }

    private var connectionPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            Picker("角色", selection: $companion.selectedCharacter) {
                Text("心").tag("hsin")
                Text("爱弥斯").tag("aemeath")
            }.pickerStyle(.segmented)
            if companion.selectedCharacter == "hsin" {
                Picker("形态", selection: $companion.selectedForm) {
                    Text("一阶段").tag("first")
                    Text("二阶段").tag("second")
                }.pickerStyle(.segmented)
            }
            Picker("聊天后端", selection: $companion.chatProvider) {
                Text(companion.selectedCharacter == "hsin" ? "角色默认 · PC Hermes" : "角色默认 · OpenClaw").tag("default")
                Text("DeepSeek").tag("deepseek")
                Text("OpenClaw").tag("openclaw")
                Text("Hermes").tag("hermes")
                Text("Ollama").tag("ollama")
            }
            Toggle("持续语音（停顿后自动发送）", isOn: $companion.continuousSpeech)
            Text("开启一次麦克风，停顿后发送；回复播放结束再继续收音。")
                .font(.caption2).foregroundStyle(.secondary)
            Picker("断句停顿", selection: $companion.speechPause) {
                Text("快速 · 0.45 秒").tag(0.45)
                Text("标准 · 0.55 秒").tag(0.55)
                Text("宽松 · 0.8 秒").tag(0.8)
            }
            Picker("识别方式", selection: $companion.sttProvider) {
                Text("PC 桥接").tag("remote")
                Text("智谱").tag("zhipu")
            }.pickerStyle(.segmented)
            HStack {
                Picker("语言", selection: $companion.language) {
                    Text("中文").tag("zh")
                    Text("日本語").tag("ja")
                }
                Button("测试音色") { companion.speakTest() }.disabled(companion.busy)
            }
            DisclosureGroup("显示设置") {
                Picker("角色大小", selection: $companion.displaySize) {
                    Text("80%").tag(0.8); Text("100%").tag(1.0); Text("125%").tag(1.25)
                }
                Picker("取景", selection: $companion.viewMode) {
                    Text("全身").tag("full"); Text("近景正面").tag("head_front")
                    Text("近景左侧").tag("head_left"); Text("近景右侧").tag("head_right")
                }
            }
            DisclosureGroup("互动设置") {
                Toggle("待机呼吸", isOn: $companion.breathing)
                Toggle("随机环顾", isOn: $companion.randomLook).disabled(!companion.canLook)
                Toggle("触摸反馈", isOn: $companion.touchEnabled)
                Toggle("闲置十分钟后休息", isOn: $companion.automaticRest).disabled(!companion.canChangePosture)
            }
            DisclosureGroup("连接详情") {
                TextField("PC HTTPS 地址", text: $companion.bridgeURL)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                SecureField("PC 访问令牌", text: $companion.bridgeToken)
                Button("保存 PC 连接") { companion.saveConnection() }
                TextField("Mac 对话网关地址", text: $companion.gatewayURL)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                SecureField("Mac 访问令牌", text: $companion.gatewayToken)
                Button("保存 Mac 连接") { companion.saveGatewayConnection() }
                Button(companion.checkingConnections ? "正在检查连接…" : "检查连接") { companion.checkConnections() }
                    .disabled(companion.checkingConnections)
                if !companion.connectionDiagnostics.isEmpty { Text(companion.connectionDiagnostics).font(.caption2) }
                if !companion.recognitionTiming.isEmpty { Text(companion.recognitionTiming).font(.caption2) }
                Text("HTTP 仅用于可信局域网，跨网请使用 HTTPS。")
                    .font(.caption2).foregroundStyle(.secondary)
            }
        }.frame(width: 400)
    }
}
