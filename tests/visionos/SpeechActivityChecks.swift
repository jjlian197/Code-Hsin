import Foundation

@main
struct SpeechActivityChecks {
    static func main() {
        for rate in [16000.0, 44100.0, 48000.0] {
            var activity = SpeechActivity()
            let frameCount = Int(rate * 0.02)
            func feed(_ amplitude: Float, frames: Int) -> [[Float]] {
                var clips: [[Float]] = []
                for _ in 0..<frames {
                    let samples = (0..<frameCount).map { index in amplitude * sin(Float(index) * 0.15) }
                    if case .utterance(let clip) = activity.consume(samples, sampleRate: rate) { clips.append(clip) }
                }
                return clips
            }
            precondition(feed(0.0004, frames: 150).isEmpty)
            precondition(feed(0.08, frames: 2).isEmpty) // brief click
            precondition(feed(0, frames: 50).isEmpty)
            precondition(feed(0.04, frames: 11).isEmpty) // short spoken answer
            let first = feed(0, frames: 45)
            precondition(first.count == 1 && !activity.speaking)
            precondition(Double(first[0].count) / rate < 1.4)
            precondition(feed(0.04, frames: 25).isEmpty)
            precondition(feed(0, frames: 20).isEmpty) // short pause stays inside same phrase
            precondition(feed(0.04, frames: 25).isEmpty)
            precondition(feed(0, frames: 45).count == 1)
            precondition(feed(0.04, frames: 1001).count == 1) // maximum utterance bound
        }
        var activity = SpeechActivity()
        _ = activity.consume([.nan, .infinity, -.infinity], sampleRate: 16000)
        _ = activity.consume([0], sampleRate: .nan)
        var emitted = false
        for _ in 0..<12 { _ = activity.consume(Array(repeating: 0.03, count: 320), sampleRate: 16000) }
        for _ in 0..<45 {
            if case .utterance(let samples) = activity.consume(Array(repeating: 0, count: 320), sampleRate: 16000) {
                precondition(samples.allSatisfy(\.isFinite)); emitted = true
            }
        }
        precondition(emitted)
        print("VAD silence, click rejection, short words, pause joining, repeated segments, rate conversion boundaries and invalid samples passed")
    }
}
