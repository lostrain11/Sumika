use std::fs;
use std::path::PathBuf;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Mutex,
};

use serde::{Deserialize, Serialize};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{
    AppHandle, Emitter, LogicalSize, Manager, PhysicalPosition, State, Webview, Window,
    WindowEvent,
};

use crate::{append_log, embedded_browser};

pub const MAIN_LABEL: &str = "main";
pub const COMPANION_LABEL: &str = "companion";
pub const RENDER_VISIBILITY_EVENT: &str = "native-render-visibility-changed";
pub const COMPANION_SETTINGS_EVENT: &str = "companion-window-changed";

const WINDOW_STATE_VERSION: u32 = 2;
const WINDOW_STATE_FILE: &str = "window-state-v2.json";
const COMPACT_WIDTH: f64 = 480.0;
const COMPACT_HEIGHT: f64 = 420.0;
const PANORAMA_WIDTH: f64 = 1120.0;
const PANORAMA_HEIGHT: f64 = 720.0;
const MIN_VISIBLE: i32 = 96;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum CompanionMode {
    Compact,
    Panorama,
    Fullscreen,
}

impl CompanionMode {
    fn parse(value: &str) -> Result<Self, String> {
        match value {
            "compact" | "pet" => Ok(Self::Compact),
            "panorama" => Ok(Self::Panorama),
            "fullscreen" => Ok(Self::Fullscreen),
            _ => Err("companion mode 只允许 compact、panorama 或 fullscreen".to_string()),
        }
    }

