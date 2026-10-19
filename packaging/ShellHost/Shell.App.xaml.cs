using System;
using System.Windows;

namespace SumikaShell;

public partial class App : Application
{
    private void OnStartup(object sender, StartupEventArgs args)
    {
        var port = 8765;
        string? dataDirectory = null;
        for (var i = 0; i < args.Args.Length; i++)
        {
            if (args.Args[i] == "-Port" && i + 1 < args.Args.Length && int.TryParse(args.Args[++i], out var parsed))
                port = parsed;
            else if (args.Args[i] == "-DataDirectory" && i + 1 < args.Args.Length)
                dataDirectory = args.Args[++i];
        }
        new ShellWindow(port, dataDirectory).Show();
    }
}
