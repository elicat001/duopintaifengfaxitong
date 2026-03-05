"""
Browser Profile Manager
=======================
Manages persistent Chrome user data directories per account.
Each account gets an isolated profile with consistent fingerprint seeds
to maintain identity across browser sessions.
"""

import os
import json
import shutil
import random
import hashlib
import time
import logging

logger = logging.getLogger(__name__)

# Default profile base directory
_DEFAULT_PROFILE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "browser_profiles"
)

try:
    from config import BROWSER_PROFILE_DIR
except ImportError:
    BROWSER_PROFILE_DIR = _DEFAULT_PROFILE_DIR

# ── Fingerprint data pools ──────────────────────────────────────────────

WEBGL_VENDORS = [
    "Google Inc. (NVIDIA)",
    "Google Inc. (AMD)",
    "Google Inc. (Intel)",
    "Google Inc.",
    "NVIDIA Corporation",
    "ATI Technologies Inc.",
    "Intel Inc.",
    "Intel Open Source Technology Center",
]

WEBGL_RENDERERS = [
    "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (NVIDIA, NVIDIA GeForce RTX 2070 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (AMD, AMD Radeon RX 5700 XT Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (AMD, AMD Radeon RX 6800 XT Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (Intel, Intel(R) HD Graphics 530 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "Mali-G78 MC14",
    "Adreno (TM) 660",
    "Apple GPU",
]

SCREEN_RESOLUTIONS = [
    [1920, 1080],
    [2560, 1440],
    [1366, 768],
    [1536, 864],
    [1440, 900],
    [1600, 900],
    [3840, 2160],
    [2560, 1080],
    [1680, 1050],
    [1280, 720],
]

PLATFORM_STRINGS = [
    "Win32",
    "Win64",
    "MacIntel",
    "Linux x86_64",
    "Linux aarch64",
]


