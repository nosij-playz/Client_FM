import argparse
import os

from .main import FMClient


DEFAULT_MYSQL_HOST = "mysql-2367c49a-radio-65e8.d.aivencloud.com"
DEFAULT_MYSQL_PORT = 14239
DEFAULT_MYSQL_USER = "avnadmin"
DEFAULT_MYSQL_PASSWORD = "AVNS_H78iyks9IERyxay-J86"
DEFAULT_MYSQL_DATABASE = "defaultdb"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

    parser.add_argument("--state", default="client_state.json")
    parser.add_argument("--poll", type=int, default=3)
    parser.add_argument("--default-duration", type=int, default=180)

    # Fixed-row music mode (your DB updates id=1 continuously)
    parser.add_argument("--music-id", type=int, default=1)
    parser.add_argument("--music-watch-interval", type=float, default=1.0)

    parser.add_argument("--mysql-host", default=os.getenv("MYSQL_HOST", DEFAULT_MYSQL_HOST))
    parser.add_argument("--mysql-port", type=int, default=int(os.getenv("MYSQL_PORT", DEFAULT_MYSQL_PORT)))
    parser.add_argument("--mysql-user", default=os.getenv("MYSQL_USER", DEFAULT_MYSQL_USER))
    parser.add_argument("--mysql-password", default=os.getenv("MYSQL_PASSWORD", DEFAULT_MYSQL_PASSWORD))
    parser.add_argument("--mysql-database", default=os.getenv("MYSQL_DATABASE", DEFAULT_MYSQL_DATABASE))
    parser.add_argument("--mysql-timeout", type=int, default=10)

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
        state_path=args.state,
        poll_interval=args.poll,
        default_duration=args.default_duration,
        music_id=args.music_id,
        music_watch_interval=args.music_watch_interval,
    )

    client.run()
