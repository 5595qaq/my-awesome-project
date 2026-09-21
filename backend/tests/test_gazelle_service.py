import numpy as np
import pytest

from app.services import gazelle_service


def test_model_without_inout_head_is_rejected_before_loading(monkeypatch):
    monkeypatch.setattr(gazelle_service.settings, "GAZELLE_MODEL_NAME", "gazelle_dinov2_vitb14")
    with pytest.raises(gazelle_service.GazelleModelConfigurationError, match="_inout"):
        gazelle_service.load_model()


def test_model_output_requires_inout_predictions():
    with pytest.raises(gazelle_service.GazelleModelConfigurationError, match="inout predictions"):
        gazelle_service.require_inout_output({"heatmap": object()})


def test_heatmap_peak_returns_normalized_cell_centre():
    heatmap = np.zeros((2, 4), dtype=float)
    heatmap[1, 2] = 1
    assert gazelle_service.heatmap_peak(heatmap) == pytest.approx((0.625, 0.75))


@pytest.mark.parametrize("heatmap", [np.array([]), np.array([[float("nan")]])])
def test_heatmap_peak_rejects_missing_or_invalid_predictions(heatmap):
    with pytest.raises(ValueError):
        gazelle_service.heatmap_peak(heatmap)


def test_gaze_artifact_name_is_idempotent_and_segment_specific():
    first = gazelle_service._artifact_prefix("video", {"start": "00:10", "end": "00:20"})
    assert first == gazelle_service._artifact_prefix("video", {"start": "00:10", "end": "00:20"})
    assert first != gazelle_service._artifact_prefix("video", {"start": "00:11", "end": "00:20"})
