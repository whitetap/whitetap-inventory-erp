# Inventory Smart Filtering Upgrade

**Status:** Planning

**Information Gathered:**
- Current: Python sends 6 low-stock items → JS search fails on hidden items
- Goal: Send `display_products` (6 low-stock) + `all_products` (full list)
- HTML: Loop `all_products`, hide non-display via CSS/JS initially
- Search: Reveal matching rows from full dataset

**Plan:**
1. **app_fixed_final.py:** 
   ```
   if view == 'inventory':
       display_products = Product.query.filter(...).limit(6)
       all_products = Product.query.all()
   ```
2. **templates/admin.html:**
   ```
   {% for product in all_products %}
     <tr class="{% if product not in display_products %}hidden-row{% endif %}">
   {% endfor %}
   ```
3. **CSS:** `.hidden-row { display: none; }`
4. **JS:** Search reveals from all rows

**Dependent Files:** app_fixed_final.py, templates/admin.html
**Follow-up:** Test search, git commit/push

Ready to implement?

