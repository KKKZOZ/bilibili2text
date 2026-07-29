from pathlib import Path


def test_rag_streaming_proxy_allows_long_idle_intervals() -> None:
    template = Path("docker/nginx.compose.conf.template").read_text(encoding="utf-8")

    assert "proxy_read_timeout 600s;" in template
    assert "proxy_buffering off;" in template
