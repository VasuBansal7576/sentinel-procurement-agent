"""Package imports must remain safe inside deterministic workflow sandboxes."""

import subprocess
import sys


def test_package_import_does_not_eagerly_import_the_fastapi_application() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import sentinel_api; "
                "assert 'sentinel_api.app' not in sys.modules; "
                "from sentinel_api import create_app; "
                "assert callable(create_app); "
                "assert 'sentinel_api.app' in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
