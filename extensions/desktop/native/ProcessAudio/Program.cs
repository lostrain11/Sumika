using System.Diagnostics;
using System.Text.Json;
using System.Threading.Channels;
using NAudio.CoreAudioApi;
using NAudio.Wave;

internal static class Program
{
    private static async Task<int> Main(string[] args)
    {
        if (args.SequenceEqual(new[] { "--probe" }))
        {
            Console.WriteLine(JsonSerializer.Serialize(new {
                provider = "wasapi-process-loopback", version = "NAudio.Wasapi 3.1.0",
                supported = OperatingSystem.IsWindowsVersionAtLeast(10, 0, 20348),
                process_isolation = true, sample_rate = 16000, channels = 1
            }));
            return 0;
        }
        try
        {
            if (args.Length != 5 || args[0] != "--process-id" || args[2] != "--creation"
                || args[4] != "--consent" || !int.TryParse(args[1], out int pid)
                || pid <= 0 || pid == Environment.ProcessId || !long.TryParse(args[3], out long creation))
                throw new ArgumentException("Explicit target identity and consent required");
            if (!OperatingSystem.IsWindowsVersionAtLeast(10, 0, 20348))
                throw new PlatformNotSupportedException("Windows build 20348 or later required");
            // The owner assigns this child to its kill-on-close job before START.
            if (await Console.In.ReadLineAsync() != "START")
                throw new InvalidOperationException("Owner did not authorize start");
            using var target = Process.GetProcessById(pid);
            if (target.HasExited || target.StartTime.ToFileTimeUtc() != creation)
                throw new InvalidOperationException("Target process identity changed");
            using var recorder = await new WasapiRecorderBuilder()
                .WithProcessLoopback((uint)pid, ProcessLoopbackMode.IncludeTargetProcessTree)
                .WithFormat(new WaveFormat(16000, 16, 1)).BuildAsync();
            if (target.HasExited || target.StartTime.ToFileTimeUtc() != creation)
                throw new InvalidOperationException("Target process exited during activation");
            if (recorder.WaveFormat.SampleRate != 16000 || recorder.WaveFormat.Channels != 1
                || recorder.WaveFormat.BitsPerSample != 16 || recorder.WaveFormat.Encoding != WaveFormatEncoding.Pcm)
                throw new InvalidOperationException("Requested PCM format unavailable");

            var packets = Channel.CreateBounded<(byte[] Pcm, long DevicePosition, long QpcPosition, int Flags)>(new BoundedChannelOptions(16) {
                SingleReader = true, SingleWriter = true, FullMode = BoundedChannelFullMode.Wait
            });
            var failed = new TaskCompletionSource<Exception>(TaskCreationOptions.RunContinuationsAsynchronously);
            recorder.DataAvailable += (buffer, flags, devicePosition, qpcPosition) => {
                if (buffer.Length > 64000 || buffer.Length % 2 != 0) {
                    failed.TrySetResult(new InvalidOperationException("Invalid capture packet"));
                    return;
                }
                byte[] pcm = (flags & AudioClientBufferFlags.Silent) != 0
                    ? new byte[buffer.Length] : buffer.ToArray();
                if (!packets.Writer.TryWrite((pcm, devicePosition, qpcPosition, (int)flags)))
                    failed.TrySetResult(new InvalidOperationException("Audio consumer overflow"));
            };
            recorder.RecordingStopped += (_, e) => {
                if (e.Exception != null) failed.TrySetResult(e.Exception);
            };
            using var stopping = new CancellationTokenSource();
            recorder.StartRecording();
            Console.WriteLine(JsonSerializer.Serialize(new {
                status = "started", process_id = pid, creation = args[3],
                sample_rate = 16000, channels = 1, sample_width = 2, process_isolation = true
            }));
            var writing = Task.Run(async () => {
                await foreach (var packet in packets.Reader.ReadAllAsync(stopping.Token)) {
                    await Console.Out.WriteLineAsync(JsonSerializer.Serialize(new {
                        status = "pcm", process_id = pid, pcm = Convert.ToBase64String(packet.Pcm),
                        device_position = packet.DevicePosition, qpc_position = packet.QpcPosition,
                        capture_flags = packet.Flags
                    }));
                    await Console.Out.FlushAsync();
                }
            });
            var targetExited = target.WaitForExitAsync(stopping.Token);
            var requestedStop = Console.In.ReadLineAsync(stopping.Token).AsTask();
            try
            {
                var ended = await Task.WhenAny(writing, targetExited, requestedStop, failed.Task);
                if (ended == failed.Task) throw await failed.Task;
                if (ended == writing) await writing;
                if (ended == targetExited) throw new InvalidOperationException("Target process exited");
                // A closed stdin is also revocation. No recording survives the owner.
            }
            finally
            {
                recorder.StopRecording();
                packets.Writer.TryComplete();
                stopping.Cancel();
                try { await writing; } catch (OperationCanceledException) { }
                while (packets.Reader.TryRead(out _)) { }
            }
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(JsonSerializer.Serialize(new {
                status = "error", reason = error.GetType().Name, hresult = error.HResult
            }));
            return 1;
        }
    }
}
