#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Kinect 3D Scanner  v0.1.0-wip  (built 2026-10-03 15:40)
# https://github.com/The-Dorkknight/kinect-scanner
#
# WORK IN PROGRESS: MANY FEATURES MAY BE BROKEN
#
# Licensed under the PolyForm Noncommercial License 1.0.0
# https://polyformproject.org/licenses/noncommercial/1.0.0/
#
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# No warranty. See LICENSE.md.
#
"""
Kinect 3D Scanner (Kinect v1 / Kinect v2)
==========================================
WORK IN PROGRESS: MANY FEATURES MAY BE BROKEN  (version 0.1.0-wip)

A self-contained, single-file desktop app that turns a Kinect v1 (Xbox 360 /
Kinect for Windows) or Kinect v2 (Kinect for Windows v2 / Kinect for Xbox
One) sensor into a simple tabletop 3D scanner: live preview -> scan while
you turn the object -> build a mesh -> save as .stl/.obj/.ply.

This is a STANDALONE sibling of the "realsense-scanner" project (same
author, same house style) -- it shares no code and no runtime dependency
with it. The scanning engine below (QualityParams / ScanSession) is ported
from realsense-scanner's camera-agnostic core, simplified for this MVP (see
README.md for exactly what was dropped). kinect_camera.py's camera classes
were deliberately written to match realsense-scanner's own camera contract,
so real integration into that project is possible later -- but is NOT done
in this release.

IMPORTANT: none of the camera-specific code in this project (kinect_camera.py,
camera_bridge.py, or this file) has been run against real Kinect v1/v2
hardware -- see README.md's honesty section. Treat the first real run as a
debugging session.

Run it with any Python 3 you have:
    python3 kinect_scanner_app.py        (Linux / macOS)
    py kinect_scanner_app.py             (Windows)
Optional:
    --version         print the version and exit (before any setup work)
    --check-drivers    report whether the Kinect v1 (freenect) and Kinect v2
                       (pylibfreenect2) Python drivers are importable, and
                       point at README.md for the manual install steps.

The first run sets up a private Python environment next to this script:
    kinect_env/   numpy / open3d / opencv-python / Pillow only. Built with
                  --system-site-packages so that a Kinect driver you install
                  manually at the system level (freenect, pylibfreenect2 --
                  see README.md) stays importable from inside it; this app
                  does NOT attempt to build those drivers itself.

Kinect driver setup (libfreenect / libfreenect2) is a manual, per-OS step --
see README.md -> Install, or run with --check-drivers / use the in-app
"Driver setup help..." button.
"""

import os
import sys
import platform
import subprocess

# ===========================================================================
# Self-bootstrapping environment (runs before any third-party imports)
# ===========================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(SCRIPT_DIR, "kinect_env")
BOOTSTRAP_LOG = os.path.join(SCRIPT_DIR, "bootstrap.log")

APP_NAME = "Kinect 3D Scanner"
APP_VERSION = "0.2.0-wip"
APP_BUILD = "2026-10-04 21:16"      # build timestamp, shown in the title bar and status bar
APP_WIP_NOTICE = "WORK IN PROGRESS: MANY FEATURES MAY BE BROKEN"
APP_COPYRIGHT = "Copyright Matthew Armstrong (https://github.com/The-Dorkknight)"
APP_LICENCE_LINE = "Licensed under the PolyForm Noncommercial License 1.0.0. No warranty."

if "--version" in sys.argv[1:]:        # answered before any set-up work starts
    print(f"{APP_NAME} v{APP_VERSION} (Built {APP_BUILD})\n{APP_WIP_NOTICE}\n{APP_COPYRIGHT}\n{APP_LICENCE_LINE}")
    sys.exit(0)

SYSTEM = platform.system()  # "Linux", "Windows" or "Darwin" (macOS)

# Written only after every required package installs AND the package-import
# check passes. Its content is BOOTSTRAP_VERSION, so bumping that version
# invalidates a marker left by an older copy of this script.
DEPS_OK_MARKER = os.path.join(VENV_DIR, ".deps_ok")
BOOTSTRAP_VERSION = "1"

# Deliberately NOT including freenect / pylibfreenect2 here -- see the
# module docstring and README.md: those need a manual driver build per-OS,
# and kinect_env/ is created with --system-site-packages specifically so
# that a system-level install of either one stays importable from inside
# this venv without this app trying to build it.
REQUIRED_PACKAGES = [
    "numpy>=1.22.0,<2.0.0",
    "open3d>=0.17.0",
    "opencv-python>=4.8.0,<4.12",
    "Pillow>=10.0.0",
]


def _venv_python_path():
    if SYSTEM == "Windows":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python")


def _venv_pip_path():
    if SYSTEM == "Windows":
        return os.path.join(VENV_DIR, "Scripts", "pip.exe")
    return os.path.join(VENV_DIR, "bin", "pip")


def _in_target_venv():
    return os.path.realpath(sys.prefix) == os.path.realpath(VENV_DIR)


def _run(cmd, description, capture=True):
    print(f"[*] {description}...")
    try:
        if capture:
            result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
            try:
                with open(BOOTSTRAP_LOG, "a", encoding="utf-8") as f:
                    f.write(f"\n$ {' '.join(cmd)}\n{result.stdout}\n{result.stderr}\n")
            except OSError:
                pass
            if result.returncode != 0:
                print(f"[X] {description} failed (exit {result.returncode}); see {BOOTSTRAP_LOG}")
                return False
            return True
        result = subprocess.run(cmd)
        return result.returncode == 0
    except Exception as exc:
        print(f"[X] {description} failed: {exc}")
        return False


def _verify_python_stack(venv_python):
    """Import the core packages together in the venv, to catch binary
    incompatibilities (e.g. a numpy 1.x/2.x mismatch between Open3D and
    OpenCV) at setup time instead of as a crash when the GUI starts."""
    code = ("import numpy, cv2, open3d, PIL; "
            "print('numpy', numpy.__version__, '| opencv', cv2.__version__, "
            "'| open3d', open3d.__version__, '| Pillow', PIL.__version__)")
    result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, errors="replace")
    if result.returncode == 0:
        print("[✓] Package check: " + result.stdout.strip())
        return True
    print("[X] Installed packages don't work together:")
    print((result.stderr or result.stdout).strip())
    return False


def _relaunch_in_venv(venv_python):
    args = [venv_python, os.path.abspath(__file__)] + sys.argv[1:]
    print("\n[✓] Environment ready. Launching scanner...\n")
    sys.stdout.flush()
    sys.stderr.flush()
    if SYSTEM == "Windows":
        # On Windows os.execv doesn't really replace the process (the
        # console gets its prompt back while the app is still running), so
        # run it as a child and pass on its exit code instead.
        try:
            code = subprocess.call(args)
        except KeyboardInterrupt:
            code = 130
        sys.exit(code)
    os.execv(venv_python, args)   # replaces this process; venv_python must be absolute-ish/on PATH-resolvable


