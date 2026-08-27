#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::env;
use std::fs::OpenOptions;
use std::io::{ErrorKind, Read, Write};
use std::net::{SocketAddr, TcpStream, ToSocketAddrs};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{
    atomic::{AtomicBool, AtomicU32, Ordering},
    Arc, Mutex,
};
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, State, WindowEvent};

#[derive(Clone)]
struct CoreProcess {
    inner: Arc<CoreProcessInner>,
}

struct CoreProcessInner {
    child: Mutex<Option<Child>>,
    log_path: PathBuf,
    host: String,
    port: u16,
    stopping: AtomicBool,
    restart_count: AtomicU32,
}

#[derive(Clone)]
struct AgentProcess {
    inner: Arc<AgentProcessInner>,
}

#[derive(Clone)]
struct AgentLaunchConfig {
    runtime_id: String,
    executable: String,
    endpoint: String,
    profile_dir: PathBuf,
    log_path: PathBuf,
    args: Vec<String>,
    environment: Vec<(String, String)>,
    health_path: String,
    health_body: String,
    default_port: u16,
}

struct AgentProcessInner {
    child: Mutex<Option<Child>>,
    log_path: PathBuf,
    runtime_id: String,
    endpoint: String,
    launcher: Option<AgentLaunchConfig>,
    stopping: AtomicBool,
    restart_count: AtomicU32,
}

fn repository_root() -> Result<PathBuf, String> {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(PathBuf::from)
        .ok_or_else(|| "无法确定 Sumika 仓库目录".to_string())
}

fn python_command() -> String {
    env::var("SUMIKA_PYTHON").unwrap_or_else(|_| "python".to_string())
}

fn core_endpoint() -> (String, u16) {
    let host = env::var("SUMIKA_CORE_HOST").unwrap_or_else(|_| "127.0.0.1".to_string());
    let port = env::var("SUMIKA_CORE_PORT")
        .ok()
        .and_then(|value| value.parse::<u16>().ok())
        .filter(|value| *value != 0)
        .unwrap_or(8771);
    (host, port)
}

fn append_log(log_path: &PathBuf, message: &str) {
    let Ok(mut file) = OpenOptions::new().create(true).append(true).open(log_path) else { return };
    let now = chrono_free_timestamp();
    let _ = writeln!(file, "[{now}] {message}");
}

fn chrono_free_timestamp() -> String {
    // Keep the shell dependency-free; the log remains sortable by process time.
    format!("{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|value| value.as_secs()).unwrap_or_default())
}

fn spawn_core(log_path: &PathBuf, host: &str, port: u16) -> Result<Child, String> {
    let root = repository_root()?;
    let data_dir = root.join(".sumika-desktop");
    std::fs::create_dir_all(&data_dir).map_err(|error| format!("创建桌面数据目录失败: {error}"))?;
    let python_path = root.join("backend").join("src");
    let log_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)
        .map_err(|error| format!("创建桌面日志失败: {error}"))?;
    let error_log = log_file.try_clone().map_err(|error| format!("复制桌面日志句柄失败: {error}"))?;
    let mut command = Command::new(python_command());
    command
        .current_dir(&root)
        .env("PYTHONPATH", python_path)
        .env("SUMIKA_DATA_DIR", &data_dir)
        .args([
            "-u",
            "-m",
            "sumika_core",
            "--host",
            host,
            "--port",
            &port.to_string(),
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::from(log_file))
        .stderr(Stdio::from(error_log));
    command
        .spawn()
        .map_err(|error| format!("启动 Sumika Python 核心失败（可设置 SUMIKA_PYTHON 指向 Python）: {error}"))
}

fn resolve_address(host: &str, port: u16) -> Result<SocketAddr, String> {
    (host, port)
        .to_socket_addrs()
        .map_err(|error| format!("解析核心地址失败 {host}:{port}: {error}"))?
        .next()
        .ok_or_else(|| format!("核心地址没有可用解析结果 {host}:{port}"))
}

fn core_health_request(address: SocketAddr) -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(250)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let host = address.ip().to_string();
    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    let status_ok = response
        .lines()
        .next()
        .map(|line| line.contains(" 200 "))
        .unwrap_or(false);
    status_ok && (response.contains("\"ok\": true") || response.contains("\"ok\":true"))
}

