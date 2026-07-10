"""图片比较引擎的指标、阈值和尺寸边界。"""
from PIL import Image

from app.compare import compare_images
from app.service import classify


def _save(path, pixels, size):
    image = Image.new("RGB", size)
    image.putdata(pixels)
    image.save(path, format="PNG")


def test_identical_images_have_zero_diff_and_perfect_similarity(tmp_path):
    current = tmp_path / "current.png"
    baseline = tmp_path / "baseline.png"
    heatmap = tmp_path / "heat.webp"
    pixels = [(20, 40, 60)] * 12
    _save(current, pixels, (4, 3))
    _save(baseline, pixels, (4, 3))

    metrics = compare_images(str(current), str(baseline), str(heatmap))

    assert metrics["diff_pct"] == 0.0
    assert metrics["diff_pixels"] == 0
    assert metrics["ssim"] == 1.0
    assert metrics["psnr"] == 99.0
    assert heatmap.is_file()
    with Image.open(heatmap) as rendered:
        assert rendered.format == "WEBP"
        assert rendered.size == (4, 3)


def test_pixel_threshold_is_strictly_greater_than_boundary(tmp_path):
    current = tmp_path / "current.png"
    baseline = tmp_path / "baseline.png"
    heatmap = tmp_path / "heat.webp"
    _save(current, [(8, 0, 0), (9, 0, 0)], (2, 1))
    _save(baseline, [(0, 0, 0), (0, 0, 0)], (2, 1))

    metrics = compare_images(
        str(current), str(baseline), str(heatmap),
        pixel_threshold=8,
    )

    assert metrics["diff_pixels"] == 1
    assert metrics["total_pixels"] == 2
    assert metrics["diff_pct"] == 50.0
    assert metrics["channel_diff"] == {"R": 50.0, "G": 0.0, "B": 0.0}


def test_baseline_is_resized_to_current_dimensions(tmp_path):
    current = tmp_path / "current.png"
    baseline = tmp_path / "baseline.png"
    heatmap = tmp_path / "heat.webp"
    _save(current, [(10, 20, 30)] * 8, (4, 2))
    _save(baseline, [(10, 20, 30)] * 2, (2, 1))

    metrics = compare_images(str(current), str(baseline), str(heatmap))

    assert metrics["total_pixels"] == 8
    assert metrics["diff_pct"] == 0.0
    with Image.open(heatmap) as rendered:
        assert rendered.size == (4, 2)


def test_classification_threshold_boundaries():
    assert classify(2.0, fail_threshold=2.0, warn_threshold=0.3) == "fail"
    assert classify(0.3, fail_threshold=2.0, warn_threshold=0.3) == "warn"
    assert classify(0.2999, fail_threshold=2.0, warn_threshold=0.3) == "pass"