def _bootstrap_and_relaunch():
    print(f"=== {APP_NAME}: environment check ===")
    print(f"Detected OS: {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Launcher Python: {platform.python_version()} ({sys.executable})")

    if not (3, 8) <= sys.version_info[:2] < (3, 13):
        print(f"\n[X] This needs Python 3.8-3.12 (you have {platform.python_version()}). "
              "Install a compatible Python 3 and re-run this script with it.")
        if SYSTEM == "Linux":
            print("    e.g.:  sudo apt-get install python3 python3-venv python3-tk")
        sys.exit(1)

    venv_python = _venv_python_path()
    marker_contents = None
    if os.path.exists(DEPS_OK_MARKER):
        try:
            with open(DEPS_OK_MARKER, encoding="utf-8") as f:
                marker_contents = f.read().strip()
        except OSError:
            marker_contents = None
    deps_ok = os.path.exists(venv_python) and marker_contents == BOOTSTRAP_VERSION

    if not deps_ok:
        if not os.path.exists(venv_python):
            # --system-site-packages: see REQUIRED_PACKAGES's comment above --
            # this is so a manually-installed Kinect driver (freenect /
            # pylibfreenect2) on the system Python stays importable in here.
            if not _run([sys.executable, "-m", "venv", "--system-site-packages", VENV_DIR],
                        "Creating virtual environment", capture=False):
                print("\n[X] Could not create a virtual environment.")
                if SYSTEM == "Linux":
                    print("    On Debian/Ubuntu try: sudo apt-get install python3-venv")
                sys.exit(1)

        pip_path = _venv_pip_path()
        _run([venv_python, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
             "Upgrading pip/setuptools/wheel")

        failed = []
        for pkg in REQUIRED_PACKAGES:
            if not _run([pip_path, "install", pkg], f"Installing {pkg}"):
                failed.append(pkg)
        if failed:
            print("\n[X] Could not install: " + ", ".join(failed))
            print(f"    Full install output was logged to: {BOOTSTRAP_LOG}")
            print("    This usually means there's no prebuilt package for your platform/Python "
                  "version. Fix the issue shown in the log, then re-run -- already-installed "
                  "packages won't be reinstalled.")
            sys.exit(1)

        if _verify_python_stack(venv_python):
            try:
                with open(DEPS_OK_MARKER, "w", encoding="utf-8") as f:
                    f.write(BOOTSTRAP_VERSION + "\n")
            except OSError:
                pass
        else:
            print("\n[!] Environment installed but the package check failed -- launching anyway. "
                  f"See {BOOTSTRAP_LOG}.")

    _relaunch_in_venv(venv_python)


if not _in_target_venv() and os.environ.get("KINECT_SKIP_BOOTSTRAP") != "1":
    _bootstrap_and_relaunch()

# ===========================================================================
# Standard imports (guaranteed inside kinect_env from here on)
# ===========================================================================

import queue
import threading
import time
import traceback
from dataclasses import dataclass

import numpy as np

_MISSING = []
try:
    import open3d as o3d
except ImportError:
    _MISSING.append("open3d")
try:
    import cv2
except ImportError:
    _MISSING.append("opencv-python")
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:
    _MISSING.append("tkinter (install the python3-tk package on Linux)")
try:
    from PIL import Image, ImageTk
except ImportError:
    _MISSING.append("Pillow")

if _MISSING:
    print("Missing required package(s): " + ", ".join(_MISSING))
    print(f"Expected these to already be installed in {VENV_DIR} -- "
          f"delete that folder and re-run this script to rebuild it.")
    sys.exit(1)

# kinect_camera.py / camera_bridge.py live next to this script -- Python
# puts this script's own directory on sys.path[0] automatically, so this
# works whether or not the re-exec above changed the interpreter.
import kinect_camera
from camera_bridge import CameraBridge

VENDOR_WHOAREYOUSB = os.path.join(SCRIPT_DIR, "plugins", "vendor", "whoareyousb.py")


# camera_bridge.CameraBridge's camera_factory used to be this module's own
# _kinect_camera_factory() wrapper. kinect_camera.py now ships the
# equivalent (kinect_camera.make_camera) directly -- same requirement
# (must be a plain module-level function: multiprocessing's "spawn" context
# pickles this callable to hand to the child, and pickle cannot look up a
# lambda or a nested function by name), one fewer thing to keep in sync.


# ===========================================================================
# Driver check (shared by --check-drivers and the in-app "Driver setup
# help..." button)
# ===========================================================================

def driver_check_text():
    lines = [f"{APP_NAME} -- Kinect driver check", "", kinect_camera.driver_status_text(), "",
             "Neither driver is something this app will build for you (see README.md for why).",
             f"Full manual install steps are in README.md, next to this script ({SCRIPT_DIR})."]
    return "\n".join(lines)


if "--check-drivers" in sys.argv[1:]:
    print(driver_check_text())
    sys.exit(0)


# ===========================================================================
# Quality slider parameters
# (ported near-verbatim from realsense-scanner's QualityParams /
#  quality_to_params -- this logic only tunes point-cloud/mesh numbers, so
#  it is entirely camera-agnostic)
# ===========================================================================

@dataclass
class QualityParams:
    voxel_size: float
    icp_fine_dist: float
    icp_coarse_dist: float
    poisson_depth: int
    density_trim_quantile: float
    fused_voxel: float = 0.002     # grid size for the fused ("Smooth") surface
    isolate: bool = True           # keep only the subject in the middle of the view


def quality_to_params(q: float, isolate: bool = True) -> QualityParams:
    q = max(0.0, min(100.0, q)) / 100.0
    voxel = 0.005 - q * (0.005 - 0.0015)
    icp_fine = voxel * 3
    icp_coarse = voxel * 15
    poisson_depth = int(round(8 + q * 3))
    density_trim = 0.06 - q * 0.04
    fused_voxel = max(0.001, voxel * 0.5)
    return QualityParams(voxel, icp_fine, icp_coarse, poisson_depth, density_trim,
                          fused_voxel, isolate)


# ===========================================================================
# Depth clean-up
# (ported verbatim from realsense-scanner -- pure numpy/OpenCV on a depth
#  image + its metres-per-unit scale, so camera-agnostic)
# ===========================================================================

def remove_depth_edges(depth, depth_scale, jump_m=0.01, width_px=2):
    """Drop pixels next to sudden depth jumps -- depth cameras produce
    unreliable "flying pixels" along object outlines that show up as spikes
    and fringes on a scan."""
    d = depth.astype(np.float32)
    valid = depth > 0
    jump = jump_m / depth_scale
    edge = np.zeros(depth.shape, dtype=np.uint8)
    dx = np.abs(np.diff(d, axis=1)) > jump
    dy = np.abs(np.diff(d, axis=0)) > jump
    edge[:, 1:] |= dx
    edge[:, :-1] |= dx
    edge[1:, :] |= dy
    edge[:-1, :] |= dy
    hole = (~valid).astype(np.uint8)
    edge |= (cv2.dilate(hole, np.ones((3, 3), np.uint8)) > 0) & valid
    if width_px > 1:
        edge = cv2.dilate(edge, np.ones((width_px, width_px), np.uint8))
    return np.where(edge > 0, 0, depth).astype(depth.dtype)


def isolate_subject(depth, depth_scale, front_m=0.10, behind_m=0.22, jump_m=0.02):
    """Keep only the object in the middle of the view: the surface nearest
    the camera in the central part of the image, and everything connected to
    it without a depth jump, within a slab of depth around it. Without this,
    if you turn in front of a fixed camera, the static room behind you
    dominates the alignment."""
    h, w = depth.shape
    cy0, cy1, cx0, cx1 = int(h * 0.3), int(h * 0.7), int(w * 0.3), int(w * 0.7)
    central = depth[cy0:cy1, cx0:cx1]
    central_valid = central[central > 0]
    if central_valid.size < 200:
        return depth  # nothing in the middle: leave the frame alone
    ref = float(np.percentile(central_valid, 10))  # the subject's near surface
    lo, hi = ref - front_m / depth_scale, ref + behind_m / depth_scale
    window = (depth > 0) & (depth >= lo) & (depth <= hi)
    d = depth.astype(np.float32)
    jump = jump_m / depth_scale
    cut = np.zeros(depth.shape, dtype=bool)
    cut[:, 1:] |= np.abs(np.diff(d, axis=1)) > jump
    cut[1:, :] |= np.abs(np.diff(d, axis=0)) > jump
    mask = (window & ~cut).astype(np.uint8)
    count, labels = cv2.connectedComponents(mask, connectivity=4)
    if count <= 1:
        return depth
    in_middle = np.bincount(labels[cy0:cy1, cx0:cx1].ravel(), minlength=count)
    in_middle[0] = 0
    best = int(in_middle.argmax())
    if in_middle[best] == 0:
        return depth
    keep = cv2.dilate((labels == best).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    return np.where(keep & window, depth, 0).astype(depth.dtype)


# ===========================================================================
# Scan session: capture -> align/merge -> mesh
#
# Ported from realsense-scanner's ScanSession (lines 2369-3857 there), which
# is itself camera-agnostic (it only ever touches colour/depth/intrinsic/
# depth_scale, whatever camera produced them). DELIBERATELY SIMPLIFIED for
# this MVP -- see README.md and this file's docstring for the full list, but
# in short: register_and_merge() below does plain coarse-to-fine sequential
# ICP chaining (each frame aligned to the most recently *kept* frame, with a
# feature-based global-registration fallback when ICP's overlap is weak). It
# does NOT do: loop closures, pose-graph global optimisation, the
# tracked-pose rescue/veto machinery, the frame-consistency outlier check, or
# per-pixel "areas that moved" masking. That is a real loss of robustness on
# a long, drifty scan -- it is the deliberate trade-off this MVP makes for a
# much simpler, easier-to-debug alignment path. build_fused_mesh() and
# build_mesh() (the actual meshing) are ported much closer to verbatim, since
# that part of the pipeline is not what was simplified.
# ===========================================================================

MIN_MESH_POINTS = 200          # fewer merged points than this can't make a meaningful mesh
FUSED_BLOCK_RESOLUTION = 16    # voxels per block edge in the fused (TSDF) volume
TRIM_DISTANCE_VOXELS = 2.5     # mesh further than this (x voxel size) from any scanned point is removed
MIN_PIECE_FRACTION = 0.05      # loose mesh pieces smaller than this share of the biggest are removed
MIN_ICP_FITNESS = 0.35         # below this, an alignment is treated as failed (frame is skipped)
CONFIDENT_ICP_FITNESS = 0.60   # below this, a global (feature-based) alignment is also tried
GLOBAL_REG_MAX_POINTS = 15000  # per-cloud cap for the (slow) feature-based alignment
MAX_FRAME_POINTS = 60000       # per-frame cap after downsampling (bounds processing time)
DEPTH_TRUNC_M = 6.0            # RGBD depth truncation; comfortably past either Kinect's guide_range far edge


class ScanError(RuntimeError):
    """Raised when a scan can't be turned into a mesh (not enough frames, no overlap, etc)."""


class ScanSession:
    def __init__(self):
        self.frames = []       # per-capture downsampled point clouds (for alignment)
        self.images = []       # per-capture cleaned colour+depth+intrinsic (for the fused surface)
        self.last_merge_report = ""
        self.last_poses = []   # [(frame index, 4x4 frame -> merged-cloud transform)] after alignment
        self._lock = threading.Lock()   # frames/images always change together

    def clear(self):
        with self._lock:
            self.frames = []
            self.images = []
            self.last_merge_report = ""
            self.last_poses = []

    def capture(self, color_rgb, depth_raw, intrinsic, depth_scale, params: QualityParams, info=None):
        depth_raw = remove_depth_edges(depth_raw, depth_scale)
        if params.isolate:
            depth_raw = isolate_subject(depth_raw, depth_scale)
        o3d_color = o3d.geometry.Image(np.ascontiguousarray(color_rgb))
        o3d_depth = o3d.geometry.Image(np.ascontiguousarray(depth_raw))
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d_color, o3d_depth, depth_scale=1.0 / depth_scale, depth_trunc=DEPTH_TRUNC_M,
            convert_rgb_to_intensity=False)
        pcd = o3d.geometry.PointCloud.create_from_rgbd_image(rgbd, intrinsic)
        if len(pcd.points) == 0:
            return None
        pcd = pcd.voxel_down_sample(params.voxel_size)
        if len(pcd.points) > MAX_FRAME_POINTS:
            pcd = pcd.random_down_sample(MAX_FRAME_POINTS / len(pcd.points))
        pcd, _ = pcd.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)
        if len(pcd.points) == 0:
            return None
        pcd.estimate_normals(search_param=o3d.geometry.KDTreeSearchParamHybrid(
            radius=params.voxel_size * 2, max_nn=30))
        # The camera is at the origin of each frame's own coordinates and can
        # only see surfaces facing it, so pointing every normal towards it
        # makes them all face outward, reliably.
        pcd.orient_normals_towards_camera_location(np.zeros(3))
        image = dict(color=np.ascontiguousarray(color_rgb), depth=np.ascontiguousarray(depth_raw),
                     intrinsic=np.asarray(intrinsic.intrinsic_matrix), width=intrinsic.width,
                     height=intrinsic.height, depth_scale=float(depth_scale), info=dict(info or {}))
        with self._lock:
            self.frames.append(pcd)
            self.images.append(image)
        return pcd

    # -- alignment --------------------------------------------------------

    @staticmethod
    def _global_registration(source, target, voxel_size):
        src_down = source.voxel_down_sample(voxel_size)
        tgt_down = target.voxel_down_sample(voxel_size)
        if len(src_down.points) > GLOBAL_REG_MAX_POINTS:
            src_down = src_down.random_down_sample(GLOBAL_REG_MAX_POINTS / len(src_down.points))
        if len(tgt_down.points) > GLOBAL_REG_MAX_POINTS:
            tgt_down = tgt_down.random_down_sample(GLOBAL_REG_MAX_POINTS / len(tgt_down.points))
        radius_normal = voxel_size * 2
        src_down.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=radius_normal, max_nn=30))
        tgt_down.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=radius_normal, max_nn=30))
        radius_feature = voxel_size * 5
        src_fpfh = o3d.pipelines.registration.compute_fpfh_feature(
            src_down, o3d.geometry.KDTreeSearchParamHybrid(radius=radius_feature, max_nn=100))
        tgt_fpfh = o3d.pipelines.registration.compute_fpfh_feature(
            tgt_down, o3d.geometry.KDTreeSearchParamHybrid(radius=radius_feature, max_nn=100))
        distance_threshold = voxel_size * 1.5
        result = o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
            src_down, tgt_down, src_fpfh, tgt_fpfh, True, distance_threshold,
            o3d.pipelines.registration.TransformationEstimationPointToPoint(False), 3,
            [o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.9),
             o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(distance_threshold)],
            o3d.pipelines.registration.RANSACConvergenceCriteria(100000, 0.999))
        return result.transformation

    @staticmethod
    def _colored_icp(source, target, params: QualityParams, init):
        """Colored ICP from `init`. Returns None instead of raising when the
        clouds don't overlap at all from that starting guess."""
        try:
            return o3d.pipelines.registration.registration_colored_icp(
                source, target, params.icp_fine_dist, init,
                o3d.pipelines.registration.TransformationEstimationForColoredICP(),
                o3d.pipelines.registration.ICPConvergenceCriteria(
                    relative_fitness=1e-6, relative_rmse=1e-6, max_iteration=50))
        except RuntimeError:
            return None

    @staticmethod
    def _overlap(source, target, params: QualityParams, result):
        """How well two frames overlap after alignment, checked in both
        directions (ICP's own "fitness" alone can call a frame full of noise
        a near-perfect match to anything)."""
        if result is None:
            return 0.0
        reverse = o3d.pipelines.registration.evaluate_registration(
            target, source, params.icp_fine_dist, np.linalg.inv(result.transformation))
        return min(result.fitness, reverse.fitness)

    def _pairwise_registration(self, source, target, params: QualityParams, inits, status):
        """Coarse-to-fine alignment of `source` onto `target`. Tries each
        initial guess in `inits` with colored ICP; if the best of those still
        has weak overlap, also tries a feature-based global registration
        followed by a point-to-plane + colored ICP refine. Returns
        (transformation, overlap)."""
        best = None
        best_overlap = 0.0
        for init in inits:
            candidate = self._colored_icp(source, target, params, init)
            candidate_overlap = self._overlap(source, target, params, candidate)
            if candidate is not None and candidate_overlap > best_overlap:
                best, best_overlap = candidate, candidate_overlap
        if best_overlap < CONFIDENT_ICP_FITNESS:
            status("  (weak match -- trying a feature-based global alignment...)")
            try:
                coarse = self._global_registration(source, target, params.voxel_size * 2)
                refined = o3d.pipelines.registration.registration_icp(
                    source, target, params.icp_coarse_dist, coarse,
                    o3d.pipelines.registration.TransformationEstimationPointToPlane(),
                    o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=60))
                candidate = self._colored_icp(source, target, params, refined.transformation) or refined
                candidate_overlap = self._overlap(source, target, params, candidate)
                if candidate_overlap > best_overlap:
                    best, best_overlap = candidate, candidate_overlap
            except RuntimeError:
                pass
        if best is None:
            return np.identity(4), 0.0
        return best.transformation, best_overlap

    def register_and_merge(self, params: QualityParams, status=print):
        """Chain all captured frames together with sequential coarse-to-fine
        ICP (see the class docstring above for what this simplifies away
        compared to realsense-scanner's full version) and merge them into
        one point cloud. Returns None if nothing was captured."""
        frames = [o3d.geometry.PointCloud(f) for f in list(self.frames)]
        n = len(frames)
        self.last_poses = []
        if n == 0:
            self.last_merge_report = "No frames captured."
            return None
        if n == 1:
            self.last_poses = [(0, np.identity(4))]
            self.last_merge_report = "Merged 1 frame."
            return frames[0]

        kept = [0]
        poses = [np.identity(4)]
        skipped = []
        last_step = None
        for k in range(1, n):
            status(f"Aligning frame {k + 1} of {n}...")
            anchor = len(kept) - 1
            inits = [np.identity(4)] if last_step is None else [last_step, np.identity(4)]
            transformation, overlap = self._pairwise_registration(
                frames[kept[anchor]], frames[k], params, inits, status)
            if overlap < MIN_ICP_FITNESS:
                skipped.append(k)
                last_step = None
                continue
            poses.append(poses[anchor] @ np.linalg.inv(transformation))
            kept.append(k)
            last_step = transformation

        if len(kept) == 1:
            self.last_merge_report = (
                f"None of the {n} frames lined up with each other, so only one was used -- "
                "capture frames closer together, or move the camera/object more smoothly.")
            self.last_poses = [(kept[0], np.identity(4))]
            return frames[kept[0]]

        status("Merging...")
        self.last_poses = list(zip(kept, poses))
        combined = o3d.geometry.PointCloud()
        for idx, pose in self.last_poses:
            pcd = o3d.geometry.PointCloud(frames[idx])
            pcd.transform(pose)
            combined += pcd
        note = ""
        if skipped:
            note = f" (skipped {len(skipped)} that didn't line up: frame(s) " \
                   f"{', '.join(str(i + 1) for i in skipped)})"
        self.last_merge_report = f"Merged {len(kept)} of {n} frames{note}."
        combined = combined.voxel_down_sample(params.voxel_size)
        combined, _ = combined.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)
        return combined

    # -- meshing (ported close to verbatim from realsense-scanner) --------

    def build_fused_mesh(self, params: QualityParams, status=print):
        """"Smooth" surface: fuse the depth images of all aligned frames into
        one TSDF volume (as in KinectFusion -- fittingly, for a Kinect). Each
        depth reading votes for where the surface is, so per-frame sensor
        noise averages out and only surface that was actually seen is
        produced (nothing invented behind)."""
        if not self.last_poses:
            raise ScanError("No aligned frames to build a surface from.")
        o3c = o3d.core
        voxel = params.fused_voxel
        block_size = voxel * FUSED_BLOCK_RESOLUTION
        trunc_voxels = 5.0

        max_depth = 0.0
        blocks = set()
        for idx, pose in self.last_poses:
            img = self.images[idx]
            valid = img["depth"][img["depth"] > 0]
            if valid.size:
                max_depth = max(max_depth, float(valid.max()) * img["depth_scale"])
            pts = np.asarray(o3d.geometry.PointCloud(self.frames[idx]).transform(pose).points)
            blocks.update(map(tuple, np.unique(np.floor(pts / block_size).astype(np.int64), axis=0)))
        if not blocks:
            raise ScanError("No 3D points to build a surface from.")
        core = np.array(sorted(blocks))
        grown = np.unique((core[:, None, :] + np.array(
            [(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)])[None]).reshape(-1, 3), axis=0)
        block_count = int(len(grown) * 1.3) + 256
        status(f"Fusing {len(self.last_poses)} frames ({block_count} blocks)...")

        device = o3c.Device("CPU:0")   # CPU-only: no GPU-only path, per this project's low-end-hardware standard
        grid = o3d.t.geometry.VoxelBlockGrid(
            ("tsdf", "weight", "color"), (o3c.float32, o3c.float32, o3c.float32),
            ((1), (1), (3)), voxel, FUSED_BLOCK_RESOLUTION, block_count, device)
        for k, (idx, pose) in enumerate(self.last_poses):
            img = self.images[idx]
            depth = o3d.t.geometry.Image(o3c.Tensor(np.ascontiguousarray(img["depth"])))
            color = o3d.t.geometry.Image(o3c.Tensor(np.ascontiguousarray(img["color"])))
            intrinsic = o3c.Tensor(img["intrinsic"], o3c.float64)
            extrinsic = o3c.Tensor(np.linalg.inv(pose), o3c.float64)  # world -> this camera
            scale = 1.0 / img["depth_scale"]
            coords = grid.compute_unique_block_coordinates(
                depth, intrinsic, extrinsic, scale, max_depth + 0.01, trunc_voxels)
            grid.integrate(coords, depth, color, intrinsic, intrinsic, extrinsic,
                           scale, max_depth + 0.01, trunc_voxels)
            if (k + 1) % 5 == 0:
                status(f"Fusing frame {k + 1} of {len(self.last_poses)}...")
        status("Extracting the surface...")
        threshold = 1.5 if len(self.last_poses) >= 3 else 0.5
        mesh = grid.extract_triangle_mesh(weight_threshold=threshold).to_legacy()
        if len(mesh.triangles) == 0:
            raise ScanError("The fused surface came out empty. Check that the object is inside "
                             "the Near/Far range and capture more frames.")
        mesh.remove_degenerate_triangles()
        mesh.remove_duplicated_vertices()
        mesh.remove_unreferenced_vertices()
        cluster_ids, _counts, areas = mesh.cluster_connected_triangles()
        cluster_ids, areas = np.asarray(cluster_ids), np.asarray(areas)
        if len(areas) > 1:
            mesh.remove_triangles_by_mask(areas[cluster_ids] < MIN_PIECE_FRACTION * areas.max())
            mesh.remove_unreferenced_vertices()
        mesh = mesh.filter_smooth_taubin(number_of_iterations=5)
        mesh.compute_vertex_normals()
        return mesh

    @staticmethod
    def build_mesh(merged_pcd, params: QualityParams, status=print):
        """"Watertight" surface: Poisson reconstruction, trimmed back to only
        the surface actually scanned (Poisson always closes the mesh, which
        would otherwise "balloon" wherever the camera never looked)."""
        if merged_pcd is None or len(merged_pcd.points) < MIN_MESH_POINTS:
            raise ScanError(
                "Not enough 3D points to build a mesh "
                f"({0 if merged_pcd is None else len(merged_pcd.points)}). Check that the object "
                "is inside the Near/Far range and fills more of the view.")
        status("Estimating normals for meshing...")
        had_normals = merged_pcd.has_normals()
        merged_pcd.estimate_normals(search_param=o3d.geometry.KDTreeSearchParamHybrid(
            radius=params.voxel_size * 2, max_nn=30))
        if not had_normals:
            merged_pcd.orient_normals_consistent_tangent_plane(30)
        status(f"Running Poisson reconstruction (depth={params.poisson_depth})...")
        mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
            merged_pcd, depth=params.poisson_depth)
        densities = np.asarray(densities)
        threshold = np.quantile(densities, params.density_trim_quantile)
        mesh.remove_vertices_by_mask(densities < threshold)

        status("Trimming surface that wasn't scanned...")
        vertex_cloud = o3d.geometry.PointCloud(mesh.vertices)
        distance = np.asarray(vertex_cloud.compute_point_cloud_distance(merged_pcd))
        mesh.remove_vertices_by_mask(distance > TRIM_DISTANCE_VOXELS * params.voxel_size)

        if len(mesh.triangles):
            cluster_ids, _counts, areas = mesh.cluster_connected_triangles()
            cluster_ids, areas = np.asarray(cluster_ids), np.asarray(areas)
            if len(areas) > 1:
                mesh.remove_triangles_by_mask(areas[cluster_ids] < MIN_PIECE_FRACTION * areas.max())
                mesh.remove_unreferenced_vertices()
        if len(mesh.triangles) == 0:
            raise ScanError("The mesh came out empty after cleaning. Capture more frames of the "
                             "object, closer together.")
        mesh = mesh.filter_smooth_laplacian(number_of_iterations=5)
        mesh.compute_vertex_normals()
        return mesh