fn core_ready(child: &mut Child, host: &str, port: u16) -> Result<(), String> {
    let address = resolve_address(host, port)?;
    let deadline = Instant::now() + Duration::from_secs(15);
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Err(format!("Sumika Python 核心提前退出: {status}")),
            Ok(None) => {}
            Err(error) => return Err(format!("检查 Sumika Python 核心状态失败: {error}")),
        }
        if core_health_request(address) {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err(format!(
                "等待 Sumika Python 核心在 {host}:{port} 健康就绪超时"
            ));
        }
        std::thread::sleep(Duration::from_millis(100));
    }
}

fn stop_core_inner(inner: &CoreProcessInner, reason: &str) {
    if inner.stopping.swap(true, Ordering::SeqCst) {
        return;
    }
    append_log(&inner.log_path, reason);
    let Ok(mut guard) = inner.child.lock() else {
        append_log(&inner.log_path, "could not lock Python core child during shutdown");
        return;
    };
    let Some(child) = guard.as_mut() else { return };
    match child.try_wait() {
        Ok(Some(_)) => {}
        Ok(None) => {
            append_log(&inner.log_path, "stopping Python core child process");
            let _ = child.kill();
            let _ = child.wait();
        }
        Err(error) if error.kind() == ErrorKind::InvalidInput => {}
        Err(_) => {}
    }
    *guard = None;
    append_log(&inner.log_path, "Python core child process stopped");
}

fn stop_core(state: &CoreProcess) {
    stop_core_inner(&state.inner, "desktop shutdown requested");
}

fn configured_agent_runtime_id() -> String {
    let value = env::var("SUMIKA_AGENT_RUNTIME")
        .unwrap_or_else(|_| "dsh".to_string())
        .trim()
        .to_ascii_lowercase();
    if !value.is_empty()
        && value.len() <= 64
        && value
            .chars()
            .enumerate()
            .all(|(index, character)| character.is_ascii_alphanumeric() || (index > 0 && character == '-'))
    {
        value
    } else {
        "invalid".to_string()
    }
}

fn first_nonempty_env(names: &[&str]) -> Option<String> {
    names
        .iter()
        .find_map(|name| env::var(name).ok().filter(|value| !value.trim().is_empty()))
}

fn configured_agent_endpoint(runtime_id: &str) -> String {
    if runtime_id == "dsh" {
        first_nonempty_env(&["SUMIKA_AGENT_ENDPOINT", "SUMIKA_DSH_ENDPOINT"])
            .unwrap_or_else(|| "http://127.0.0.1:3080".to_string())
    } else {
        first_nonempty_env(&["SUMIKA_AGENT_ENDPOINT"]).unwrap_or_default()
    }
}

fn agent_autostart(runtime_id: &str) -> bool {
    let names: &[&str] = if runtime_id == "dsh" {
        &["SUMIKA_AGENT_AUTOSTART", "SUMIKA_DSH_AUTOSTART"]
    } else {
        &["SUMIKA_AGENT_AUTOSTART"]
    };
    first_nonempty_env(names)
        .map(|value| matches!(value.to_ascii_lowercase().as_str(), "1" | "true" | "yes"))
        .unwrap_or(false)
}

fn agent_port(endpoint: &str, default_port: u16) -> Option<u16> {
    let parsed = endpoint
        .strip_prefix("http://")
        .or_else(|| endpoint.strip_prefix("https://"))
        .unwrap_or(endpoint);
    let port_text = parsed.split('/').next()?.rsplit_once(':').map(|(_, port)| port);
    port_text
        .and_then(|value| value.parse::<u16>().ok())
        .or(Some(default_port))
}

