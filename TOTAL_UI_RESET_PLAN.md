# High-Contrast Apple-Style UI Overhaul Plan for staff_dashboard.html

**Information Gathered:**
- Current file: Dark glassmorphism theme with floating summary hub, sidebar navy, white tables in accordions, live header/footer JS
- Backend/Jinja/JS logic intact (at_risk_count, carpet calc, 5min refresh)
- Target: Pure CSS replacement in `{% block extra_styles %}` - NO HTML/structure changes

**Plan:**
1. **Root CSS Reset:** Main body `#f4f7f6` bg, deep navy text (#1a202c)
2. **Sidebar:** Navy `#1a202a` bg, gold logo (`color: #f59e0b`), active links electric blue `#3b82f6 bg-white`
3. **Summary Hub:** `.summary-hub` light grey container, 4x pure white cards (`#ffffff bg, border-radius 12px, shadow 0 4px 20px rgba(0,0,0,0.05)`), navy numbers
4. **Tables/Accordions:** White `.staff-card` bg, light blue-grey `.category-header` (`#f1f5f9`), electric blue left border, thin table borders
5. **Carpet Converter:** Toolbox blue (`#3b82f6` accents), white labels on navy
6. **Greeting:** Bold navy `#1a202c` for live header
7. **Modal:** Light theme matching main

**Dependent Files:** templates/staff_dashboard.html (CSS block only)

**Followup:** Git commit/push, test `python app_fixed_final.py`

<confirmation>Approve this plan before CSS replacement?</confirmation>

