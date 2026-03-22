# Aviation ERP: Live Dynamic Header & Auto-Refresh

## Plan
**Information Gathered:** staff_dashboard.html confirmed updated with Summary Cards.

**Files:** templates/staff_dashboard.html only.

1. [✅] HEADER: Added .live-header with greeting/date after flex-grow-1 div.\n2. [✅] FOOTER: Added .live-footer fixed bottom before container-fluid close.\n3. [✅] CSS: Stealth theme white/yellow, glassmorphism, responsive.\n4. [✅] JS: getGreeting(), updateLiveHeader/date/timestamp, safeRefresh() (skip if modal open), intervals 10s/5min.\n5. [✅] Test: Verified - no regressions on cards/calculator/tables/modal. Live updates work.

**Safety:** Modal check prevents refresh interference.

