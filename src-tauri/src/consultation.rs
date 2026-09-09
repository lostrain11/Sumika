use std::fs::{self, File, OpenOptions};
use std::io::{ErrorKind, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, LogicalPosition, LogicalSize, Manager, Rect, State, Webview, WebviewUrl};

const CHATGPT_URL: &str = "https://chatgpt.com/";
const CHATGPT_LOGIN_URL: &str = "https://chatgpt.com/auth/login";
const CHATGPT_ORIGIN: &str = "https://chatgpt.com";
const LOGIN_HOST: &str = "auth.openai.com";
const CONSULTATION_LABEL: &str = "consultation-chatgpt";
const PROFILE_DIRNAME: &str = "consultation/chatgpt";
const PROFILE_LOCK_FILENAME: &str = ".sumika-profile.lock";
const JOURNAL_FILENAME: &str = ".sumika-attempt.json";
const MAX_INPUT_BYTES: usize = 32 * 1024;
const MAX_EVAL_BYTES: usize = 128 * 1024;
const MAX_RESULT_BYTES: usize = 64 * 1024;
const MAX_REASON_BYTES: usize = 1024;
const EVAL_TIMEOUT: Duration = Duration::from_secs(8);

const OBSERVE_SCRIPT: &str = r##"
(() => {
  try {
    const visible = (node) => !!node && node.getClientRects().length > 0;
    const first = (selectors) => selectors.map((selector) => document.querySelector(selector)).find(visible) || null;
    const composerSelectors = [
      "textarea[data-composer-draft-react]",
      "#prompt-textarea",
      "textarea[placeholder*='Message']",
      "[contenteditable='true'][data-lexical-editor='true']",
      "[contenteditable='true'][role='textbox']"
    ];
    const explicitSendSelectors = [
      "button[data-composer-submit]",
      "button[data-testid='send-button']",
      "button[aria-label='Send prompt']",
      "button[aria-label='Send message']"
    ];
    const responseSelectors = [
      "[data-assistant-markdown]",
      "[data-message-role='assistant']",
      "[data-message-author-role='assistant']"
    ];
    const pageText = (document.body?.innerText || "").slice(0, 12000);
    const lower = pageText.toLowerCase();
    const challenge = /verify you are human|checking your browser|cloudflare|安全验证|人机验证|验证码/.test(lower);
    const limited = /usage limit|rate limit|too many requests|try again later|reached.*limit|已达到.*限制|请求过多|稍后再试/.test(lower);
    const login = !first(composerSelectors) && (/log in|sign up|登录|注册/.test(lower) || first(["a[href*='auth/login']", "button[data-testid*='login']"]));
    const pending = !!first(["button[data-testid='stop-button']", "button[aria-label*='Stop']", "[data-testid='composer-speech-button'][disabled]"]);
    const composer = first(composerSelectors);
    const scopedSend = first(explicitSendSelectors) || (composer?.closest("form")
      ? Array.from(composer.closest("form").querySelectorAll("button[type='submit']")).find(visible) || null
      : null);
    const responses = responseSelectors.flatMap((selector) => Array.from(document.querySelectorAll(selector))).filter(visible);
    const last = responses.length ? (responses[responses.length - 1].innerText || responses[responses.length - 1].textContent || "") : "";
    const status = challenge ? "challenge" : limited ? "limited" : login ? "login" : pending ? "pending" : composer ? "ready" : "unavailable";
    const reason = status !== "unavailable" ? null : document.readyState !== "complete" ? "page-loading" : pageText.trim() ? "composer-not-found" : "empty-document";
    return JSON.stringify({ status, reason, text: last.slice(0, 65536), assistant_count: responses.length, composer: !!composer, send: !!scopedSend, pending });
  } catch (error) {
    return JSON.stringify({ status: "error", reason: String(error).slice(0, 1024) });
  }
})()
"##;

const FILL_SCRIPT: &str = r##"
((value) => {
  try {
    const visible = (node) => !!node && node.getClientRects().length > 0;
    const first = (selectors) => selectors.map((selector) => document.querySelector(selector)).find(visible) || null;
    const composerSelectors = [
      "textarea[data-composer-draft-react]",
      "#prompt-textarea",
      "textarea[placeholder*='Message']",
      "[contenteditable='true'][data-lexical-editor='true']",
      "[contenteditable='true'][role='textbox']"
    ];
    const responseSelectors = [
      "[data-assistant-markdown]",
      "[data-message-role='assistant']",
      "[data-message-author-role='assistant']"
    ];
    const composer = first(composerSelectors);
    if (!composer) return JSON.stringify({ status: "unavailable", reason: "composer-not-found" });
    composer.focus();
    if (composer instanceof HTMLTextAreaElement || composer instanceof HTMLInputElement) {
      const prototype = composer instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
      if (!setter) return JSON.stringify({ status: "error", reason: "native-value-setter-missing" });
      setter.call(composer, value);
    } else {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(composer);
      selection.removeAllRanges();
      selection.addRange(range);
      if (!document.execCommand("insertText", false, value)) composer.textContent = value;
    }
    composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
    composer.dispatchEvent(new Event("change", { bubbles: true }));
    const responses = responseSelectors.flatMap((selector) => Array.from(document.querySelectorAll(selector))).filter(visible);
    const last = responses.length ? (responses[responses.length - 1].innerText || responses[responses.length - 1].textContent || "") : "";
    return JSON.stringify({ status: "filled", assistant_count: responses.length, text: last.slice(0, 65536) });
  } catch (error) {
    return JSON.stringify({ status: "error", reason: String(error).slice(0, 1024) });
  }
})(__SUMIKA_TEXT__)
"##;

const SUBMIT_SCRIPT: &str = r##"
(() => {
  try {
    const visible = (node) => !!node && node.getClientRects().length > 0;
    const first = (selectors) => selectors.map((selector) => document.querySelector(selector)).find(visible) || null;
    const pageText = (document.body?.innerText || "").slice(0, 12000).toLowerCase();
    if (/verify you are human|checking your browser|cloudflare|安全验证|人机验证|验证码/.test(pageText)) return JSON.stringify({ status: "challenge", clicked: false });
    if (/usage limit|rate limit|too many requests|try again later|reached.*limit|已达到.*限制|请求过多|稍后再试/.test(pageText)) return JSON.stringify({ status: "limited", clicked: false });
    const composer = first([
      "textarea[data-composer-draft-react]",
      "#prompt-textarea",
      "textarea[placeholder*='Message']",
      "[contenteditable='true'][data-lexical-editor='true']",
      "[contenteditable='true'][role='textbox']"
    ]);
    if (!composer && /log in|sign up|登录|注册/.test(pageText)) return JSON.stringify({ status: "login", clicked: false });
    const send = first([
      "button[data-composer-submit]",
      "button[data-testid='send-button']",
      "button[aria-label='Send prompt']",
      "button[aria-label='Send message']"
    ]) || (composer.closest("form")
      ? Array.from(composer.closest("form").querySelectorAll("button[type='submit']")).find(visible) || null
      : null);
    if (!send || send.disabled || send.getAttribute("aria-disabled") === "true") {
      return JSON.stringify({ status: "not_sent", clicked: false, reason: "enabled-submit-control-not-found" });
    }
    send.click();
    return JSON.stringify({ status: "pending", clicked: true });
  } catch (error) {
    return JSON.stringify({ status: "error", clicked: false, reason: String(error).slice(0, 1024) });
  }
})()
"##;

const READ_SCRIPT: &str = OBSERVE_SCRIPT;

#[derive(Clone, Copy, Debug, PartialEq)]
struct Bounds {
    x: f64,
    y: f64,
    width: f64,
    height: f64,
}

impl Default for Bounds {
    fn default() -> Self {
        Self {
            x: 0.0,
            y: 0.0,
            width: 960.0,
            height: 720.0,
        }
    }
}

impl Bounds {
    fn validate(x: f64, y: f64, width: f64, height: f64) -> Result<Self, String> {
        let finite = [x, y, width, height].into_iter().all(f64::is_finite);
        if !finite || x.abs() > 32768.0 || y.abs() > 32768.0 {
            return Err("consultation bounds position is invalid".to_string());
        }
        if !(1.0..=8192.0).contains(&width) || !(1.0..=8192.0).contains(&height) {
            return Err("consultation bounds size must be between 1 and 8192".to_string());
        }
        Ok(Self {
            x,
            y,
            width,
            height,
        })
    }

