#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# kinect_camera.py -- Kinect v1 / Kinect v2 camera backends for kinect_scanner_app.py
#
# v0.2.0-wip: a bug report from a sibling chat (working on realsense-scanner,
# which imported this module as an optional camera backend) found and fixed
# 14 real faults in v0.1.0-wip -- found by running this code against hand-
# built stand-in driver modules (fake_kinect_drivers.py in tests/) and by
# reading libfreenect's and pylibfreenect2's own source, not just by reading
# this file. See CHANGELOG.md for the list. Every one of those fixes is
# applied here, and the test suite that caught them is ported into tests/
# and passes against this file.
#
# That said: WORK IN PROGRESS. The tests prove this code holds together
# against driver modules that MIMIC freenect/pylibfreenect2's documented
# behaviour -- they do not prove a real Kinect works, because there is still
# no real sensor or real driver build on either side of this fix. Treat the
# first real run on each platform as a debugging session.
#
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE.md). No warranty.
#
"""
Deliberately mirrors the camera-object contract used by SR305Camera in the
sibling realsense-scanner project (same author), so that:
  (a) the scanning engine (ScanSession / QualityParams / build_mesh, ported
      into kinect_scanner_app.py) can stay camera-agnostic, and
  (b) true integration into realsense-scanner (one app, one camera dropdown,
      RealSense or Kinect) would be a small amount of glue, not a rewrite,
      if that is ever wanted. Not done here; this module only promises the
      same shape -- and in fact a fix for these same two files, independently
      written for realsense-scanner's own camera slot, is where this
      release's bug fixes came from (see CHANGELOG.md).

Contract (what kinect_scanner_app.py relies on):
    cam = KinectXCamera()                # or kinect_camera.detect_and_create(log=...)
    cam.start(log=print)                 # raises CameraError on failure
    color, depth, intrinsic = cam.get_frame()
        color:     np.uint8, HxWx3, RGB order
        depth:     np.uint16, HxW, in units of cam.depth_scale metres (0 = no data)
        intrinsic: o3d.camera.PinholeCameraIntrinsic, matches depth's HxW
        -- or (None, None, None) if a frame could not be read this call.
    cam.depth_scale                      # float, metres per depth unit
    cam.guide_range                       # (near_m, far_m) for the UI's distance guide
    cam.near_m / cam.far_m                # mutable directly, or via cam.set_range(...)
    cam.device_info                       # human-readable string, for logging/UI
    cam.family                            # "KinectV1" / "KinectV2", for messages/tests
    cam.serial                            # device serial, where the driver reports one
    cam.stop()
"""

import importlib
import json
import os
import shutil
import subprocess
import sys

import numpy as np

try:
    import open3d as o3d
except ImportError as exc:
    raise ImportError("open3d is required (pip install open3d)") from exc

MODULE_VERSION = "0.2.0-wip"

# Best-effort USB identification, for the "what did I find" message only --
# NOT used to decide which driver to call (see detect_and_create below,
# which asks each driver library directly instead of trusting a PID table).
KINECT_VID = 0x045E
KINECT_V1_PIDS = {0x02AE: "Kinect for Xbox 360 (camera)", 0x02AD: "Kinect for Xbox 360 (audio)",
                  0x02B0: "Kinect for Xbox 360 (motor)", 0x02BF: "Kinect for Windows (camera)"}
KINECT_V2_PIDS = {0x02C4: "Kinect for Windows v2 (pre-firmware-upload mode)",
                  0x02D8: "Kinect for Windows v2", 0x02D9: "Kinect for Windows v2 (alt mode)"}

# Kinect v1's RGB and IR/depth cameras are two separate sensors with two
# separate fields of view; registered depth (lined up with colour) belongs
# to the RGB camera's view, raw/unregistered depth to the IR camera's. Both
# are the commonly published default calibrations used across the
# OpenKinect/libfreenect community when a unit's own factory calibration
# isn't read back -- an approximation, not a per-unit figure.
KINECT_V1_RGB_K = (525.0, 525.0, 319.5, 239.5)      # registered depth's view
KINECT_V1_DEPTH_K = (594.2, 591.0, 339.5, 242.7)    # raw depth's (IR camera's) view
KINECT_V1_SIZE = (640, 480)
KINECT_V2_SIZE = (512, 424)

GUIDE_RANGE_KINECT_V1 = (0.8, 3.5)   # Kinect v1's practical sweet spot
GUIDE_RANGE_KINECT_V2 = (0.5, 4.5)   # Kinect v2's practical sweet spot

