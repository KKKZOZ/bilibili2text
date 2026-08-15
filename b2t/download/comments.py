"""Fetch and format platform comments."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from b2t.download.metadata import VideoMetadata
from b2t.download.platform import Platform
from b2t.download.url_detect import extract_platform_id

logger = logging.getLogger(__name__)

BILIBILI_VIDEO_COMMENT_TYPE = 1
DEFAULT_COMMENT_LIMIT = 200
MAX_PAGE_SIZE = 20
XIAOYUZHOU_PAGE_SIZE = 20
BILIBILI_WBI_WEB_LOCATION = 1315875
BILIBILI_MIXIN_KEY_ENC_TAB = (
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
)
XIAOYUZHOU_COMMENT_API_URL = "https://api.xiaoyuzhoufm.com/v1/comment/list-primary"
XIAOYUZHOU_REPLY_API_URL = "https://api.xiaoyuzhoufm.com/v1/comment/list-reply"
_NEXT_DATA_PATTERN = re.compile(
    r'<script\s+id="__NEXT_DATA__"\s+type="application/json">\s*(.*?)\s*</script>',
    re.DOTALL,
)
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class PlatformComment:
    rpid: int | str
    author: str
    author_uid: int | str
    message: str
    like: int
    ctime: str
    ctime_timestamp: int
    is_up_reply: bool = False
    replies: tuple["PlatformComment", ...] = ()


@dataclass(frozen=True)
class PlatformCommentBundle:
    bvid: str
    fetched_count: int
    requested_limit: int | None
    total_count: int
    sort: str
    comments: tuple[PlatformComment, ...] = field(default_factory=tuple)
    aid: int = 0
    platform: str = Platform.BILIBILI.value
    source: str = "api"


BilibiliComment = PlatformComment
BilibiliCommentBundle = PlatformCommentBundle


def comment_platform_from_metadata(metadata: VideoMetadata) -> Platform | None:
    if metadata.bvid.startswith("BV") and metadata.aid > 0:
        return Platform.BILIBILI
    if metadata.bvid.startswith(f"{Platform.XIAOYUZHOU.value}_"):
        return Platform.XIAOYUZHOU
    return None


def comment_platform_label(platform: Platform) -> str:
    return {
        Platform.BILIBILI: "B 站",
        Platform.XIAOYUZHOU: "小宇宙",
    }.get(platform, platform.value)


def count_comment_replies(bundle: PlatformCommentBundle) -> int:
    """Return the number of downloaded child replies."""
    return sum(len(comment.replies) for comment in bundle.comments)


def count_up_replies(bundle: PlatformCommentBundle) -> int:
    """Return the number of downloaded replies authored by the uploader."""
    return sum(
        int(comment.is_up_reply)
        + sum(int(reply.is_up_reply) for reply in comment.replies)
        for comment in bundle.comments
    )


def _headers(cookie: str = "") -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com",
        "Origin": "https://www.bilibili.com",
    }
    if cookie.strip():
        headers["Cookie"] = cookie.strip()
    return headers


def _xiaoyuzhou_headers(
    *,
    refresh_token: str = "",
    device_id: str = "",
) -> dict[str, str]:
    headers = {
        "User-Agent": _USER_AGENT,
        "Referer": "https://www.xiaoyuzhoufm.com",
        "Origin": "https://www.xiaoyuzhoufm.com",
        "Content-Type": "application/json",
    }
    resolved_device_id = device_id.strip() or os.getenv("XIAOYUZHOU_DEVICE_ID", "")
    resolved_refresh_token = refresh_token.strip() or os.getenv(
        "XIAOYUZHOU_REFRESH_TOKEN", ""
    )
    if resolved_device_id:
        headers["x-jike-device-id"] = resolved_device_id
    if resolved_refresh_token:
        headers["x-jike-refresh-token"] = resolved_refresh_token
    return headers


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _format_ctime(timestamp: int) -> str:
    if timestamp <= 0:
        return ""
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _parse_comment(raw: dict[str, Any], *, up_uid: int) -> PlatformComment:
    member = raw.get("member")
    if not isinstance(member, dict):
        member = {}
    content = raw.get("content")
    if not isinstance(content, dict):
        content = {}

    author_uid = _to_int(member.get("mid"))
    ctime_timestamp = _to_int(raw.get("ctime"))
    return PlatformComment(
        rpid=_to_int(raw.get("rpid")),
        author=str(member.get("uname") or ""),
        author_uid=author_uid,
        message=str(content.get("message") or "").strip(),
        like=_to_int(raw.get("like")),
        ctime=_format_ctime(ctime_timestamp),
        ctime_timestamp=ctime_timestamp,
        is_up_reply=up_uid > 0 and author_uid == up_uid,
    )


def _sort_value(sort: str) -> int:
    normalized = sort.strip().lower()
    if normalized in {"time", "latest", "new"}:
        return 0
    return 1


def _wbi_sort_mode(sort: str) -> int:
    normalized = sort.strip().lower()
    if normalized in {"time", "latest", "new"}:
        return 2
    return 3


def _wbi_mixin_key(img_key: str, sub_key: str) -> str:
    original = f"{img_key}{sub_key}"
    if len(original) < 64:
        raise RuntimeError("Bilibili WBI key is incomplete")
    return "".join(original[index] for index in BILIBILI_MIXIN_KEY_ENC_TAB)[:32]


def _extract_wbi_key(url: Any) -> str:
    filename = str(url or "").rsplit("/", 1)[-1]
    return filename.split(".", 1)[0]


async def _fetch_wbi_mixin_key(client: httpx.AsyncClient) -> str:
    response = await client.get("https://api.bilibili.com/x/web-interface/nav")
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Bilibili WBI nav data is missing")
    wbi_img = data.get("wbi_img")
    if not isinstance(wbi_img, dict):
        raise RuntimeError("Bilibili WBI image keys are missing")
    return _wbi_mixin_key(
        _extract_wbi_key(wbi_img.get("img_url")),
        _extract_wbi_key(wbi_img.get("sub_url")),
    )


def _sign_wbi_params(params: dict[str, Any], mixin_key: str) -> dict[str, Any]:
    signed = dict(params)
    signed["wts"] = int(time.time())
    sanitized = {
        key: "".join(char for char in str(value) if char not in "!'()*")
        for key, value in signed.items()
    }
    query = urllib.parse.urlencode(sorted(sanitized.items()))
    sanitized["w_rid"] = hashlib.md5(f"{query}{mixin_key}".encode()).hexdigest()
    return sanitized


async def _fetch_main_comment_page(
    client: httpx.AsyncClient,
    *,
    aid: int,
    mode: int,
    offset: str,
    mixin_key: str,
) -> dict[str, Any]:
    response = await client.get(
        "https://api.bilibili.com/x/v2/reply/wbi/main",
        params=_sign_wbi_params(
            {
                "oid": aid,
                "type": BILIBILI_VIDEO_COMMENT_TYPE,
                "mode": mode,
                "pagination_str": json.dumps({"offset": offset}, separators=(",", ":")),
                "plat": 1,
                "seek_rpid": "",
                "web_location": BILIBILI_WBI_WEB_LOCATION,
            },
            mixin_key,
        ),
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(payload.get("message") or "Bilibili WBI comment API error")
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    return data


async def _fetch_reply_page(
    client: httpx.AsyncClient,
    *,
    aid: int,
    root_rpid: int,
    page: int,
) -> list[dict[str, Any]]:
    response = await client.get(
        "https://api.bilibili.com/x/v2/reply/reply",
        params={
            "type": BILIBILI_VIDEO_COMMENT_TYPE,
            "oid": aid,
            "root": root_rpid,
            "ps": MAX_PAGE_SIZE,
            "pn": page,
        },
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(payload.get("message") or "Bilibili reply API error")
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    replies = data.get("replies")
    return replies if isinstance(replies, list) else []


async def _fetch_all_replies(
    client: httpx.AsyncClient,
    *,
    aid: int,
    root_rpid: int,
    reply_count: int,
    up_uid: int,
) -> tuple[PlatformComment, ...]:
    if reply_count <= 0:
        return ()

    replies: list[PlatformComment] = []
    page = 1
    while True:
        try:
            raw_replies = await _fetch_reply_page(
                client,
                aid=aid,
                root_rpid=root_rpid,
                page=page,
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch Bilibili child replies for root %s page %s: %s",
                root_rpid,
                page,
                exc,
            )
            break
        if not raw_replies:
            break
        replies.extend(_parse_comment(item, up_uid=up_uid) for item in raw_replies)
        if len(raw_replies) < MAX_PAGE_SIZE or len(replies) >= reply_count:
            break
        page += 1

    return tuple(replies[:reply_count])


async def fetch_bilibili_comments_async(
    *,
    aid: int,
    bvid: str,
    up_uid: int,
    limit: int | None = DEFAULT_COMMENT_LIMIT,
    sort: str = "hot",
    cookie: str = "",
) -> PlatformCommentBundle:
    """Fetch top-level Bilibili video comments and all child replies."""
    if aid <= 0:
        raise ValueError("Bilibili aid is required to fetch comments")
    if limit is not None and limit <= 0:
        raise ValueError("comment limit must be positive or None")

    try:
        return await _fetch_bilibili_comments_wbi(
            aid=aid,
            bvid=bvid,
            up_uid=up_uid,
            limit=limit,
            sort=sort,
        )
    except Exception as exc:
        logger.warning("Bilibili WBI comment API failed, falling back: %s", exc)

    return await _fetch_bilibili_comments_legacy(
        aid=aid,
        bvid=bvid,
        up_uid=up_uid,
        limit=limit,
        sort=sort,
        cookie=cookie,
    )


async def _fetch_bilibili_comments_wbi(
    *,
    aid: int,
    bvid: str,
    up_uid: int,
    limit: int | None,
    sort: str,
) -> PlatformCommentBundle:
    total_count = 0
    comments: list[PlatformComment] = []
    seen_rpids: set[int | str] = set()
    offset = ""
    mode = _wbi_sort_mode(sort)
    stopped_early = False

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=30.0,
        headers=_headers(),
    ) as client:
        mixin_key = await _fetch_wbi_mixin_key(client)
        while limit is None or len(comments) < limit:
            try:
                data = await _fetch_main_comment_page(
                    client,
                    aid=aid,
                    mode=mode,
                    offset=offset,
                    mixin_key=mixin_key,
                )
            except Exception:
                if comments:
                    logger.warning(
                        "Bilibili WBI comment pagination stopped after %s comments; returning partial results",
                        len(comments),
                    )
                    stopped_early = True
                    break
                raise
            cursor = data.get("cursor")
            if isinstance(cursor, dict):
                total_count = max(
                    total_count,
                    _to_int(cursor.get("all_count")),
                    _to_int(cursor.get("total")),
                )
            raw_comments = data.get("replies")
            if not isinstance(raw_comments, list) or not raw_comments:
                break

            for raw_comment in raw_comments:
                if not isinstance(raw_comment, dict):
                    continue
                comment = _parse_comment(raw_comment, up_uid=up_uid)
                if comment.rpid in seen_rpids:
                    continue
                seen_rpids.add(comment.rpid)
                reply_count = _to_int(
                    raw_comment.get("rcount"), _to_int(raw_comment.get("count"))
                )
                replies = await _fetch_all_replies(
                    client,
                    aid=aid,
                    root_rpid=comment.rpid,
                    reply_count=reply_count,
                    up_uid=up_uid,
                )
                comments.append(
                    PlatformComment(
                        rpid=comment.rpid,
                        author=comment.author,
                        author_uid=comment.author_uid,
                        message=comment.message,
                        like=comment.like,
                        ctime=comment.ctime,
                        ctime_timestamp=comment.ctime_timestamp,
                        is_up_reply=comment.is_up_reply,
                        replies=replies,
                    )
                )
                if limit is not None and len(comments) >= limit:
                    break

            if not isinstance(cursor, dict) or cursor.get("is_end"):
                break
            pagination_reply = cursor.get("pagination_reply")
            next_offset = (
                pagination_reply.get("next_offset")
                if isinstance(pagination_reply, dict)
                else ""
            )
            if not next_offset or next_offset == offset:
                break
            offset = str(next_offset)

    return PlatformCommentBundle(
        bvid=bvid,
        fetched_count=len(comments),
        requested_limit=limit,
        total_count=max(total_count, len(comments)),
        sort=sort,
        comments=tuple(comments),
        aid=aid,
        platform=Platform.BILIBILI.value,
        source="wbi_api_partial" if stopped_early else "wbi_api",
    )


async def _fetch_bilibili_comments_legacy(
    *,
    aid: int,
    bvid: str,
    up_uid: int,
    limit: int | None,
    sort: str,
    cookie: str,
) -> PlatformCommentBundle:
    page = 1
    total_count = 0
    comments: list[PlatformComment] = []

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=30.0,
        headers=_headers(cookie),
    ) as client:
        while limit is None or len(comments) < limit:
            remaining = MAX_PAGE_SIZE if limit is None else limit - len(comments)
            page_size = min(MAX_PAGE_SIZE, max(1, remaining))
            response = await client.get(
                "https://api.bilibili.com/x/v2/reply",
                params={
                    "type": BILIBILI_VIDEO_COMMENT_TYPE,
                    "oid": aid,
                    "sort": _sort_value(sort),
                    "ps": page_size,
                    "pn": page,
                    "nohot": 1,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                raise RuntimeError(
                    payload.get("message") or "Bilibili comment API error"
                )

            data = payload.get("data")
            if not isinstance(data, dict):
                break
            page_info = data.get("page")
            if isinstance(page_info, dict):
                total_count = _to_int(page_info.get("count"), total_count)
            raw_comments = data.get("replies")
            if not isinstance(raw_comments, list) or not raw_comments:
                break

            for raw_comment in raw_comments:
                if not isinstance(raw_comment, dict):
                    continue
                comment = _parse_comment(raw_comment, up_uid=up_uid)
                reply_count = _to_int(
                    raw_comment.get("rcount"), _to_int(raw_comment.get("count"))
                )
                replies = await _fetch_all_replies(
                    client,
                    aid=aid,
                    root_rpid=comment.rpid,
                    reply_count=reply_count,
                    up_uid=up_uid,
                )
                comments.append(
                    PlatformComment(
                        rpid=comment.rpid,
                        author=comment.author,
                        author_uid=comment.author_uid,
                        message=comment.message,
                        like=comment.like,
                        ctime=comment.ctime,
                        ctime_timestamp=comment.ctime_timestamp,
                        is_up_reply=comment.is_up_reply,
                        replies=replies,
                    )
                )
                if limit is not None and len(comments) >= limit:
                    break

            if len(raw_comments) < page_size:
                break
            page += 1

    return PlatformCommentBundle(
        bvid=bvid,
        fetched_count=len(comments),
        requested_limit=limit,
        total_count=total_count,
        sort=sort,
        comments=tuple(comments),
        aid=aid,
        platform=Platform.BILIBILI.value,
        source="api",
    )


def fetch_bilibili_comments(
    *,
    aid: int,
    bvid: str,
    up_uid: int,
    limit: int | None = DEFAULT_COMMENT_LIMIT,
    sort: str = "hot",
    cookie: str = "",
) -> PlatformCommentBundle:
    """Synchronously fetch Bilibili comments."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "An event loop is already running; use fetch_bilibili_comments_async instead."
        )

    return asyncio.run(
        fetch_bilibili_comments_async(
            aid=aid,
            bvid=bvid,
            up_uid=up_uid,
            limit=limit,
            sort=sort,
            cookie=cookie,
        )
    )


