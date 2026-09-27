#!/bin/bash
# Runs on the display after SDB stages and launches this script; no host Bash is required.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
work_dir=$PWD
pid_file="$work_dir/stream.pid"
log_file="$work_dir/stream.log"
action=${1:-}

running_pid() {
    [ -r "$pid_file" ] || return 1
    read -r stream_pid start_time < "$pid_file"
    [[ "$stream_pid" =~ ^[0-9]+$ && "$start_time" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$stream_pid" 2>/dev/null || return 1
    [ "$(awk '{print $22}' "/proc/$stream_pid/stat" 2>/dev/null)" = "$start_time" ] || return 1
    tr '\0' ' ' < "/proc/$stream_pid/cmdline" | grep -Eq 'name=tizen_obs_video|NativeStream.dll'
}

stop_stream() {
    if running_pid; then
        kill -INT "$stream_pid" 2>/dev/null || true
        for ((attempt=0; attempt<20; attempt++)); do
            running_pid || break
            sleep 0.1
        done
        if running_pid; then kill -TERM "$stream_pid" 2>/dev/null || true; sleep 1; fi
        if running_pid; then printf 'Stream did not stop; inspect logs.\n' >&2; return 1; fi
    fi
    rm -f "$pid_file"
}

case "$action" in
    status)
        if running_pid; then printf 'Stream running (PID %s)\n' "$stream_pid";
        else printf 'Stream stopped\n'; fi
        exit 0 ;;
    logs)
        if [ -f "$log_file" ]; then tail -60 "$log_file";
        else printf 'No stream log yet.\n'; fi
        exit 0 ;;
    stop) stop_stream || exit 1; printf 'Stream stopped\n'; exit 0 ;;
    start|sample|check) ;;
    *) printf 'Unknown action\n' >&2; exit 2 ;;
esac

host=${2:-}; port=${3:-}; video_bps=${4:-}; audio_source=${5:-}
quality_mode=${6:-}; width=${7:-}; height=${8:-}; fps=${9:-}
audio_enabled=${10:-}; audio_kbps=${11:-}; sample_seconds=${12:-}
[[ "$host" =~ ^[0-9.]+$ && "$port" =~ ^[0-9]+$ && "$video_bps" =~ ^[0-9]+$ &&
   "$audio_source" =~ ^[A-Za-z0-9_.-]+$ ]] || { printf 'Invalid stream arguments\n' >&2; exit 2; }
[ "$port" -ge 1024 ] && [ "$port" -le 65535 ] || exit 2
case "$width:$height" in 1920:1080|1280:720) ;; *) exit 2 ;; esac
case "$fps" in 30|60) ;; *) exit 2 ;; esac
case "$audio_enabled" in 0|1) ;; *) exit 2 ;; esac
case "$audio_kbps" in 128|192|256) ;; *) exit 2 ;; esac
case "$quality_mode" in
    standard) [ "$video_bps" -ge 1000000 ] && [ "$video_bps" -le 8000000 ] || exit 2 ;;
    high) [ "$video_bps" -ge 9000000 ] && [ "$video_bps" -le 30000000 ] || exit 2 ;;
    *) exit 2 ;;
esac

if [ "$action" = check ]; then
    for executable in gst-launch-1.0 gst-inspect-1.0 setsid; do
        command -v "$executable" >/dev/null || { printf 'Missing %s\n' "$executable" >&2; exit 1; }
    done
    plugins=(smsrcavsource smsrcvideoenc h264parse queue mpegtsmux tcpclientsink)
    if [ "$audio_enabled" = 1 ]; then plugins+=(pulsesrc audioconvert audioresample avenc_aac aacparse); fi
    for plugin in "${plugins[@]}"; do
        gst-inspect-1.0 "$plugin" >/dev/null 2>&1 || { printf 'Missing media component: %s\n' "$plugin" >&2; exit 1; }
    done
    if [ "$quality_mode" = high ]; then
        runtime_found=false
        for runtime in /usr/share/dotnet/shared/Microsoft.NETCore.App/6.*; do
            if [ -f "$runtime/libcoreclr.so" ]; then runtime_found=true; break; fi
        done
        [ -x /usr/bin/dotnet ] && $runtime_found || {
            printf 'High mode requires the display .NET 6 runtime\n' >&2; exit 1;
        }
    fi
    printf 'SDB launch and media components available. Run sample to verify capture.\n'
    exit 0
fi
if [ "$action" = sample ]; then
    [[ "$sample_seconds" =~ ^[0-9]+$ ]] && [ "$sample_seconds" -ge 1 ] && [ "$sample_seconds" -le 30 ] || exit 2
fi

if ! mkdir "$work_dir/launch.lock" 2>/dev/null; then
    printf 'Another start/sample is in progress.\n' >&2; exit 1
fi
trap 'rmdir "$work_dir/launch.lock" 2>/dev/null || true' EXIT
if running_pid; then
    printf 'Stream already running; stop it before changing settings or taking a sample.\n' >&2; exit 1
fi

pipeline=(gst-launch-1.0 -e -q
    smsrcavsource avtype=1 host=localhost port=48819
    '!' smsrcvideoenc name=tizen_obs_video drm-type=2 enc-type=0 src-w=1920 src-h=1080
        dst-w="$width" dst-h="$height" frame-rate="$((fps * 100))" bitrate="$video_bps"
    '!' h264parse config-interval=-1 '!' queue '!' mux.)
if [ "$audio_enabled" = 1 ]; then
    pipeline+=(pulsesrc device="$audio_source"
        '!' 'audio/x-raw,rate=48000,channels=2'
        '!' audioconvert '!' audioresample
        '!' 'audio/x-raw,rate=48000,channels=2'
        '!' avenc_aac bitrate="$((audio_kbps * 1000))" '!' aacparse '!' queue '!' mux.)
fi
pipeline+=(mpegtsmux name=mux '!' tcpclientsink host="$host" port="$port")
if [ "$quality_mode" = high ]; then
    pipeline=(/usr/bin/dotnet "$work_dir/NativeStream.dll"
        "$host" "$port" "$video_bps" "$audio_source" "$width" "$height" "$fps" "$audio_enabled" "$audio_kbps")
fi

setsid "${pipeline[@]}" > "$log_file" 2>&1 < /dev/null 3>&- &
stream_pid=$!
start_time=$(awk '{print $22}' "/proc/$stream_pid/stat" 2>/dev/null) || true
printf '%s %s\n' "$stream_pid" "$start_time" > "$pid_file"
if [ "$action" = start ]; then
    sleep 1
    if ! running_pid; then tail -20 "$log_file" >&2; rm -f "$pid_file"; exit 1; fi
    printf 'Display encoder started. Confirm video in your receiver.\n'
    exit 0
fi

trap 'stop_stream; rmdir "$work_dir/launch.lock" 2>/dev/null || true' EXIT
trap 'exit 130' INT TERM
for ((elapsed=0; elapsed<sample_seconds; elapsed++)); do
    sleep 1
    if ! running_pid; then tail -20 "$log_file" >&2; exit 1; fi
done
stop_stream || exit 1
wait "$stream_pid" 2>/dev/null || true
printf 'Sample finished\n'
