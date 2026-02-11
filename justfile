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
