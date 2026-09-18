import numpy as np
import pytest

from app.services import evaluation_queue, gazelle_service


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


def test_default_gaze_source_uri():
    assert evaluation_queue.default_gaze_source_uri("gs://bucket/cam_1fps.mp4") == \
        "gs://bucket/cam_gaze_5fps.mp4"
