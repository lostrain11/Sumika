use std::collections::{BTreeMap, HashMap};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::net::IpAddr;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, LogicalPosition, LogicalSize, Manager, Rect, State, Webview, WebviewUrl};

const MAX_TABS: usize = 32;
const MAX_RESULT: usize = 128 * 1024;
const MODELSCOPE_SOURCE: &str = include_str!("../../backend/src/sumika_core/integrations/modelscope_benefits.py");
const OLLAMA_SOURCE: &str = include_str!("../../backend/src/sumika_core/integrations/account_portals.py");

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
pub struct Bounds {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

impl Default for Bounds {
    fn default() -> Self {
        Self { x: 0.0, y: 0.0, width: 640.0, height: 480.0 }
    }
}

impl Bounds {
    fn validate(self) -> Result<Self, String> {
        if ![self.x, self.y, self.width, self.height].iter().all(|value| value.is_finite())
            || self.x < 0.0 || self.y < 0.0 || self.width < 1.0 || self.height < 1.0
            || self.x + self.width > 16384.0 || self.y + self.height > 16384.0
        {
            return Err("invalid-browser-bounds".into());
        }
        Ok(self)
    }

    fn rect(self) -> Rect {
        Rect { position: LogicalPosition::new(self.x, self.y).into(), size: LogicalSize::new(self.width, self.height).into() }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Tab {
    pub tab_id: String,
    pub account_id: String,
    pub url: String,
    pub title: String,
    pub profile_id: String,
    pub visible: bool,
    pub opened: bool,
    pub status: String,
    pub attempt_id: Option<String>,
    pub possibly_sent: bool,
    pub takeover: bool,
    pub reason: Option<String>,
    pub bounds: Bounds,
    pub site_id: Option<String>,
    #[serde(default)]
    pub baseline_count: usize,
}

#[derive(Serialize)]
pub struct ActionResult {
    status: String,
    text: String,
    attempt_id: Option<String>,
    possibly_sent: bool,
    reason: Option<String>,
    tab: Tab,
    source: Option<String>,
    observation: Option<Value>,
}

impl ActionResult {
    fn new(tab: Tab) -> Self {
        Self { status: tab.status.clone(), text: String::new(), attempt_id: tab.attempt_id.clone(), possibly_sent: tab.possibly_sent, reason: tab.reason.clone(), tab, source: None, observation: None }
    }
}

struct Profile {
    _lease: File,
    writer: Option<String>,
    human: Option<String>,
    busy: bool,
    draft: Option<(String, String, String)>,
    last_read: Option<(String, String)>,
}

#[derive(Default)]
struct Registry {
    tabs: BTreeMap<String, Tab>,
    profiles: HashMap<String, Profile>,
}

pub struct EmbeddedBrowserState {
    registry: Mutex<Registry>,
    lifecycle: tokio::sync::Mutex<()>,
    data_dir: PathBuf,
    metadata_dir: PathBuf,
    _lease: File,
}

fn lock_file(path: &Path) -> Result<File, String> {
    let file = OpenOptions::new().create(true).truncate(false).read(true).write(true).open(path)
        .map_err(|_| "profile-lock-open-failed".to_string())?;
    file.try_lock().map_err(|_| "profile-already-leased".to_string())?;
    Ok(file)
}

fn identifier(value: &str) -> Result<(), String> {
    if value.is_empty() || value.len() > 128 || !value.bytes().all(|character| character.is_ascii_alphanumeric() || b"-_.:".contains(&character)) {
        return Err("invalid-browser-identifier".into());
    }
    Ok(())
}

fn digest(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}

fn label(tab_id: &str) -> String {
    format!("embedded-{}", digest(tab_id))
}

fn public_host(host: &str) -> bool {
    let host = host.trim_end_matches('.').to_ascii_lowercase();
    let literal = host.trim_start_matches('[').trim_end_matches(']');
    if let Ok(address) = literal.parse::<IpAddr>() {
        return match address {
            IpAddr::V4(address) => {
                let octets = address.octets();
                !address.is_private() && !address.is_loopback() && !address.is_link_local()
                    && !address.is_broadcast() && !address.is_documentation() && !address.is_unspecified()
                    && octets[0] != 0 && octets[0] < 224
                    && !(octets[0] == 100 && (64..=127).contains(&octets[1]))
                    && !(octets[0] == 198 && (18..=19).contains(&octets[1]))
            }
            IpAddr::V6(address) => {
                let first = address.segments()[0];
                (0x2000..=0x3fff).contains(&first) && first != 0x2001 && first != 0x2002
            }
        };
    }
    host.contains('.') && !["localhost", "local", "internal", "home", "lan", "test", "invalid"].iter()
        .any(|suffix| host == *suffix || host.ends_with(&format!(".{suffix}")))
        && !host.ends_with(".localhost.direct") && !host.ends_with(".nip.io") && !host.ends_with(".sslip.io")
}

pub fn validate_url(raw: &str) -> Result<tauri::Url, String> {
    if raw.is_empty() || raw.len() > 2048 || raw.chars().any(|character| character.is_whitespace() || character.is_control()) {
        return Err("invalid-browser-url".into());
    }
    let normalized = if raw.contains("://") { raw.to_string() } else { format!("https://{raw}") };
    let url: tauri::Url = normalized.parse().map_err(|_| "invalid-browser-url".to_string())?;
    if url.scheme() != "https" || url.port().is_some()
        || !url.username().is_empty() || url.password().is_some() || !url.host_str().is_some_and(public_host)
    {
        return Err("blocked-browser-url".into());
    }
    Ok(url)
}

fn safe_url(url: &tauri::Url) -> String {
    let mut url = url.clone();
    url.set_query(None);
    url.set_fragment(None);
    url.to_string()
}

fn profile_id(account: &str, url: &tauri::Url, site: Option<&str>) -> String {
    site.map(|site| format!("legacy-{site}")).unwrap_or_else(|| digest(&format!("{}\n{account}", url.origin().ascii_serialization())))
}

fn validate_legacy_account(account: &str, site: Option<&str>) -> Result<(), String> {
    if let Some(site) = site {
        super::validate_portal_site_id(site)?;
        if account != site { return Err("legacy-profile-account-mismatch".into()); }
    }
    Ok(())
}

fn has_tab_capacity(registry: &Registry, tab_id: &str) -> bool {
    registry.tabs.values().filter(|tab| tab.opened && tab.tab_id != tab_id).count() < MAX_TABS
}

impl EmbeddedBrowserState {
    pub fn new(data_dir: &Path) -> Result<Self, String> {
        let metadata_dir = data_dir.join("embedded-browser");
        fs::create_dir_all(&metadata_dir).map_err(|_| "browser-metadata-create-failed".to_string())?;
        let lease = lock_file(&metadata_dir.join(".instance.lock"))?;
        let mut registry = Registry::default();
        for entry in fs::read_dir(&metadata_dir).map_err(|_| "browser-metadata-read-failed".to_string())? {
            let path = entry.map_err(|_| "browser-metadata-read-failed".to_string())?.path();
            if path.extension().and_then(|value| value.to_str()) != Some("json") { continue; }
            let bytes = fs::read(&path).map_err(|_| "browser-metadata-read-failed".to_string())?;
            if bytes.len() > 16 * 1024 { return Err("browser-metadata-invalid".into()); }
            let mut tab: Tab = serde_json::from_slice(&bytes).map_err(|_| "browser-metadata-invalid".to_string())?;
            identifier(&tab.tab_id)?;
            identifier(&tab.account_id)?;
            validate_legacy_account(&tab.account_id, tab.site_id.as_deref())?;
            let url = validate_url(&tab.url)?;
            if tab.profile_id != profile_id(&tab.account_id, &url, tab.site_id.as_deref()) {
                return Err("browser-metadata-invalid".into());
            }
            tab.bounds.validate()?;
            if !tab.opened && !tab.possibly_sent { continue; }
            tab.opened = false;
            tab.visible = false;
            tab.status = if tab.possibly_sent { "unknown" } else { "restored" }.into();
            tab.reason = Some("restored-metadata-only-no-navigation-or-resubmit".into());
            registry.tabs.insert(tab.tab_id.clone(), tab);
        }
        Ok(Self { registry: Mutex::new(registry), lifecycle: tokio::sync::Mutex::new(()), data_dir: data_dir.to_path_buf(), metadata_dir, _lease: lease })
    }

    fn profile_path(&self, tab: &Tab) -> PathBuf {
        if let Some(site) = &tab.site_id { self.data_dir.join("portals").join(site) }
        else { self.metadata_dir.join("profiles").join(&tab.profile_id) }
    }

    fn persist(&self, tab: &Tab) -> Result<(), String> {
        let path = self.metadata_dir.join(format!("{}.json", digest(&tab.tab_id)));
        let temporary = path.with_extension("pending");
        let mut file = File::create(&temporary).map_err(|_| "browser-metadata-write-failed".to_string())?;
        file.write_all(&serde_json::to_vec(tab).map_err(|_| "browser-metadata-encode-failed".to_string())?)
            .and_then(|_| file.sync_all()).map_err(|_| "browser-metadata-write-failed".to_string())?;
        drop(file);
        fs::rename(&temporary, &path).map_err(|_| "browser-metadata-replace-failed".to_string())
    }

    fn acquire(&self, registry: &mut Registry, tab: &Tab) -> Result<(), String> {
        if registry.profiles.contains_key(&tab.profile_id) { return Ok(()); }
        let path = self.profile_path(tab);
        fs::create_dir_all(&path).map_err(|_| "browser-profile-create-failed".to_string())?;
        let lease = lock_file(&path.join(".sumika-embedded.lock"))?;
        let human = registry.tabs.values().find(|entry| entry.profile_id == tab.profile_id && entry.takeover).map(|entry| entry.tab_id.clone());
        let writer = registry.tabs.values().find(|entry| entry.profile_id == tab.profile_id && entry.possibly_sent).map(|entry| entry.tab_id.clone());
        registry.profiles.insert(tab.profile_id.clone(), Profile { _lease: lease, writer, human, busy: false, draft: None, last_read: None });
        Ok(())
    }

    fn tab(&self, tab_id: &str) -> Result<Tab, String> {
        self.registry.lock().map_err(|_| "browser-state-poisoned".to_string())?.tabs.get(tab_id).cloned().ok_or_else(|| "browser-tab-not-found".into())
    }
}

fn workspace_visible(app: &AppHandle) -> bool {
    let Some(window) = app.get_window("main") else { return false; };
    window.is_visible().unwrap_or(false) && !window.is_minimized().unwrap_or(true)
}

pub fn hide_children(app: &AppHandle) -> Result<(), String> {
    for (label, webview) in app.webviews() {
        if label.starts_with("embedded-") {
            webview.hide().map_err(|_| "browser-hide-failed".to_string())?;
        }
    }
    if let Some(state) = app.try_state::<EmbeddedBrowserState>() {
        let mut registry = state.registry.lock().map_err(|_| "browser-state-poisoned".to_string())?;
        for tab in registry.tabs.values_mut() { tab.visible = false; }
    }
    Ok(())
}

async fn show_tab(app: &AppHandle, state: &EmbeddedBrowserState, tab_id: &str, bounds: Bounds) -> Result<Tab, String> {
    bounds.validate()?;
    hide_children(app)?;
    let child = app.get_webview(&label(tab_id)).ok_or_else(|| "browser-tab-closed".to_string())?;
    let window = app.get_window("main").ok_or_else(|| "main-window-missing".to_string())?;
    let size = window.inner_size().map_err(|_| "main-bounds-unavailable".to_string())?.to_logical::<f64>(window.scale_factor().map_err(|_| "main-scale-unavailable".to_string())?);
    let visible = workspace_visible(app) && bounds.x + bounds.width <= size.width + 1.0 && bounds.y + bounds.height <= size.height + 1.0;
    child.set_bounds(bounds.rect()).map_err(|_| "browser-bounds-failed".to_string())?;
    if visible { child.show().map_err(|_| "browser-show-failed".to_string())?; }
    let mut registry = state.registry.lock().map_err(|_| "browser-state-poisoned".to_string())?;
    let tab = registry.tabs.get_mut(tab_id).ok_or_else(|| "browser-tab-not-found".to_string())?;
    tab.bounds = bounds;
    tab.visible = visible;
    state.persist(tab)?;
    Ok(tab.clone())
}

pub async fn open(app: &AppHandle, state: &EmbeddedBrowserState, tab_id: String, account_id: String, raw_url: String, title: String, bounds: Option<Bounds>, site_id: Option<String>) -> Result<Tab, String> {
    let _lifecycle = state.lifecycle.lock().await;
    identifier(&tab_id)?;
    identifier(&account_id)?;
    validate_legacy_account(&account_id, site_id.as_deref())?;
    if let Some(bounds) = bounds { bounds.validate()?; }
    if title.len() > 160 || title.chars().any(char::is_control) { return Err("invalid-browser-title".into()); }
    let url = validate_url(&raw_url)?;
    let profile = profile_id(&account_id, &url, site_id.as_deref());
    let mut tab = {
        let mut registry = state.registry.lock().map_err(|_| "browser-state-poisoned".to_string())?;
        if !has_tab_capacity(&registry, &tab_id) { return Err("browser-tab-limit".into()); }
        if let Some(tab) = registry.tabs.get(&tab_id) {
            if tab.profile_id != profile || tab.account_id != account_id || tab.site_id != site_id || tab.url != safe_url(&url) {
                return Err("tab-binding-immutable-use-new-tab-id".into());
            }
            tab.clone()
        } else {
            let tab = Tab { tab_id: tab_id.clone(), account_id, url: safe_url(&url), title, profile_id: profile, visible: false, opened: false, status: "opened".into(), attempt_id: None, possibly_sent: false, takeover: false, reason: None, bounds: bounds.unwrap_or_default(), site_id, baseline_count: 0 };
            state.persist(&tab)?;
            registry.tabs.insert(tab_id.clone(), tab.clone());
            tab
        }
    };
    if app.get_webview(&label(&tab_id)).is_none() {
        {
            let mut registry = state.registry.lock().map_err(|_| "browser-state-poisoned".to_string())?;
            state.acquire(&mut registry, &tab)?;
        }
        let blank = "about:blank".parse().map_err(|_| "invalid-blank-url".to_string())?;
        let builder = tauri::webview::WebviewBuilder::new(label(&tab_id), WebviewUrl::External(blank))
            .data_directory(state.profile_path(&tab)).focused(false)
            .on_navigation(|url| validate_url(url.as_str()).is_ok())
            .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny);
        let child = app.get_window("main").ok_or_else(|| "main-window-missing".to_string())?
            .add_child(builder, LogicalPosition::new(-20000.0, -20000.0), LogicalSize::new(1.0, 1.0))
            .map_err(|_| "embedded-browser-unsupported-or-create-failed".to_string())?;
        child.hide().map_err(|_| "browser-hide-failed".to_string())?;
        if let Err(error) = install_network_guard(&child, state.profile_path(&tab)).await {
            let _ = child.close();
            return Err(error);
        }
        child.navigate(url).map_err(|_| "browser-navigation-failed".to_string())?;
        tab.opened = true;
        state.persist(&tab)?;
        state.registry.lock().map_err(|_| "browser-state-poisoned".to_string())?.tabs.insert(tab_id.clone(), tab);
    }
    if let Some(bounds) = bounds { show_tab(app, state, &tab_id, bounds).await }
    else { state.tab(&tab_id) }
}

#[tauri::command]
pub async fn embedded_browser_open(caller: Webview, app: AppHandle, state: State<'_, EmbeddedBrowserState>, tab_id: String, account_id: String, url: String, title: String, bounds: Option<Bounds>, legacy_site_id: Option<String>) -> Result<Tab, String> {
    super::consultation::authorize_main_caller(&caller)?;
    if let Some(site) = &legacy_site_id { super::validate_portal_site_id(site)?; }
    open(&app, &state, tab_id, account_id, url, title, bounds, legacy_site_id).await
}

#[tauri::command]
pub async fn embedded_browser_bounds(caller: Webview, app: AppHandle, state: State<'_, EmbeddedBrowserState>, tab_id: String, x: f64, y: f64, width: f64, height: f64) -> Result<Tab, String> {
    super::consultation::authorize_main_caller(&caller)?;
    let _lifecycle = state.lifecycle.lock().await;
    show_tab(&app, &state, &tab_id, Bounds { x, y, width, height }).await
}

#[tauri::command]
pub async fn embedded_browser_list(caller: Webview, state: State<'_, EmbeddedBrowserState>) -> Result<Vec<Tab>, String> {
    super::consultation::authorize_main_caller(&caller)?;
    list(&state)
}

pub fn list(state: &EmbeddedBrowserState) -> Result<Vec<Tab>, String> {
    Ok(state.registry.lock().map_err(|_| "browser-state-poisoned".to_string())?.tabs.values()
        .filter(|tab| tab.opened || tab.possibly_sent || tab.status == "restored").cloned().collect())
}

#[tauri::command]
pub async fn embedded_browser_hide_all(caller: Webview, app: AppHandle, state: State<'_, EmbeddedBrowserState>) -> Result<Vec<Tab>, String> {
    super::consultation::authorize_main_caller(&caller)?;
    hide_children(&app)?;
    list(&state)
}

pub async fn close(app: &AppHandle, state: &EmbeddedBrowserState, tab_id: &str) -> Result<Tab, String> {
    let _lifecycle = state.lifecycle.lock().await;
    let mut registry = state.registry.lock().map_err(|_| "browser-state-poisoned".to_string())?;
    let mut tab = registry.tabs.get(tab_id).cloned().ok_or_else(|| "browser-tab-not-found".to_string())?;
    if registry.profiles.get(&tab.profile_id).is_some_and(|profile| profile.busy) { return Err("profile-operation-in-flight".into()); }
    if let Some(child) = app.get_webview(&label(tab_id)) { child.close().map_err(|_| "browser-close-failed".to_string())?; }
    tab.opened = false;
    tab.visible = false;
    tab.status = if tab.possibly_sent { "unknown" } else { "closed" }.into();
    state.persist(&tab)?;
    registry.tabs.insert(tab_id.into(), tab.clone());
    if let Some(profile) = registry.profiles.get_mut(&tab.profile_id) {
        if profile.writer.as_deref() == Some(tab_id) && !tab.possibly_sent { profile.writer = None; profile.draft = None; }
    }
    Ok(tab)
}

#[tauri::command]
pub async fn embedded_browser_close(caller: Webview, app: AppHandle, state: State<'_, EmbeddedBrowserState>, tab_id: String) -> Result<Tab, String> {
    super::consultation::authorize_main_caller(&caller)?;
    close(&app, &state, &tab_id).await
}

pub async fn focus_portal(app: &AppHandle, state: &EmbeddedBrowserState, site_id: &str) -> Result<(), String> {
    let tab = state.tab(&format!("portal-{site_id}"))?;
    open(app, state, tab.tab_id, tab.account_id, tab.url, tab.title, None, tab.site_id).await?;
    Ok(())
}

fn fixed_expression(source: &str, name: &str) -> Result<String, String> {
    let marker = format!("{name} = r\"\"\"");
    source.split_once(&marker).and_then(|(_, rest)| rest.split_once("\"\"\"")).map(|(script, _)| script.to_string()).ok_or_else(|| "fixed-reader-source-invalid".into())
}

fn modelscope_expression(name: &str) -> Result<String, String> {
    let guard = fixed_expression(MODELSCOPE_SOURCE, "_PAGE_GUARD")?;
    let marker = format!("{name} = \"JSON.stringify((() => {{\\n\" + _PAGE_GUARD + r\"\"\"");
    let body = MODELSCOPE_SOURCE.split_once(&marker).and_then(|(_, rest)| rest.split_once("\"\"\"")).map(|(script, _)| script).ok_or_else(|| "fixed-reader-source-invalid".to_string())?;
    Ok(format!("JSON.stringify((() => {{\n{guard}{body}"))
}

fn account_source(url: &tauri::Url) -> Option<&'static str> {
    if url.scheme() != "https" || url.port().is_some() || url.fragment().is_some()
        || !url.username().is_empty() || url.password().is_some() { return None; }
    match (url.host_str(), url.path()) {
        (Some("modelscope.cn"), "/magicube/usage") => Some("modelscope"),
        (Some("ollama.com"), "/settings") if url.query().is_none() => Some("ollama"),
        _ => None,
    }
}

fn receipt_page(url: &tauri::Url) -> bool {
    url.scheme() == "https" && url.host_str() == Some("moark.com") && url.path() == "/serverless-api"
        && url.port().is_none() && url.fragment().is_none() && url.username().is_empty() && url.password().is_none()
}

#[cfg(debug_assertions)]
#[tauri::command]
pub async fn embedded_browser_reader_probe(caller: Webview, app: AppHandle, state: State<'_, EmbeddedBrowserState>, tab_id: String) -> Result<Value, String> {
    super::consultation::authorize_main_caller(&caller)?;
    let tab = state.tab(&tab_id)?;
    check_automation(&app, &state, &tab)?;
    let child = app.get_webview(&label(&tab_id)).ok_or_else(|| "browser-tab-closed".to_string())?;
    let url = child.url().map_err(|_| "browser-url-unavailable".to_string())?;
    if account_source(&url) != Some("modelscope") && !receipt_page(&url) { return Err("unsupported-diagnostic-page".into()); }
    evaluate(&child, r#"(() => {
        const modelscope = location.origin === 'https://modelscope.cn' && location.pathname === '/magicube/usage';
        const moark = location.origin === 'https://moark.com' && location.pathname === '/serverless-api';
        if (!modelscope && !moark) return JSON.stringify({state:'needs-review',reason:'wrong-page'});
        const visible = element => element.getClientRects().length > 0 && !element.closest('[hidden],[aria-hidden=true]');
        const elements = Array.from(document.querySelectorAll('button,[role=tab],div,span')).slice(0,6000);
        const labels = [...new Set(elements.filter(element => visible(element) && element.childElementCount === 0)
            .map(element => element.textContent.trim()).filter(text => /^[\u4e00-\u9fff]{0,12}(记录|统计|明细|魔粒|额度)$/.test(text)))].slice(0,20);
        const recordLabels = ['发放记录', '消耗统计'];
        const feature = element => recordLabels.includes(element.textContent.trim()) ? element.textContent.trim() : null;
        const structure = elements.filter(element => visible(element) && element.childElementCount === 0 && feature(element))
            .slice(0,8).map(element => {
                const ancestors = [];
                for (let parent = element.parentElement; parent && ancestors.length < 3; parent = parent.parentElement) {
                    ancestors.push({tag:parent.tagName,children:Array.from(parent.children).slice(0,8).map(child =>
                        ({tag:child.tagName,children:child.childElementCount,label:feature(child),
                          sibling_function_label:['赚魔粒', ...recordLabels].includes(child.textContent.trim()) ? child.textContent.trim() : null,
                          empty:!child.textContent.trim(),visible:visible(child)}))});
                }
                return {label:feature(element),tag:element.tagName,ancestors};
            });
        const resources = performance.getEntriesByType('resource').flatMap(entry => {
            try {
                const url = new URL(entry.name);
                if (url.origin !== location.origin || !/^\/api\/base\/[A-Za-z0-9_-]+\/(profile|inference-logs)$/.test(url.pathname)) return [];
                return [{kind:url.pathname.endsWith('/profile')?'profile':'receipts',duration_ms:Math.round(entry.duration),
                    transfer_bytes:entry.transferSize,status:entry.responseStatus || null}];
            } catch { return []; }
        }).slice(-12);
        return JSON.stringify({state:'diagnostic',ready:document.readyState,feature_labels:labels,record_structure:structure,
            legacy_tabs:document.querySelectorAll('.acss-zav6uu > *').length,
            semantic_tabs:document.querySelectorAll('[role=tab]').length,
            magic_cube_controls:document.querySelectorAll('[aria-label="Magic Cube"]').length,
            resources});
    })()"#.into()).await
}

