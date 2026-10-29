// The manager window is a child of the SnipType app (source/manager_bridge.py).
// It owns no data: the webview's requests go out on stdout, one JSON line each,
// and the app's answers and events come back on stdin. EOF on stdin means the
// app closed the window or quit, so the process exits with it.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, Write};

use tauri::Emitter;

#[tauri::command]
fn bridge_send(line: String) -> Result<(), String> {
    if line.contains('\n') {
        return Err("a bridge message must be a single line".into());
    }
    let mut out = std::io::stdout().lock();
    writeln!(out, "{line}")
        .and_then(|()| out.flush())
        .map_err(|error| error.to_string())
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![bridge_send])
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                for line in std::io::stdin().lock().lines() {
                    let Ok(line) = line else { break };
                    if let Err(error) = handle.emit("bridge", line) {
                        eprintln!("bridge: emit failed: {error}");
                    }
                }
                handle.exit(0);
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("SnipType manager failed to start");
}
