"""Development entrypoint for the Sentinel API."""

import uvicorn

from sentinel_api.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "sentinel_api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.environment == "development",
    )


if __name__ == "__main__":
    main()
