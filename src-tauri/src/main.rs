#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod consultation;
mod embedded_browser;

use std::env;
use std::fs::OpenOptions;
use std::io::{ErrorKind, Read, Write};
use std::net::{SocketAddr, TcpStream, ToSocketAddrs};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{
    atomic::{AtomicBool, AtomicU32, Ordering},
    Arc, Mutex,
};
use std::time::{Duration, Instant};

use tauri::{
    AppHandle, Emitter, Manager, PhysicalPosition, PhysicalSize, RunEvent, State, Webview,
    Window, WindowEvent,
};

const PET_WIDTH: u32 = 480;
const PET_HEIGHT: u32 = 420;

const DSH_CREDENTIAL_PROTOCOL_MAGIC: &[u8] = b"SUMIKA_DSH_CREDENTIAL_V2";
const LOCAL_DSH_CREDENTIAL_REF: &str = "SUMIKA_LOCAL_PROVIDER_API_KEY";
const LOCAL_DSH_CREDENTIAL_VALUE: &str = "sumika-local";
const PINNED_DSH_VERSION: &str = "0.1.1-rc.2";
const PINNED_DSH_EXECUTABLE: &str =
    r"D:\Tools\DeepSeekHarness\0.1.1-rc.2\node_modules\.bin\dsh.cmd";

#[derive(Clone)]
struct CoreProcess {
    inner: Arc<CoreProcessInner>,
}

