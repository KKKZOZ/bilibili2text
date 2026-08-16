import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.routes import history as history_routes

from b2t.history import HistoryItem, HistoryPage


def test_history_list_resolves_parent_and_child_partition_names(monkeypatch) -> None:
    page = HistoryPage(
        items=[
            HistoryItem(
                run_id="BV1Hdgs6ME67-12345678",
                bvid="BV1Hdgs6ME67",
                title="康师傅控股中报点评",
                author="测试UP主",
                pubdate="2026-08-15 10:00:00",
                created_at="2026-08-15T11:00:00+08:00",
                has_summary=True,
                file_count=4,
                summary_version_count=2,
                tid=207,
            )
        ],
        total=1,
        page=1,
        page_size=20,
        has_more=False,
    )

    class FakeHistoryDB:
        received_filters = None

        def list_runs(self, **kwargs):
            self.received_filters = kwargs
            return page

    fake_db = FakeHistoryDB()
    monkeypatch.setattr(history_routes, "get_history_db", lambda: fake_db)

    response = history_routes.list_history(
        platform=["bilibili", "xiaoyuzhou"],
        category_tid=[36, 174],
        author=["测试UP主", "另一个UP主"],
    )

    assert response.items[0].tid == 207
    assert response.items[0].summary_version_count == 2
    assert response.items[0].parent_tname == "知识"
    assert response.items[0].tname == "财经商业"
    assert set(fake_db.received_filters["category_tids"]) == {
        36,
        122,
        124,
        174,
        201,
        207,
        208,
        209,
        228,
        229,
    }
    assert fake_db.received_filters["authors"] == ("测试UP主", "另一个UP主")
    assert fake_db.received_filters["platforms"] == ("bilibili", "xiaoyuzhou")


def test_history_filter_options_include_category_hierarchy_and_authors(
    monkeypatch,
) -> None:
    class FakeHistoryDB:
        def list_history_category_counts(self):
            return [(21, 2), (174, 3), (207, 5), (208, 1)]

        def list_history_platform_counts(self):
            return [
                ("bilibili", 8),
                ("xiaoyuzhou", 2),
                ("knowledge_base", 4),
            ]

        def list_history_author_counts(self):
            return [("投资UP主", 6), ("生活UP主", 2)]

    monkeypatch.setattr(history_routes, "get_history_db", lambda: FakeHistoryDB())

    response = history_routes.history_filter_options()

    assert [option.tid for option in response.categories] == [
        36,
        207,
        208,
        174,
        160,
        21,
    ]
    categories = {option.tid: option for option in response.categories}
    assert categories[36].tname == "知识"
    assert categories[36].is_parent is True
    assert categories[36].count == 6
    assert categories[207].parent_tname == "知识"
    assert categories[207].count == 5
    assert categories[174].tname == "直播回放"
    assert categories[174].parent_tname == ""
    assert [(option.author, option.count) for option in response.authors] == [
        ("投资UP主", 6),
        ("生活UP主", 2),
    ]
    assert [
        (option.platform, option.name, option.count) for option in response.platforms
    ] == [
        ("bilibili", "Bilibili", 8),
        ("xiaoyuzhou", "小宇宙", 2),
        ("knowledge_base", "知识库查询", 4),
    ]