# libfreenect2 hands out frames mirrored left-to-right (as a mirror facing
# the sensor would show them), matching the Kinect v2 hardware itself. Left
# unmirrored, a scan comes out mirrored. UNVERIFIED on real hardware -- if a
# Kinect v2 scan looks mirrored, set this False (or see test_kinect.py for
# how to check it against a real frame).
KINECT_V2_UNMIRROR = True


class CameraError(RuntimeError):
    """Raised when a Kinect camera can't be found or started.

    fatal=True (only ever raised by camera_bridge.CameraBridge, never by the
    camera classes below) means the bridge has given up retrying and the
    camera should be treated as stopped, not just hiccuping.
    """

    def __init__(self, message, fatal=False):
        super().__init__(message)
        self.fatal = fatal


# ===========================================================================
# Finding the driver modules
# ===========================================================================
# kinect_scanner_app.py runs inside its own private venv (kinect_env/, built
# with --system-site-packages), which sees system-installed packages but
# only if they were built against the SAME Python version/installation that
# venv was created from. A hand-built `freenect` or `pylibfreenect2` living
# under a *different* Python (common: the driver was built against whatever
# `python3` happened to be on $PATH at the time) would otherwise be
# invisible. So when the normal import fails, other Pythons on this machine
# are asked where THEY would look for packages, and -- only for a folder
# that actually contains the module -- that folder is appended (never
# prepended) to sys.path, so nothing this app already uses can be shadowed.

_PROBE = ("import sys, site, json; "
          "print(json.dumps({'v': list(sys.version_info[:2]), "
          "'p': list(getattr(site, 'getsitepackages', lambda: [])()) + [site.getusersitepackages()]}))")
_extra_dirs_cache = None


def _extra_site_dirs():
    global _extra_dirs_cache
    if _extra_dirs_cache is not None:
        return _extra_dirs_cache
    dirs = [p for p in os.environ.get("KINECT_DRIVER_PATH", "").split(os.pathsep) if p]
    seen = set()
    candidates = [getattr(sys, "_base_executable", None), shutil.which("python3"), shutil.which("python")]
    for exe in candidates:
        if not exe or exe in seen or os.path.realpath(exe) == os.path.realpath(sys.executable):
            continue
        seen.add(exe)
        try:
            out = subprocess.run([exe, "-c", _PROBE], capture_output=True, text=True, timeout=10).stdout
            info = json.loads(out.strip().splitlines()[-1])
        except Exception:
            continue
        if tuple(info.get("v", ())) != tuple(sys.version_info[:2]):
            continue                      # a compiled module only loads into the same Python version
        dirs += [p for p in info.get("p", []) if p]
    for extra in ("/usr/local/lib/python3/dist-packages", "/usr/lib/python3/dist-packages"):
        dirs.append(extra)
    _extra_dirs_cache = [d for i, d in enumerate(dirs) if d and d not in dirs[:i]]
    return _extra_dirs_cache


def _holds_module(folder, name):
    try:
        return any(entry == name or entry.startswith(name + ".") for entry in os.listdir(folder))
    except OSError:
        return False


def import_driver(name):
    """Import a Kinect driver module ("freenect" or "pylibfreenect2"),
    looking outside this app's private environment if the normal import
    fails. Raises ImportError (the original one, if none of the fallback
    folders work either)."""
    try:
        return importlib.import_module(name)
    except ImportError as first:
        for folder in _extra_site_dirs():
            if folder in sys.path or not _holds_module(folder, name):
                continue
            sys.path.append(folder)
            importlib.invalidate_caches()
            try:
                return importlib.import_module(name)
            except ImportError:
                sys.path.remove(folder)
        raise first


def driver_status():
    """{'freenect': (ok, note), 'pylibfreenect2': (ok, note)} -- never raises."""
    status = {}
    for name in ("freenect", "pylibfreenect2"):
        try:
            module = import_driver(name)
            status[name] = (True, getattr(module, "__file__", "") or "built in")
        except Exception as exc:
            status[name] = (False, str(exc))
    return status


def driver_status_text():
    status = driver_status()
    lines = ["Kinect drivers (this app does not install these -- see README.md):", ""]
    for name, label in (("freenect", "Kinect v1 (libfreenect, module 'freenect')"),
                        ("pylibfreenect2", "Kinect v2 (libfreenect2, module 'pylibfreenect2')")):
        ok, note = status[name]
        lines.append(f"  {'[found]  ' if ok else '[missing]'} {label}" + ("" if ok else f"\n             {note}"))
    return "\n".join(lines)


