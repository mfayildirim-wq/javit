// Javit – Mikrofon-Helfer für macOS mit Apples Sprachverarbeitung (Echounterdrückung).
//
// Nimmt das Standard-Mikrofon über AVAudioEngine mit „Voice Processing“ auf: Das Echo der eigenen
// Sprachausgabe (Lautsprecher) wird herausgerechnet, bevor Weckwort und Stoppwort geprüft werden.
// Schreibt rohes PCM (int16, mono, 16 kHz) nach stdout und läuft, bis stdin geschlossen wird.
//
// Bauen (macht scripts/install.sh bzw. der Kern beim ersten Start):
//     xcrun swiftc -O -o ~/.jarvis/bin/javit-mikrofon kern/jarvis/stimme/mac_mikrofon.swift

import AVFoundation
import Foundation

func meldung(_ text: String) {
    FileHandle.standardError.write((text + "\n").data(using: .utf8)!)
}

let engine = AVAudioEngine()
let eingang = engine.inputNode
do {
    try eingang.setVoiceProcessingEnabled(true)
} catch {
    meldung("Sprachverarbeitung nicht verfügbar: \(error)")
    exit(2)
}

let quellFormat = eingang.outputFormat(forBus: 0)
guard quellFormat.sampleRate > 0, quellFormat.channelCount > 0 else {
    meldung("Kein Eingabegerät (Format \(quellFormat))")
    exit(4)
}
let monoFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: quellFormat.sampleRate, channels: 1, interleaved: false)!
let zielFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true)!
guard let konverter = AVAudioConverter(from: monoFormat, to: zielFormat) else {
    meldung("Konvertierung nach 16 kHz nicht möglich")
    exit(5)
}
meldung("bereit: \(Int(quellFormat.sampleRate)) Hz, \(quellFormat.channelCount) Kanäle, Echounterdrückung an")

let ausgabe = FileHandle.standardOutput
let sperre = NSLock()

eingang.installTap(onBus: 0, bufferSize: 2048, format: quellFormat) { puffer, _ in
    let n = Int(puffer.frameLength)
    guard n > 0, let kanaele = puffer.floatChannelData else { return }
    guard let mono = AVAudioPCMBuffer(pcmFormat: monoFormat, frameCapacity: AVAudioFrameCount(n)) else { return }
    mono.frameLength = AVAudioFrameCount(n)
    let quelle = kanaele[0]
    let ziel = mono.floatChannelData![0]
    for i in 0..<n { ziel[i] = quelle[i] }
    let kapazitaet = AVAudioFrameCount(Double(n) * 16000.0 / quellFormat.sampleRate) + 64
    guard let out16 = AVAudioPCMBuffer(pcmFormat: zielFormat, frameCapacity: kapazitaet) else { return }
    var geliefert = false
    var fehler: NSError?
    let status = konverter.convert(to: out16, error: &fehler) { _, outStatus in
        if geliefert { outStatus.pointee = .noDataNow; return nil }
        geliefert = true
        outStatus.pointee = .haveData
        return mono
    }
    if status == .error { return }
    let bytes = Int(out16.frameLength) * 2
    if bytes == 0 { return }
    let daten = Data(bytes: out16.int16ChannelData![0], count: bytes)
    sperre.lock()
    ausgabe.write(daten)
    sperre.unlock()
}

do {
    try engine.start()
} catch {
    meldung("Aufnahme konnte nicht gestartet werden: \(error)")
    exit(3)
}

// Läuft, bis der Kern stdin schließt (oder SIGTERM kommt).
signal(SIGTERM) { _ in exit(0) }
signal(SIGINT) { _ in exit(0) }
let leser = Thread {
    while let zeile = readLine(strippingNewline: true) {
        if zeile == "ende" { break }
    }
    engine.stop()
    exit(0)
}
leser.start()
RunLoop.main.run()