fn dsh_launch_config(root: &PathBuf, log_dir: &PathBuf) -> Result<AgentLaunchConfig, String> {
    let endpoint = configured_agent_endpoint("dsh");
    let executable = first_nonempty_env(&["SUMIKA_AGENT_EXECUTABLE", "SUMIKA_DSH_EXECUTABLE"])
        .ok_or_else(|| "SUMIKA_AGENT_EXECUTABLE or SUMIKA_DSH_EXECUTABLE is required when DSH autostart is enabled".to_string())?;
    let profile_dir = first_nonempty_env(&[
        "SUMIKA_AGENT_PROFILE_DIR",
        "SUMIKA_DSH_PROFILE_DIR",
        "SUMIKA_DSH_HOME",
    ])
    .map(PathBuf::from)
    .unwrap_or_else(|| root.join(".sumika-desktop").join("dsh-profile"));
    let port = agent_port(&endpoint, 3080)
        .ok_or_else(|| format!("无法从 DSH endpoint 解析端口: {endpoint}"))?;
    let profile_text = profile_dir.to_string_lossy().to_string();
    Ok(AgentLaunchConfig {
        runtime_id: "dsh".to_string(),
        executable,
        endpoint,
        profile_dir,
        log_path: log_dir.join("dsh.log"),
        args: vec![
            "--profile".to_string(),
            "web".to_string(),
            "--no-open".to_string(),
            "--host".to_string(),
            "127.0.0.1".to_string(),
            "--port".to_string(),
            port.to_string(),
        ],
        environment: vec![
            ("DSH_HOME".to_string(), profile_text.clone()),
            ("SUMIKA_DSH_HOME".to_string(), profile_text),
        ],
        health_path: "/api/host.describe".to_string(),
        health_body: r#"{"type":"client-request","rpcId":"sumika-health","method":"host.describe","payload":{}}"#.to_string(),
        default_port: 3080,
    })
}

fn agent_launch_config(root: &PathBuf, log_dir: &PathBuf) -> Result<(String, PathBuf, Option<AgentLaunchConfig>), String> {
    let runtime_id = configured_agent_runtime_id();
    let fallback_log = if runtime_id == "dsh" {
        log_dir.join("dsh.log")
    } else {
        log_dir.join("agent-runtime.log")
    };
    if !agent_autostart(&runtime_id) {
        return Ok((runtime_id, fallback_log, None));
    }
    let launcher = match runtime_id.as_str() {
        "dsh" => dsh_launch_config(root, log_dir)?,
        _ => {
            return Err(format!(
                "Agent runtime '{runtime_id}' has no registered desktop launcher; start it externally or disable SUMIKA_AGENT_AUTOSTART"
            ))
        }
    };
    let log_path = launcher.log_path.clone();
    Ok((runtime_id, log_path, Some(launcher)))
}