fn decode(raw: &str) -> Result<Value, String> {
    if raw.len() > MAX_RESULT { return Err("browser-result-too-large".into()); }
    let value: Value = serde_json::from_str(raw).map_err(|_| "browser-result-invalid".to_string())?;
    let value = if let Value::String(value) = value { serde_json::from_str(&value).map_err(|_| "browser-result-invalid".to_string())? } else { value };
    if !value.is_object() { return Err("browser-result-invalid".into()); }
    Ok(value)
}

#[cfg(windows)]
async fn evaluate(webview: &Webview, script: String) -> Result<Value, String> {
    use webview2_com::ExecuteScriptCompletedHandler;
    use windows::core::HSTRING;
    let (sender, receiver) = tokio::sync::oneshot::channel();
    let sender = Arc::new(Mutex::new(Some(sender)));
    webview.with_webview(move |platform| {
        let result = (|| -> Result<(), String> {
            let core = unsafe { platform.controller().CoreWebView2() }.map_err(|_| "browser-evaluation-unavailable".to_string())?;
            let callback_sender = sender.clone();
            let handler = ExecuteScriptCompletedHandler::create(Box::new(move |code, raw| {
                if let Ok(mut sender) = callback_sender.lock() {
                    if let Some(sender) = sender.take() { let _ = sender.send(if code.is_ok() { decode(&raw) } else { Err("browser-evaluation-failed".into()) }); }
                }
                Ok(())
            }));
            unsafe { core.ExecuteScript(&HSTRING::from(script), &handler) }.map_err(|_| "browser-evaluation-dispatch-failed".to_string())
        })();
        if let Err(error) = result {
            if let Ok(mut sender) = sender.lock() { if let Some(sender) = sender.take() { let _ = sender.send(Err(error)); } }
        }
    }).map_err(|_| "browser-evaluation-schedule-failed".to_string())?;
    tokio::time::timeout(Duration::from_secs(8), receiver).await.map_err(|_| "browser-evaluation-timeout".to_string())?.map_err(|_| "browser-evaluation-dropped".to_string())?
}

