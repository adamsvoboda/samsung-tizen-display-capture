using System.Net;
using System.Runtime.InteropServices;

internal static class Program
{
    [DllImport("libgstreamer-1.0.so.0", EntryPoint = "gst_init")]
    private static extern void GstInit(IntPtr argc, IntPtr argv);

    [DllImport("libgstreamer-1.0.so.0", EntryPoint = "gst_parse_launch")]
    private static extern IntPtr GstParseLaunch(string description, out IntPtr error);

    [DllImport("libgstreamer-1.0.so.0", EntryPoint = "gst_element_set_state")]
    private static extern int GstElementSetState(IntPtr element, int state);

    [DllImport("libgstreamer-1.0.so.0", EntryPoint = "gst_element_get_state")]
    private static extern int GstElementGetState(IntPtr element, out int state, out int pending, ulong timeout);

    [DllImport("libgstreamer-1.0.so.0", EntryPoint = "gst_object_unref")]
    private static extern void GstObjectUnref(IntPtr obj);

    [DllImport("libgstreamer-1.0.so.0", EntryPoint = "gst_element_get_bus")]
    private static extern IntPtr GstElementGetBus(IntPtr element);

    [DllImport("libgstreamer-1.0.so.0", EntryPoint = "gst_bus_timed_pop_filtered")]
    private static extern IntPtr GstBusTimedPopFiltered(IntPtr bus, ulong timeout, uint types);

    [DllImport("libgstreamer-1.0.so.0", EntryPoint = "gst_message_get_structure")]
    private static extern IntPtr GstMessageGetStructure(IntPtr message);

    [DllImport("libgstreamer-1.0.so.0", EntryPoint = "gst_message_parse_error")]
    private static extern void GstMessageParseError(IntPtr message, out IntPtr error, out IntPtr debug);

    [DllImport("libgstreamer-1.0.so.0", EntryPoint = "gst_mini_object_unref")]
    private static extern void GstMiniObjectUnref(IntPtr message);

    [DllImport("libglib-2.0.so.0", EntryPoint = "g_error_free")]
    private static extern void GErrorFree(IntPtr error);

    [DllImport("libglib-2.0.so.0", EntryPoint = "g_free")]
    private static extern void GFree(IntPtr memory);

    [StructLayout(LayoutKind.Sequential)]
    private struct GError
    {
        public uint Domain;
        public int Code;
        public IntPtr Message;
    }

    private static void ReportError(string context, IntPtr error)
    {
        string? detail = error == IntPtr.Zero ? null
            : Marshal.PtrToStringUTF8(Marshal.PtrToStructure<GError>(error).Message);
        Console.Error.WriteLine(detail == null ? context : $"{context}: {detail}");
    }

