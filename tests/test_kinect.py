"""Kinect v1/v2 modules, tested with stand-in drivers and cameras.

No real Kinect or Kinect driver was available, so these show that the code
holds together, not that a real Kinect works. They need Open3D and are
skipped where it is missing.
"""
import os
import sys
import time

import numpy as np
import pytest

pytest.importorskip("open3d")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import fake_kinect_drivers as fakes          # noqa: E402
import kinect_camera as kc                   # noqa: E402
import camera_bridge as cb                   # noqa: E402


@pytest.fixture(autouse=True)
def _clean_modules(monkeypatch):
    saved = {name: sys.modules.get(name, "absent") for name in ("freenect", "pylibfreenect2")}
    monkeypatch.setattr(kc, "_extra_dirs_cache", [])      # never search the real machine in tests
    yield
    for name, mod in saved.items():
        if mod == "absent":
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


# ------------------------------------------------------------------ drivers missing
def test_missing_drivers_give_a_clear_error_and_never_crash():
    fakes.install(None, None)
    assert kc.Kinect1Camera.is_present() is False and kc.Kinect2Camera.is_present() is False
    status = kc.driver_status()
    assert status["freenect"][0] is False and status["pylibfreenect2"][0] is False
    assert "[missing]" in kc.driver_status_text()
    for camera in (kc.Kinect1Camera(), kc.Kinect2Camera()):
        with pytest.raises(kc.CameraError) as err:
            camera.start(log=lambda m: None)
        assert "README.md" in str(err.value)
        assert camera.get_frame() == (None, None, None)
        camera.stop()                                          # safe when never started
    with pytest.raises(kc.CameraError):
        kc.detect_and_create(log=lambda m: None)


# ------------------------------------------------------------------ Kinect v1
def test_kinect_v1_registered_frames():
    fake = fakes.make_fake_freenect(registered=True)
    fakes.install(fake, None)
    cam = kc.detect_and_create(log=lambda m: None)
    assert isinstance(cam, kc.Kinect1Camera) and cam.family == "KinectV1"
    cam.start(log=lambda m: None)
    color, depth, intrinsic = cam.get_frame()
    assert color.shape == (480, 640, 3) and color.dtype == np.uint8 and color[5, 300, 0] == 200
    assert depth.shape == (480, 640) and depth.dtype == np.uint16
    assert depth[5, 300] == 1200                    # 1.2 m, in millimetres
    assert depth[5, 50] == 0 and depth[5, 600] == 0 and depth[0, 0] == 0    # outside 0.8-3.5 m, or no data
    assert cam.depth_scale == 0.001
    assert (intrinsic.width, intrinsic.height) == (640, 480)
    assert intrinsic.get_focal_length() == (525.0, 525.0)
    assert cam.last_aligned_depth[5, 50] == 500     # the raw recorder gets ungated depth
    cam.set_range(0.3, 6.0)
    assert cam.get_frame()[1][5, 50] == 500
    cam.stop()
    assert fake.calls["stop"] == 1 and cam.get_frame() == (None, None, None)


def test_kinect_v1_falls_back_to_raw_depth():
    fakes.install(fakes.make_fake_freenect(registered=False), None)
    cam = kc.Kinect1Camera()
    notes = []
    cam.start(log=notes.append)
    assert any("NOT" in n for n in notes)            # the user is told colour and depth won't line up
    color, depth, intrinsic = cam.get_frame()
    expected_mm = 1000.0 / (800 * -0.0030711016 + 3.3309495161)
    assert abs(float(depth[5, 300]) - expected_mm) < 1.5 and depth[0, 0] == 0
    assert intrinsic.get_focal_length()[0] == pytest.approx(594.2)


def test_kinect_v1_colour_is_a_copy_not_the_drivers_buffer():
    fake = fakes.make_fake_freenect()
    fakes.install(fake, None)
    cam = kc.Kinect1Camera()
    cam.start(log=lambda m: None)
    first, _depth, _k = cam.get_frame()
    kept = first.copy()
    assert not np.shares_memory(first, fake.video_buffer)
    cam.get_frame()                                  # the driver now overwrites its buffer
    assert np.array_equal(first, kept)