#[cfg(not(windows))]
async fn evaluate(_webview: &Webview, _script: String) -> Result<Value, String> { Err("unsupported-native-engine".into()) }

#[cfg(windows)]
async fn install_network_guard(webview: &Webview, expected_directory: PathBuf) -> Result<(), String> {
    use webview2_com::{take_pwstr, WebResourceRequestedEventHandler, Microsoft::Web::WebView2::Win32::*};
    use windows::core::{HSTRING, Interface, PWSTR};
    let (sender, receiver) = tokio::sync::oneshot::channel();
    webview.with_webview(move |platform| {
        let result = (|| -> windows::core::Result<()> {
            let core = unsafe { platform.controller().CoreWebView2()? };
            let environment = platform.environment();
            let modern_environment: ICoreWebView2Environment7 = environment.cast()?;
            let mut folder = PWSTR::null();
            unsafe { modern_environment.UserDataFolder(&mut folder)?; }
            let actual_directory = PathBuf::from(take_pwstr(folder));
            if fs::canonicalize(actual_directory).ok().zip(fs::canonicalize(expected_directory).ok())
                .is_none_or(|(actual, expected)| actual != expected) {
                return Err(windows::core::Error::from_hresult(windows::core::HRESULT(0x80070005u32 as i32)));
            }
            let modern: ICoreWebView2_22 = core.cast()?;
            unsafe { modern.AddWebResourceRequestedFilterWithRequestSourceKinds(&HSTRING::from("*"), COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL, COREWEBVIEW2_WEB_RESOURCE_REQUEST_SOURCE_KINDS_ALL)?; }
            let handler = WebResourceRequestedEventHandler::create(Box::new(move |_, args| {
                let Some(args) = args else { return Ok(()); };
                unsafe {
                    let request = args.Request()?;
                    let mut uri = PWSTR::null();
                    request.Uri(&mut uri)?;
                    let uri = take_pwstr(uri);
                    if validate_url(&uri).is_err() && !uri.starts_with("data:") && !uri.starts_with("blob:https://") {
                        let response = environment.CreateWebResourceResponse(None, 403, &HSTRING::from("Blocked by Sumika"), &HSTRING::from("Content-Type: text/plain\r\nCache-Control: no-store"))?;
                        args.SetResponse(&response)?;
                    }
                }
                Ok(())
            }));
            let mut token = 0;
            unsafe { core.add_WebResourceRequested(&handler, &mut token)?; }
            Ok(())
        })();
        let _ = sender.send(result.map_err(|_| "unsupported-native-network-isolation".to_string()));
    }).map_err(|_| "browser-guard-schedule-failed".to_string())?;
    tokio::time::timeout(Duration::from_secs(8), receiver).await.map_err(|_| "browser-guard-timeout".to_string())?.map_err(|_| "browser-guard-dropped".to_string())?
}

