using System;
using System.Windows;
using System.Windows.Input;
using System.Windows.Interop;
using System.Runtime.InteropServices;
using System.ComponentModel;
using System.IO;
using System.Collections.Generic;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;

namespace SumikaPetHost;

public partial class PetHost : Window
{
    private readonly string _url;
    private readonly bool _hidden;
    private bool _compact;
    private const string CaptureHostProperty = "Sumika.Companion.CaptureHost";

    private static void Diagnostic(string stage)
    {
        var directory = Environment.GetEnvironmentVariable("SUMIKA_PET_DIAGNOSTICS");
        if (string.IsNullOrWhiteSpace(directory)) return;
        try
        {
            Directory.CreateDirectory(directory);
            File.AppendAllText(Path.Combine(directory, $"pet-{Environment.ProcessId}.log"),
                $"{DateTimeOffset.UtcNow:O} {stage}{Environment.NewLine}");
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool SetWindowDisplayAffinity(IntPtr window, uint affinity);

    [StructLayout(LayoutKind.Sequential)]
    private struct NativeRect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr window, out NativeRect rect);
    [DllImport("gdi32.dll")]
    private static extern IntPtr CreateRoundRectRgn(int left, int top, int right, int bottom, int width, int height);
    [DllImport("user32.dll")]
    private static extern int SetWindowRgn(IntPtr window, IntPtr region, bool redraw);
    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr window, IntPtr insertAfter, int x, int y, int cx, int cy, uint flags);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetProp(IntPtr window, string name, IntPtr value);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr RemoveProp(IntPtr window, string name);

    [DllImport("user32.dll")]
    private static extern bool ReleaseCapture();

    [StructLayout(LayoutKind.Sequential)]
    private struct CursorPoint { public int X; public int Y; }

