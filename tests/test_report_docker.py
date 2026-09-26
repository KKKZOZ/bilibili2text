"""Opt-in real Pi smoke test against a synthetic local model (no paid API calls)."""

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread

import pytest

from b2t.config import ReportRuntimeConfig, create_app_config
from b2t.report.generate import generate_report
from b2t.report.options import ReportOptions

pytestmark = pytest.mark.skipif(
    os.environ.get("B2T_TEST_PI_DOCKER") != "1", reason="requires built Pi Docker image"
)


@pytest.mark.parametrize("network", ["bridge", "host"])
def test_real_pi_concurrent_user_credentials_and_tool_delivery(
    tmp_path, monkeypatch, network
):
    monkeypatch.delenv("B2T_REPORT_NETWORK", raising=False)
    monkeypatch.setenv("B2T_REPORT_RUNTIME", "docker")
    monkeypatch.setenv("B2T_WEB_UI_MODE", "open-public")
    gateway = subprocess.check_output(
        [
            "docker",
            "network",
            "inspect",
            "bridge",
            "--format",
            "{{(index .IPAM.Config 0).Gateway}}",
        ],
        text=True,
    ).strip()
    if network == "host":
        gateway = "127.0.0.1"
    calls = {}
    lock = Lock()

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            key = self.headers.get("Authorization", "")
            with lock:
                calls.setdefault(key, []).append(request)
            completed = any(m.get("role") == "tool" for m in request["messages"])
            content = '<html><head><title>Fixture</title></head><body><p data-source-units="u000001">Synthetic report</p></body></html>'
            delta = (
                {"role": "assistant", "content": "Report written."}
                if completed
                else {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "write-report",
                            "type": "function",
                            "function": {
                                "name": "write",
                                "arguments": json.dumps(
                                    {"path": "report.html", "content": content}
                                ),
                            },
                        }
                    ],
                }
            )
            chunks = [
                {
                    "id": "fixture",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": request["model"],
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                },
                {
                    "id": "fixture",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": request["model"],
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop" if completed else "tool_calls",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "total_tokens": 150,
                    },
                },
            ]
            body = (
                "".join(f"data: {json.dumps(c)}\n\n" for c in chunks)
                + "data: [DONE]\n\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body.encode())))
            self.end_headers()
            self.wfile.write(body.encode())

    server = ThreadingHTTPServer(("0.0.0.0", 0), Model)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def generate(index):
        source = tmp_path / f"source-{index}.md"
        source.write_text("Synthetic source.")
        config = create_app_config(
            summarize_provider="openai_compatible",
            summarize_model=f"fixture-{index}",
            summarize_api_key=f"test-user-{index}",
            summarize_base_url=f"http://{gateway}:{server.server_port}/v1",
        )
        config = replace(config, report=ReportRuntimeConfig(docker_network=network))
        return generate_report(source, config, options=ReportOptions(mode="brief"))

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outputs = list(executor.map(generate, [1, 2]))
        assert len(calls) == 2
        for index, output in enumerate(outputs, 1):
            assert "Synthetic report" in Path(output).read_text()
            assert "test-user-" not in Path(output).read_text()
            requests = calls[f"Bearer test-user-{index}"]
            assert len(requests) == 2
            assert all(r["model"] == f"fixture-{index}" for r in requests)
            assert any(m.get("role") == "tool" for m in requests[-1]["messages"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
