#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# camera_bridge.py -- runs a Kinect camera backend in its own child process
# and auto-restarts it if that process dies, hangs, or the USB device drops
# out. Presents the SAME contract as the camera classes in kinect_camera.py
# (start/get_frame/stop/depth_scale/guide_range/device_info), so it is a
# drop-in: swap `cam = Kinect2Camera()` for `cam = CameraBridge(kinect_camera.make_camera)`
# and nothing else in the caller needs to change.
#
# v0.2.0-wip: fixed against a bug report from a sibling chat (working on
# realsense-scanner, which imported this module as an optional camera
# backend) that found and fixed real faults here by running this code
# against hand-built stand-in driver modules and reading libfreenect's and
# pylibfreenect2's own source. See CHANGELOG.md for the list. The worst of
# them: an Open3D intrinsic object can't survive a trip across a
# multiprocessing Queue (it isn't picklable) -- it was silently dropped,
# which meant NO frame ever reached the caller, and after enough failed
# restarts the bridge would blame "a genuine hardware/cable/port problem"
# that was never actually there. It now crosses as six plain numbers and is
# rebuilt on arrival.
#
# WHY A SEPARATE PROCESS (not just a thread):
# libfreenect/libfreenect2 are old, thin C/C++ wrappers around raw USB
# traffic on hardware that is itself known to be flaky (Kinect v2 runs right
# at USB3 bandwidth limits; both devices have a long history of GitHub
# issues describing hangs or crashes that need a physical replug -- see
# README.md for sources). A hang or native-code fault in that C layer can
# freeze or kill the whole interpreter; a Python thread shares the same
# process and the same fate. A child process can be watched from outside
# and killed/restarted without touching the GUI.
#
# WHAT THIS DOES vs DOESN'T FIX:
# It cannot fix a dead USB cable, a USB2 port being used for a USB3-only
# Kinect v2, or a genuinely unplugged sensor. What it DOES fix is the class
# of fault where the driver's internal state gets wedged (a stuck pipe, a
# never-returning blocking call) -- tearing down and recreating the whole
# process is a strong form of "unplug and replug" at the software level,
# which is exactly the recovery step commonly suggested in the upstream
# issue trackers.
#
# WORK IN PROGRESS. The restart logic is proven against stand-in cameras
# (tests/test_kinect.py: one that crashes, one that hangs, one that answers
# but never sends a picture, one that is not there) -- it has not been run
# against a real Kinect driver fault.
#
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE.md). No warranty.
#
"""
Frames cross the process boundary as plain arrays and numbers. An Open3D
intrinsic object cannot be sent between processes (it is not picklable), so
it travels as six numbers (width, height, fx, fy, cx, cy) and is rebuilt on
arrival with _unpack_intrinsic.
"""

import multiprocessing
import queue
import time

HEARTBEAT_TIMEOUT_S = 8.0        # no frame and no "still alive" ping for this long = hung
NO_PICTURE_TIMEOUT_S = 12.0      # answering, but no picture for this long = stuck all the same
MAX_CONSECUTIVE_RESTARTS = 5     # then give up: it is a real hardware/cable problem
RESTART_BACKOFF_S = 2.0
START_TIMEOUT_S = 20.0
STABLE_AFTER_S = 30.0            # frames for this long after a (re)start = working again


class CameraError(RuntimeError):
    """fatal=True means the bridge has given up and the camera should be
    treated as stopped, not just hiccuping."""

    def __init__(self, message, fatal=False):
        super().__init__(message)
        self.fatal = fatal


def _pack_intrinsic(intrinsic):
    """Open3D's PinholeCameraIntrinsic cannot be pickled, so it crosses the
    process boundary as a plain tuple of six numbers instead."""
    if intrinsic is None:
        return None
    if isinstance(intrinsic, (tuple, list)):
        return tuple(intrinsic)
    fx, fy = intrinsic.get_focal_length()
    cx, cy = intrinsic.get_principal_point()
    return (int(intrinsic.width), int(intrinsic.height), float(fx), float(fy), float(cx), float(cy))


