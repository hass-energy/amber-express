"""Tests for the data source merger."""

# pyright: reportArgumentType=false
# pyright: reportGeneralTypeIssues=false

from datetime import datetime

from custom_components.amber_express.const import DATA_SOURCE_POLLING, DATA_SOURCE_WEBSOCKET
from custom_components.amber_express.data import DataSourceMerger, MergedResult


class TestDataSourceMergerInit:
    """Tests for DataSourceMerger initialization."""

    def test_initial_state(self) -> None:
        """Test initial state after construction."""
        merger = DataSourceMerger()

        assert merger.polling_data == {}
        assert merger.websocket_data == {}
        assert merger.polling_timestamp is None
        assert merger.websocket_timestamp is None


class TestUpdatePolling:
    """Tests for update_polling method."""

    def test_stores_data(self) -> None:
        """Test that polling data is stored."""
        merger = DataSourceMerger()
        data = {"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00"}}

        merger.update_polling(data)

        assert merger.polling_data["general"]["price"] == 0.25

    def test_sets_timestamp_from_start_time(self) -> None:
        """Test that timestamp is derived from the data's start_time."""
        merger = DataSourceMerger()

        merger.update_polling({"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00"}})

        assert merger.polling_timestamp == datetime.fromisoformat("2024-01-01T10:00:00+10:00")

    def test_no_timestamp_without_start_time(self) -> None:
        """Test that timestamp stays None when data has no start_time."""
        merger = DataSourceMerger()

        merger.update_polling({"general": {"price": 0.25}})

        assert merger.polling_timestamp is None

    def test_overwrites_previous_data(self) -> None:
        """Test that new data overwrites previous data."""
        merger = DataSourceMerger()

        merger.update_polling({"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00"}})
        merger.update_polling({"general": {"price": 0.30, "start_time": "2024-01-01T10:00:00+10:00"}})

        assert merger.polling_data["general"]["price"] == 0.30


class TestUpdateWebsocket:
    """Tests for update_websocket method."""

    def test_stores_data(self) -> None:
        """Test that websocket data is stored."""
        merger = DataSourceMerger()
        data = {"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00"}}

        merger.update_websocket(data)

        assert merger.websocket_data == data

    def test_sets_timestamp_from_start_time(self) -> None:
        """Test that timestamp is derived from the data's start_time."""
        merger = DataSourceMerger()

        merger.update_websocket({"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00"}})

        assert merger.websocket_timestamp == datetime.fromisoformat("2024-01-01T10:00:00+10:00")

    def test_no_timestamp_without_start_time(self) -> None:
        """Test that timestamp stays None when data has no start_time."""
        merger = DataSourceMerger()

        merger.update_websocket({"general": {"price": 0.25}})

        assert merger.websocket_timestamp is None