struct CoreProcessInner {
    child: Mutex<Option<Child>>,
    log_path: PathBuf,
    host: String,
    port: u16,
    mcp_credential_refs: Vec<String>,
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
    verified_version: String,
    endpoint: String,
    profile_dir: PathBuf,
    log_path: PathBuf,
    args: Vec<String>,
    environment: Vec<(String, String)>,
    protected_credential_loaded: bool,
    protected_credential_error: Option<String>,
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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum DisplayMode {
    Workspace,
    Pet,
}

impl DisplayMode {
    fn as_str(self) -> &'static str {
        match self {
            Self::Workspace => "workspace",
            Self::Pet => "pet",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct WindowSnapshot {
    x: i32,
    y: i32,
    width: u32,
    height: u32,
    maximized: bool,
    minimized: bool,
}

struct DisplayModeState(Mutex<DisplayModeStateInner>);

struct DisplayModeStateInner {
    mode: DisplayMode,
    workspace: WindowSnapshot,
    pet: Option<WindowSnapshot>,
    needs_recovery: bool,
}

trait DisplayWindow {
    fn snapshot(&self, fallback: WindowSnapshot) -> Result<WindowSnapshot, String>;
    fn scale_factor(&self) -> Result<f64, String>;
    fn apply(&self, mode: DisplayMode, snapshot: WindowSnapshot) -> Result<(), String>;
}

fn parse_display_mode(value: &str) -> Result<DisplayMode, String> {
    match value {
        "workspace" => Ok(DisplayMode::Workspace),
        "pet" => Ok(DisplayMode::Pet),
        _ => Err("display mode 只允许 workspace 或 pet".to_string()),
    }
}

fn default_window_snapshot() -> WindowSnapshot {
    WindowSnapshot {
        x: 0,
        y: 0,
        width: 1440,
        height: 900,
        maximized: false,
        minimized: false,
    }
}

impl DisplayModeStateInner {
    fn new(workspace: WindowSnapshot) -> Self {
        Self {
            mode: DisplayMode::Workspace,
            workspace,
            pet: None,
            needs_recovery: false,
        }
    }

    fn mode(&self) -> Result<String, String> {
        if self.needs_recovery {
            Err("窗口恢复未完成，请调用 set_display_mode({mode: workspace}) 恢复".to_string())
        } else {
            Ok(self.mode.as_str().to_string())
        }
    }

    fn transition(
        &mut self,
        window: &impl DisplayWindow,
        target: DisplayMode,
        minimize: bool,
    ) -> Result<String, String> {
        if self.needs_recovery {
            if target != DisplayMode::Workspace {
                return Err("窗口恢复未完成，只允许恢复 workspace".to_string());
            }
            let snapshot = WindowSnapshot { minimized: minimize, ..self.workspace };
            window.apply(DisplayMode::Workspace, snapshot)?;
            self.mode = DisplayMode::Workspace;
            self.needs_recovery = false;
            return self.mode();
        }
        if self.mode == target && !minimize {
            return self.mode();
        }

        let fallback = match self.mode {
            DisplayMode::Workspace => self.workspace,
            DisplayMode::Pet => self.pet.unwrap_or(self.workspace),
        };
        let previous = window.snapshot(fallback)?;
        if target == DisplayMode::Pet && previous.minimized {
            return Err("主窗口已最小化，请从任务栏恢复后再切换 pet".to_string());
        }
        let workspace = if self.mode == DisplayMode::Workspace {
            previous
        } else {
            self.workspace
        };
        let next = match target {
            DisplayMode::Workspace => WindowSnapshot { minimized: minimize, ..workspace },
            DisplayMode::Pet => self.pet.unwrap_or(WindowSnapshot {
                width: (f64::from(PET_WIDTH) * window.scale_factor()?).round() as u32,
                height: (f64::from(PET_HEIGHT) * window.scale_factor()?).round() as u32,
                maximized: false,
                minimized: false,
                ..previous
            }),
        };

        if let Err(error) = window.apply(target, next) {
            if let Err(rollback) = window.apply(self.mode, previous) {
                self.workspace = workspace;
                self.needs_recovery = true;
                return Err(format!("{error}；回滚也失败: {rollback}；请恢复 workspace"));
            }
            return Err(format!("{error}；已恢复原窗口模式"));
        }

        self.workspace = workspace;
        if self.mode == DisplayMode::Pet {
            self.pet = Some(previous);
        }
        if target == DisplayMode::Pet {
            self.pet = Some(next);
        }
        self.mode = target;
        self.mode()
    }
}

impl DisplayWindow for Window {
    fn scale_factor(&self) -> Result<f64, String> {
        Window::scale_factor(self).map_err(|error| error.to_string())
    }

    fn snapshot(&self, fallback: WindowSnapshot) -> Result<WindowSnapshot, String> {
        if self.is_fullscreen().map_err(|error| error.to_string())? {
            return Err("请先退出系统全屏，再切换窗口模式".to_string());
        }
        let maximized = self.is_maximized().map_err(|error| error.to_string())?;
        let minimized = self.is_minimized().map_err(|error| error.to_string())?;
        if maximized || minimized {
            return Ok(WindowSnapshot { maximized, minimized, ..fallback });
        }
        let position = self.outer_position().map_err(|error| error.to_string())?;
        let size = self.inner_size().map_err(|error| error.to_string())?;
        Ok(WindowSnapshot {
            x: position.x,
            y: position.y,
            width: size.width,
            height: size.height,
            maximized,
            minimized,
        })
    }

    fn apply(&self, mode: DisplayMode, snapshot: WindowSnapshot) -> Result<(), String> {
        let pet = mode == DisplayMode::Pet;
        let mut errors = Vec::new();
        let mut record = |step: &str, result: tauri::Result<()>| {
            if let Err(error) = result {
                errors.push(format!("{step}: {error}"));
            }
        };
        record("退出最大化", self.unmaximize());
        record("窗口边框", self.set_decorations(!pet));
        record("窗口阴影", self.set_shadow(!pet));
        record("任务栏入口", self.set_skip_taskbar(pet));
        record("窗口缩放", self.set_resizable(true));
        let minimum = if pet { (320.0, 280.0) } else { (900.0, 640.0) };
        record(
            "最小尺寸",
            self.set_min_size(Some(tauri::LogicalSize::new(minimum.0, minimum.1))),
        );
        record("窗口位置", self.set_position(PhysicalPosition::new(snapshot.x, snapshot.y)));
        record("窗口尺寸", self.set_size(PhysicalSize::new(snapshot.width, snapshot.height)));
        record("窗口置顶", self.set_always_on_top(pet));
        if snapshot.maximized && !pet {
            record("恢复最大化", self.maximize());
        }
        if snapshot.minimized {
            record("最小化到任务栏", self.minimize());
        } else if self.is_minimized().map_err(|error| error.to_string())? {
            record("恢复最小化", self.unminimize());
        }
        if errors.is_empty() {
            Ok(())
        } else {
            Err(errors.join("；"))
        }
    }
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

fn development_python_path(root: &Path) -> Result<std::ffi::OsString, String> {
    let mut paths = vec![
        root.join("backend").join("src"),
        root.join("packages").join("quality-routing").join("src"),
    ];
    if let Some(inherited) = env::var_os("PYTHONPATH") {
        paths.extend(env::split_paths(&inherited));
    }
    env::join_paths(paths).map_err(|error| format!("无法构造开发态 PYTHONPATH: {error}"))
}

fn desktop_data_dir(root: &PathBuf) -> Result<PathBuf, String> {
    match env::var("SUMIKA_DESKTOP_DATA_DIR") {
        Ok(value) => {
            let path = PathBuf::from(value);
            if !path.is_absolute() {
                return Err("SUMIKA_DESKTOP_DATA_DIR must be an absolute path".to_string());
            }
            Ok(path)
        }
        Err(env::VarError::NotPresent) => Ok(root.join(".sumika-desktop")),
        Err(error) => Err(format!("Invalid SUMIKA_DESKTOP_DATA_DIR: {error}")),
    }
}

fn browser_skill_environment() -> Option<(String, String)> {
    let configured = env::var("SUMIKA_BSK_EXECUTABLE")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .map(PathBuf::from);
    let executable = match configured {
        Some(path) if path.is_file() => path,
        Some(_) => return None,
        None => {
            let pinned = PathBuf::from(r"D:\Tools\BrowserSkill\0.1.11\bsk.exe");
            if !pinned.is_file() {
                return None;
            }
            pinned
        }
    };
    let parent = executable.parent()?.to_path_buf();
    let current = env::var_os("PATH").unwrap_or_default();
    let already_present = env::split_paths(&current).any(|entry| {
        entry
            .to_string_lossy()
            .trim_end_matches(['\\', '/'])
            .eq_ignore_ascii_case(parent.to_string_lossy().trim_end_matches(['\\', '/']))
    });
    let path_value = if already_present {
        current.to_string_lossy().to_string()
    } else {
        let delimiter = if cfg!(windows) { ";" } else { ":" };
        format!(
            "{}{}{}",
            parent.to_string_lossy(),
            delimiter,
            current.to_string_lossy()
        )
    };
    Some((executable.to_string_lossy().to_string(), path_value))
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

fn spawn_core(
    log_path: &PathBuf,
    host: &str,
    port: u16,
    mcp_credential_refs: &[String],
) -> Result<Child, String> {
    let root = repository_root()?;
    let data_dir = desktop_data_dir(&root)?;
    std::fs::create_dir_all(&data_dir).map_err(|error| format!("创建桌面数据目录失败: {error}"))?;
    let python_path = development_python_path(&root)?;
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
        .env("SUMIKA_EMBEDDED_BROWSER", "1")
        .env("BSK_AUTO_UPDATE", "off")
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
    if let Some((executable, path_value)) = browser_skill_environment() {
        command
            .env("SUMIKA_BSK_EXECUTABLE", executable)
            .env("PATH", path_value);
    }
    if !mcp_credential_refs.is_empty() {
        command.env(
            "SUMIKA_DSH_MCP_CREDENTIAL_REFS",
            mcp_credential_refs.join(","),
        );
    }
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
    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n"
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

fn dsh_display_name(executable: &str) -> String {
    PathBuf::from(executable)
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty())
        .unwrap_or("<invalid-path>")
        .to_string()
}

fn first_nonempty_version_line(bytes: &[u8]) -> Option<String> {
    String::from_utf8_lossy(bytes)
        .lines()
        .map(str::trim)
        .find(|line| !line.is_empty())
        .map(|line| line.chars().take(128).collect())
}

fn dsh_version_command(executable: &str) -> Command {
    let extension = PathBuf::from(executable)
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.to_ascii_lowercase());
    if matches!(extension.as_deref(), Some("cmd" | "bat")) {
        let mut command = Command::new("cmd.exe");
        // `call` is required for batch files; quoting keeps spaces and shell
        // metacharacters in an explicitly configured path inert.
        // Keep the command and path as separate arguments. This lets Rust
        // apply Windows argument quoting without putting backslash-escaped
        // quotes into cmd.exe's `/c` command string.
        command.args(["/d", "/c", "call"]);
        command.arg(executable);
        command.arg("--version");
        command
    } else {
        let mut command = Command::new(executable);
        command.arg("--version");
        command
    }
}

fn validate_dsh_executable(executable: &str) -> Result<String, String> {
    let display_name = dsh_display_name(executable);
    let path = PathBuf::from(executable);
    if !path.is_absolute() {
        return Err(format!(
            "DSH executable '{display_name}' rejected [path-not-absolute]"
        ));
    }
    if !path.is_file() {
        return Err(format!(
            "DSH executable '{display_name}' rejected [path-not-found]"
        ));
    }
    if executable.chars().any(|value| value.is_control() || value == '\n' || value == '\r') {
        return Err(format!(
            "DSH executable '{display_name}' rejected [path-invalid]"
        ));
    }

    let output = dsh_version_command(executable)
        .stdin(Stdio::null())
        .output()
        .map_err(|_| {
            format!(
                "DSH executable '{display_name}' rejected [version-command-failed]"
            )
        })?;
    if !output.status.success() {
        return Err(format!(
            "DSH executable '{display_name}' rejected [version-command-failed]"
        ));
    }
    let actual = first_nonempty_version_line(&output.stdout)
        .or_else(|| first_nonempty_version_line(&output.stderr))
        .ok_or_else(|| {
            format!(
                "DSH executable '{display_name}' rejected [version-output-empty]"
            )
        })?;
    if actual != PINNED_DSH_VERSION {
        return Err(format!(
            "DSH executable '{display_name}' rejected [version-mismatch]: expected '{PINNED_DSH_VERSION}', actual '{actual}'"
        ));
    }
    Ok(actual)
}

fn dsh_launch_config(root: &PathBuf, log_dir: &PathBuf) -> Result<AgentLaunchConfig, String> {
    let endpoint = configured_agent_endpoint("dsh");
    let executable = first_nonempty_env(&["SUMIKA_AGENT_EXECUTABLE", "SUMIKA_DSH_EXECUTABLE"])
        .unwrap_or_else(|| PINNED_DSH_EXECUTABLE.to_string());
    let verified_version = validate_dsh_executable(&executable)?;
    let profile_dir = first_nonempty_env(&[
        "SUMIKA_AGENT_PROFILE_DIR",
        "SUMIKA_DSH_PROFILE_DIR",
        "SUMIKA_DSH_HOME",
    ])
    .map(PathBuf::from)
    .unwrap_or(desktop_data_dir(root)?.join("dsh-profile"));
    let port = agent_port(&endpoint, 3080)
        .ok_or_else(|| format!("无法从 DSH endpoint 解析端口: {endpoint}"))?;
    let (core_host, core_port) = core_endpoint();
    let profile_text = profile_dir.to_string_lossy().to_string();
    let (protected_credentials, protected_credential_error) =
        match load_dsh_launch_credentials(root, &profile_dir) {
            Ok(value) => (value, None),
            Err(error) => (Vec::new(), Some(error)),
        };
    let protected_credential_loaded = !protected_credentials.is_empty();
    let mut environment = vec![
        ("DSH_HOME".to_string(), profile_text.clone()),
        ("SUMIKA_DSH_HOME".to_string(), profile_text),
        ("SUMIKA_DSH_VERSION_VERIFIED".to_string(), "1".to_string()),
        ("BSK_AUTO_UPDATE".to_string(), "off".to_string()),
        ("SUMIKA_CORE_HOST".to_string(), core_host),
        ("SUMIKA_CORE_PORT".to_string(), core_port.to_string()),
        (
            LOCAL_DSH_CREDENTIAL_REF.to_string(),
            LOCAL_DSH_CREDENTIAL_VALUE.to_string(),
        ),
    ];
    if let Some((browser_skill_executable, path_value)) = browser_skill_environment() {
        // The official BrowserSkill DSH plugin resolves `bsk` from PATH. Keep
        // the explicit executable reference for Core and pass both values only
        // to this managed runtime child.
        environment.push((
            "SUMIKA_BSK_EXECUTABLE".to_string(),
            browser_skill_executable,
        ));
        environment.push(("PATH".to_string(), path_value));
    }
    for (name, value) in protected_credentials {
        environment.push((name, value));
    }
    Ok(AgentLaunchConfig {
        runtime_id: "dsh".to_string(),
        executable,
        verified_version,
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
        environment,
        protected_credential_loaded,
        protected_credential_error,
        health_path: "/api/host.describe".to_string(),
        health_body: r#"{"type":"client-request","rpcId":"sumika-health","method":"host.describe","payload":{}}"#.to_string(),
        default_port: 3080,
    })
}

fn load_dsh_launch_credentials(
    root: &PathBuf,
    profile_dir: &PathBuf,
) -> Result<Vec<(String, String)>, String> {
    let data_dir = desktop_data_dir(root)?;
    let python_path = development_python_path(root)?;
    let output = Command::new(python_command())
        .current_dir(root)
        .env("PYTHONPATH", python_path)
        .args([
            "-m",
            "sumika_core.agent.credential_binding",
            "--data-dir",
            &data_dir.to_string_lossy(),
            "--profile-dir",
            &profile_dir.to_string_lossy(),
        ])
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .map_err(|_| "protected credential bridge could not be started".to_string())?;
    if !output.status.success() {
        return Err("protected credential bridge failed closed".to_string());
    }
    parse_dsh_credential_bindings(&output.stdout)
}

fn parse_dsh_credential_bindings(payload: &[u8]) -> Result<Vec<(String, String)>, String> {
    if payload.len() > 24 * 1024 {
        return Err("protected credential bridge returned an oversized response".to_string());
    }
    let fields: Vec<&[u8]> = payload.split(|byte| *byte == 0).collect();
    if fields.first().copied() != Some(DSH_CREDENTIAL_PROTOCOL_MAGIC) {
        return Err("protected credential bridge returned an invalid protocol".to_string());
    }
    if fields.len() < 4 || fields[1] != b"loaded" || !fields.last().is_some_and(|value| value.is_empty()) {
        return Err("protected credential bridge returned an invalid payload".to_string());
    }
    let count = std::str::from_utf8(fields[2])
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value <= 33)
        .ok_or_else(|| "protected credential bridge returned an invalid count".to_string())?;
    if fields.len() != 4 + count * 2 {
        return Err("protected credential bridge returned an invalid payload".to_string());
    }
    let mut result = Vec::with_capacity(count);
    let mut names = std::collections::HashSet::new();
    for index in 0..count {
        let name_field = fields[3 + index * 2];
        let value_field = fields[4 + index * 2];
        let name = std::str::from_utf8(name_field)
            .map_err(|_| "protected credential bridge returned an invalid name".to_string())?;
        if !valid_protected_environment_name(name)
            || !names.insert(name.to_string())
            || value_field.is_empty()
            || value_field.len() > 8192
        {
            return Err("protected credential bridge returned invalid credential metadata".to_string());
        }
        let value = String::from_utf8(value_field.to_vec())
            .map_err(|_| "protected credential bridge returned an invalid value".to_string())?;
        result.push((name.to_string(), value));
    }
    Ok(result)
}

fn valid_protected_environment_name(name: &str) -> bool {
    let safe = name.starts_with("SUMIKA_")
        && name
            .chars()
            .enumerate()
            .all(|(index, character)| character.is_ascii_alphanumeric() || character == '_' && index > 0);
    let provider = name.ends_with("_API_KEY");
    let mcp = name
        .strip_prefix("SUMIKA_MCP_")
        .and_then(|value| value.strip_suffix("_SECRET"))
        .is_some_and(|digest| digest.len() == 24 && digest.chars().all(|character| character.is_ascii_hexdigit() && !character.is_ascii_lowercase()));
    safe && (provider || mcp)
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
    if stream.read_to_string(&mut response).is_err()
        || !response
            .lines()
            .next()
            .map(|line| line.contains(" 200 "))
            .unwrap_or(false)
    {
        return false;
    }
    // host.describe is the protocol health evidence. A bare HTTP 200 from a
    // proxy or unrelated service must not make the launcher claim readiness.
    response.contains("\"ok\": true") || response.contains("\"ok\":true")
}

fn spawn_agent(config: &AgentLaunchConfig) -> Result<Child, String> {
    let verified_version = validate_dsh_executable(&config.executable)?;
    if verified_version != config.verified_version {
        return Err(format!(
            "DSH executable '{}' changed after configuration [version-mismatch]",
            dsh_display_name(&config.executable)
        ));
    }
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
        match spawn_core(
            &state.inner.log_path,
            &state.inner.host,
            state.inner.port,
            &state.inner.mcp_credential_refs,
        ) {
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
    agent_protected_credential_loaded: bool,
    agent_protected_credential_error: bool,
}

#[tauri::command]
async fn core_status(
    caller: Webview,
    state: State<'_, CoreProcess>,
    agent: State<'_, AgentProcess>,
) -> Result<CoreStatus, String> {
    consultation::authorize_main_caller(&caller)?;
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
    Ok(CoreStatus {
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
        agent_protected_credential_loaded: agent
            .inner
            .launcher
            .as_ref()
            .map(|config| config.protected_credential_loaded)
            .unwrap_or(false),
        agent_protected_credential_error: agent
            .inner
            .launcher
            .as_ref()
            .and_then(|config| config.protected_credential_error.as_ref())
            .is_some(),
    })
}

#[derive(Clone, Copy)]
enum DisplayAction {
    Set(DisplayMode),
    Get,
    Drag,
    Hide,
    Open,
}

async fn run_display_action(caller: Webview, action: DisplayAction) -> Result<String, String> {
    consultation::authorize_main_caller(&caller)?;
    let window = caller.window();
    let (sender, mut receiver) = tauri::async_runtime::channel(1);
    let handle = caller.app_handle().clone();
    handle.run_on_main_thread(move || {
        let result = (|| {
            let state = window.state::<DisplayModeState>();
            let mut state = state.0.try_lock().map_err(|_| "窗口模式正在操作，请稍后重试".to_string())?;
            let previous = state.mode;
            let result = match action {
                DisplayAction::Get => state.mode(),
                DisplayAction::Set(target) => state.transition(&window, target, false),
                DisplayAction::Hide => state.transition(&window, DisplayMode::Workspace, true),
                DisplayAction::Open => {
                    let mode = state.transition(&window, DisplayMode::Workspace, false)?;
                    window.unminimize().map_err(|error| error.to_string())?;
                    window.show().map_err(|error| error.to_string())?;
                    window.set_focus().map_err(|error| error.to_string())?;
                    Ok(mode)
                }
                DisplayAction::Drag => {
                    state.mode()?;
                    if state.mode != DisplayMode::Pet {
                        return Err("原生拖动只允许在 pet 模式使用".to_string());
                    }
                    window.start_dragging().map_err(|error| error.to_string())?;
                    state.mode()
                }
            };
            let changed = previous != state.mode;
            let mode = state.mode();
            drop(state);
            if changed {
                if let Ok(mode) = mode {
                    let _ = window.emit("display-mode-changed", mode);
                }
            }
            result
        })();
        let _ = sender.try_send(result);
    }).map_err(|error| format!("调度窗口操作失败: {error}"))?;
    receiver.recv().await.ok_or_else(|| "窗口操作已取消".to_string())?
}

#[tauri::command]
async fn set_display_mode(caller: Webview, app: AppHandle, mode: String) -> Result<String, String> {
    consultation::authorize_main_caller(&caller)?;
    if mode == "pet" { embedded_browser::hide_children(&app)?; }
    run_display_action(caller, DisplayAction::Set(parse_display_mode(&mode)?)).await
}

#[tauri::command]
async fn get_display_mode(caller: Webview) -> Result<String, String> {
    run_display_action(caller, DisplayAction::Get).await
}

#[tauri::command]
async fn start_pet_drag(caller: Webview) -> Result<(), String> {
    run_display_action(caller, DisplayAction::Drag).await.map(|_| ())
}

#[tauri::command]
async fn hide_pet(caller: Webview) -> Result<String, String> {
    run_display_action(caller, DisplayAction::Hide).await
}

#[tauri::command]
async fn show_overlay(caller: Webview) -> Result<(), String> {
    run_display_action(caller, DisplayAction::Set(DisplayMode::Pet)).await.map(|_| ())
}

#[tauri::command]
async fn hide_overlay(caller: Webview) -> Result<(), String> {
    run_display_action(caller, DisplayAction::Hide).await.map(|_| ())
}

#[tauri::command]
async fn open_main_window(caller: Webview) -> Result<(), String> {
    run_display_action(caller, DisplayAction::Open).await.map(|_| ())
}

fn validate_portal_site_id(site_id: &str) -> Result<(), String> {
    let valid = !site_id.is_empty()
        && site_id.len() <= 48
        && !site_id.starts_with('-')
        && site_id
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || character == '-' || character == '_');
    if valid {
        Ok(())
    } else {
        Err("站点 ID 只能包含字母、数字、短横线或下划线，最长 48 字符".to_string())
    }
}

fn validate_portal_url(url: &str) -> Result<tauri::Url, String> {
    embedded_browser::validate_url(url)
}

#[tauri::command]
async fn open_portal(
    caller: Webview,
    app: AppHandle,
    site_id: String,
    title: String,
    url: String,
) -> Result<(), String> {
    consultation::authorize_main_caller(&caller)?;
    validate_portal_site_id(&site_id)?;
    let parsed = validate_portal_url(&url)?;
    embedded_browser::open(&app, &app.state::<embedded_browser::EmbeddedBrowserState>(), format!("portal-{site_id}"), site_id.clone(), parsed.to_string(), title, None, Some(site_id)).await.map(|_| ())
}

#[tauri::command]
async fn focus_portal(caller: Webview, app: AppHandle, site_id: String) -> Result<(), String> {
    consultation::authorize_main_caller(&caller)?;
    validate_portal_site_id(&site_id)?;
    embedded_browser::focus_portal(&app, &app.state::<embedded_browser::EmbeddedBrowserState>(), &site_id).await
}

#[tauri::command]
async fn close_portal(caller: Webview, app: AppHandle, site_id: String) -> Result<(), String> {
    consultation::authorize_main_caller(&caller)?;
    validate_portal_site_id(&site_id)?;
    embedded_browser::close(&app, &app.state::<embedded_browser::EmbeddedBrowserState>(), &format!("portal-{site_id}")).await.map(|_| ())
}

#[derive(serde::Serialize)]
struct PortalWindowEntry {
    site_id: String,
    title: String,
}

#[tauri::command]
async fn portal_list(caller: Webview, app: AppHandle) -> Result<Vec<PortalWindowEntry>, String> {
    consultation::authorize_main_caller(&caller)?;
    let mut entries: Vec<PortalWindowEntry> = embedded_browser::list(&app.state::<embedded_browser::EmbeddedBrowserState>())?
        .into_iter().filter(|tab| tab.opened).filter_map(|tab| tab.site_id.map(|site_id| PortalWindowEntry { site_id, title: tab.title })).collect();
    entries.sort_by(|left, right| left.site_id.cmp(&right.site_id));
    Ok(entries)
}

fn setup(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let window = app.get_window("main").ok_or("找不到 Sumika 主窗口")?;
    let snapshot = window.snapshot(default_window_snapshot()).map_err(std::io::Error::other)?;
    app.manage(DisplayModeState(Mutex::new(DisplayModeStateInner::new(snapshot))));
    let root = repository_root().map_err(std::io::Error::other)?;
    let consultation_state = consultation::ConsultationState::new(
        &desktop_data_dir(&root).map_err(std::io::Error::other)?,
    )
    .map_err(std::io::Error::other)?;
    app.manage(consultation_state);
    app.manage(embedded_browser::EmbeddedBrowserState::new(&desktop_data_dir(&root).map_err(std::io::Error::other)?).map_err(std::io::Error::other)?);
    let (host, port) = core_endpoint();
    let log_dir = desktop_data_dir(&root).map_err(std::io::Error::other)?.join("logs");
    std::fs::create_dir_all(&log_dir)?;
    let log_path = log_dir.join("desktop.log");
    append_log(
        &log_path,
        &format!("desktop setup started; core={host}:{port}"),
    );
    let (agent_runtime_id, agent_log_path, agent_launcher) = match agent_launch_config(&root, &log_dir) {
        Ok(value) => value,
        Err(error) => {
            append_log(&log_dir.join("dsh.log"), &format!("managed DSH launch rejected: {error}"));
            return Err(std::io::Error::other(error).into());
        }
    };
    let managed_agent = if let Some(config) = &agent_launcher {
        append_log(
            &agent_log_path,
            &format!(
                "DSH executable validated; name={}; expected={}; actual={}",
                dsh_display_name(&config.executable),
                PINNED_DSH_VERSION,
                config.verified_version,
            ),
        );
        append_log(
            &agent_log_path,
            &format!(
                "managed {} autostart requested; endpoint={}; profile={}; protected_credential_loaded={}",
                config.runtime_id,
                config.endpoint,
                config.profile_dir.display(),
                config.protected_credential_loaded,
            ),
        );
        if config.protected_credential_error.is_some() {
            append_log(
                &agent_log_path,
                "one or more protected Agent credentials were not loaded; affected Provider or MCP connections will fail closed",
            );
        }
        let mut child = match spawn_agent(config) {
            Ok(child) => child,
            Err(error) => {
                append_log(&agent_log_path, &format!("managed DSH spawn rejected: {error}"));
                return Err(std::io::Error::other(error).into());
            }
        };
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
    let mcp_credential_refs = agent_launcher
        .as_ref()
        .map(|config| {
            config
                .environment
                .iter()
                .filter_map(|(name, _)| {
                    (name.starts_with("SUMIKA_MCP_") && name.ends_with("_SECRET"))
                        .then(|| name.clone())
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
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
    let mut child = match spawn_core(&log_path, &host, port, &mcp_credential_refs) {
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
            mcp_credential_refs,
            stopping: AtomicBool::new(false),
            restart_count: AtomicU32::new(0),
        }),
    };
    app.manage(state.clone());
    app.manage(agent.clone());
    if let Some(window) = app.get_window("main") {
        let app_handle = app.handle().clone();
        let close_log_path = state.inner.log_path.clone();
        let observed_window = window.clone();
        window.on_window_event(move |event| {
            if matches!(event, WindowEvent::Moved(_) | WindowEvent::Resized(_)) {
                if observed_window.is_minimized().unwrap_or(false) { let _ = embedded_browser::hide_children(&app_handle); }
                let state = observed_window.state::<DisplayModeState>();
                if let Ok(mut state) = state.0.try_lock() {
                    if state.mode == DisplayMode::Workspace && !state.needs_recovery {
                        if let Ok(snapshot) = observed_window.snapshot(state.workspace) {
                            state.workspace = snapshot;
                        }
                    }
                };
            }
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
    let _ = app.get_webview("main");
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::cell::{Cell, RefCell};
    use std::path::PathBuf;

    use super::{
        first_nonempty_version_line, parse_dsh_credential_bindings, validate_dsh_executable,
        validate_portal_site_id, validate_portal_url, DSH_CREDENTIAL_PROTOCOL_MAGIC,
        PINNED_DSH_EXECUTABLE, PINNED_DSH_VERSION, DisplayMode, DisplayModeStateInner,
        DisplayWindow, WindowSnapshot, default_window_snapshot, parse_display_mode,
    };

    struct TestWindow {
        current: Cell<WindowSnapshot>,
        failures: Cell<usize>,
        calls: RefCell<Vec<DisplayMode>>,
    }

    impl TestWindow {
        fn new(snapshot: WindowSnapshot) -> Self {
            Self { current: Cell::new(snapshot), failures: Cell::new(0), calls: RefCell::new(Vec::new()) }
        }
    }

    impl DisplayWindow for TestWindow {
        fn snapshot(&self, _: WindowSnapshot) -> Result<WindowSnapshot, String> { Ok(self.current.get()) }
        fn scale_factor(&self) -> Result<f64, String> { Ok(1.5) }
        fn apply(&self, mode: DisplayMode, snapshot: WindowSnapshot) -> Result<(), String> {
            self.calls.borrow_mut().push(mode);
            self.current.set(snapshot);
            if self.failures.get() > 0 {
                self.failures.set(self.failures.get() - 1);
                Err("injected partial window failure".to_string())
            } else { Ok(()) }
        }
    }

    #[test]
    fn display_mode_commands_reject_unknown_modes() {
        assert_eq!(parse_display_mode("pet").unwrap(), DisplayMode::Pet);
        assert!(parse_display_mode("wallpaper").is_err());
    }

    #[test]
    fn display_modes_restore_workspace_and_pet_bounds_without_recreating_state() {
        let original = WindowSnapshot { x: 180, y: 90, maximized: true, ..default_window_snapshot() };
        let window = TestWindow::new(original);
        let mut state = DisplayModeStateInner::new(original);
        assert_eq!(state.transition(&window, DisplayMode::Pet, false).unwrap(), "pet");
        assert_eq!((window.current.get().width, window.current.get().height), (720, 630));
        let moved_pet = WindowSnapshot { x: 20, y: 40, ..window.current.get() };
        window.current.set(moved_pet);
        state.transition(&window, DisplayMode::Workspace, false).unwrap();
        assert_eq!(window.current.get(), original);
        state.transition(&window, DisplayMode::Pet, false).unwrap();
        assert_eq!(window.current.get(), moved_pet);
        let calls = window.calls.borrow().len();
        state.transition(&window, DisplayMode::Pet, false).unwrap();
        assert_eq!(window.calls.borrow().len(), calls);
    }

    #[test]
    fn failed_mode_change_rolls_back_and_does_not_publish_success() {
        let original = default_window_snapshot();
        let window = TestWindow::new(original);
        let mut state = DisplayModeStateInner::new(original);
        window.failures.set(1);
        assert!(state.transition(&window, DisplayMode::Pet, false).is_err());
        assert_eq!(state.mode().unwrap(), "workspace");
        assert_eq!(window.current.get(), original);
        assert_eq!(*window.calls.borrow(), vec![DisplayMode::Pet, DisplayMode::Workspace]);
        window.failures.set(2);
        assert!(state.transition(&window, DisplayMode::Pet, false).is_err());
        assert!(state.mode().is_err());
        assert!(state.transition(&window, DisplayMode::Pet, false).is_err());
        assert_eq!(state.transition(&window, DisplayMode::Workspace, false).unwrap(), "workspace");
    }

    #[test]
    fn hidden_pet_returns_to_minimized_workspace_with_taskbar_recovery() {
        let original = default_window_snapshot();
        let window = TestWindow::new(original);
        let mut state = DisplayModeStateInner::new(original);
        state.transition(&window, DisplayMode::Pet, false).unwrap();
        state.transition(&window, DisplayMode::Workspace, true).unwrap();
        assert!(window.current.get().minimized);
        assert_eq!(window.current.get().width, original.width);
        assert_eq!(state.mode().unwrap(), "workspace");
        assert!(state.transition(&window, DisplayMode::Pet, false).is_err());
    }

    #[test]
    fn parses_only_an_exact_dsh_version_line() {
        assert_eq!(
            first_nonempty_version_line(b"\n0.1.1-rc.2\n"),
            Some(PINNED_DSH_VERSION.to_string())
        );
        assert_ne!(
            first_nonempty_version_line(b"0.1.0-rc.6\n").as_deref(),
            Some(PINNED_DSH_VERSION)
        );
        assert_eq!(first_nonempty_version_line(b"\n\t"), None);
    }

    #[test]
    fn rejects_missing_or_path_based_dsh_candidates() {
        assert!(validate_dsh_executable("dsh.cmd")
            .unwrap_err()
            .contains("path-not-absolute"));
        let missing = PathBuf::from(PINNED_DSH_EXECUTABLE)
            .with_file_name("sumika-missing-dsh.cmd");
        assert!(validate_dsh_executable(&missing.to_string_lossy())
            .unwrap_err()
            .contains("path-not-found"));
    }

    #[test]
    fn validates_the_installed_pinned_cmd_launcher_when_available() {
        if !PathBuf::from(PINNED_DSH_EXECUTABLE).is_file() {
            return;
        }
        assert_eq!(
            validate_dsh_executable(PINNED_DSH_EXECUTABLE).unwrap(),
            PINNED_DSH_VERSION
        );
    }

    #[test]
    fn parses_empty_and_multiple_credential_protocol() {
        let none = [DSH_CREDENTIAL_PROTOCOL_MAGIC, b"loaded", b"0", b""].join(&0);
        assert_eq!(parse_dsh_credential_bindings(&none).unwrap(), Vec::new());

        let loaded = [
            DSH_CREDENTIAL_PROTOCOL_MAGIC,
            b"loaded",
            b"2",
            b"SUMIKA_1234_API_KEY",
            b"secret-value",
            b"SUMIKA_MCP_0123456789ABCDEF01234567_SECRET",
            b"mcp-secret",
            b"",
        ]
        .join(&0);
        assert_eq!(
            parse_dsh_credential_bindings(&loaded).unwrap(),
            vec![
                ("SUMIKA_1234_API_KEY".to_string(), "secret-value".to_string()),
                (
                    "SUMIKA_MCP_0123456789ABCDEF01234567_SECRET".to_string(),
                    "mcp-secret".to_string(),
                ),
            ]
        );
    }

    #[test]
    fn rejects_untrusted_environment_names() {
        let payload = [
            DSH_CREDENTIAL_PROTOCOL_MAGIC,
            b"loaded",
            b"1",
            b"PATH",
            b"value",
            b"",
        ]
        .join(&0);
        assert!(parse_dsh_credential_bindings(&payload).is_err());
    }

    #[test]
    fn rejects_duplicate_names_and_oversized_values() {
        let duplicate = [
            DSH_CREDENTIAL_PROTOCOL_MAGIC,
            b"loaded",
            b"2",
            b"SUMIKA_1234_API_KEY",
            b"first",
            b"SUMIKA_1234_API_KEY",
            b"second",
            b"",
        ]
        .join(&0);
        assert!(parse_dsh_credential_bindings(&duplicate).is_err());

        let mut oversized = [
            DSH_CREDENTIAL_PROTOCOL_MAGIC,
            b"loaded",
            b"1",
            b"SUMIKA_1234_API_KEY",
        ]
        .join(&0);
        oversized.push(0);
        oversized.extend(vec![b'x'; 8193]);
        oversized.push(0);
        assert!(parse_dsh_credential_bindings(&oversized).is_err());
    }

    #[test]
    fn portal_site_ids_reject_path_traversal_and_symbols() {
        assert!(validate_portal_site_id("kimi").is_ok());
        assert!(validate_portal_site_id("chatgpt-2").is_ok());
        assert!(validate_portal_site_id("site_1").is_ok());
        assert!(validate_portal_site_id("").is_err());
        assert!(validate_portal_site_id("-lead").is_err());
        assert!(validate_portal_site_id("../etc").is_err());
        assert!(validate_portal_site_id("white space").is_err());
        assert!(validate_portal_site_id("中文名").is_err());
        let oversized = "a".repeat(49);
        assert!(validate_portal_site_id(&oversized).is_err());
    }

    #[test]
    fn portal_urls_require_http_schemes() {
        assert!(validate_portal_url("https://www.kimi.com").is_ok());
        assert!(validate_portal_url("http://127.0.0.1:8080").is_err());
        assert!(validate_portal_url("kimi.com").is_ok());
        assert!(validate_portal_url("javascript:alert(1)").is_err());
        assert!(validate_portal_url("file:///C:/Windows").is_err());
        assert!(validate_portal_url("").is_err());
        assert!(validate_portal_url("https://bad host").is_err());
    }

    #[test]
    fn socket_addresses_format_exact_host_headers_with_ports() {
        let ipv4 = "127.0.0.1:43123"
            .parse::<std::net::SocketAddr>()
            .unwrap();
        let ipv6 = "[::1]:43123"
            .parse::<std::net::SocketAddr>()
            .unwrap();
        assert_eq!(ipv4.to_string(), "127.0.0.1:43123");
        assert_eq!(ipv6.to_string(), "[::1]:43123");
    }
}

#[cfg(debug_assertions)]
macro_rules! sumika_invoke_handler {
    () => {
        tauri::generate_handler![
            set_display_mode,
            get_display_mode,
            start_pet_drag,
            hide_pet,
            show_overlay,
            hide_overlay,
            open_main_window,
            core_status,
            open_portal,
            focus_portal,
            close_portal,
            portal_list,
            embedded_browser::embedded_browser_open,
            embedded_browser::embedded_browser_list,
            embedded_browser::embedded_browser_bounds,
            embedded_browser::embedded_browser_hide_all,
            embedded_browser::embedded_browser_close,
            embedded_browser::embedded_browser_action,
            consultation::consultation_open,
            consultation::consultation_set_bounds,
            consultation::consultation_hide,
            consultation::consultation_close,
            consultation::consultation_action,
            consultation::consultation_smoke_probe,
            embedded_browser::embedded_browser_reader_probe
        ]
    };
}

#[cfg(not(debug_assertions))]
macro_rules! sumika_invoke_handler {
    () => {
        tauri::generate_handler![
            set_display_mode,
            get_display_mode,
            start_pet_drag,
            hide_pet,
            show_overlay,
            hide_overlay,
            open_main_window,
            core_status,
            open_portal,
            focus_portal,
            close_portal,
            portal_list,
            embedded_browser::embedded_browser_open,
            embedded_browser::embedded_browser_list,
            embedded_browser::embedded_browser_bounds,
            embedded_browser::embedded_browser_hide_all,
            embedded_browser::embedded_browser_close,
            embedded_browser::embedded_browser_action,
            consultation::consultation_open,
            consultation::consultation_set_bounds,
            consultation::consultation_hide,
            consultation::consultation_close,
            consultation::consultation_action
        ]
    };
}

fn main() {
    let mut context = tauri::generate_context!();
    #[cfg(debug_assertions)]
    if let Some(directory) = env::var_os("SUMIKA_SMOKE_MAIN_DATA_DIR") {
        let directory = PathBuf::from(directory);
        assert!(directory.is_absolute(), "smoke WebView directory must be absolute");
        for window in &mut context.config_mut().app.windows {
            if window.label == "main" { window.data_directory = Some(directory.clone()); }
        }
    }
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(sumika_invoke_handler!())
        .setup(setup)
        .build(context)
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
