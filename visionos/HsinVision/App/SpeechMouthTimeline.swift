import Foundation

/// Text supplies approximate vowel cues; decoded PCM gates them and preserves pauses.
/// This is not forced phoneme alignment. Sampling uses the actual player's clock.
struct SpeechMouthTimeline: Sendable {
    static let vowels = ["a", "i", "u", "e", "o"]
    let frameSeconds: Double
    let levels: [Float]
    let cues: [String]
    let duration: Double

    init(audio: Data, text: String, language: String) {
        let envelope = Self.envelope(audio)
        frameSeconds = envelope.step
        levels = envelope.levels
        duration = envelope.duration
        let syllables = Self.vowelCues(text, language: language)
        let voicedFrames = levels.filter { $0 > 0 }.count
        var voicedIndex = 0
        cues = levels.map { level in
            guard level > 0, voicedFrames > 0 else { return "" }
            let index = min(syllables.count - 1, voicedIndex * syllables.count / voicedFrames)
            voicedIndex += 1
            return syllables[index]
        }
    }

    func weights(at seconds: Double) -> [String: Float] {
        guard seconds >= 0, seconds < duration, !levels.isEmpty else { return [:] }
        let frame = min(levels.count - 1, Int(seconds / frameSeconds))
        guard levels[frame] > 0, !cues[frame].isEmpty else { return [:] }
        return [cues[frame]: levels[frame] * 0.8]
    }

    static func vowelCues(_ text: String, language: String) -> [String] {
        let transform: StringTransform = language == "ja" ? .toLatin : .mandarinToLatin
        let latin = (text.applyingTransform(transform, reverse: false) ?? text)
            .folding(options: .diacriticInsensitive, locale: Locale(identifier: language)).lowercased()
        let cues: [String]
        if language == "ja" {
            cues = latin.compactMap { vowels.contains(String($0)) ? String($0) : nil }
        } else {
            cues = latin.split(whereSeparator: { !$0.isLetter }).compactMap { syllable in
                ["a", "o", "e", "i", "u"].first { syllable.contains($0) }
            }
        }
        return cues.isEmpty ? ["a"] : cues
    }

    private static func envelope(_ audio: Data) -> (step: Double, levels: [Float], duration: Double) {
        let empty = (step: 0.02, levels: [Float](), duration: 0.0)
        return audio.withUnsafeBytes { bytes in
            func integer(_ offset: Int, _ count: Int) -> UInt32 {
                guard offset >= 0, offset + count <= bytes.count else { return 0 }
                return (0..<count).reduce(UInt32(0)) { $0 | UInt32(bytes[offset + $1]) << (8 * $1) }
            }
            func tag(_ offset: Int) -> String {
                guard offset + 4 <= bytes.count else { return "" }
                return String(bytes: bytes[offset..<(offset + 4)], encoding: .ascii) ?? ""
            }
            guard bytes.count >= 12, tag(0) == "RIFF", tag(8) == "WAVE" else { return empty }
            var cursor = 12
            var format = 0, channels = 0, sampleRate = 0, bits = 0, blockAlign = 0
            var samplesOffset = 0, samplesLength = 0
            while cursor + 8 <= bytes.count {
                let length = Int(integer(cursor + 4, 4))
                let body = cursor + 8
                guard length <= bytes.count - body else { return empty }
                if tag(cursor) == "fmt ", length >= 16 {
                    format = Int(integer(body, 2)); channels = Int(integer(body + 2, 2))
                    sampleRate = Int(integer(body + 4, 4)); blockAlign = Int(integer(body + 12, 2))
                    bits = Int(integer(body + 14, 2))
                } else if tag(cursor) == "data" {
                    samplesOffset = body; samplesLength = length
                }
                cursor = body + length + (length % 2)
            }
            guard (1...8).contains(channels), (8_000...96_000).contains(sampleRate),
                  (format == 1 && [16, 24, 32].contains(bits) || format == 3 && bits == 32),
                  blockAlign == channels * bits / 8, samplesLength > 0 else { return empty }
            let totalFrames = samplesLength / blockAlign
            let frameSamples = max(1, Int(Double(sampleRate) * 0.02))
            var levels: [Float] = []
            for start in stride(from: 0, to: totalFrames, by: frameSamples) {
                let end = min(totalFrames, start + frameSamples)
                var energy: Double = 0
                for frame in start..<end {
                    for channel in 0..<channels {
                        let offset = samplesOffset + frame * blockAlign + channel * bits / 8
                        let encoded = integer(offset, bits / 8)
                        let sample: Double
                        if format == 3 {
                            let value = Float(bitPattern: encoded)
                            sample = value.isFinite ? Double(max(-1, min(1, value))) : 0
                        } else {
                            let shift = 32 - bits
                            sample = Double(Int32(bitPattern: encoded << shift)) / 2_147_483_648
                        }
                        energy += sample * sample
                    }
                }
                let rms = sqrt(energy / Double((end - start) * channels))
                // Preserve the desktop PCM noise floor and gentle gain, avoiding always-open lips.
                levels.append(Float(min(1, max(0, (rms - 0.008) * 7))))
            }
            return (Double(frameSamples) / Double(sampleRate), levels, Double(totalFrames) / Double(sampleRate))
        }
    }
}

struct SpeechMouthSmoother {
    private(set) var weights: [String: Float] = [:]

    mutating func update(_ target: [String: Float], elapsed: Double) -> [String: Float] {
        for vowel in SpeechMouthTimeline.vowels {
            let previous = weights[vowel] ?? 0
            let next = target[vowel] ?? 0
            let timeConstant = next > previous ? 0.055 : 0.075
            let blend = Float(1 - exp(-min(0.1, max(0, elapsed)) / timeConstant))
            let value = previous + (next - previous) * blend
            weights[vowel] = value < 0.001 ? 0 : value
        }
        return weights
    }

    mutating func reset() { weights = [:] }
}
