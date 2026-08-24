# Echo tool example

This example implements the `sumika.tool.v1` JSONL contract used by the
`tools` module. It reads one JSON request from stdin and returns one result
line. The core starts it as a fresh process for each explicitly approved
`tool.run` call.

Configure the module with:

- executable: the Python interpreter absolute path;
- arguments: the absolute path to `echo_tool.py`;
- working directory: optional;
- timeout: the default is sufficient for this example.

The example is intentionally stateless and does not access files or devices.