def test_kinect_v1_that_cannot_be_opened_says_so():
    fake = fakes.make_fake_freenect(opens=False)
    fakes.install(fake, None)
    assert kc.Kinect1Camera.is_present() is True     # it can be counted...
    cam = kc.Kinect1Camera()
    with pytest.raises(kc.CameraError) as err:       # ...but not used, and start() says why
        cam.start(log=lambda m: None)
    assert "permission" in str(err.value) and "udev" in str(err.value)
    assert fake.calls["stop"] == 1 and cam.get_frame() == (None, None, None)


def test_kinect_v1_driver_that_cannot_start():
    fake = fakes.make_fake_freenect(init_ok=False)
    fakes.install(fake, None)
    assert kc.Kinect1Camera.is_present() is False    # and no call with a missing context
    with pytest.raises(kc.CameraError) as err:
        kc.Kinect1Camera().start(log=lambda m: None)
    assert "could not start" in str(err.value)


def test_kinect_v1_no_device():
    fakes.install(fakes.make_fake_freenect(devices=0), None)
    assert kc.Kinect1Camera.is_present() is False
    with pytest.raises(kc.CameraError):
        kc.Kinect1Camera().start(log=lambda m: None)


# ------------------------------------------------------------------ Kinect v2
@pytest.mark.parametrize("timeout_keyword", [True, False])
def test_kinect_v2_frames_are_unmirrored_and_in_rgb(timeout_keyword):
    fake = fakes.make_fake_pylibfreenect2(timeout_keyword=timeout_keyword)
    fakes.install(None, fake)
    cam = kc.detect_and_create(log=lambda m: None)
    assert isinstance(cam, kc.Kinect2Camera)
    notes = []
    cam.start(log=notes.append)
    assert fake.state["started"] and fake.state["pipeline"] == "CpuPacketPipeline"
    assert any("CPU" in n for n in notes)
    assert cam.serial == "012345" and "012345" in cam.device_info
    color, depth, intrinsic = cam.get_frame()
    assert color.shape == (424, 512, 3) and depth.shape == (424, 512) and depth.dtype == np.uint16
    assert color[100, 100].tolist() == [200, 0, 0]              # BGRX -> RGB
    # the band was on the left as delivered; unmirrored it is on the right, in both pictures
    assert depth[100, 500] == 900 and depth[100, 20] == 1500
    assert color[100, 500, 2] == 255 and color[100, 20, 2] == 0
    assert depth[0, 511] == 0                                   # the NaN reading became "no data"
    fx, fy = intrinsic.get_focal_length()
    cx, cy = intrinsic.get_principal_point()
    assert (fx, fy, cy) == (365.0, 366.0, 205.0) and cx == pytest.approx(511 - 250.0)
    assert fake.state["released"] == 1
    cam.stop()
    assert fake.state["stopped"] and cam.get_frame() == (None, None, None)


def test_kinect_v2_mirror_switch(monkeypatch):
    monkeypatch.setattr(kc, "KINECT_V2_UNMIRROR", False)
    fakes.install(None, fakes.make_fake_pylibfreenect2())
    cam = kc.Kinect2Camera()
    cam.start(log=lambda m: None)
    _color, depth, intrinsic = cam.get_frame()
    assert depth[100, 20] == 900 and intrinsic.get_principal_point()[0] == 250.0


@pytest.mark.parametrize("wanted, expected", [("", "OpenGLPacketPipeline"), ("cpu", "CpuPacketPipeline"),
                                              ("opengl", "OpenGLPacketPipeline"), ("cuda", "CpuPacketPipeline"),
                                              ("nonsense", "OpenGLPacketPipeline")])