def _usb_hint():
    """Best-effort list of Kinect-looking USB devices, for the error message
    only. Uses pyusb if available; silently gives nothing if not (not a
    required dependency)."""
    try:
        import usb.core
    except ImportError:
        return "  (no USB listing: the optional 'pyusb' package is not installed)"
    found = []
    try:
        for dev in usb.core.find(find_all=True):
            vid, pid = getattr(dev, "idVendor", None), getattr(dev, "idProduct", None)
            if vid == KINECT_VID and pid in KINECT_V1_PIDS:
                found.append(f"  USB {vid:04x}:{pid:04x}  looks like {KINECT_V1_PIDS[pid]}")
            elif vid == KINECT_VID and pid in KINECT_V2_PIDS:
                found.append(f"  USB {vid:04x}:{pid:04x}  looks like {KINECT_V2_PIDS[pid]}")
    except Exception as exc:
        return f"  (could not list USB devices: {exc})"
    return "\n".join(found) if found else "  (no Kinect-looking USB device seen)"


def diagnose_no_camera():
    return "\n".join([
        "No Kinect v1 or v2 was found by either driver.", "", _usb_hint(), "",
        "Checklist:",
        "  - Kinect v2 needs a real USB 3 port (blue socket) -- USB 2 is not enough bandwidth",
        "    and the device will not enumerate correctly.",
        "  - Kinect v1 needs its own 12V power supply as well as USB -- the USB cable alone",
        "    does not power it.",
        "  - Linux: the driver's udev rule must be installed, then log out and in. Without",
        "    it the camera can be seen (counted) but not opened.",
        "  - Windows: Kinect v2 needs the libusbK driver bound via Zadig, NOT the official",
        "    Kinect for Windows SDK driver (they conflict) -- see README.md.",
        "  - macOS: there is no official Kinect v2 driver; only the community libfreenect2",
        "    build is supported, and it is the least-tested path here.",
        "  - The drivers are installed by hand -- see README.md -> Install the Kinect driver.",
        "  - If this is a repeat disconnect rather than 'never worked', try Diagnose USB...",
        "    (Linux only, uses whoareyousb) for flaky-connection / USB-speed diagnostics.",
        "", driver_status_text()])


def _intrinsic(size, k):
    return o3d.camera.PinholeCameraIntrinsic(size[0], size[1], k[0], k[1], k[2], k[3])