    fn rect(self) -> Rect {
        Rect {
            position: tauri::Position::Logical(LogicalPosition::new(self.x, self.y)),
            size: tauri::Size::Logical(LogicalSize::new(self.width, self.height)),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Operation {
    Observe,
    Fill,
    Submit,
    Read,
    Takeover,
    Release,
    Status,
    Reload,
    Login,
}

impl Operation {
    fn parse(value: &str) -> Result<Self, String> {
        match value {
            "observe" => Ok(Self::Observe),
            "fill" => Ok(Self::Fill),
            "submit" => Ok(Self::Submit),
            "read" => Ok(Self::Read),
            "takeover" => Ok(Self::Takeover),
            "release" => Ok(Self::Release),
            "status" => Ok(Self::Status),
            "reload" => Ok(Self::Reload),
            "login" => Ok(Self::Login),
            _ => Err("unsupported consultation operation".to_string()),
        }
    }

    fn writes(self) -> bool {
        matches!(self, Self::Fill | Self::Submit)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum AttemptPhase {
    Filled,
    SubmitStarted,
    Pending,
    Completed,
    NotSent,
    Unknown,
}

impl AttemptPhase {
    fn status(self) -> &'static str {
        match self {
            Self::Filled => "filled",
            Self::SubmitStarted | Self::Pending => "pending",
            Self::Completed => "completed",
            Self::NotSent => "not_sent",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Clone, Debug)]
struct Attempt {
    id: String,
    phase: AttemptPhase,
    baseline_count: Option<usize>,
    baseline_text: String,
    baseline_text_known: bool,
    possibly_sent: bool,
}

#[derive(Debug, Serialize, Deserialize)]
struct AttemptJournal {
    version: u8,
    attempt_id: String,
    phase: AttemptPhase,
    possibly_sent: bool,
    #[serde(default)]
    baseline_count: Option<usize>,
}

#[derive(Debug)]
struct Machine {
    opened: bool,
    visible: bool,
    opening: bool,
    takeover: bool,
    operation_in_flight: bool,
    lease_owner: Option<String>,
    bounds: Bounds,
    attempt: Option<Attempt>,
}

impl Machine {
    fn new(recovered: Option<AttemptJournal>) -> Self {
        let attempt = recovered.map(|journal| Attempt {
            id: journal.attempt_id,
            phase: AttemptPhase::Unknown,
            baseline_count: journal.baseline_count,
            baseline_text: String::new(),
            baseline_text_known: false,
            possibly_sent: true,
        });
        Self {
            opened: false,
            visible: false,
            opening: false,
            takeover: false,
            operation_in_flight: false,
            lease_owner: None,
            bounds: Bounds::default(),
            attempt,
        }
    }

    fn begin_open(&mut self) -> Result<(), String> {
        if self.opening {
            return Err("consultation profile is already opening".to_string());
        }
        if let Some(owner) = &self.lease_owner {
            if owner != CONSULTATION_LABEL {
                return Err("consultation profile lease is held by another webview".to_string());
            }
        }
        self.opening = true;
        self.lease_owner = Some(CONSULTATION_LABEL.to_string());
        Ok(())
    }

    fn finish_open(&mut self, success: bool) {
        self.opening = false;
        self.opened = success;
        self.visible = success;
        if !success {
            self.lease_owner = None;
        }
    }

    fn begin_fill(&mut self, attempt_id: &str) -> Result<(), String> {
        self.ensure_operation_available(Operation::Fill)?;
        if let Some(attempt) = &self.attempt {
            let terminal = matches!(attempt.phase, AttemptPhase::Completed | AttemptPhase::NotSent);
            if attempt.id == attempt_id && attempt.phase != AttemptPhase::Filled {
                return Err("consultation attempt_id cannot be reused after submit".to_string());
            }
            if attempt.id != attempt_id && !terminal {
                return Err("another consultation attempt is still active".to_string());
            }
        }
        self.operation_in_flight = true;
        Ok(())
    }

    fn finish_fill(&mut self, attempt_id: String, dom: &DomResult) -> ConsultationResult {
        self.operation_in_flight = false;
        if dom.status == "filled" {
            self.attempt = Some(Attempt {
                id: attempt_id.clone(),
                phase: AttemptPhase::Filled,
                baseline_count: Some(dom.assistant_count),
                baseline_text: bounded(&dom.text, MAX_RESULT_BYTES),
                baseline_text_known: true,
                possibly_sent: false,
            });
            ConsultationResult::new("filled", "", Some(attempt_id), false, None)
        } else {
            ConsultationResult::new(
                &dom.status,
                &dom.text,
                self.attempt.as_ref().map(|attempt| attempt.id.clone()),
                false,
                dom.reason.clone(),
            )
        }
    }

    fn begin_submit(&mut self, attempt_id: &str) -> Result<SubmitDecision, String> {
        self.ensure_operation_available(Operation::Submit)?;
        let attempt = self
            .attempt
            .as_mut()
            .ok_or_else(|| "fill must succeed before submit".to_string())?;
        if attempt.id != attempt_id {
            return Err("submit attempt_id does not match the filled attempt".to_string());
        }
        if attempt.phase != AttemptPhase::Filled {
            return Ok(SubmitDecision::AlreadyAttempted(ConsultationResult::from_attempt(
                attempt,
                Some("submit was already attempted; use read with the same attempt_id".to_string()),
            )));
        }
        attempt.phase = AttemptPhase::SubmitStarted;
        attempt.possibly_sent = true;
        self.operation_in_flight = true;
        Ok(SubmitDecision::Dispatch)
    }

    fn finish_submit(&mut self, dom: Option<&DomResult>, failure: Option<&str>) -> ConsultationResult {
        self.operation_in_flight = false;
        let attempt = self.attempt.as_mut().expect("submit requires an attempt");
        if let Some(dom) = dom {
            if dom.clicked {
                attempt.phase = AttemptPhase::Pending;
                attempt.possibly_sent = true;
                return ConsultationResult::from_attempt(attempt, dom.reason.clone());
            }
            if matches!(dom.status.as_str(), "login" | "challenge" | "limited" | "not_sent") {
                attempt.phase = AttemptPhase::NotSent;
                attempt.possibly_sent = false;
                return ConsultationResult::new(
                    &dom.status,
                    "",
                    Some(attempt.id.clone()),
                    false,
                    dom.reason.clone(),
                );
            }
        }
        attempt.phase = AttemptPhase::Unknown;
        attempt.possibly_sent = true;
        ConsultationResult::from_attempt(
            attempt,
            Some(failure.unwrap_or("submit result was ambiguous").to_string()),
        )
    }

    fn begin_read(&mut self, attempt_id: &str) -> Result<(), String> {
        self.ensure_operation_available(Operation::Read)?;
        let attempt = self
            .attempt
            .as_ref()
            .ok_or_else(|| "no consultation attempt is available to read".to_string())?;
        if attempt.id != attempt_id {
            return Err("read must use the active attempt_id".to_string());
        }
        self.operation_in_flight = true;
        Ok(())
    }

    fn finish_read(&mut self, dom: &DomResult) -> ConsultationResult {
        self.operation_in_flight = false;
        let attempt = self.attempt.as_mut().expect("read requires an attempt");
        let text = bounded(&dom.text, MAX_RESULT_BYTES);
        let has_new_response = dom.status == "ready"
            && !text.is_empty()
            && attempt.baseline_count.is_some_and(|baseline_count| {
                dom.assistant_count > baseline_count
                    || (attempt.baseline_text_known && text != attempt.baseline_text)
            });
        if has_new_response {
            attempt.phase = AttemptPhase::Completed;
            attempt.possibly_sent = false;
            return ConsultationResult::new(
                "completed",
                &text,
                Some(attempt.id.clone()),
                false,
                None,
            );
        }
        if attempt.phase == AttemptPhase::Filled || attempt.phase == AttemptPhase::NotSent {
            return ConsultationResult::from_attempt(attempt, dom.reason.clone());
        }
        if dom.status == "pending" {
            attempt.phase = AttemptPhase::Pending;
        } else if matches!(dom.status.as_str(), "challenge" | "login" | "limited" | "error") {
            attempt.phase = AttemptPhase::Unknown;
        }
        ConsultationResult::new(
            attempt.phase.status(),
            "",
            Some(attempt.id.clone()),
            attempt.possibly_sent,
            dom.reason.clone().or_else(|| Some("no new assistant response observed".to_string())),
        )
    }

    fn fail_operation(&mut self) {
        self.operation_in_flight = false;
    }

    fn ensure_operation_available(&self, operation: Operation) -> Result<(), String> {
        if !self.opened {
            return Err("consultation webview is closed".to_string());
        }
        if self.operation_in_flight {
            return Err("another consultation operation is in progress".to_string());
        }
        if self.takeover && operation.writes() {
            return Err("user takeover is active; release it before automated writes".to_string());
        }
        Ok(())
    }

    fn enter_takeover(&mut self) -> Result<(), String> {
        if !self.opened {
            return Err("consultation webview is closed".to_string());
        }
        if self.operation_in_flight {
            return Err("another consultation operation is in progress".to_string());
        }
        self.takeover = true;
        if let Some(attempt) = self.attempt.as_mut() {
            if attempt.phase == AttemptPhase::Filled {
                attempt.phase = AttemptPhase::Unknown;
                attempt.possibly_sent = true;
            }
        }
        Ok(())
    }

    fn status_result(&self) -> ConsultationResult {
        if self.takeover {
            return ConsultationResult::new(
                "takeover",
                "",
                self.attempt.as_ref().map(|attempt| attempt.id.clone()),
                self.attempt.as_ref().is_some_and(|attempt| attempt.possibly_sent),
                Some("automated writes are paused until explicit release".to_string()),
            );
        }
        if let Some(attempt) = &self.attempt {
            return ConsultationResult::from_attempt(attempt, None);
        }
        let status = if self.opening {
            "opening"
        } else if !self.opened {
            "closed"
        } else if self.visible {
            "ready"
        } else {
            "hidden"
        };
        ConsultationResult::new(status, "", None, false, None)
    }
}

enum SubmitDecision {
    Dispatch,
    AlreadyAttempted(ConsultationResult),
}

#[derive(Clone)]
pub struct ConsultationState {
    inner: Arc<Mutex<Machine>>,
    navigation: Arc<Mutex<NavigationDiagnostics>>,
    profile_dir: PathBuf,
    profile_lock_path: PathBuf,
    profile_lease: Arc<Mutex<Option<File>>>,
    journal_path: PathBuf,
}

impl ConsultationState {
    pub fn new(data_dir: &Path) -> Result<Self, String> {
        let profile_dir = data_dir.join(PROFILE_DIRNAME);
        fs::create_dir_all(&profile_dir)
            .map_err(|error| format!("failed to create consultation profile: {error}"))?;
        let journal_path = profile_dir.join(JOURNAL_FILENAME);
        let profile_lock_path = profile_dir.join(PROFILE_LOCK_FILENAME);
        let recovered = read_journal(&journal_path);
        Ok(Self {
            inner: Arc::new(Mutex::new(Machine::new(recovered))),
            navigation: Arc::new(Mutex::new(NavigationDiagnostics::default())),
            profile_dir,
            profile_lock_path,
            profile_lease: Arc::new(Mutex::new(None)),
            journal_path,
        })
    }

    fn acquire_profile_lease(&self) -> Result<(), String> {
        let mut lease = self
            .profile_lease
            .lock()
            .map_err(|_| "consultation profile lease is poisoned".to_string())?;
        if lease.is_some() {
            return Ok(());
        }
        *lease = Some(open_profile_lease(&self.profile_lock_path)?);
        Ok(())
    }

    fn release_profile_lease(&self) -> Result<(), String> {
        let mut lease = self
            .profile_lease
            .lock()
            .map_err(|_| "consultation profile lease is poisoned".to_string())?;
        *lease = None;
        Ok(())
    }

    fn persist_active_attempt(&self) -> Result<(), String> {
        let journal = {
            let machine = self.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
            machine.attempt.as_ref().map(|attempt| AttemptJournal {
                version: 1,
                attempt_id: attempt.id.clone(),
                phase: attempt.phase,
                possibly_sent: attempt.possibly_sent,
                baseline_count: attempt.baseline_count,
            })
        };
        if let Some(journal) = journal {
            if !journal.possibly_sent {
                return Err("refusing to persist a consultation attempt that was not submitted".to_string());
            }
            let bytes = serde_json::to_vec(&journal)
                .map_err(|error| format!("failed to encode consultation attempt journal: {error}"))?;
            let mut file = match OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(&self.journal_path)
            {
                Ok(file) => file,
                Err(error) if error.kind() == ErrorKind::AlreadyExists => {
                    let existing = read_journal(&self.journal_path).ok_or_else(|| {
                        "existing consultation attempt journal is invalid".to_string()
                    })?;
                    if existing.attempt_id == journal.attempt_id && existing.possibly_sent {
                        return Ok(());
                    }
                    return Err("another consultation attempt journal already exists".to_string());
                }
                Err(error) => {
                    return Err(format!(
                        "failed to persist consultation attempt journal: {error}"
                    ));
                }
            };
            file.write_all(&bytes)
                .and_then(|_| file.sync_all())
                .map_err(|error| format!("failed to persist consultation attempt journal: {error}"))?;
        }
        Ok(())
    }

    fn clear_journal(&self) -> Result<(), String> {
        match fs::remove_file(&self.journal_path) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == ErrorKind::NotFound => Ok(()),
            Err(error) => Err(format!("failed to clear consultation attempt journal: {error}")),
        }
    }
}

#[cfg(windows)]
fn open_profile_lease(path: &Path) -> Result<File, String> {
    use std::os::windows::fs::OpenOptionsExt;

    OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .share_mode(0)
        .open(path)
        .map_err(|error| format!("consultation profile is already leased: {error}"))
}

#[cfg(not(windows))]
fn open_profile_lease(path: &Path) -> Result<File, String> {
    OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .open(path)
        .map_err(|error| format!("failed to open consultation profile lease: {error}"))
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct ConsultationResult {
    status: String,
    text: String,
    attempt_id: Option<String>,
    possibly_sent: bool,
    reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    navigation: Option<NavigationDiagnostics>,
}

impl ConsultationResult {
    fn new(
        status: &str,
        text: &str,
        attempt_id: Option<String>,
        possibly_sent: bool,
        reason: Option<String>,
    ) -> Self {
        Self {
            status: status.to_string(),
            text: bounded(text, MAX_RESULT_BYTES),
            attempt_id,
            possibly_sent,
            reason: reason.map(|value| bounded(&value, MAX_REASON_BYTES)),
            navigation: None,
        }
    }

    fn from_attempt(attempt: &Attempt, reason: Option<String>) -> Self {
        Self::new(
            attempt.phase.status(),
            "",
            Some(attempt.id.clone()),
            attempt.possibly_sent,
            reason,
        )
    }
}

#[derive(Clone, Debug, Default, Serialize, PartialEq, Eq)]
struct NavigationDiagnostics {
    events: Vec<NavigationEvent>,
    failure: Option<String>,
    manual_login_active: bool,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
struct NavigationEvent {
    kind: String,
    origin: String,
    error_code: Option<i32>,
}

impl NavigationDiagnostics {
    fn allow_navigation(&mut self, url: &tauri::Url) -> bool {
        let allowed = validate_automation_url(url) || is_exact_https_host(url, LOGIN_HOST)
            || (self.manual_login_active && is_google_login_url(url));
        if allowed && is_exact_https_host(url, LOGIN_HOST) {
            self.manual_login_active = true;
        } else if allowed && validate_automation_url(url) {
            self.manual_login_active = false;
        }
        self.record(if allowed { "navigation-started" } else { "navigation-blocked" }, Some(url), None);
        allowed
    }

    fn record(&mut self, kind: &str, url: Option<&tauri::Url>, error_code: Option<i32>) {
        let origin = url.filter(|url| url.scheme() == "https")
            .map(|url| bounded(&url.origin().ascii_serialization(), 200))
            .unwrap_or_else(|| "non-https-or-unavailable".to_string());
        self.failure = match kind {
            "navigation-blocked" => Some(format!("已阻止未支持的登录跳转（{origin}）；未开放该站点权限。")),
            "popup-blocked" => Some(format!("该登录弹窗暂不支持（{origin}）；未打开外部窗口。")),
            "load-failed" if error_code == Some(14) && self.failure.is_some() => self.failure.clone(),
            "load-failed" if error_code == Some(14) => Some("网页导航被取消；可返回登录首页，不会重发咨询。".to_string()),
            "load-failed" => Some(format!("网页加载失败（WebView2错误码{}）；可检查网络后返回登录首页。", error_code.unwrap_or(-1))),
            "popup-navigation-failed" => Some("无法在当前标签打开登录页，请返回登录首页重试。".to_string()),
            "navigation-started" => None,
            _ => self.failure.clone(),
        };
        if self.events.len() == 16 {
            self.events.remove(0);
        }
        self.events.push(NavigationEvent { kind: kind.to_string(), origin, error_code });
    }
}

fn record_navigation(state: &ConsultationState, kind: &str, url: Option<&tauri::Url>, code: Option<i32>) {
    if let Ok(mut navigation) = state.navigation.lock() {
        navigation.record(kind, url, code);
    }
}

fn with_navigation(mut result: ConsultationResult, state: &ConsultationState) -> ConsultationResult {
    if let Ok(navigation) = state.navigation.lock() {
        if let Some(failure) = &navigation.failure {
            if !matches!(result.status.as_str(), "pending" | "completed" | "unknown" | "takeover") {
                result.status = "unavailable".to_string();
                result.reason = Some(failure.clone());
            }
        }
        result.navigation = Some(navigation.clone());
    }
    result
}

fn can_restart_navigation(machine: &Machine) -> bool {
    machine.opened && !machine.operation_in_flight && !machine.attempt.as_ref().is_some_and(|attempt| {
        matches!(attempt.phase, AttemptPhase::Filled | AttemptPhase::SubmitStarted | AttemptPhase::Pending | AttemptPhase::Unknown)
    })
}

#[cfg(windows)]
fn watch_navigation(webview: &Webview, state: ConsultationState) -> Result<(), String> {
    use webview2_com::{NavigationCompletedEventHandler, Microsoft::Web::WebView2::Win32::COREWEBVIEW2_WEB_ERROR_STATUS};
    use windows::core::BOOL;
    webview.with_webview(move |native| unsafe {
        let Ok(core) = native.controller().CoreWebView2() else { return };
        let mut token = 0;
        let _ = core.add_NavigationCompleted(&NavigationCompletedEventHandler::create(Box::new(move |_, args| {
            if let Some(args) = args {
                let mut success = BOOL(0);
                let mut code = COREWEBVIEW2_WEB_ERROR_STATUS(0);
                if args.IsSuccess(&mut success).is_ok() && !success.as_bool() {
                    let _ = args.WebErrorStatus(&mut code);
                    record_navigation(&state, "load-failed", None, Some(code.0));
                }
            }
            Ok(())
        })), &mut token);
    }).map_err(|_| "failed to install consultation navigation diagnostics".to_string())
}

#[cfg(not(windows))]
fn watch_navigation(_webview: &Webview, _state: ConsultationState) -> Result<(), String> {
    Ok(())
}

#[derive(Debug, Default, Deserialize)]
struct DomResult {
    #[serde(default)]
    status: String,
    #[serde(default)]
    text: String,
    #[serde(default)]
    reason: Option<String>,
    #[serde(default)]
    assistant_count: usize,
    #[serde(default)]
    clicked: bool,
}

pub fn validate_main_caller_parts(
    webview_label: &str,
    window_label: &str,
    url: &tauri::Url,
) -> Result<(), String> {
    if webview_label != "main" || window_label != "main" {
        return Err("command is restricted to the main webview".to_string());
    }
    let trusted = matches!(
        (url.scheme(), url.host_str(), url.port()),
        ("http", Some("127.0.0.1"), Some(8771))
            | ("http", Some("tauri.localhost"), None)
    );
    if !trusted || !url.username().is_empty() || url.password().is_some() {
        return Err("command caller origin is not trusted".to_string());
    }
    Ok(())
}

pub fn authorize_main_caller(webview: &Webview) -> Result<(), String> {
    let url = webview
        .url()
        .map_err(|error| format!("failed to inspect command caller URL: {error}"))?;
    validate_main_caller_parts(webview.label(), webview.window().label(), &url)
}

fn is_exact_https_host(url: &tauri::Url, host: &str) -> bool {
    url.scheme() == "https"
        && url.host_str() == Some(host)
        && url.port().is_none()
        && url.username().is_empty()
        && url.password().is_none()
}

fn validate_automation_url(url: &tauri::Url) -> bool {
    is_exact_https_host(url, "chatgpt.com")
}

fn validate_consultation_navigation(url: &tauri::Url) -> bool {
    validate_automation_url(url) || is_exact_https_host(url, LOGIN_HOST) || is_google_login_url(url)
}

fn is_google_login_url(url: &tauri::Url) -> bool {
    is_exact_https_host(url, "accounts.google.com") && (
        ["/o/oauth2/", "/v3/signin/", "/signin/", "/gsi/"].iter().any(|prefix| url.path().starts_with(prefix))
        || ["/ServiceLogin", "/AccountChooser", "/InteractiveLogin", "/CheckCookie", "/signin"].contains(&url.path())
    )
}

fn validate_attempt_id(value: Option<String>, required: bool) -> Result<Option<String>, String> {
    let Some(value) = value else {
        return if required {
            Err("attempt_id is required for this operation".to_string())
        } else {
            Ok(None)
        };
    };
    let valid = !value.is_empty()
        && value.len() <= 128
        && value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || "-_.:".contains(character));
    if valid {
        Ok(Some(value))
    } else {
        Err("attempt_id must be 1-128 ASCII identifier characters".to_string())
    }
}

fn validate_action_arguments(
    operation: Operation,
    attempt_id: Option<String>,
    text: Option<String>,
) -> Result<(Option<String>, Option<String>), String> {
    match operation {
        Operation::Fill => {
            let attempt_id = validate_attempt_id(attempt_id, true)?;
            let text = text.ok_or_else(|| "text is required for fill".to_string())?;
            if text.is_empty() || text.len() > MAX_INPUT_BYTES {
                return Err(format!("fill text must be 1-{MAX_INPUT_BYTES} UTF-8 bytes"));
            }
            Ok((attempt_id, Some(text)))
        }
        Operation::Submit | Operation::Read => {
            if text.is_some() {
                return Err("text is only accepted by fill".to_string());
            }
            Ok((validate_attempt_id(attempt_id, true)?, None))
        }
        _ => {
            if attempt_id.is_some() || text.is_some() {
                return Err("this operation does not accept attempt_id or text".to_string());
            }
            Ok((None, None))
        }
    }
}

fn bounded(value: &str, max_bytes: usize) -> String {
    if value.len() <= max_bytes {
        return value.to_string();
    }
    let mut end = max_bytes;
    while !value.is_char_boundary(end) {
        end -= 1;
    }
    value[..end].to_string()
}

fn read_journal(path: &Path) -> Option<AttemptJournal> {
    let bytes = fs::read(path).ok()?;
    if bytes.len() > 4096 {
        return None;
    }
    let journal: AttemptJournal = serde_json::from_slice(&bytes).ok()?;
    if journal.version != 1
        || validate_attempt_id(Some(journal.attempt_id.clone()), true).is_err()
        || journal.baseline_count.is_some_and(|count| count > 100_000)
    {
        return None;
    }
    if !journal.possibly_sent
        || !matches!(
            journal.phase,
            AttemptPhase::SubmitStarted | AttemptPhase::Pending | AttemptPhase::Unknown
        )
    {
        return None;
    }
    Some(journal)
}

fn decode_dom_result(raw: &str) -> Result<DomResult, String> {
    if raw.len() > MAX_EVAL_BYTES {
        return Err("consultation evaluation result exceeded its size limit".to_string());
    }
    let value: serde_json::Value = serde_json::from_str(raw)
        .map_err(|error| format!("consultation evaluation returned invalid JSON: {error}"))?;
    let value = match value {
        serde_json::Value::String(inner) => serde_json::from_str(&inner)
            .map_err(|error| format!("consultation evaluation returned invalid payload: {error}"))?,
        other => other,
    };
    let mut result: DomResult = serde_json::from_value(value)
        .map_err(|error| format!("consultation evaluation returned invalid shape: {error}"))?;
    const STATUSES: &[&str] = &[
        "challenge",
        "limited",
        "login",
        "pending",
        "ready",
        "unavailable",
        "filled",
        "not_sent",
        "error",
    ];
    if !STATUSES.contains(&result.status.as_str()) {
        return Err("consultation evaluation returned an unknown status".to_string());
    }
    if result.assistant_count > 100_000 {
        return Err("consultation evaluation returned an invalid response count".to_string());
    }
    result.text = bounded(&result.text, MAX_RESULT_BYTES);
    result.reason = result.reason.map(|reason| bounded(&reason, MAX_REASON_BYTES));
    Ok(result)
}

#[cfg(windows)]
async fn evaluate_raw(webview: &Webview, script: String) -> Result<String, String> {
    use webview2_com::{
        ExecuteScriptCompletedHandler, Microsoft::Web::WebView2::Win32::ICoreWebView2,
    };
    use windows::core::HSTRING;

    let (sender, receiver) = tokio::sync::oneshot::channel::<Result<String, String>>();
    let sender = Arc::new(Mutex::new(Some(sender)));
    let dispatch_sender = sender.clone();
    let schedule_result = webview.with_webview(move |platform_webview| {
        let result = (|| -> Result<(), String> {
            let controller = platform_webview.controller();
            let core: ICoreWebView2 = unsafe { controller.CoreWebView2() }
                .map_err(|error| format!("failed to access WebView2: {error}"))?;
            let callback_sender = dispatch_sender.clone();
            let handler = ExecuteScriptCompletedHandler::create(Box::new(move |code, result| {
                let outcome = if code.is_ok() {
                    Ok(result)
                } else {
                    Err(format!("WebView2 script failed with HRESULT {code:?}"))
                };
                if let Ok(mut sender) = callback_sender.lock() {
                    if let Some(sender) = sender.take() {
                        let _ = sender.send(outcome);
                    }
                }
                Ok(())
            }));
            unsafe { core.ExecuteScript(&HSTRING::from(script), &handler) }
                .map_err(|error| format!("failed to dispatch WebView2 script: {error}"))?;
            Ok(())
        })();
        if let Err(error) = result {
            if let Ok(mut sender) = dispatch_sender.lock() {
                if let Some(sender) = sender.take() {
                    let _ = sender.send(Err(error));
                }
            }
        }
    });
    if let Err(error) = schedule_result {
        return Err(format!("failed to schedule WebView2 evaluation: {error}"));
    }
    let raw = tokio::time::timeout(EVAL_TIMEOUT, receiver)
        .await
        .map_err(|_| "consultation evaluation timed out".to_string())?
        .map_err(|_| "consultation evaluation callback was dropped".to_string())??;
    if raw.len() > MAX_EVAL_BYTES {
        return Err("consultation evaluation result exceeded its size limit".to_string());
    }
    Ok(raw)
}

#[cfg(not(windows))]
async fn evaluate_raw(_webview: &Webview, _script: String) -> Result<String, String> {
    Err("native consultation transport currently requires Windows WebView2".to_string())
}

async fn evaluate(webview: &Webview, script: String) -> Result<DomResult, String> {
    decode_dom_result(&evaluate_raw(webview, script).await?)
}

fn get_child(app: &AppHandle) -> Result<Webview, String> {
    app.get_webview(CONSULTATION_LABEL)
        .ok_or_else(|| "consultation webview is closed".to_string())
}

fn child_for_action(app: &AppHandle) -> Result<Webview, ConsultationResult> {
    let child = app.get_webview(CONSULTATION_LABEL).ok_or_else(|| {
        ConsultationResult::new("closed", "", None, false, Some("consultation webview is closed".to_string()))
    })?;
    let url = child.url().map_err(|error| {
        ConsultationResult::new(
            "unavailable",
            "",
            None,
            false,
            Some(format!("failed to inspect consultation URL: {error}")),
        )
    })?;
    if !validate_automation_url(&url) {
        let status = if url.as_str() == "about:blank" { "loading" } else if is_exact_https_host(&url, LOGIN_HOST) || is_google_login_url(&url) { "login" } else { "blocked_origin" };
        return Err(ConsultationResult::new(
            status,
            "",
            None,
            false,
            Some(format!(
                "请在内置页手动完成登录；自动操作仅限{CHATGPT_ORIGIN}，不会读取OpenAI或Google登录页的密码、验证码。"
            )),
        ));
    }
    Ok(child)
}

#[cfg(debug_assertions)]
#[derive(Serialize)]
pub struct ConsultationSmokeResult {
    label: String,
    origin: String,
    x: i32,
    y: i32,
    width: u32,
    height: u32,
    scale_factor: f64,
    remote_ipc: String,
    remote_core_fetch: String,
}

#[cfg(debug_assertions)]
#[derive(Deserialize)]
struct ConsultationSmokeMarkers {
    remote_ipc: String,
    remote_core_fetch: String,
}

#[cfg(debug_assertions)]
#[tauri::command]
pub async fn consultation_smoke_probe(
    caller: Webview,
    app: AppHandle,
    core: State<'_, crate::CoreProcess>,
) -> Result<ConsultationSmokeResult, String> {
    authorize_main_caller(&caller)?;
    if core.inner.host != "127.0.0.1" && core.inner.host != "localhost" {
        return Err("consultation smoke requires a loopback Core host".to_string());
    }
    let child = get_child(&app)?;
    let url = child
        .url()
        .map_err(|error| format!("failed to inspect consultation smoke URL: {error}"))?;
    let webview2_error_page = url.scheme() == "chrome-error"
        && url.host_str() == Some("chromewebdata")
        && url.username().is_empty()
        && url.password().is_none();
    if !validate_consultation_navigation(&url) && !webview2_error_page {
        return Err("consultation smoke child is outside the expected origins".to_string());
    }
    let position = child
        .position()
        .map_err(|error| format!("failed to inspect consultation position: {error}"))?;
    let size = child
        .size()
        .map_err(|error| format!("failed to inspect consultation size: {error}"))?;
    let scale_factor = caller
        .window()
        .scale_factor()
        .map_err(|error| format!("failed to inspect consultation scale factor: {error}"))?;
    if !validate_automation_url(&url) && !webview2_error_page {
        return Ok(ConsultationSmokeResult {
            label: child.label().to_string(), origin: url.origin().ascii_serialization(),
            x: position.x, y: position.y, width: size.width, height: size.height, scale_factor,
            remote_ipc: "not-run-on-login".to_string(), remote_core_fetch: "not-run-on-login".to_string(),
        });
    }
    let core_url = serde_json::to_string(&format!(
        "http://{}:{}",
        core.inner.host, core.inner.port
    ))
    .map_err(|error| format!("failed to encode consultation smoke Core URL: {error}"))?;
    let start_script = format!(
        r##"
((coreUrl) => {{
  const root = document.documentElement;
  if (!root) return "no-document";
  root.dataset.sumikaRemoteIpc = "pending";
  root.dataset.sumikaRemoteCoreFetch = "pending";
  const invoke = window.__TAURI__?.core?.invoke;
  if (!invoke) {{
    root.dataset.sumikaRemoteIpc = "api-absent";
  }} else {{
    Promise.resolve(invoke("get_display_mode")).then(
      () => {{ root.dataset.sumikaRemoteIpc = "resolved"; }},
      () => {{ root.dataset.sumikaRemoteIpc = "rejected"; }}
    );
  }}
  fetch(`${{coreUrl}}/api/health`, {{
    method: "GET",
    mode: "cors",
    credentials: "omit",
    redirect: "error"
  }}).then(
    () => {{ root.dataset.sumikaRemoteCoreFetch = "resolved"; }},
    () => {{ root.dataset.sumikaRemoteCoreFetch = "rejected"; }}
  );
  return "scheduled";
}})({core_url})
"##
    );
    evaluate_raw(&child, start_script).await?;

    let mut markers = None;
    for _ in 0..25 {
        tokio::time::sleep(Duration::from_millis(100)).await;
        let raw = evaluate_raw(
            &child,
            r##"JSON.stringify({
  remote_ipc: document.documentElement?.dataset.sumikaRemoteIpc || "missing",
  remote_core_fetch: document.documentElement?.dataset.sumikaRemoteCoreFetch || "missing"
})"##
                .to_string(),
        )
        .await?;
        let encoded: String = serde_json::from_str(&raw)
            .map_err(|error| format!("failed to decode consultation smoke markers: {error}"))?;
        let current: ConsultationSmokeMarkers = serde_json::from_str(&encoded)
            .map_err(|error| format!("failed to parse consultation smoke markers: {error}"))?;
        if current.remote_ipc != "pending" && current.remote_core_fetch != "pending" {
            markers = Some(current);
            break;
        }
    }
    let markers = markers.ok_or_else(|| "consultation smoke probes timed out".to_string())?;
    Ok(ConsultationSmokeResult {
        label: child.label().to_string(),
        origin: url.origin().ascii_serialization(),
        x: position.x,
        y: position.y,
        width: size.width,
        height: size.height,
        scale_factor,
        remote_ipc: markers.remote_ipc,
        remote_core_fetch: markers.remote_core_fetch,
    })
}

#[tauri::command]
pub async fn consultation_open(
    caller: Webview,
    app: AppHandle,
    state: State<'_, ConsultationState>,
) -> Result<ConsultationResult, String> {
    authorize_main_caller(&caller)?;
    if let Some(existing) = app.get_webview(CONSULTATION_LABEL) {
        state.acquire_profile_lease()?;
        existing.show().map_err(|error| format!("failed to show consultation webview: {error}"))?;
        let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
        machine.opened = true;
        machine.visible = true;
        machine.lease_owner = Some(CONSULTATION_LABEL.to_string());
        return Ok(machine.status_result());
    }
    let bounds = {
        let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
        machine.begin_open()?;
        machine.bounds
    };
    if let Err(error) = state.acquire_profile_lease() {
        let mut machine = state
            .inner
            .lock()
            .map_err(|_| "consultation state is poisoned".to_string())?;
        machine.finish_open(false);
        return Err(error);
    }
    let url: tauri::Url = CHATGPT_URL.parse().map_err(|error| format!("invalid fixed ChatGPT URL: {error}"))?;
    let navigation_state = state.inner().clone();
    let load_state = state.inner().clone();
    let popup_state = state.inner().clone();
    let popup_app = app.clone();
    let builder = tauri::webview::WebviewBuilder::new(
        CONSULTATION_LABEL,
        WebviewUrl::External(url),
    )
    .data_directory(state.profile_dir.clone())
    .on_navigation(move |url| {
        navigation_state.navigation.lock().map(|mut navigation| navigation.allow_navigation(url)).unwrap_or(false)
    })
    .on_page_load(move |_, payload| {
        if matches!(payload.event(), tauri::webview::PageLoadEvent::Finished) {
            record_navigation(&load_state, "loaded", Some(payload.url()), None);
        }
    })
    .on_new_window(move |url, _| {
        let child = popup_app.get_webview(CONSULTATION_LABEL);
        let login_destination = is_exact_https_host(&url, LOGIN_HOST) || (is_google_login_url(&url)
            && popup_state.navigation.lock().is_ok_and(|navigation| navigation.manual_login_active));
        let allowed = login_destination
            && child.as_ref().and_then(|child| child.url().ok()).is_some_and(|source| validate_consultation_navigation(&source))
            && popup_state.inner.lock().map(|machine| can_restart_navigation(&machine)).unwrap_or(false);
        record_navigation(&popup_state, if allowed { "popup-in-current-tab" } else { "popup-blocked" }, Some(&url), None);
        if allowed {
            if child.is_some_and(|child| child.navigate(url).is_err()) {
                record_navigation(&popup_state, "popup-navigation-failed", None, None);
            }
        }
        tauri::webview::NewWindowResponse::Deny
    });
    let result = caller.window().add_child(
        builder,
        LogicalPosition::new(bounds.x, bounds.y),
        LogicalSize::new(bounds.width, bounds.height),
    );
    let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
    machine.finish_open(result.is_ok());
    if let Err(error) = result {
        drop(machine);
        state.release_profile_lease()?;
        return Err(format!("failed to open consultation webview: {error}"));
    }
    drop(machine);
    watch_navigation(&get_child(&app)?, state.inner().clone())?;
    let machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
    Ok(machine.status_result())
}

#[tauri::command]
pub async fn consultation_set_bounds(
    caller: Webview,
    app: AppHandle,
    state: State<'_, ConsultationState>,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    authorize_main_caller(&caller)?;
    let bounds = Bounds::validate(x, y, width, height)?;
    let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
    if let Some(child) = app.get_webview(CONSULTATION_LABEL) {
        child
            .set_bounds(bounds.rect())
            .map_err(|error| format!("failed to set consultation bounds: {error}"))?;
    }
    machine.bounds = bounds;
    Ok(())
}

#[tauri::command]
pub async fn consultation_hide(
    caller: Webview,
    app: AppHandle,
    state: State<'_, ConsultationState>,
) -> Result<(), String> {
    authorize_main_caller(&caller)?;
    let child = get_child(&app)?;
    child.hide().map_err(|error| format!("failed to hide consultation webview: {error}"))?;
    let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
    machine.visible = false;
    Ok(())
}

#[tauri::command]
pub async fn consultation_close(
    caller: Webview,
    app: AppHandle,
    state: State<'_, ConsultationState>,
) -> Result<(), String> {
    authorize_main_caller(&caller)?;
    let mut machine = state
        .inner
        .lock()
        .map_err(|_| "consultation state is poisoned".to_string())?;
    if machine.opening || machine.operation_in_flight {
        return Err("consultation operation is in progress".to_string());
    }
    if let Some(child) = app.get_webview(CONSULTATION_LABEL) {
        child.close().map_err(|error| format!("failed to close consultation webview: {error}"))?;
    }
    machine.opened = false;
    machine.visible = false;
    machine.takeover = false;
    machine.lease_owner = None;
    drop(machine);
    state.release_profile_lease()?;
    Ok(())
}

#[tauri::command]
pub async fn consultation_action(
    caller: Webview,
    app: AppHandle,
    state: State<'_, ConsultationState>,
    operation: String,
    attempt_id: Option<String>,
    text: Option<String>,
) -> Result<ConsultationResult, String> {
    authorize_main_caller(&caller)?;
    let operation = Operation::parse(&operation)?;
    let (attempt_id, text) = validate_action_arguments(operation, attempt_id, text)?;

    match operation {
        Operation::Status => {
            let machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
            return Ok(with_navigation(machine.status_result(), &state));
        }
        Operation::Reload | Operation::Login => {
            let machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
            if !machine.visible || !can_restart_navigation(&machine) {
                return Err("cannot reload while hidden, busy, or an unresolved attempt exists".to_string());
            }
            drop(machine);
            let url = if operation == Operation::Login { CHATGPT_LOGIN_URL } else { CHATGPT_URL };
            get_child(&app)?.navigate(url.parse().expect("fixed ChatGPT URL"))
                .map_err(|_| "failed to return to the consultation homepage".to_string())?;
            return Ok(ConsultationResult::new("loading", "", None, false, None));
        }
        Operation::Takeover => {
            let child = get_child(&app)?;
            {
                let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
                machine.enter_takeover()?;
            }
            state.persist_active_attempt()?;
            child.show().map_err(|error| format!("failed to show consultation webview: {error}"))?;
            child.set_focus().map_err(|error| format!("failed to focus consultation webview: {error}"))?;
            let machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
            return Ok(machine.status_result());
        }
        Operation::Release => {
            let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
            machine.takeover = false;
            return Ok(machine.status_result());
        }
        _ => {}
    }

    let child = match child_for_action(&app) {
        Ok(child) => child,
        Err(mut result) => {
            let machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
            result.attempt_id = machine.attempt.as_ref().map(|attempt| attempt.id.clone());
            result.possibly_sent = machine.attempt.as_ref().is_some_and(|attempt| attempt.possibly_sent);
            return Ok(with_navigation(result, &state));
        }
    };

    match operation {
        Operation::Observe => {
            {
                let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
                machine.ensure_operation_available(Operation::Observe)?;
                machine.operation_in_flight = true;
            }
            let evaluated = evaluate(&child, OBSERVE_SCRIPT.to_string()).await;
            let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
            machine.fail_operation();
            match evaluated {
                Ok(dom) => Ok(with_navigation(ConsultationResult::new(
                    &dom.status,
                    &dom.text,
                    machine.attempt.as_ref().map(|attempt| attempt.id.clone()),
                    machine.attempt.as_ref().is_some_and(|attempt| attempt.possibly_sent),
                    dom.reason,
                ), &state)),
                Err(error) => Ok(ConsultationResult::new(
                    "unavailable",
                    "",
                    machine.attempt.as_ref().map(|attempt| attempt.id.clone()),
                    machine.attempt.as_ref().is_some_and(|attempt| attempt.possibly_sent),
                    Some(error),
                )),
            }
        }
        Operation::Fill => {
            let attempt_id = attempt_id.expect("validated fill attempt_id");
            let text = text.expect("validated fill text");
            {
                let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
                machine.begin_fill(&attempt_id)?;
            }
            let encoded = serde_json::to_string(&text)
                .map_err(|error| format!("failed to encode fill text: {error}"))?;
            let script = FILL_SCRIPT.replace("__SUMIKA_TEXT__", &encoded);
            let evaluated = evaluate(&child, script).await;
            let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
            match evaluated {
                Ok(dom) => Ok(machine.finish_fill(attempt_id, &dom)),
                Err(error) => {
                    machine.fail_operation();
                    Ok(ConsultationResult::new("unavailable", "", Some(attempt_id), false, Some(error)))
                }
            }
        }
        Operation::Submit => {
            let attempt_id = attempt_id.expect("validated submit attempt_id");
            let decision = {
                let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
                machine.begin_submit(&attempt_id)?
            };
            if let SubmitDecision::AlreadyAttempted(result) = decision {
                return Ok(result);
            }
            if let Err(error) = state.persist_active_attempt() {
                let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
                if let Some(attempt) = machine.attempt.as_mut() {
                    attempt.phase = AttemptPhase::Filled;
                    attempt.possibly_sent = false;
                }
                machine.fail_operation();
                return Err(error);
            }
            let evaluated = evaluate(&child, SUBMIT_SCRIPT.to_string()).await;
            let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
            let result = match evaluated {
                Ok(dom) => machine.finish_submit(Some(&dom), None),
                Err(error) => machine.finish_submit(None, Some(&error)),
            };
            let keep_journal = machine
                .attempt
                .as_ref()
                .is_some_and(|attempt| attempt.possibly_sent);
            drop(machine);
            if !keep_journal {
                state.clear_journal()?;
            }
            Ok(result)
        }
        Operation::Read => {
            let attempt_id = attempt_id.expect("validated read attempt_id");
            {
                let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
                machine.begin_read(&attempt_id)?;
            }
            let evaluated = evaluate(&child, READ_SCRIPT.to_string()).await;
            let mut machine = state.inner.lock().map_err(|_| "consultation state is poisoned".to_string())?;
            let result = match evaluated {
                Ok(dom) => machine.finish_read(&dom),
                Err(error) => {
                    machine.fail_operation();
                    let attempt = machine.attempt.as_ref().expect("read requires an attempt");
                    ConsultationResult::from_attempt(attempt, Some(error))
                }
            };
            let possibly_sent = machine
                .attempt
                .as_ref()
                .is_some_and(|attempt| attempt.possibly_sent);
            drop(machine);
            if !possibly_sent {
                state.clear_journal()?;
            }
            Ok(result)
        }
        Operation::Takeover | Operation::Release | Operation::Status | Operation::Reload | Operation::Login => unreachable!(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dom(status: &str) -> DomResult {
        DomResult {
            status: status.to_string(),
            ..DomResult::default()
        }
    }

    fn opened_machine() -> Machine {
        let mut machine = Machine::new(None);
        machine.begin_open().unwrap();
        machine.finish_open(true);
        machine
    }

    #[test]
    fn caller_validation_requires_main_webview_and_trusted_origin() {
        let local: tauri::Url = "http://127.0.0.1:8771/app".parse().unwrap();
        let production: tauri::Url = "http://tauri.localhost/".parse().unwrap();
        let remote: tauri::Url = CHATGPT_URL.parse().unwrap();
        assert!(validate_main_caller_parts("main", "main", &local).is_ok());
        assert!(validate_main_caller_parts("main", "main", &production).is_ok());
        assert!(validate_main_caller_parts(CONSULTATION_LABEL, "main", &remote).is_err());
        assert!(validate_main_caller_parts("main", "main", &remote).is_err());
        assert!(validate_main_caller_parts("main", "portal-chatgpt", &production).is_err());
        assert!(validate_main_caller_parts(
            "main",
            "main",
            &"http://localhost:8771/".parse().unwrap()
        )
        .is_err());
        assert!(validate_main_caller_parts(
            "main",
            "main",
            &"http://127.0.0.1:5173/".parse().unwrap()
        )
        .is_err());
        assert!(validate_main_caller_parts(
            "main",
            "main",
            &"http://127.0.0.1:49152/".parse().unwrap()
        )
        .is_err());
        assert!(validate_main_caller_parts(
            "main",
            "main",
            &"https://tauri.localhost/".parse().unwrap()
        )
        .is_err());
    }

    #[test]
    fn operation_and_arguments_are_bounded_and_closed() {
        assert_eq!(Operation::parse("observe").unwrap(), Operation::Observe);
        assert!(Operation::parse("eval").is_err());
        assert!(validate_action_arguments(Operation::Fill, Some("attempt-1".into()), Some("hello".into())).is_ok());
        assert!(validate_action_arguments(Operation::Fill, Some("../bad".into()), Some("hello".into())).is_err());
        assert!(validate_action_arguments(Operation::Submit, Some("attempt-1".into()), Some("extra".into())).is_err());
        assert!(validate_action_arguments(Operation::Status, Some("attempt-1".into()), None).is_err());
    }

    #[test]
    fn state_machine_enforces_fill_submit_and_same_attempt_recovery() {
        let mut machine = opened_machine();
        machine.begin_fill("attempt-1").unwrap();
        let mut filled = dom("filled");
        filled.assistant_count = 2;
        filled.text = "old".to_string();
        assert_eq!(machine.finish_fill("attempt-1".to_string(), &filled).status, "filled");
        assert!(matches!(machine.begin_submit("attempt-1").unwrap(), SubmitDecision::Dispatch));
        let mut submitted = dom("pending");
        submitted.clicked = true;
        let result = machine.finish_submit(Some(&submitted), None);
        assert_eq!(result.status, "pending");
        assert!(result.possibly_sent);
        assert!(matches!(machine.begin_submit("attempt-1").unwrap(), SubmitDecision::AlreadyAttempted(_)));
        assert!(machine.begin_read("attempt-2").is_err());
        machine.begin_read("attempt-1").unwrap();
        let mut read = dom("ready");
        read.assistant_count = 3;
        read.text = "new answer".to_string();
        let result = machine.finish_read(&read);
        assert_eq!(result.status, "completed");
        assert_eq!(result.text, "new answer");
        assert!(!result.possibly_sent);
    }

    #[test]
    fn read_does_not_return_a_partial_stream() {
        let mut machine = opened_machine();
        machine.begin_fill("attempt-streaming").unwrap();
        machine.finish_fill("attempt-streaming".to_string(), &dom("filled"));
        assert!(matches!(
            machine.begin_submit("attempt-streaming").unwrap(),
            SubmitDecision::Dispatch
        ));
        let mut submitted = dom("pending");
        submitted.clicked = true;
        machine.finish_submit(Some(&submitted), None);
        machine.begin_read("attempt-streaming").unwrap();
        let mut partial = dom("pending");
        partial.assistant_count = 1;
        partial.text = "partial response".to_string();
        let result = machine.finish_read(&partial);
        assert_eq!(result.status, "pending");
        assert!(result.text.is_empty());
        assert!(result.possibly_sent);
    }

    #[test]
    fn ambiguous_submit_is_never_retried() {
        let mut machine = opened_machine();
        machine.begin_fill("attempt-ambiguous").unwrap();
        machine.finish_fill("attempt-ambiguous".to_string(), &dom("filled"));
        assert!(matches!(machine.begin_submit("attempt-ambiguous").unwrap(), SubmitDecision::Dispatch));
        let result = machine.finish_submit(None, Some("timeout"));
        assert_eq!(result.status, "unknown");
        assert!(result.possibly_sent);
        assert!(matches!(machine.begin_submit("attempt-ambiguous").unwrap(), SubmitDecision::AlreadyAttempted(_)));
        assert!(machine.begin_fill("attempt-new").is_err());
    }

    #[test]
    fn known_not_sent_attempt_id_cannot_be_reused() {
        let mut machine = opened_machine();
        machine.begin_fill("attempt-not-sent").unwrap();
        machine.finish_fill("attempt-not-sent".to_string(), &dom("filled"));
        assert!(matches!(
            machine.begin_submit("attempt-not-sent").unwrap(),
            SubmitDecision::Dispatch
        ));
        let result = machine.finish_submit(Some(&dom("not_sent")), None);
        assert_eq!(result.status, "not_sent");
        assert!(!result.possibly_sent);
        assert!(machine.begin_fill("attempt-not-sent").is_err());
        assert!(machine.begin_fill("attempt-new").is_ok());
    }

    #[test]
    fn restart_without_a_baseline_stays_unknown() {
        let recovered = AttemptJournal {
            version: 1,
            attempt_id: "attempt-recovered".to_string(),
            phase: AttemptPhase::Pending,
            possibly_sent: true,
            baseline_count: Some(4),
        };
        let mut machine = Machine::new(Some(recovered));
        machine.begin_open().unwrap();
        machine.finish_open(true);
        machine.begin_read("attempt-recovered").unwrap();
        let mut existing = dom("ready");
        existing.assistant_count = 4;
        existing.text = "pre-existing response".to_string();
        let result = machine.finish_read(&existing);
        assert_eq!(result.status, "unknown");
        assert!(result.text.is_empty());
        assert!(result.possibly_sent);
    }

    #[test]
    fn takeover_pauses_writes_until_explicit_release() {
        let mut machine = opened_machine();
        machine.begin_fill("attempt-takeover").unwrap();
        machine.finish_fill("attempt-takeover".to_string(), &dom("filled"));
        machine.enter_takeover().unwrap();
        assert!(machine.takeover);
        assert_eq!(machine.status_result().status, "takeover");
        assert!(machine.begin_submit("attempt-takeover").is_err());
        assert!(machine.begin_fill("attempt-takeover").is_err());
        machine.takeover = false;
        assert!(matches!(machine.begin_submit("attempt-takeover").unwrap(), SubmitDecision::AlreadyAttempted(_)));
    }

    #[test]
    fn navigation_allows_only_chatgpt_and_the_manual_login_origin() {
        for allowed in [
            CHATGPT_URL,
            "https://chatgpt.com/c/123",
            "https://auth.openai.com/",
            "https://auth.openai.com/authorize?client_id=public",
        ] {
            assert!(validate_consultation_navigation(&allowed.parse().unwrap()));
        }
        for blocked in [
            "http://chatgpt.com/",
            "http://auth.openai.com/",
            "https://chatgpt.com.evil.example/",
            "https://auth.openai.com.evil.example/",
            "https://auth-openai.com/",
            "https://user@auth.openai.com/",
            "https://auth.openai.com:444/",
            "https://openai.com/",
            "https://accounts.google.com/",
        ] {
            assert!(!validate_consultation_navigation(&blocked.parse().unwrap()));
        }
    }

    #[test]
    fn navigation_diagnostics_never_keep_auth_path_query_or_fragment() {
        let mut navigation = NavigationDiagnostics::default();
        let url = "https://auth.openai.com/secret-path?code=secret-code#secret-fragment".parse().unwrap();
        for _ in 0..20 {
            navigation.record("navigation-blocked", Some(&url), None);
        }
        assert_eq!(navigation.events.len(), 16);
        let encoded = serde_json::to_string(&navigation).unwrap();
        assert!(!encoded.contains("secret"));
        assert!(encoded.contains("https://auth.openai.com"));
        navigation.record("loaded", None, None);
        assert!(navigation.failure.is_some());
        navigation.record("navigation-started", Some(&url), None);
        assert!(navigation.failure.is_none());
        navigation.record("load-failed", None, Some(7));
        assert!(navigation.failure.unwrap().contains('7'));
    }

    #[test]
    fn google_sso_is_navigation_only_and_requires_the_openai_login_chain() {
        let mut navigation = NavigationDiagnostics::default();
        let google: tauri::Url = "https://accounts.google.com/o/oauth2/v2/auth?state=private-state".parse().unwrap();
        assert!(!navigation.allow_navigation(&google));
        assert!(navigation.allow_navigation(&"https://auth.openai.com/authorize".parse().unwrap()));
        assert!(navigation.allow_navigation(&google));
        assert!(navigation.allow_navigation(&"https://accounts.google.com/v3/signin/identifier".parse().unwrap()));
        assert!(!validate_automation_url(&google));
        for blocked in ["https://accounts.google.com/ManageAccount", "https://accounts.google.com.evil.test/o/oauth2/v2/auth",
            "https://user:password@accounts.google.com/ServiceLogin", "https://accounts.google.com:8443/ServiceLogin",
            "https://myaccount.google.com/", "http://accounts.google.com/ServiceLogin"] {
            assert!(!navigation.allow_navigation(&blocked.parse().unwrap()));
        }
        let blocked_reason = navigation.failure.clone();
        navigation.record("load-failed", None, Some(14));
        assert_eq!(navigation.failure, blocked_reason);
        assert!(navigation.allow_navigation(&CHATGPT_URL.parse().unwrap()));
        assert!(!navigation.manual_login_active);
        assert!(!navigation.allow_navigation(&google));
        assert!(!serde_json::to_string(&navigation).unwrap().contains("private-state"));
    }

    #[test]
    fn reload_and_login_popup_cannot_discard_unresolved_attempts() {
        let mut machine = opened_machine();
        assert!(can_restart_navigation(&machine));
        machine.operation_in_flight = true;
        assert!(!can_restart_navigation(&machine));
        machine.operation_in_flight = false;
        machine.begin_fill("preserved-attempt").unwrap();
        machine.finish_fill("preserved-attempt".to_string(), &dom("filled"));
        for phase in [AttemptPhase::Filled, AttemptPhase::SubmitStarted, AttemptPhase::Pending, AttemptPhase::Unknown] {
            machine.attempt.as_mut().unwrap().phase = phase;
            assert!(!can_restart_navigation(&machine));
        }
        machine.attempt.as_mut().unwrap().phase = AttemptPhase::Completed;
        assert!(can_restart_navigation(&machine));
    }

    #[test]
    fn automation_never_runs_on_the_login_origin() {
        assert!(validate_automation_url(&CHATGPT_URL.parse().unwrap()));
        assert!(validate_automation_url(
            &"https://chatgpt.com/c/123".parse().unwrap()
        ));
        assert!(!validate_automation_url(
            &"https://auth.openai.com/authorize".parse().unwrap()
        ));
        assert!(!validate_automation_url(
            &"https://auth.openai.com.evil.example/".parse().unwrap()
        ));
    }

    #[cfg(windows)]
    #[test]
    fn profile_lease_is_exclusive_until_released() {
        use std::time::{SystemTime, UNIX_EPOCH};

        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let data_dir = std::env::temp_dir().join(format!(
            "sumika-consultation-lease-{}-{suffix}",
            std::process::id()
        ));
        let first = ConsultationState::new(&data_dir).unwrap();
        let second = ConsultationState::new(&data_dir).unwrap();
        first.acquire_profile_lease().unwrap();
        assert!(second.acquire_profile_lease().is_err());
        first.release_profile_lease().unwrap();
        second.acquire_profile_lease().unwrap();
        second.release_profile_lease().unwrap();
        fs::remove_dir_all(data_dir).unwrap();
    }

    #[cfg(windows)]
    #[test]
    fn profile_lease_is_recoverable_after_owner_drop() {
        use std::time::{SystemTime, UNIX_EPOCH};

        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let data_dir = std::env::temp_dir().join(format!(
            "sumika-consultation-crash-{}-{suffix}",
            std::process::id()
        ));
        {
            let crashed_owner = ConsultationState::new(&data_dir).unwrap();
            crashed_owner.acquire_profile_lease().unwrap();
        }
        let recovered_owner = ConsultationState::new(&data_dir).unwrap();
        recovered_owner.acquire_profile_lease().unwrap();
        recovered_owner.release_profile_lease().unwrap();
        fs::remove_dir_all(data_dir).unwrap();
    }

    #[test]
    fn attempt_journal_contains_no_message_or_credential_body() {
        use std::time::{SystemTime, UNIX_EPOCH};

        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let data_dir = std::env::temp_dir().join(format!(
            "sumika-consultation-journal-{}-{suffix}",
            std::process::id()
        ));
        let state = ConsultationState::new(&data_dir).unwrap();
        {
            let mut machine = state.inner.lock().unwrap();
            machine.begin_open().unwrap();
            machine.finish_open(true);
            machine.begin_fill("attempt-journal").unwrap();
            let mut baseline = dom("filled");
            baseline.text = "PRIVATE-REMOTE-CONTENT".to_string();
            machine.finish_fill("attempt-journal".to_string(), &baseline);
            assert!(matches!(
                machine.begin_submit("attempt-journal").unwrap(),
                SubmitDecision::Dispatch
            ));
        }
        state.persist_active_attempt().unwrap();
        let journal = fs::read_to_string(&state.journal_path).unwrap();
        assert!(!journal.contains("PRIVATE-REMOTE-CONTENT"));
        assert!(!journal.to_ascii_lowercase().contains("credential"));
        let value: serde_json::Value = serde_json::from_str(&journal).unwrap();
        let keys = value.as_object().unwrap().keys().cloned().collect::<Vec<_>>();
        assert_eq!(
            keys,
            vec![
                "attempt_id",
                "baseline_count",
                "phase",
                "possibly_sent",
                "version"
            ]
        );
        fs::remove_dir_all(data_dir).unwrap();
    }
}
