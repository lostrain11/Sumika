use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::{Duration, Instant};

use serde_json::Value;
use tauri::{State, Webview};
use hmac::{Hmac, Mac};
use sha2::Sha256;

use crate::{consultation, resolve_address, CoreProcess};

pub fn new_secret() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|_| "host-random-source-unavailable".to_string())?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn verify_process_proof(value: &Value, secret: &str, nonce: &str, pid: u32) -> bool {
    if value.get("schema_version").and_then(Value::as_str) != Some("sumika-core-identity/v1")
        || value.get("nonce").and_then(Value::as_str) != Some(nonce)
        || value.get("pid").and_then(Value::as_u64) != Some(pid as u64) {
        return false;
    }
    let Some(proof) = value.get("proof").and_then(Value::as_str) else { return false };
    if proof.len() != 64 || !proof.bytes().all(|byte| byte.is_ascii_hexdigit()) { return false; }
    let signature: Result<Vec<u8>, _> = (0..64).step_by(2)
        .map(|index| u8::from_str_radix(&proof[index..index + 2], 16)).collect();
    let Ok(signature) = signature else { return false };
    let Ok(mut mac) = Hmac::<Sha256>::new_from_slice(secret.as_bytes()) else { return false };
    mac.update(format!("sumika-core-identity/v1\n{nonce}\n{pid}").as_bytes());
    mac.verify_slice(&signature).is_ok()
}

pub fn core_identity_request(address: SocketAddr, secret: &str, pid: u32) -> bool {
    let Ok(nonce) = new_secret() else { return false };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(250)) else { return false };
    if stream.set_read_timeout(Some(Duration::from_millis(500))).is_err()
        || stream.set_write_timeout(Some(Duration::from_millis(500))).is_err() { return false; }
    let body = serde_json::json!({"nonce": nonce}).to_string();
    let request = format!("POST /internal/host-identity/v1 HTTP/1.1\r\nHost: {address}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len());
    if stream.write_all(request.as_bytes()).is_err() { return false; }
    let deadline = Instant::now() + Duration::from_millis(750);
    let mut bytes = Vec::new();
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() || stream.set_read_timeout(Some(remaining)).is_err() { return false; }
        let mut chunk = [0u8; 1024];
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(count) => bytes.extend_from_slice(&chunk[..count]),
            Err(_) => return false,
        }
        if bytes.len() > 8192 { return false; }
    }
    let Ok(response) = String::from_utf8(bytes) else { return false };
    let Some((headers, body)) = response.split_once("\r\n\r\n") else { return false };
    let Some(status) = headers.lines().next() else { return false };
    if !matches!(status.split_whitespace().nth(1), Some("200")) { return false; }
    let Ok(value) = serde_json::from_str::<Value>(body) else { return false };
    verify_process_proof(&value, secret, &nonce, pid)
}