#[cfg(not(windows))]
async fn install_network_guard(_webview: &Webview, _expected_directory: PathBuf) -> Result<(), String> { Err("unsupported-native-network-isolation".into()) }

fn check_automation(app: &AppHandle, state: &EmbeddedBrowserState, tab: &Tab) -> Result<(), String> {
    if !workspace_visible(app) { return Err("browser-workspace-not-visible".into()); }
    let registry = state.registry.lock().map_err(|_| "browser-state-poisoned".to_string())?;
    if registry.profiles.get(&tab.profile_id).is_none_or(|profile| profile.human.is_some()) {
        return Err("browser-taken-over".into());
    }
    Ok(())
}

fn reader_reason(observation: &Value) -> Option<&str> {
    observation.get("reason").and_then(Value::as_str).filter(|reason| matches!(*reason,
        "unbounded-page" | "challenge" | "login-required" | "wrong-page" | "page-loading"
        | "ambiguous-records-tab" | "select-grant-records" | "missing-balance" | "invalid-balance"
        | "missing-grants" | "unbounded-grants" | "invalid-grant-row" | "invalid-grant-date"
        | "duplicate-grant" | "no-grant-evidence" | "records-selected" | "initial-blank" | "missing-records-tabs"
        | "missing-usage-section" | "allowed-models-changed" | "invalid-usage-evidence" | "invalid-reset-display"
        | "profile-resource-unavailable" | "ambiguous-account-profile" | "lossless-json-parser-unavailable"
        | "official-log-auth-rejected" | "official-log-forbidden" | "official-log-rate-limited" | "official-log-read-failed"
        | "log-page-too-large" | "invalid-log-json" | "invalid-log-schema" | "log-pagination-changed-or-unbounded"
        | "invalid-log-amount-or-model" | "invalid-receipt-identity" | "account-read-timeout" | "receipt-read-timeout"
        | "abort-controller-unavailable" | "receipt-read-cancelled" | "official-log-read-timeout"
        | "receipt-fetch-timeout" | "receipt-body-timeout" | "receipt-hash-timeout" | "receipt-context-lost"))
}

