import asyncio

from b2t.download import metadata as metadata_module
from b2t.download.bilibili_categories import (
    get_bilibili_parent_tid,
    get_bilibili_parent_tname,
    get_bilibili_tname,
)


def test_bilibili_category_mapping_uses_explicit_parent_relationship() -> None:
    assert get_bilibili_tname(207) == "财经商业"
    assert get_bilibili_parent_tid(207) == 36
    assert get_bilibili_parent_tname(207) == "知识"
    assert get_bilibili_tname(174) == "直播回放"
    assert get_bilibili_parent_tname(174) == ""
    assert get_bilibili_tname(999_999) == ""
    assert get_bilibili_parent_tid(999_999) == 0


def test_get_video_metadata_saves_tid_and_resolves_empty_api_tname(
    monkeypatch,
) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "code": 0,
                "data": {
                    "bvid": "BV1Hdgs6ME67",
                    "aid": 117088458968224,
                    "tid": 207,
                    "tname": "",
                    "title": "康师傅控股中报点评",
                    "owner": {"name": "测试UP主", "mid": 123},
                    "pubdate": 0,
                    "desc": "测试简介",
                },
            }

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            pass

        async def get(self, url, *, headers):
            return FakeResponse()

    monkeypatch.setattr(
        metadata_module.httpx,
        "AsyncClient",
        lambda **kwargs: FakeAsyncClient(),
    )

    metadata = asyncio.run(metadata_module.get_video_metadata_async("BV1Hdgs6ME67"))

    assert metadata.tid == 207
    assert metadata.tname == "财经商业"
    assert metadata.parent_tid == 36
    assert metadata.parent_tname == "知识"
