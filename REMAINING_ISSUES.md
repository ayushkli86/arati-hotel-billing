# REMAINING_ISSUES

1. Sync disabled on the hotel PC until `KOT_CLOUD_URL`, `KOT_CLOUD_USERNAME`, `KOT_CLOUD_PASSWORD` are set and the webapp restarted.
2. Service account `kot-sync` not yet created in the cloud app; `admin`/9999 can serve meanwhile.
3. Android APK fallback URL still points at `kot-mobile.onrender.com` (functional via shared DB) rather than `arati-kot.onrender.com`.
4. Restaurant dine-in/takeaway cloud tickets are mirrored only; desk billing uses the existing local flow (no auto-invoice).
5. Price-mismatch discrepancies are logged but not surfaced as a separate filter beyond the exception queue.
EOF