fn reader_timeout(observation: &Value) -> Value {
    json!({"state":"needs-review", "reason":reader_reason(observation).unwrap_or("account-read-timeout")})
}

fn receipt_profile_pending(observation: &Value) -> bool {
    observation.get("state").and_then(Value::as_str) == Some("needs-review")
        && reader_reason(observation) == Some("profile-resource-unavailable")
}

fn account_result(tab: Tab, source: &str, observation: Value) -> ActionResult {
    let mut result = ActionResult::new(tab);
    result.status = observation.get("state").and_then(Value::as_str).unwrap_or("needs-review").to_string();
    result.reason = reader_reason(&observation).map(str::to_string);
    result.source = Some(source.into());
    result.observation = Some(observation);
    result
}

async fn read_account(child: &Webview, source: &str, app: &AppHandle, state: &EmbeddedBrowserState, tab: &Tab) -> Result<Value, String> {
    let expression = if source == "modelscope" { modelscope_expression("READ_EXPRESSION")? }
        else { fixed_expression(OLLAMA_SOURCE, "OLLAMA_EXPRESSION")? };
    let mut selected = false;
    let mut last = json!({"state":"pending"});
    for _attempt in 0..24 {
        check_automation(app, state, tab)?;
        let observation = evaluate(child, expression.clone()).await?;
        check_automation(app, state, tab)?;
        match observation.get("state").and_then(Value::as_str) {
            Some("select-records") if source == "modelscope" && !selected => {
                let selection = evaluate(child, modelscope_expression("SELECT_RECORDS_EXPRESSION")?).await?;
                if selection.get("state").and_then(Value::as_str) != Some("pending") { return Ok(selection); }
                selected = selection.get("reason").and_then(Value::as_str) == Some("records-selected");
            }
            Some("select-records") if source == "modelscope" && selected => {}
            Some("pending") => {}
            Some("needs-review") if observation.get("reason").and_then(Value::as_str) == Some("missing-usage-section") => {}
            _ => return Ok(observation),
        }
        last = observation;
        tokio::time::sleep(Duration::from_millis(400)).await;
    }
    Ok(reader_timeout(&last))
}

