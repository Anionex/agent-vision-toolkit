"""Optional pytest fixtures for the standalone test scripts."""

import pytest


@pytest.fixture
def mod(request):
    return request.module.load_module()


@pytest.fixture
def temp_dir(tmp_path):
    return str(tmp_path)