class TestGetMergedData:
    """Tests for get_merged_data method."""

    def test_empty_returns_polling_source(self) -> None:
        """Test empty merger returns polling as source."""
        merger = DataSourceMerger()

        result = merger.get_merged_data()

        assert result.source == DATA_SOURCE_POLLING
        assert "_source" in result.data
        assert result.data["_source"] == DATA_SOURCE_POLLING

    def test_polling_only(self) -> None:
        """Test with only polling data."""
        merger = DataSourceMerger()

        merger.update_polling({"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00"}})
        result = merger.get_merged_data()

        assert result.source == DATA_SOURCE_POLLING
        assert result.data["general"]["price"] == 0.25

    def test_websocket_only(self) -> None:
        """Test with only websocket data."""
        merger = DataSourceMerger()

        merger.update_websocket({"general": {"price": 0.30, "start_time": "2024-01-01T10:00:00+10:00"}})
        result = merger.get_merged_data()

        assert result.source == DATA_SOURCE_WEBSOCKET
        assert result.data["general"]["price"] == 0.30

    def test_websocket_newer_interval_wins(self) -> None:
        """Test that WebSocket wins when it has a strictly newer interval."""
        merger = DataSourceMerger()

        merger.update_polling({"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00"}})
        merger.update_websocket({"general": {"price": 0.30, "start_time": "2024-01-01T10:30:00+10:00"}})

        result = merger.get_merged_data()

        assert result.source == DATA_SOURCE_WEBSOCKET
        assert result.data["general"]["price"] == 0.30

    def test_polling_newer_interval_wins(self) -> None:
        """Test that polling wins when it has a newer interval."""
        merger = DataSourceMerger()

        merger.update_websocket({"general": {"price": 0.30, "start_time": "2024-01-01T10:00:00+10:00"}})
        merger.update_polling({"general": {"price": 0.25, "start_time": "2024-01-01T10:30:00+10:00"}})

        result = merger.get_merged_data()

        assert result.source == DATA_SOURCE_POLLING
        assert result.data["general"]["price"] == 0.25

    def test_same_interval_polling_wins(self) -> None:
        """Test that polling wins when both sources cover the same interval."""
        merger = DataSourceMerger()

        merger.update_polling({"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00"}})
        merger.update_websocket({"general": {"price": 0.30, "start_time": "2024-01-01T10:00:00+10:00"}})

        result = merger.get_merged_data()

        assert result.source == DATA_SOURCE_POLLING
        assert result.data["general"]["price"] == 0.25

    def test_old_websocket_does_not_trump_polling(self) -> None:
        """Test that WebSocket data for an old interval cannot override newer polling data."""
        merger = DataSourceMerger()

        merger.update_polling({"general": {"price": 0.25, "start_time": "2024-01-01T10:30:00+10:00"}})
        merger.update_websocket({"general": {"price": 0.30, "start_time": "2024-01-01T10:00:00+10:00"}})

        result = merger.get_merged_data()

        assert result.source == DATA_SOURCE_POLLING
        assert result.data["general"]["price"] == 0.25

    def test_both_without_start_time_polling_wins(self) -> None:
        """Test that polling wins when neither source has start_time."""
        merger = DataSourceMerger()

        merger.update_polling({"general": {"price": 0.25}})
        merger.update_websocket({"general": {"price": 0.30}})

        result = merger.get_merged_data()

        assert result.source == DATA_SOURCE_POLLING
        assert result.data["general"]["price"] == 0.25

    def test_includes_metadata(self) -> None:
        """Test that merged data includes metadata from start_time."""
        merger = DataSourceMerger()

        merger.update_polling({"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00"}})
        merger.update_websocket({"general": {"price": 0.30, "start_time": "2024-01-01T10:30:00+10:00"}})

        result = merger.get_merged_data()

        assert "_source" in result.data
        assert "_polling_timestamp" in result.data
        assert "_websocket_timestamp" in result.data
        assert result.data["_polling_timestamp"] == "2024-01-01T10:00:00+10:00"
        assert result.data["_websocket_timestamp"] == "2024-01-01T10:30:00+10:00"

    def test_metadata_with_no_timestamps(self) -> None:
        """Test metadata when no timestamps are set."""
        merger = DataSourceMerger()

        result = merger.get_merged_data()

        assert result.data["_polling_timestamp"] is None
        assert result.data["_websocket_timestamp"] is None

    def test_returns_shallow_copy_of_data(self) -> None:
        """Test that merged data is a shallow copy at the top level."""
        merger = DataSourceMerger()

        merger.update_polling({"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00"}})
        result = merger.get_merged_data()

        # Adding a new key to result doesn't affect the original
        result.data["new_key"] = "new_value"

        # Original should not have the new key
        assert "new_key" not in merger.polling_data


class TestMergedResult:
    """Tests for MergedResult dataclass."""

    def test_fields(self) -> None:
        """Test MergedResult dataclass fields."""
        result = MergedResult(
            data={"general": {"price": 0.25}},
            source=DATA_SOURCE_POLLING,
        )

        assert result.data == {"general": {"price": 0.25}}
        assert result.source == DATA_SOURCE_POLLING


class TestProperties:
    """Tests for DataSourceMerger properties."""

    def test_polling_data_property(self) -> None:
        """Test polling_data property."""
        merger = DataSourceMerger()
        data = {"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00"}}

        merger.update_polling(data)

        assert merger.polling_data["general"]["price"] == 0.25

    def test_websocket_data_property(self) -> None:
        """Test websocket_data property."""
        merger = DataSourceMerger()
        data = {"general": {"price": 0.30, "start_time": "2024-01-01T10:00:00+10:00"}}

        merger.update_websocket(data)

        assert merger.websocket_data == data

    def test_polling_timestamp_property(self) -> None:
        """Test polling_timestamp property."""
        merger = DataSourceMerger()

        assert merger.polling_timestamp is None

        merger.update_polling({"general": {"start_time": "2024-01-01T10:00:00+10:00"}})
        assert merger.polling_timestamp is not None

    def test_polling_timestamp_none_without_start_time(self) -> None:
        """Test polling_timestamp stays None without start_time in data."""
        merger = DataSourceMerger()

        merger.update_polling({"general": {"price": 0.25}})
        assert merger.polling_timestamp is None

    def test_websocket_timestamp_property(self) -> None:
        """Test websocket_timestamp property."""
        merger = DataSourceMerger()

        assert merger.websocket_timestamp is None

        merger.update_websocket({"general": {"start_time": "2024-01-01T10:00:00+10:00"}})
        assert merger.websocket_timestamp is not None

    def test_websocket_timestamp_none_without_start_time(self) -> None:
        """Test websocket_timestamp stays None without start_time in data."""
        merger = DataSourceMerger()

        merger.update_websocket({"general": {"price": 0.25}})
        assert merger.websocket_timestamp is None


