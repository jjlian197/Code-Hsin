import Foundation

@main
struct TouchSpeechChecks {
    static func main() throws {
        for role in ["hsin", "aemeath"] {
            for language in ["zh", "ja"] {
                for part in ["head", "left_hand", "right_hand", "chest", "body"] {
                    precondition(TouchSpeech.phrase(role: role, language: language, part: part) != nil)
                }
            }
        }
        precondition(TouchSpeech.phrase(role: "other", language: "zh", part: "body") == nil)
        precondition(TouchSpeech.phrase(role: "hsin", language: "zh", part: "unknown") == nil)
        func eligible(_ enabled: Bool = true, _ visible: Bool = true, _ busy: Bool = false,
                      _ listening: Bool = false, _ voiceSession: Bool = false, _ playing: Bool = false,
                      _ queued: Bool = false, _ now: Double = 10) -> Bool {
            TouchSpeech.eligible(enabled: enabled, visible: visible, busy: busy, listening: listening,
                                 voiceSession: voiceSession, playing: playing, queued: queued, now: now, last: 7)
        }
        precondition(eligible())
        precondition(!eligible(false) && !eligible(true, false) && !eligible(true, true, true))
        precondition(!eligible(true, true, false, true) && !eligible(true, true, false, false, true))
        precondition(!eligible(true, true, false, false, false, true))
        precondition(!eligible(true, true, false, false, false, false, true))
        precondition(!eligible(true, true, false, false, false, false, false, 9.99))
        let keys = [
            TouchSpeech.cacheKey(endpoint: "https://example.org", role: "hsin", language: "zh", fingerprint: "v1", text: "你好"),
            TouchSpeech.cacheKey(endpoint: "https://example.org", role: "aemeath", language: "zh", fingerprint: "v1", text: "你好"),
            TouchSpeech.cacheKey(endpoint: "https://example.org", role: "hsin", language: "ja", fingerprint: "v1", text: "你好"),
            TouchSpeech.cacheKey(endpoint: "https://example.org", role: "hsin", language: "zh", fingerprint: "v2", text: "你好"),
            TouchSpeech.cacheKey(endpoint: "https://other.org", role: "hsin", language: "zh", fingerprint: "v1", text: "你好")]
        precondition(Set(keys).count == keys.count)
        print("Touch speech: roles, languages, regions, suppression, cooldown and cache isolation passed")
    }
}
