using System;
using System.Windows;

namespace SumikaPetHost;

public partial class App : Application
{
    private void OnStartup(object sender, StartupEventArgs args)
    {
        var url = args.Args.Length > 0 ? args.Args[0] : "http://127.0.0.1:8879/?pet=1";
        if (!Uri.TryCreate(url, UriKind.Absolute, out var parsed) || parsed.Scheme != "http"
            || parsed.Host != "127.0.0.1" || parsed.UserInfo.Length != 0)
        {
            MessageBox.Show("桌宠仅接受本机 Sumika bridge 地址。", "Sumika");
            Shutdown(2);
            return;
        }
        new PetHost(parsed.ToString()).Show();
    }
}
