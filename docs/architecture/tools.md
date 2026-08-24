# External tools

The `tools` module is an explicit bridge to user-selected local software. It
is disabled by default and stores only non-secret configuration: an absolute
executable path, fixed arguments, an optional absolute working directory, and
an execution timeout.

## Configuration

Select the `external-process` implementation in the Modules page, enable the
module, and provide:

- `executable`: an absolute path to the program;
- `arguments`: fixed startup arguments, never interpolated with user input;
- `working_directory`: optional absolute directory;
- `timeout_seconds`: between 1 and 120 seconds.

The core starts a new process for each call with `shell=False`. It never
searches `PATH`, evaluates a shell command, or keeps the process alive.
This process boundary is not an OS sandbox: the configured program retains its
normal user permissions. A future sandboxed runner must be a separate
implementation with its own manifest and approval policy.

## JSONL contract

`tool.run` accepts `tool_id`, JSON-compatible `input`, and
`approved: true`. Approval is required for every invocation:

```json
{
  "protocol": "sumika.tool.v1",
  "request_id": "tool-...",
  "tool_id": "document-check",
  "input": {"path": "D:/work/report.md"}
}
```

The process reads one request line from stdin and returns one or more JSONL
lines. A result may be returned as `{"type":"result","result":...}` or a
direct JSON value. `{"type":"error","message":"..."}` fails the call.

`tool.started`, `tool.completed`, and `tool.failed` events contain request
identity, executable name, input hash/size, output size, timing, and a
redacted error summary. They never contain the input or result body.

## 相关文档

- [Manifest](manifest.md)
- [Tasks](tasks.md)
- [Security](security.md)
