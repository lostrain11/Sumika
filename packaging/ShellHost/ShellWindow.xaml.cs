using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;
using Microsoft.Web.WebView2.Core;
using WinForms = System.Windows.Forms;

namespace SumikaShell;

public partial class ShellWindow : Window
{
    private readonly int _port;
    private readonly string? _dataDirectory;
    private readonly string _baseUrl;
    private readonly HttpClient _http;
    private Process? _server;
    private bool _ownsServer;
    private bool _allowClose;
    private string _route = "room";
    private bool _petRunning;
    private bool _petBusy;
    private int _petPid;
    private IntPtr _petWindow;
    private bool _serverReady;
    private readonly string? _initialRoute;
    private WinForms.NotifyIcon? _tray;
    private readonly DispatcherTimer _petTimer = new() { Interval = TimeSpan.FromMilliseconds(400) };

    public ShellWindow(int port, string? dataDirectory, string? initialRoute = null)
    {
        InitializeComponent();
        _initialRoute = initialRoute;
        _route = string.IsNullOrWhiteSpace(initialRoute) ? "room" : initialRoute;
        _port = port;
        _dataDirectory = dataDirectory;
        _baseUrl = $"http://127.0.0.1:{port}/";
        _http = new HttpClient(new HttpClientHandler { UseProxy = false })
        {
            Timeout = TimeSpan.FromSeconds(8),
        };
        Loaded += OnLoaded;
        Closing += OnClosing;
        _petTimer.Tick += (_, _) => _ = SyncPetAsync();
        _petTimer.Start();
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        try
        {
            await EnsureServerAsync();
            _serverReady = true;
            _ = PrewarmPetAsync();
            var cache = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Sumika", "WebView2");
            var environment = await CoreWebView2Environment.CreateAsync(null, cache, null);
            await Browser.EnsureCoreWebView2Async(environment);
            Browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            Browser.CoreWebView2.Settings.AreDevToolsEnabled = false;
            Browser.CoreWebView2.Settings.IsStatusBarEnabled = false;
            await Browser.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                "document.documentElement.classList.add('shell-host');" +
                "document.addEventListener('click', e => {" +
                " if (e.target && e.target.closest && e.target.closest('#petChip'))" +
                "  window.chrome.webview.postMessage(JSON.stringify({type:'sumika:pet-mode'}));" +
                "}, true);");
            Browser.CoreWebView2.WebMessageReceived += OnShellMessage;
            var target = _baseUrl + "?shell=1";
            if (!string.IsNullOrWhiteSpace(_initialRoute))
                target += "#" + Uri.EscapeDataString(_initialRoute);
            Browser.Source = new Uri(target);
        }
        catch (Exception error)
        {
            MessageBox.Show(this,
                "无法打开 Sumika 主窗口：" + error.Message + "\n\n请确认安装目录完整，且端口可用。",
                "Sumika", MessageBoxButton.OK, MessageBoxImage.Error);
            _allowClose = true;
            Close();
        }
    }

    private void OnShellMessage(object? sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        try
        {
            using var outer = JsonDocument.Parse(e.WebMessageAsJson);
            JsonElement root = outer.RootElement;
            if (root.ValueKind == JsonValueKind.String)
            {
                using var nested = JsonDocument.Parse(root.GetString() ?? "{}");
                root = nested.RootElement.Clone();
            }
            if (root.ValueKind != JsonValueKind.Object
                || !root.TryGetProperty("type", out var kind)) return;
            if (kind.GetString() == "sumika:pet-mode")
            {
                Dispatcher.Invoke(() => WindowState = WindowState.Minimized);
                return;
            }
            if (kind.GetString() != "sumika:context") return;
            var route = root.TryGetProperty("route", out var value) ? value.GetString() : null;
            if (!string.IsNullOrWhiteSpace(route) && route != _route)
            {
                _route = route;
                _ = SyncPetAsync();
            }
        }
        catch (JsonException) { }
        catch (InvalidOperationException) { }
        catch (KeyNotFoundException) { }
    }

    private void CreateTray()
    {
        try
        {
            var resource = System.Windows.Application.GetResourceStream(
                new Uri("Assets/Sumika.ico", UriKind.Relative));
            var icon = resource?.Stream is { } stream
                ? new System.Drawing.Icon(stream)
                : System.Drawing.SystemIcons.Application;
            _tray = new WinForms.NotifyIcon
            {
                Icon = icon,
                Text = "晴日部室",
                Visible = true,
            };
            var menu = new WinForms.ContextMenuStrip();
            menu.Items.Add("显示主窗口", null, (_, _) => ShowMainWindow());
            menu.Items.Add("隐藏到托盘", null, (_, _) => Hide());
            menu.Items.Add("退出 Sumika", null, (_, _) =>
            {
                _allowClose = true;
                Close();
            });
            _tray.ContextMenuStrip = menu;
            _tray.DoubleClick += (_, _) => ShowMainWindow();
        }
        catch (Exception) { }
    }

    private void ShowMainWindow()
    {
        Dispatcher.Invoke(() =>
        {
            Show();
            WindowState = WindowState.Normal;
            Activate();
        });
    }

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr parameter);
    private delegate bool EnumWindowsProc(IntPtr window, IntPtr parameter);
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("user32.dll")]
    private static extern bool IsWindow(IntPtr window);
    [StructLayout(LayoutKind.Sequential)]
    private struct WindowRect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr window, out WindowRect rect);
    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr window, IntPtr insertAfter,
        int x, int y, int width, int height, uint flags);

    private static IntPtr FindPetWindow(int pid)
    {
        var found = IntPtr.Zero;
        EnumWindows((window, _) =>
        {
            GetWindowThreadProcessId(window, out var owner);
            if (owner != pid) return true;
            if (!GetWindowRect(window, out var rect)) return true;
            // The pet's top-level window is at least the compact orb box; skip
            // WebView2/utility windows that are short or zero-sized.
            var width = rect.Right - rect.Left;
            var height = rect.Bottom - rect.Top;
            if (width < 60 || height < 60 || width > 600 || height > 800) return true;
            found = window;
            return false;
        }, IntPtr.Zero);
        return found;
    }

    private async Task SyncPetAsync()
    {
        if (_petBusy || !_serverReady) return;
        _petBusy = true;
        try
        {
            var desired = WindowState == WindowState.Minimized || !IsVisible;
            if (desired)
            {
                if (!await EnsurePetAsync()) return;
                ShowWindow(_petWindow, 8); // SW_SHOWNA
                SetWindowPos(_petWindow, new IntPtr(-1), 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010);
                _petRunning = true;
            }
            else
            {
                if (_petWindow != IntPtr.Zero && IsWindow(_petWindow))
                    ShowWindow(_petWindow, 0); // SW_HIDE
                _petRunning = false;
            }
        }
        finally
        {
            _petBusy = false;
        }
    }

    private async Task PrewarmPetAsync()
    {
        if (!_serverReady) return;
        await EnsurePetAsync();
    }

    private async Task<bool> EnsurePetAsync()
    {
        if (_petWindow != IntPtr.Zero && IsWindow(_petWindow)) return true;
        if (_petPid == 0)
        {
            var started = await StartHiddenPetAsync();
            if (!started) return false;
        }
        for (var i = 0; i < 50; i++)
        {
            var handle = FindPetWindow(_petPid);
            if (handle != IntPtr.Zero)
            {
                _petWindow = handle;
                ShowWindow(handle, 0);
                return true;
            }
            await Task.Delay(100);
        }
        return false;
    }

    private async Task<bool> StartHiddenPetAsync()
    {
        try
        {
            using var session = await _http.GetAsync(_baseUrl + "api/manage/session");
            using var sessionDocument = JsonDocument.Parse(await session.Content.ReadAsStringAsync());
            var csrf = sessionDocument.RootElement.GetProperty("csrf").GetString();
            if (string.IsNullOrWhiteSpace(csrf)) return false;
            using var request = new HttpRequestMessage(HttpMethod.Post, _baseUrl + "api/companion/pet");
            request.Headers.Add("X-Sumika-CSRF", csrf);
            request.Content = new StringContent("{\"action\":\"start\",\"hidden\":true}",
                System.Text.Encoding.UTF8, "application/json");
            using var response = await _http.SendAsync(request);
            if (!response.IsSuccessStatusCode) return false;
            using var result = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            if (!result.RootElement.TryGetProperty("alive", out var alive)
                || alive.ValueKind != JsonValueKind.True) return false;
            if (result.RootElement.TryGetProperty("pid", out var pid)
                && pid.TryGetInt32(out var value)) _petPid = value;
            return _petPid != 0;
        }
        catch (Exception) { return false; }
    }

    private async Task StopPetAsync()
    {
        if (_petPid == 0) return;
        try
        {
            using var session = await _http.GetAsync(_baseUrl + "api/manage/session");
            using var sessionDocument = JsonDocument.Parse(await session.Content.ReadAsStringAsync());
            var csrf = sessionDocument.RootElement.GetProperty("csrf").GetString();
            if (!string.IsNullOrWhiteSpace(csrf))
            {
                using var request = new HttpRequestMessage(HttpMethod.Post, _baseUrl + "api/companion/pet");
                request.Headers.Add("X-Sumika-CSRF", csrf);
                request.Content = new StringContent("{\"action\":\"stop\"}",
                    System.Text.Encoding.UTF8, "application/json");
                using var response = await _http.SendAsync(request);
            }
        }
        catch (Exception) { }
        _petWindow = IntPtr.Zero;
        _petPid = 0;
        _petRunning = false;
    }

    private async Task EnsureServerAsync()
    {
        if (await ProbeAsync()) return;

        var launcher = Path.Combine(AppContext.BaseDirectory, "Sumika.exe");
        if (!File.Exists(launcher))
            throw new FileNotFoundException("缺少 Sumika.exe", launcher);

        var start = new ProcessStartInfo(launcher)
        {
            WorkingDirectory = AppContext.BaseDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        start.ArgumentList.Add("-NoBrowser");
        start.ArgumentList.Add("-Port");
        start.ArgumentList.Add(_port.ToString());
        if (!string.IsNullOrWhiteSpace(_dataDirectory))
        {
            start.ArgumentList.Add("-DataDirectory");
            start.ArgumentList.Add(_dataDirectory);
        }
        _server = Process.Start(start) ?? throw new InvalidOperationException("无法启动 Sumika 服务");
        _ownsServer = true;

        for (var i = 0; i < 90; i++)
        {
            await Task.Delay(500);
            if (await ProbeAsync()) return;
            if (_server.HasExited && !await ProbeAsync())
                throw new InvalidOperationException("Sumika 服务提前退出");
        }
        throw new TimeoutException("Sumika 服务启动超时");
    }

    private async Task<bool> ProbeAsync()
    {
        try
        {
            using var response = await _http.GetAsync(_baseUrl, HttpCompletionOption.ResponseHeadersRead);
            return response.IsSuccessStatusCode;
        }
        catch (HttpRequestException) { return false; }
        catch (TaskCanceledException) { return false; }
    }

    private async void OnClosing(object? sender, System.ComponentModel.CancelEventArgs e)
    {
        if (_allowClose) return;
        e.Cancel = true;
        _allowClose = true;
        _serverReady = false;
        try
        {
            if (_ownsServer || _petPid != 0) await StopPetAsync();
            if (_ownsServer) await StopOwnedServerAsync();
        }
        finally
        {
            _petTimer.Stop();
            _tray?.Dispose();
            _tray = null;
            Close();
        }
    }

    private async Task StopOwnedServerAsync()
    {
        try
        {
            using var session = await _http.GetAsync(_baseUrl + "api/manage/session");
            using var document = JsonDocument.Parse(await session.Content.ReadAsStringAsync());
            var csrf = document.RootElement.GetProperty("csrf").GetString();
            if (!string.IsNullOrWhiteSpace(csrf))
            {
                using var request = new HttpRequestMessage(HttpMethod.Post, _baseUrl + "api/lifecycle/shutdown");
                request.Headers.Add("X-Sumika-CSRF", csrf);
                request.Content = new StringContent("{}", System.Text.Encoding.UTF8, "application/json");
                using var response = await _http.SendAsync(request);
            }
        }
        catch (Exception) { }

        if (_server is { HasExited: false })
        {
            try
            {
                await _server.WaitForExitAsync(new CancellationTokenSource(TimeSpan.FromSeconds(4)).Token);
            }
            catch (OperationCanceledException)
            {
                try { _server.Kill(entireProcessTree: true); } catch (InvalidOperationException) { }
            }
        }
    }
}
