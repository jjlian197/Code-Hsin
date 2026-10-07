import SwiftUI

@main
struct HsinVisionApp: App {
    @StateObject private var companion = CompanionStore()

    var body: some Scene {
        // visionOS initially requests an application window role, even for a volume companion.
        WindowGroup(id: "launcher") {
            LauncherView()
        }
        .defaultSize(width: 360, height: 180)

        WindowGroup(id: "companion") {
            CompanionView().environmentObject(companion)
        }
        .windowStyle(.volumetric)
        .defaultSize(width: 0.95, height: 1.15, depth: 0.8, in: .meters)
    }
}

private struct LauncherView: View {
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow
    @State private var opening = false

    var body: some View {
        VStack(spacing: 12) {
            Text("心 · 空间伙伴").font(.title)
            Button("打开空间伙伴") { openCompanion() }
        }
        .task { openCompanion() }
    }

    private func openCompanion() {
        guard !opening else { return }
        opening = true
        openWindow(id: "companion")
        // Wait until the volume owns a scene before dismissing the launch window.
        Task {
            try? await Task.sleep(for: .seconds(1))
            dismissWindow(id: "launcher")
        }
    }
}
