# Changelog

## 1.1.0 — 2026-09-02

### Fixed

- **Repeated notifications.** `resets_at` carries sub-second jitter around the
  whole minute, and truncating it made the same window alternate between two
  epochs. That epoch is the identity of a window — it keys the notification
  dedup and the history series — so every flip looked like a new window and
  re-fired the "limit reached" alert, while splitting each burn-rate series in
  two. Reset epochs are now rounded to the minute, the stored history is
  migrated, and keys written before the fix are adopted instead of re-alerting.
- **Two processes alerting at once.** The dongle and the background timer share
  the notification state; both read "not alerted yet" and both alerted. The
  read → decide → send → write cycle now runs under a file lock (`flock`, or
  `msvcrt` on Windows) with an atomic write.
- **Thresholds saved on every keystroke.** Typing `85` stored a threshold of
  `8` along the way, and the next poll alerted at 8%. They now commit on
  Enter/focus-out, validated, sorted and deduplicated.
- **The panel ran off the screen.** With the sections open the content passed
  1600px on a 1366x768 laptop, with no way to scroll to the buttons. The panel
  now scrolls, is capped to the screen it is on, and Settings starts collapsed:
  the default panel went from 1076px to 591px.
- **Red for the wrong reason.** The border turned red when any metric passed
  95%, including a single model's weekly limit — which doesn't stop the other
  models. Red is now reserved for a limit that stops everything.
- **Off-Linux behaviour.** Windows had no cross-process lock, language
  detection read variables Windows and Finder-launched macOS apps don't set,
  and battery detection was Linux-only.

### Added

- **English / Portuguese switch**, applied to the panel, the dongle tooltip and
  the notifications on the spot. Defaults to your system locale.
- **What is still usable.** A model running out of its weekly quota doesn't
  stop the others, and the panel and tooltip now say exactly that, and when it
  comes back.
- **"Limit is back" notification.** The monitor used to speak only on the way
  up; it now tells you once when a spent limit resets.
- **Forecast read as a budget** — "~2h30 of work left · the reset only comes in
  1d 23h" instead of "overflows in 2h30".
- **Burn by hour of the day**, built from the history already being collected.
- **Battery saver**: every timer runs at half rate while unplugged.
- **New API fields**: `is_active` (which limit is biting), `locked_reason`, the
  full `extra_usage` block as a percentage, and a fallback to the top-level
  per-model weekly keys.

### Changed

- **The dongle is pure black**, and the warning border breathes (a 5.5s cycle
  smoothed at both ends) instead of blinking at ~0.8Hz.
- **Per-project usage was removed**; the section is per model. Attributing by
  the session's working directory is wrong often enough to mislead, and doing
  it right is a different tool's job.
- **Cheaper at rest.** An idle dongle went from ~5.7% of a core to ~2.2%:
  breathing frames are painted only when the border actually changes, the
  countdown repaints only when its text changes (its finest unit is the
  minute), and the visibility check reads `/proc` instead of forking `ps`
  (114ms → 15ms).

### Notes

CI now builds the real UI on Linux, macOS and Windows and runs a behaviour
smoke there; screenshots can't be compared on the Windows runner, which exposes
no fonts to Qt at all.

## 1.0.1 — 2026-07-13

Docs and packaging only: install from PyPI, `Homepage` metadata, classifiers.

## 1.0.0 — 2026-07-12

First public release: floating dongle, dashboard with burn rate and overflow
forecast, per-project usage, limit notifications, autostart on Linux/macOS/Windows.
