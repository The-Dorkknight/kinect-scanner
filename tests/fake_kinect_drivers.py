"""Stand-ins for the Kinect driver modules and for cameras, used by the tests.

There is no Kinect and no build of libfreenect / libfreenect2 to test against,
so these mimic the parts of their Python interfaces that kinect_camera.py
uses, as described in those projects' own documentation. Passing these tests
shows the app-side logic holds together; it does not show a real Kinect works.
"""
import os
import sys
import time
import types

import numpy as np

# ------------------------------------------------------------------ Kinect v1: "freenect"
V1_H, V1_W = 480, 640


def make_fake_freenect(devices=1, registered=True, opens=True, init_ok=True):
    """opens=False: the camera is counted but cannot be opened (as with no
    permission), so the frame calls answer None. init_ok=False: init() answers
    None, as the real one does when its USB set-up fails."""
    mod = types.ModuleType("freenect")
    mod.DEPTH_11BIT, mod.VIDEO_RGB = 0, 0
    if registered:
        mod.DEPTH_REGISTERED = 4
    mod.calls = dict(depth=0, video=0, stop=0, shutdown=0)
    mod.init = lambda: object() if init_ok else None

    def num_devices(ctx):
        assert ctx is not None, "the real driver would crash here"
        return devices

    mod.num_devices = num_devices
    mod.shutdown = lambda ctx: mod.calls.__setitem__("shutdown", mod.calls["shutdown"] + 1)
    mod.video_buffer = np.zeros((V1_H, V1_W, 3), np.uint8)    # the driver's own, reused every call

    def sync_get_depth(index=0, fmt=0):
        mod.calls["depth"] += 1
        if not opens:
            return None
        if registered and fmt == 4:                  # millimetres, lined up with colour
            depth = np.full((V1_H, V1_W), 1200, np.uint16)
            depth[:, :100] = 500                     # too near for the default range
            depth[:, -100:] = 5000                   # too far
            depth[0, 0] = 0
            return depth, 123
        raw = np.full((V1_H, V1_W), 800, np.uint16)  # raw 11-bit values
        raw[0, 0] = 2047                             # "no reading"
        return raw, 123

    def sync_get_video(index=0, fmt=0):
        mod.calls["video"] += 1
        if not opens:
            return None
        img = mod.video_buffer
        img[...] = 0
        img[..., 0] = 200                            # red, so RGB order can be checked
        img[..., 1] = mod.calls["video"] % 200       # differs from one picture to the next
        return img, 123

    mod.sync_get_depth, mod.sync_get_video = sync_get_depth, sync_get_video
    mod.sync_stop = lambda: mod.calls.__setitem__("stop", mod.calls["stop"] + 1)
    return mod


# ------------------------------------------------------------------ Kinect v2: "pylibfreenect2"
V2_H, V2_W = 424, 512


def make_fake_pylibfreenect2(devices=1, timeout_keyword=True, gpu=()):
    """gpu: names of graphics pipelines this "build" has, e.g. ("OpenGLPacketPipeline",)."""
    mod = types.ModuleType("pylibfreenect2")
    mod.state = dict(started=False, stopped=False, released=0, pipeline=None)

    class FrameType:
        Color, Ir, Depth = 1, 2, 4

    class Frame:
        def __init__(self, width, height, bpp):
            self.width, self.height, self.bpp = width, height, bpp
            self.data = None

        def asarray(self, dtype=np.uint8):
            return np.asarray(self.data, dtype=dtype)

    class Params:
        fx, fy, cx, cy = 365.0, 366.0, 250.0, 205.0

    class Device:
        def setColorFrameListener(self, listener): pass
        def setIrAndDepthFrameListener(self, listener): pass
        def start(self): mod.state["started"] = True
        def stop(self): mod.state["stopped"] = True
        def close(self): pass
        def getIrCameraParams(self): return Params()
        def getColorCameraParams(self): return Params()

    class Freenect2:
        def enumerateDevices(self): return devices
        def getDeviceSerialNumber(self, index): return b"012345"

        def openDevice(self, serial, pipeline=None):
            mod.state["pipeline"] = type(pipeline).__name__
            return Device()

    class SyncMultiFrameListener:
        def __init__(self, kinds): self.kinds = kinds

        def _frames(self):
            return {"color": Frame(1920, 1080, 4), "depth": Frame(V2_W, V2_H, 4)}

        if timeout_keyword:
            def waitForNewFrame(self, frame_map=None, milliseconds=-1):
                return self._frames()
        else:
            def waitForNewFrame(self, frame_map=None):
                return self._frames()

        def release(self, frames): mod.state["released"] += 1

    class Registration:
        def __init__(self, ir, color): pass

        def apply(self, color, depth, undistorted, registered):
            d = np.full((V2_H, V2_W), 1500.0, np.float32)     # millimetres
            d[:, :50] = 900.0                                 # a band on the LEFT as delivered (mirrored)
            d[0, 0] = np.nan
            undistorted.data = d
            bgrx = np.zeros((V2_H, V2_W, 4), np.uint8)
            bgrx[..., 2] = 200                                # red, in BGRX order
            bgrx[:, :50, 0] = 255                             # blue band on the same side
            registered.data = bgrx

    class CpuPacketPipeline:
        pass

    for gpu_name in gpu:
        setattr(mod, gpu_name, type(gpu_name, (), {}))
    for name, obj in dict(FrameType=FrameType, Frame=Frame, Freenect2=Freenect2, Registration=Registration,
                          SyncMultiFrameListener=SyncMultiFrameListener,
                          CpuPacketPipeline=CpuPacketPipeline).items():
        setattr(mod, name, obj)
    return mod


