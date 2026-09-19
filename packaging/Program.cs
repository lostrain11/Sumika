using System.Diagnostics;

static string? FindPowerShell()
{
    foreach (var name in new[] { "pwsh.exe", "powershell.exe" })
    {
        var path = Environment.GetEnvironmentVariable("PATH")?.Split(Path.PathSeparator)
            .Select(p => Path.Combine(p, name)).FirstOrDefault(File.Exists);
        if (path is not null) return path;
    }
    return null;
}

var root = AppContext.BaseDirectory;
var script = Path.Combine(root, "tools", "start_sumika.ps1");
if (!File.Exists(script))
{
    Console.Error.WriteLine($"Sumika 运行文件不完整，缺少：{script}");
    return 2;
}

var shell = FindPowerShell();
if (shell is null)
{
    Console.Error.WriteLine("未找到 PowerShell，无法启动 Sumika。");
    return 3;
}

var psi = new ProcessStartInfo(shell)
{
    UseShellExecute = false,
    WorkingDirectory = root,
    RedirectStandardOutput = true,
    RedirectStandardError = true,
    CreateNoWindow = false,
};
psi.ArgumentList.Add("-NoProfile");
psi.ArgumentList.Add("-ExecutionPolicy");
psi.ArgumentList.Add("Bypass");
psi.ArgumentList.Add("-File");
psi.ArgumentList.Add(script);
foreach (var arg in args) psi.ArgumentList.Add(arg);

using var process = Process.Start(psi);
if (process is null)
{
    Console.Error.WriteLine("无法启动 Sumika PowerShell 宿主。");
    return 4;
}
process.OutputDataReceived += (_, e) => { if (e.Data is not null) Console.Out.WriteLine(e.Data); };
process.ErrorDataReceived += (_, e) => { if (e.Data is not null) Console.Error.WriteLine(e.Data); };
process.BeginOutputReadLine();
process.BeginErrorReadLine();
process.WaitForExit();
return process.ExitCode;
