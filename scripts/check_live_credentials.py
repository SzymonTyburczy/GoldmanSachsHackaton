"""Fail before billable live tests if either provider credential is missing."""

import sys

from app.settings import Settings


def main() -> int:
    settings = Settings.from_env()
    missing = []
    if settings.typesafe_api_key is None:
        missing.append("TYPESAFE_API_KEY")
    if settings.openai_api_key is None:
        missing.append("OPENAI_API_KEY")
    if missing:
        print(f"Missing live-test credentials: {', '.join(missing)}", file=sys.stderr)
        return 2
    print("Live-test credentials are configured (values not displayed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