class BrowserProfileManager:
    """Manages persistent Chrome user data directories per account."""

    def __init__(self, base_dir=None):
        self.base_dir = base_dir or BROWSER_PROFILE_DIR
        os.makedirs(self.base_dir, exist_ok=True)
        logger.info("BrowserProfileManager initialized, base_dir=%s", self.base_dir)

    # ── Public API ───────────────────────────────────────────────────────

    def get_or_create_profile(self, account_id, platform=""):
        """
        Get or create a browser profile for the given account.

        Returns:
            dict with keys:
                - profile_dir (str): absolute path to the Chrome user data dir
                - fingerprint (dict): consistent fingerprint seed values
                - exists (bool): True if profile already existed
        """
        profile_dir = self.get_profile_dir(account_id)
        fingerprint_path = os.path.join(profile_dir, "fingerprint_seed.json")
        metadata_path = os.path.join(profile_dir, "profile_metadata.json")
        exists = os.path.isdir(profile_dir) and os.path.isfile(fingerprint_path)

        if exists:
            # Load existing fingerprint
            with open(fingerprint_path, "r", encoding="utf-8") as f:
                fingerprint = json.load(f)
            self.update_last_used(account_id)
            logger.debug("Loaded existing profile for account %s", account_id)
        else:
            # Create new profile directory and fingerprint
            os.makedirs(profile_dir, exist_ok=True)
            fingerprint = self._generate_fingerprint_seed()

            with open(fingerprint_path, "w", encoding="utf-8") as f:
                json.dump(fingerprint, f, indent=2, ensure_ascii=False)

            now = time.time()
            metadata = {
                "account_id": str(account_id),
                "platform": platform,
                "created_at": now,
                "last_used": now,
            }
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            logger.info(
                "Created new browser profile for account %s (platform=%s)",
                account_id,
                platform,
            )

        return {
            "profile_dir": profile_dir,
            "fingerprint": fingerprint,
            "exists": exists,
        }

    def get_profile_dir(self, account_id):
        """Return the absolute profile directory path for an account."""
        safe_id = str(account_id).replace(os.sep, "_").replace("/", "_")
        return os.path.join(self.base_dir, safe_id)

    def delete_profile(self, account_id):
        """
        Delete a profile directory entirely.

        Returns:
            True if deleted, False if profile did not exist.
        """
        profile_dir = self.get_profile_dir(account_id)
        if not os.path.isdir(profile_dir):
            logger.warning("Profile for account %s does not exist", account_id)
            return False

        shutil.rmtree(profile_dir, ignore_errors=True)
        logger.info("Deleted browser profile for account %s", account_id)
        return True

    def list_profiles(self):
        """
        List all profiles with metadata.

        Returns:
            list of dicts, each containing profile metadata plus computed fields.
        """
        profiles = []
        if not os.path.isdir(self.base_dir):
            return profiles

        for entry in os.listdir(self.base_dir):
            entry_path = os.path.join(self.base_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            info = self.get_profile_info(entry)
            if info:
                profiles.append(info)

        # Sort by last_used descending (most recently used first)
        profiles.sort(key=lambda p: p.get("last_used", 0), reverse=True)
        return profiles

    def get_profile_info(self, account_id):
        """
        Get profile metadata for an account.

        Returns:
            dict with metadata or None if profile does not exist.
        """
        profile_dir = self.get_profile_dir(account_id)
        if not os.path.isdir(profile_dir):
            return None

        metadata_path = os.path.join(profile_dir, "profile_metadata.json")
        fingerprint_path = os.path.join(profile_dir, "fingerprint_seed.json")

        # Load or reconstruct metadata
        if os.path.isfile(metadata_path):
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        else:
            # Reconstruct from filesystem timestamps
            stat = os.stat(profile_dir)
            metadata = {
                "account_id": str(account_id),
                "platform": "",
                "created_at": getattr(stat, "st_birthtime", stat.st_ctime),
                "last_used": stat.st_mtime,
            }

        # Add computed fields
        metadata["profile_dir"] = profile_dir
        metadata["total_size"] = self._get_profile_size(profile_dir)
        metadata["has_fingerprint"] = os.path.isfile(fingerprint_path)

        return metadata

    def cleanup_stale_profiles(self, max_age_days=30):
        """
        Delete profiles not used within max_age_days.

        Returns:
            int: number of profiles deleted.
        """
        cutoff = time.time() - (max_age_days * 86400)
        deleted = 0

        for entry in os.listdir(self.base_dir):
            entry_path = os.path.join(self.base_dir, entry)
            if not os.path.isdir(entry_path):
                continue

            last_used = self._get_last_used(entry_path)
            if last_used < cutoff:
                shutil.rmtree(entry_path, ignore_errors=True)
                logger.info(
                    "Cleaned up stale profile %s (last used %.0f days ago)",
                    entry,
                    (time.time() - last_used) / 86400,
                )
                deleted += 1

        if deleted:
            logger.info("Cleaned up %d stale browser profiles", deleted)
        return deleted

    def update_last_used(self, account_id):
        """Update the last_used timestamp for a profile."""
        profile_dir = self.get_profile_dir(account_id)
        metadata_path = os.path.join(profile_dir, "profile_metadata.json")

        if not os.path.isdir(profile_dir):
            return

        now = time.time()

        if os.path.isfile(metadata_path):
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            metadata["last_used"] = now
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        else:
            # Touch the directory to update mtime as fallback
            os.utime(profile_dir, (now, now))

    # ── Private helpers ──────────────────────────────────────────────────

    def _generate_fingerprint_seed(self):
        """
        Generate a consistent set of fingerprint seed values.
        These seeds are stored once per profile and reused across sessions
        to maintain a stable browser identity.
        """
        return {
            "canvas_seed": hashlib.sha256(
                os.urandom(32)
            ).hexdigest()[:16],
            "webgl_vendor": random.choice(WEBGL_VENDORS),
            "webgl_renderer": random.choice(WEBGL_RENDERERS),
            "audio_seed": round(random.uniform(0.0001, 0.9999), 6),
            "screen_resolution": random.choice(SCREEN_RESOLUTIONS),
            "color_depth": random.choice([24, 32]),
            "hardware_concurrency": random.choice([4, 8, 16]),
            "device_memory": random.choice([4, 8, 16]),
            "platform_string": random.choice(PLATFORM_STRINGS),
        }

    def _get_profile_size(self, profile_dir):
        """Calculate total size of a profile directory in bytes."""
        total = 0
        try:
            for dirpath, _dirnames, filenames in os.walk(profile_dir):
                for fname in filenames:
                    fpath = os.path.join(dirpath, fname)
                    try:
                        total += os.path.getsize(fpath)
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def _get_last_used(self, profile_dir):
        """Get the last_used timestamp from metadata or filesystem."""
        metadata_path = os.path.join(profile_dir, "profile_metadata.json")
        if os.path.isfile(metadata_path):
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                return metadata.get("last_used", 0)
            except (json.JSONDecodeError, OSError):
                pass
        # Fallback to directory mtime
        try:
            return os.stat(profile_dir).st_mtime
        except OSError:
            return 0
