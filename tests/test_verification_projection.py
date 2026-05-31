from pixelle_video.device_farm.verification.projection import ProjectionCalibration


def test_logical_point_to_ratio():
    calibration = ProjectionCalibration(
        projection_id="vivo_v2199a_001",
        raw_size=(1920, 1080),
        logical_size=(1080, 2400),
    )

    assert calibration.logical_to_ratio(540, 1200) == (0.5, 0.5)


def test_raw_to_logical_with_stretch_mapping():
    calibration = ProjectionCalibration(
        projection_id="vivo_v2199a_001",
        raw_size=(1920, 1080),
        logical_size=(1080, 2400),
    )

    assert calibration.raw_to_logical(960, 540) == (540, 1200)


def test_rejects_out_of_bounds_logical_point():
    calibration = ProjectionCalibration(
        projection_id="vivo_v2199a_001",
        raw_size=(1920, 1080),
        logical_size=(1080, 2400),
    )

    assert calibration.contains_logical_point(1079, 2399)
    assert not calibration.contains_logical_point(1080, 2400)