def _unpack_intrinsic(packed):
    import open3d as o3d
    return o3d.camera.PinholeCameraIntrinsic(*packed)


def _child_main(camera_factory, cmd_q, frame_q, log_q, stop_evt):
    """Runs inside the child process. camera_factory is a zero-arg callable
    returning a fresh, unstarted camera object (kinect_camera.make_camera,
    or a module-level function wrapping Kinect1Camera/Kinect2Camera)."""
    def log(msg):
        try:
            log_q.put(("log", str(msg)), timeout=1)
        except Exception:
            pass

    # Without this the process cannot exit while a frame is still on its way
    # to a parent that has stopped reading: stopping would wait three seconds
    # and then be killed outright.
    frame_q.cancel_join_thread()

    cam = None
    try:
        cam = camera_factory()
        cam.start(log=log)
        native_k = getattr(cam, "native_K", None)
        log_q.put(("started", {
            "device_info": getattr(cam, "device_info", ""),
            "depth_scale": getattr(cam, "depth_scale", None),
            "guide_range": getattr(cam, "guide_range", None),
            "family": getattr(cam, "family", "Kinect"),
            "serial": getattr(cam, "serial", None),
            "native_K": None if native_k is None else [list(map(float, row)) for row in native_k],
        }))
    except BaseException as exc:
        try:
            log_q.put(("start_failed", str(exc) or type(exc).__name__))
        except Exception:
            pass
        try:
            if cam is not None:
                cam.stop()
        except Exception:
            pass
        return

    try:
        while not stop_evt.is_set():
            # Let the parent push small control messages (currently just
            # near/far range updates) without a second channel.
            try:
                while True:
                    kind, payload = cmd_q.get_nowait()
                    if kind == "range":
                        if hasattr(cam, "set_range"):
                            cam.set_range(*payload)
                        else:
                            cam.near_m, cam.far_m = payload
            except queue.Empty:
                pass

            try:
                color, depth, intrinsic = cam.get_frame()
            except Exception as exc:
                log_q.put(("frame_error", str(exc)))
                time.sleep(0.2)
                continue

            if color is None:
                # Still alive, just no frame this tick -- let the parent's
                # heartbeat know we're not hung, we're waiting.
                try:
                    frame_q.put_nowait(("alive", None))
                except queue.Full:
                    pass
                time.sleep(0.005)
                continue

            try:
                # Replace rather than queue up frames: a lagging consumer
                # should see the newest frame, not a backlog (same reasoning
                # as the single-slot preview buffer in realsense-scanner's
                # camera loop).
                while True:
                    frame_q.get_nowait()
            except queue.Empty:
                pass
            try:
                frame_q.put_nowait(("frame", (color, depth, _pack_intrinsic(intrinsic))))
            except queue.Full:
                pass
    finally:
        try:
            if cam is not None:
                cam.stop()
        except Exception:
            pass


