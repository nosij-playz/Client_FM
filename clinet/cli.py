import argparse
import os

from .main import FMClient


DEFAULT_MYSQL_HOST = os.getenv("MYSQL_HOST", "")
DEFAULT_MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306") or 3306)
DEFAULT_MYSQL_USER = os.getenv("MYSQL_USER", "")
DEFAULT_MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
DEFAULT_MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

    parser.add_argument("--state", default="client_state.json")
    parser.add_argument("--poll", type=int, default=3)
    parser.add_argument("--default-duration", type=int, default=180)

    # Fixed-row music mode (your DB updates id=1 continuously)
    parser.add_argument("--music-id", type=int, default=1)
    parser.add_argument("--music-watch-interval", type=float, default=1.5)

    parser.add_argument("--status-watch-interval", type=float, default=2.0)
    parser.add_argument("--alert-check-interval", type=float, default=1.5)

    parser.add_argument("--no-tts", action="store_true", help="Disable TTS generation/playback")
    parser.add_argument(
        "--no-duration-detect",
        action="store_true",
        help="Disable yt-dlp duration detection (uses DB duration or --default-duration)",
    )

    parser.add_argument("--mysql-host", default=DEFAULT_MYSQL_HOST)
    parser.add_argument("--mysql-port", type=int, default=DEFAULT_MYSQL_PORT)
    parser.add_argument("--mysql-user", default=DEFAULT_MYSQL_USER)
    parser.add_argument("--mysql-password", default=DEFAULT_MYSQL_PASSWORD)
    parser.add_argument("--mysql-database", default=DEFAULT_MYSQL_DATABASE)
    parser.add_argument("--mysql-timeout", type=int, default=10)
    parser.add_argument("--mysql-pool-size", type=int, default=int(os.getenv("MYSQL_POOL_SIZE", "3") or 3))

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    client = FMClient(
        mysql_host=args.mysql_host,
        mysql_port=args.mysql_port,
        mysql_user=args.mysql_user,
        mysql_password=args.mysql_password,
        mysql_database=args.mysql_database,
        mysql_timeout=args.mysql_timeout,
        mysql_pool_size=args.mysql_pool_size,
        state_path=args.state,
        poll_interval=args.poll,
        default_duration=args.default_duration,
        music_id=args.music_id,
        music_watch_interval=args.music_watch_interval,
        status_watch_interval=args.status_watch_interval,
        alert_check_interval=args.alert_check_interval,
        enable_tts=(not args.no_tts),
        enable_duration_detect=(not args.no_duration_detect),
    )

    client.run()