    [DllImport("user32.dll")]
    private static extern bool GetCursorPos(out CursorPoint point);

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);

    public PetHost(string url, bool hidden = false)
    {
        InitializeComponent();
        _url = url;
        _hidden = hidden;
        var workArea = SystemParameters.WorkArea;
        Left = workArea.Right - Width - 12;
        Top = workArea.Bottom - Height - 12;
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        try
        {
            var handle = new WindowInteropHelper(this).Handle;
            Diagnostic("window-created");
            // Do not set WDA_EXCLUDEFROMCAPTURE here: the desktop pet is meant to
            // be visible in screenshots and normal capture tools.
            SetProp(handle, CaptureHostProperty, new IntPtr(1));
            Topmost = true;
            SetWindowPos(handle, new IntPtr(-1), 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010);
            var cache = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Sumika", "WebView2", "PetHost");
            var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: cache);
            Diagnostic("environment-ready");
            await Browser.EnsureCoreWebView2Async(environment);
            Diagnostic("webview-ready");
            Browser.DefaultBackgroundColor = System.Drawing.Color.Transparent;
            Browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            Browser.CoreWebView2.Settings.AreDevToolsEnabled = false;
            var origin = new Uri(_url).GetLeftPart(UriPartial.Authority);
            Browser.CoreWebView2.WebMessageReceived += (_, message) =>
            {
                if (!Uri.TryCreate(message.Source, UriKind.Absolute, out var source)
                    || source.GetLeftPart(UriPartial.Authority) != origin)
                    return;
                try
                {
                    var action = message.TryGetWebMessageAsString();
                    if (action == "sumika:compact" || action == "sumika:expand")
                    {
                        var compact = action == "sumika:compact";
                        if (compact == _compact) return;
                        var right = Left + Width;
                        var bottom = Top + Height;
                        Width = compact ? 76 : 380;
                        Height = compact ? 76 : 540;
                        Left = right - Width;
                        Top = bottom - Height;
                        CloseButton.Visibility = Visibility.Collapsed;
                        _compact = compact;
                        Diagnostic(compact ? "compacted" : "expanded");
                        return;
                    }
                    if (action != "sumika:drag") return;
                }
                catch (ArgumentException) { return; }
                Diagnostic("drag-received");
                // Delegate the existing page drag gesture to the native window.
                if (!GetCursorPos(out var point)) return;
                ReleaseCapture();
                var coordinates = unchecked((int)(((uint)point.Y & 0xffff) << 16 | ((uint)point.X & 0xffff)));
                SendMessage(handle, 0xA1, new IntPtr(2), new IntPtr(coordinates));
            };
            Browser.CoreWebView2.NavigationStarting += (_, navigation) =>
            {
                if (!Uri.TryCreate(navigation.Uri, UriKind.Absolute, out var destination)
                    || destination.GetLeftPart(UriPartial.Authority) != origin)
                    navigation.Cancel = true;
            };
            Browser.CoreWebView2.NewWindowRequested += (_, request) => request.Handled = true;
            if (!string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("SUMIKA_PET_DIAGNOSTICS")))
            {
                var requests = new Dictionary<string, string>();
                Browser.CoreWebView2.GetDevToolsProtocolEventReceiver("Network.requestWillBeSent")
                    .DevToolsProtocolEventReceived += (_, message) =>
                {
                    using var document = JsonDocument.Parse(message.ParameterObjectAsJson);
                    var data = document.RootElement;
                    if (Uri.TryCreate(data.GetProperty("request").GetProperty("url").GetString(), UriKind.Absolute, out var uri)
                        && uri.GetLeftPart(UriPartial.Authority) == origin
                        && uri.AbsolutePath.EndsWith(".css", StringComparison.OrdinalIgnoreCase))
                    {
                        if (requests.Count >= 64) requests.Clear();
                        requests[data.GetProperty("requestId").GetString()!] = uri.AbsolutePath;
                        Diagnostic($"stylesheet-request {uri.AbsolutePath}");
                    }
                };
                foreach (var eventName in new[] { "Network.loadingFailed", "Network.loadingFinished" })
                {
                    var failed = eventName == "Network.loadingFailed";
                    Browser.CoreWebView2.GetDevToolsProtocolEventReceiver(eventName)
                        .DevToolsProtocolEventReceived += (_, message) =>
                    {
                        using var document = JsonDocument.Parse(message.ParameterObjectAsJson);
                        var data = document.RootElement;
                        if (!requests.Remove(data.GetProperty("requestId").GetString()!, out var path)) return;
                        var detail = failed ? data.GetProperty("errorText").GetString() : "finished";
                        Diagnostic($"stylesheet-network {path} result={detail}");
                    };
                }
                await Browser.CoreWebView2.CallDevToolsProtocolMethodAsync("Network.enable", "{}");
            }
            Browser.CoreWebView2.WebResourceResponseReceived += (_, resource) =>
            {
                if (Uri.TryCreate(resource.Request.Uri, UriKind.Absolute, out var uri)
                    && uri.AbsolutePath.EndsWith(".css", StringComparison.OrdinalIgnoreCase))
                    Diagnostic($"stylesheet {uri.AbsolutePath} status={resource.Response.StatusCode} type={resource.Response.Headers.GetHeader("Content-Type")}");
            };
            Browser.CoreWebView2.ProcessFailed += (_, failure) =>
                Diagnostic($"webview-process-failed kind={failure.ProcessFailedKind} reason={failure.Reason}");
            Browser.CoreWebView2.NavigationCompleted += async (_, navigation) =>
            {
                Diagnostic($"navigation-completed success={navigation.IsSuccess} status={navigation.WebErrorStatus}");
                if (!string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("SUMIKA_PET_DIAGNOSTICS")))
                {
                    var styles = await Browser.CoreWebView2.ExecuteScriptAsync("""
                        JSON.stringify({ready:document.readyState,
                          sheets:[...document.styleSheets].map(sheet=>{
                            const result={path:sheet.href&&new URL(sheet.href).pathname,disabled:sheet.disabled};
                            try{result.rules=sheet.cssRules.length}catch(error){result.error=error.name}
                            return result;
                          }),
                          links:[...document.querySelectorAll('link[rel="stylesheet"]')].map(link=>({
                            path:new URL(link.href).pathname,loaded:!!link.sheet,media:link.media})),
                          ink:getComputedStyle(document.documentElement).getPropertyValue('--ink'),
                          paper:getComputedStyle(document.documentElement).getPropertyValue('--paper')})
                        """);
                    Diagnostic($"style-health={styles}");
                    var projection = await Browser.CoreWebView2.ExecuteScriptAsync(
                        "JSON.stringify({pet:document.documentElement.classList.contains('pet-host'),body:document.body.className,desk:JSON.stringify((()=>{const e=document.querySelector('#deskpet');const r=e?.getBoundingClientRect();return {display:e&&getComputedStyle(e).display,rect:r&&[r.left,r.top,r.width,r.height],pointer:e&&getComputedStyle(e).pointerEvents}})()),input:JSON.stringify((()=>{const e=document.querySelector('[data-dp-input]');const r=e?.getBoundingClientRect(),s=e&&getComputedStyle(e);return {display:s?.display,visibility:s?.visibility,rect:r&&[r.left,r.top,r.width,r.height]}})()),styles:[...document.styleSheets].map(x=>x.href),resources:performance.getEntriesByType('resource').map(x=>x.name).filter(x=>x.includes('/app/css/')),main:JSON.stringify((()=>{const e=document.querySelector('main');return e&&getComputedStyle(e).display})()),point:document.elementFromPoint(innerWidth/2,innerHeight/2)?.className})");
                    Diagnostic($"projection={projection}");
                }
            };
            Browser.Source = new Uri(_url);
            Dispatcher.BeginInvoke(new Action(ApplyShape));
            if (_hidden) Dispatcher.BeginInvoke(new Action(Hide));
        }
        catch (Exception error)
        {
            MessageBox.Show($"桌宠窗口无法启动：{error.Message}", "Sumika");
            Close();
        }
    }

    protected override void OnClosed(EventArgs e)
    {
        RemoveProp(new WindowInteropHelper(this).Handle, CaptureHostProperty);
        base.OnClosed(e);
    }

    private void ApplyShape()
    {
        var handle = new WindowInteropHelper(this).Handle;
        if (handle == IntPtr.Zero || !GetWindowRect(handle, out var rect)) return;
        var width = rect.Right - rect.Left;
        var height = rect.Bottom - rect.Top;
        if (width < 8 || height < 8) return;
        if (Width > 100)
        {
            SetWindowRgn(handle, IntPtr.Zero, true);
            return;
        }
        var region = CreateRoundRectRgn(0, 0, width + 1, height + 1, width, width);
        if (region != IntPtr.Zero) SetWindowRgn(handle, region, true);
    }

    private void CloseHost(object sender, RoutedEventArgs e) => Close();
}
