# bilibili-to-text

Convert Bilibili videos into structured text, Markdown transcripts, and LLM-generated summaries.

`bilibili-to-text` provides both a command-line pipeline and a Web UI for downloading Bilibili audio, transcribing speech, converting transcripts to Markdown/TXT, generating summaries, storing artifacts, and optionally monitoring creators for new videos.

## Features

- Download audio from Bilibili videos with `yutto`
- Transcribe audio with configurable STT providers:
  - Alibaba DashScope / Qwen ASR
  - Groq Whisper-compatible ASR
- Generate cleaned Markdown transcripts from STT JSON output
- Summarize transcripts with configurable LiteLLM-compatible model profiles
- Store generated artifacts locally, in MinIO, or in Alibaba Cloud OSS
- Run a FastAPI + Vue Web UI for browser-based processing
- Query indexed transcript history with the optional RAG module
- Monitor Bilibili creators and send Feishu notifications for new videos
- Export and format Markdown-derived outputs, including table-oriented PDF/PNG workflows

## Project Structure

```text
.
|-- b2t/                  # Core Python package and CLI pipeline
|   |-- download/         # Bilibili/yutto download integration
|   |-- stt/              # Speech-to-text providers
|   |-- converter/        # JSON, Markdown, TXT, PDF, PNG converters
|   |-- summarize/        # LLM summary generation
|   |-- storage/          # Local, MinIO, and Alibaba Cloud OSS backends
|   |-- rag/              # ChromaDB-based retrieval utilities
|   `-- monitor/          # Bilibili creator monitoring and Feishu notifications
|-- web-ui/               # FastAPI backend and Vue/Vite frontend
|-- tests/                # Pytest test suite
|-- scripts/              # Utility and maintenance scripts
|-- config.toml.example   # Main configuration template
|-- summary_presets.toml  # Summary prompt presets
|-- justfile              # Common local commands
`-- Dockerfile            # Single-container Web UI deployment
```

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for Python dependency management
- [Bun](https://bun.sh/) for the Web UI frontend
- `ffmpeg` for audio processing
- `pandoc` for Markdown/TXT/PDF-related conversion workflows
- Chromium installed through Playwright when using PNG/PDF rendering helpers:

```bash
uv run playwright install chromium
```

## Installation

Clone the repository and install Python dependencies:

```bash
git clone <repo-url>
cd bilibili-to-text
uv sync
```

Install frontend dependencies if you plan to run the Web UI:

```bash
cd web-ui/frontend
bun install
```

## Configuration

Create a local configuration file from the template:

```bash
cp config.toml.example config.toml
```

Then edit `config.toml` with the providers and credentials you need. The main sections are:

- `[download]`: audio quality, output directory, and local database directory
- `[storage]`: artifact storage backend, either `local`, `minio`, or `alicloud`
- `[stt]`: active speech-to-text profile
- `[summarize]`: active summary model profile and default summary preset
- `[rag]`: optional ChromaDB-based transcript retrieval
- `[feishu]`: optional notification settings
- `[bilibili]`: optional Bilibili cookies for authenticated requests
- `[monitor]`: optional creator monitoring configuration

The pipeline also reads summary prompt presets from `summary_presets.toml` by default. You can point `[summarize].presets_file` at another TOML file if you maintain custom presets.

For Qwen ASR, the STT storage backend must provide a public URL for uploaded audio, so use MinIO or Alibaba Cloud OSS for `storage_profile` or `storage.backend`.

## CLI Usage

Run the full pipeline for a Bilibili video:

```bash
uv run b2t "https://www.bilibili.com/video/BVxxxxxxxxxx"
```

Useful options:

```bash
uv run b2t "https://www.bilibili.com/video/BVxxxxxxxxxx" \
  --config config.toml \
  --output ./transcriptions \
  --summary-preset timeline_merge \
  --summary-profile bailian-main
```

Skip LLM summarization:

```bash
uv run b2t "https://www.bilibili.com/video/BVxxxxxxxxxx" --no-summary
```

Run the interactive CLI:

```bash
uv run b2t
```

Run the Bilibili creator monitor once:

```bash
uv run b2t monitor --once
```

Run the monitor continuously:

```bash
uv run b2t monitor
```

## Web UI

The Web UI contains a FastAPI backend and a Vue/Vite frontend. It uses the same root-level `config.toml` and `summary_presets.toml` files as the CLI.

Start both services from the repository root:

```bash
just web on
```

Open the frontend at:

```text
http://127.0.0.1:6010
```

Stop the services:

```bash
just web off
```

You can also start the public-safe mode:

```bash
just web-open-public on
```

In `open-public` mode, uploaded audio, destructive history operations, and local project API keys are disabled. Users must provide their own DashScope API key in the Web UI.

For manual backend/frontend commands and API details, see [web-ui/README.md](web-ui/README.md).

## Docker

Build the single-container Web UI image:

```bash
docker build -t bilibili-to-text:latest .
```

Run it with a mounted configuration file and output directory:

```bash
docker run --rm \
  -p 6010:6010 \
  -v "$(pwd)/config.toml:/app/config.toml:ro" \
  -v "$(pwd)/transcriptions:/app/transcriptions" \
  bilibili-to-text:latest
```

Then open:

```text
http://127.0.0.1:6010
```

The container starts the FastAPI backend internally and serves the frontend through Nginx.

## Development

Run tests:

```bash
uv run pytest
```

Run the backend manually:

```bash
uv run uvicorn backend.main:app --app-dir web-ui --host 0.0.0.0 --port 8000 --reload
```

Run the frontend manually:

```bash
cd web-ui/frontend
bun run dev
```

Build the frontend:

```bash
cd web-ui/frontend
bun run build
```

## Generated Data

Typical local runtime outputs include:

- `transcriptions/`: audio, transcript, summary, and derived artifact files
- `db_data/`: CLI/Web UI history and monitor state
- `chroma_data/`: optional RAG vector database
- `web-ui/logs/`: local Web UI service logs

These files may contain transcripts, summaries, API-derived metadata, and credentials in generated logs. Do not commit local runtime data or secrets.

## License

No license file is currently included. Add a license before publishing or redistributing this project as open source.