async fn read_receipts(child: &Webview, app: &AppHandle, state: &EmbeddedBrowserState, tab: &Tab) -> Result<Value, String> {
    let expression = fixed_expression(OLLAMA_SOURCE, "MOARK_RECEIPTS_EXPRESSION")?;
    let body = expression.trim().strip_suffix("})()").ok_or_else(|| "fixed-reader-source-invalid".to_string())?;
    let expression = format!("{body}}})({{signal:receiptRead.controller.signal,onStage:stage => {{receiptRead.stage = stage;}}}})");
    let started = format!("(() => {{ const receiptRead = {{result:null,stage:'initial',controller:new AbortController()}}; window.__sumikaReceiptRead = receiptRead; Promise.resolve({expression}).then(value => {{ if (window.__sumikaReceiptRead === receiptRead) receiptRead.result = value; }}, () => {{ if (window.__sumikaReceiptRead === receiptRead) receiptRead.result = JSON.stringify({{state:'needs-review',reason:'official-log-read-failed'}}); }}); return JSON.stringify({{state:'pending'}}); }})()");
    check_automation(app, state, tab)?;
    evaluate(child, started.clone()).await?;
    let mut last = json!({"state":"pending", "reason":"receipt-read-timeout"});
    let outcome = tokio::time::timeout(Duration::from_secs(14), async {
        for attempt in 0..30 {
            tokio::time::sleep(Duration::from_millis(400)).await;
            check_automation(app, state, tab)?;
            let result = evaluate(child, r#"(() => {
                const read = window.__sumikaReceiptRead;
                if (!read) return JSON.stringify({state:'needs-review',reason:'receipt-context-lost'});
                if (read.result) return read.result;
                const reasons = {fetch:'receipt-fetch-timeout',body:'receipt-body-timeout',hash:'receipt-hash-timeout'};
                return JSON.stringify({state:'pending',reason:reasons[read.stage] || 'receipt-read-timeout'});
            })()"#.into()).await?;
            check_automation(app, state, tab)?;
            if receipt_profile_pending(&result) {
                last = result;
                if attempt < 29 { evaluate(child, started.clone()).await?; }
                continue;
            }
            if result.get("state").and_then(Value::as_str) != Some("pending") { return Ok(result); }
            last = result;
        }
        Ok(reader_timeout(&last))
    }).await;
    let _ = evaluate(child, "(() => { window.__sumikaReceiptRead?.controller.abort(); delete window.__sumikaReceiptRead; return JSON.stringify({state:'cleared'}); })()".into()).await;
    outcome.unwrap_or_else(|_| Ok(reader_timeout(&last)))
}

