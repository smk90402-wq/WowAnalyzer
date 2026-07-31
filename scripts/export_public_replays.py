from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.public_replay_export import export_public_replays


def _available_video_keys(path: Path) -> set[str]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != 1
        or not isinstance(value.get("videoKeys"), list)
        or not all(isinstance(key, str) for key in value["videoKeys"])
    ):
        raise ValueError("available video allowlist schema error")
    return set(value["videoKeys"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export sanitized static replay data for public R2 delivery.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Public output directory (replaced only after a complete export).",
    )
    parser.add_argument(
        "--private-video-map",
        type=Path,
        help=(
            "Private id-to-R2-key JSON. Must be outside --output; "
            "omit to publish no video routes."
        ),
    )
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument(
        "--available-video-keys",
        type=Path,
        help="Private JSON allowlist of video object keys confirmed in R2.",
    )
    parser.add_argument(
        "--no-terrain",
        action="store_true",
        help="Skip optional per-replay terrain grids.",
    )
    args = parser.parse_args()
    available_video_keys = (
        _available_video_keys(args.available_video_keys)
        if args.available_video_keys is not None else None
    )

    result = export_public_replays(
        args.output,
        private_video_map=args.private_video_map,
        limit=args.limit,
        include_terrain=not args.no_terrain,
        available_video_keys=available_video_keys,
    )
    print(
        f"public replay export complete: {result.replays} replays, "
        f"{result.videos} videos, {result.terrain} terrain grids"
    )
    print(f"public output: {result.output_dir}")
    if result.private_video_map:
        print(f"private video map: {result.private_video_map}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
