"""
Tests for GPU/CPU device selection on HarmoniCA (added so the fine-tuned
models actually use a GPU when one is available, e.g. when self-hosting on a
VM with a GPU, instead of always running on CPU).
"""
import pandas as pd
import pytest

from harmonica.harmonica import HarmoniCA, _auto_device

INVENTORY_COLUMNS = [
    'item_id', 'item_text', 'construct', 'questionnaire',
    'dimension', 'dimension_label', 'confidence',
    'source', 'date_added', 'model_version',
]


@pytest.fixture
def inventory_path(tmp_path):
    path = tmp_path / 'inventory.csv'
    pd.DataFrame(columns=INVENTORY_COLUMNS).to_csv(path, index=False)
    return path


def test_auto_device_returns_cpu_without_gpu():
    # CI runners (and most dev machines) have no GPU, so this should resolve
    # to 'cpu' whether or not torch itself is installed.
    assert _auto_device() == 'cpu'


def test_default_device_uses_auto_detection(tmp_path, inventory_path):
    hca = HarmoniCA(models_dir=str(tmp_path / 'models'), inventory_path=str(inventory_path))
    assert hca.device == _auto_device()


def test_explicit_device_override_is_respected(tmp_path, inventory_path):
    hca = HarmoniCA(
        models_dir=str(tmp_path / 'models'), inventory_path=str(inventory_path), device='cuda',
    )
    assert hca.device == 'cuda'

    hca_cpu = HarmoniCA(
        models_dir=str(tmp_path / 'models'), inventory_path=str(inventory_path), device='cpu',
    )
    assert hca_cpu.device == 'cpu'
