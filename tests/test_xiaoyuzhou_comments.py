from __future__ import annotations

import json

from b2t.download.comments import (
    comments_to_markdown,
    count_comment_replies,
    count_up_replies,
    fetch_xiaoyuzhou_comments,
)


class _FakeResponse:
    def __init__(self, payload=None, text: str = "") -> None:
        self._payload = payload
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def _page_html(comments: list[dict], comment_count: int = 480) -> str:
    next_data = {
        "props": {
            "pageProps": {
                "episode": {"commentCount": comment_count},
                "comments": comments,
            }
        }
    }
    return (
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(next_data, ensure_ascii=False)}"
        "</script>"
    )


def test_fetch_xiaoyuzhou_comments_reads_embedded_comments(monkeypatch) -> None:
    html = _page_html(
        [
            {
                "id": "comment-1",
                "author": {"uid": "user-1", "nickname": "听众"},
                "text": "主评论观点",
                "likeCount": 12,
                "createdAt": "2026-05-18T10:00:00.000Z",
                "replyCount": 1,
                "threadReplyCount": 1,
                "replies": [
                    {
                        "id": "reply-1",
                        "author": {"uid": "podcaster-1", "nickname": "主播"},
                        "authorAssociation": "PODCASTER",
                        "podcastAssociation": "ORIGINAL",
                        "text": "主播补充观点",
                        "likeCount": 5,
                        "createdAt": "2026-05-18T11:00:00.000Z",
                    }
                ],
            }
        ]
    )

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url):
            return _FakeResponse(text=html)

    monkeypatch.delenv("XIAOYUZHOU_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("XIAOYUZHOU_DEVICE_ID", raising=False)
    monkeypatch.setattr("b2t.download.comments.httpx.AsyncClient", FakeAsyncClient)

    bundle = fetch_xiaoyuzhou_comments(episode_id="6a0a7365e1eb34a93997ffa2")

    assert bundle.platform == "xiaoyuzhou"
    assert bundle.source == "embedded_page"
    assert bundle.fetched_count == 1
    assert bundle.total_count == 480
    assert count_comment_replies(bundle) == 1
    assert count_up_replies(bundle) == 1
    markdown = comments_to_markdown(bundle)
    assert "# 小宇宙 精选评论" in markdown
    assert "**UP主回复** 主播" in markdown
    assert "**主播补充观点**" in markdown


def test_fetch_xiaoyuzhou_comments_fetches_api_child_replies(monkeypatch) -> None:
    class FakeAsyncClient:
        requests: list[tuple[str, dict]] = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json=None, headers=None):
            self.requests.append((url, dict(json or {})))
            if url.endswith("/comment/list-reply"):
                return _FakeResponse(
                    {
                        "data": {
                            "comments": [
                                {
                                    "id": "reply-1",
                                    "author": {
                                        "uid": "podcaster-1",
                                        "nickname": "主播",
                                    },
                                    "authorAssociation": "PODCASTER",
                                    "podcastAssociation": "ORIGINAL",
                                    "text": "主播补充观点",
                                    "likeCount": 5,
                                    "createdAt": "2026-05-18T11:00:00.000Z",
                                },
                                {
                                    "id": "reply-2",
                                    "author": {"uid": "user-2", "nickname": "听众B"},
                                    "text": "完整子评论",
                                    "likeCount": 1,
                                    "createdAt": "2026-05-18T12:00:00.000Z",
                                },
                            ]
                        }
                    }
                )
            return _FakeResponse(
                {
                    "data": {
                        "comments": [
                            {
                                "id": "comment-1",
                                "author": {"uid": "user-1", "nickname": "听众A"},
                                "text": "主评论观点",
                                "likeCount": 9,
                                "createdAt": "2026-05-18T10:00:00.000Z",
                                "replies": [],
                            }
                        ]
                    }
                }
            )

    monkeypatch.setattr("b2t.download.comments.httpx.AsyncClient", FakeAsyncClient)

    bundle = fetch_xiaoyuzhou_comments(
        episode_id="6a0a7365e1eb34a93997ffa2",
        limit=1,
        refresh_token="test-token",
    )

    assert bundle.source == "api"
    assert bundle.fetched_count == 1
    assert len(bundle.comments[0].replies) == 2
    assert bundle.comments[0].replies[0].is_up_reply is True
    assert FakeAsyncClient.requests[0][0].endswith("/comment/list-primary")
    assert FakeAsyncClient.requests[1][0].endswith("/comment/list-reply")
    assert FakeAsyncClient.requests[1][1]["thread"] == "comment-1"