#[tauri::command]
pub async fn embedded_browser_action(caller: Webview, app: AppHandle, state: State<'_, EmbeddedBrowserState>, tab_id: String, action: String, attempt_id: Option<String>, text: Option<String>) -> Result<ActionResult, String> {
    super::consultation::authorize_main_caller(&caller)?;
    if !matches!(action.as_str(), "observe" | "fill" | "submit" | "read" | "takeover" | "release" | "read-account" | "read-receipts") {
        return Err("unsupported-browser-action".into());
    }
    if !workspace_visible(&app) { return Err("browser-workspace-not-visible".into()); }
    if let Some(attempt) = &attempt_id { identifier(attempt)?; }
    if text.as_ref().is_some_and(|value| value.len() > 32000 || value.trim().is_empty()) { return Err("bounded-message-required".into()); }
    let child = app.get_webview(&label(&tab_id)).ok_or_else(|| "browser-tab-closed".to_string())?;
    let mut tab = state.tab(&tab_id)?;
    if action == "read" && tab.possibly_sent && tab.reason.as_deref() == Some("restored-metadata-only-no-navigation-or-resubmit") {
        let mut result = ActionResult::new(tab);
        result.status = "unknown".into();
        result.reason = Some("restart-requires-manual-original-request-reconciliation".into());
        return Ok(result);
    }
    {
        let mut registry = state.registry.lock().map_err(|_| "browser-state-poisoned".to_string())?;
        state.acquire(&mut registry, &tab)?;
        let profile = registry.profiles.get_mut(&tab.profile_id).ok_or_else(|| "browser-profile-missing".to_string())?;
        if action == "takeover" || action == "release" {
            let takeover = action == "takeover";
            profile.human = if takeover { Some(tab_id.clone()) } else { None };
            for peer in registry.tabs.values_mut().filter(|peer| peer.profile_id == tab.profile_id) {
                peer.takeover = takeover;
                state.persist(peer)?;
            }
            tab.takeover = takeover;
            let mut result = ActionResult::new(tab);
            result.status = if takeover { "takeover" } else { "released" }.into();
            return Ok(result);
        }
        if profile.busy || profile.human.is_some() || profile.writer.as_ref().is_some_and(|writer| writer != &tab_id) {
            return Err("browser-account-occupied-or-takeover".into());
        }
        if action == "fill" && (tab.possibly_sent || tab.attempt_id.as_ref() == attempt_id.as_ref() || attempt_id.is_none()) {
            return Err("recover-original-attempt-before-new-message".into());
        }
        if matches!(action.as_str(), "submit" | "read") && (attempt_id.is_none() || attempt_id != tab.attempt_id) {
            return Err("browser-attempt-mismatch".into());
        }
        if action == "submit" && (tab.possibly_sent || profile.draft.as_ref().is_none_or(|(owner, attempt, _)| owner != &tab_id || Some(attempt) != attempt_id.as_ref())) {
            return Err("browser-submit-not-prepared-or-already-sent".into());
        }
        profile.busy = true;
    }
    let operation = async {
        let current = child.url().map_err(|_| "browser-url-unavailable".to_string())?;
        if action == "read-receipts" {
            if !receipt_page(&current) { return Err("unsupported-receipts-page".into()); }
            let observation = read_receipts(&child, &app, &state, &tab).await?;
            return Ok(account_result(tab.clone(), "moark", observation));
        }
        if action == "read-account" {
            let source = account_source(&current).ok_or_else(|| "unsupported-account-page".to_string())?;
            let observation = read_account(&child, source, &app, &state, &tab).await?;
            return Ok(account_result(tab.clone(), source, observation));
        }
        let expected = validate_url(&tab.url)?.origin().ascii_serialization();
        if current.origin().ascii_serialization() != expected { return Err("browser-origin-changed".into()); }
        let value = if action == "submit" {
            let mut registry = state.registry.lock().map_err(|_| "browser-state-poisoned".to_string())?;
            let profile = registry.profiles.get_mut(&tab.profile_id).ok_or_else(|| "browser-profile-missing".to_string())?;
            if profile.human.is_some() { return Err("browser-taken-over".into()); }
            let value = profile.draft.as_ref().ok_or_else(|| "browser-draft-missing".to_string())?.2.clone();
            tab.possibly_sent = true;
            tab.status = "unknown".into();
            state.persist(&tab)?;
            registry.tabs.insert(tab_id.clone(), tab.clone());
            value
        } else { text.clone().unwrap_or_default() };
        let script = include_str!("embedded-chat.js").replace("__ACTION__", &json!(action).to_string())
            .replace("__TEXT__", &json!(value).to_string()).replace("__ORIGIN__", &json!(expected).to_string());
        check_automation(&app, &state, &tab)?;
        let response = evaluate(&child, script).await?;
        let mut status = response.get("status").and_then(Value::as_str).unwrap_or("unknown").to_string();
        let response_text = response.get("text").and_then(Value::as_str).unwrap_or("").to_string();
        let count = response.get("assistant_count").and_then(Value::as_u64).unwrap_or(0) as usize;
        let mut registry = state.registry.lock().map_err(|_| "browser-state-poisoned".to_string())?;
        let profile = registry.profiles.get_mut(&tab.profile_id).ok_or_else(|| "browser-profile-missing".to_string())?;
        if action == "fill" && status == "filled" {
            tab.reason = None;
            tab.attempt_id = attempt_id.clone();
            tab.baseline_count = count;
            profile.writer = Some(tab_id.clone());
            profile.draft = Some((tab_id.clone(), attempt_id.clone().unwrap(), value));
            profile.last_read = None;
        }
        if action == "submit" {
            tab.possibly_sent = response.get("possibly_sent").and_then(Value::as_bool) != Some(false);
            if !tab.possibly_sent { profile.writer = None; profile.draft = None; }
        }
        if action == "read" {
            let signature = digest(&response_text);
            let changed = count > tab.baseline_count && !response_text.trim().is_empty();
            let stable = profile.last_read.as_ref().is_some_and(|(owner, previous)| owner == &tab_id && previous == &signature);
            if changed && status == "ready" && stable {
                status = "completed".into();
                profile.writer = None;
                profile.draft = None;
                tab.possibly_sent = false;
            } else if tab.status == "completed" && changed { status = "completed".into(); }
            else if matches!(status.as_str(), "ready" | "pending") { status = "pending".into(); }
            profile.last_read = if changed && status != "pending" || changed && response.get("status").and_then(Value::as_str) == Some("ready") {
                Some((tab_id.clone(), signature))
            } else { None };
        }
        if action != "observe" || !tab.possibly_sent { tab.status = status.clone(); }
        tab.takeover = profile.human.is_some();
        state.persist(&tab)?;
        registry.tabs.insert(tab_id.clone(), tab.clone());
        let mut result = ActionResult::new(tab.clone());
        result.status = status;
        if result.status == "completed" { result.text = response_text; result.possibly_sent = true; }
        Ok(result)
    }.await;
    if let Ok(mut registry) = state.registry.lock() {
        if let Some(profile) = registry.profiles.get_mut(&tab.profile_id) { profile.busy = false; }
    }
    operation
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn public_https_only_and_account_isolation() {
        for raw in ["http://example.org/", "https://127.0.0.1/", "https://localhost/", "https://user:password@example.org/", "file:///C:/Windows", "https://192.168.0.1/", "https://example.org:8443/"] { assert!(validate_url(raw).is_err()); }
        let url = validate_url("https://chatgpt.com/").unwrap();
        assert_ne!(profile_id("alice", &url, None), profile_id("bob", &url, None));
        assert_eq!(profile_id("chatgpt", &url, Some("chatgpt")), "legacy-chatgpt");
        assert!(validate_legacy_account("chatgpt", Some("chatgpt")).is_ok());
        assert!(validate_legacy_account("second", Some("chatgpt")).is_err());
        assert!(validate_legacy_account("second", None).is_ok());
    }

    #[test]
    fn closed_tab_history_does_not_exhaust_live_capacity() {
        let mut registry = Registry::default();
        for index in 0..MAX_TABS + 5 {
            let tab_id = format!("tab-{index}");
            registry.tabs.insert(tab_id.clone(), Tab { tab_id, account_id: "fixture".into(), url: "https://example.org/".into(),
                title: "fixture".into(), profile_id: "fixture".into(), visible: false, opened: false, status: "closed".into(),
                attempt_id: None, possibly_sent: false, takeover: false, reason: None, bounds: Bounds::default(), site_id: None, baseline_count: 0 });
        }
        assert!(has_tab_capacity(&registry, "new"));
        for tab in registry.tabs.values_mut().take(MAX_TABS) { tab.opened = true; }
        assert!(!has_tab_capacity(&registry, "new"));
        let existing = registry.tabs.values().find(|tab| tab.opened).unwrap();
        assert!(has_tab_capacity(&registry, &existing.tab_id));
    }

    #[test]
    fn only_registered_account_pages_and_fixed_readers() {
        assert_eq!(account_source(&validate_url("https://ollama.com/settings").unwrap()), Some("ollama"));
        assert_eq!(account_source(&validate_url("https://ollama.com/settings/keys").unwrap()), None);
        assert!(modelscope_expression("READ_EXPRESSION").unwrap().contains("available_balance"));
        assert!(modelscope_expression("SELECT_RECORDS_EXPRESSION").unwrap().contains("records-selected"));
        assert!(fixed_expression(OLLAMA_SOURCE, "OLLAMA_EXPRESSION").unwrap().contains("free_usage_percent"));
    }

    #[test]
    fn fixed_account_pages_accept_opaque_query_without_expanding_origins_or_paths() {
        assert_eq!(account_source(&"https://modelscope.cn/magicube/usage?opaque=fixture".parse().unwrap()), Some("modelscope"));
        assert!(receipt_page(&"https://moark.com/serverless-api?opaque=fixture".parse().unwrap()));
        assert!(account_source(&"https://ollama.com/settings?opaque=fixture".parse().unwrap()).is_none());
        for raw in ["https://modelscope.cn/magicube/usage#other", "https://modelscope.cn/magicube/usage/", "https://modelscope.cn/settings",
            "https://other.invalid/magicube/usage", "http://modelscope.cn/magicube/usage", "https://user:password@modelscope.cn/magicube/usage",
            "https://modelscope.cn:8443/magicube/usage"] {
            assert!(account_source(&raw.parse().unwrap()).is_none());
        }
        for raw in ["https://moark.com/serverless-api#other", "https://moark.com/serverless-api/", "https://moark.com/settings",
            "https://other.invalid/serverless-api", "http://moark.com/serverless-api", "https://user:password@moark.com/serverless-api",
            "https://moark.com:8443/serverless-api"] {
            assert!(!receipt_page(&raw.parse().unwrap()));
        }
    }

    #[test]
    fn account_timeout_keeps_only_fixed_diagnostic_codes() {
        for reason in ["missing-records-tabs", "missing-balance", "missing-grants", "missing-usage-section"] {
            assert_eq!(reader_timeout(&json!({"state":"pending", "reason":reason})), json!({"state":"needs-review", "reason":reason}));
        }
        let untrusted = json!({"state":"pending", "reason":"private-page-content", "body":"unrelated-account-data"});
        assert_eq!(reader_timeout(&untrusted), json!({"state":"needs-review", "reason":"account-read-timeout"}));
        assert!(reader_reason(&untrusted).is_none());
    }

    #[test]
    fn only_missing_profile_resource_can_retry_receipt_initialization() {
        let pending = json!({"state":"needs-review", "reason":"profile-resource-unavailable"});
        assert!(receipt_profile_pending(&pending));
        assert_eq!(reader_timeout(&pending), pending);
        for reason in ["official-log-auth-rejected", "official-log-forbidden", "official-log-rate-limited",
            "invalid-log-schema", "ambiguous-account-profile", "private-page-content"] {
            assert!(!receipt_profile_pending(&json!({"state":"needs-review", "reason":reason})));
        }
        assert!(!receipt_profile_pending(&json!({"state":"verified", "reason":"profile-resource-unavailable"})));
    }

    #[test]
    fn account_actions_surface_fixed_failure_reasons_without_login_inference() {
        let tab = Tab { tab_id:"account-moark".into(), account_id:"moark".into(), url:"https://moark.com/serverless-api".into(),
            title:"fixture".into(), profile_id:"fixture".into(), visible:true, opened:true, status:"opened".into(),
            attempt_id:None, possibly_sent:false, takeover:false, reason:None, bounds:Bounds::default(), site_id:None, baseline_count:0 };
        let result = account_result(tab, "moark", json!({"state":"needs-review", "reason":"profile-resource-unavailable"}));
        assert_eq!(result.reason.as_deref(), Some("profile-resource-unavailable"));
        assert_eq!(result.status, "needs-review");
        assert_eq!(result.source.as_deref(), Some("moark"));
        let script = fixed_expression(OLLAMA_SOURCE, "MOARK_RECEIPTS_EXPRESSION").unwrap();
        assert!(script.contains("ambiguous-account-profile"));
        assert!(!script.contains("login-or-profile-required"));
    }
}