    fn as_str(self) -> &'static str {
        match self {
            Self::Compact => "compact",
            Self::Panorama => "panorama",
            Self::Fullscreen => "fullscreen",
        }
    }

    fn default_always_on_top(self) -> bool {
        self == Self::Compact
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
struct MonitorGeometry {
    name: Option<String>,
    x: i32,
    y: i32,
    width: u32,
    height: u32,
    scale_factor: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
struct WindowGeometry {
    x: i32,
    y: i32,
    width: f64,
    height: f64,
    scale_factor: f64,
    monitor: Option<MonitorGeometry>,
    #[serde(default)]
    maximized: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct PersistedWindowState {
    version: u32,
    main: WindowGeometry,
    companion_compact: WindowGeometry,
    companion_panorama: WindowGeometry,
    companion_mode: CompanionMode,
    companion_transparent: bool,
    companion_always_on_top: Option<bool>,
}

struct WindowManagerInner {
    persisted: PersistedWindowState,
    display_mode: String,
    main_rendering: bool,
    companion_rendering: bool,
}

pub struct WindowManagerState {
    path: PathBuf,
    inner: Mutex<WindowManagerInner>,
}

pub struct AppLifecycle {
    quitting: AtomicBool,
}

#[derive(Clone, Debug, Serialize)]
pub struct NativeWindowStatus {
    #[cfg(windows)]
    native_handle: isize,
    label: String,
    visible: bool,
    minimized: bool,
    focused: bool,
    fullscreen: bool,
    decorated: bool,
    always_on_top: bool,
    scale_factor: f64,
    position: PhysicalPosition<i32>,
    size: tauri::PhysicalSize<u32>,
    monitor: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
pub struct NativeWindowsState {
    display_mode: String,
    companion_mode: String,
    companion_transparent: bool,
    companion_always_on_top: bool,
    tray_available: bool,
    monitor_count: usize,
    main: NativeWindowStatus,
    companion: NativeWindowStatus,
}

#[derive(Clone, Debug, Serialize)]
struct RenderVisibilityPayload {
    window_label: String,
    rendering: bool,
    reason: String,
}

#[derive(Clone, Debug, Serialize)]
struct CompanionSettingsPayload {
    mode: String,
    transparent: bool,
    always_on_top: bool,
}

#[derive(Clone, Debug)]
struct MonitorWorkArea {
    name: Option<String>,
    x: i32,
    y: i32,
    width: u32,
    height: u32,
    scale_factor: f64,
}

impl MonitorWorkArea {
    fn from_monitor(monitor: &tauri::window::Monitor) -> Self {
        let area = monitor.work_area();
        Self {
            name: monitor.name().cloned(),
            x: area.position.x,
            y: area.position.y,
            width: area.size.width,
            height: area.size.height,
            scale_factor: monitor.scale_factor(),
        }
    }

    fn snapshot(&self) -> MonitorGeometry {
        MonitorGeometry {
            name: self.name.clone(),
            x: self.x,
            y: self.y,
            width: self.width,
            height: self.height,
            scale_factor: self.scale_factor,
        }
    }
}

impl WindowGeometry {
    fn default_main() -> Self {
        Self {
            x: 80,
            y: 60,
            width: 1440.0,
            height: 900.0,
            scale_factor: 1.0,
            monitor: None,
            maximized: false,
        }
    }

    fn default_compact() -> Self {
        Self {
            x: 120,
            y: 100,
            width: COMPACT_WIDTH,
            height: COMPACT_HEIGHT,
            scale_factor: 1.0,
            monitor: None,
            maximized: false,
        }
    }

    fn default_panorama() -> Self {
        Self {
            x: 120,
            y: 80,
            width: PANORAMA_WIDTH,
            height: PANORAMA_HEIGHT,
            scale_factor: 1.0,
            monitor: None,
            maximized: false,
        }
    }
}

impl PersistedWindowState {
    fn defaults(main: WindowGeometry) -> Self {
        Self {
            version: WINDOW_STATE_VERSION,
            main,
            companion_compact: WindowGeometry::default_compact(),
            companion_panorama: WindowGeometry::default_panorama(),
            companion_mode: CompanionMode::Compact,
            companion_transparent: false,
            companion_always_on_top: None,
        }
    }

    fn load(path: &PathBuf, main: WindowGeometry) -> Self {
        let fallback = Self::defaults(main);
        let Ok(raw) = fs::read(path) else {
            return fallback;
        };
        let Ok(saved) = serde_json::from_slice::<Self>(&raw) else {
            return fallback;
        };
        if saved.version == WINDOW_STATE_VERSION {
            saved
        } else {
            fallback
        }
    }
}

impl WindowManagerState {
    fn save(&self, persisted: &PersistedWindowState) -> Result<(), String> {
        let bytes = serde_json::to_vec_pretty(persisted)
            .map_err(|error| format!("窗口状态序列化失败: {error}"))?;
        fs::write(&self.path, bytes).map_err(|error| format!("窗口状态保存失败: {error}"))
    }
}

pub fn authorize_shell_caller(caller: &Webview) -> Result<(), String> {
    let webview_label = caller.label();
    let window_label = caller.window().label().to_string();
    if webview_label != window_label
        || !matches!(webview_label, MAIN_LABEL | COMPANION_LABEL)
    {
        return Err("command is restricted to a trusted Sumika shell webview".to_string());
    }
    let url = caller
        .url()
        .map_err(|error| format!("failed to inspect command caller URL: {error}"))?;
    let configured_origin = matches!(
        (url.scheme(), url.host_str(), url.port()),
        ("http", Some("127.0.0.1"), Some(8771))
            | ("http", Some("tauri.localhost"), None)
    );
    #[cfg(debug_assertions)]
    let smoke_origin = std::env::var_os("SUMIKA_SMOKE_MAIN_DATA_DIR").is_some()
        && url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && url.port() == Some(crate::core_endpoint().1);
    #[cfg(not(debug_assertions))]
    let smoke_origin = false;
    let trusted = configured_origin || smoke_origin;
    if !trusted || !url.username().is_empty() || url.password().is_some() {
        return Err("command caller origin is not trusted".to_string());
    }
    Ok(())
}

fn authorize_companion_caller(caller: &Webview) -> Result<(), String> {
    authorize_shell_caller(caller)?;
    if caller.label() == COMPANION_LABEL {
        Ok(())
    } else {
        Err("command is restricted to the companion webview".to_string())
    }
}

fn window_status(window: &Window) -> Result<NativeWindowStatus, String> {
    Ok(NativeWindowStatus {
        label: window.label().to_string(),
        #[cfg(windows)]
        native_handle: window.hwnd().map_err(|error| error.to_string())?.0 as isize,
        visible: window.is_visible().map_err(|error| error.to_string())?,
        minimized: window.is_minimized().map_err(|error| error.to_string())?,
        focused: window.is_focused().map_err(|error| error.to_string())?,
        fullscreen: window.is_fullscreen().map_err(|error| error.to_string())?,
        decorated: window.is_decorated().map_err(|error| error.to_string())?,
        always_on_top: window.is_always_on_top().map_err(|error| error.to_string())?,
        scale_factor: window.scale_factor().map_err(|error| error.to_string())?,
        position: window.outer_position().map_err(|error| error.to_string())?,
        size: window.inner_size().map_err(|error| error.to_string())?,
        monitor: window
            .current_monitor()
            .map_err(|error| error.to_string())?
            .and_then(|monitor| monitor.name().cloned()),
    })
}

fn monitor_work_areas(window: &Window) -> Result<Vec<MonitorWorkArea>, String> {
    let monitors = window
        .available_monitors()
        .map_err(|error| format!("读取显示器失败: {error}"))?;
    if monitors.is_empty() {
        return Err("没有可用显示器".to_string());
    }
    Ok(monitors.iter().map(MonitorWorkArea::from_monitor).collect())
}

fn intersection_area(geometry: &WindowGeometry, monitor: &MonitorWorkArea) -> i64 {
    let width = (geometry.width * geometry.scale_factor.max(0.5)).round() as i32;
    let height = (geometry.height * geometry.scale_factor.max(0.5)).round() as i32;
    let left = geometry.x.max(monitor.x);
    let top = geometry.y.max(monitor.y);
    let right = geometry
        .x
        .saturating_add(width)
        .min(monitor.x.saturating_add(monitor.width as i32));
    let bottom = geometry
        .y
        .saturating_add(height)
        .min(monitor.y.saturating_add(monitor.height as i32));
    i64::from((right - left).max(0)) * i64::from((bottom - top).max(0))
}

fn restore_geometry(
    geometry: &WindowGeometry,
    monitors: &[MonitorWorkArea],
) -> (PhysicalPosition<i32>, LogicalSize<f64>) {
    let named = geometry.monitor.as_ref().and_then(|saved| {
        saved.name.as_ref().and_then(|name| {
            monitors
                .iter()
                .find(|monitor| monitor.name.as_ref() == Some(name))
        })
    });
    let target = named.unwrap_or_else(|| {
        monitors
            .iter()
            .max_by_key(|monitor| intersection_area(geometry, monitor))
            .unwrap_or(&monitors[0])
    });
    let scale = target.scale_factor.max(0.5);
    let width = geometry
        .width
        .clamp(320.0, f64::from(target.width) / scale);
    let height = geometry
        .height
        .clamp(240.0, f64::from(target.height) / scale);
    let physical_width = (width * scale).round() as i32;
    let physical_height = (height * scale).round() as i32;
    let (candidate_x, candidate_y) = match (&geometry.monitor, named) {
        (Some(saved), Some(_)) => {
            let saved_scale = saved.scale_factor.max(0.5);
            let logical_x = f64::from(geometry.x - saved.x) / saved_scale;
            let logical_y = f64::from(geometry.y - saved.y) / saved_scale;
            (
                target.x + (logical_x * scale).round() as i32,
                target.y + (logical_y * scale).round() as i32,
            )
        }
        _ => (
            target.x + (32.0 * scale).round() as i32,
            target.y + (32.0 * scale).round() as i32,
        ),
    };
    let min_x = target.x - physical_width + MIN_VISIBLE;
    let max_x = target.x + target.width as i32 - MIN_VISIBLE;
    let min_y = target.y - physical_height + MIN_VISIBLE;
    let max_y = target.y + target.height as i32 - MIN_VISIBLE;
    (
        PhysicalPosition::new(candidate_x.clamp(min_x, max_x), candidate_y.clamp(min_y, max_y)),
        LogicalSize::new(width, height),
    )
}

fn capture_geometry(window: &Window, fallback: &WindowGeometry) -> Result<WindowGeometry, String> {
    let scale_factor = window.scale_factor().map_err(|error| error.to_string())?;
    let maximized = window.is_maximized().map_err(|error| error.to_string())?;
    let minimized = window.is_minimized().map_err(|error| error.to_string())?;
    let fullscreen = window.is_fullscreen().map_err(|error| error.to_string())?;
    let current_monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .map(|monitor| MonitorWorkArea::from_monitor(&monitor).snapshot());
    if maximized || minimized || fullscreen {
        return Ok(WindowGeometry {
            scale_factor,
            monitor: current_monitor.or_else(|| fallback.monitor.clone()),
            maximized,
            ..fallback.clone()
        });
    }
    let position = window.outer_position().map_err(|error| error.to_string())?;
    let size = window.inner_size().map_err(|error| error.to_string())?;
    Ok(WindowGeometry {
        x: position.x,
        y: position.y,
        width: f64::from(size.width) / scale_factor,
        height: f64::from(size.height) / scale_factor,
        scale_factor,
        monitor: current_monitor,
        maximized: false,
    })
}

fn apply_geometry(window: &Window, geometry: &WindowGeometry) -> Result<(), String> {
    let monitors = monitor_work_areas(window)?;
    let (position, size) = restore_geometry(geometry, &monitors);
    window
        .set_position(position)
        .map_err(|error| format!("设置窗口位置失败: {error}"))?;
    window
        .set_size(size)
        .map_err(|error| format!("设置窗口尺寸失败: {error}"))?;
    Ok(())
}

#[cfg(windows)]
fn show_without_activation(window: &Window) -> Result<(), String> {
    use windows::Win32::UI::WindowsAndMessaging::{ShowWindow, SW_SHOWNOACTIVATE};

    let handle = window.hwnd().map_err(|error| error.to_string())?;
    unsafe {
        let _ = ShowWindow(handle, SW_SHOWNOACTIVATE);
    }
    Ok(())
}

#[cfg(windows)]
fn foreground_window() -> windows::Win32::Foundation::HWND {
    use windows::Win32::UI::WindowsAndMessaging::GetForegroundWindow;

    unsafe { GetForegroundWindow() }
}

#[cfg(windows)]
fn restore_foreground_window(handle: windows::Win32::Foundation::HWND) {
    use windows::Win32::UI::WindowsAndMessaging::SetForegroundWindow;

    if !handle.0.is_null() {
        unsafe {
            let _ = SetForegroundWindow(handle);
        }
    }
}

#[cfg(not(windows))]
fn show_without_activation(window: &Window) -> Result<(), String> {
    window.unminimize().map_err(|error| error.to_string())?;
    window.show().map_err(|error| error.to_string())
}

fn effective_always_on_top(persisted: &PersistedWindowState) -> bool {
    persisted
        .companion_always_on_top
        .unwrap_or_else(|| persisted.companion_mode.default_always_on_top())
}

fn emit_companion_settings(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<WindowManagerState>();
    let inner = state
        .inner
        .lock()
        .map_err(|_| "窗口状态已损坏".to_string())?;
    let payload = CompanionSettingsPayload {
        mode: inner.persisted.companion_mode.as_str().to_string(),
        transparent: inner.persisted.companion_transparent,
        always_on_top: effective_always_on_top(&inner.persisted),
    };
    drop(inner);
    let window = app
        .get_window(COMPANION_LABEL)
        .ok_or_else(|| "找不到 Sumika 陪伴窗口".to_string())?;
    window
        .emit(COMPANION_SETTINGS_EVENT, payload)
        .map_err(|error| format!("发布陪伴窗口状态失败: {error}"))
}

fn emit_render_visibility(
    app: &AppHandle,
    label: &str,
    rendering: bool,
    reason: &str,
) -> Result<(), String> {
    let state = app.state::<WindowManagerState>();
    let changed = {
        let mut inner = state
            .inner
            .lock()
            .map_err(|_| "窗口状态已损坏".to_string())?;
        let current = if label == MAIN_LABEL {
            &mut inner.main_rendering
        } else {
            &mut inner.companion_rendering
        };
        if *current == rendering {
            false
        } else {
            *current = rendering;
            true
        }
    };
    if !changed {
        return Ok(());
    }
    let window = app
        .get_window(label)
        .ok_or_else(|| format!("找不到窗口 {label}"))?;
    window
        .emit(
            RENDER_VISIBILITY_EVENT,
            RenderVisibilityPayload {
                window_label: label.to_string(),
                rendering,
                reason: reason.to_string(),
            },
        )
        .map_err(|error| format!("发布渲染可见性失败: {error}"))
}

fn persist_window_geometry(app: &AppHandle, label: &str) -> Result<(), String> {
    let window = app
        .get_window(label)
        .ok_or_else(|| format!("找不到窗口 {label}"))?;
    let state = app.state::<WindowManagerState>();
    let inner = state
        .inner
        .try_lock()
        .map_err(|_| "窗口状态正在更新".to_string())?;
    let captured_mode = inner.persisted.companion_mode;
    let fallback = if label == MAIN_LABEL {
        inner.persisted.main.clone()
    } else {
        match inner.persisted.companion_mode {
            CompanionMode::Compact => inner.persisted.companion_compact.clone(),
            CompanionMode::Panorama => inner.persisted.companion_panorama.clone(),
            CompanionMode::Fullscreen => return Ok(()),
        }
    };
    drop(inner);
    let geometry = capture_geometry(&window, &fallback)?;
    let mut inner = state.inner.lock().map_err(|_| "窗口状态已损坏".to_string())?;
    if label == COMPANION_LABEL && inner.persisted.companion_mode != captured_mode {
        return Ok(());
    }
    if label == MAIN_LABEL {
        inner.persisted.main = geometry;
    } else if inner.persisted.companion_mode == CompanionMode::Compact {
        inner.persisted.companion_compact = geometry;
    } else {
        inner.persisted.companion_panorama = geometry;
    }
    state.save(&inner.persisted)
}

fn configure_companion(app: &AppHandle, show: bool) -> Result<(), String> {
    #[cfg(windows)]
    let foreground = foreground_window();
    let window = app
        .get_window(COMPANION_LABEL)
        .ok_or_else(|| "找不到 Sumika 陪伴窗口".to_string())?;
    let state = app.state::<WindowManagerState>();
    let (mode, geometry, always_on_top) = {
        let inner = state
            .inner
            .lock()
            .map_err(|_| "窗口状态已损坏".to_string())?;
        let geometry = match inner.persisted.companion_mode {
            CompanionMode::Compact | CompanionMode::Fullscreen => {
                inner.persisted.companion_compact.clone()
            }
            CompanionMode::Panorama => inner.persisted.companion_panorama.clone(),
        };
        (
            inner.persisted.companion_mode,
            geometry,
            effective_always_on_top(&inner.persisted),
        )
    };
    window
        .set_fullscreen(false)
        .map_err(|error| format!("退出陪伴全屏失败: {error}"))?;
    window
        .unmaximize()
        .map_err(|error| format!("退出陪伴最大化失败: {error}"))?;
    window
        .set_decorations(mode == CompanionMode::Panorama)
        .map_err(|error| format!("设置陪伴窗口边框失败: {error}"))?;
    window
        .set_shadow(mode == CompanionMode::Panorama)
        .map_err(|error| format!("设置陪伴窗口阴影失败: {error}"))?;
    window
        .set_skip_taskbar(mode != CompanionMode::Panorama)
        .map_err(|error| format!("设置陪伴任务栏状态失败: {error}"))?;
    window
        .set_resizable(mode != CompanionMode::Fullscreen)
        .map_err(|error| format!("设置陪伴缩放失败: {error}"))?;
    window
        .set_min_size(Some(LogicalSize::new(320.0, 280.0)))
        .map_err(|error| format!("设置陪伴最小尺寸失败: {error}"))?;
    window
        .set_always_on_top(always_on_top)
        .map_err(|error| format!("设置陪伴置顶失败: {error}"))?;
    apply_geometry(&window, &geometry)?;
    if mode == CompanionMode::Fullscreen {
        window
            .set_fullscreen(true)
            .map_err(|error| format!("进入陪伴全屏失败: {error}"))?;
    }
    if show {
        show_without_activation(&window)
            .map_err(|error| format!("显示陪伴窗口失败: {error}"))?;
        let mut inner = state
            .inner
            .lock()
            .map_err(|_| "窗口状态已损坏".to_string())?;
        inner.display_mode = "pet".to_string();
        drop(inner);
        emit_render_visibility(app, COMPANION_LABEL, true, "shown")?;
    }
    emit_companion_settings(app)
        .inspect(|_| {
            #[cfg(windows)]
            restore_foreground_window(foreground);
        })
}

fn show_main(app: &AppHandle, focus: bool) -> Result<(), String> {
    let window = app
        .get_window(MAIN_LABEL)
        .ok_or_else(|| "找不到 Sumika 主窗口".to_string())?;
    let state = app.state::<WindowManagerState>();
    let geometry = state
        .inner
        .lock()
        .map_err(|_| "窗口状态已损坏".to_string())?
        .persisted
        .main
        .clone();
    window
        .set_fullscreen(false)
        .map_err(|error| format!("退出主窗口全屏失败: {error}"))?;
    window
        .unmaximize()
        .map_err(|error| format!("退出主窗口最大化失败: {error}"))?;
    apply_geometry(&window, &geometry)?;
    if geometry.maximized {
        window
            .maximize()
            .map_err(|error| format!("恢复主窗口最大化失败: {error}"))?;
    }
    window
        .unminimize()
        .map_err(|error| format!("恢复主窗口失败: {error}"))?;
    window
        .show()
        .map_err(|error| format!("显示主窗口失败: {error}"))?;
    if focus {
        window
            .set_focus()
            .map_err(|error| format!("聚焦主窗口失败: {error}"))?;
    }
    emit_render_visibility(app, MAIN_LABEL, true, "shown")
}

fn hide_window(app: &AppHandle, label: &str, reason: &str) -> Result<(), String> {
    if label == MAIN_LABEL {
        let _ = embedded_browser::hide_children(app);
    }
    let _ = persist_window_geometry(app, label);
    let window = app
        .get_window(label)
        .ok_or_else(|| format!("找不到窗口 {label}"))?;
    window
        .hide()
        .map_err(|error| format!("隐藏窗口失败: {error}"))?;
    emit_render_visibility(app, label, false, reason)
}

fn hide_companion_inner(app: &AppHandle, reason: &str) -> Result<(), String> {
    let window = app
        .get_window(COMPANION_LABEL)
        .ok_or_else(|| "找不到 Sumika 陪伴窗口".to_string())?;
    if window.is_fullscreen().unwrap_or(false) {
        window
            .set_fullscreen(false)
            .map_err(|error| format!("退出陪伴全屏失败: {error}"))?;
    }
    hide_window(app, COMPANION_LABEL, reason)?;
    let state = app.state::<WindowManagerState>();
    let mut inner = state
        .inner
        .lock()
        .map_err(|_| "窗口状态已损坏".to_string())?;
    inner.display_mode = "workspace".to_string();
    Ok(())
}

pub fn initialize(app: &mut tauri::App, data_dir: PathBuf) -> Result<(), String> {
    let main = app
        .get_window(MAIN_LABEL)
        .ok_or_else(|| "找不到 Sumika 主窗口".to_string())?;
    let companion = app
        .get_window(COMPANION_LABEL)
        .ok_or_else(|| "找不到 Sumika 陪伴窗口".to_string())?;
    let main_fallback = capture_geometry(&main, &WindowGeometry::default_main())?;
    let path = data_dir.join(WINDOW_STATE_FILE);
    let persisted = PersistedWindowState::load(&path, main_fallback);
    let main_geometry = persisted.main.clone();
    app.manage(WindowManagerState {
        path,
        inner: Mutex::new(WindowManagerInner {
            persisted,
            display_mode: "workspace".to_string(),
            main_rendering: true,
            companion_rendering: false,
        }),
    });
    app.manage(AppLifecycle {
        quitting: AtomicBool::new(false),
    });
    apply_geometry(&main, &main_geometry)?;
    companion.hide().map_err(|error| error.to_string())?;
    configure_companion(app.handle(), false)
}

pub fn install_window_handlers(app: &tauri::App, log_path: PathBuf) {
    for label in [MAIN_LABEL, COMPANION_LABEL] {
        let Some(window) = app.get_window(label) else {
            continue;
        };
        let app_handle = app.handle().clone();
        let observed = window.clone();
        let observed_label = label.to_string();
        let event_log_path = log_path.clone();
        window.on_window_event(move |event| match event {
            WindowEvent::CloseRequested { api, .. } => {
                if app_handle.state::<AppLifecycle>().quitting.load(Ordering::SeqCst) {
                    return;
                }
                api.prevent_close();
                let result = if observed_label == MAIN_LABEL {
                    hide_window(&app_handle, MAIN_LABEL, "closed-to-tray")
                } else {
                    hide_companion_inner(&app_handle, "closed")
                };
                append_log(
                    &event_log_path,
                    &format!(
                        "{} window close requested; hidden={}",
                        observed_label,
                        result.is_ok()
                    ),
                );
            }
            WindowEvent::Moved(_) | WindowEvent::Resized(_) | WindowEvent::ScaleFactorChanged { .. } => {
                let minimized = observed.is_minimized().unwrap_or(false);
                let visible = observed.is_visible().unwrap_or(false);
                if observed_label == MAIN_LABEL && minimized {
                    let _ = embedded_browser::hide_children(&app_handle);
                }
                let _ = emit_render_visibility(
                    &app_handle,
                    &observed_label,
                    visible && !minimized,
                    if minimized { "minimized" } else { "restored" },
                );
                if visible && !minimized {
                    let _ = persist_window_geometry(&app_handle, &observed_label);
                }
            }
            _ => {}
        });
    }
}

pub fn build_tray(app: &tauri::App) -> Result<(), String> {
    let show_main = MenuItem::with_id(app, "show-main", "打开工作台", true, None::<&str>)
        .map_err(|error| error.to_string())?;
    let show_companion = MenuItem::with_id(
        app,
        "show-companion",
        "显示陪伴窗口",
        true,
        None::<&str>,
    )
    .map_err(|error| error.to_string())?;
    let quit = MenuItem::with_id(app, "quit", "真正退出", true, None::<&str>)
        .map_err(|error| error.to_string())?;
    let menu = Menu::with_items(app, &[&show_main, &show_companion, &quit])
        .map_err(|error| error.to_string())?;
    let mut builder = TrayIconBuilder::with_id("sumika")
        .menu(&menu)
        .tooltip("Sumika")
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show-main" => {
                let _ = show_main_window_inner(app);
            }
            "show-companion" => {
                let _ = configure_companion(app, true);
            }
            "quit" => request_exit(app),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if matches!(
                event,
                TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                } | TrayIconEvent::DoubleClick {
                    button: MouseButton::Left,
                    ..
                }
            ) {
                let _ = show_main_window_inner(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon().cloned() {
        builder = builder.icon(icon);
    }
    builder.build(app).map_err(|error| error.to_string())?;
    Ok(())
}

fn show_main_window_inner(app: &AppHandle) -> Result<(), String> {
    show_main(app, true)
}

pub fn request_exit(app: &AppHandle) {
    app.state::<AppLifecycle>()
        .quitting
        .store(true, Ordering::SeqCst);
    app.exit(0);
}

pub fn should_prevent_exit(app: &AppHandle) -> bool {
    !app
        .state::<AppLifecycle>()
        .quitting
        .load(Ordering::SeqCst)
}

#[tauri::command]
pub async fn set_display_mode(
    caller: Webview,
    app: AppHandle,
    mode: String,
) -> Result<String, String> {
    authorize_shell_caller(&caller)?;
    match mode.as_str() {
        "pet" => {
            configure_companion(&app, true)?;
            Ok("pet".to_string())
        }
        "workspace" => {
            hide_companion_inner(&app, "workspace-restored")?;
            show_main(&app, true)?;
            Ok("workspace".to_string())
        }
        _ => Err("display mode 只允许 workspace 或 pet".to_string()),
    }
}

#[tauri::command]
pub async fn get_display_mode(caller: Webview, state: State<'_, WindowManagerState>) -> Result<String, String> {
    authorize_shell_caller(&caller)?;
    Ok(state
        .inner
        .lock()
        .map_err(|_| "窗口状态已损坏".to_string())?
        .display_mode
        .clone())
}

#[tauri::command]
pub async fn start_pet_drag(caller: Webview, app: AppHandle) -> Result<(), String> {
    authorize_companion_caller(&caller)?;
    let window = app
        .get_window(COMPANION_LABEL)
        .ok_or_else(|| "找不到 Sumika 陪伴窗口".to_string())?;
    if window.is_fullscreen().map_err(|error| error.to_string())? {
        return Err("全屏陪伴窗口不能拖动".to_string());
    }
    window.start_dragging().map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn hide_pet(caller: Webview, app: AppHandle) -> Result<String, String> {
    authorize_shell_caller(&caller)?;
    hide_companion_inner(&app, "hidden")?;
    Ok("workspace".to_string())
}

#[tauri::command]
pub async fn show_overlay(caller: Webview, app: AppHandle) -> Result<(), String> {
    authorize_shell_caller(&caller)?;
    configure_companion(&app, true)
}

#[tauri::command]
pub async fn hide_overlay(caller: Webview, app: AppHandle) -> Result<(), String> {
    authorize_shell_caller(&caller)?;
    hide_companion_inner(&app, "hidden")
}

#[tauri::command]
pub async fn open_main_window(caller: Webview, app: AppHandle) -> Result<(), String> {
    authorize_shell_caller(&caller)?;
    hide_companion_inner(&app, "workspace-restored")?;
    show_main(&app, true)
}

#[tauri::command]
pub async fn show_main_window(caller: Webview, app: AppHandle) -> Result<(), String> {
    authorize_shell_caller(&caller)?;
    show_main(&app, true)
}

#[tauri::command]
pub async fn hide_main_window(caller: Webview, app: AppHandle) -> Result<(), String> {
    authorize_shell_caller(&caller)?;
    if caller.label() != MAIN_LABEL {
        return Err("command is restricted to the main webview".to_string());
    }
    hide_window(&app, MAIN_LABEL, "hidden")
}

#[tauri::command]
pub async fn show_companion(caller: Webview, app: AppHandle) -> Result<(), String> {
    authorize_shell_caller(&caller)?;
    configure_companion(&app, true)
}

#[tauri::command]
pub async fn hide_companion(caller: Webview, app: AppHandle) -> Result<(), String> {
    authorize_shell_caller(&caller)?;
    hide_companion_inner(&app, "hidden")
}

#[tauri::command]
pub async fn set_companion_mode(
    caller: Webview,
    app: AppHandle,
    mode: String,
) -> Result<NativeWindowsState, String> {
    authorize_shell_caller(&caller)?;
    let target = CompanionMode::parse(&mode)?;
    let state = app.state::<WindowManagerState>();
    if let Some(window) = app.get_window(COMPANION_LABEL) {
        let current_mode = state
            .inner
            .lock()
            .map_err(|_| "窗口状态已损坏".to_string())?
            .persisted
            .companion_mode;
        if current_mode != CompanionMode::Fullscreen {
            let _ = persist_window_geometry(&app, COMPANION_LABEL);
        }
        let mut inner = state
            .inner
            .lock()
            .map_err(|_| "窗口状态已损坏".to_string())?;
        inner.persisted.companion_mode = target;
        state.save(&inner.persisted)?;
        drop(inner);
        if target != CompanionMode::Fullscreen && window.is_fullscreen().unwrap_or(false) {
            window.set_fullscreen(false).map_err(|error| error.to_string())?;
        }
    }
    configure_companion(&app, true)?;
    native_windows_state_inner(&app)
}

#[tauri::command]
pub async fn set_companion_transparent(
    caller: Webview,
    app: AppHandle,
    transparent: bool,
) -> Result<NativeWindowsState, String> {
    authorize_shell_caller(&caller)?;
    let state = app.state::<WindowManagerState>();
    let mut inner = state
        .inner
        .lock()
        .map_err(|_| "窗口状态已损坏".to_string())?;
    inner.persisted.companion_transparent = transparent;
    state.save(&inner.persisted)?;
    drop(inner);
    emit_companion_settings(&app)?;
    native_windows_state_inner(&app)
}

#[tauri::command]
pub async fn set_companion_always_on_top(
    caller: Webview,
    app: AppHandle,
    always_on_top: bool,
) -> Result<NativeWindowsState, String> {
    authorize_shell_caller(&caller)?;
    let state = app.state::<WindowManagerState>();
    let mut inner = state
        .inner
        .lock()
        .map_err(|_| "窗口状态已损坏".to_string())?;
    inner.persisted.companion_always_on_top = Some(always_on_top);
    state.save(&inner.persisted)?;
    drop(inner);
    let companion = app
        .get_window(COMPANION_LABEL)
        .ok_or_else(|| "找不到 Sumika 陪伴窗口".to_string())?;
    companion
        .set_always_on_top(always_on_top)
        .map_err(|error| error.to_string())?;
    emit_companion_settings(&app)?;
    native_windows_state_inner(&app)
}

#[tauri::command]
pub async fn set_companion_bounds(
    caller: Webview,
    app: AppHandle,
    x: i32,
    y: i32,
    width: f64,
    height: f64,
) -> Result<NativeWindowsState, String> {
    authorize_shell_caller(&caller)?;
    if !width.is_finite()
        || !height.is_finite()
        || !(320.0..=3840.0).contains(&width)
        || !(280.0..=2160.0).contains(&height)
    {
        return Err("陪伴窗口尺寸超出允许范围".to_string());
    }
    let companion = app
        .get_window(COMPANION_LABEL)
        .ok_or_else(|| "找不到 Sumika 陪伴窗口".to_string())?;
    if companion.is_fullscreen().map_err(|error| error.to_string())? {
        return Err("全屏模式不能直接设置窗口边界".to_string());
    }
    companion
        .set_position(PhysicalPosition::new(x, y))
        .map_err(|error| format!("设置陪伴窗口位置失败: {error}"))?;
    companion
        .set_size(LogicalSize::new(width, height))
        .map_err(|error| format!("设置陪伴窗口尺寸失败: {error}"))?;
    persist_window_geometry(&app, COMPANION_LABEL)?;
    native_windows_state_inner(&app)
}

#[tauri::command]
pub async fn set_window_minimized(
    caller: Webview,
    app: AppHandle,
    minimized: bool,
) -> Result<(), String> {
    authorize_shell_caller(&caller)?;
    let label = caller.label().to_string();
    let window = app
        .get_window(&label)
        .ok_or_else(|| format!("找不到窗口 {label}"))?;
    if minimized {
        if label == MAIN_LABEL {
            let _ = embedded_browser::hide_children(&app);
        }
        window.minimize().map_err(|error| error.to_string())?;
        emit_render_visibility(&app, &label, false, "minimized")
    } else {
        window.unminimize().map_err(|error| error.to_string())?;
        window.show().map_err(|error| error.to_string())?;
        emit_render_visibility(&app, &label, true, "restored")
    }
}

fn native_windows_state_inner(app: &AppHandle) -> Result<NativeWindowsState, String> {
    let main = app
        .get_window(MAIN_LABEL)
        .ok_or_else(|| "找不到 Sumika 主窗口".to_string())?;
    let companion = app
        .get_window(COMPANION_LABEL)
        .ok_or_else(|| "找不到 Sumika 陪伴窗口".to_string())?;
    let state = app.state::<WindowManagerState>();
    let inner = state
        .inner
        .lock()
        .map_err(|_| "窗口状态已损坏".to_string())?;
    let display_mode = inner.display_mode.clone();
    let persisted = inner.persisted.clone();
    drop(inner);
    let result = NativeWindowsState {
        display_mode,
        companion_mode: persisted.companion_mode.as_str().to_string(),
        companion_transparent: persisted.companion_transparent,
        companion_always_on_top: effective_always_on_top(&persisted),
        tray_available: app.tray_by_id("sumika").is_some(),
        monitor_count: main
            .available_monitors()
            .map_err(|error| error.to_string())?
            .len(),
        main: window_status(&main)?,
        companion: window_status(&companion)?,
    };
    Ok(result)
}

#[tauri::command]
pub async fn native_windows_state(
    caller: Webview,
    app: AppHandle,
) -> Result<NativeWindowsState, String> {
    authorize_shell_caller(&caller)?;
    native_windows_state_inner(&app)
}

#[tauri::command]
pub async fn exit_application(caller: Webview, app: AppHandle) -> Result<(), String> {
    authorize_shell_caller(&caller)?;
    request_exit(&app);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn monitor(name: &str, x: i32, scale_factor: f64) -> MonitorWorkArea {
        MonitorWorkArea {
            name: Some(name.to_string()),
            x,
            y: 0,
            width: (1920.0 * scale_factor) as u32,
            height: (1040.0 * scale_factor) as u32,
            scale_factor,
        }
    }

    #[test]
    fn companion_modes_accept_legacy_pet_only_as_compact() {
        assert_eq!(CompanionMode::parse("pet").unwrap(), CompanionMode::Compact);
        assert_eq!(CompanionMode::parse("panorama").unwrap(), CompanionMode::Panorama);
        assert!(CompanionMode::parse("wallpaper").is_err());
    }

    #[test]
    fn dpi_restore_preserves_logical_offset_and_size_on_the_same_monitor() {
        let saved_monitor = monitor("secondary", 1920, 1.0);
        let geometry = WindowGeometry {
            x: 2020,
            y: 80,
            width: 480.0,
            height: 420.0,
            scale_factor: 1.0,
            monitor: Some(saved_monitor.snapshot()),
            maximized: false,
        };
        let target = monitor("secondary", 2880, 1.5);
        let (position, size) = restore_geometry(&geometry, &[target]);
        assert_eq!(position, PhysicalPosition::new(3030, 120));
        assert_eq!(size, LogicalSize::new(480.0, 420.0));
    }

    #[test]
    fn missing_monitor_restores_inside_an_available_work_area() {
        let geometry = WindowGeometry {
            x: 5000,
            y: -2000,
            width: 1120.0,
            height: 720.0,
            scale_factor: 1.0,
            monitor: Some(monitor("removed", 3840, 1.0).snapshot()),
            maximized: false,
        };
        let target = monitor("primary", 0, 1.0);
        let (position, size) = restore_geometry(&geometry, &[target]);
        assert!(position.x >= 0 && position.x + size.width as i32 <= 1920);
        assert!(position.y >= 0 && position.y + size.height as i32 <= 1040);
    }
}
