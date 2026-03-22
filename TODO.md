# Aviation ERP: Summary Cards Upgrade & 30-Day Forecast
Approved Plan Implementation Tracker

## [✅] Step 1: Backend - Add at_risk_count to app_fixed_final.py
- Compute `all_items = paints + carpets + others`
- `at_risk_count = len([p for p in all_items if (p.current_stock or 0) < 2 * (p.min_stock_level or 0)])`
- Pass `at_risk_count=at_risk_count` to render_template

## [✅] Step 2: Frontend - Update templates/staff_dashboard.html
### HTML Changes:
- Summary Hub: Add class="summary-hub" to row container
- Convert 3 col-md-4 to .summary-card divs with glass styles
- Add 4th col-md-3: &#39;30-Day Forecast&#39; with {{ at_risk_count }} &amp; .at-risk-number class
### CSS (extra_styles):
- `.summary-hub { ... }`
- `.summary-card { transition/box-shadow/hover transform; glass bg; }`
- `@keyframes pulse` + `.at-risk-number { animation... }`

## [✅] Step 3: Test & Verify\n✅ Verified: Floating glass cards with hover transform/shadow, 30-Day Forecast with amber pulse animation.\n✅ Sidebar calculator and inventory tables unchanged.\nRun `python app_fixed_final.py` and visit http://localhost:10000/staff-inventory to confirm.

**Completed Steps: 3/3**

