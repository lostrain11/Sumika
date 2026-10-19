using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
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
    private bool _serverReady;
    private readonly string? _initialRoute;
    private WinForms.NotifyIcon? _tray;

    public ShellWindow(int port, string? dataDirectory, string? initialRoute = null)
    {
        InitializeComponent();
        _initialRoute = initialRoute;
        _port = port;
        _dataDirectory = dataDirectory;
        _baseUrl = $"http://127.0.0.1:{port}/";
        _http = new HttpClient(new HttpClientHandler { UseProxy = false })
        {
            Timeout = TimeSpan.FromSeconds(8),
        };
        Loaded += OnLoaded;
        Closing += OnClosing;
        StateChanged += (_, _) => _ = SyncPetAsync();
        IsVisibleChanged += (_, _) => _ = SyncPetAsync();
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        try
        {
            await EnsureServerAsync();
            _serverReady = true;
            var cache = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Sumika", "WebView2");
            var environment = await CoreWebView2Environment.CreateAsync(null, cache, null);
            await Browser.EnsureCoreWebView2Async(environment);
            Browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            Browser.CoreWebView2.Settings.AreDevToolsEnabled = false;
            Browser.CoreWebView2.Settings.IsStatusBarEnabled = false;
            await Browser.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                "document.documentElement.classList.add('shell-host');");
            Browser.CoreWebView2.WebMessageReceived += OnShellMessage;
            var target = string.IsNullOrWhiteSpace(_initialRoute)
                ? _baseUrl
                : _baseUrl + "#" + Uri.EscapeDataString(_initialRoute);
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
            using var document = JsonDocument.Parse(e.WebMessageAsJson);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object
                || root.GetProperty("type").GetString() != "sumika:context") return;
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

    private async Task SyncPetAsync()
    {
        if (_petBusy || !_serverReady) return;
        _petBusy = true;
        try
        {
            var desired = _route != "room" || WindowState == WindowState.Minimized || !IsVisible;
            if (desired == _petRunning) return;
            if (desired)
                _petRunning = await PetActionAsync("start");
            else
            {
                await PetActionAsync("stop");
                _petRunning = false;
            }
        }
        finally
        {
            _petBusy = false;
        }
    }

    private async Task<bool> PetActionAsync(string action)
    {
        try
        {
            using var session = await _http.GetAsync(_baseUrl + "api/manage/session");
            using var sessionDocument = JsonDocument.Parse(await session.Content.ReadAsStringAsync());
            var csrf = sessionDocument.RootElement.GetProperty("csrf").GetString();
            if (string.IsNullOrWhiteSpace(csrf)) return false;
            using var request = new HttpRequestMessage(HttpMethod.Post, _baseUrl + "api/companion/pet");
            request.Headers.Add("X-Sumika-CSRF", csrf);
            request.Content = new StringContent("{\"action\":\"" + action + "\"}",
                System.Text.Encoding.UTF8, "application/json");
            using var response = await _http.SendAsync(request);
            if (!response.IsSuccessStatusCode) return false;
            using var result = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            return action == "start"
                && result.RootElement.TryGetProperty("alive", out var alive)
                && alive.ValueKind == JsonValueKind.True;
        }
        catch (Exception) { return false; }
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
            if (_ownsServer || _petRunning) await StopPetAsync();
            if (_ownsServer) await StopOwnedServerAsync();
        }
        finally
        {
            _tray?.Dispose();
            _tray = null;
            Close();
        }
    }

    private async Task StopPetAsync()
    {
        if (!_petRunning) return;
        await PetActionAsync("stop");
        _petRunning = false;
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
