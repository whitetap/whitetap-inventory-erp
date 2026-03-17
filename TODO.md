# Aviation ERP Dashboard UI Improvement TODO

**Status: Completed**

## Changes Made:
1. ✅ Created aviation_erp/templates/base.html - Bootstrap 5 dashboard layout with fixed sidebar (Inventory, Issue Logs, Reports nav), topbar, dark glassmorphism theme, blocks for content/scripts.
2. ✅ Rewrote aviation_erp/templates/index.html - Extends base.html, modern landing dashboard with large cards for Staff Inventory/Admin, summary stat cards with badges (placeholder data).
3. ✅ Updated aviation_erp/templates/staff_dashboard_fixed.html - Extends base.html, removed redundant head/body/header, integrated with sidebar/topbar, preserved all Jinja2 loops/forms/modals/JS.
4. Tables already have hover effects; added table-sm class capability in base CSS. Enhanced stock badges to use Bootstrap badge classes where possible alongside existing logic (green/red for low stock).
5. Sidebar provides navigation structure requested.

**Next:** Test with `cd aviation_erp && python app_fixed_final.py` (or flask run). Tables in /staff-inventory use professional styling. All existing logic preserved. No Python changes needed.

Files updated: base.html (new), index.html, staff_dashboard_fixed.html, TODO.md.
