from __future__ import annotations

from b2t.download.comments import (
    BilibiliComment,
    BilibiliCommentBundle,
    comments_to_markdown,
    count_comment_replies,
    count_up_replies,
    fetch_bilibili_comments,
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class FakeAsyncClient:
    requests = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, params=None):
        params = dict(params or {})
        self.requests.append((url, params))
        if url.endswith("/reply/reply"):
            return FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "replies": [
                            {
                                "rpid": 2001,
                                "member": {"mid": "42", "uname": "UP主"},
                                "content": {"message": "置顶补充观点"},
                                "like": 9,
                                "ctime": 1780000000,
                            },
                            {
                                "rpid": 2002,
                                "member": {"mid": "100", "uname": "观众B"},
                                "content": {"message": "子评论观点"},
                                "like": 3,
                                "ctime": 1780000001,
                            },
                        ]
                    },
                }
            )
        return FakeResponse(
            {
                "code": 0,
                "data": {
                    "page": {"count": 100},
                    "replies": [
                        {
                            "rpid": 1001,
                            "member": {"mid": "99", "uname": "观众A"},
                            "content": {"message": "主评论观点"},
                            "like": 30,
                            "ctime": 1780000002,
                            "rcount": 2,
                        }
                    ],
                },
            }
        )


def test_fetch_bilibili_comments_fetches_child_replies(monkeypatch) -> None:
    FakeAsyncClient.requests = []
    monkeypatch.setattr("b2t.download.comments.httpx.AsyncClient", FakeAsyncClient)

    bundle = fetch_bilibili_comments(
        aid=123,
        bvid="BV1ABcsztEcY",
        up_uid=42,
        limit=1,
        cookie="SESSDATA=test",
    )

    assert bundle.fetched_count == 1
    assert bundle.total_count == 100
    assert len(bundle.comments[0].replies) == 2
    assert bundle.comments[0].replies[0].is_up_reply is True
    assert count_comment_replies(bundle) == 2
    assert count_up_replies(bundle) == 1
    assert FakeAsyncClient.requests[0][1]["sort"] == 1
    assert FakeAsyncClient.requests[0][1]["ps"] == 1
    assert FakeAsyncClient.requests[1][1]["root"] == 1001
    assert FakeAsyncClient.requests[1][1]["ps"] == 20


def test_comments_markdown_bolds_up_replies() -> None:
    bundle = BilibiliCommentBundle(
        aid=123,
        bvid="BV1ABcsztEcY",
        fetched_count=1,
        requested_limit=1,
        total_count=1,
        sort="hot",
        comments=(
            BilibiliComment(
                rpid=1001,
                author="观众A",
                author_uid=99,
                message="主评论观点",
                like=30,
                ctime="",
                ctime_timestamp=0,
                replies=(
                    BilibiliComment(
                        rpid=2001,
                        author="UP主",
                        author_uid=42,
                        message="UP 的回复",
                        like=5,
                        ctime="",
                        ctime_timestamp=0,
                        is_up_reply=True,
                    ),
                ),
            ),
        ),
    )

    markdown = comments_to_markdown(bundle)

    assert "**UP主回复** UP主" in markdown
    assert "**UP 的回复**" in markdown
