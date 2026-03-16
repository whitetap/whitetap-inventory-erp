// Staff Dashboard JS
document.addEventListener('DOMContentLoaded', function() {

    // Barcode input
    const barcodeInput = document.getElementById('barcode-input');
    const productDetails = document.getElementById('product-details');
    const productName = document.getElementById('product-name');
    const productStock = document.getElementById('product-stock');
    const productCategory = document.getElementById('product-category');
    const productMin = document.getElementById('product-min');

    barcodeInput.addEventListener('input', function(e) {
        if (e.target.value.length > 2) {
            fetchProduct(e.target.value);
        }
    });

    barcodeInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            fetchProduct(e.target.value);
            e.target.value = '';
            e.target.blur();
            setTimeout(() => barcodeInput.focus(), 100);
        }
    });

    async function fetchProduct(barcode) {
        try {
            const res = await fetch(`/api/product/${barcode}`);
            const product = await res.json();
            if (product.name) {
                productName.textContent = product.name;
                productStock.textContent = `${product.current_stock} ${product.unit_type}`;
                productCategory.textContent = product.category;
                productMin.textContent = product.min_stock_level;
                productDetails.classList.remove('hidden');
                setTimeout(() => productDetails.classList.add('animate-pulse'), 100);
            }
        } catch (err) {
            console.error('Product fetch error:', err);
        }
    }

    // Carpet Calculator
    const calcBtn = document.getElementById('calc-carpet');
    const carpetResult = document.getElementById('carpet-result');
    const totalSqft = document.getElementById('total-sqft');
    const stockCompare = document.getElementById('stock-compare');
    const lengthFt = document.getElementById('length-ft');
    const widthFt = document.getElementById('width-ft');

    calcBtn.addEventListener('click', async function() {
        const len = parseFloat(lengthFt.value) || 0;
        const wid = parseFloat(widthFt.value) || 0;
        const sqft = len * wid;
        totalSqft.textContent = `${sqft.toFixed(1)} sq ft`;

        try {
            const res = await fetch('/api/carpet-stock');
            const carpets = await res.json();
            let compareHtml = '';
            carpets.forEach(carpet => {
                const enough = carpet.stock_sqft >= sqft;
                compareHtml += `
                    <div class="flex justify-between p-2 bg-white rounded-lg shadow-sm mb-2">
                        <span>${carpet.name}</span>
                        <span class="${enough ? 'text-green-600 font-semibold' : 'text-red-600 font-semibold'}">${carpet.stock_sqft.toFixed(1)} sq ft ${enough ? '(OK)' : '(Low)'}</span>
                    </div>
                `;
            });
            stockCompare.innerHTML = compareHtml;
            carpetResult.classList.remove('hidden');
        } catch (err) {
            stockCompare.innerHTML = '<p class="text-red-500">Error loading stock</p>';
        }
    });

    lengthFt.addEventListener('input', calcBtn.click);
    widthFt.addEventListener('input', calcBtn.click);

    // Usage Toggle
    const togglePaints = document.getElementById('toggle-paints');
    const toggleCarpets = document.getElementById('toggle-carpets');
    const usageTbody = document.getElementById('usage-tbody');

    async function loadUsage(type) {
        try {
            const res = await fetch(`/api/usage-reports/${type}`);
            const reports = await res.json();
            let html = '';
            reports.forEach(report => {
                html += `
                    <tr class="hover:bg-gray-50 transition">
                        <td class="p-3 font-mono">${report.job_id}</td>
                        <td class="p-3 text-gray-500">${new Date(report.created_at).toLocaleString()}</td>
                        <td class="p-3 text-right font-mono">${report.total_volume_ml?.toFixed(1) || report.total_sqft || 'N/A'} ${report.unit || 'ml'}</td>
                    </tr>
                `;
            });
            usageTbody.innerHTML = html || '<tr><td colspan="3" class="p-8 text-center text-gray-500">No reports</td></tr>';
        } catch (err) {
            usageTbody.innerHTML = '<tr><td colspan="3" class="p-8 text-center text-red-500">Error loading</td></tr>';
        }
    }

    togglePaints.addEventListener('click', () => {
        togglePaints.classList.add('bg-purple-600', 'text-white');
        togglePaints.classList.remove('bg-gray-200', 'text-gray-700');
        toggleCarpets.classList.add('bg-gray-200', 'text-gray-700');
        toggleCarpets.classList.remove('bg-purple-600', 'text-white');
        loadUsage('paints');
    });

    toggleCarpets.addEventListener('click', () => {
        toggleCarpets.classList.add('bg-purple-600', 'text-white');
        toggleCarpets.classList.remove('bg-gray-200', 'text-gray-700');
        togglePaints.classList.add('bg-gray-200', 'text-gray-700');
        togglePaints.classList.remove('bg-purple-600', 'text-white');
        loadUsage('carpets');
    });

// Init paints
    togglePaints.click();
});

