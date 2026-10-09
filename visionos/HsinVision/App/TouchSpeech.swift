import Foundation
import CryptoKit

/// Fixed responses keep character identity separate from conversation history.
enum TouchSpeech {
    static func phrase(role: String, language: String, part: String) -> String? {
        let region = part.contains("hand") ? "hand" : part
        let regions = ["head", "hand", "chest", "body"]
        guard let index = regions.firstIndex(of: region) else { return nil }
        switch (role, language) {
        case ("hsin", "zh"): return ["嗯？御者，怎么啦？", "走吧，陪你逛逛。", "御者，这里可不行喔。", "御者，我在听。"][index]
        case ("hsin", "ja"): return ["あら、御者。どうしたの？", "行きましょう、御者。", "御者、そこはだめよ。", "御者、聞いているわ。"][index]
        case ("aemeath", "zh"): return ["父亲，怎么啦？", "父亲，陪我一起走吧。", "父亲，请温柔一点。", "父亲，我在这里陪着你。"][index]
        case ("aemeath", "ja"): return ["父さん、どうしたの？", "父さん、一緒に歩こう。", "父さん、優しくしてね。", "父さん、そばにいるよ。"][index]
        default: return nil
        }
    }

    static func eligible(enabled: Bool, visible: Bool, busy: Bool, listening: Bool,
                         voiceSession: Bool, playing: Bool, queued: Bool, now: Double, last: Double) -> Bool {
        enabled && visible && !busy && !listening && !voiceSession && !playing && !queued && now - last >= 3
    }

    // Length-prefixed JSON fields avoid ambiguous keys; fingerprints invalidate changed PC voices.
    static func cacheKey(endpoint: String, role: String, language: String, fingerprint: String, text: String) -> String {
        let encoded = try! JSONEncoder().encode([endpoint, role, language, fingerprint, text, "1.0"])
        return SHA256.hash(data: encoded).map { String(format: "%02x", $0) }.joined()
    }

    static func cacheURL(key: String) throws -> URL {
        let directory = try FileManager.default.url(for: .cachesDirectory, in: .userDomainMask,
                                                    appropriateFor: nil, create: true).appendingPathComponent("TouchSpeech", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory.appendingPathComponent(key).appendingPathExtension("wav")
    }
}
