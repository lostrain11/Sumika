# Echo provider

This is the smallest external provider example. It reads one JSON request per
line from stdin and emits JSONL token events. The core never imports this file;
the manifest and process boundary are the extension contract.

Run it manually from the repository root:

```powershell
python plugins/examples/echo-provider/echo_provider.py
```
