import json

from b2t.download.xiaoyuzhou import XiaoyuzhouDownloader


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


def _page_html(episode: dict, schema: dict | None = None) -> str:
    next_data = {"props": {"pageProps": {"episode": episode}}}
    schema_html = ""
    if schema is not None:
        schema_html = (
            '<script name="schema:podcast-show" type="application/ld+json">'
            f"{json.dumps(schema, ensure_ascii=False)}"
            "</script>"
        )
    return (
        "<html><head>"
        f"{schema_html}"
        "</head><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(next_data, ensure_ascii=False)}"
        "</script>"
        "</body></html>"
    )


def test_fetch_metadata_reads_xiaoyuzhou_current_fields(monkeypatch) -> None:
    html = _page_html(
        {
            "eid": "episode-1",
            "title": "E191 AI四大半导体新方向",
            "description": "节目介绍",
            "duration": 4218,
            "pubDate": "2026-07-19T23:54:05.387Z",
            "podcast": {
                "title": "投资实战派",
                "author": "wong永庆",
            },
            "enclosure": {
                "url": "https://media.example.test/audio.m4a",
            },
        }
    )

    monkeypatch.setattr(
        "b2t.download.xiaoyuzhou.httpx.get",
        lambda *args, **kwargs: _FakeResponse(html),
    )

    metadata = XiaoyuzhouDownloader().fetch_metadata(
        "https://www.xiaoyuzhoufm.com/episode/episode-1"
    )

    assert metadata.title == "投资实战派 — E191 AI四大半导体新方向"
    assert metadata.author == "wong永庆"
    assert metadata.pubdate == "2026-07-19 23:54:05"
    assert metadata.pubdate_timestamp > 0


def test_fetch_metadata_falls_back_to_podcaster_and_schema_publish_time(
    monkeypatch,
) -> None:
    html = _page_html(
        {
            "eid": "episode-2",
            "title": "多人对话节目",
            "podcast": {
                "title": "投资实战派",
                "podcasters": [{"nickname": "大卫", "bio": "主持人"}],
            },
            "media": {
                "source": {
                    "url": "https://media.example.test/audio.m4a",
                },
            },
        },
        schema={"datePublished": "2026-07-20T01:02:03.000Z"},
    )

    monkeypatch.setattr(
        "b2t.download.xiaoyuzhou.httpx.get",
        lambda *args, **kwargs: _FakeResponse(html),
    )

    metadata = XiaoyuzhouDownloader().fetch_metadata("xiaoyuzhou_episode-2")

    assert metadata.title == "投资实战派 — 多人对话节目"
    assert metadata.author == "大卫"
    assert metadata.pubdate == "2026-07-20 01:02:03"
    assert metadata.extra["podcasters"] == [{"nickname": "大卫", "bio": "主持人"}]
