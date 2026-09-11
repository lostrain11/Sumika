use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::Duration;

use serde_json::Value;
use tauri::{State, Webview};

use crate::{consultation, resolve_address, CoreProcess};

pub fn new_secret() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|_| "host-random-source-unavailable".to_string())?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn allowed_action(method: &str) -> bool {
    matches!(method, "work.authorization.confirm" | "quality.task.confirm" | "quality.task.budget"
        | "schedule.create" | "schedule.update" | "schedule.pause" | "agent.approval.respond"
        | "agent.question.respond")
}

#[tauri::command]
pub async fn host_confirm(caller: Webview, state: State<'_, CoreProcess>, method: String,
                          params: Value, digest: String) -> Result<Value, String> {
    consultation::authorize_main_caller(&caller)?;
    if !allowed_action(&method) || !params.is_object() || digest.len() != 64
        || !digest.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("unsupported-host-confirmation".into());
    }
    let body = serde_json::json!({"method": method, "params": params, "digest": digest}).to_string();
    if body.len() > 65536 { return Err("host-confirmation-too-large".into()); }
    let secret = state.inner.host_secret.lock().map_err(|_| "host-unavailable")?.clone();
    let address = resolve_address(&state.inner.host, state.inner.port)?;
    tauri::async_runtime::spawn_blocking(move || {
        let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(2))
            .map_err(|_| "host-confirmation-connect-failed".to_string())?;
        stream.set_read_timeout(Some(Duration::from_secs(15))).map_err(|_| "host-timeout")?;
        stream.set_write_timeout(Some(Duration::from_secs(5))).map_err(|_| "host-timeout")?;
        let request = format!("POST /internal/host-confirm/v1 HTTP/1.1\r\nHost: {address}\r\nX-Sumika-Host: {secret}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len());
        stream.write_all(request.as_bytes()).map_err(|_| "host-confirmation-submit-unknown")?;
        let mut bytes = Vec::new();
        stream.take(2 * 1024 * 1024).read_to_end(&mut bytes).map_err(|_| "host-confirmation-response-unknown")?;
        let response = String::from_utf8(bytes).map_err(|_| "invalid-host-response")?;
        let (_, body) = response.split_once("\r\n\r\n").ok_or("invalid-host-response")?;
        let value: Value = serde_json::from_str(body).map_err(|_| "invalid-host-response")?;
        if let Some(error) = value.get("error") {
            return Err(error.get("message").and_then(Value::as_str).unwrap_or("host-confirmation-rejected").to_string());
        }
        value.get("result").cloned().ok_or("invalid-host-response".to_string())
    }).await.map_err(|_| "host-confirmation-interrupted".to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn secret_is_random_and_not_reused() {
        let first = new_secret().unwrap();
        assert_eq!(first.len(), 64);
        assert_ne!(first, new_secret().unwrap());
    }

    #[test]
    fn confirmation_channel_is_not_arbitrary_rpc() {
        assert!(allowed_action("work.authorization.confirm"));
        assert!(allowed_action("agent.question.respond"));
        for method in ["chat.send", "browser.web_chat.send", "plugin.install", "core.diagnostics", "work.task.merge.apply"] {
            assert!(!allowed_action(method));
        }
    }
}
