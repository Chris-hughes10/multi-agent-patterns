"""Tests for V2 Session state management."""

import pytest

from youtube_agent_v2.core.session import Session, SessionEntry


class TestSession:
    """Tests for Session class."""

    def test_create_session_with_auto_id(self) -> None:
        """Session auto-generates an ID if not provided."""
        session = Session()
        assert session.id is not None
        assert len(session.id) > 0

    def test_create_session_with_custom_id(self) -> None:
        """Session uses provided ID."""
        session = Session(session_id="my-session-123")
        assert session.id == "my-session-123"

    def test_store_and_get_simple_value(self) -> None:
        """Can store and retrieve a simple value."""
        session = Session()
        session.store("greeting", "hello world")
        assert session.get("greeting") == "hello world"

    def test_store_and_get_dict(self) -> None:
        """Can store and retrieve a dictionary."""
        session = Session()
        data = {"results": [{"id": "abc"}, {"id": "def"}]}
        session.store("search", data)
        assert session.get("search") == data

    def test_get_missing_key_returns_default(self) -> None:
        """Get returns default for missing keys."""
        session = Session()
        assert session.get("missing") is None
        assert session.get("missing", "default") == "default"

    def test_has_key(self) -> None:
        """Has correctly checks key existence."""
        session = Session()
        session.store("exists", "value")
        assert session.has("exists") is True
        assert session.has("missing") is False

    def test_keys(self) -> None:
        """Keys returns all stored keys."""
        session = Session()
        session.store("a", 1)
        session.store("b", 2)
        session.store("c", 3)
        assert set(session.keys()) == {"a", "b", "c"}

    def test_len(self) -> None:
        """Len returns number of entries."""
        session = Session()
        assert len(session) == 0
        session.store("a", 1)
        assert len(session) == 1
        session.store("b", 2)
        assert len(session) == 2

    def test_clear(self) -> None:
        """Clear removes all entries."""
        session = Session()
        session.store("a", 1)
        session.store("b", 2)
        session.clear()
        assert len(session) == 0
        assert session.get("a") is None

    def test_get_entry_with_metadata(self) -> None:
        """Can store and retrieve entry with metadata."""
        session = Session()
        session.store("search", {"results": []}, metadata={"agent": "search", "task_id": "123"})
        entry = session.get_entry("search")
        assert entry is not None
        assert entry.key == "search"
        assert entry.value == {"results": []}
        assert entry.metadata["agent"] == "search"
        assert entry.metadata["task_id"] == "123"

    def test_to_dict(self) -> None:
        """To_dict exports session as dictionary."""
        session = Session()
        session.store("a", 1)
        session.store("b", {"nested": "value"})
        result = session.to_dict()
        assert result == {"a": 1, "b": {"nested": "value"}}


class TestSessionResolve:
    """Tests for Session.resolve() variable path resolution."""

    def test_resolve_simple_key(self) -> None:
        """Resolve simple $key path."""
        session = Session()
        session.store("search", "search results")
        assert session.resolve("$search") == "search results"

    def test_resolve_dict_field(self) -> None:
        """Resolve $key.field path."""
        session = Session()
        session.store("search", {"query": "test", "count": 5})
        assert session.resolve("$search.query") == "test"
        assert session.resolve("$search.count") == 5

    def test_resolve_nested_dict(self) -> None:
        """Resolve deeply nested dict path."""
        session = Session()
        session.store("data", {"level1": {"level2": {"level3": "deep value"}}})
        assert session.resolve("$data.level1.level2.level3") == "deep value"

    def test_resolve_array_index(self) -> None:
        """Resolve $key.field[0] path."""
        session = Session()
        session.store("search", {"results": [{"id": "first"}, {"id": "second"}]})
        assert session.resolve("$search.results[0]") == {"id": "first"}
        assert session.resolve("$search.results[1]") == {"id": "second"}

    def test_resolve_array_index_then_field(self) -> None:
        """Resolve $key.field[0].subfield path."""
        session = Session()
        session.store("search", {"results": [{"video_id": "abc123"}, {"video_id": "def456"}]})
        assert session.resolve("$search.results[0].video_id") == "abc123"
        assert session.resolve("$search.results[1].video_id") == "def456"

    def test_resolve_top_level_array(self) -> None:
        """Resolve when stored value is an array."""
        session = Session()
        session.store("videos", [{"id": "a"}, {"id": "b"}, {"id": "c"}])
        assert session.resolve("$videos[0].id") == "a"
        assert session.resolve("$videos[2].id") == "c"

    def test_resolve_missing_dollar_raises(self) -> None:
        """Resolve raises if path doesn't start with $."""
        session = Session()
        session.store("search", "value")
        with pytest.raises(ValueError, match="must start with"):
            session.resolve("search")

    def test_resolve_missing_key_raises(self) -> None:
        """Resolve raises if session key not found."""
        session = Session()
        with pytest.raises(KeyError, match="not found"):
            session.resolve("$missing")

    def test_resolve_missing_field_raises(self) -> None:
        """Resolve raises if dict field not found."""
        session = Session()
        session.store("search", {"existing": "value"})
        with pytest.raises(KeyError):
            session.resolve("$search.missing")

    def test_resolve_index_out_of_bounds_raises(self) -> None:
        """Resolve raises if array index out of bounds."""
        session = Session()
        session.store("search", {"results": [{"id": "only_one"}]})
        with pytest.raises(IndexError):
            session.resolve("$search.results[5]")

    def test_resolve_quoted_string_key(self) -> None:
        """Resolve with quoted string in brackets."""
        session = Session()
        session.store("data", {"special-key": "value"})
        assert session.resolve('$data["special-key"]') == "value"

    def test_resolve_complex_real_world_example(self) -> None:
        """Resolve complex path like what DAG executor would use."""
        session = Session()
        # Simulate search results
        session.store(
            "search",
            {
                "query": "pork loin kamado",
                "results": [
                    {"video_id": "vid123", "title": "Best Pork Loin", "channel": "BBQ Master"},
                    {"video_id": "vid456", "title": "Kamado Cooking", "channel": "Grill Guy"},
                ],
            },
        )
        # Simulate transcript
        session.store(
            "transcript_vid123",
            {
                "video_id": "vid123",
                "text": "Today we're cooking pork loin at 275 degrees...",
                "duration": 600,
            },
        )

        # These are the kinds of resolutions DAG executor would do
        assert session.resolve("$search.results[0].video_id") == "vid123"
        assert session.resolve("$search.results[1].channel") == "Grill Guy"
        assert session.resolve("$transcript_vid123.text").startswith("Today we're cooking")


class TestSessionEntry:
    """Tests for SessionEntry dataclass."""

    def test_entry_has_timestamp(self) -> None:
        """SessionEntry auto-generates timestamp."""
        entry = SessionEntry(key="test", value="data")
        assert entry.timestamp is not None

    def test_entry_default_metadata(self) -> None:
        """SessionEntry has empty metadata by default."""
        entry = SessionEntry(key="test", value="data")
        assert entry.metadata == {}
