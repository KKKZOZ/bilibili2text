from pathlib import Path


def test_rag_streaming_proxy_allows_long_idle_intervals() -> None:
    template = Path("docker/nginx.compose.conf.template").read_text(encoding="utf-8")

    assert "proxy_read_timeout 600s;" in template
    assert "proxy_buffering off;" in template


def test_compose_uses_the_configured_timezone_for_both_services() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "TZ: ${B2T_TIMEZONE:-Asia/Shanghai}" in compose
    assert compose.count("TZ: ${B2T_TIMEZONE:-Asia/Shanghai}") == 2
    assert "B2T_TIMEZONE=Asia/Shanghai" in env_example


def test_runtime_images_install_timezone_data() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "ffmpeg pandoc tzdata" in dockerfile
    assert "RUN apk add --no-cache tzdata" in dockerfile
