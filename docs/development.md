# Development

The Python host controller uses only the standard library. Bash runs on the display, not on the Windows host. The managed helper is our own source-built code; Samsung media libraries are loaded from the display and are not bundled.

```sh
uv venv
uv pip install -e .
uv run python -m unittest discover -s tests -v
uv build
```

The CI workflow runs host tests on Windows, macOS, and Linux. Local tests cover argument handling, SDB launch, error propagation, LF staging, output protection, configuration, and loopback reception. Physical display checks are recorded in [compatibility](compatibility.md).

## Helper build

A compatible .NET SDK builds the .NET 6 managed helper required by the tested display runtime:

```sh
dotnet build native-stream/NativeStream.csproj -c Release
```

Copy `NativeStream.dll` and `NativeStream.runtimeconfig.json` from `native-stream/bin/Release/net6.0/` to `samsung_tizen_obs_input/bin/`. On PowerShell use `Copy-Item`; on macOS/Linux use `cp`. The source maps build paths to a fixed public path for reproducible output. No host .NET runtime is required to run the Python controller.

The helper handles SIGINT/SIGTERM and GStreamer ERROR/EOS, releasing its pipeline on exit. Source/destination sizes are deliberately separate. `avtype=1` must not be relabeled as an HDMI selector without evidence.

## Release contents

Build archives from the audited source snapshot. Include only project source, our helper binary/runtime configuration, documentation, tests, and license. Exclude local config, recordings, logs, device identifiers, credentials, vendor images/libraries, and environment files.
