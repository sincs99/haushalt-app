# Changelog

## [0.1.0.0] - 2026-10-22

### Fixed

- Keep expenses recoverable: validate every individual share, preserve unsaved edits when closing or resolving concurrent changes, and load older deleted expenses and settlements.
- Use household dates for meal-plan weeks, today indicators and meal polls, including when members travel across timezones.
- Preserve registered uploads during Windows file cleanup and continue supporting existing Windows storage paths.
- Allow versioned expense edits through configured cross-origin deployments.
- Prevent stale requests, cached widget data and native credential writes from crossing account boundaries; enforce session revocation and household authorization.
- Serialize upload quotas and AI budgets, finalize reservations once, and preserve account counters through the security migration.
- Tighten reverse-proxy trust and validate restore inputs before changing the database; retain stopped services when recovery requires operator intervention.
- Linearize migrations and update dependencies with known security advisories.

### Changed

- Keep dialog actions visible on small screens, wrap verification banners and billing actions, provide accessible share errors, and clarify feeding counts.
- Use two columns for the desktop dashboard and adapt its navigation to available space.
- Document coordinated frontend/backend rollout, required proxy settings, backup/restore checks and the distinction between local validation and production evidence.

This is the first repository release marker. Existing application history is retained in Git.