# ===========================================================================
# Live preview image (colour + a simple depth colormap, side by side)
# ===========================================================================

def make_preview(color_rgb, depth_u16, depth_scale, near_m, far_m, max_total_width=960):
    depth_m = depth_u16.astype(np.float32) * depth_scale
    span = max(far_m - near_m, 1e-3)
    norm = np.clip((depth_m - near_m) / span, 0.0, 1.0)
    norm_u8 = (norm * 255).astype(np.uint8)
    depth_color = cv2.applyColorMap(norm_u8, cv2.COLORMAP_JET)
    depth_color = cv2.cvtColor(depth_color, cv2.COLOR_BGR2RGB)
    depth_color[depth_u16 == 0] = (25, 25, 25)   # no-data pixels: flat dark grey, not "near" blue
    h, w = color_rgb.shape[:2]
    if depth_color.shape[:2] != (h, w):
        depth_color = cv2.resize(depth_color, (w, h), interpolation=cv2.INTER_NEAREST)
    combined = np.hstack((np.ascontiguousarray(color_rgb), depth_color))
    ch, cw = combined.shape[:2]
    if cw > max_total_width:
        scale = max_total_width / cw
        combined = cv2.resize(combined, (int(cw * scale), int(ch * scale)), interpolation=cv2.INTER_AREA)
    return combined


