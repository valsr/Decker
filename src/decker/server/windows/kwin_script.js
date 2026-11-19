// Reports the focused window to the Decker server over D-Bus (KWin 6).
function typeName(w) {
    const flags = [
        ["desktop", w.desktopWindow],
        ["dock", w.dock],
        ["toolbar", w.toolbar],
        ["menu", w.menu],
        ["splash", w.splash],
        ["utility", w.utility],
        ["dialog", w.dialog],
        ["notification", w.notification],
        ["criticalnotification", w.criticalNotification],
        ["onscreendisplay", w.onScreenDisplay],
        ["popup", w.popupWindow],
        ["normal", w.normalWindow],
    ];
    for (const [name, on] of flags) {
        if (on) {
            return name;
        }
    }
    return "normal";
}

function report(w) {
    if (!w) {
        return;
    }
    callDBus(
        "org.decker.WindowWatcher",
        "/WindowWatcher",
        "org.decker.WindowWatcher",
        "Focused",
        JSON.stringify({
            resourceClass: w.resourceClass || "",
            windowType: typeName(w),
            caption: w.caption || "",
            pid: w.pid || 0,
            desktopFileName: w.desktopFileName || "",
        })
    );
}

workspace.windowActivated.connect(report);
report(workspace.activeWindow);
