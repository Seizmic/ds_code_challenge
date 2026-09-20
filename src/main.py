"""Pipeline entrypoint.

Runs end to end with no human interaction, as the challenge requires:

    python -m src.main
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src import config, extract_hex, reporting, s3_io, transform_join
from src.logging_setup import MANIFEST, configure_logging, timed

logger = logging.getLogger("src.main")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="City of Cape Town DS code challenge -- Sections 1 and 2.",
    )
    parser.add_argument(
        "--section", choices=["1", "2", "all"], default="all",
        help="Which section to run (default: all).",
    )
    parser.add_argument(
        "--baseline", action="store_true",
        help="Also run the naive full-download baseline for Section 1. "
             "Transfers 108 MB; off by default.",
    )
    parser.add_argument(
        "--join-method", choices=list(config.JOIN_METHODS), default=None,
        help="Which assignment to publish. Default comes from "
             "config.JOIN_METHOD (currently %(default)s -> geometric).",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=None,
        help="Write all data and artifacts beneath this directory instead of "
             "./data. Use it to keep two runs side by side, since both "
             "--join-method settings otherwise write the same filename.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(logging.DEBUG if args.verbose else logging.INFO)
    if args.data_dir:
        config.set_data_dir(args.data_dir)
    config.ensure_directories()
    if args.join_method:
        config.JOIN_METHOD = args.join_method

    logger.info("=" * 78)
    logger.info("City of Cape Town DS code challenge -- Sections 1 and 2")
    logger.info("=" * 78)

    exit_code = 0
    try:
        with timed("pipeline.total", logger):
            client = s3_io.make_s3_client()

            hex_features = None
            if args.section in {"1", "all"}:
                logger.info("--- Section 1: Data Extraction ---")
                hex_features = extract_hex.run(client, run_baseline=args.baseline)["features"]

            if args.section in {"2", "all"}:
                logger.info("--- Section 2: Initial Data Transformation ---")
                transform_join.run(client, hex_features=hex_features)

    except Exception as exc:  # noqa: BLE001 - top-level handler reports and exits
        logger.error("Pipeline FAILED: %s", exc, exc_info=True)
        MANIFEST.record_verdict("pipeline", False, str(exc))
        exit_code = 1
    else:
        MANIFEST.record_verdict("pipeline", True, "completed")

    manifest_path = MANIFEST.write()
    logger.info("Run manifest written to %s", manifest_path)

    # The results document is generated from the manifest rather than written
    # by hand, so it cannot drift from what the run actually did.
    if args.section == "all" and exit_code == 0:
        try:
            reporting.generate(MANIFEST.data)
        except Exception as exc:  # noqa: BLE001 - reporting must not fail the run
            logger.warning("Could not generate the results document: %s", exc)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