class CameraBridge:
    """Drop-in replacement for a kinect_camera.py camera object. Owns a
    child process running the real camera; restarts it automatically on
    death, hang, or a stalled-but-still-answering stream, up to
    MAX_CONSECUTIVE_RESTARTS times in a row."""

    def __init__(self, camera_factory):
        """camera_factory: zero-arg callable returning a fresh, unstarted
        camera instance -- kinect_camera.make_camera, or a module-level
        function wrapping Kinect1Camera/Kinect2Camera directly. Must be a
        plain module-level function, not a lambda or closure: it has to
        survive being pickled to the spawned child process."""
        self._factory = camera_factory
        self._ctx = multiprocessing.get_context("spawn")   # fork is unsafe once native libraries are loaded
        self._proc = None
        self._cmd_q = self._frame_q = self._log_q = self._stop_evt = None
        self._last_frame_at = 0.0
        self._last_picture_at = 0.0
        self._spawned_at = 0.0
        self._restart_count = 0
        self._log_sink = print
        self._started_info = None
        self._start_error = None
        self._gave_up = False

        # Public attributes mirroring the wrapped camera, filled in once the
        # child reports "started".
        self.device_info = ""
        self.depth_scale = 0.001
        self.guide_range = (0.5, 4.0)
        self.near_m, self.far_m = self.guide_range
        self._range_set = False
        self.family = "Kinect"
        self.serial = None
        self.native_K = None
        self.last_aligned_depth = None
        # Inert, for interface parity with kinect_camera.py's cameras -- no
        # Kinect equivalent, but a caller that pokes at it with
        # getattr/hasattr (matching realsense-scanner's SR305Camera) sees a
        # complete shape either way.
        self.last_raw_depth = None
        self.confidence = None
        self.bad_mask = None
        self.mask_serial = None
        self.use_mask = False
        self.want_ir = False
        self.has_ir = False
        self.last_ir = None

    # -- lifecycle ------------------------------------------------------------

    def start(self, log=print):
        self._log_sink = log
        self._restart_count = 0
        self._gave_up = False
        self._spawn()

    def _spawn(self):
        self._started_info = self._start_error = None
        self._cmd_q = self._ctx.Queue(maxsize=8)
        self._frame_q = self._ctx.Queue(maxsize=1)
        self._log_q = self._ctx.Queue(maxsize=64)
        self._stop_evt = self._ctx.Event()
        self._proc = self._ctx.Process(
            target=_child_main,
            args=(self._factory, self._cmd_q, self._frame_q, self._log_q, self._stop_evt), daemon=True)
        self._proc.start()
        self._last_frame_at = self._spawned_at = time.time()

        # Block briefly for the child's "started"/"start_failed" message so
        # a bad camera fails start() the same way the direct classes do,
        # instead of only failing on the first get_frame().
        deadline = time.time() + START_TIMEOUT_S
        while time.time() < deadline:
            self._drain_log()
            if self._started_info is not None:
                info, self._started_info = self._started_info, None
                self.device_info = info.get("device_info") or "Kinect"
                if info.get("depth_scale"):
                    self.depth_scale = float(info["depth_scale"])
                if info.get("guide_range"):
                    self.guide_range = tuple(info["guide_range"])
                self.family = info.get("family") or "Kinect"
                self.serial = info.get("serial")
                if info.get("native_K") is not None:
                    import numpy as np
                    self.native_K = np.array(info["native_K"], dtype=float)
                if self._range_set:                 # the user's Near/Far survive a restart
                    self._send_range()
                else:
                    self.near_m, self.far_m = self.guide_range
                self._last_frame_at = self._last_picture_at = time.time()
                return
            if self._start_error is not None:
                error, self._start_error = self._start_error, None
                self._teardown_process()
                raise CameraError(error)
            if not self._proc.is_alive():
                # The child exited without ever sending "started" or
                # "start_failed" -- a bare crash (segfault, native abort)
                # rather than a clean Python-level failure. Fail fast with
                # whatever hint can be given, instead of waiting out the
                # full timeout for a process that is already gone.
                self._drain_log()
                if self._start_error is None and self._started_info is None:
                    code = self._proc.exitcode
                    self._teardown_process()
                    raise CameraError(
                        f"The camera process stopped while starting (exit code {code}). "
                        "That is a crash inside the Kinect driver. The usual causes are a camera "
                        "that could not be opened (no permission: on Linux, check the driver's "
                        "udev rule -- see README.md; or another program already has it open) or "
                        "a graphics pipeline the driver could not start (Kinect v2: try setting "
                        "KINECT_V2_PIPELINE=cpu).")
                continue
            time.sleep(0.05)
        self._teardown_process()
        raise CameraError(f"The camera process did not answer within {START_TIMEOUT_S:.0f} seconds of starting.")

    def _drain_log(self):
        if self._log_q is None:
            return
        try:
            while True:
                kind, payload = self._log_q.get_nowait()
                if kind == "log":
                    self._log_sink(payload)
                elif kind == "started":
                    self._started_info = payload
                elif kind == "start_failed":
                    self._start_error = payload
                elif kind == "frame_error":
                    self._log_sink(f"Camera process reported a frame error: {payload}")
        except queue.Empty:
            pass
        except (EOFError, OSError):
            pass

    def _teardown_process(self):
        if self._stop_evt is not None:
            try:
                self._stop_evt.set()
            except Exception:
                pass
        proc, self._proc = self._proc, None
        if proc is not None:
            proc.join(timeout=3)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=3)
            if proc.is_alive():
                try:
                    proc.kill()
                except Exception:
                    pass
        for q in (self._cmd_q, self._frame_q, self._log_q):
            if q is not None:
                try:
                    q.cancel_join_thread()
                    q.close()
                except Exception:
                    pass
        self._cmd_q = self._frame_q = self._log_q = None

    def _restart(self, reason):
        self._restart_count += 1
        if self._restart_count > MAX_CONSECUTIVE_RESTARTS:
            self._gave_up = True
            self._teardown_process()
            raise CameraError(
                f"The camera kept failing after {MAX_CONSECUTIVE_RESTARTS} automatic restarts "
                f"(last reason: {reason}). This usually means a genuine hardware/cable/port "
                "problem rather than a recoverable driver hiccup -- check the USB connection "
                "(see README.md's troubleshooting section) rather than retrying again.", fatal=True)
        self._log_sink(f"Camera bridge: restarting ({reason}), attempt {self._restart_count}"
                       f"/{MAX_CONSECUTIVE_RESTARTS}...")
        self._teardown_process()
        time.sleep(RESTART_BACKOFF_S)
        try:
            self._spawn()
        except CameraError as exc:
            # A failed restart attempt is not yet "giving up" -- the next
            # call to get_frame() will see self._proc is None and try again,
            # until MAX_CONSECUTIVE_RESTARTS is actually exceeded above.
            self._log_sink(f"Camera bridge: restart attempt failed ({exc}).")
            return
        self._log_sink("Camera bridge: restarted successfully.")

    # -- per-frame API ---------------------------------------------------------

    def get_frame(self):
        if self._gave_up:
            return None, None, None
        if self._proc is None:
            if self._restart_count:                 # a previous restart attempt failed: try again
                self._restart("previous restart attempt failed")
            return None, None, None
        self._drain_log()

        if not self._proc.is_alive():
            self._restart("the camera process stopped unexpectedly")
            return None, None, None

        # Read the queue FIRST and judge the heartbeat only afterwards: if
        # this side (the GUI thread) was itself busy for a moment, a healthy
        # camera has a frame already waiting, and that must not be mistaken
        # for a hung camera just because some wall-clock time passed.
        try:
            kind, payload = self._frame_q.get(timeout=0.05)
        except (queue.Empty, EOFError, OSError):
            kind = payload = None

        now = time.time()
        if kind is not None:
            self._last_frame_at = now
        if kind != "frame":
            if now - self._last_frame_at > HEARTBEAT_TIMEOUT_S:
                self._restart(f"no response for over {HEARTBEAT_TIMEOUT_S:.0f} seconds (hung)")
            elif now - self._last_picture_at > NO_PICTURE_TIMEOUT_S:
                # The driver still answers (heartbeats keep arriving) but
                # hands over nothing real: a stalled USB stream looks
                # exactly like this, and sitting in that state forever
                # would otherwise never trigger a restart.
                self._restart(f"no picture for over {NO_PICTURE_TIMEOUT_S:.0f} seconds")
            return None, None, None

        self._last_picture_at = now
        if self._restart_count and time.time() - self._spawned_at > STABLE_AFTER_S:
            self._restart_count = 0          # it has run properly for a while: forget earlier failures
        color, depth, packed = payload
        self.last_aligned_depth = depth
        return color, depth, _unpack_intrinsic(packed)

    def apply_settings(self, log=print):
        pass  # ranges are pushed via the range-change path below; nothing per-frame to apply

    def _send_range(self):
        if self._cmd_q is not None:
            try:
                self._cmd_q.put(("range", (self.near_m, self.far_m)), timeout=1)
            except Exception:
                pass

    def set_range(self, near_m, far_m):
        self.near_m, self.far_m = float(near_m), float(far_m)
        self._range_set = True
        self._send_range()

    def stop(self):
        self._teardown_process()
        self._restart_count = 0