fn agent_health_request(config: &AgentLaunchConfig) -> bool {
    let parsed = config
        .endpoint
        .strip_prefix("http://")
        .or_else(|| config.endpoint.strip_prefix("https://"))
        .unwrap_or(&config.endpoint);
    let authority = parsed.split('/').next().unwrap_or(parsed);
    let host = authority.split(':').next().unwrap_or(authority);
    let port = agent_port(&config.endpoint, config.default_port).unwrap_or(config.default_port);
    let Ok(address) = (host, port).to_socket_addrs().ok().and_then(|mut values| values.next()).ok_or(()) else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(250)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let host_header = format!("{}:{}", address.ip(), port);
    let request = format!(
        "POST {} HTTP/1.1\r\nHost: {host_header}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        config.health_path,
        config.health_body.len(),
        config.health_body,
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    stream.read_to_string(&mut response).is_ok()
        && response.lines().next().map(|line| line.contains(" 200 ")).unwrap_or(false)
}

fn spawn_agent(config: &AgentLaunchConfig) -> Result<Child, String> {
    std::fs::create_dir_all(&config.profile_dir)
        .map_err(|error| format!("创建 {} profile 失败: {error}", config.runtime_id))?;
    let log_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&config.log_path)
        .map_err(|error| format!("创建 {} 日志失败: {error}", config.runtime_id))?;
    let error_log = log_file
        .try_clone()
        .map_err(|error| format!("复制 {} 日志句柄失败: {error}", config.runtime_id))?;
    let executable_path = PathBuf::from(&config.executable);
    let is_windows_script = executable_path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| matches!(value.to_ascii_lowercase().as_str(), "cmd" | "bat"))
        .unwrap_or(false);
    let mut command = if is_windows_script {
        let mut command = Command::new("cmd.exe");
        command.args(["/d", "/c", &config.executable]);
        command
    } else {
        Command::new(&config.executable)
    };
    command
        .current_dir(repository_root().map_err(|error| error.to_string())?)
        .args(&config.args)
        .stdin(Stdio::null())
        .stdout(Stdio::from(log_file))
        .stderr(Stdio::from(error_log));
    for (name, value) in &config.environment {
        command.env(name, value);
    }
    command
        .spawn()
        .map_err(|error| format!("启动受管 {} 失败: {error}", config.runtime_id))
}

fn agent_ready(child: &mut Child, config: &AgentLaunchConfig) -> Result<(), String> {
    let deadline = Instant::now() + Duration::from_secs(15);
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Err(format!("受管 {} 提前退出: {status}", config.runtime_id)),
            Ok(None) => {}
            Err(error) => return Err(format!("检查受管 {} 状态失败: {error}", config.runtime_id)),
        }
        if agent_health_request(config) {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err(format!(
                "等待受管 {} 在 {} 健康就绪超时",
                config.runtime_id, config.endpoint
            ));
        }
        std::thread::sleep(Duration::from_millis(150));
    }
}

fn stop_agent_inner(inner: &AgentProcessInner, reason: &str) {
    if inner.stopping.swap(true, Ordering::SeqCst) {
        return;
    }
    append_log(&inner.log_path, reason);
    let Ok(mut guard) = inner.child.lock() else {
        append_log(&inner.log_path, "could not lock managed Agent runtime child during shutdown");
        return;
    };
    let Some(child) = guard.as_mut() else { return };
    match child.try_wait() {
        Ok(Some(_)) => {}
        Ok(None) => {
            append_log(
                &inner.log_path,
                &format!("stopping managed {} child process", inner.runtime_id),
            );
            let _ = child.kill();
            let _ = child.wait();
        }
        Err(_) => {}
    }
    *guard = None;
    append_log(
        &inner.log_path,
        &format!("managed {} child process stopped", inner.runtime_id),
    );
}

fn stop_agent(state: &AgentProcess) {
    stop_agent_inner(
        &state.inner,
        &format!(
            "desktop shutdown requested; stopping managed {}",
            state.inner.runtime_id
        ),
    );
}

impl Drop for AgentProcessInner {
    fn drop(&mut self) {
        stop_agent_inner(
            self,
            &format!(
                "desktop process dropped; stopping managed {} child process",
                self.runtime_id
            ),
        );
    }
}

