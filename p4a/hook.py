"""python-for-android hook.

Why this exists
---------------
Buildozer 1.5.0 can generate an invalid AndroidManifest.xml when using
`android.extra_manifest_application_arguments` (manifest merger fails).

We add our BootReceiver via this hook *before* the APK build runs.

This keeps the build stable across CI environments.
"""

from __future__ import annotations

from pathlib import Path


RECEIVER_XML = """
    <receiver
        android:name=\"org.erick.tibiatools.BootReceiver\"
        android:enabled=\"true\"
        android:exported=\"true\">
        <intent-filter>
            <action android:name=\"android.intent.action.BOOT_COMPLETED\" />
            <action android:name=\"android.intent.action.LOCKED_BOOT_COMPLETED\" />
            <action android:name=\"android.intent.action.MY_PACKAGE_REPLACED\" />
            <action android:name=\"android.intent.action.QUICKBOOT_POWERON\" />
        </intent-filter>
    </receiver>
""".strip(
    "\n"
)


def _candidate_manifest_paths(toolchain) -> list[Path]:
    """Return a short list of likely manifest locations."""
    candidates: list[Path] = []

    # Most common: toolchain._dist.dist_dir points to the dist folder.
    dist_dir = getattr(getattr(toolchain, "_dist", None), "dist_dir", None)
    if dist_dir:
        d = Path(dist_dir)
        candidates.append(d / "src/main/AndroidManifest.xml")

        # If dist_dir is only the dist *name*, try with ctx.dist_dir.
        ctx = getattr(toolchain, "ctx", None)
        ctx_dist = getattr(ctx, "dist_dir", None)
        if ctx_dist:
            candidates.append(Path(ctx_dist) / str(dist_dir) / "src/main/AndroidManifest.xml")

    # Fallbacks: search in .buildozer folder (used by Buildozer)
    cwd = Path(".").resolve()
    candidates.extend(
        sorted(cwd.glob(".buildozer/android/platform/build-*/dists/*/src/main/AndroidManifest.xml"))
    )

    # Deduplicate while preserving order
    seen = set()
    out: list[Path] = []
    for p in candidates:
        pp = p.resolve()
        if pp in seen:
            continue
        seen.add(pp)
        out.append(pp)
    return out


def _patch_manifest_file(manifest_path: Path) -> bool:
    """Inject the receiver entry into AndroidManifest.xml.

    Returns True if the file was changed.
    """
    if not manifest_path.exists():
        return False

    text = manifest_path.read_text("utf-8", errors="replace")

    # Already present?
    if "org.erick.tibiatools.BootReceiver" in text or "<receiver" in text and "BootReceiver" in text:
        return False

    close_tag = "</application>"
    idx = text.rfind(close_tag)
    if idx == -1:
        # Unexpected manifest layout; don't risk breaking it.
        return False

    new_text = text[:idx] + "\n" + RECEIVER_XML + "\n" + text[idx:]
    manifest_path.write_text(new_text, "utf-8")
    return True


def _ensure_receiver(toolchain) -> None:
    for mf in _candidate_manifest_paths(toolchain):
        try:
            if _patch_manifest_file(mf):
                # Patched successfully; stop.
                return
        except Exception:
            # Ignore and try next candidate.
            continue


# Hook entry points
# python-for-android calls these if present.

def before_apk_build(toolchain):  # noqa: N802
    _ensure_receiver(toolchain)


def before_apk_package(toolchain):  # noqa: N802
    _ensure_receiver(toolchain)


def after_apk_build(toolchain):  # noqa: N802
    # As a fallback, try again; useful if the hook ordering differs.
    _ensure_receiver(toolchain)