class _KinectBase:
    """What both Kinect cameras share, including a few attributes that are
    inert here but keep the interface complete for a future caller that
    pokes at it with getattr/hasattr (matching realsense-scanner's own
    SR305Camera, which has no real Kinect equivalent for these)."""

    family = "Kinect"

    def __init__(self, guide_range):
        self.device_info = ""
        self.serial = None
        self.depth_scale = 0.001            # both drivers report millimetres
        self.guide_range = guide_range
        self.near_m, self.far_m = guide_range
        self.native_K = None
        self.last_raw_depth = None
        self.last_aligned_depth = None
        # Inert, for interface parity -- no Kinect equivalent.
        self.confidence = None
        self.bad_mask = None
        self.mask_serial = None
        self.use_mask = False
        self.want_ir = False
        self.has_ir = False
        self.last_ir = None

    def set_range(self, near_m, far_m):
        self.near_m, self.far_m = float(near_m), float(far_m)

    def apply_settings(self, log=print):
        pass  # no equivalent control on either Kinect generation

    def _gate(self, depth_mm):
        """Depth in millimetres -> uint16, with everything outside Near/Far
        zeroed, and NaN/inf (Kinect v2's Registration can emit these for
        unknown pixels) treated as 'no data' rather than left to explode the
        uint16 cast."""
        depth_mm = np.nan_to_num(np.asarray(depth_mm, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        self.last_aligned_depth = np.clip(depth_mm, 0, 65535).astype(np.uint16)
        near, far = self.near_m / self.depth_scale, self.far_m / self.depth_scale
        return np.where((depth_mm > near) & (depth_mm < far), depth_mm, 0).astype(np.uint16)


# ===========================================================================
# Kinect v1 (libfreenect / "freenect" python wrapper)
# ===========================================================================

class Kinect1Camera(_KinectBase):
    """Kinect for Xbox 360 / Kinect for Windows (v1), via the `freenect`
    ctypes wrapper bundled with libfreenect's wrappers/python.

    UNTESTED against real hardware -- see the module docstring.
    """

    family = "KinectV1"

    def __init__(self):
        super().__init__(GUIDE_RANGE_KINECT_V1)
        self._freenect = None
        self._registered = False
        self._k = KINECT_V1_RGB_K

    @staticmethod
    def is_present():
        """Best-effort, fast 'is there a Kinect v1 the freenect driver can
        see' check, used by detect_and_create(). Must not raise."""
        try:
            freenect = import_driver("freenect")
            ctx = freenect.init()
            if ctx is None:          # libfreenect's own start-up failed
                return False
            try:
                return freenect.num_devices(ctx) > 0
            finally:
                try:
                    freenect.shutdown(ctx)
                except Exception:
                    pass
        except Exception:
            return False

    def start(self, log=print):
        try:
            freenect = import_driver("freenect")
        except ImportError as exc:
            raise CameraError(
                "The Kinect v1 driver module 'freenect' (part of libfreenect) was not found.\n\n"
                + driver_status_text()) from exc

        try:
            ctx = freenect.init()
            if ctx is None:          # init() answers None when its USB set-up fails
                raise RuntimeError("its USB set-up failed")
            count = freenect.num_devices(ctx)
            try:
                freenect.shutdown(ctx)
            except Exception:
                pass
        except Exception as exc:
            raise CameraError(f"libfreenect could not start: {exc}\n\n{diagnose_no_camera()}") from exc
        if count <= 0:
            raise CameraError("No Kinect v1 device found.\n\n" + diagnose_no_camera())

        log(f"Found {count} Kinect v1 device(s) -- using the first.")
        self._freenect = freenect
        self.device_info = "Kinect v1 (Xbox 360 / Kinect for Windows)"

        # Prefer depth already registered (aligned) to the colour camera and
        # reported in millimetres -- matches this module's contract with no
        # extra work. Not every libfreenect build/platform exposes this.
        self._registered = False
        mode = getattr(freenect, "DEPTH_REGISTERED", None)
        if mode is not None:
            try:
                result = freenect.sync_get_depth(0, mode)
                self._registered = result is not None and result[0] is not None
            except Exception as exc:
                log(f"  (registered depth mode failed: {exc})")
        if not self._registered:
            # Raw depth exists in every build. If THIS also gives nothing,
            # the camera is being counted but can't actually be opened --
            # say so now rather than leaving the picture black forever.
            try:
                result = freenect.sync_get_depth(0, freenect.DEPTH_11BIT)
            except Exception as exc:
                log(f"  (raw depth mode failed: {exc})")
                result = None
            if result is None or result[0] is None:
                self.stop()
                raise CameraError(
                    "A Kinect v1 was found but gave no depth picture. This usually means it could "
                    "not be opened: no permission to use it (on Linux, check the driver's udev rule "
                    "-- see README.md), or another program already has it open.\n\n"
                    + diagnose_no_camera())

        if self._registered:
            self._k = KINECT_V1_RGB_K
            log("Using registered (colour-aligned) depth mode.")
        else:
            self._k = KINECT_V1_DEPTH_K
            log("  (registered depth mode not available -- falling back to raw 11-bit depth, which "
                "is NOT aligned to the colour image. Expect a visible offset between the depth and "
                "colour pictures.)")
        self.native_K = np.array([[self._k[0], 0, self._k[2]], [0, self._k[1], self._k[3]], [0, 0, 1.0]])

    @staticmethod
    def _raw_to_mm(raw11):
        """Approximate conversion from Kinect v1's raw 11-bit disparity-like
        depth value to millimetres, when registered depth isn't available.
        Constants are the ones long published across OpenKinect/libfreenect
        community code; treat as an approximation, not a factory calibration."""
        raw = np.asarray(raw11).astype(np.float32)
        with np.errstate(divide="ignore", invalid="ignore"):
            mm = 1000.0 / (raw * -0.0030711016 + 3.3309495161)
        mm[(raw >= 2047) | ~np.isfinite(mm) | (mm < 0)] = 0
        return mm

    def get_frame(self):
        freenect = self._freenect
        if freenect is None:
            return None, None, None
        try:
            if self._registered:
                got = freenect.sync_get_depth(0, freenect.DEPTH_REGISTERED)
                depth_mm = None if got is None else np.asarray(got[0], dtype=np.float32)
            else:
                got = freenect.sync_get_depth(0, freenect.DEPTH_11BIT)
                depth_mm = None if got is None else self._raw_to_mm(got[0])
            video = freenect.sync_get_video(0, freenect.VIDEO_RGB)
        except Exception:
            return None, None, None
        if depth_mm is None or video is None or video[0] is None:
            return None, None, None

        # A copy, not a view: the driver hands back its OWN buffer and
        # overwrites it on the next call, so without copying here a frame
        # already handed to the caller (or mid-way through being sent across
        # camera_bridge.py's queue) could change under it or tear between
        # two frames.
        color = np.array(video[0], dtype=np.uint8, order="C", copy=True)
        if color.ndim != 3 or color.shape[:2] != depth_mm.shape[:2]:
            return None, None, None

        self.last_raw_depth = depth_mm
        depth = self._gate(depth_mm)
        return color, depth, _intrinsic((depth.shape[1], depth.shape[0]), self._k)

    def stop(self):
        if self._freenect is not None:
            try:
                self._freenect.sync_stop()
            except Exception:
                pass
        self._freenect = None


# ===========================================================================
# Kinect v2 (libfreenect2 / "pylibfreenect2" python wrapper)
# ===========================================================================

class Kinect2Camera(_KinectBase):
    """Kinect for Windows v2 / Kinect for Xbox One sensor, via pylibfreenect2.

    UNTESTED against real hardware -- see the module docstring.
    """

    family = "KinectV2"

    def __init__(self):
        super().__init__(GUIDE_RANGE_KINECT_V2)
        self._lib = None
        self._fn = None
        self._device = None
        self._listener = None
        self._registration = None
        self._undistorted = None
        self._registered_frame = None
        self._wait_with_timeout = True
        self._k = None

    @staticmethod
    def is_present():
        try:
            lib = import_driver("pylibfreenect2")
            return lib.Freenect2().enumerateDevices() > 0
        except Exception:
            return False

    @staticmethod
    def _make_pipeline(lib, log):
        """GPU pipeline if this build has one, CPU always works (project
        standard: optional GPU acceleration, mandatory CPU fallback).
        KINECT_V2_PIPELINE=cpu (or cuda/opencl/opengl) in the environment
        overrides the automatic choice -- the escape hatch for a graphics
        pipeline that loads but then fails when the device actually starts."""
        wanted = os.environ.get("KINECT_V2_PIPELINE", "").strip().lower()
        choices = {"cpu": (), "cuda": ("CudaPacketPipeline",), "opencl": ("OpenCLPacketPipeline",),
                   "opengl": ("OpenGLPacketPipeline",)}
        if wanted and wanted not in choices:
            log(f"KINECT_V2_PIPELINE={wanted!r} is not one of cpu, cuda, opencl, opengl -- ignored.")
        for name in choices.get(wanted, ("CudaPacketPipeline", "OpenCLPacketPipeline", "OpenGLPacketPipeline")):
            try:
                pipeline = getattr(lib, name)()
                log(f"Using the {name[:-14]} packet pipeline.")
                return pipeline, name[:-14]
            except Exception:
                continue
        log("No GPU packet pipeline available -- using the CPU pipeline (slower, but works on "
            "anything; matches this project's low-end-hardware requirement).")
        return lib.CpuPacketPipeline(), "CPU"

    def start(self, log=print):
        try:
            lib = import_driver("pylibfreenect2")
        except ImportError as exc:
            raise CameraError(
                "The Kinect v2 driver module 'pylibfreenect2' was not found (or libfreenect2 itself "
                "is not built).\n\n" + driver_status_text()) from exc

        fn = lib.Freenect2()
        if fn.enumerateDevices() == 0:
            raise CameraError("No Kinect v2 device found.\n\n" + diagnose_no_camera())
        serial = fn.getDeviceSerialNumber(0)
        pipeline, pipeline_name = self._make_pipeline(lib, log)
        device = fn.openDevice(serial, pipeline=pipeline)
        if device is None:
            # In practice pylibfreenect2's openDevice always returns a
            # wrapper object even when libfreenect2 failed to open the
            # device underneath it, so this check rarely fires -- a failure
            # at this point more often shows up as the child process dying
            # on the next call (see camera_bridge.py's start-up message).
            # It is kept because a future/different pylibfreenect2 build
            # might actually return None, and it's a clearer error than a
            # crash if so.
            raise CameraError("A Kinect v2 was found but could not be opened (another process using "
                              "it? insufficient permissions?).\n\n" + diagnose_no_camera())

        kinds = lib.FrameType.Color | lib.FrameType.Ir | lib.FrameType.Depth
        listener = lib.SyncMultiFrameListener(kinds)
        device.setColorFrameListener(listener)
        device.setIrAndDepthFrameListener(listener)
        device.start()

        self._lib, self._fn, self._device, self._listener = lib, fn, device, listener
        ir = device.getIrCameraParams()
        self._registration = lib.Registration(ir, device.getColorCameraParams())
        width, height = KINECT_V2_SIZE
        self._undistorted = lib.Frame(width, height, 4)
        self._registered_frame = lib.Frame(width, height, 4)
        cx = (width - 1) - ir.cx if KINECT_V2_UNMIRROR else ir.cx
        self._k = (float(ir.fx), float(ir.fy), float(cx), float(ir.cy))
        self.native_K = np.array([[self._k[0], 0, self._k[2]], [0, self._k[1], self._k[3]], [0, 0, 1.0]])
        self.serial = serial.decode(errors="replace") if isinstance(serial, bytes) else str(serial)
        self.device_info = f"Kinect v2 (S/N {self.serial}, {pipeline_name} pipeline)"

    def _wait(self):
        """Next set of frames. pylibfreenect2's waitForNewFrame takes the
        time limit as a KEYWORD argument (milliseconds=...), not
        positionally -- some builds don't accept it at all, so both forms
        are tried and remembered."""
        if self._wait_with_timeout:
            try:
                return self._listener.waitForNewFrame(milliseconds=2000)
            except TypeError:
                self._wait_with_timeout = False
        return self._listener.waitForNewFrame()

    @staticmethod
    def _pick(frames, name, kind):
        try:
            return frames[name]
        except Exception:
            return frames[kind]

    def get_frame(self):
        if self._device is None:
            return None, None, None
        lib = self._lib
        try:
            frames = self._wait()
        except Exception:
            return None, None, None
        if frames is None or frames is False:   # a timeout: nothing to release
            return None, None, None
        try:
            color = self._pick(frames, "color", lib.FrameType.Color)
            depth = self._pick(frames, "depth", lib.FrameType.Depth)
            # Registration.apply() fills two frames on the depth camera's
            # 512x424 grid: the undistorted DEPTH frame (lens distortion
            # removed) and the colour picture resampled to match it. Those
            # two belong together -- using the raw (still-distorted) depth
            # frame instead would leave colour and depth misaligned.
            self._registration.apply(color, depth, self._undistorted, self._registered_frame)
            depth_mm = np.array(self._undistorted.asarray(np.float32), dtype=np.float32, copy=True)
            bgrx = np.asarray(self._registered_frame.asarray(np.uint8))
            color_img = np.ascontiguousarray(bgrx[:, :, 2::-1])   # BGRX -> RGB
        except Exception:
            return None, None, None
        finally:
            try:
                self._listener.release(frames)
            except Exception:
                pass

        if KINECT_V2_UNMIRROR:
            depth_mm = np.ascontiguousarray(depth_mm[:, ::-1])
            color_img = np.ascontiguousarray(color_img[:, ::-1])

        self.last_raw_depth = depth_mm
        depth_img = self._gate(depth_mm)
        return color_img, depth_img, _intrinsic((depth_img.shape[1], depth_img.shape[0]), self._k)

    def stop(self):
        if self._device is not None:
            try:
                self._device.stop()
                self._device.close()
            except Exception:
                pass
        self._device = self._fn = self._listener = None


# ===========================================================================
# Auto-detection
# ===========================================================================

def detect_and_create(log=print):
    """Ask each driver directly whether it sees a device (rather than
    trusting a hand-maintained USB PID table), and return a ready-to-start
    camera object for whichever answers first. Kinect v2 is checked first:
    if both are plugged in, that's almost certainly the one you want to use."""
    if Kinect2Camera.is_present():
        log("Detected a Kinect v2.")
        return Kinect2Camera()
    if Kinect1Camera.is_present():
        log("Detected a Kinect v1.")
        return Kinect1Camera()
    raise CameraError(diagnose_no_camera())


def make_camera():
    """Zero-argument camera factory for camera_bridge.CameraBridge. This has
    to be a plain module-level function (not a lambda or a closure): the
    bridge spawns its child process with multiprocessing's "spawn" context,
    which pickles this callable to hand it to the child, and the standard
    pickle module can only look a plain module-level function up by name --
    it cannot pickle a lambda or a nested function."""
    return detect_and_create(log=lambda _msg: None)