fn supervise_agent(state: AgentProcess) {
    let Some(config) = state.inner.launcher.clone() else {
        return;
    };
    let mut failed_restarts = 0u32;
    loop {
        std::thread::sleep(Duration::from_millis(700));
        if state.inner.stopping.load(Ordering::SeqCst) {
            return;
        }
        let exited = match state.inner.child.lock() {
            Ok(mut guard) => match guard.as_mut() {
                Some(child) => match child.try_wait() {
                    Ok(Some(status)) => {
                        append_log(
                            &state.inner.log_path,
                            &format!("managed {} exited unexpectedly: {status}", config.runtime_id),
                        );
                        *guard = None;
                        true
                    }
                    Ok(None) => false,
                    Err(_) => {
                        *guard = None;
                        true
                    }
                },
                None => return,
            },
            Err(_) => return,
        };
        if !exited {
            continue;
        }
        if failed_restarts >= 3 {
            append_log(
                &state.inner.log_path,
                &format!("managed {} restart limit reached; staying stopped", config.runtime_id),
            );
            return;
        }
        failed_restarts += 1;
        std::thread::sleep(Duration::from_millis(700 * failed_restarts as u64));
        if state.inner.stopping.load(Ordering::SeqCst) {
            return;
        }
        match spawn_agent(&config) {
            Ok(mut child) => match agent_ready(&mut child, &config) {
                Ok(()) => {
                    let pid = child.id();
                    if let Ok(mut guard) = state.inner.child.lock() {
                        *guard = Some(child);
                        state.inner.restart_count.fetch_add(1, Ordering::SeqCst);
                        failed_restarts = 0;
                        append_log(
                            &state.inner.log_path,
                            &format!("managed {} restarted and healthy; pid={pid}", config.runtime_id),
                        );
                    } else {
                        let _ = child.kill();
                        let _ = child.wait();
                        return;
                    }
                }
                Err(error) => {
                    append_log(
                        &state.inner.log_path,
                        &format!("managed {} restart health check failed: {error}", config.runtime_id),
                    );
                    let _ = child.kill();
                    let _ = child.wait();
                }
            },
            Err(error) => append_log(
                &state.inner.log_path,
                &format!("managed {} restart spawn failed: {error}", config.runtime_id),
            ),
        }
    }
}
impl Drop for CoreProcessInner {
    fn drop(&mut self) {
        stop_core_inner(self, "desktop process dropped; stopping Python core child process");
    }
}

fn supervise_core(state: CoreProcess) {
    let mut failed_restarts = 0u32;
    loop {
        std::thread::sleep(Duration::from_millis(500));
        if state.inner.stopping.load(Ordering::SeqCst) {
            return;
        }

        let exited = match state.inner.child.lock() {
            Ok(mut guard) => match guard.as_mut() {
                Some(child) => match child.try_wait() {
                    Ok(Some(status)) => {
                        append_log(
                            &state.inner.log_path,
                            &format!("Python core exited unexpectedly: {status}"),
                        );
                        *guard = None;
                        true
                    }
                    Ok(None) => false,
                    Err(error) => {
                        append_log(
                            &state.inner.log_path,
                            &format!("core process health poll failed: {error}"),
                        );
                        *guard = None;
                        true
                    }
                },
                None => true,
            },
            Err(_) => return,
        };
        if !exited {
            continue;
        }

        if failed_restarts >= 5 {
            append_log(
                &state.inner.log_path,
                "core restart limit reached; desktop will keep the core stopped",
            );
            return;
        }
        failed_restarts += 1;
        std::thread::sleep(Duration::from_millis(500 * failed_restarts as u64));
        if state.inner.stopping.load(Ordering::SeqCst) {
            return;
        }
        match spawn_core(&state.inner.log_path, &state.inner.host, state.inner.port) {
            Ok(mut child) => match core_ready(&mut child, &state.inner.host, state.inner.port) {
                Ok(()) => {
                    let pid = child.id();
                    if let Ok(mut guard) = state.inner.child.lock() {
                        *guard = Some(child);
                        state.inner.restart_count.fetch_add(1, Ordering::SeqCst);
                        failed_restarts = 0;
                        append_log(
                            &state.inner.log_path,
                            &format!("Python core restarted and healthy; pid={pid}"),
                        );
                    } else {
                        let _ = child.kill();
                        let _ = child.wait();
                        return;
                    }
                }
                Err(error) => {
                    append_log(
                        &state.inner.log_path,
                        &format!("core restart health check failed: {error}"),
                    );
                    let _ = child.kill();
                    let _ = child.wait();
                }
            },
            Err(error) => append_log(
                &state.inner.log_path,
                &format!("core restart spawn failed: {error}"),
            ),
        }
    }
}

