"""Tests for YouTube search tool."""

import pytest

from youtube_agent.models.search import VideoSearchResult
from youtube_agent.services.youtube import (
    YouTubeSearchError,
    _extract_videos_from_html,
    search_youtube,
)
from youtube_agent.tools.search import search_youtube_formatted


class TestVideoSearchResult:
    """Tests for VideoSearchResult dataclass."""

    def test_url_property(self) -> None:
        result = VideoSearchResult(
            video_id="abc123XYZ",
            title="Test Video",
            channel="Test Channel",
            duration="10:30",
            view_count="1,000 views",
            published_time="2 days ago",
        )
        assert result.url == "https://www.youtube.com/watch?v=abc123XYZ"

    def test_optional_fields_can_be_none(self) -> None:
        result = VideoSearchResult(
            video_id="abc123XYZ",
            title="Test Video",
            channel="Test Channel",
            duration="10:30",
            view_count=None,
            published_time=None,
        )
        assert result.view_count is None
        assert result.published_time is None


class TestYouTubeSearchError:
    """Tests for YouTubeSearchError."""

    def test_error_message_includes_query_and_reason(self) -> None:
        error = YouTubeSearchError("test query", "network error")
        assert "test query" in str(error)
        assert "network error" in str(error)

    def test_stores_query_and_reason(self) -> None:
        error = YouTubeSearchError("test query", "network error")
        assert error.query == "test query"
        assert error.reason == "network error"


class TestExtractVideosFromHtml:
    """Tests for HTML extraction function."""

    def test_returns_empty_list_for_no_match(self) -> None:
        html = "<html><body>No video data here</body></html>"
        result = _extract_videos_from_html(html, 5)
        assert result == []

    def test_returns_empty_list_for_invalid_json(self) -> None:
        html = "var ytInitialData = {invalid json};</script>"
        result = _extract_videos_from_html(html, 5)
        assert result == []

    def test_returns_empty_list_for_empty_contents(self) -> None:
        html = 'var ytInitialData = {"contents": {}};</script>'
        result = _extract_videos_from_html(html, 5)
        assert result == []

    def test_extracts_video_data_from_valid_html(self) -> None:
        # Create minimal valid structure with video renderers
        html = '''<script>var ytInitialData = {"contents":{"twoColumnSearchResultsRenderer":{"primaryContents":{"sectionListRenderer":{"contents":[{"itemSectionRenderer":{"contents":[{"videoRenderer":{"videoId":"vid1","title":{"runs":[{"text":"Video 1"}]},"ownerText":{"runs":[{"text":"Channel 1"}]},"lengthText":{"simpleText":"5:00"}}}]}}]}}}}};</script>'''
        result = _extract_videos_from_html(html, 5)
        assert len(result) == 1
        assert result[0]["video_id"] == "vid1"
        assert result[0]["title"] == "Video 1"
        assert result[0]["channel"] == "Channel 1"


class TestSearchYoutube:
    """Tests for search_youtube function."""

    def test_raises_error_for_empty_query(self) -> None:
        with pytest.raises(YouTubeSearchError) as exc_info:
            search_youtube("")
        assert "empty" in exc_info.value.reason.lower()

    def test_raises_error_for_whitespace_query(self) -> None:
        with pytest.raises(YouTubeSearchError) as exc_info:
            search_youtube("   ")
        assert "empty" in exc_info.value.reason.lower()


class TestSearchYoutubeFormatted:
    """Tests for search_youtube_formatted function."""

    def test_returns_no_videos_message_for_empty_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Mock search_youtube in tools.search where search_youtube_formatted uses it
        monkeypatch.setattr(
            "youtube_agent.tools.search.search_youtube",
            lambda _query, _max_results=5: [],
        )
        result = search_youtube_formatted("nonexistent video xyz123")
        assert "No videos found" in result

    def test_formats_results_with_video_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Mock search_youtube to return test data
        mock_results = [
            VideoSearchResult(
                video_id="abc123",
                title="Test Video Title",
                channel="Test Channel",
                duration="5:30",
                view_count="1,000 views",
                published_time="1 day ago",
            ),
        ]
        monkeypatch.setattr(
            "youtube_agent.tools.search.search_youtube",
            lambda _query, _max_results=5: mock_results,
        )
        result = search_youtube_formatted("test")
        assert "Test Video Title" in result
        assert "Test Channel" in result
        assert "5:30" in result
        assert "abc123" in result
        assert "1,000 views" in result
