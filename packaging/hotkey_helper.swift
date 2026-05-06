import Carbon
import Cocoa
import Foundation

let args = CommandLine.arguments
guard args.count >= 4,
      let port = UInt16(args[1]),
      let keyCode = UInt32(args[2]),
      let cgModifierMask = UInt64(args[3]) else {
    fputs("Usage: hotkey_helper <port> <keyCode> <modifierMask>\n", stderr)
    exit(1)
}

let sock = socket(AF_INET, SOCK_DGRAM, 0)
var addr = sockaddr_in()
addr.sin_family = sa_family_t(AF_INET)
addr.sin_port = CFSwapInt16HostToBig(port)
addr.sin_addr.s_addr = inet_addr("127.0.0.1")
let app = NSApplication.shared
app.setActivationPolicy(.accessory)

func sendUDP(_ message: String) {
    var target = addr
    _ = message.withCString { ptr in
        withUnsafePointer(to: &target) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
                sendto(sock, ptr, strlen(ptr), 0, sa, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
    }
}

func carbonModifiers(from cgMask: UInt64) -> UInt32 {
    var modifiers: UInt32 = 0
    if (cgMask & 0x40000) != 0 { modifiers |= UInt32(controlKey) }
    if (cgMask & 0x80000) != 0 { modifiers |= UInt32(optionKey) }
    if (cgMask & 0x20000) != 0 { modifiers |= UInt32(shiftKey) }
    if (cgMask & 0x100000) != 0 { modifiers |= UInt32(cmdKey) }
    return modifiers
}

let hotKeyID = EventHotKeyID(signature: OSType(0x5348544B), id: 1) // SHTK
let modifierMask = carbonModifiers(from: cgModifierMask)
var hotKeyRef: EventHotKeyRef?

let handler: EventHandlerUPP = { _, event, _ in
    var eventID = EventHotKeyID()
    let status = GetEventParameter(
        event,
        EventParamName(kEventParamDirectObject),
        EventParamType(typeEventHotKeyID),
        nil,
        MemoryLayout<EventHotKeyID>.size,
        nil,
        &eventID
    )

    if status == noErr && eventID.signature == hotKeyID.signature && eventID.id == hotKeyID.id {
        sendUDP("{\"event\":\"hotkey\"}")
        fputs("hotkey matched\n", stderr)
    }

    return noErr
}

var eventSpec = EventTypeSpec(
    eventClass: OSType(kEventClassKeyboard),
    eventKind: UInt32(kEventHotKeyPressed)
)

let installStatus = InstallEventHandler(
    GetApplicationEventTarget(),
    handler,
    1,
    &eventSpec,
    nil,
    nil
)
guard installStatus == noErr else {
    fputs("InstallEventHandler failed: \(installStatus)\n", stderr)
    exit(1)
}

let registerStatus = RegisterEventHotKey(
    keyCode,
    modifierMask,
    hotKeyID,
    GetApplicationEventTarget(),
    0,
    &hotKeyRef
)
guard registerStatus == noErr else {
    fputs("RegisterEventHotKey failed: \(registerStatus) keyCode=\(keyCode) modifiers=\(modifierMask)\n", stderr)
    exit(1)
}

sendUDP("{\"event\":\"ready\"}")
fputs("Registered keyCode=\(keyCode) modifiers=\(modifierMask) port=\(port)\n", stderr)
app.run()
