import Foundation

@main
struct SpeechMouthChecks {
    static func wav(_ levels: [Int16]) -> Data {
        var bytes = Data()
        func word(_ number: UInt32, count: Int) {
            for index in 0..<count { bytes.append(UInt8(truncatingIfNeeded: number >> (8 * index))) }
        }
        func tag(_ value: String) { bytes.append(contentsOf: value.utf8) }
        let length = levels.count * 320 * 2
        tag("RIFF"); word(UInt32(length + 36), count: 4); tag("WAVE")
        tag("fmt "); word(16, count: 4); word(1, count: 2); word(1, count: 2)
        word(16_000, count: 4); word(32_000, count: 4); word(2, count: 2); word(16, count: 2)
        tag("data"); word(UInt32(length), count: 4)
        for level in levels { for _ in 0..<320 { word(UInt32(UInt16(bitPattern: level)), count: 2) } }
        return bytes
    }

    static func main() throws {
        let frames: [Int16] = [0, 0, 4000, 4000, 0, 4000, 4000, 4000, 0, 0]
        let timeline = SpeechMouthTimeline(audio: wav(frames), text: "あいうえお", language: "ja")
        precondition(timeline.cues.filter { !$0.isEmpty } == ["a", "i", "u", "e", "o"])
        precondition(timeline.weights(at: 0.001).isEmpty && timeline.weights(at: 0.085).isEmpty)
        precondition(timeline.weights(at: timeline.duration).isEmpty)
        precondition(SpeechMouthTimeline.vowelCues("阿姨五个哦", language: "zh") == ["a", "i", "u", "e", "o"])
        precondition(SpeechMouthTimeline(audio: Data([1, 2]), text: "a", language: "zh").levels.isEmpty)
        precondition(SpeechMouthTimeline(audio: wav([0, 0, 0]), text: "a", language: "zh").cues.allSatisfy { $0.isEmpty })
        var smoother = SpeechMouthSmoother()
        let first = smoother.update(["a": 0.8], elapsed: 1.0 / 30)
        precondition(first["a"]! > 0 && first["a"]! < 0.8)
        for _ in 0..<20 { _ = smoother.update([:], elapsed: 1.0 / 30) }
        precondition(smoother.weights.values.allSatisfy { $0 == 0 })
        smoother.reset(); precondition(smoother.weights.isEmpty)
        var realReports: [[String: Any]] = []
        for (path, text, language) in [
            (".runtime/public-bridge-validation/aemeath-zh.wav", "父亲，这是外网桥接测试，爱弥斯已经准备好了。", "zh"),
            (".runtime/public-bridge-validation/aemeath-ja.wav", "父さん、エイメスはそばにいるよ。", "ja")
        ] {
            if FileManager.default.fileExists(atPath: path) {
                let speech = SpeechMouthTimeline(audio: try Data(contentsOf: URL(fileURLWithPath: path)), text: text, language: language)
                precondition(speech.duration > 1 && speech.levels.contains { $0 > 0 })
                let used = Set(speech.cues.filter { !$0.isEmpty }).sorted()
                precondition(used.count >= 3)
                realReports.append(["language": language, "duration": speech.duration, "mouths": used])
            }
        }
        print(String(decoding: try JSONSerialization.data(withJSONObject: ["checks_passed": true, "real_wav": realReports], options: [.prettyPrinted]), as: UTF8.self))
    }
}