    // Only ERROR and EOS pass the filter. EOS has no structure; ERROR carries
    // a GError. Use accessors rather than architecture-specific message offsets.
    private static int? PollTerminalMessage(IntPtr bus, ulong timeout)
    {
        IntPtr message = GstBusTimedPopFiltered(bus, timeout, 3);
        if (message == IntPtr.Zero) return null;
        try
        {
            if (GstMessageGetStructure(message) == IntPtr.Zero)
            {
                Console.WriteLine("Display stream ended");
                return 0;
            }
            GstMessageParseError(message, out IntPtr error, out IntPtr debug);
            try { ReportError("Display stream failed", error); }
            finally
            {
                if (error != IntPtr.Zero) GErrorFree(error);
                if (debug != IntPtr.Zero) GFree(debug);
            }
            return 7;
        }
        finally { GstMiniObjectUnref(message); }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct BitrateControl
    {
        public uint Id;
        public uint Value;
    }

    [DllImport("libvideo-encoder.so", EntryPoint = "ppi_video_encoder_set_bitrate", SetLastError = true)]
    private static extern int SetEncoderBitrate(ref BitrateControl control);

    private static readonly CancellationTokenSource Stop = new();

    private static int Main(string[] args)
    {
        if (args.Length != 9 || !IPAddress.TryParse(args[0], out var address)
            || address.AddressFamily != System.Net.Sockets.AddressFamily.InterNetwork
            || !int.TryParse(args[1], out int port) || port < 1024 || port > 65535
            || !uint.TryParse(args[2], out uint bitrate) || bitrate < 9_000_000 || bitrate > 30_000_000
            || args[3].Length is < 1 or > 100
            || args[3].Any(c => !((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')
                || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-'))
            || !int.TryParse(args[4], out int width)
            || !int.TryParse(args[5], out int height)
            || !((width == 1920 && height == 1080) || (width == 1280 && height == 720))
            || !int.TryParse(args[6], out int fps) || fps is not (30 or 60)
            || args[7] is not ("0" or "1")
            || !int.TryParse(args[8], out int audioKbps) || audioKbps is not (128 or 192 or 256))
        {
            Console.Error.WriteLine("Usage: NativeStream RECEIVER_IPV4 PORT VIDEO_BPS AUDIO_SOURCE WIDTH HEIGHT FPS AUDIO_ENABLED AUDIO_KBPS\nVideo: 9-30 Mbps, 1920x1080 or 1280x720, 30 or 60 fps. Audio: 0/1, 128/192/256 kbps.");
            return 2;
        }

        using var interrupt = PosixSignalRegistration.Create(PosixSignal.SIGINT, context =>
        {
            context.Cancel = true;
            Stop.Cancel();
        });
        using var terminate = PosixSignalRegistration.Create(PosixSignal.SIGTERM, context =>
        {
            context.Cancel = true;
            Stop.Cancel();
        });

        GstInit(IntPtr.Zero, IntPtr.Zero);
        string audio = args[7] == "1"
            ? $"pulsesrc device={args[3]} ! audio/x-raw,rate=48000,channels=2 ! " +
              "audioconvert ! audioresample ! " +
              $"audio/x-raw,rate=48000,channels=2 ! avenc_aac bitrate={audioKbps * 1000} ! " +
              "aacparse ! queue ! mux. "
            : "";
        string pipeline =
            "smsrcavsource avtype=1 host=localhost port=48819 ! " +
            "smsrcvideoenc drm-type=2 enc-type=0 src-w=1920 src-h=1080 " +
            $"dst-w={width} dst-h={height} frame-rate={fps * 100} bitrate=8000000 ! " +
            "h264parse config-interval=-1 ! queue ! mux. " +
            audio +
            $"mpegtsmux name=mux ! tcpclientsink host={address} port={port}";

        IntPtr element = GstParseLaunch(pipeline, out IntPtr error);
        if (element == IntPtr.Zero || error != IntPtr.Zero)
        {
            ReportError("Could not create the display stream pipeline", error);
            if (error != IntPtr.Zero) GErrorFree(error);
            if (element != IntPtr.Zero) GstObjectUnref(element);
            return 3;
        }
        IntPtr bus = GstElementGetBus(element);
        try
        {
            if (bus == IntPtr.Zero)
            {
                Console.Error.WriteLine("Could not get the display stream message bus");
                return 3;
            }
            if (GstElementSetState(element, 4) == 0)
            {
                Console.Error.WriteLine("Could not start the display stream pipeline");
                return 4;
            }
            int stateResult = GstElementGetState(element, out int state, out _, 5_000_000_000);
            if (stateResult == 0 || state != 4)
            {
                Console.Error.WriteLine("Display stream did not reach PLAYING state");
                return 5;
            }
            for (int i = 0; i < 20 && !Stop.IsCancellationRequested; i++)
            {
                int? terminal = PollTerminalMessage(bus, 100_000_000);
                if (terminal.HasValue) return terminal.Value;
            }
            if (Stop.IsCancellationRequested) return 0;
            var control = new BitrateControl { Id = 0x00a20064, Value = bitrate };
            int result = SetEncoderBitrate(ref control);
            if (result != 0)
            {
                Console.Error.WriteLine($"Could not set video bitrate: result={result} errno={Marshal.GetLastWin32Error()}");
                return 6;
            }
            Console.WriteLine($"Streaming {width}x{height} at {fps} fps, H.264 {bitrate} bps, audio {(args[7] == "1" ? $"AAC {audioKbps} kbps" : "off")}");
            while (!Stop.IsCancellationRequested)
            {
                int? terminal = PollTerminalMessage(bus, 100_000_000);
                if (terminal.HasValue) return terminal.Value;
            }
            return 0;
        }
        finally
        {
            GstElementSetState(element, 1);
            if (bus != IntPtr.Zero) GstObjectUnref(bus);
            GstObjectUnref(element);
        }
    }
}