// Tinting Area
async function loadColors() {
    try {
        const res = await fetch('/api/products');
        const products = await res.json();
        const formulas = products.filter(p => p.category === 'final_color' || p.category === 'carpet_formula');
        const select = document.getElementById('color-select');
        select.innerHTML = '<option value="">Select Color</option>' + 
            formulas.map(p => `<option value="${p.id}">${p.name} (ID: ${p.id})</option>`).join('');
    } catch (err) {
        console.error('Colors load error:', err);
    }
}

document.getElementById('color-select').addEventListener('change', async function() {
    const colorId = this.value;
    const preview = document.getElementById('formula-preview');
    const executeBtn = document.getElementById('execute-tint');
    const ingredientsList = document.getElementById('ingredients-list');
    
    if (!colorId) {
        preview.classList.add('hidden');
        executeBtn.disabled = true;
        return;
    }
    
    try {
        const res = await fetch(`/api/formulas/${colorId}`);
        const ingredients = await res.json();
        ingredientsList.innerHTML = ingredients.map(ing => 
            `<div class="flex justify-between text-sm"><span>${ing.pigment_name}</span><span class="font-mono">${ing.quantity} ml</span></div>`
        ).join('');
        preview.classList.remove('hidden');
        executeBtn.disabled = false;
    } catch (err) {
        console.error('Formula load error:', err);
    }
});

document.getElementById('execute-tint').addEventListener('click', async function() {
    const colorId = document.getElementById('color-select').value;
    const scale = parseFloat(document.getElementById('tint-scale').value) || 1.0;
    const btn = this;
    btn.disabled = true;
    btn.textContent = 'Executing...';
    
    try {
        const res = await fetch('/tinting/execute', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({result_color_id: colorId, scale_factor: scale})
        });
        const result = await res.json();
        const resultDiv = document.getElementById('tint-result');
        if (result.success) {
            resultDiv.innerHTML = `<p class="text-green-600 font-semibold">✅ Success! Job: ${result.job_id}, Total: ${result.total_ml.toFixed(1)} ml</p>`;
            resultDiv.classList.remove('hidden', 'bg-red-50', 'border-red-200');
            resultDiv.classList.add('bg-green-50', 'border-green-200');
        } else {
            resultDiv.innerHTML = `<p class="text-red-600 font-semibold">❌ Failed: ${result.error}</p>`;
            resultDiv.classList.remove('hidden', 'bg-green-50', 'border-green-200');
            resultDiv.classList.add('bg-red-50', 'border-red-200');
        }
    } catch (err) {
        console.error('Tint execute error:', err);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Execute Tinting';
        document.getElementById('color-select').value = '';
        document.getElementById('formula-preview').classList.add('hidden');
    }
});

// Carpet Deduction
async function loadCarpetRolls() {
    try {
        const res = await fetch('/api/carpet-stock');
        const carpets = await res.json();
        const select = document.getElementById('carpet-roll-select');
        select.innerHTML = '<option value="">Select Roll</option>' + 
            carpets.map(c => `<option value="${c.name}" data-id="${c.name.split(' ')[0]}">${c.name} (${c.stock_sqft.toFixed(1)} sq ft)</option>`).join('');
    } catch (err) {
        console.error('Carpet rolls error:', err);
    }
}

document.getElementById('deduct-carpet').addEventListener('click', async function() {
    const sqft = parseFloat(document.getElementById('total-sqft').textContent);
    if (!sqft || sqft <= 0) return alert('Calculate area first');
    
    const select = document.getElementById('carpet-roll-select');
    const rollName = select.value;
    if (!rollName) return alert('Select roll');
    
    // Extract ID from name (e.g., 'Black' -> find product ID; approx via name for demo)
    // In prod, use proper ID mapping
    const productId = 30;  // Placeholder; fetch real ID via /api/products filter carpet name
    const btn = this;
    btn.disabled = true;
    btn.textContent = 'Deducting...';
    
    try {
        const res = await fetch('/api/stock-adjust', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({product_id: productId, quantity: -sqft, reason: `carpet_cut_${rollName}_${sqft}sqft`})
        });
        const result = await res.json();
        const resultDiv = document.getElementById('deduct-result');
        if (result.success) {
            resultDiv.innerHTML = `<p class="text-green-600 font-semibold">✅ Deducted ${sqft.toFixed(1)} sq ft from ${rollName}. New stock: ${result.new_stock.toFixed(1)}</p>`;
            resultDiv.classList.add('bg-green-50', 'border-green-200');
        } else {
            resultDiv.innerHTML = `<p class="text-red-600">❌ Deduct failed</p>`;
            resultDiv.classList.add('bg-red-50', 'border-red-200');
        }
        resultDiv.classList.remove('hidden');
        loadCarpetRolls();  // Refresh
    } catch (err) {
        console.error('Deduct error:', err);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Cut & Deduct Sq Ft';
    }
});

document.getElementById('carpet-roll-select').addEventListener('change', function() {
    document.getElementById('deduct-carpet').disabled = !this.value;
});

loadColors();
loadCarpetRolls();
});