fn allowed_action(method: &str) -> bool {
    matches!(method,
        "work.authorization.confirm"
        | "quality.task.confirm"
        | "quality.task.budget"
        | "schedule.create"
        | "schedule.update"
        | "schedule.pause"
        | "schedule.run"
        | "agent.approval.respond"
        | "agent.question.respond"
        | "agent.session.retry"
        | "agent.mcp.configuration.apply"
        | "workspace.worktree.create"
        | "workspace.commit"
        | "workspace.restore"
        | "workspace.checkpoint.create"
        | "agent.skills.approve"
        | "agent.skill.approve"
        | "agent.skills.revoke"
        | "agent.skill.revoke"
        | "agent.session.create"
        | "agent.session.select_preset"
        | "agent.session.select_model"
        | "agent.session.fork"
        | "agent.preset.copy"
        | "agent.preset.open"
        | "agent.preset.remove"
        | "agent.workspace.create"
        | "agent.provider.sync"
        | "model.policy.apply"
        | "model.policy.refresh"
        | "skill.builtin.set"
        | "module.update"
        | "plugin.approve"
        | "plugin.configure"
        | "plugin.run"
        | "tool.run"
        | "task.run"
        | "audio.permission.set"
        | "audio.start"
        | "audio.asr.transcribe"
        | "audio.tts.synthesize"
        | "audio.vad.detect"
        | "vision.permission.set"
        | "vision.start"
        | "vision.observe"
        | "provider.profile.save"
        | "provider.import.save"
        | "provider.profile.activate"
        | "provider.profile.model.select"
        | "provider.profile.restore"
        | "provider.profile.models"
        | "provider.profile.health"
        | "snapshot.restore"
        | "browser.embedded.attach"
        | "browser.embedded.poll"
        | "browser.embedded.complete"
        | "browser.embedded.alive"
        | "browser.embedded.bind_portal"
        | "browser.profile.create"
        | "browser.profile.restore"
        | "browser.session.create"
        | "browser.session.focus"
        | "browser.tab.create"
        | "browser.tab.select"
        | "browser.tab.close"
        | "browser.navigate"
        | "browser.action.execute"
        | "browser.console"
        | "browser.network"
        | "browser.download.release"
        | "browser.download.quarantine"
        | "browser.web_chat.profile.create"
        | "browser.web_chat.profile.update"
        | "browser.web_chat.profile.bind_native"
        | "browser.web_chat.profile.native_takeover"
        | "browser.web_chat.profile.authorize"
        | "browser.web_chat.profile.open"
        | "browser.web_chat.profile.focus"
        | "browser.web_chat.profile.check"
        | "browser.web_chat.profile.consent"
        | "browser.web_chat.profile.activate"
        | "browser.web_chat.profile.restore"
        | "desktop.automation.register"
        | "desktop.automation.open"
        | "desktop.automation.act"
        | "desktop.automation.close"
        | "desktop.automation.approval"
        | "desktop.automation.takeover"
        | "sumika.route.bridge_tools"
        | "sumika.route.occupancy"
        | "sumika.route.takeover"
        | "benefits.configure"
        | "benefits.refresh"
        | "benefits.checkin"
    )
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
    fn process_proof_matches_python_and_rejects_replay_and_wrong_process() {
        let secret = "a".repeat(64);
        let nonce = "b".repeat(64);
        let value = serde_json::json!({"schema_version": "sumika-core-identity/v1", "nonce": nonce,
            "pid": 1234, "proof": "ab00a98b18dfb2d71ebf89c76313b693a35a32e2fb448929a2cdc332f3bd668b"});
        assert!(verify_process_proof(&value, &secret, &nonce, 1234));
        assert!(!verify_process_proof(&value, &"d".repeat(64), &nonce, 1234));
        assert!(!verify_process_proof(&value, &secret, &"c".repeat(64), 1234));
        assert!(!verify_process_proof(&value, &secret, &nonce, 1235));
        for proof in ["bad".to_string(), "0".repeat(64), "中文".repeat(32)] {
            let mut invalid = value.clone();
            invalid["proof"] = Value::String(proof);
            assert!(!verify_process_proof(&invalid, &secret, &nonce, 1234));
        }
    }

    #[test]
    fn unrelated_healthy_server_never_receives_bootstrap_secret() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
            let mut bytes = [0u8; 4096];
            let count = stream.read(&mut bytes).unwrap();
            let request = String::from_utf8_lossy(&bytes[..count]).to_string();
            stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{\"ok\":true}").unwrap();
            request
        });
        let secret = "a".repeat(64);
        assert!(!core_identity_request(address, &secret, 1234));
        let request = server.join().unwrap();
        assert!(request.starts_with("POST /internal/host-identity/v1 "));
        assert!(!request.contains(&secret));
        assert!(!request.contains("X-Sumika-Host"));
    }

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
        assert!(allowed_action("agent.mcp.configuration.apply"));
        for method in ["agent.skills.approve", "agent.skill.approve", "agent.skills.revoke", "agent.skill.revoke"] {
            assert!(allowed_action(method));
        }
        for method in ["workspace.worktree.create", "workspace.commit", "workspace.restore"] {
            assert!(allowed_action(method));
        }
        for method in ["module.update", "plugin.approve", "plugin.configure", "plugin.run", "snapshot.restore",
                       "audio.permission.set", "vision.permission.set", "agent.session.create", "model.policy.apply",
                       "sumika.route.bridge_tools", "browser.embedded.attach", "browser.embedded.poll",
                       "browser.embedded.complete", "browser.embedded.alive", "browser.embedded.bind_portal"] {
            assert!(allowed_action(method));
        }
        for method in ["chat.send", "browser.web_chat.send", "plugin.install", "core.diagnostics", "work.task.merge.apply",
                       "work.task.merge.undo", "agent.event.ingest", "browser.embedded.eval", "module.arbitrary"] {
            assert!(!allowed_action(method));
        }
    }
}
