/**
 * IWS Calculator
 * Calculates Ice & Water Shield requirements for roofing projects
 */

(function() {
    'use strict';

    // ─── Constants ───────────────────────────────────────────────────────────
    const ROLL_WIDTH_INCHES = 36;
    const ROLL_WIDTH_FEET = 3;
    const SQ_FEET_PER_SQUARE = 100;

    // ─── Wall Thickness Lookup (inches) ──────────────────────────────────────
    const WALL_THICKNESS = {
        '2x4': {
            vinyl: 6,
            wood: 6,
            stucco: 6,
            brick: 8
        },
        '2x6': {
            vinyl: 8,
            wood: 8,
            stucco: 10,
            brick: 10
        }
    };

    // ─── DOM Elements ────────────────────────────────────────────────────────
    const els = {
        projectName: document.getElementById('projectName'),
        projectAddress: document.getElementById('projectAddress'),
        roofSize: document.getElementById('roofSize'),
        calcMode: document.getElementsByName('calcMode'),
        roofPitch: document.getElementById('roofPitch'),
        insideWall: document.getElementById('insideWall'),
        eaveLength: document.getElementById('eaveLength'),
        valleyLength: document.getElementById('valleyLength'),
        soffitDepth: document.getElementById('soffitDepth'),
        studSize: document.getElementById('studSize'),
        exteriorType: document.getElementById('exteriorType'),
        calculateBtn: document.getElementById('calculateBtn'),
        clearBtn: document.getElementById('clearBtn'),
        roofPlanBtn: document.getElementById('roofPlanBtn'),
        savePdfBtn: document.getElementById('savePdfBtn'),
        closeRoofPlan: document.getElementById('closeRoofPlan'),
        roofPlanPanel: document.getElementById('roofPlanPanel'),
        resultsSection: document.getElementById('resultsSection'),
        actualTotal: document.getElementById('actualTotal'),
        actualSupport: document.getElementById('actualSupport'),
        actualEaveCalc: document.getElementById('actualEaveCalc'),
        actualValleyCalc: document.getElementById('actualValleyCalc'),
        actualFeltReduction: document.getElementById('actualFeltReduction'),
        fullRollTotal: document.getElementById('fullRollTotal'),
        fullRollSupport: document.getElementById('fullRollSupport'),
        fullRollEaveCalc: document.getElementById('fullRollEaveCalc'),
        fullRollValleyCalc: document.getElementById('fullRollValleyCalc'),
        fullRollFeltReduction: document.getElementById('fullRollFeltReduction'),
        labelCoverage: document.getElementById('labelCoverage'),
        labelRise: document.getElementById('labelRise'),
        labelPitch: document.getElementById('labelPitch'),
        labelInsideWall: document.getElementById('labelInsideWall'),
        labelSoffit: document.getElementById('labelSoffit'),
        labelWallThickness: document.getElementById('labelWallThickness'),
        diagramImg: document.getElementById('diagramImg'),
        saveDiagramBtn: document.getElementById('saveDiagramBtn'),
        year: document.getElementById('year'),
        historySection: document.getElementById('historySection'),
        historyList: document.getElementById('historyList')
    };

    // ─── Helpers ─────────────────────────────────────────────────────────────
    function roundOneDecimal(num) {
        return Math.round(num * 10) / 10;
    }

    function formatNumber(num) {
        return num.toLocaleString('en-US', {
            minimumFractionDigits: 1,
            maximumFractionDigits: 1
        });
    }

    function getCalcMode() {
        for (const radio of els.calcMode) {
            if (radio.checked) return radio.value;
        }
        return 'eaveValley';
    }

    function getInputs() {
        return {
            projectName: (els.projectName.value || '').trim(),
            projectAddress: (els.projectAddress.value || '').trim(),
            roofSizeSq: parseFloat(els.roofSize.value) || 0,
            insideWall: parseFloat(els.insideWall.value) || 24,
            roofPitch: parseFloat(els.roofPitch.value) || 0,
            eaveLength: parseFloat(els.eaveLength.value) || 0,
            valleyLength: parseFloat(els.valleyLength.value) || 0,
            soffitDepth: parseFloat(els.soffitDepth.value) || 0,
            studSize: els.studSize.value,
            exteriorType: els.exteriorType.value,
            calcMode: getCalcMode()
        };
    }

    function getWallThickness(studSize, exteriorType) {
        const stud = WALL_THICKNESS[studSize];
        return stud ? (stud[exteriorType] || 0) : 0;
    }

    function calculateGeometry(inputs) {
        const wallThickness = getWallThickness(inputs.studSize, inputs.exteriorType);
        const run = inputs.soffitDepth + wallThickness + inputs.insideWall;
        const rise = (run / 12) * inputs.roofPitch;
        const coveragePrecise = Math.sqrt(Math.pow(run, 2) + Math.pow(rise, 2));
        const coverage = roundOneDecimal(coveragePrecise);

        return {
            wallThickness,
            run,
            rise,
            coverage,
            coveragePrecise
        };
    }

    // ─── Calculation Modes ───────────────────────────────────────────────────
    function calculateActualSF(inputs, geom) {
        const eaveSf = roundOneDecimal(inputs.eaveLength * (geom.coveragePrecise / 12));
        const valleySf = roundOneDecimal(inputs.valleyLength * ROLL_WIDTH_FEET);
        const total = inputs.calcMode === 'eaveOnly'
            ? eaveSf
            : roundOneDecimal(eaveSf + valleySf);
        const roofSf = inputs.roofSizeSq * SQ_FEET_PER_SQUARE;
        const feltReduction = roundOneDecimal(roofSf - eaveSf);
        const feltSq = roundOneDecimal(feltReduction / SQ_FEET_PER_SQUARE);

        return {
            eaveSf,
            valleySf,
            total,
            roofSf,
            feltReduction,
            feltSq,
            coverage: geom.coverage,
            wallThickness: geom.wallThickness,
            calcMode: inputs.calcMode
        };
    }

    function calculateFullRoll(inputs, geom) {
        const rollsNeeded = Math.ceil(geom.coverage / ROLL_WIDTH_INCHES);
        const eaveSf = roundOneDecimal(rollsNeeded * ROLL_WIDTH_FEET * inputs.eaveLength);
        const valleySf = roundOneDecimal(inputs.valleyLength * ROLL_WIDTH_FEET);
        const total = inputs.calcMode === 'eaveOnly'
            ? eaveSf
            : roundOneDecimal(eaveSf + valleySf);
        const roofSf = inputs.roofSizeSq * SQ_FEET_PER_SQUARE;
        const feltReduction = roundOneDecimal(roofSf - eaveSf);
        const feltSq = roundOneDecimal(feltReduction / SQ_FEET_PER_SQUARE);

        return {
            rollsNeeded,
            eaveSf,
            valleySf,
            total,
            roofSf,
            feltReduction,
            feltSq,
            coverage: geom.coverage,
            wallThickness: geom.wallThickness,
            calcMode: inputs.calcMode
        };
    }

    // ─── Formatters ──────────────────────────────────────────────────────────
    function formatSupportText(inputs, geom) {
        return `Math Breakdown: Using the predominant soffit depth of ${inputs.soffitDepth} inches, wall thickness of ${geom.wallThickness} inches, and a ${inputs.roofPitch}/12 roof pitch, the ice barrier must extend onto the roof's surface at least ${geom.coverage} inches from the lowest edge of all roof surfaces to a point not less than ${inputs.insideWall} inches inside the exterior wall line of the building.`;
    }

    function formatActualEave(inputs, result) {
        return `Round to the nearest square foot of IWS on the eave using an eave length of ${inputs.eaveLength} LF * (${result.coverage} inches / 12 inches) = ${formatNumber(result.eaveSf)} SF.`;
    }

    function formatFullRollEave(inputs, result) {
        return `With a minimum width of 1 roll, round ${result.coverage}" up to the nearest full roll, requiring ${result.rollsNeeded} rolls. ${result.rollsNeeded} * ${ROLL_WIDTH_FEET} FT * ${inputs.eaveLength} LF eave length = ${formatNumber(result.eaveSf)} SF of IWS.`;
    }

    function formatValley(inputs, result) {
        return `Round to the nearest square foot using a valley length of ${inputs.valleyLength} LF * ${ROLL_WIDTH_FEET} FT Wide Roll = ${formatNumber(result.valleySf)} SF.`;
    }

    function formatFeltReduction(result) {
        return `The roof size, ${formatNumber(result.roofSf)} SF, less the eave's IWS of ${formatNumber(result.eaveSf)} SF = ${formatNumber(result.feltReduction)} SF or ${formatNumber(result.feltSq)} SQs`;
    }

    function buildNoteText(inputs, result, geom) {
        let lines = [];
        lines.push(formatSupportText(inputs, geom));
        lines.push('');
        lines.push(formatActualEave(inputs, result));
        if (result.calcMode !== 'eaveOnly') {
            lines.push('');
            lines.push(formatValley(inputs, result));
        }
        lines.push('');
        lines.push(formatFeltReduction(result));
        return lines.join('\n');
    }

    // ─── History / localStorage ──────────────────────────────────────────────
    const HISTORY_KEY = 'iws_history';
    const MAX_HISTORY = 3;

    function loadHistory() {
        try {
            const raw = localStorage.getItem(HISTORY_KEY);
            return raw ? JSON.parse(raw) : [];
        } catch (e) {
            return [];
        }
    }

    function saveHistory(history) {
        try {
            localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
        } catch (e) {
            // Storage may be full or unavailable; silently fail
        }
    }

    function entriesMatch(a, b) {
        return (
            a.projectName === b.projectName &&
            a.projectAddress === b.projectAddress &&
            a.roofSizeSq === b.roofSizeSq &&
            a.roofPitch === b.roofPitch &&
            a.insideWall === b.insideWall &&
            a.eaveLength === b.eaveLength &&
            a.valleyLength === b.valleyLength &&
            a.soffitDepth === b.soffitDepth &&
            a.studSize === b.studSize &&
            a.exteriorType === b.exteriorType &&
            a.calcMode === b.calcMode
        );
    }

    function addToHistory(inputs, actual, fullRoll) {
        const history = loadHistory();
        const entry = {
            timestamp: Date.now(),
            projectName: inputs.projectName || '',
            projectAddress: inputs.projectAddress || '',
            roofSizeSq: inputs.roofSizeSq,
            roofPitch: inputs.roofPitch,
            insideWall: inputs.insideWall,
            eaveLength: inputs.eaveLength,
            valleyLength: inputs.valleyLength,
            soffitDepth: inputs.soffitDepth,
            studSize: inputs.studSize,
            exteriorType: inputs.exteriorType,
            calcMode: inputs.calcMode,
            actualTotal: actual.total,
            fullRollTotal: fullRoll.total
        };

        // Prevent duplicates: if the most recent entry has identical inputs, skip
        if (history.length > 0 && entriesMatch(history[0], entry)) {
            return;
        }

        history.unshift(entry);
        while (history.length > MAX_HISTORY) {
            history.pop();
        }
        saveHistory(history);
        renderHistory();
    }

    function formatTimestamp(ts) {
        const d = new Date(ts);
        return d.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit'
        });
    }

    function renderHistory() {
        const history = loadHistory();
        if (!history.length) {
            els.historySection.classList.add('hidden');
            return;
        }

        els.historyList.innerHTML = '';
        history.forEach(function(entry, index) {
            const card = document.createElement('div');
            card.className = 'history-card';

            const title = entry.projectName || 'Untitled Project';
            const address = entry.projectAddress || 'No address provided';

            card.innerHTML =
                '<div class="history-info">' +
                    '<div class="history-title">' + escapeHtml(title) + '</div>' +
                    '<div class="history-address">' + escapeHtml(address) + '</div>' +
                '</div>' +
                '<div class="history-meta">' +
                    '<div class="history-totals">' +
                        '<span><strong>Actual:</strong> ' + formatNumber(entry.actualTotal) + ' SF</span>' +
                        '<span><strong>Full Roll:</strong> ' + formatNumber(entry.fullRollTotal) + ' SF</span>' +
                    '</div>' +
                    '<span class="history-time">' + formatTimestamp(entry.timestamp) + '</span>' +
                    '<button type="button" class="btn btn-load" data-history-index="' + index + '">Load</button>' +
                    '<button type="button" class="btn btn-delete" data-history-index="' + index + '" title="Remove">&times;</button>' +
                '</div>';

            els.historyList.appendChild(card);
        });

        // Attach load listeners
        els.historyList.querySelectorAll('.btn-load').forEach(function(btn) {
            btn.addEventListener('click', handleLoadHistory);
        });

        // Attach delete listeners
        els.historyList.querySelectorAll('.btn-delete').forEach(function(btn) {
            btn.addEventListener('click', handleDeleteHistory);
        });

        els.historySection.classList.remove('hidden');
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function handleLoadHistory(e) {
        const index = parseInt(e.target.getAttribute('data-history-index'), 10);
        const history = loadHistory();
        const entry = history[index];
        if (!entry) return;

        els.projectName.value = entry.projectName || '';
        els.projectAddress.value = entry.projectAddress || '';
        els.roofSize.value = entry.roofSizeSq || '';
        els.roofPitch.value = entry.roofPitch || '';
        els.insideWall.value = entry.insideWall || '';
        els.eaveLength.value = entry.eaveLength || '';
        els.valleyLength.value = entry.valleyLength || '';
        els.soffitDepth.value = entry.soffitDepth || '';
        els.studSize.value = entry.studSize || '2x6';
        els.exteriorType.value = entry.exteriorType || 'brick';

        for (const radio of els.calcMode) {
            radio.checked = (radio.value === entry.calcMode);
        }

        // Re-run calculation to restore results and diagram labels
        handleCalculate();

        // Scroll to form top
        els.projectName.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function handleDeleteHistory(e) {
        const index = parseInt(e.target.getAttribute('data-history-index'), 10);
        const history = loadHistory();
        if (index < 0 || index >= history.length) return;

        history.splice(index, 1);
        saveHistory(history);
        renderHistory();
    }

    // ─── Display ─────────────────────────────────────────────────────────────
    function displayResults(actual, fullRoll, inputs, geom) {
        const actualValleyLine = document.getElementById('actualValleyLine');
        const fullRollValleyLine = document.getElementById('fullRollValleyLine');

        const supportHtml = '<strong>Math Breakdown:</strong> ' + formatSupportText(inputs, geom).replace('Math Breakdown: ', '');

        // Actual SF
        els.actualTotal.textContent = `${formatNumber(actual.total)} SF`;
        els.actualSupport.innerHTML = supportHtml;
        els.actualEaveCalc.textContent = formatActualEave(inputs, actual);
        if (actual.calcMode === 'eaveOnly') {
            actualValleyLine.classList.add('hidden');
        } else {
            actualValleyLine.classList.remove('hidden');
            els.actualValleyCalc.textContent = formatValley(inputs, actual);
        }
        els.actualFeltReduction.textContent = formatFeltReduction(actual);

        // Full Roll
        els.fullRollTotal.textContent = `${formatNumber(fullRoll.total)} SF`;
        els.fullRollSupport.innerHTML = supportHtml;
        els.fullRollEaveCalc.textContent = formatFullRollEave(inputs, fullRoll);
        if (fullRoll.calcMode === 'eaveOnly') {
            fullRollValleyLine.classList.add('hidden');
        } else {
            fullRollValleyLine.classList.remove('hidden');
            els.fullRollValleyCalc.textContent = formatValley(inputs, fullRoll);
        }
        els.fullRollFeltReduction.textContent = formatFeltReduction(fullRoll);

        // Update diagram overlay labels (positions mapped from number_locations.png)
        els.labelCoverage.textContent = formatNumber(geom.coverage) + '"';
        els.labelRise.textContent = formatNumber(geom.rise) + '"';
        els.labelPitch.textContent = inputs.roofPitch + '/12';
        els.labelInsideWall.textContent = formatNumber(inputs.insideWall) + '"';
        els.labelSoffit.textContent = formatNumber(inputs.soffitDepth) + '"';
        els.labelWallThickness.textContent = formatNumber(geom.wallThickness) + '"';

        // Show results
        els.resultsSection.classList.remove('hidden');
        els.resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // ─── Diagram JPEG Export ───────────────────────────────────────────────
    function buildDiagramCanvas() {
        const img = els.diagramImg;
        if (!img || !img.complete || img.naturalWidth === 0) return null;
        if (!els.labelCoverage.textContent) return null;

        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        const w = img.naturalWidth;
        const h = img.naturalHeight;
        canvas.width = w;
        canvas.height = h;

        // Draw base image
        ctx.drawImage(img, 0, 0, w, h);

        // Label definitions: [element, top%, left%]
        const labels = [
            [els.labelCoverage, 30, 51],
            [els.labelRise, 36, 73],
            [els.labelPitch, 52, 53],
            [els.labelInsideWall, 55, 65],
            [els.labelSoffit, 67, 34],
            [els.labelWallThickness, 95, 47]
        ];

        // Text styling (scaled to full-resolution image)
        const fontSize = Math.round(h * 0.026); // ~2.6% of image height
        ctx.font = 'bold ' + fontSize + 'px "Segoe UI", Tahoma, Geneva, Verdana, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';

        labels.forEach(function(pair) {
            const el = pair[0];
            const text = el.textContent.trim();
            if (!text) return;

            const x = (pair[2] / 100) * w;
            const y = (pair[1] / 100) * h;

            // White glow shadow for readability
            ctx.shadowColor = 'rgba(255, 255, 255, 0.9)';
            ctx.shadowBlur = fontSize * 0.3;
            ctx.fillStyle = '#4a3c2a';
            ctx.fillText(text, x, y);

            // Reset shadow for next label
            ctx.shadowColor = 'transparent';
            ctx.shadowBlur = 0;
        });

        return canvas;
    }

    function handleSaveDiagram() {
        const img = els.diagramImg;
        if (!img.complete || img.naturalWidth === 0) {
            alert('Diagram image is not ready yet. Please try again.');
            return;
        }

        // Check if labels have been populated
        if (!els.labelCoverage.textContent) {
            alert('Please run a calculation first so the diagram has values to display.');
            return;
        }

        const canvas = buildDiagramCanvas();
        if (!canvas) {
            alert('Diagram is not ready yet. Please try again.');
            return;
        }
        const inputs = getInputs();
        const rawName = (inputs.projectName || '').trim();
        const safeName = rawName.replace(/\s+/g, '_').replace(/[\\/:*?"<>|]/g, '');
        const fileName = safeName ? 'IWS_Diagram_' + safeName + '.jpg' : 'IWS_Diagram.jpg';

        const dataUrl = canvas.toDataURL('image/jpeg', 0.95);
        const link = document.createElement('a');
        link.href = dataUrl;
        link.download = fileName;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    // ─── PDF Export ──────────────────────────────────────────────────────
    function askCalcChoice() {
        // Small modal asking which calculation to print on the PDF.
        return new Promise(function(resolve) {
            var overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.45);' +
                'display:flex;align-items:center;justify-content:center;z-index:9999;';
            var box = document.createElement('div');
            box.style.cssText = 'background:#fff;border-radius:8px;padding:24px;max-width:360px;' +
                'text-align:center;box-shadow:0 8px 30px rgba(0,0,0,0.3);font-family:inherit;';
            box.innerHTML = '<h3 style="margin:0 0 8px;">Which calculation should the PDF use?</h3>' +
                '<p style="margin:0 0 16px;color:#555;font-size:0.9em;">Pick the coverage number to print on the report.</p>';
            var row = document.createElement('div');
            row.style.cssText = 'display:flex;gap:10px;justify-content:center;flex-wrap:wrap;';
            function mkBtn(label, value) {
                var b = document.createElement('button');
                b.type = 'button';
                b.className = 'btn btn-primary';
                b.textContent = label;
                b.style.cssText = 'padding:10px 16px;cursor:pointer;';
                b.onclick = function() { document.body.removeChild(overlay); resolve(value); };
                return b;
            }
            row.appendChild(mkBtn('Actual SF', 'actual'));
            row.appendChild(mkBtn('Full Roll SF', 'fullRoll'));
            var cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.className = 'btn btn-secondary';
            cancel.textContent = 'Cancel';
            cancel.style.cssText = 'padding:10px 16px;cursor:pointer;';
            cancel.onclick = function() { document.body.removeChild(overlay); resolve(null); };
            row.appendChild(cancel);
            box.appendChild(row);
            overlay.appendChild(box);
            document.body.appendChild(overlay);
        });
    }

    function handleSavePdf() {
        askCalcChoice().then(function(calcChoice) {
            if (!calcChoice) return;
            exportPdf(calcChoice);
        });
    }

    function exportPdf(calcChoice) {
        var inputs = getInputs();
        var geom = calculateGeometry(inputs);
        var actual = calculateActualSF(inputs, geom);
        var fullRoll = calculateFullRoll(inputs, geom);

        var diagramCanvas = buildDiagramCanvas();
        var diagramImage = diagramCanvas ? diagramCanvas.toDataURL('image/jpeg', 0.9) : null;

        var payload = {
            projectName: inputs.projectName,
            projectAddress: inputs.projectAddress,
            roofSizeSq: inputs.roofSizeSq,
            roofPitch: inputs.roofPitch,
            eaveLength: inputs.eaveLength,
            valleyLength: inputs.valleyLength,
            calcMode: inputs.calcMode,
            insideWall: inputs.insideWall,
            soffitDepth: inputs.soffitDepth,
            coverage: geom.coverage,
            wallThickness: geom.wallThickness,
            actualTotal: actual.total,
            fullRollTotal: fullRoll.total,
            feltReduction: actual.feltReduction,
            feltSq: actual.feltSq,
            calcChoice: calcChoice,
            diagramImage: diagramImage
        };

        els.savePdfBtn.disabled = true;
        els.savePdfBtn.textContent = 'Generating...';
        console.log('[iws] pdf export:', {project: inputs.projectName, actual: actual.total, fullRoll: fullRoll.total});

        fetch('/iws/pdf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function(r) {
            return r.json();
        }).then(function(data) {
            if (data.error) { throw new Error(data.error); }
            if (data.ok && data.filename) {
                if (window.pywebview && window.pywebview.api && window.pywebview.api.save_file) {
                    els.savePdfBtn.textContent = 'Saving...';
                    return window.pywebview.api.save_file(data.filename).then(function(res) {
                        if (!res.ok && res.error !== 'Save cancelled.') {
                            throw new Error(res.error || 'Could not save file.');
                        }
                        els.savePdfBtn.textContent = 'Saved!';
                        setTimeout(function() { els.savePdfBtn.textContent = 'Save as PDF'; }, 2000);
                    });
                } else {
                    // Browser fallback: direct download link
                    window.location.href = data.download;
                    els.savePdfBtn.textContent = 'Save as PDF';
                }
            }
        }).catch(function(err) {
            alert('PDF export failed: ' + err.message);
        }).finally(function() {
            els.savePdfBtn.disabled = false;
            els.savePdfBtn.textContent = 'Save as PDF';
        });
    }

    // ─── Event Handlers ──────────────────────────────────────────────────────
    function handleCalculate() {
        const inputs = getInputs();

        // Basic validation
        if (inputs.roofSizeSq <= 0) {
            alert('Please enter a valid Roof Size.');
            els.roofSize.focus();
            return;
        }
        if (inputs.roofPitch <= 0) {
            alert('Please enter a valid Roof Pitch.');
            els.roofPitch.focus();
            return;
        }
        if (inputs.insideWall <= 0) {
            alert('Please enter a valid Inside Exterior Wall distance.');
            els.insideWall.focus();
            return;
        }
        if (inputs.eaveLength < 0) {
            alert('Please enter a valid Eave Length.');
            els.eaveLength.focus();
            return;
        }
        if (inputs.valleyLength < 0) {
            alert('Please enter a valid Valley Length.');
            els.valleyLength.focus();
            return;
        }

        const geom = calculateGeometry(inputs);
        const actual = calculateActualSF(inputs, geom);
        const fullRoll = calculateFullRoll(inputs, geom);

        displayResults(actual, fullRoll, inputs, geom);

        // Enable IWS Diagram button after successful calculation
        els.roofPlanBtn.disabled = false;
        els.savePdfBtn.disabled = false;

        // Persist calculation to localStorage history
        addToHistory(inputs, actual, fullRoll);
    }

    function handleClear() {
        els.projectName.value = '';
        els.projectAddress.value = '';
        els.roofSize.value = '';
        els.roofPitch.value = '';
        els.insideWall.value = '';
        els.eaveLength.value = '';
        els.valleyLength.value = '';
        els.soffitDepth.value = '';
        els.studSize.value = '2x6';
        els.exteriorType.value = 'brick';

        els.labelCoverage.textContent = '';
        els.labelRise.textContent = '';
        els.labelPitch.textContent = '';
        els.labelInsideWall.textContent = '';
        els.labelSoffit.textContent = '';
        els.labelWallThickness.textContent = '';

        els.resultsSection.classList.add('hidden');
        els.roofPlanPanel.classList.add('hidden');
        els.roofPlanBtn.setAttribute('aria-expanded', 'false');
        els.roofPlanBtn.disabled = true;
        els.savePdfBtn.disabled = true;

        els.roofSize.focus();
    }

    function toggleRoofPlan() {
        const isHidden = els.roofPlanPanel.classList.contains('hidden');
        if (isHidden) {
            els.roofPlanPanel.classList.remove('hidden');
            els.roofPlanBtn.setAttribute('aria-expanded', 'true');
        } else {
            els.roofPlanPanel.classList.add('hidden');
            els.roofPlanBtn.setAttribute('aria-expanded', 'false');
        }
    }

    function closeRoofPlanPanel() {
        els.roofPlanPanel.classList.add('hidden');
        els.roofPlanBtn.setAttribute('aria-expanded', 'false');
    }

    function handleCopy(e) {
        const btn = e.target;
        const cardId = btn.getAttribute('data-copy-target');
        const card = document.getElementById(cardId);
        if (!card) return;

        const totalEl = card.querySelector('.result-total');
        const supportEl = card.querySelector('.support-text');
        const calcLines = card.querySelectorAll('.calc-line');

        const parts = [];

        if (totalEl) {
            parts.push('IWS: ' + totalEl.textContent.trim());
        }

        // Math Breakdown (support text)
        if (supportEl && !supportEl.classList.contains('hidden')) {
            const supportText = supportEl.innerText.trim();
            if (supportText) {
                parts.push('Math Breakdown: ' + supportText.replace(/^Math Breakdown:\s*/, ''));
            }
        }

        // Collect calc lines - each on its own line
        calcLines.forEach(el => {
            if (el.classList.contains('hidden')) return;
            const strong = el.querySelector('strong');
            const span = el.querySelector('span');
            if (!strong || !span) return;

            const label = strong.innerText.trim().toUpperCase();
            const text = span.innerText.trim();
            const formatted = label + ' ' + text;

            if (label.includes('FELT')) {
                parts.push(''); // blank line before felt reduction
            }
            parts.push(formatted);
        });

        const text = parts.join('\n');

        navigator.clipboard.writeText(text).then(() => {
            const originalText = btn.textContent;
            btn.textContent = 'Copied!';
            btn.classList.add('copied');
            setTimeout(() => {
                btn.textContent = originalText;
                btn.classList.remove('copied');
            }, 2000);
        }).catch(() => {
            btn.textContent = 'Copy failed';
            setTimeout(() => {
                btn.textContent = 'Copy Note';
            }, 2000);
        });
    }

    // ─── Init ────────────────────────────────────────────────────────────────
    function init() {
        els.year.textContent = new Date().getFullYear();

        els.calculateBtn.addEventListener('click', handleCalculate);
        els.clearBtn.addEventListener('click', handleClear);
        els.roofPlanBtn.addEventListener('click', toggleRoofPlan);
        els.closeRoofPlan.addEventListener('click', closeRoofPlanPanel);
        els.saveDiagramBtn.addEventListener('click', handleSaveDiagram);
        els.savePdfBtn.addEventListener('click', handleSavePdf);

        // Copy buttons
        document.querySelectorAll('.btn-copy').forEach(btn => {
            btn.addEventListener('click', handleCopy);
        });

        // Allow Enter key to calculate
        document.querySelectorAll('input').forEach(input => {
            input.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    handleCalculate();
                }
            });
        });

        // Restore any persisted history on page load
        renderHistory();
    }

    init();
})();