#[derive(serde::Serialize)]
struct CoreStatus {
    host: String,
    port: u16,
    pid: Option<u32>,
    running: bool,
    restart_count: u32,
    log_path: String,
    agent_runtime_id: String,
    agent_endpoint: String,
    agent_pid: Option<u32>,
    agent_running: bool,
    agent_restart_count: u32,
    agent_managed: bool,
}

#[tauri::command]
fn core_status(state: State<'_, CoreProcess>, agent: State<'_, AgentProcess>) -> CoreStatus {
    let (pid, running) = match state.inner.child.lock() {
        Ok(mut guard) => match guard.as_mut() {
            Some(child) => {
                let running = child.try_wait().map(|result| result.is_none()).unwrap_or(false);
                (Some(child.id()), running)
            }
            None => (None, false),
        },
        Err(_) => (None, false),
    };
    CoreStatus {
        host: state.inner.host.clone(),
        port: state.inner.port,
        pid,
        running,
        restart_count: state.inner.restart_count.load(Ordering::SeqCst),
        log_path: state.inner.log_path.display().to_string(),
        agent_runtime_id: agent.inner.runtime_id.clone(),
        agent_endpoint: agent.inner.endpoint.clone(),
        agent_pid: match agent.inner.child.lock() {
            Ok(mut guard) => guard.as_mut().and_then(|child| child.try_wait().ok().and_then(|status| if status.is_none() { Some(child.id()) } else { None })),
            Err(_) => None,
        },
        agent_running: match agent.inner.child.lock() {
            Ok(mut guard) => guard.as_mut().map(|child| child.try_wait().map(|status| status.is_none()).unwrap_or(false)).unwrap_or(false),
            Err(_) => false,
        },
        agent_restart_count: agent.inner.restart_count.load(Ordering::SeqCst),
        agent_managed: agent.inner.child.lock().map(|guard| guard.is_some()).unwrap_or(false),
    }
}

#[tauri::command]
fn show_overlay(app: AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window("overlay")
        .ok_or_else(|| "找不到桌面 Avatar 浮窗".to_string())?;
    window.show().map_err(|error| format!("显示 Avatar 浮窗失败: {error}"))?;
    window
        .set_focus()
        .map_err(|error| format!("聚焦 Avatar 浮窗失败: {error}"))?;
    Ok(())
}

#[tauri::command]
fn hide_overlay(app: AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window("overlay")
        .ok_or_else(|| "找不到桌面 Avatar 浮窗".to_string())?;
    window.hide().map_err(|error| format!("隐藏 Avatar 浮窗失败: {error}"))?;
    Ok(())
}

#[tauri::command]
fn open_main_window(app: AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "找不到 Sumika 主窗口".to_string())?;
    window.show().map_err(|error| format!("显示 Sumika 主窗口失败: {error}"))?;
    window
        .set_focus()
        .map_err(|error| format!("聚焦 Sumika 主窗口失败: {error}"))?;
    Ok(())
}

