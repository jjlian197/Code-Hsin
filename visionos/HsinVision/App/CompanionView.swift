import Combine
import RealityKit
import SwiftUI

struct CompanionView: View {
    @EnvironmentObject private var companion: CompanionStore
    @Environment(\.scenePhase) private var scenePhase
    @State private var showConnection = false
    @State private var showChat = false
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
                if showConnection { connectionPanel }
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
                if companion.selectedCharacter == "hsin" {
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
            Button(companion.busy ? "打断" : companion.isListening ? "结束说话" : "和\(companion.characterName)说话",
                   systemImage: companion.busy ? "hand.raised.fill" : companion.isListening ? "stop.fill" : "mic.fill") {
                companion.noteInteraction()
                if companion.busy { companion.stopSpeech() }
                else { companion.toggleRecording() }
            }
            Button("聊天", systemImage: "text.bubble") { companion.noteInteraction(); showChat.toggle() }
            Button("设置", systemImage: "gearshape") { companion.noteInteraction(wake: false); showConnection.toggle() }
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
                    .labelStyle(.iconOnly).disabled(companion.busy || companion.isListening)
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
            Picker("识别方式", selection: $companion.sttProvider) {
                Text("PC 桥接").tag("remote")
                Text("智谱").tag("zhipu")
            }.pickerStyle(.segmented)
            HStack {
                Picker("语言", selection: $companion.language) {
                    Text("中文").tag("zh")
                    Text("日本語").tag("ja")
                }
                Button("测试音色") { companion.speakTest() }.disabled(companion.busy || companion.isListening)
            }
            DisclosureGroup("互动设置") {
                Toggle("待机呼吸", isOn: $companion.breathing).disabled(companion.selectedCharacter != "hsin")
                Toggle("随机环顾", isOn: $companion.randomLook).disabled(!companion.canLook)
                Toggle("触摸反馈", isOn: $companion.touchEnabled).disabled(companion.selectedCharacter != "hsin")
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
                Text("HTTP 仅用于可信局域网，跨网请使用 HTTPS。")
                    .font(.caption2).foregroundStyle(.secondary)
            }
        }.frame(width: 400)
    }
}