# ===========================================================================
# GUI
# ===========================================================================

MESH_FILETYPES = [("STL files", "*.stl"), ("OBJ files", "*.obj"), ("PLY files", "*.ply")]
SCAN_INTERVAL_S = 0.5     # how often "Start Scan" auto-captures a frame
DEFAULT_NEAR_M, DEFAULT_FAR_M = 0.5, 4.5


class ScannerApp:
    def __init__(self, root):
        self.root = root
        root.title(f"{APP_NAME} v{APP_VERSION} (Built {APP_BUILD})")
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.session = ScanSession()
        self.camera = None             # a CameraBridge, once started
        self.camera_running = False
        self.camera_starting = False
        self.camera_thread = None
        self.scanning = False
        self.capture_once_requested = threading.Event()
        self.last_capture_at = 0.0

        self.msg_queue = queue.Queue()
        self.preview_lock = threading.Lock()
        self.latest_preview = None     # np.ndarray, set by the camera thread, read by the GUI thread
        self._preview_photo = None     # keep a reference so Tk doesn't garbage-collect it

        self.capture_params = quality_to_params(60.0)
        self.merged_pcd = None
        self.merged_mesh = None
        self.busy = False
        self.last_save_dir = None
        self.closing = False

        self._build_ui()
        self.root.after(50, self._poll_queue)
        self.root.after(50, self._update_preview)

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
        ttk.Label(self.root, text=f"v{APP_VERSION}  •  {APP_BUILD}  •  {APP_WIP_NOTICE}",
                  anchor="e", foreground="#666666", padding=(10, 1)).pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = tk.StringVar(value="Camera off. Press Start Camera to begin.")
        status = ttk.Label(self.root, textvariable=self.status_var, anchor="w",
                            padding=(10, 4), relief=tk.SUNKEN)
        status.pack(side=tk.BOTTOM, fill=tk.X)
        self.root.bind("<Configure>", lambda e: status.configure(
            wraplength=max(200, self.root.winfo_width() - 30)), add="+")

        main = ttk.Frame(self.root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        side = ttk.Frame(main)
        side.pack(side=tk.RIGHT, fill=tk.Y)

        # Mesh actions are packed FIRST at the bottom of the side panel, so
        # they keep their space and stay visible at any window size; the
        # controls above them scroll instead.
        actions = ttk.LabelFrame(side, text="Mesh", padding=8)
        actions.pack(side=tk.BOTTOM, fill=tk.X, padx=(10, 4), pady=(6, 0))
        self.build_btn = ttk.Button(actions, text="Build Mesh", command=self.build_mesh_clicked,
                                     state=tk.DISABLED)
        self.build_btn.pack(fill=tk.X, pady=2)
        self.save_btn = ttk.Button(actions, text="Save Mesh...", command=self.save_mesh, state=tk.DISABLED)
        self.save_btn.pack(fill=tk.X, pady=2)
        units_row = ttk.Frame(actions)
        units_row.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(units_row, text="Save in:").pack(side=tk.LEFT)
        self.units_var = tk.StringVar(value="mm")
        ttk.Radiobutton(units_row, text="millimetres", value="mm", variable=self.units_var).pack(
            side=tk.LEFT, padx=(6, 0))
        ttk.Radiobutton(units_row, text="metres", value="m", variable=self.units_var).pack(
            side=tk.LEFT, padx=(6, 0))
        ttk.Button(actions, text="About / licence...", command=self.show_about).pack(fill=tk.X, pady=(6, 0))

        scroll_area = ttk.Frame(side)
        scroll_area.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        side_canvas = tk.Canvas(scroll_area, highlightthickness=0, borderwidth=0, width=300)
        side_scroll = ttk.Scrollbar(scroll_area, orient=tk.VERTICAL, command=side_canvas.yview)
        side_canvas.configure(yscrollcommand=side_scroll.set)
        side_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right = ttk.Frame(side_canvas, padding=(10, 0, 4, 0))
        side_canvas.create_window((0, 0), window=right, anchor="nw")

        def _fit_side(_event=None):
            side_canvas.configure(scrollregion=side_canvas.bbox("all"))
            if right.winfo_reqheight() > side_canvas.winfo_height() > 1:
                side_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            else:
                side_scroll.pack_forget()
        right.bind("<Configure>", _fit_side)
        side_canvas.bind("<Configure>", _fit_side)

        def _wheel(event):
            if side_scroll.winfo_ismapped() and str(event.widget).startswith(str(scroll_area)):
                step = -1 if (getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0) else 1
                side_canvas.yview_scroll(step, "units")
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            side_canvas.bind_all(seq, _wheel, add="+")

        # -- Camera panel --------------------------------------------------
        cam_frame = ttk.LabelFrame(right, text="Camera", padding=8)
        cam_frame.pack(fill=tk.X, pady=(0, 10))
        self.start_btn = ttk.Button(cam_frame, text="Start Camera", command=self.start_camera)
        self.start_btn.pack(fill=tk.X, pady=2)
        self.stop_cam_btn = ttk.Button(cam_frame, text="Stop Camera", command=self.stop_camera,
                                        state=tk.DISABLED)
        self.stop_cam_btn.pack(fill=tk.X, pady=2)
        self.device_info_var = tk.StringVar(value="No camera connected yet.")
        ttk.Label(cam_frame, textvariable=self.device_info_var, foreground="#666666",
                  wraplength=250).pack(anchor="w", pady=(4, 0))

        range_frame = ttk.Frame(cam_frame)
        range_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(range_frame, text="Near (m)").grid(row=0, column=0, sticky="w")
        self.near_var = tk.StringVar(value=str(DEFAULT_NEAR_M))
        ttk.Spinbox(range_frame, textvariable=self.near_var, width=6, from_=0.1, to=8.0,
                    increment=0.1).grid(row=0, column=1, padx=4)
        ttk.Label(range_frame, text="Far (m)").grid(row=0, column=2, sticky="w")
        self.far_var = tk.StringVar(value=str(DEFAULT_FAR_M))
        ttk.Spinbox(range_frame, textvariable=self.far_var, width=6, from_=0.2, to=8.0,
                    increment=0.1).grid(row=0, column=3, padx=4)
        ttk.Button(range_frame, text="Apply range", command=self.apply_range).grid(
            row=1, column=0, columnspan=4, sticky="ew", pady=(4, 0))

        ttk.Button(cam_frame, text="Driver setup help...", command=self.show_driver_help).pack(
            fill=tk.X, pady=(8, 0))
        self.diagnose_btn = ttk.Button(cam_frame, text="Diagnose USB...", command=self.diagnose_usb)
        self.diagnose_btn.pack(fill=tk.X, pady=(4, 0))
        if SYSTEM != "Linux":
            self.diagnose_btn.config(state=tk.DISABLED)
            ttk.Label(cam_frame, text="USB diagnostics (whoareyousb) are Linux-only.",
                      foreground="#888888", wraplength=250).pack(anchor="w")

        # -- Scan panel -----------------------------------------------------
        scan_frame = ttk.LabelFrame(right, text="Scan", padding=8)
        scan_frame.pack(fill=tk.X, pady=(0, 10))
        self.scan_btn = ttk.Button(scan_frame, text="Start Scan", command=self.toggle_scan)
        self.scan_btn.pack(fill=tk.X, pady=2)
        ttk.Button(scan_frame, text="Capture Frame", command=self.capture_frame_once).pack(
            fill=tk.X, pady=2)
        self.frame_count_var = tk.StringVar(value="Captured frames: 0")
        ttk.Label(scan_frame, textvariable=self.frame_count_var).pack(anchor="w", pady=(6, 2))
        ttk.Button(scan_frame, text="Clear captured frames", command=self.clear_frames).pack(
            fill=tk.X, pady=2)

        # -- Quality panel ----------------------------------------------------
        quality_frame = ttk.LabelFrame(right, text="Quality", padding=8)
        quality_frame.pack(fill=tk.X, pady=(0, 10))
        self.quality_var = tk.DoubleVar(value=60.0)
        ttk.Scale(quality_frame, from_=0, to=100, variable=self.quality_var,
                  orient=tk.HORIZONTAL, command=lambda _v: self._quality_changed()).pack(fill=tk.X)
        ttk.Label(quality_frame, text="Low <-> High (denser / slower)").pack(anchor="w")
        self.isolate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(quality_frame, text="Only keep the subject in the middle\n(ignore the background)",
                        variable=self.isolate_var, command=self._quality_changed).pack(anchor="w", pady=(6, 0))
        self.method_var = tk.StringVar(value="smooth")
        ttk.Radiobutton(quality_frame, text="Smooth surface (recommended)", value="smooth",
                        variable=self.method_var).pack(anchor="w", pady=(6, 0))
        ttk.Radiobutton(quality_frame, text="Watertight (fills unscanned gaps)", value="watertight",
                        variable=self.method_var).pack(anchor="w")

        # -- Preview area -----------------------------------------------------
        preview_frame = ttk.Frame(main)
        preview_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(preview_frame, text="Live preview: colour (left) / depth (right)").pack(anchor="w")
        self.preview_label = ttk.Label(preview_frame, text="Camera is off.", anchor="center",
                                        relief=tk.SUNKEN)
        self.preview_label.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    def _quality_changed(self):
        self.capture_params = quality_to_params(self.quality_var.get(), isolate=bool(self.isolate_var.get()))

    # ------------------------------------------------------------------ camera
    def start_camera(self):
        if self.camera_running or self.camera_starting:
            return
        self.camera_starting = True
        self.start_btn.config(state=tk.DISABLED)
        self.status_var.set("Checking for a Kinect...")

        def log(msg):
            self.msg_queue.put(("status", str(msg)))

        def worker():
            # Cheap "is a device present" check on THIS process first (see
            # kinect_camera.py / this file's docstring), so a missing/
            # unplugged camera fails fast with a friendly message instead of
            # spawning camera_bridge's child process only to watch it die.
            try:
                present = kinect_camera.Kinect2Camera.is_present() or kinect_camera.Kinect1Camera.is_present()
            except Exception as exc:
                self.msg_queue.put(("camera_start_failed", f"Could not check for a Kinect: {exc}"))
                return
            if not present:
                self.msg_queue.put(("camera_start_failed", kinect_camera.diagnose_no_camera()))
                return

            bridge = CameraBridge(kinect_camera.make_camera)
            try:
                bridge.start(log=log)
            except Exception as exc:
                self.msg_queue.put(("camera_start_failed", str(exc)))
                return
            self.camera = bridge
            self.camera_running = True
            self.msg_queue.put(("camera_started", None))
            try:
                self._camera_loop()
            finally:
                try:
                    self.camera.stop()
                except Exception:
                    pass
                self.msg_queue.put(("camera_stopped", None))

        self.camera_thread = threading.Thread(target=worker, daemon=True)
        self.camera_thread.start()

    def _camera_loop(self):
        # NOTE: no Tk calls or Tk variable reads in here -- this runs on a
        # background thread and Tk is not thread-safe. Everything the GUI
        # needs goes through msg_queue / self.latest_preview (behind a lock);
        # everything this loop needs from the GUI comes through plain
        # attributes set on the Tk thread (self.capture_params, self.scanning).
        while self.camera_running:
            try:
                color, depth, intrinsic = self.camera.get_frame()
            except RuntimeError as exc:   # CameraError, from either kinect_camera.py or camera_bridge.py
                self.msg_queue.put(("status", f"Camera error: {exc}"))
                self.camera_running = False
                break
            except Exception as exc:
                self.msg_queue.put(("status", f"Frame error: {exc}"))
                time.sleep(0.2)
                continue
            if color is None:
                time.sleep(0.01)
                continue

            now = time.time()
            if self.scanning and now - self.last_capture_at >= SCAN_INTERVAL_S:
                self.last_capture_at = now
                self._do_capture(color, depth, intrinsic)
            elif self.capture_once_requested.is_set():
                self.capture_once_requested.clear()
                self._do_capture(color, depth, intrinsic)

            try:
                preview = make_preview(color, depth, self.camera.depth_scale,
                                        self.camera.near_m, self.camera.far_m)
                with self.preview_lock:
                    self.latest_preview = preview
            except Exception:
                pass   # a bad preview frame must never take the camera loop down

    def _do_capture(self, color, depth, intrinsic):
        try:
            pcd = self.session.capture(color, depth, intrinsic, self.camera.depth_scale, self.capture_params)
        except Exception as exc:
            self.msg_queue.put(("status", f"Capture failed: {exc}"))
            return
        if pcd is None:
            self.msg_queue.put(("status", "Nothing in range to capture -- check the Near/Far settings."))
        else:
            self.msg_queue.put(("frame_captured", len(self.session.frames)))

    def stop_camera(self):
        if not self.camera_running and not self.camera_starting:
            return
        self.camera_running = False
        self.scanning = False
        self.start_btn.config(state=tk.DISABLED)
        self.status_var.set("Stopping camera...")

    def apply_range(self):
        try:
            near, far = float(self.near_var.get()), float(self.far_var.get())
        except ValueError:
            messagebox.showerror("Range", "Near/Far must be numbers (metres).")
            return
        if near <= 0 or far <= near:
            messagebox.showerror("Range", "Near must be positive and less than Far.")
            return
        if self.camera is None:
            return
        if hasattr(self.camera, "set_range"):
            self.camera.set_range(near, far)
        else:
            self.camera.near_m, self.camera.far_m = near, far
        self.status_var.set(f"Range set to {near:.2f}-{far:.2f} m.")

    # ------------------------------------------------------------------ scan
    def toggle_scan(self):
        if not self.camera_running:
            messagebox.showinfo("Start Scan", "Start the camera first.")
            return
        self.scanning = not self.scanning
        self.scan_btn.config(text="Stop Scan" if self.scanning else "Start Scan")
        if self.scanning:
            self.last_capture_at = 0.0
            self.status_var.set("Scanning -- slowly turn the object or walk the camera round it.")
        else:
            self.status_var.set("Scan stopped.")

    def capture_frame_once(self):
        if not self.camera_running:
            messagebox.showinfo("Capture Frame", "Start the camera first.")
            return
        self.capture_once_requested.set()

    def clear_frames(self):
        if self.busy:
            return
        self.session.clear()
        self.frame_count_var.set("Captured frames: 0")
        self.build_btn.config(state=tk.DISABLED)
        self.merged_pcd = None
        self.merged_mesh = None
        self.save_btn.config(state=tk.DISABLED)
        self.status_var.set("Cleared captured frames.")

    # ------------------------------------------------------------------ mesh
    def build_mesh_clicked(self):
        if self.busy or not self.session.frames:
            return
        self.busy = True
        self.build_btn.config(state=tk.DISABLED)
        self.save_btn.config(state=tk.DISABLED)
        self.status_var.set("Building mesh...")
        params = quality_to_params(self.quality_var.get(), isolate=bool(self.isolate_var.get()))
        method = self.method_var.get()

        def status(msg):
            self.msg_queue.put(("status", msg))

        # A plain threading.Thread is enough here (unlike realsense-scanner's
        # separate-process mesh builder): this app has no raw-stream replay
        # or other heavy, crashy-native-code work competing for the same
        # process, so there's much less to isolate a hang/crash from, and
        # Open3D releases the GIL for its own heavy lifting -- the GUI stays
        # responsive. It can take several seconds; the status bar is the only
        # feedback while it runs.
        def work():
            try:
                merged = self.session.register_and_merge(params, status=status)
                if merged is None:
                    raise ScanError("No frames captured.")
                if method == "watertight":
                    mesh = ScanSession.build_mesh(merged, params, status=status)
                else:
                    mesh = self.session.build_fused_mesh(params, status=status)
                self.msg_queue.put(("mesh_done", (merged, mesh, self.session.last_merge_report)))
            except ScanError as exc:
                self.msg_queue.put(("mesh_failed", str(exc)))
            except Exception as exc:
                self.msg_queue.put(("mesh_failed", f"{exc}\n" + traceback.format_exc(limit=4)))

        threading.Thread(target=work, daemon=True).start()

    def save_mesh(self):
        if self.merged_mesh is None:
            return
        if not self.last_save_dir:
            self.last_save_dir = os.path.join(SCRIPT_DIR, "scans")
            try:
                os.makedirs(self.last_save_dir, exist_ok=True)
            except OSError:
                self.last_save_dir = os.path.expanduser("~")
        path = filedialog.asksaveasfilename(
            title="Save mesh", initialdir=self.last_save_dir,
            initialfile=time.strftime("scan_%Y%m%d_%H%M%S"),
            filetypes=MESH_FILETYPES + [("All files", "*")])
        if not path:
            return
        base, ext = os.path.splitext(path)
        ext = ext.lower()
        if ext not in (".stl", ".obj", ".ply"):
            base, ext = path, ".stl"
        mesh_path = base + ext
        self.last_save_dir = os.path.dirname(mesh_path) or self.last_save_dir

        # The scan is computed in metres (the camera's unit), but STL/OBJ/PLY
        # files carry no units and most CAD tools/slicers read them as
        # millimetres -- so scale to millimetres unless metres was chosen.
        factor = 1000.0 if self.units_var.get() == "mm" else 1.0
        mesh = o3d.geometry.TriangleMesh(self.merged_mesh)
        if factor != 1.0:
            mesh.scale(factor, center=(0.0, 0.0, 0.0))
        if ext == ".stl":
            mesh.compute_triangle_normals()
        else:
            mesh.triangle_normals = o3d.utility.Vector3dVector()
        try:
            ok = o3d.io.write_triangle_mesh(mesh_path, mesh)
        except Exception as exc:
            ok = False
            messagebox.showerror("Save failed", str(exc))
            return
        if ok and os.path.exists(mesh_path):
            self.status_var.set(f"Saved: {mesh_path}")
            messagebox.showinfo("Saved", f"Saved:\n{mesh_path}")
        else:
            messagebox.showerror("Save failed", f"Could not write:\n{mesh_path}\n\n"
                                  "Check the folder exists and you can write to it.")

    # ------------------------------------------------------------------ USB diagnostics
    def diagnose_usb(self):
        if SYSTEM != "Linux":
            return
        top = tk.Toplevel(self.root)
        top.title("Diagnose USB (whoareyousb monitor)")
        ttk.Label(top, text="Live USB connect/disconnect log for about 15 seconds -- this is for "
                            "diagnosing exactly the kind of flaky-connection / USB-speed-drop problems "
                            "Kinect v1/v2 are known for. Wiggle the cable or let the Kinect sit idle "
                            "while this runs.",
                  wraplength=600, justify="left", padding=8).pack(fill=tk.X)
        text = tk.Text(top, width=100, height=30, state=tk.DISABLED)
        text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        line_q = queue.Queue()

        def worker():
            try:
                proc = subprocess.Popen(
                    [sys.executable, VENDOR_WHOAREYOUSB, "monitor", "--seconds", "15", "--interval", "0.25"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                for line in proc.stdout:
                    line_q.put(line)
                proc.wait()
            except Exception as exc:
                line_q.put(f"(could not run whoareyousb.py: {exc})\n")
            line_q.put(None)

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            try:
                while True:
                    line = line_q.get_nowait()
                    if line is None:
                        return
                    text.configure(state=tk.NORMAL)
                    text.insert(tk.END, line)
                    text.see(tk.END)
                    text.configure(state=tk.DISABLED)
            except queue.Empty:
                pass
            if top.winfo_exists():
                top.after(100, poll)
        top.after(100, poll)

    # ------------------------------------------------------------------ about / help
    def show_about(self):
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME}  v{APP_VERSION}  (Built {APP_BUILD})\n{APP_WIP_NOTICE}\n\n"
            f"{APP_COPYRIGHT}\n{APP_LICENCE_LINE}\n\n"
            "Uses kinect_camera.py and camera_bridge.py (this project) and vendors "
            "whoareyousb.py (same author, same licence) for the USB diagnostics feature.\n\n"
            "https://github.com/The-Dorkknight/kinect-scanner")

    def show_driver_help(self):
        messagebox.showinfo("Driver setup help", driver_check_text())

    # ------------------------------------------------------------------ Tk event loop glue
    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "camera_started":
                    self.camera_starting = False
                    info = getattr(self.camera, "device_info", "") or "(unknown device)"
                    self.device_info_var.set(info)
                    self.status_var.set(f"Camera running: {info}")
                    self.stop_cam_btn.config(state=tk.NORMAL)
                    guide = getattr(self.camera, "guide_range", None)
                    if guide:
                        self.near_var.set(f"{guide[0]:.2f}")
                        self.far_var.set(f"{guide[1]:.2f}")
                elif kind == "camera_start_failed":
                    self.camera_starting = False
                    self.start_btn.config(state=tk.NORMAL)
                    self.status_var.set("Camera failed to start (see error dialog).")
                    messagebox.showerror("Camera error", payload)
                elif kind == "camera_stopped":
                    self.camera_running = False
                    self.scanning = False
                    self.scan_btn.config(text="Start Scan")
                    self.start_btn.config(state=tk.NORMAL)
                    self.stop_cam_btn.config(state=tk.DISABLED)
                    self.status_var.set("Camera off.")
                    self.preview_label.config(image="", text="Camera is off.")
                    with self.preview_lock:
                        self.latest_preview = None
                elif kind == "frame_captured":
                    count = payload
                    self.frame_count_var.set(f"Captured frames: {count}")
                    if not self.busy:
                        self.build_btn.config(state=tk.NORMAL)
                        self.status_var.set(f"Captured frame {count}.")
                elif kind == "mesh_done":
                    self.merged_pcd, self.merged_mesh, report = payload
                    self.busy = False
                    self.build_btn.config(state=tk.NORMAL)
                    self.save_btn.config(state=tk.NORMAL)
                    self.status_var.set(
                        f"Mesh built: {len(self.merged_mesh.vertices)} vertices, "
                        f"{len(self.merged_mesh.triangles)} triangles. {report}")
                elif kind == "mesh_failed":
                    self.busy = False
                    self.build_btn.config(state=tk.NORMAL if self.session.frames else tk.DISABLED)
                    self.status_var.set("Mesh build failed (see error dialog).")
                    messagebox.showerror("Build Mesh", payload)
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(50, self._poll_queue)

    def _update_preview(self):
        with self.preview_lock:
            arr = self.latest_preview
        if arr is not None:
            try:
                image = Image.fromarray(arr)
                self._preview_photo = ImageTk.PhotoImage(image)
                self.preview_label.config(image=self._preview_photo, text="")
            except Exception:
                pass
        if not self.closing:
            self.root.after(50, self._update_preview)

    def on_close(self):
        self.closing = True
        self.camera_running = False
        self.scanning = False
        if self.camera_thread is not None and self.camera_thread.is_alive():
            self.camera_thread.join(timeout=5.0)
        if self.camera is not None:
            try:
                self.camera.stop()
            except Exception:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    ScannerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
