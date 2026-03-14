set shell := ["bash", "-cu"]

@default:
    just --list

alias t := transcode
alias m := to-mp3
alias c := clip

transcode file:
    @cd "{{invocation_directory()}}"; \
    in="{{file}}"; \
    if [[ ! -f "$in" ]]; then \
      echo "File not found: $in" >&2; exit 1; \
    fi; \
    out="${in%.*}.wav"; \
    ffmpeg -hide_banner -y -i "$in" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$out"; \
    echo "OK -> $out"

# Create a clip of specified duration from audio file
clip file duration:
    @cd "{{invocation_directory()}}"; \
    in="{{file}}"; \
    dur="{{duration}}"; \
    if [[ ! -f "$in" ]]; then \
      echo "File not found: $in" >&2; exit 1; \
    fi; \
    if ! [[ "$dur" =~ ^[0-9]+$ ]]; then \
      echo "Duration must be a number (in seconds)" >&2; exit 1; \
    fi; \
    base="${in%.*}"; \
    ext="${in##*.}"; \
    out="${base}-${dur}s.${ext}"; \
    echo "Creating ${dur}s clip from $in..."; \
    ffmpeg -hide_banner -y -i "$in" -t "$dur" -c copy "$out"; \
    echo "OK -> $out"

# Convert audio to MP3 (mono, preserving original sample rate and bitrate)
to-mp3 file:
    @cd "{{invocation_directory()}}"; \
    in="{{file}}"; \
    if [[ ! -f "$in" ]]; then \
      echo "File not found: $in" >&2; exit 1; \
    fi; \
    out="${in%.*}.mp3"; \
    echo "Detecting audio parameters..."; \
    bitrate=$(ffprobe -v error -select_streams a:0 -show_entries stream=bit_rate -of default=noprint_wrappers=1:nokey=1 "$in"); \
    samplerate=$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of default=noprint_wrappers=1:nokey=1 "$in"); \
    if [[ -z "$bitrate" || "$bitrate" == "N/A" ]]; then \
      echo "Warning: Could not detect bitrate, using 64k as default"; \
      bitrate=64000; \
    fi; \
    bitrate_k=$((bitrate / 1000)); \
    echo "Input: ${samplerate}Hz, ${bitrate_k}kb/s"; \
    echo "Converting to MP3 (mono, ${samplerate}Hz, ${bitrate_k}kb/s)..."; \
    ffmpeg -hide_banner -y -i "$in" -vn -ac 1 -ar "$samplerate" -c:a libmp3lame -b:a "${bitrate_k}k" "$out"; \
    echo "OK -> $out"

# Start or stop web backend/frontend services.
# Usage:
#   just web on
#   just web off
#   just web on open-public
web action mode='default':
    @cd "{{invocation_directory()}}"; \
    action="{{action}}"; \
    mode="{{mode}}"; \
    if [[ "$mode" != "default" && "$mode" != "open-public" ]]; then \
      echo "Unknown mode: $mode. Use: default|open-public" >&2; \
      exit 1; \
    fi; \
    frontend_port=6010; \
    backend_port=8000; \
    frontend_pid="$(lsof -tiTCP:${frontend_port} -sTCP:LISTEN || true)"; \
    backend_pid="$(lsof -tiTCP:${backend_port} -sTCP:LISTEN || true)"; \
    case "$action" in \
      on) \
        if [[ -n "$frontend_pid" && -n "$backend_pid" ]]; then \
          echo "web is running (frontend:${frontend_port} backend:${backend_port}, mode:${mode})"; \
          exit 0; \
        fi; \
        mkdir -p web-ui/logs; \
        if [[ -z "$backend_pid" ]]; then \
          echo "Starting backend on :${backend_port} (mode:${mode}) ..."; \
          if [[ -x ".venv/bin/uvicorn" ]]; then \
            nohup env PYTHONPATH="$PWD" B2T_WEB_UI_MODE="$mode" .venv/bin/uvicorn backend.main:app --app-dir web-ui --host 0.0.0.0 --port "${backend_port}" > web-ui/logs/backend.log 2>&1 & \
          elif command -v uv >/dev/null 2>&1; then \
            nohup env PYTHONPATH="$PWD" B2T_WEB_UI_MODE="$mode" uv run uvicorn backend.main:app --app-dir web-ui --host 0.0.0.0 --port "${backend_port}" > web-ui/logs/backend.log 2>&1 & \
          else \
            echo "Cannot find uvicorn: need .venv/bin/uvicorn or uv in PATH" >&2; \
            exit 1; \
          fi \
        else \
          echo "Backend already running on :${backend_port} (pid: ${backend_pid})"; \
        fi; \
        if [[ -z "$frontend_pid" ]]; then \
          echo "Starting frontend on :${frontend_port} (mode:${mode}) ..."; \
          nohup bash -lc 'cd web-ui/frontend && VITE_B2T_WEB_UI_MODE='"'"'"$mode"'"'"' bun run dev' > web-ui/logs/frontend.log 2>&1 & \
        else \
          echo "Frontend already running on :${frontend_port} (pid: ${frontend_pid})"; \
        fi; \
        for _ in {1..15}; do \
          frontend_pid="$(lsof -tiTCP:${frontend_port} -sTCP:LISTEN || true)"; \
          backend_pid="$(lsof -tiTCP:${backend_port} -sTCP:LISTEN || true)"; \
          if [[ -n "$frontend_pid" && -n "$backend_pid" ]]; then \
            break; \
          fi; \
          sleep 1; \
        done; \
        if [[ -n "$frontend_pid" && -n "$backend_pid" ]]; then \
          echo "web started (frontend:${frontend_port} backend:${backend_port}, mode:${mode})"; \
        else \
          echo "web start failed, check web-ui/logs/frontend.log and web-ui/logs/backend.log" >&2; \
          exit 1; \
        fi \
        ;; \
      off) \
        stopped=0; \
        if [[ -n "$frontend_pid" ]]; then \
          kill ${frontend_pid} 2>/dev/null || true; \
          echo "Stopped frontend on :${frontend_port} (pid: ${frontend_pid})"; \
          stopped=1; \
        fi; \
        if [[ -n "$backend_pid" ]]; then \
          kill ${backend_pid} 2>/dev/null || true; \
          echo "Stopped backend on :${backend_port} (pid: ${backend_pid})"; \
          stopped=1; \
        fi; \
        sleep 1; \
        frontend_pid="$(lsof -tiTCP:${frontend_port} -sTCP:LISTEN || true)"; \
        backend_pid="$(lsof -tiTCP:${backend_port} -sTCP:LISTEN || true)"; \
        if [[ -n "$frontend_pid" ]]; then \
          kill -9 ${frontend_pid} 2>/dev/null || true; \
          echo "Force stopped frontend on :${frontend_port} (pid: ${frontend_pid})"; \
          stopped=1; \
        fi; \
        if [[ -n "$backend_pid" ]]; then \
          kill -9 ${backend_pid} 2>/dev/null || true; \
          echo "Force stopped backend on :${backend_port} (pid: ${backend_pid})"; \
          stopped=1; \
        fi; \
        if [[ "$stopped" -eq 0 ]]; then \
          echo "web is not running"; \
        fi \
        ;; \
      *) \
        echo "Unknown action: $action. Use: on|off" >&2; \
        exit 1 \
        ;; \
    esac

# Start or stop web in open-public mode.
# Usage:
#   just web-open-public on
#   just web-open-public off
web-open-public action:
    @cd "{{invocation_directory()}}"; \
    just web "{{action}}" open-public
