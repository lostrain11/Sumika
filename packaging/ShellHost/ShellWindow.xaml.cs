using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using Microsoft.Web.WebView2.Core;

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

    public ShellWindow(int port, string? dataDirectory)
    {
        InitializeComponent();
        _port = port;
        _dataDirectory = dataDirectory;
        _baseUrl = $"http://127.0.0.1:{port}/";
        _http = new HttpClient(new HttpClientHandler { UseProxy = false })
        {
            Timeout = TimeSpan.FromSeconds(8),
        };
        Loaded += OnLoaded;
        Closing += OnClosing;
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        try
        {
            await EnsureServerAsync();
            var cache = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Sumika", "WebView2");
            var environment = await CoreWebView2Environment.CreateAsync(null, cache, null);
            await Browser.EnsureCoreWebView2Async(environment);
            Browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            Browser.CoreWebView2.Settings.AreDevToolsEnabled = false;
            Browser.CoreWebView2.Settings.IsStatusBarEnabled = false;
            Browser.Source = new Uri(_baseUrl);
        }
        catch (Exception error)
        {
            MessageBox.Show(this,
                "无法打开 Sumika 主窗口：" + error.Message + "\n\n请确认安装目录完整，且 8765 端口可用。",
                "Sumika", MessageBoxButton.OK, MessageBoxImage.Error);
            _allowClose = true;
            Close();
        }
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
        try
        {
            if (_ownsServer) await StopOwnedServerAsync();
        }
        finally
        {
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
