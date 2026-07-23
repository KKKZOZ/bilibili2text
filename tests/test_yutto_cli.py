from b2t.download.yutto_cli import (
    extract_bilibili_page,
    extract_bilibili_page_from_target_id,
    extract_bilibili_target_id,
    normalize_bilibili_target,
)


def test_normalize_bilibili_target_preserves_multipart_page() -> None:
    target = normalize_bilibili_target(
        "https://www.bilibili.com/video/BV1ua4y1Y7yX"
        "?vd_source=0913c1e4dedf4378c61d39741a2d6190&p=3"
    )

    assert target == "https://www.bilibili.com/video/BV1ua4y1Y7yX?p=3"


def test_normalize_bilibili_target_removes_tracking_query() -> None:
    target = normalize_bilibili_target(
        "https://www.bilibili.com/video/BV1ua4y1Y7yX/"
        "?vd_source=0913c1e4dedf4378c61d39741a2d6190"
    )

    assert target == "https://www.bilibili.com/video/BV1ua4y1Y7yX"


def test_bilibili_page_and_target_id_distinguish_multipart_video() -> None:
    target = "https://www.bilibili.com/video/BV1ua4y1Y7yX?p=5"

    assert extract_bilibili_page(target) == 5
    assert extract_bilibili_target_id(target) == "BV1ua4y1Y7yX_p5"
    assert extract_bilibili_page_from_target_id("BV1ua4y1Y7yX_p5-abc123") == 5


def test_first_page_uses_the_base_video_identity() -> None:
    target = "https://www.bilibili.com/video/BV1ua4y1Y7yX?p=1"

    assert normalize_bilibili_target(target).endswith("?p=1")
    assert extract_bilibili_target_id(target) == "BV1ua4y1Y7yX"


def test_invalid_page_is_not_preserved() -> None:
    target = "https://www.bilibili.com/video/BV1ua4y1Y7yX?p=invalid"

    assert extract_bilibili_page(target) is None
    assert normalize_bilibili_target(target) == (
        "https://www.bilibili.com/video/BV1ua4y1Y7yX"
    )
