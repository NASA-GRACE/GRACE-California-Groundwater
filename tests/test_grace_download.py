"""Tests for grace_download.py GRACE collection discovery."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add scripts directory to path so we can import grace_download
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import grace_download


class TestParseGraceShortName:
    """Tests for parse_grace_short_name() function."""

    def test_parse_valid_rl06_3_v4(self):
        """Parse the current default release."""
        result = grace_download.parse_grace_short_name(
            "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4"
        )
        assert result == ((6, 3), 4)

    def test_parse_valid_rl07_0_v1(self):
        """Parse a hypothetical future release."""
        result = grace_download.parse_grace_short_name(
            "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL07.0_V1"
        )
        assert result == ((7, 0), 1)

    def test_parse_valid_rl10_15_v99(self):
        """Parse with multi-digit release and version numbers."""
        result = grace_download.parse_grace_short_name(
            "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL10.15_V99"
        )
        assert result == ((10, 15), 99)

    def test_parse_invalid_wrong_prefix(self):
        """Return None for wrong dataset prefix."""
        result = grace_download.parse_grace_short_name(
            "WRONG_PREFIX_RL06.3_V4"
        )
        assert result is None

    def test_parse_invalid_missing_version(self):
        """Return None when version part is missing."""
        result = grace_download.parse_grace_short_name(
            "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3"
        )
        assert result is None

    def test_parse_invalid_missing_release_minor(self):
        """Return None when release minor version is missing."""
        result = grace_download.parse_grace_short_name(
            "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06_V4"
        )
        assert result is None

    def test_parse_invalid_empty_string(self):
        """Return None for empty string."""
        result = grace_download.parse_grace_short_name("")
        assert result is None

    def test_parse_invalid_extra_suffix(self):
        """Return None when there's extra text after valid pattern."""
        result = grace_download.parse_grace_short_name(
            "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4_EXTRA"
        )
        assert result is None


class TestDiscoverLatestGraceCollection:
    """Tests for discover_latest_grace_collection() function."""

    @patch("grace_download.requests.get")
    @patch("grace_download.earthaccess.search_data")
    def test_discover_returns_latest_by_release_and_version(
        self, mock_search_data, mock_get
    ):
        """Discover should return the collection with highest (release, version)."""
        # Mock CMR response with multiple collections
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "hits": 3,
            "items": [
                {
                    "umm": {
                        "ShortName": "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4",
                        "DOI": {"DOI": "10.5067/TEMSC-3JC634"},
                    }
                },
                {
                    "umm": {
                        "ShortName": "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL07.0_V1",
                        "DOI": {"DOI": "10.5067/TEMSC-NEW"},
                    }
                },
                {
                    "umm": {
                        "ShortName": "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.5_V10",
                    }
                },
            ],
        }
        # Mock granule verification to return data for all collections
        mock_search_data.return_value = [MagicMock()]  # Non-empty list

        short_name, doi = grace_download.discover_latest_grace_collection(
            fallback_short_name="FALLBACK"
        )

        assert short_name == "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL07.0_V1"
        assert doi == "10.5067/TEMSC-NEW"

    @patch("grace_download.requests.get")
    @patch("grace_download.earthaccess.search_data")
    def test_discover_skips_empty_collections(self, mock_search_data, mock_get):
        """Discover should skip collections with no granules."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "hits": 2,
            "items": [
                {
                    "umm": {
                        "ShortName": "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL07.0_V1",
                    }
                },
                {
                    "umm": {
                        "ShortName": "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4",
                        "DOI": {"DOI": "10.5067/TEMSC-3JC634"},
                    }
                },
            ],
        }
        # First collection has no granules, second one does
        mock_search_data.side_effect = [[], [MagicMock()]]

        short_name, doi = grace_download.discover_latest_grace_collection(
            fallback_short_name="FALLBACK"
        )

        assert short_name == "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4"
        assert doi == "10.5067/TEMSC-3JC634"

    @patch("grace_download.requests.get")
    def test_discover_falls_back_on_network_error(self, mock_get):
        """Discover should return fallback on network error."""
        mock_get.side_effect = Exception("Network error")

        short_name, doi = grace_download.discover_latest_grace_collection(
            fallback_short_name="FALLBACK_NAME"
        )

        assert short_name == "FALLBACK_NAME"
        assert doi is None

    @patch("grace_download.requests.get")
    def test_discover_falls_back_on_empty_results(self, mock_get):
        """Discover should return fallback when no collections found."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"hits": 0, "items": []}

        short_name, doi = grace_download.discover_latest_grace_collection(
            fallback_short_name="FALLBACK_NAME"
        )

        assert short_name == "FALLBACK_NAME"
        assert doi is None

    @patch("grace_download.requests.get")
    def test_discover_falls_back_on_unparseable_names(self, mock_get):
        """Discover should return fallback when no names match regex."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "hits": 1,
            "items": [
                {
                    "umm": {
                        "ShortName": "INVALID_NAME_FORMAT",
                    }
                },
            ],
        }

        short_name, doi = grace_download.discover_latest_grace_collection(
            fallback_short_name="FALLBACK_NAME"
        )

        assert short_name == "FALLBACK_NAME"
        assert doi is None

    @patch("grace_download.requests.get")
    @patch("grace_download.earthaccess.search_data")
    def test_discover_falls_back_when_all_collections_empty(
        self, mock_search_data, mock_get
    ):
        """Discover should return fallback when all collections have no granules."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "hits": 2,
            "items": [
                {
                    "umm": {
                        "ShortName": "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL07.0_V1",
                    }
                },
                {
                    "umm": {
                        "ShortName": "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4",
                    }
                },
            ],
        }
        # All collections are empty
        mock_search_data.return_value = []

        short_name, doi = grace_download.discover_latest_grace_collection(
            fallback_short_name="FALLBACK_NAME"
        )

        assert short_name == "FALLBACK_NAME"
        assert doi is None

    @patch("grace_download.requests.get")
    @patch("grace_download.earthaccess.search_data")
    def test_discover_handles_missing_doi(self, mock_search_data, mock_get):
        """Discover should handle collections without DOI field."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "hits": 1,
            "items": [
                {
                    "umm": {
                        "ShortName": "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4",
                    }
                },
            ],
        }
        mock_search_data.return_value = [MagicMock()]

        short_name, doi = grace_download.discover_latest_grace_collection(
            fallback_short_name="FALLBACK"
        )

        assert short_name == "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4"
        assert doi is None

    @patch("grace_download.requests.get")
    @patch("grace_download.earthaccess.search_data")
    def test_discover_treats_granule_check_failure_as_valid(
        self, mock_search_data, mock_get
    ):
        """When granule check fails due to error, treat candidate as valid (optimistic)."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "hits": 1,
            "items": [
                {
                    "umm": {
                        "ShortName": "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4",
                        "DOI": {"DOI": "10.5067/TEMSC-3JC634"},
                    }
                },
            ],
        }
        # Granule check raises exception
        mock_search_data.side_effect = Exception("Network error")

        short_name, doi = grace_download.discover_latest_grace_collection(
            fallback_short_name="FALLBACK"
        )

        # Should accept the candidate optimistically
        assert short_name == "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4"
        assert doi == "10.5067/TEMSC-3JC634"
