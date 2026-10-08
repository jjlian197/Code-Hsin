import Foundation

/// Energy VAD runs on copied native-format samples. No speech framework or cloud call is needed.
struct SpeechActivity {
    enum Event { case waiting, began, utterance([Float]) }
    private var pending: [Float] = []
    private var preRoll: [Float] = []
    private var utterance: [Float] = []
    private var noise: Float = 0.0008
    private var voiced = 0.0
    private var silence = 0.0
    private(set) var speaking = false
    private var onset = 0.0
    private var peakEnergy: Float = 0
    var pauseSeconds = 0.55

    mutating func consume(_ samples: [Float], sampleRate: Double) -> Event {
        guard sampleRate.isFinite, sampleRate > 0 else { return .waiting }
        let window = max(1, Int(sampleRate * 0.02))
        pending.append(contentsOf: samples.map { $0.isFinite ? $0 : 0 })
        var began = false
        while pending.count >= window {
            let frame = Array(pending.prefix(window))
            pending.removeFirst(window)
            let energy = sqrt(frame.reduce(Float(0)) { $0 + $1 * $1 } / Float(window))
            // Room tone must not keep a phrase open until the 20-second limit.
            // Combine calibrated noise with the voice envelope, retaining a floor for soft speech.
            let threshold = speaking ? max(0.004, noise * 2.5, peakEnergy * 0.12) : max(0.004, noise * 3)
            let audible = energy.isFinite && energy >= threshold
            if !speaking {
                preRoll.append(contentsOf: frame)
                let maximum = Int(sampleRate * 0.24)
                if preRoll.count > maximum { preRoll.removeFirst(preRoll.count - maximum) }
                onset = audible ? onset + 0.02 : 0
                if !audible { noise += (min(energy, 0.01) - noise) * 0.015 }
                if onset >= 0.10 {
                    speaking = true
                    began = true
                    utterance = preRoll
                    preRoll = []
                    peakEnergy = energy
                    voiced = onset
                    silence = 0
                }
            } else {
                utterance.append(contentsOf: frame)
                if audible { peakEnergy = max(energy, peakEnergy * 0.995); voiced += 0.02; silence = 0 } else { silence += 0.02 }
                if silence >= min(1.2, max(0.4, pauseSeconds)) || Double(utterance.count) / sampleRate >= 20 {
                    let completed = utterance
                    let valid = voiced >= 0.18
                    // Short clicks are discarded; speech retains pre-roll and trailing silence for ASR.
                    utterance = []; speaking = false; voiced = 0; silence = 0; onset = 0; peakEnergy = 0
                    if valid { return .utterance(completed) }
                }
            }
        }
        return began ? .began : .waiting
    }
}