def _extract_next_data(html: str) -> dict[str, Any]:
    match = _NEXT_DATA_PATTERN.search(html)
    if match is None:
        raise RuntimeError("无法从小宇宙页面中提取 __NEXT_DATA__ JSON")
    data = json.loads(match.group(1))
    if not isinstance(data, dict):
        raise RuntimeError("小宇宙页面 __NEXT_DATA__ 不是 JSON 对象")
    return data


def _format_iso_datetime(value: Any) -> tuple[str, int]:
    text = str(value or "").strip()
    if not text:
        return "", 0
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return text, 0
    return parsed.strftime("%Y-%m-%d %H:%M:%S"), int(parsed.timestamp())


def _find_comment_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in (
        "comments",
        "data",
        "items",
        "list",
        "commentList",
        "primaryComments",
        "replies",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        nested = _find_comment_items(value)
        if nested:
            return nested
    return []


def _find_load_more_key(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("loadMoreKey", "load_more_key", "next", "cursor", "nextCursor"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for value in payload.values():
        if isinstance(value, dict):
            nested = _find_load_more_key(value)
            if nested:
                return nested
    return ""


def _parse_xiaoyuzhou_comment(raw: dict[str, Any]) -> PlatformComment:
    author = raw.get("author")
    if not isinstance(author, dict):
        author = {}
    ctime, ctime_timestamp = _format_iso_datetime(raw.get("createdAt"))
    is_author = str(raw.get("authorAssociation") or "").upper() == "PODCASTER" or str(
        raw.get("podcastAssociation") or ""
    ).upper() in {"ORIGINAL", "PODCASTER"}
    replies = tuple(
        _parse_xiaoyuzhou_comment(reply)
        for reply in raw.get("replies", ())
        if isinstance(reply, dict)
    )
    return PlatformComment(
        rpid=str(raw.get("id") or ""),
        author=str(author.get("nickname") or ""),
        author_uid=str(author.get("uid") or ""),
        message=str(raw.get("text") or "").strip(),
        like=_to_int(raw.get("likeCount")),
        ctime=ctime,
        ctime_timestamp=ctime_timestamp,
        is_up_reply=is_author,
        replies=replies,
    )


async def _fetch_xiaoyuzhou_api_page(
    client: httpx.AsyncClient,
    *,
    episode_id: str,
    load_more_key: str = "",
    thread_id: str = "",
    refresh_token: str = "",
    device_id: str = "",
) -> dict[str, Any]:
    if thread_id:
        url = XIAOYUZHOU_REPLY_API_URL
        payload: dict[str, Any] = {
            "owner": {"id": episode_id, "type": "EPISODE"},
            "thread": thread_id,
        }
    else:
        url = XIAOYUZHOU_COMMENT_API_URL
        payload = {
            "owner": {"id": episode_id, "type": "EPISODE"},
        }
    if load_more_key:
        payload["loadMoreKey"] = load_more_key
    response = await client.post(
        url,
        json=payload,
        headers=_xiaoyuzhou_headers(
            refresh_token=refresh_token,
            device_id=device_id,
        ),
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("小宇宙评论接口返回非 JSON 对象")
    return data


async def _fetch_all_xiaoyuzhou_replies(
    client: httpx.AsyncClient,
    *,
    episode_id: str,
    root_comment: PlatformComment,
    refresh_token: str = "",
    device_id: str = "",
) -> tuple[PlatformComment, ...]:
    if not root_comment.rpid:
        return root_comment.replies

    replies = list(root_comment.replies)
    seen_ids = {str(reply.rpid) for reply in replies}
    load_more_key = ""
    while True:
        payload = await _fetch_xiaoyuzhou_api_page(
            client,
            episode_id=episode_id,
            thread_id=str(root_comment.rpid),
            load_more_key=load_more_key,
            refresh_token=refresh_token,
            device_id=device_id,
        )
        raw_replies = _find_comment_items(payload)
        new_count = 0
        for raw_reply in raw_replies:
            reply = _parse_xiaoyuzhou_comment(raw_reply)
            reply_id = str(reply.rpid)
            if reply_id in seen_ids:
                continue
            seen_ids.add(reply_id)
            replies.append(reply)
            new_count += 1

        load_more_key = _find_load_more_key(payload)
        if not load_more_key or new_count == 0:
            break
    return tuple(replies)


def _parse_xiaoyuzhou_embedded_comments(
    *,
    episode_id: str,
    html: str,
    limit: int | None,
    sort: str,
) -> PlatformCommentBundle:
    next_data = _extract_next_data(html)
    page_props = (
        next_data.get("props", {}).get("pageProps", {})
        if isinstance(next_data.get("props"), dict)
        else {}
    )
    if not isinstance(page_props, dict):
        page_props = {}
    episode = page_props.get("episode")
    if not isinstance(episode, dict):
        episode = {}
    raw_comments = page_props.get("comments")
    if not isinstance(raw_comments, list):
        raw_comments = []
    selected = raw_comments if limit is None else raw_comments[:limit]
    comments = tuple(
        _parse_xiaoyuzhou_comment(item) for item in selected if isinstance(item, dict)
    )
    return PlatformCommentBundle(
        bvid=f"{Platform.XIAOYUZHOU.value}_{episode_id}",
        fetched_count=len(comments),
        requested_limit=limit,
        total_count=_to_int(episode.get("commentCount"), len(comments)),
        sort=sort,
        comments=comments,
        platform=Platform.XIAOYUZHOU.value,
        source="embedded_page",
    )


async def fetch_xiaoyuzhou_comments_async(
    *,
    episode_id: str,
    limit: int | None = DEFAULT_COMMENT_LIMIT,
    sort: str = "hot",
    refresh_token: str = "",
    device_id: str = "",
) -> PlatformCommentBundle:
    """Fetch Xiaoyuzhou comments.

    The public episode page embeds a first page of comments. Xiaoyuzhou's
    paginated comment endpoints require Jike/Xiaoyuzhou device credentials in
    many environments, so this function first tries the API when credentials
    are supplied and falls back to the embedded page otherwise.
    """
    if not episode_id.strip():
        raise ValueError("Xiaoyuzhou episode ID is required to fetch comments")
    if limit is not None and limit <= 0:
        raise ValueError("comment limit must be positive or None")

    episode_id = episode_id.strip().removeprefix(f"{Platform.XIAOYUZHOU.value}_")
    page_url = f"https://www.xiaoyuzhoufm.com/episode/{episode_id}"

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=30.0,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        use_api = bool(
            (refresh_token or os.getenv("XIAOYUZHOU_REFRESH_TOKEN", "")).strip()
            or (device_id or os.getenv("XIAOYUZHOU_DEVICE_ID", "")).strip()
        )
        if use_api:
            try:
                comments: list[PlatformComment] = []
                seen_ids: set[str] = set()
                load_more_key = ""
                total_count = 0
                while limit is None or len(comments) < limit:
                    payload = await _fetch_xiaoyuzhou_api_page(
                        client,
                        episode_id=episode_id,
                        load_more_key=load_more_key,
                        refresh_token=refresh_token,
                        device_id=device_id,
                    )
                    raw_comments = _find_comment_items(payload)
                    if not raw_comments:
                        break
                    for raw_comment in raw_comments:
                        comment = _parse_xiaoyuzhou_comment(raw_comment)
                        comment_id = str(comment.rpid)
                        if comment_id in seen_ids:
                            continue
                        seen_ids.add(comment_id)
                        replies = await _fetch_all_xiaoyuzhou_replies(
                            client,
                            episode_id=episode_id,
                            root_comment=comment,
                            refresh_token=refresh_token,
                            device_id=device_id,
                        )
                        comments.append(
                            PlatformComment(
                                rpid=comment.rpid,
                                author=comment.author,
                                author_uid=comment.author_uid,
                                message=comment.message,
                                like=comment.like,
                                ctime=comment.ctime,
                                ctime_timestamp=comment.ctime_timestamp,
                                is_up_reply=comment.is_up_reply,
                                replies=replies,
                            )
                        )
                        if limit is not None and len(comments) >= limit:
                            break
                    total_count = max(total_count, len(comments))
                    load_more_key = _find_load_more_key(payload)
                    if not load_more_key:
                        break
                return PlatformCommentBundle(
                    bvid=f"{Platform.XIAOYUZHOU.value}_{episode_id}",
                    fetched_count=len(comments),
                    requested_limit=limit,
                    total_count=total_count,
                    sort=sort,
                    comments=tuple(comments),
                    platform=Platform.XIAOYUZHOU.value,
                    source="api",
                )
            except Exception as exc:
                logger.warning("小宇宙评论 API 获取失败，回退公开页面评论: %s", exc)

        response = await client.get(page_url)
        response.raise_for_status()
        bundle = _parse_xiaoyuzhou_embedded_comments(
            episode_id=episode_id,
            html=response.text,
            limit=limit,
            sort=sort,
        )
        if bundle.total_count > bundle.fetched_count:
            logger.warning(
                "小宇宙公开页面仅内嵌 %s/%s 条主评论；若要分页下载更多主评论和完整子评论，"
                "请配置 XIAOYUZHOU_DEVICE_ID 或 XIAOYUZHOU_REFRESH_TOKEN 后重试",
                bundle.fetched_count,
                bundle.total_count,
            )
        return bundle


def fetch_xiaoyuzhou_comments(
    *,
    episode_id: str,
    limit: int | None = DEFAULT_COMMENT_LIMIT,
    sort: str = "hot",
    refresh_token: str = "",
    device_id: str = "",
) -> PlatformCommentBundle:
    """Synchronously fetch Xiaoyuzhou comments."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "An event loop is already running; use fetch_xiaoyuzhou_comments_async instead."
        )
    return asyncio.run(
        fetch_xiaoyuzhou_comments_async(
            episode_id=episode_id,
            limit=limit,
            sort=sort,
            refresh_token=refresh_token,
            device_id=device_id,
        )
    )


def fetch_platform_comments(
    *,
    platform: Platform,
    resource_id: str,
    aid: int = 0,
    up_uid: int = 0,
    limit: int | None = DEFAULT_COMMENT_LIMIT,
    sort: str = "hot",
    cookie: str = "",
) -> PlatformCommentBundle:
    """Fetch comments for a supported platform."""
    if platform == Platform.BILIBILI:
        return fetch_bilibili_comments(
            aid=aid,
            bvid=resource_id,
            up_uid=up_uid,
            limit=limit,
            sort=sort,
            cookie=cookie,
        )
    if platform == Platform.XIAOYUZHOU:
        episode_id = extract_platform_id(
            resource_id, Platform.XIAOYUZHOU
        ) or resource_id.removeprefix(f"{Platform.XIAOYUZHOU.value}_")
        return fetch_xiaoyuzhou_comments(
            episode_id=episode_id,
            limit=limit,
            sort=sort,
        )
    raise ValueError(f"不支持获取评论的平台: {platform.value}")


def write_comments_json(bundle: PlatformCommentBundle, path: Path) -> Path:
    path.write_text(
        json.dumps(asdict(bundle), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def comments_to_markdown(bundle: PlatformCommentBundle) -> str:
    platform_label = {
        Platform.BILIBILI.value: "Bilibili",
        Platform.XIAOYUZHOU.value: "小宇宙",
    }.get(bundle.platform, bundle.platform)
    lines = [
        f"# {platform_label} 精选评论",
        "",
        f"- 资源: {bundle.bvid}",
        f"- 排序: {bundle.sort}",
        f"- 已抓取主评论: {bundle.fetched_count}",
        f"- 已抓取子评论: {count_comment_replies(bundle)}",
        f"- 评论区总数: {bundle.total_count}",
        f"- 来源: {bundle.source}",
        "",
    ]
    if bundle.aid:
        lines.insert(3, f"- AID: {bundle.aid}")
    if not bundle.comments:
        lines.append("暂无可用评论。")
        return "\n".join(lines).rstrip() + "\n"

    for index, comment in enumerate(bundle.comments, start=1):
        prefix = "**UP主回复** " if comment.is_up_reply else ""
        lines.append(f"## {index}. {prefix}{comment.author}")
        lines.append(f"- 点赞: {comment.like}")
        if comment.ctime:
            lines.append(f"- 时间: {comment.ctime}")
        lines.append("")
        message = f"**{comment.message}**" if comment.is_up_reply else comment.message
        lines.append(message or "(空评论)")
        lines.append("")
        if comment.replies:
            lines.append("子评论：")
            for reply in comment.replies:
                reply_prefix = "**UP主回复** " if reply.is_up_reply else ""
                reply_message = (
                    f"**{reply.message}**" if reply.is_up_reply else reply.message
                )
                lines.append(
                    f"- {reply_prefix}{reply.author}（点赞 {reply.like}）：{reply_message or '(空评论)'}"
                )
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_comments_markdown(bundle: PlatformCommentBundle, path: Path) -> Path:
    path.write_text(comments_to_markdown(bundle), encoding="utf-8")
    return path


__all__ = [
    "BilibiliComment",
    "BilibiliCommentBundle",
    "DEFAULT_COMMENT_LIMIT",
    "PlatformComment",
    "PlatformCommentBundle",
    "fetch_bilibili_comments",
    "fetch_bilibili_comments_async",
    "fetch_platform_comments",
    "fetch_xiaoyuzhou_comments",
    "fetch_xiaoyuzhou_comments_async",
    "comments_to_markdown",
    "comment_platform_from_metadata",
    "comment_platform_label",
    "count_comment_replies",
    "count_up_replies",
    "write_comments_json",
    "write_comments_markdown",
]
