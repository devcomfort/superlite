"""predict_calibration: least squares, leave-one-run-out run model, on synthetic runs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench"))
import predict_calibration as pc  # noqa: E402


def test_ols_recovers_a_line():
    X = [[1.0, x] for x in range(1, 8)]
    w = pc.ols(X, [30 + 12 * r[1] for r in X])
    assert abs(w[0] - 30) < 0.01 and abs(w[1] - 12) < 0.01


def test_run_models_scales_build_and_adds_phases():
    def run(build, pred, pre, post):
        return {"complete": True, "build_span_s": build, "pred_build_s": pred, "pre_build_s": pre, "post_build_s": post,
                "pred_total_s": pred + 210, "total_s": pre + build + post, "peak_agents": 4, "graph": {}}
    runs = {"a": run(500, 700, 300, 600), "b": run(520, 700, 320, 640), "c": run(480, 700, 280, 560)}
    out = {r["run"]: r for r in pc.run_models([], runs)}
    assert out["a"]["k"] == round(500 / 700 * 0 + __import__("statistics").median([520 / 700, 480 / 700]), 2)
    # the calibrated total is the median pre + k x predicted build + median post of the other two runs
    assert out["a"]["calibrated_total_s"] == round(300 + (520 / 700 + 480 / 700) / 2 * 700 + 600)
    assert abs(out["a"]["calibrated_total_s"] - out["a"]["actual_total_s"]) < abs(out["a"]["predictor_total_s"] - out["a"]["actual_total_s"])