def install(freenect=None, pylibfreenect2=None):
    """Put the fakes (or absence) in place. None = make the import fail."""
    for name, mod in (("freenect", freenect), ("pylibfreenect2", pylibfreenect2)):
        sys.modules[name] = mod          # a None entry makes "import name" raise ImportError


# ------------------------------------------------------------------ stand-in cameras for the bridge
class _Intrinsic:                        # the same four calls an Open3D intrinsic answers
    width, height = 64, 48
    def get_focal_length(self): return (60.0, 61.0)
    def get_principal_point(self): return (31.5, 23.5)


class FakeCamera:
    """Behaviour is chosen by the FAKE_CAM_MODE environment variable, because
    the camera is created inside the child process:
      good        frames keep coming
      absent      start() fails
      crash_once  the process dies on its fifth frame, once (marker file), then behaves
      crash       the process dies on its fifth frame, every time
      hang        get_frame() never returns
      silent      get_frame() answers, but never with a picture (a stalled stream)
      big         full-size 640x480 frames, as a real camera sends
    If FAKE_CAM_STOP_MARK names a file, stop() creates it.
    """
    family, serial, device_info = "KinectV2", "FAKE", "Fake camera"
    depth_scale, guide_range = 0.001, (0.5, 4.5)

    def __init__(self):
        self.mode = os.environ.get("FAKE_CAM_MODE", "good")
        self.near_m, self.far_m = self.guide_range
        self.native_K = [[60.0, 0, 31.5], [0, 61.0, 23.5], [0, 0, 1.0]]
        self.count = 0

    def start(self, log=print):
        if self.mode == "absent":
            raise RuntimeError("No Kinect v2 found.")
        log("fake camera started")

    def set_range(self, near_m, far_m):
        self.near_m, self.far_m = near_m, far_m

    def get_frame(self):
        self.count += 1
        if self.mode == "crash" and self.count >= 5:
            os._exit(3)
        if self.mode == "crash_once" and self.count >= 5:
            mark = os.environ["FAKE_CAM_MARK"]
            if not os.path.exists(mark):
                open(mark, "w").close()
                os._exit(3)
        if self.mode == "hang":
            time.sleep(3600)
        time.sleep(0.01)
        if self.mode == "silent":
            return None, None, None
        if self.mode == "big":
            return (np.zeros((480, 640, 3), np.uint8), np.full((480, 640), 1000, np.uint16),
                    (640, 480, 525.0, 525.0, 319.5, 239.5))
        color = np.full((48, 64, 3), self.count % 250, np.uint8)
        depth = np.full((48, 64), int(self.far_m * 1000), np.uint16)   # shows which range the child holds
        return color, depth, _Intrinsic()

    def stop(self):
        mark = os.environ.get("FAKE_CAM_STOP_MARK")
        if mark:
            open(mark, "w").close()


def make_fake_camera():
    return FakeCamera()