fn setup(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let root = repository_root().map_err(std::io::Error::other)?;
    let (host, port) = core_endpoint();
    let log_dir = root.join(".sumika-desktop").join("logs");
    std::fs::create_dir_all(&log_dir)?;
    let log_path = log_dir.join("desktop.log");
    append_log(
        &log_path,
        &format!("desktop setup started; data_dir=.sumika-desktop; core={host}:{port}"),
    );
    let (agent_runtime_id, agent_log_path, agent_launcher) =
        agent_launch_config(&root, &log_dir).map_err(std::io::Error::other)?;
    let managed_agent = if let Some(config) = &agent_launcher {
        append_log(
            &agent_log_path,
            &format!(
                "managed {} autostart requested; endpoint={}; profile={}",
                config.runtime_id,
                config.endpoint,
                config.profile_dir.display()
            ),
        );
        let mut child = spawn_agent(config).map_err(std::io::Error::other)?;
        append_log(
            &agent_log_path,
            &format!("managed {} spawned; pid={}", config.runtime_id, child.id()),
        );
        if let Err(error) = agent_ready(&mut child, config) {
            append_log(
                &agent_log_path,
                &format!("managed {} health check failed: {error}", config.runtime_id),
            );
            let _ = child.kill();
            let _ = child.wait();
            return Err(std::io::Error::other(error).into());
        }
        append_log(
            &agent_log_path,
            &format!("managed {} health check passed", config.runtime_id),
        );
        Some(child)
    } else {
        append_log(
            &agent_log_path,
            &format!(
                "managed {} autostart disabled; using external endpoint if available",
                agent_runtime_id
            ),
        );
        None
    };
    let agent_endpoint = agent_launcher
        .as_ref()
        .map(|config| config.endpoint.clone())
        .unwrap_or_else(|| configured_agent_endpoint(&agent_runtime_id));
    let agent = AgentProcess {
        inner: Arc::new(AgentProcessInner {
            child: Mutex::new(managed_agent),
            log_path: agent_log_path,
            runtime_id: agent_runtime_id,
            endpoint: agent_endpoint,
            launcher: agent_launcher,
            stopping: AtomicBool::new(false),
            restart_count: AtomicU32::new(0),
        }),
    };
    let mut child = match spawn_core(&log_path, &host, port) {
        Ok(child) => child,
        Err(error) => {
            append_log(&log_path, &format!("core spawn failed: {error}"));
            return Err(std::io::Error::other(error).into());
        }
    };
    append_log(&log_path, &format!("Python core spawned; pid={}", child.id()));
    if let Err(error) = core_ready(&mut child, &host, port) {
        append_log(&log_path, &format!("core health check failed: {error}"));
        let _ = child.kill();
        let _ = child.wait();
        return Err(std::io::Error::other(error).into());
    }
    append_log(&log_path, &format!("core health check passed on {host}:{port}"));
    let state = CoreProcess {
        inner: Arc::new(CoreProcessInner {
            child: Mutex::new(Some(child)),
            log_path,
            host,
            port,
            stopping: AtomicBool::new(false),
            restart_count: AtomicU32::new(0),
        }),
    };
    app.manage(state.clone());
    app.manage(agent.clone());
    if let Some(window) = app.get_webview_window("main") {
        let app_handle = app.handle().clone();
        let close_log_path = state.inner.log_path.clone();
        window.on_window_event(move |event| {
            if matches!(event, WindowEvent::CloseRequested { .. }) {
                append_log(
                    &close_log_path,
                    "main window close requested; exiting desktop application",
                );
                app_handle.exit(0);
            }
        });
    }
    std::thread::Builder::new()
        .name("sumika-core-supervisor".to_string())
        .spawn(move || supervise_core(state))?;
    if agent.inner.child.lock().map(|guard| guard.is_some()).unwrap_or(false) {
        let supervised_agent = agent.clone();
        std::thread::Builder::new()
            .name("sumika-agent-supervisor".to_string())
            .spawn(move || supervise_agent(supervised_agent))?;
    }
    let _ = app.get_webview_window("main");
    Ok(())
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            show_overlay,
            hide_overlay,
            open_main_window,
            core_status
        ])
        .setup(setup)
        .build(tauri::generate_context!())
        .expect("failed to build Sumika desktop shell");
    app.run(|app: &AppHandle, event: RunEvent| {
        if let RunEvent::Exit = event {
            if let Some(state) = app.try_state::<CoreProcess>() {
                stop_core(&state);
            }
            if let Some(agent) = app.try_state::<AgentProcess>() {
                stop_agent(&agent);
            }
        }
    });
}