class TestMultipleChannels:
    """Tests for handling multiple channels."""

    def test_preserves_all_channels(self) -> None:
        """Test that all channels are preserved in merged data."""
        merger = DataSourceMerger()

        data = {
            "general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00"},
            "feed_in": {"price": 0.10, "start_time": "2024-01-01T10:00:00+10:00"},
            "controlled_load": {"price": 0.15, "start_time": "2024-01-01T10:00:00+10:00"},
        }

        merger.update_polling(data)
        result = merger.get_merged_data()

        assert "general" in result.data
        assert "feed_in" in result.data
        assert "controlled_load" in result.data

    def test_different_channels_per_source(self) -> None:
        """Test sources with different channels available."""
        merger = DataSourceMerger()

        merger.update_polling({"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00"}})
        merger.update_websocket(
            {
                "general": {"price": 0.30, "start_time": "2024-01-01T10:30:00+10:00"},
                "feed_in": {"price": 0.10, "start_time": "2024-01-01T10:30:00+10:00"},
            }
        )

        result = merger.get_merged_data()

        assert result.source == DATA_SOURCE_WEBSOCKET
        assert "general" in result.data
        assert "feed_in" in result.data
        assert result.data["general"]["price"] == 0.30


class TestForecastPreservation:
    """Tests for forecast preservation across updates."""

    def test_websocket_update_preserves_polling_forecasts(self) -> None:
        """Test that websocket updates preserve forecasts from polling."""
        merger = DataSourceMerger()
        forecasts = [{"time": "2024-01-01T11:00:00", "price": 0.28}]

        merger.update_polling(
            {"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00", "forecasts": forecasts}}
        )
        merger.update_websocket({"general": {"price": 0.30, "start_time": "2024-01-01T10:30:00+10:00"}})

        result = merger.get_merged_data()

        assert result.source == DATA_SOURCE_WEBSOCKET
        assert result.data["general"]["price"] == 0.30
        assert result.data["general"]["forecasts"] == forecasts

    def test_multiple_websocket_updates_preserve_forecasts(self) -> None:
        """Test that multiple websocket updates still preserve forecasts."""
        merger = DataSourceMerger()
        forecasts = [{"time": "2024-01-01T11:00:00", "price": 0.28}]

        merger.update_polling(
            {"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00", "forecasts": forecasts}}
        )
        merger.update_websocket({"general": {"price": 0.30, "start_time": "2024-01-01T10:30:00+10:00"}})
        merger.update_websocket({"general": {"price": 0.35, "start_time": "2024-01-01T11:00:00+10:00"}})

        result = merger.get_merged_data()

        assert result.data["general"]["price"] == 0.35
        assert result.data["general"]["forecasts"] == forecasts

    def test_forecasts_preserved_for_all_channels(self) -> None:
        """Test that forecasts are preserved for all channels."""
        merger = DataSourceMerger()
        general_forecasts = [{"time": "2024-01-01T11:00:00", "price": 0.28}]
        feed_in_forecasts = [{"time": "2024-01-01T11:00:00", "price": 0.08}]

        merger.update_polling(
            {
                "general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00", "forecasts": general_forecasts},
                "feed_in": {"price": 0.10, "start_time": "2024-01-01T10:00:00+10:00", "forecasts": feed_in_forecasts},
            }
        )
        merger.update_websocket(
            {
                "general": {"price": 0.30, "start_time": "2024-01-01T10:30:00+10:00"},
                "feed_in": {"price": 0.12, "start_time": "2024-01-01T10:30:00+10:00"},
            }
        )

        result = merger.get_merged_data()

        assert result.data["general"]["forecasts"] == general_forecasts
        assert result.data["feed_in"]["forecasts"] == feed_in_forecasts

    def test_new_polling_updates_forecasts(self) -> None:
        """Test that new polling data updates forecasts."""
        merger = DataSourceMerger()
        old_forecasts = [{"time": "2024-01-01T11:00:00", "price": 0.28}]
        new_forecasts = [{"time": "2024-01-01T12:00:00", "price": 0.32}]

        merger.update_polling(
            {"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00", "forecasts": old_forecasts}}
        )
        merger.update_websocket({"general": {"price": 0.30, "start_time": "2024-01-01T10:30:00+10:00"}})
        merger.update_polling(
            {"general": {"price": 0.27, "start_time": "2024-01-01T11:00:00+10:00", "forecasts": new_forecasts}}
        )

        result = merger.get_merged_data()

        assert result.source == DATA_SOURCE_POLLING
        assert result.data["general"]["price"] == 0.27
        assert result.data["general"]["forecasts"] == new_forecasts

    def test_forecasts_property(self) -> None:
        """Test the forecasts property returns stored forecasts."""
        merger = DataSourceMerger()
        forecasts = [{"time": "2024-01-01T11:00:00", "price": 0.28}]

        merger.update_polling(
            {"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00", "forecasts": forecasts}}
        )

        assert merger.forecasts == {"general": forecasts}

    def test_forecasts_timestamp_from_start_time(self) -> None:
        """Test the forecasts_timestamp is derived from start_time."""
        merger = DataSourceMerger()

        assert merger.forecasts_timestamp is None

        merger.update_polling({"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00", "forecasts": []}})

        assert merger.forecasts_timestamp == datetime.fromisoformat("2024-01-01T10:00:00+10:00")

    def test_polling_without_forecasts_preserves_existing(self) -> None:
        """Test that polling without forecasts preserves existing forecasts."""
        merger = DataSourceMerger()
        forecasts = [{"time": "2024-01-01T11:00:00", "price": 0.28}]

        merger.update_polling(
            {"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00", "forecasts": forecasts}}
        )
        merger.update_polling({"general": {"price": 0.27, "start_time": "2024-01-01T10:00:00+10:00"}})

        result = merger.get_merged_data()

        assert result.data["general"]["price"] == 0.27
        assert result.data["general"]["forecasts"] == forecasts

    def test_forecasts_only_creates_channel_entry(self) -> None:
        """Test that forecasts without current data still creates channel entry."""
        merger = DataSourceMerger()
        forecasts = [{"time": "2024-01-01T11:00:00", "price": 0.28}]

        merger.update_polling({"general": {"forecasts": forecasts}})

        result = merger.get_merged_data()

        assert "general" in result.data
        assert result.data["general"]["forecasts"] == forecasts

    def test_websocket_first_then_polling_same_interval(self) -> None:
        """Test WebSocket price arrives first, polling arrives for same interval."""
        merger = DataSourceMerger()
        forecasts = [{"time": "2024-01-01T11:00:00", "price": 0.28}]

        merger.update_websocket({"general": {"price": 0.30, "start_time": "2024-01-01T10:00:00+10:00"}})
        merger.update_polling(
            {"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00", "forecasts": forecasts}}
        )

        result = merger.get_merged_data()

        # Same interval: polling wins (has confirmed data + forecasts)
        assert result.source == DATA_SOURCE_POLLING
        assert result.data["general"]["price"] == 0.25
        assert result.data["general"]["forecasts"] == forecasts

    def test_polling_then_websocket_then_polling_newer(self) -> None:
        """Test API price, WebSocket price, then API with newer interval."""
        merger = DataSourceMerger()
        forecasts = [{"time": "2024-01-01T11:00:00", "price": 0.28}]

        merger.update_polling({"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00"}})
        merger.update_websocket({"general": {"price": 0.30, "start_time": "2024-01-01T10:30:00+10:00"}})
        merger.update_polling(
            {"general": {"price": 0.27, "start_time": "2024-01-01T11:00:00+10:00", "forecasts": forecasts}}
        )

        result = merger.get_merged_data()

        assert result.source == DATA_SOURCE_POLLING
        assert result.data["general"]["price"] == 0.27
        assert result.data["general"]["forecasts"] == forecasts

    def test_websocket_newer_interval_with_polling_forecasts(self) -> None:
        """Test WebSocket price is used when it has a newer interval, with forecasts preserved."""
        merger = DataSourceMerger()
        forecasts = [{"time": "2024-01-01T11:00:00", "price": 0.28}]

        merger.update_polling(
            {"general": {"price": 0.25, "start_time": "2024-01-01T10:00:00+10:00", "forecasts": forecasts}}
        )
        merger.update_websocket({"general": {"price": 0.30, "start_time": "2024-01-01T10:30:00+10:00"}})

        result = merger.get_merged_data()

        assert result.source == DATA_SOURCE_WEBSOCKET
        assert result.data["general"]["price"] == 0.30
        assert result.data["general"]["forecasts"] == forecasts
