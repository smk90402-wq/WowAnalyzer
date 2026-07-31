from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import cctv_sync
from app import main


PUBLIC_ID = "0123456789abcdef01234567"


class PublicReplayRouteTests(unittest.TestCase):
    def test_public_release_status_is_safe_and_minimal(self) -> None:
        with (
            patch.object(
                main.public_replay_client,
                "configured",
                return_value=True,
            ),
            patch.object(
                main.public_replay_client,
                "release_mode",
                return_value=True,
            ),
        ):
            self.assertEqual(
                {"configured": True, "release_mode": True},
                main.public_replay_status(),
            )

    def test_known_public_detail_skips_local_lookup(self) -> None:
        payload = {"capture": {"id": PUBLIC_ID}, "duration": 180}
        with (
            patch.object(
                main.public_replay_client,
                "has_replay",
                return_value=True,
            ),
            patch.object(
                main.public_replay_client,
                "detail",
                return_value=payload,
            ),
            patch.object(
                main.local_replay,
                "replay_detail",
                side_effect=OSError("local disk unavailable"),
            ) as local_detail,
        ):
            response = main.local_replay_detail(PUBLIC_ID)

        self.assertEqual(200, response.status_code)
        self.assertIn(PUBLIC_ID.encode(), response.body)
        local_detail.assert_not_called()

    def test_public_release_list_never_touches_private_sync_or_local_replays(
        self,
    ) -> None:
        merged = {
            "sources": {"public_replays": 1},
            "rows": [{"id": PUBLIC_ID, "public_remote": True}],
        }
        with (
            patch.object(
                main.public_replay_client,
                "release_mode",
                return_value=True,
            ),
            patch.object(
                main.public_replay_client,
                "invalidate",
            ) as public_invalidate,
            patch.object(
                main.public_replay_client,
                "merge_listing",
                return_value=merged,
            ) as merge_listing,
            patch.object(
                main.local_replay,
                "list_replays",
                side_effect=AssertionError("private replay scan"),
            ) as local_listing,
            patch.object(cctv_sync, "invalidate") as private_invalidate,
        ):
            response = main.local_replay_list(limit=5, refresh=1)

        self.assertEqual(200, response.status_code)
        public_invalidate.assert_called_once_with()
        private_invalidate.assert_not_called()
        local_listing.assert_not_called()
        merge_listing.assert_called_once_with(
            {"sources": {"release_mode": True}, "rows": []},
            limit=5,
            force=True,
        )

    def test_unknown_public_release_replay_never_falls_back_to_local_disk(
        self,
    ) -> None:
        with (
            patch.object(
                main.public_replay_client,
                "release_mode",
                return_value=True,
            ),
            patch.object(
                main.public_replay_client,
                "has_replay",
                return_value=False,
            ),
            patch.object(
                main.local_replay,
                "replay_detail",
                side_effect=AssertionError("private replay detail"),
            ) as local_detail,
        ):
            with self.assertRaises(HTTPException) as raised:
                main.local_replay_detail(PUBLIC_ID)

        self.assertEqual(404, raised.exception.status_code)
        local_detail.assert_not_called()


if __name__ == "__main__":
    unittest.main()