def test_kinect_v2_pipeline_choice(monkeypatch, wanted, expected):
    monkeypatch.setenv("KINECT_V2_PIPELINE", wanted)
    fake = fakes.make_fake_pylibfreenect2(gpu=("OpenGLPacketPipeline",))
    fakes.install(None, fake)
    cam = kc.Kinect2Camera()
    cam.start(log=lambda m: None)
    assert fake.state["pipeline"] == expected
    cam.stop()


def test_v2_is_preferred_when_both_are_present():
    fakes.install(fakes.make_fake_freenect(), fakes.make_fake_pylibfreenect2())
    assert isinstance(kc.detect_and_create(log=lambda m: None), kc.Kinect2Camera)


# ------------------------------------------------------------------ the process bridge
def _frames(bridge, seconds, want=1):
    got, end = [], time.time() + seconds
    while time.time() < end and len(got) < want:
        color, depth, intrinsic = bridge.get_frame()
        if color is not None:
            got.append((color, depth, intrinsic))
    return got


def test_bridge_delivers_frames_and_range_changes(monkeypatch):
    monkeypatch.setenv("FAKE_CAM_MODE", "good")
    bridge = cb.CameraBridge(fakes.make_fake_camera)
    notes = []
    bridge.start(log=notes.append)
    try:
        assert bridge.family == "KinectV2" and bridge.serial == "FAKE" and bridge.depth_scale == 0.001
        assert bridge.guide_range == (0.5, 4.5) and bridge.native_K.shape == (3, 3)
        color, depth, intrinsic = _frames(bridge, 10)[0]
        assert color.shape == (48, 64, 3) and depth.dtype == np.uint16
        assert type(intrinsic).__name__ == "PinholeCameraIntrinsic"       # rebuilt on this side
        assert intrinsic.get_focal_length() == (60.0, 61.0) and intrinsic.width == 64
        assert depth[0, 0] == 4500                                        # the camera's own far limit
        bridge.set_range(0.4, 2.0)
        end = time.time() + 10
        while time.time() < end and _frames(bridge, 2)[0][1][0, 0] != 2000:
            pass
        assert _frames(bridge, 2)[0][1][0, 0] == 2000                     # the child got the new range
        assert bridge.last_aligned_depth is not None
        assert "fake camera started" in notes
    finally:
        bridge.stop()
    assert bridge.get_frame() == (None, None, None)


def test_bridge_reports_a_camera_that_is_not_there(monkeypatch):
    monkeypatch.setenv("FAKE_CAM_MODE", "absent")
    bridge = cb.CameraBridge(fakes.make_fake_camera)
    with pytest.raises(cb.CameraError) as err:
        bridge.start(log=lambda m: None)
    assert "No Kinect v2 found" in str(err.value) and not err.value.fatal
    bridge.stop()


