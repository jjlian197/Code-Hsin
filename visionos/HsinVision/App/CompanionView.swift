import Combine
import RealityKit
import SwiftUI

struct CompanionView: View {
    @EnvironmentObject private var companion: CompanionStore
    @State private var showConnection = false
    @State private var showChat = false
    private let animationClock = Timer.publish(every: 1.0 / 30, on: .main, in: .common).autoconnect()

    var body: some View {
        RealityView { content in
            await companion.load(into: content)
        }
        .id(companion.modelResource)
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
        .onDisappear { companion.stopSpeech() }
    }

    private var controlBar: some View {
        HStack(spacing: 10) {
            Button("挥手", systemImage: "hand.wave") { companion.wave() }
                .disabled(!companion.modelReady)
            if companion.selectedCharacter == "hsin" {
                Menu("动作", systemImage: "figure.wave") {
                    Button("点头") { companion.gesture("nod", label: "点头") }
                    Button("比耶") { companion.gesture("peace", label: "比耶") }
                    Button("比心") { companion.gesture("finger_heart", label: "比心") }
                    Button("双臂交叉") { companion.gesture("crossed_arms", label: "双臂交叉") }
                }.disabled(!companion.modelReady)
            }
            Button(companion.busy ? "打断" : companion.isListening ? "结束说话" : "和\(companion.characterName)说话",
                   systemImage: companion.busy ? "hand.raised.fill" : companion.isListening ? "stop.fill" : "mic.fill") {
                if companion.busy { companion.stopSpeech() }
                else { companion.toggleRecording() }
            }
            Button("聊天", systemImage: "text.bubble") { showChat.toggle() }
            Button("设置", systemImage: "gearshape") { showConnection.toggle() }
        }
    }

    private var chatPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !companion.fullReply.isEmpty {
                ScrollView { Text(companion.fullReply).textSelection(.enabled) }
                    .frame(maxHeight: 220)
            }
            HStack {
                TextField("输入对话", text: $companion.inputText).onSubmit { companion.sendText() }
                Button("发送", systemImage: "arrow.up") { companion.sendText() }
                    .labelStyle(.iconOnly).disabled(companion.busy || companion.isListening)
            }
        }
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
