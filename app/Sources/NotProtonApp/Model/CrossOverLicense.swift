// Checks whether the user's CrossOver install is licensed.
// CodeWeavers, I hope this doesn't bother you. You don't validate
// license when the Wine binary itself is invoked, so I wanted to
// do something to prevent skids from doing really trivial piracy.

import Foundation

enum CrossOverLicense {

    struct Status: Sendable {
        let licensed: Bool
        let detail: String
        // The real reason, for the log.
        let diagnostic: String
    }

    static let defaultSearchDirs: [URL] = {
        let home = URL(filePath: NSHomeDirectory())
        return [
            home.appending(path: "Library/Preferences"),
            URL(filePath: "/Library/Preferences"),
        ]
    }()

    private static let licenseBase = "com.codeweavers.CrossOver"

    static let notActivatedTitle = "CrossOver does not appear to be activated."
    static let notActivatedAdvice = "Please run CrossOver and try again."
    static var notActivated: String { "\(notActivatedTitle) \(notActivatedAdvice)" }

    static let defaultOpenssl = "/usr/bin/openssl"

    // CrossOver's trial runs this long from the FirstRunDate it records on first launch.
    // That date is an unsigned preference, so a trial is only as hard to extend as
    // CrossOver's own. compat_run.sh repeats this check on every launch.
    static let trialLength: TimeInterval = 14 * 24 * 60 * 60
    static let trialEndedTitle = "Your CrossOver trial has ended."
    static let trialEndedAdvice = "Buy a CrossOver license to keep using NotProton."
    static var trialEnded: String { "\(trialEndedTitle) \(trialEndedAdvice)" }

    static func check(
        crossOverRoot: URL,
        searchDirs: [URL] = defaultSearchDirs,
        openssl: String = defaultOpenssl,
        now: Date = Date()
    ) -> Status {
        var status = evaluate(
            crossOverRoot: crossOverRoot, searchDirs: searchDirs, openssl: openssl
        )
        // A bundle without CrossOver's key is not CrossOver, trial or not.
        if !status.licensed, FileManager.default.fileExists(atPath: keyFile(in: crossOverRoot)),
           let trial = trial(searchDirs: searchDirs, now: now, license: status) {
            status = trial
        }
        AppLog.note("license: \(status.diagnostic)")
        return status
    }

    private static func keyFile(in crossOverRoot: URL) -> String {
        crossOverRoot.appending(path: "share/crossover/data/tie.pub").path(percentEncoded: false)
    }

    // Only the user domain, the first search directory, holds CrossOver's preferences.
    private static func trial(searchDirs: [URL], now: Date, license: Status) -> Status? {
        guard let prefs = searchDirs.first?.appending(path: "\(licenseBase).plist"),
              let data = try? Data(contentsOf: prefs),
              let plist = try? PropertyListSerialization.propertyList(from: data, format: nil)
                as? [String: Any],
              let started = plist["FirstRunDate"] as? Date
        else { return nil }

        let ends = started.addingTimeInterval(trialLength)
        let when = ends.formatted(date: .abbreviated, time: .shortened)
        // A start date ahead of the clock would stretch the trial past its length.
        guard started <= now.addingTimeInterval(60 * 60) else {
            return Status(
                licensed: false,
                detail: license.detail,
                diagnostic: "\(license.diagnostic); trial start \(started) is in the future"
            )
        }
        guard now < ends else {
            return Status(
                licensed: false,
                detail: trialEnded,
                diagnostic: "\(license.diagnostic); trial ended \(ends)"
            )
        }
        return Status(
            licensed: true,
            detail: "CrossOver trial active until \(when).",
            diagnostic: "\(license.diagnostic); trial active until \(ends)"
        )
    }

    private static func evaluate(
        crossOverRoot: URL,
        searchDirs: [URL],
        openssl: String
    ) -> Status {
        let keyFile = keyFile(in: crossOverRoot)

        guard FileManager.default.fileExists(atPath: keyFile) else {
            return Status(
                licensed: false,
                detail: notActivated,
                diagnostic: "no verification key in the CrossOver bundle"
            )
        }

        var rejection: String?

        for dir in searchDirs {
            let label = dir.path(percentEncoded: false)
            let license = dir.appending(path: "\(licenseBase).license")
                .path(percentEncoded: false)

            guard FileManager.default.fileExists(atPath: license) else { continue }

            let signatures = sidecars(in: dir)
            guard !signatures.isEmpty else {
                rejection = "the license in \(label) has no signature beside it"
                continue
            }

            var unchecked: String?

            for signature in signatures {
                let result: CommandResult
                do {
                    result = try Shell.run(openssl, [
                        "dgst", signature.digest, "-verify", keyFile,
                        "-signature", signature.path, license,
                    ])
                } catch {
                    return Status(
                        licensed: false,
                        detail: notActivated,
                        diagnostic: "could not run \(openssl) to verify the license"
                    )
                }

                if result.succeeded {
                    return Status(
                        licensed: true,
                        detail: "CrossOver is activated.",
                        diagnostic: "valid license in \(label)"
                    )
                }

                let trouble = result.stderr.trimmingCharacters(in: .whitespacesAndNewlines)
                if !trouble.isEmpty {
                    if trouble.localizedCaseInsensitiveContains("unable to load key") {
                        return Status(
                            licensed: false,
                            detail: notActivated,
                            diagnostic: "the verification key in the CrossOver bundle could not be read"
                        )
                    }
                    unchecked = "the license in \(label) could not be checked"
                }
            }

            rejection = unchecked
                ?? "no signature beside the license in \(label) verified against this bundle"
        }

        return Status(
            licensed: false,
            detail: notActivated,
            diagnostic: rejection ?? "no CrossOver license file found"
        )
    }

    static func requireValid(
        for install: CrossOverInstall, searchDirs: [URL] = defaultSearchDirs
    ) throws {
        let status = check(crossOverRoot: install.crossOverRoot, searchDirs: searchDirs)
        guard status.licensed else {
            throw StepFailure(
                step: "Verify CrossOver license",
                detail: status.detail
            )
        }
    }

    private static func sidecars(in dir: URL) -> [(path: String, digest: String)] {
        let candidates: [(path: String, digest: String)] = [
            (dir.appending(path: "\(licenseBase).sha256").path(percentEncoded: false), "-sha256"),
            (dir.appending(path: "\(licenseBase).sig").path(percentEncoded: false), "-sha1"),
        ]
        return candidates.filter { FileManager.default.fileExists(atPath: $0.path) }
    }
}
