import Foundation

/// Display history is separate from Agent-owned context: never replay this file to a backend.
struct ConversationMessage: Codable, Identifiable, Equatable {
    enum State: String, Codable { case streaming, complete, interrupted }
    let id: String
    let role: String
    var text: String
    var state: State
}

struct ConversationHistory {
    private(set) var messages: [ConversationMessage] = []
    let directory: URL
    private(set) var context = ""
    private var file: URL { directory.appendingPathComponent(context + ".json") }

    mutating func select(character: String, provider: String) throws {
        var previousSaveFailure: Error?
        do { try interrupt() } catch { previousSaveFailure = error }
        // Switch the visible context even if saving the previous context failed.
        // Otherwise an I/O error could display another character's conversation.
        // Role/backend keys come from validated selections, never from user text or URLs.
        context = character + "-" + provider
        messages = []
        if FileManager.default.fileExists(atPath: file.path) {
            messages = try JSONDecoder().decode([ConversationMessage].self, from: Data(contentsOf: file))
            messages = messages.map { message in
                var recovered = message
                if recovered.state == .streaming { recovered.state = .interrupted }
                return recovered
            }
        }
        if let previousSaveFailure { throw previousSaveFailure }
    }

    mutating func user(_ text: String, turn: String) throws {
        guard !text.isEmpty, !messages.contains(where: { $0.id == turn + ":user" }) else { return }
        messages.append(.init(id: turn + ":user", role: "user", text: text, state: .complete))
        try save()
    }

    mutating func reply(_ text: String, turn: String, complete: Bool) throws {
        guard !text.isEmpty else { return }
        let identity = turn + ":assistant"
        if let index = messages.firstIndex(where: { $0.id == identity }) {
            messages[index].text = text
            messages[index].state = complete ? .complete : .streaming
        } else {
            messages.append(.init(id: identity, role: "assistant", text: text,
                                  state: complete ? .complete : .streaming))
        }
        // Stream deltas stay in memory; completion, cancellation and scene exit persist once.
        if complete { try save() }
    }

    mutating func interrupt() throws {
        guard messages.contains(where: { $0.state == .streaming }) else { return }
        for index in messages.indices where messages[index].state == .streaming {
            messages[index].state = .interrupted
        }
        try save()
    }

    private mutating func save() throws {
        guard !context.isEmpty else { return }
        messages = Array(messages.suffix(500))
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var options: Data.WritingOptions = [.atomic]
        #if os(visionOS) || os(iOS)
        options.insert(.completeFileProtection)
        #endif
        try JSONEncoder().encode(messages).write(to: file, options: options)
    }
}