def test_bridge_restarts_after_a_crash(monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_CAM_MODE", "crash_once")
    monkeypatch.setenv("FAKE_CAM_MARK", str(tmp_path / "crashed"))
    monkeypatch.setattr(cb, "RESTART_BACKOFF_S", 0.1)
    bridge = cb.CameraBridge(fakes.make_fake_camera)
    notes = []
    bridge.start(log=notes.append)
    try:
        end = time.time() + 40
        while time.time() < end and not any("restarted" in n.lower() for n in notes):
            bridge.get_frame()
        assert any("restarting" in n for n in notes) and any("restarted" in n.lower() for n in notes)
        assert _frames(bridge, 30), "no frames after the restart"
    finally:
        bridge.stop()


def test_bridge_restarts_a_hung_camera_then_gives_up(monkeypatch):
    monkeypatch.setenv("FAKE_CAM_MODE", "hang")
    monkeypatch.setattr(cb, "RESTART_BACKOFF_S", 0.05)
    monkeypatch.setattr(cb, "HEARTBEAT_TIMEOUT_S", 0.6)
    monkeypatch.setattr(cb, "MAX_CONSECUTIVE_RESTARTS", 2)
    bridge = cb.CameraBridge(fakes.make_fake_camera)
    notes = []
    bridge.start(log=notes.append)
    with pytest.raises(cb.CameraError) as err:
        end = time.time() + 60
        while time.time() < end:
            bridge.get_frame()
    assert err.value.fatal and "kept failing" in str(err.value)
    assert sum("restarting" in n for n in notes) == 2
    assert bridge.get_frame() == (None, None, None)      # after giving up it stays quiet
    bridge.stop()


def test_bridge_gives_up_on_a_camera_that_always_crashes(monkeypatch):
    monkeypatch.setenv("FAKE_CAM_MODE", "crash")
    monkeypatch.setattr(cb, "RESTART_BACKOFF_S", 0.05)
    monkeypatch.setattr(cb, "MAX_CONSECUTIVE_RESTARTS", 2)
    bridge = cb.CameraBridge(fakes.make_fake_camera)
    bridge.start(log=lambda m: None)
    with pytest.raises(cb.CameraError) as err:
        end = time.time() + 60
        while time.time() < end:
            bridge.get_frame()
    assert err.value.fatal
    bridge.stop()


def test_bridge_restarts_a_camera_that_answers_but_sends_no_picture(monkeypatch):
    monkeypatch.setenv("FAKE_CAM_MODE", "silent")
    monkeypatch.setattr(cb, "RESTART_BACKOFF_S", 0.05)
    monkeypatch.setattr(cb, "NO_PICTURE_TIMEOUT_S", 0.6)
    monkeypatch.setattr(cb, "MAX_CONSECUTIVE_RESTARTS", 2)
    bridge = cb.CameraBridge(fakes.make_fake_camera)
    notes = []
    bridge.start(log=notes.append)
    with pytest.raises(cb.CameraError) as err:
        end = time.time() + 60
        while time.time() < end:
            bridge.get_frame()
    assert err.value.fatal
    assert sum("no picture" in n for n in notes) == 2
    bridge.stop()


def test_bridge_does_not_mistake_a_busy_reader_for_a_dead_camera(monkeypatch):
    monkeypatch.setenv("FAKE_CAM_MODE", "good")
    monkeypatch.setattr(cb, "HEARTBEAT_TIMEOUT_S", 0.5)
    monkeypatch.setattr(cb, "NO_PICTURE_TIMEOUT_S", 0.8)
    bridge = cb.CameraBridge(fakes.make_fake_camera)
    notes = []
    bridge.start(log=notes.append)
    try:
        assert _frames(bridge, 10)
        time.sleep(1.5)                              # this side is busy; the camera is fine
        assert _frames(bridge, 5, want=3)
        assert not any("restarting" in n for n in notes)
    finally:
        bridge.stop()


def test_bridge_stops_quickly_and_shuts_the_camera_down(monkeypatch, tmp_path):
    mark = tmp_path / "stopped"
    monkeypatch.setenv("FAKE_CAM_MODE", "big")
    monkeypatch.setenv("FAKE_CAM_STOP_MARK", str(mark))
    bridge = cb.CameraBridge(fakes.make_fake_camera)
    bridge.start(log=lambda m: None)
    color, depth, intrinsic = _frames(bridge, 10)[0]
    assert color.shape == (480, 640, 3) and intrinsic.width == 640
    time.sleep(0.3)                                  # frames pile up against a reader that has stopped
    began = time.time()
    bridge.stop()
    assert time.time() - began < 1.5                 # was 3 seconds, ending with the process being killed
    assert mark.exists()                             # the camera's own stop() ran


def test_open3d_intrinsic_survives_the_trip():
    import open3d as o3d
    packed = cb._pack_intrinsic(o3d.camera.PinholeCameraIntrinsic(640, 480, 525.0, 526.0, 319.5, 239.5))
    assert packed == (640, 480, 525.0, 526.0, 319.5, 239.5)
    back = cb._unpack_intrinsic(packed)
    assert back.get_focal_length() == (525.0, 526.0) and back.get_principal_point() == (319.5, 239.5)
