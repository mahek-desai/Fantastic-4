/* ============================================
   BTP Hotspot Intelligence Dashboard — JS
   Phase 5.1: Data Loader + All Page Renderers
   ============================================ */

// ── Global State ──
const DATA = {};
let mapInstance = null;
let mapMarkers = [];

// ── Utility Helpers ──
const fmt = (n, d = 0) => {
    if (n == null || isNaN(n)) return '—';
    return Number(n).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
};

const pct = (n, d = 1) => {
    if (n == null || isNaN(n)) return '—';
    return (Number(n) * 100).toFixed(d) + '%';
};

const bandClass = (band) => {
    if (!band) return '';
    const b = band.toLowerCase().replace(/\s+/g, '-');
    return `band-${b}`;
};

const riskTagClass = (band) => {
    if (!band) return '';
    const b = band.toLowerCase().replace(/\s+/g, '-');
    return `risk-${b}`;
};

const riskColor = (band) => {
    const map = {
        'Very High': '#ef4444',
        'High': '#f97316',
        'Medium': '#eab308',
        'Low': '#22c55e'
    };
    return map[band] || '#64748b';
};

// ── Phase 5.1: Data Loading Layer ──
function loadCSV(path) {
    return new Promise((resolve, reject) => {
        Papa.parse(path, {
            download: true,
            header: true,
            skipEmptyLines: true,
            dynamicTyping: true,
            complete: (results) => resolve(results.data),
            error: (err) => reject(err)
        });
    });
}

function normalizeColumns(rows) {
    return rows.map(row => {
        const out = {};
        for (const [k, v] of Object.entries(row)) {
            const key = k.trim().toLowerCase().replace(/\s+/g, '_');
            out[key] = v;
        }
        return out;
    });
}

async function loadAllData() {
    const base = '../dataset/';
    try {
        const [hotspotZones, locationRanking, deployRecs, featureImp, errorAnalysis, mapData, summaryReport, predictions] = await Promise.all([
            loadCSV(base + 'hotspot_zones.csv'),
            loadCSV(base + 'location_ranking.csv'),
            loadCSV(base + 'deployment_recommendations.csv'),
            loadCSV(base + 'feature_importance.csv'),
            loadCSV(base + 'prediction_error_analysis.csv'),
            loadCSV(base + 'hotspot_map_data.csv'),
            loadCSV(base + 'hotspot_summary_report.csv'),
            loadCSV(base + 'step4_predictions.csv')
        ]);

        DATA.hotspotZones = normalizeColumns(hotspotZones);
        DATA.locationRanking = normalizeColumns(locationRanking);
        DATA.deployRecs = normalizeColumns(deployRecs);
        DATA.featureImp = normalizeColumns(featureImp);
        DATA.errorAnalysis = normalizeColumns(errorAnalysis);
        DATA.mapData = normalizeColumns(mapData);
        DATA.summaryReport = normalizeColumns(summaryReport);
        DATA.predictions = normalizeColumns(predictions);

        // Ensure zone_id consistency
        [DATA.hotspotZones, DATA.deployRecs, DATA.errorAnalysis, DATA.mapData].forEach(table => {
            table.forEach(r => {
                if (r.zone_id && typeof r.zone_id === 'string') {
                    r.zone_id = r.zone_id.trim().toUpperCase();
                }
            });
        });

        // ── Helper tables ──
        // Top hotspots
        DATA.topHotspots = [...DATA.hotspotZones]
            .sort((a, b) => (b.hotspot_score || 0) - (a.hotspot_score || 0))
            .slice(0, 10);

        // Rankings
        DATA.rankingByEntity = DATA.locationRanking;

        // Forecast / deployment
        DATA.forecast = [...DATA.deployRecs]
            .sort((a, b) => (b.predicted_risk_score || 0) - (a.predicted_risk_score || 0));

        // Feature importance sorted
        DATA.featureSorted = [...DATA.featureImp]
            .sort((a, b) => (b.average || 0) - (a.average || 0));

        // Error analysis sorted
        DATA.errorSorted = [...DATA.errorAnalysis]
            .sort((a, b) => (a.absolute_error || 0) - (b.absolute_error || 0));

        // Summary lookup
        DATA.summaryMap = {};
        DATA.summaryReport.forEach(r => {
            DATA.summaryMap[r.metric_name] = r.metric_value;
        });

        // Merge map data with deployment data for popups
        const deployMap = {};
        DATA.deployRecs.forEach(r => { deployMap[r.zone_id] = r; });
        DATA.mapData.forEach(r => {
            const d = deployMap[r.zone_id];
            if (d) {
                r.predicted_next_day_violations = d.predicted_next_day_violations;
                r.predicted_risk_score = d.predicted_risk_score;
                r.predicted_risk_band = d.predicted_risk_band;
                r.recommended_action = d.recommended_action;
                r.manpower_estimate = d.manpower_estimate;
                r.time_window_to_watch = d.time_window_to_watch;
            }
        });

        console.log('✅ All data loaded.', Object.keys(DATA).map(k => `${k}: ${Array.isArray(DATA[k]) ? DATA[k].length + ' rows' : typeof DATA[k]}`));

    } catch (err) {
        console.error('❌ Data loading failed:', err);
        document.getElementById('loading-overlay').innerHTML =
            `<div class="loader-container"><p class="loader-text" style="color:#f43f5e">Failed to load data</p><p class="loader-subtext">${err.message || err}</p></div>`;
    }
}

// ── Navigation ──
function initNavigation() {
    const btns = document.querySelectorAll('.nav-btn');
    btns.forEach(btn => {
        btn.addEventListener('click', () => {
            const page = btn.dataset.page;
            btns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.getElementById(`page-${page}`).classList.add('active');

            // Close mobile sidebar on link click
            if (window.innerWidth <= 860) {
                document.body.classList.remove('sidebar-open');
            }

            // Lazy-init map
            if (page === 'map' && !mapInstance) {
                setTimeout(initMap, 100);
            }
            if (page === 'map' && mapInstance) {
                setTimeout(() => mapInstance.invalidateSize(), 150);
            }

            // Force Chart.js to recalculate dimensions since sections are shown/hidden
            setTimeout(() => {
                if (typeof Chart !== 'undefined' && Chart.instances) {
                    Object.values(Chart.instances).forEach(chart => {
                        chart.resize();
                    });
                }
            }, 100);
        });
    });

    // Tabs
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const parent = tab.closest('.tabs-container');
            parent.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            parent.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(tab.dataset.tab).classList.add('active');
        });
    });

    // Sidebar toggle functionality
    const sidebarToggleBtn = document.getElementById('sidebar-toggle-btn');
    const sidebarCollapseBtn = document.getElementById('sidebar-collapse-btn');
    const sidebarOverlay = document.getElementById('sidebar-overlay');

    if (sidebarToggleBtn) {
        sidebarToggleBtn.addEventListener('click', () => {
            if (window.innerWidth <= 860) {
                document.body.classList.add('sidebar-open');
            } else {
                document.body.classList.remove('sidebar-collapsed');
            }
        });
    }

    if (sidebarCollapseBtn) {
        sidebarCollapseBtn.addEventListener('click', () => {
            if (window.innerWidth <= 860) {
                document.body.classList.remove('sidebar-open');
            } else {
                document.body.classList.add('sidebar-collapsed');
            }
        });
    }

    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', () => {
            document.body.classList.remove('sidebar-open');
        });
    }
}

// ── Phase 5.2: Executive Summary ──
function renderExecutiveSummary() {
    const s = DATA.summaryMap;
    const pred = DATA.predictions[0] || {};

    const kpis = [
        { icon: '📊', value: fmt(s['Total Violations Processed']), label: 'Total Violations Processed' },
        { icon: '📍', value: fmt(s['Total Geo Clusters (Zones) Detected']), label: 'Hotspot Zones Detected' },
        { icon: '🔴', value: fmt(s['Very High Severity Zones']), label: 'Very High-Risk Zones' },
        { icon: '⏰', value: s['Peak Hour Violations Share in Hotspots'], label: 'Peak-Hour Violation Share' },
        { icon: '🎯', value: pct(pred.val_p10, 1), label: 'Best Val Daily P@10' },
        { icon: '🤖', value: pred.best_model || 'Ensemble', label: 'Best Model' },
    ];

    const grid = document.getElementById('kpi-grid');
    grid.innerHTML = kpis.map(k => `
        <div class="kpi-card">
            <div class="kpi-icon">${k.icon}</div>
            <div class="kpi-value">${k.value}</div>
            <div class="kpi-label">${k.label}</div>
        </div>
    `).join('');

    // Top hotspot zone
    const topHS = DATA.topHotspots[0];
    if (topHS) {
        document.getElementById('exec-top-hotspot').innerHTML = `
            <div class="top-zone-detail">
                <div class="zone-name-big">${topHS.zone_name}</div>
                <div class="zone-meta">
                    <span class="zone-tag risk-very-high">Score: ${fmt(topHS.hotspot_score, 1)}</span>
                    <span class="zone-tag">${fmt(topHS.total_violations)} violations</span>
                    <span class="zone-tag">📍 ${topHS.top_police_station}</span>
                    <span class="zone-tag">⏰ ${topHS.dominant_time_bucket}</span>
                </div>
            </div>
        `;
    }

    // Top deployment zone
    const topDep = DATA.forecast[0];
    if (topDep) {
        document.getElementById('exec-top-deploy').innerHTML = `
            <div class="top-zone-detail">
                <div class="zone-name-big">${topDep.zone_name}</div>
                <div class="zone-meta">
                    <span class="zone-tag risk-very-high">Risk: ${fmt(topDep.predicted_risk_score, 1)}</span>
                    <span class="zone-tag">${fmt(topDep.predicted_next_day_violations, 1)} predicted</span>
                    <span class="zone-tag">👮 ${topDep.manpower_estimate} officers</span>
                    <span class="zone-tag">⏰ ${topDep.time_window_to_watch}</span>
                </div>
            </div>
        `;
    }

    // Severity distribution chart
    const bands = ['Very High', 'High', 'Medium', 'Low'];
    const bandCounts = bands.map(b =>
        DATA.hotspotZones.filter(z => z.hotspot_band === b).length
    );

    new Chart(document.getElementById('severity-chart'), {
        type: 'doughnut',
        data: {
            labels: bands,
            datasets: [{
                data: bandCounts,
                backgroundColor: ['#ff3860', '#ff7600', '#ffdd00', '#00e676'],
                borderColor: 'rgba(13, 16, 21, 0.9)',
                borderWidth: 2,
                hoverOffset: 12
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '60%',
            onClick: (event, elements) => {
                if (elements.length > 0) {
                    const index = elements[0].index;
                    const bandName = bands[index];
                    // Navigate to Map page
                    const mapBtn = document.getElementById('nav-map');
                    if (mapBtn) {
                        mapBtn.click();
                        // Apply band filter
                        const filterBand = document.getElementById('filter-band');
                        if (filterBand) {
                            filterBand.value = bandName;
                            // Trigger change event to redraw map markers
                            filterBand.dispatchEvent(new Event('change'));
                        }
                    }
                }
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#cbd5e1',
                        font: { family: 'Outfit', size: 12, weight: 600 },
                        padding: 20,
                        usePointStyle: true,
                        pointStyleWidth: 12
                    }
                },
                tooltip: {
                    backgroundColor: '#111413',
                    titleColor: '#f8fafc',
                    bodyColor: '#cbd5e1',
                    borderColor: 'rgba(255,255,255,0.08)',
                    borderWidth: 1,
                    cornerRadius: 8,
                    padding: 12,
                    callbacks: {
                        label: (ctx) => ` ${ctx.label}: ${ctx.raw} zones (${(ctx.raw / DATA.hotspotZones.length * 100).toFixed(1)}%)`
                    }
                }
            }
        }
    });
}

function initMap() {
    // Define base layers
    const googleRoadmap = L.tileLayer('https://mt{s}.google.com/vt/lyrs=m&x={x}&y={y}&z={z}', {
        subdomains: '0123',
        attribution: '© Google Maps',
        maxZoom: 20
    });

    const cartoPositron = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '© OpenStreetMap © CARTO',
        maxZoom: 19
    });

    const cartoDark = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '© OpenStreetMap © CARTO',
        maxZoom: 19
    });

    const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19
    });

    // Initialize map with Google Maps as default
    mapInstance = L.map('hotspot-map', {
        zoomControl: true,
        attributionControl: true,
        layers: [googleRoadmap]
    }).setView([12.97, 77.59], 12);

    // Add base layers selector
    const baseMaps = {
        "Google Maps (Default)": googleRoadmap,
        "CartoDB Positron (Light)": cartoPositron,
        "CartoDB Dark Matter (Dark)": cartoDark,
        "OpenStreetMap (OSM)": osm
    };

    L.control.layers(baseMaps, null, { position: 'topright' }).addTo(mapInstance);

    renderMapMarkers();

    // Filters
    document.getElementById('filter-band').addEventListener('change', renderMapMarkers);
    document.getElementById('filter-police').addEventListener('change', renderMapMarkers);
    document.getElementById('filter-time').addEventListener('change', renderMapMarkers);
    document.getElementById('btn-reset-filters').addEventListener('click', () => {
        document.getElementById('filter-band').value = 'all';
        document.getElementById('filter-police').value = 'all';
        document.getElementById('filter-time').value = 'all';
        renderMapMarkers();
    });

    // Populate police station filter
    const stations = [...new Set(DATA.mapData.map(r => r.top_police_station).filter(Boolean))].sort();
    const sel = document.getElementById('filter-police');
    stations.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = s;
        sel.appendChild(opt);
    });
}

function renderMapMarkers() {
    // Clear existing
    mapMarkers.forEach(m => mapInstance.removeLayer(m));
    mapMarkers = [];

    const bandFilter = document.getElementById('filter-band').value;
    const policeFilter = document.getElementById('filter-police').value;
    const timeFilter = document.getElementById('filter-time').value;

    let filtered = DATA.mapData;

    if (bandFilter !== 'all') {
        filtered = filtered.filter(r => r.hotspot_band === bandFilter);
    }
    if (policeFilter !== 'all') {
        filtered = filtered.filter(r => r.top_police_station === policeFilter);
    }
    if (timeFilter !== 'all') {
        filtered = filtered.filter(r => r.dominant_time_bucket === timeFilter);
    }

    filtered.forEach(r => {
        const lat = Number(r.latitude);
        const lon = Number(r.longitude);
        if (isNaN(lat) || isNaN(lon)) return;

        const color = riskColor(r.hotspot_band);
        const violations = Number(r.total_violations) || 0;
        const radius = Math.max(5, Math.min(25, Math.sqrt(violations) * 0.3));

        const marker = L.circleMarker([lat, lon], {
            radius: radius,
            fillColor: color,
            color: '#111827',
            fillOpacity: 0.7,
            weight: 1.8,
            opacity: 0.95
        });

        const popupContent = `
            <div class="popup-title">${r.zone_name || r.zone_id}</div>
            <div class="popup-row"><span class="popup-label">Police Station</span><span class="popup-value">${r.top_police_station || '—'}</span></div>
            <div class="popup-row"><span class="popup-label">Hotspot Score</span><span class="popup-value">${fmt(r.hotspot_score, 1)}</span></div>
            <div class="popup-row"><span class="popup-label">Band</span><span class="popup-value" style="color:${color}">${r.hotspot_band}</span></div>
            <div class="popup-row"><span class="popup-label">Total Violations</span><span class="popup-value">${fmt(r.total_violations)}</span></div>
            <div class="popup-row"><span class="popup-label">Time Bucket</span><span class="popup-value">${r.dominant_time_bucket || '—'}</span></div>
            ${r.predicted_next_day_violations != null ? `
            <hr style="border:none;border-top:1px solid rgba(148,163,184,0.15);margin:8px 0">
            <div class="popup-row"><span class="popup-label">Predicted (Tomorrow)</span><span class="popup-value">${fmt(r.predicted_next_day_violations, 1)}</span></div>
            <div class="popup-row"><span class="popup-label">Risk Score</span><span class="popup-value">${fmt(r.predicted_risk_score, 1)}</span></div>
            <div class="popup-action">🚔 ${r.recommended_action || '—'}</div>
            ` : ''}
        `;

        marker.bindPopup(popupContent, { maxWidth: 320 });
        marker.addTo(mapInstance);
        mapMarkers.push(marker);
    });
}

// ── Phase 5.4: Rankings ──
function renderRankings() {
    // Top 10 zones by hotspot score
    const top10zones = DATA.topHotspots;
    const zoneBody = document.querySelector('#table-zone-rankings tbody');
    zoneBody.innerHTML = top10zones.map((r, i) => `
        <tr>
            <td class="num">${i + 1}</td>
            <td>${r.zone_name}</td>
            <td class="num">${fmt(r.total_violations)}</td>
            <td class="num">${fmt(r.hotspot_score, 2)}</td>
            <td><span class="band-badge ${bandClass(r.hotspot_band)}">${r.hotspot_band}</span></td>
            <td>${r.top_police_station}</td>
            <td class="num">${(r.peak_share * 100).toFixed(1)}%</td>
        </tr>
    `).join('');

    // Top 10 deployment
    const top10deploy = DATA.forecast.slice(0, 10);
    const depBody = document.querySelector('#table-deploy-rankings tbody');
    depBody.innerHTML = top10deploy.map((r, i) => `
        <tr>
            <td class="num">${i + 1}</td>
            <td>${r.zone_name}</td>
            <td class="num">${fmt(r.predicted_next_day_violations, 1)}</td>
            <td class="num">${fmt(r.predicted_risk_score, 1)}</td>
            <td><span class="band-badge ${bandClass(r.predicted_risk_band)}">${r.predicted_risk_band}</span></td>
            <td class="num">${r.manpower_estimate}</td>
            <td>${r.time_window_to_watch}</td>
        </tr>
    `).join('');

    // Location rankings
    renderLocationRankings('all');
    document.getElementById('filter-entity-type').addEventListener('change', (e) => {
        renderLocationRankings(e.target.value);
    });
}

function renderLocationRankings(entityType) {
    let data = DATA.rankingByEntity;
    if (entityType !== 'all') {
        data = data.filter(r => r.entity_type === entityType);
    }
    data = data.slice(0, 50); // Show top 50

    const body = document.querySelector('#table-location-rankings tbody');
    body.innerHTML = data.map(r => `
        <tr>
            <td class="num">${r.global_rank}</td>
            <td><span class="band-badge ${r.entity_type === 'Police Station' ? 'band-very-high' : r.entity_type === 'Junction' ? 'band-high' : 'band-medium'}">${r.entity_type}</span></td>
            <td>${r.entity_name}</td>
            <td class="num">${fmt(r.hotspot_score, 2)}</td>
            <td class="num">${fmt(r.total_violations)}</td>
            <td class="num">${fmt(r.peak_hour_violations)}</td>
        </tr>
    `).join('');
}

// ── Phase 5.5: Forecast & Recommendations ──
function renderForecast() {
    // Top 10 deployment plan
    const top10 = DATA.forecast.slice(0, 10);
    const body = document.getElementById('deployment-plan-body');
    body.innerHTML = top10.map((r, i) => {
        const needsTow = r.recommended_action && r.recommended_action.toLowerCase().includes('towing');
        return `
        <tr>
            <td class="num">${i + 1}</td>
            <td>${r.zone_name}</td>
            <td class="num">${fmt(r.predicted_next_day_violations, 1)}</td>
            <td class="num">${fmt(r.predicted_risk_score, 1)}</td>
            <td><span class="band-badge ${bandClass(r.predicted_risk_band)}">${r.predicted_risk_band}</span></td>
            <td style="max-width:220px;white-space:normal;font-size:12px">${r.recommended_action}</td>
            <td class="num">${r.manpower_estimate}</td>
            <td>${needsTow ? '✅ Yes' : '❌ No'}</td>
            <td style="font-size:12px">${r.time_window_to_watch}</td>
        </tr>
    `}).join('');

    // Full forecast (filterable)
    renderFullForecast('all');
    document.getElementById('filter-risk-band').addEventListener('change', (e) => {
        renderFullForecast(e.target.value);
    });
}

function renderFullForecast(band) {
    let data = DATA.forecast;
    if (band !== 'all') {
        data = data.filter(r => r.predicted_risk_band === band);
    }

    const body = document.querySelector('#table-full-forecast tbody');
    body.innerHTML = data.map(r => `
        <tr>
            <td class="num">${r.zone_id}</td>
            <td>${r.zone_name}</td>
            <td class="num">${fmt(r.predicted_next_day_violations, 1)}</td>
            <td class="num">${fmt(r.predicted_risk_score, 1)}</td>
            <td><span class="band-badge ${bandClass(r.predicted_risk_band)}">${r.predicted_risk_band}</span></td>
            <td style="max-width:200px;white-space:normal;font-size:11px">${r.recommended_action}</td>
            <td class="num">${r.manpower_estimate}</td>
            <td style="font-size:11px">${r.time_window_to_watch}</td>
        </tr>
    `).join('');
}

// Feature Explanations Lookup Map
const FEATURE_EXPLAIN_MAP = {
    'rolling_7_sum': 'Sum of traffic violations in the zone in the last 7 days. Reflects recent traffic behavior.',
    'lag_1': 'Number of violations from yesterday in this zone. Autoregressive momentum.',
    'lag_7': 'Number of violations from exactly 7 days ago. Weekly seasonal indicator.',
    'lag_14': 'Number of violations from exactly 14 days ago. Longer term seasonal indicator.',
    'rolling_14_sum': 'Sum of traffic violations in the last 14 days.',
    'hour': 'Hour of day of the traffic violation. Capture temporal risk shifts.',
    'dayofweek': 'Day of the week (0=Monday, 6=Sunday). Capture weekend vs weekday patterns.',
    'dominant_time_bucket': 'Temporal bucket (morning_peak, evening_peak, midday, night).',
    'peak_share': 'Percentage share of violations occurring in peak hours.',
    'latitude': 'Latitude coordinate of the zone center.',
    'longitude': 'Longitude coordinate of the zone center.',
    'total_violations': 'Total violations detected historically in this zone.',
    'hotspot_score': 'Density clustering priority score.',
    'num_junctions': 'Number of distinct traffic junctions within the zone.',
    'num_locations': 'Number of distinct street addresses/locations.',
    'val_p10': 'Best validation Daily Precision@10.',
    'zone_id': 'Unique identification ID of the hotspot zone.'
};

function renderExplainability() {
    const top15 = DATA.featureSorted.slice(0, 15);

    // Horizontal bar chart — average importance
    new Chart(document.getElementById('feature-importance-chart'), {
        type: 'bar',
        data: {
            labels: top15.map(r => r.feature),
            datasets: [{
                label: 'Average Importance',
                data: top15.map(r => r.average),
                backgroundColor: top15.map((_, i) => {
                    const hue = 145 - (i * 7);
                    return `hsla(${hue}, 90%, 55%, 0.75)`;
                }),
                borderColor: top15.map((_, i) => {
                    const hue = 145 - (i * 7);
                    return `hsla(${hue}, 90%, 55%, 1)`;
                }),
                borderWidth: 1,
                borderRadius: 5
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#111413',
                    titleColor: '#f8fafc',
                    bodyColor: '#cbd5e1',
                    borderColor: 'rgba(255,255,255,0.08)',
                    borderWidth: 1,
                    cornerRadius: 8,
                    padding: 12,
                    callbacks: {
                        label: (ctx) => ` Importance: ${(ctx.raw * 100).toFixed(2)}%`,
                        afterLabel: (ctx) => {
                            const feat = ctx.label;
                            const explanation = FEATURE_EXPLAIN_MAP[feat] || 'Model feature weight.';
                            return `\nDescription: ${explanation}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255,255,255,0.04)' },
                    ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 11 } }
                },
                y: {
                    grid: { display: false },
                    ticks: { color: '#cbd5e1', font: { family: 'Outfit', size: 12, weight: 600 } }
                }
            }
        }
    });

    // SHAP Zoom Lightbox modal
    const shapZoomBtn = document.getElementById('btn-zoom-shap');
    const shapLightbox = document.getElementById('shap-lightbox');
    const shapCloseLightbox = document.getElementById('close-shap-lightbox');

    if (shapZoomBtn && shapLightbox) {
        shapZoomBtn.addEventListener('click', () => {
            shapLightbox.classList.add('active');
        });
    }

    if (shapCloseLightbox && shapLightbox) {
        shapCloseLightbox.addEventListener('click', () => {
            shapLightbox.classList.remove('active');
        });
        shapLightbox.addEventListener('click', (e) => {
            if (e.target === shapLightbox) {
                shapLightbox.classList.remove('active');
            }
        });
    }

    // SHAP Hotspots hover descriptions
    const hotspots = document.querySelectorAll('.shap-hotspot');
    const explainPanel = document.getElementById('shap-explanation-panel');
    const defaultSHAPText = `✨ <strong>Interactive Feature Inspector:</strong> Hover over the flashing indicator nodes on the chart to read how individual features impact the model's decisions.`;

    hotspots.forEach(h => {
        h.addEventListener('mouseenter', () => {
            const feat = h.dataset.feature;
            const explain = h.dataset.explain;
            if (explainPanel) {
                explainPanel.innerHTML = `<p class="shap-info-text" style="color:#ffe699">🔍 <strong>Feature [${feat}]:</strong> ${explain}</p>`;
                explainPanel.style.background = 'rgba(0, 255, 135, 0.12)';
                explainPanel.style.borderColor = 'rgba(0, 255, 135, 0.3)';
            }
        });

        h.addEventListener('mouseleave', () => {
            if (explainPanel) {
                explainPanel.innerHTML = defaultSHAPText;
                explainPanel.style.background = 'rgba(0, 255, 135, 0.05)';
                explainPanel.style.borderColor = 'rgba(0, 255, 135, 0.15)';
            }
        });
    });

    // Per-model grouped bar chart (top 10)
    const top10 = DATA.featureSorted.slice(0, 10);
    new Chart(document.getElementById('feature-model-chart'), {
        type: 'bar',
        data: {
            labels: top10.map(r => r.feature),
            datasets: [
                {
                    label: 'LightGBM',
                    data: top10.map(r => r.lightgbm),
                    backgroundColor: 'rgba(0, 255, 135, 0.6)',
                    borderColor: 'rgba(0, 255, 135, 1)',
                    borderWidth: 1,
                    borderRadius: 3
                },
                {
                    label: 'XGBoost',
                    data: top10.map(r => r.xgboost),
                    backgroundColor: 'rgba(255, 170, 0, 0.6)',
                    borderColor: 'rgba(255, 170, 0, 1)',
                    borderWidth: 1,
                    borderRadius: 3
                },
                {
                    label: 'Random Forest',
                    data: top10.map(r => r.random_forest),
                    backgroundColor: 'rgba(52, 211, 153, 0.6)',
                    borderColor: 'rgba(52, 211, 153, 1)',
                    borderWidth: 1,
                    borderRadius: 3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        color: '#94a3b8',
                        font: { family: 'Inter', size: 12 },
                        usePointStyle: true,
                        pointStyleWidth: 12,
                        padding: 20
                    }
                },
                tooltip: {
                    backgroundColor: '#1a1f35',
                    titleColor: '#f1f5f9',
                    bodyColor: '#94a3b8',
                    borderColor: 'rgba(148,163,184,0.15)',
                    borderWidth: 1,
                    cornerRadius: 8
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: '#64748b', font: { family: 'Inter', size: 10 }, maxRotation: 45 }
                },
                y: {
                    grid: { color: 'rgba(148,163,184,0.06)' },
                    ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 11 } }
                }
            }
        }
    });
}

// ── Phase 5.7: Error Analysis ──
// Expose error table reset globally
window.resetErrorTables = () => {
    const alertPanel = document.getElementById('table-filter-alert');
    if (alertPanel) alertPanel.remove();

    const errors = DATA.errorSorted;
    const best10 = errors.slice(0, 10);
    const worst10 = [...errors].sort((a, b) => (b.absolute_error || 0) - (a.absolute_error || 0)).slice(0, 10);

    document.querySelector('#table-best-predictions tbody').innerHTML = best10.map(r => `
        <tr>
            <td class="num">${r.zone_id}</td>
            <td class="num">${fmt(r.actual, 2)}</td>
            <td class="num">${fmt(r.predicted, 2)}</td>
            <td class="num">${fmt(r.absolute_error, 3)}</td>
        </tr>
    `).join('');

    document.querySelector('#table-worst-predictions tbody').innerHTML = worst10.map(r => `
        <tr>
            <td class="num">${r.zone_id}</td>
            <td class="num">${fmt(r.actual, 2)}</td>
            <td class="num">${fmt(r.predicted, 2)}</td>
            <td class="num">${fmt(r.absolute_error, 2)}</td>
        </tr>
    `).join('');
};

// ── Phase 5.7: Error Analysis ──
function renderErrorAnalysis() {
    const errors = DATA.errorSorted;

    // Scatter: Actual vs Predicted
    const scatterData = errors.map(r => ({
        x: Number(r.actual),
        y: Number(r.predicted)
    }));

    const maxVal = Math.max(
        ...errors.map(r => Math.max(Number(r.actual) || 0, Number(r.predicted) || 0))
    );

    new Chart(document.getElementById('scatter-chart'), {
        type: 'scatter',
        data: {
            datasets: [
                {
                    label: 'Zones',
                    data: scatterData,
                    backgroundColor: 'rgba(0, 255, 135, 0.6)',
                    borderColor: 'rgba(0, 255, 135, 0.9)',
                    borderWidth: 1,
                    pointRadius: 4.5,
                    pointHoverRadius: 8
                },
                {
                    label: 'Perfect Prediction',
                    data: [{ x: 0, y: 0 }, { x: maxVal, y: maxVal }],
                    type: 'line',
                    borderColor: 'rgba(239, 68, 68, 0.6)',
                    borderDash: [6, 4],
                    borderWidth: 2,
                    pointRadius: 0,
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            onClick: (event, elements) => {
                if (elements.length > 0) {
                    const index = elements[0].index;
                    const zoneErrorData = errors[index];
                    if (zoneErrorData) {
                        const deployRec = DATA.deployRecs.find(d => d.zone_id === zoneErrorData.zone_id) || {};
                        const hotspotZone = DATA.hotspotZones.find(hz => hz.zone_id === zoneErrorData.zone_id) || {};

                        const zoneName = zoneErrorData.zone_name || deployRec.zone_name || hotspotZone.zone_name || '—';
                        const stationName = zoneErrorData.top_police_station || deployRec.top_police_station || hotspotZone.top_police_station || '—';

                        document.getElementById('inspect-name').textContent = zoneName;
                        document.getElementById('inspect-id').textContent = zoneErrorData.zone_id || '—';
                        document.getElementById('inspect-actual').textContent = fmt(zoneErrorData.actual, 1);
                        document.getElementById('inspect-predicted').textContent = fmt(zoneErrorData.predicted, 1);
                        document.getElementById('inspect-error').textContent = fmt(zoneErrorData.absolute_error, 2);
                        document.getElementById('inspect-station').textContent = stationName;
                        document.getElementById('inspect-manpower').textContent = deployRec.manpower_estimate || '0 officers';
                        document.getElementById('inspect-window').textContent = deployRec.time_window_to_watch || '—';

                        document.getElementById('inspector-placeholder').classList.add('hidden');
                        document.getElementById('inspector-content').classList.remove('hidden');
                    }
                }
            },
            plugins: {
                legend: {
                    labels: {
                        color: '#cbd5e1',
                        font: { family: 'Outfit', size: 12 },
                        usePointStyle: true
                    }
                },
                tooltip: {
                    backgroundColor: '#111413',
                    titleColor: '#f8fafc',
                    bodyColor: '#cbd5e1',
                    borderColor: 'rgba(255,255,255,0.08)',
                    borderWidth: 1,
                    cornerRadius: 8,
                    callbacks: {
                        label: (ctx) => ` Actual: ${fmt(ctx.raw.x, 2)}, Predicted: ${fmt(ctx.raw.y, 2)}`
                    }
                }
            },
            scales: {
                x: {
                    title: { display: true, text: 'Actual Violations', color: '#cbd5e1', font: { size: 12 } },
                    grid: { color: 'rgba(255,255,255,0.04)' },
                    ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 11 } }
                },
                y: {
                    title: { display: true, text: 'Predicted Violations', color: '#cbd5e1', font: { size: 12 } },
                    grid: { color: 'rgba(255,255,255,0.04)' },
                    ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 11 } }
                }
            }
        }
    });

    // Error distribution histogram
    const absErrors = errors.map(r => Number(r.absolute_error) || 0);
    const bins = [0, 0.5, 1, 2, 5, 10, 20, 50, 100];
    const binLabels = [];
    const binCounts = [];
    for (let i = 0; i < bins.length; i++) {
        const lo = bins[i];
        const hi = i < bins.length - 1 ? bins[i + 1] : Infinity;
        const label = hi === Infinity ? `>${lo}` : `${lo}–${hi}`;
        binLabels.push(label);
        binCounts.push(absErrors.filter(e => e >= lo && e < hi).length);
    }

    new Chart(document.getElementById('error-dist-chart'), {
        type: 'bar',
        data: {
            labels: binLabels,
            datasets: [{
                label: 'Zone Count',
                data: binCounts,
                backgroundColor: binLabels.map((_, i) => {
                    const t = i / binLabels.length;
                    return `hsla(${145 - t * 145}, 90%, 55%, 0.7)`;
                }),
                borderColor: binLabels.map((_, i) => {
                    const t = i / binLabels.length;
                    return `hsla(${145 - t * 145}, 90%, 55%, 1)`;
                }),
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            onClick: (event, elements) => {
                if (elements.length > 0) {
                    const index = elements[0].index;
                    const lo = bins[index];
                    const hi = index < bins.length - 1 ? bins[index + 1] : Infinity;

                    const filteredBest = DATA.errorSorted.filter(r => r.absolute_error >= lo && r.absolute_error < hi).slice(0, 10);
                    const filteredWorst = [...DATA.errorSorted]
                        .sort((a, b) => (b.absolute_error || 0) - (a.absolute_error || 0))
                        .filter(r => r.absolute_error >= lo && r.absolute_error < hi)
                        .slice(0, 10);

                    const bestBody = document.querySelector('#table-best-predictions tbody');
                    if (filteredBest.length > 0) {
                        bestBody.innerHTML = filteredBest.map(r => `
                            <tr style="background: rgba(0,255,135,0.06)">
                                <td class="num">${r.zone_id}</td>
                                <td class="num">${fmt(r.actual, 2)}</td>
                                <td class="num">${fmt(r.predicted, 2)}</td>
                                <td class="num">${fmt(r.absolute_error, 3)}</td>
                            </tr>
                        `).join('');
                    } else {
                        bestBody.innerHTML = `<tr><td colspan="4" style="text-align:center">No zones in this range</td></tr>`;
                    }

                    const worstBody = document.querySelector('#table-worst-predictions tbody');
                    if (filteredWorst.length > 0) {
                        worstBody.innerHTML = filteredWorst.map(r => `
                            <tr style="background: rgba(244,63,94,0.06)">
                                <td class="num">${r.zone_id}</td>
                                <td class="num">${fmt(r.actual, 2)}</td>
                                <td class="num">${fmt(r.predicted, 2)}</td>
                                <td class="num">${fmt(r.absolute_error, 2)}</td>
                            </tr>
                        `).join('');
                    } else {
                        worstBody.innerHTML = `<tr><td colspan="4" style="text-align:center">No zones in this range</td></tr>`;
                    }

                    // Show reset indicator
                    const alertPanel = document.getElementById('table-filter-alert');
                    if (alertPanel) alertPanel.remove();

                    let rangeLabel = hi === Infinity ? `>${lo}` : `${lo}–${hi}`;
                    document.getElementById('error-stats-body').insertAdjacentHTML('afterbegin', `
                        <div class="filter-alert-panel" id="table-filter-alert" style="background:rgba(0, 255, 135, 0.08); border:1px solid rgba(0, 255, 135, 0.25); padding:12px 18px; border-radius: var(--radius-sm); margin-bottom:14px; display:flex; justify-content:space-between; align-items:center; width:100%; grid-column: 1 / -1; font-size:13px; color:#cbd5e1;">
                            <span>Active Filter: Absolute Error between <strong>${rangeLabel}</strong></span>
                            <button class="btn-action-sm" style="padding:4px 8px;" onclick="resetErrorTables()">Reset Tables</button>
                        </div>
                    `);
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#111413',
                    titleColor: '#f8fafc',
                    bodyColor: '#cbd5e1',
                    borderColor: 'rgba(255,255,255,0.08)',
                    borderWidth: 1,
                    cornerRadius: 8
                }
            },
            scales: {
                x: {
                    title: { display: true, text: 'Absolute Error Range', color: '#cbd5e1', font: { size: 12 } },
                    grid: { display: false },
                    ticks: { color: '#64748b', font: { family: 'Outfit', size: 11 } }
                },
                y: {
                    title: { display: true, text: 'Number of Zones', color: '#cbd5e1', font: { size: 12 } },
                    grid: { color: 'rgba(255,255,255,0.04)' },
                    ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 11 } }
                }
            }
        }
    });

    // Best / worst tables
    const best10 = errors.slice(0, 10);
    const worst10 = [...errors].sort((a, b) => (b.absolute_error || 0) - (a.absolute_error || 0)).slice(0, 10);

    document.querySelector('#table-best-predictions tbody').innerHTML = best10.map(r => `
        <tr>
            <td class="num">${r.zone_id}</td>
            <td class="num">${fmt(r.actual, 2)}</td>
            <td class="num">${fmt(r.predicted, 2)}</td>
            <td class="num">${fmt(r.absolute_error, 3)}</td>
        </tr>
    `).join('');

    document.querySelector('#table-worst-predictions tbody').innerHTML = worst10.map(r => `
        <tr>
            <td class="num">${r.zone_id}</td>
            <td class="num">${fmt(r.actual, 2)}</td>
            <td class="num">${fmt(r.predicted, 2)}</td>
            <td class="num">${fmt(r.absolute_error, 2)}</td>
        </tr>
    `).join('');

    // Error statistics
    const mean = absErrors.reduce((a, b) => a + b, 0) / absErrors.length;
    const median = [...absErrors].sort((a, b) => a - b)[Math.floor(absErrors.length / 2)];
    const max = Math.max(...absErrors);
    const min = Math.min(...absErrors);
    const under1 = absErrors.filter(e => e < 1).length;
    const under5 = absErrors.filter(e => e < 5).length;

    document.getElementById('error-stats-body').innerHTML = `
        <div class="error-stat-grid">
            <div class="error-stat"><div class="stat-val">${fmt(mean, 2)}</div><div class="stat-label">Mean Abs Error</div></div>
            <div class="error-stat"><div class="stat-val">${fmt(median, 2)}</div><div class="stat-label">Median Abs Error</div></div>
            <div class="error-stat"><div class="stat-val">${fmt(min, 3)}</div><div class="stat-label">Min Error</div></div>
            <div class="error-stat"><div class="stat-val">${fmt(max, 2)}</div><div class="stat-label">Max Error</div></div>
            <div class="error-stat"><div class="stat-val">${under1}/${absErrors.length}</div><div class="stat-label">Zones < 1 Error</div></div>
            <div class="error-stat"><div class="stat-val">${((under5 / absErrors.length) * 100).toFixed(1)}%</div><div class="stat-label">Zones < 5 Error</div></div>
        </div>
    `;
}

// ── Phase 5.8: Model Comparison ──
function renderComparison() {
    const benchmarkData = {
        validation: [
            { model: 'Persistence Baseline', mae: 2.432, rmse: 13.113, p10: 0.56 },
            { model: '7-Day Rolling Mean', mae: 2.052, rmse: 10.030, p10: 0.667 },
            { model: 'Tuned XGBoost', mae: 2.433, rmse: 9.460, p10: 0.673 },
            { model: 'Tuned HistGBT', mae: 2.307, rmse: 9.779, p10: 0.680 },
            { model: 'Tuned LightGBM', mae: 2.201, rmse: 10.008, p10: 0.680 },
            { model: 'Ensemble (Final)', mae: 2.284, rmse: 9.489, p10: 0.687 },
        ],
        test: [
            { model: 'Persistence Baseline', mae: 2.676, rmse: 14.113, p10: 0.519 },
            { model: '7-Day Rolling Mean', mae: 2.286, rmse: 11.679, p10: 0.600 },
            { model: 'Tuned XGBoost', mae: 2.712, rmse: 12.222, p10: 0.606 },
            { model: 'Tuned HistGBT', mae: 2.471, rmse: 10.867, p10: 0.581 },
            { model: 'Tuned LightGBM', mae: 2.373, rmse: 10.806, p10: 0.594 },
            { model: 'Ensemble (Final)', mae: 2.492, rmse: 11.085, p10: 0.594 },
        ]
    };

    const modelNames = benchmarkData.validation.map(m => m.model);
    const chartColors = [
        'rgba(100, 116, 139, 0.7)',
        'rgba(100, 116, 139, 0.7)',
        'rgba(255, 170, 0, 0.7)',
        'rgba(52, 211, 153, 0.7)',
        'rgba(0, 230, 118, 0.7)',
        'rgba(0, 255, 135, 0.8)',
    ];

    // Validation chart: P@10
    new Chart(document.getElementById('val-comparison-chart'), {
        type: 'bar',
        data: {
            labels: modelNames,
            datasets: [{
                label: 'Daily Precision@10',
                data: benchmarkData.validation.map(m => m.p10 * 100),
                backgroundColor: chartColors,
                borderColor: chartColors.map(c => c.replace('0.7', '1').replace('0.8', '1')),
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#111413',
                    titleColor: '#f1f5f9',
                    bodyColor: '#94a3b8',
                    borderColor: 'rgba(148,163,184,0.15)',
                    borderWidth: 1,
                    cornerRadius: 8,
                    callbacks: { label: (ctx) => ` P@10: ${ctx.raw.toFixed(1)}%` }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: '#64748b', font: { size: 10 }, maxRotation: 30 }
                },
                y: {
                    title: { display: true, text: 'Daily P@10 (%)', color: '#64748b', font: { size: 12 } },
                    grid: { color: 'rgba(148,163,184,0.06)' },
                    ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 11 } },
                    min: 40,
                    max: 75
                }
            }
        }
    });

    // Test chart: P@10
    new Chart(document.getElementById('test-comparison-chart'), {
        type: 'bar',
        data: {
            labels: modelNames,
            datasets: [{
                label: 'Daily Precision@10',
                data: benchmarkData.test.map(m => m.p10 * 100),
                backgroundColor: chartColors,
                borderColor: chartColors.map(c => c.replace('0.7', '1').replace('0.8', '1')),
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#111413',
                    titleColor: '#f1f5f9',
                    bodyColor: '#94a3b8',
                    borderColor: 'rgba(148,163,184,0.15)',
                    borderWidth: 1,
                    cornerRadius: 8,
                    callbacks: { label: (ctx) => ` P@10: ${ctx.raw.toFixed(1)}%` }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: '#64748b', font: { size: 10 }, maxRotation: 30 }
                },
                y: {
                    title: { display: true, text: 'Daily P@10 (%)', color: '#64748b', font: { size: 12 } },
                    grid: { color: 'rgba(148,163,184,0.06)' },
                    ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 11 } },
                    min: 40,
                    max: 70
                }
            }
        }
    });

    // Comparison table
    const tableBody = document.getElementById('comparison-table-body');
    let rows = '';
    benchmarkData.validation.forEach((m, i) => {
        const isEnsemble = m.model.includes('Ensemble');
        rows += `<tr style="${isEnsemble ? 'background:rgba(16,185,129,0.06)' : ''}">
            <td>Validation</td>
            <td style="${isEnsemble ? 'font-weight:700;color:#10b981' : ''}">${m.model}</td>
            <td class="num">${m.mae.toFixed(3)}</td>
            <td class="num">${m.rmse.toFixed(3)}</td>
            <td class="num" style="${isEnsemble ? 'font-weight:700;color:#10b981' : ''}">${(m.p10 * 100).toFixed(1)}%</td>
        </tr>`;
    });
    rows += '<tr><td colspan="5" style="height:8px;border:none"></td></tr>';
    benchmarkData.test.forEach((m, i) => {
        const isEnsemble = m.model.includes('Ensemble');
        rows += `<tr style="${isEnsemble ? 'background:rgba(16,185,129,0.06)' : ''}">
            <td>Test</td>
            <td style="${isEnsemble ? 'font-weight:700;color:#10b981' : ''}">${m.model}</td>
            <td class="num">${m.mae.toFixed(3)}</td>
            <td class="num">${m.rmse.toFixed(3)}</td>
            <td class="num" style="${isEnsemble ? 'font-weight:700;color:#10b981' : ''}">${(m.p10 * 100).toFixed(1)}%</td>
        </tr>`;
    });
    tableBody.innerHTML = rows;
}

// ── Phase 5.9: Downloads ──
function renderDownloads() {
    const files = [
        {
            icon: '📍',
            title: 'Hotspot Zones',
            desc: '539 detected hotspot zones with scores, severity bands, temporal patterns, and 38 aggregated features.',
            file: 'hotspot_zones.csv'
        },
        {
            icon: '🚔',
            title: 'Deployment Recommendations',
            desc: 'Next-day deployment plan for all 539 zones including predicted violations, risk scores, actions, and manpower.',
            file: 'deployment_recommendations.csv'
        },
        {
            icon: '🧠',
            title: 'Feature Importance',
            desc: 'Normalized feature importances from LightGBM, XGBoost, and Random Forest with cross-model average.',
            file: 'feature_importance.csv'
        },
        {
            icon: '📊',
            title: 'Prediction Error Analysis',
            desc: 'Per-zone actual vs predicted violations on the test set with signed and absolute error metrics.',
            file: 'prediction_error_analysis.csv'
        },
        {
            icon: '🏆',
            title: 'Location Rankings',
            desc: 'Combined priority leaderboard of police stations, junctions, and streets ranked by hotspot score.',
            file: 'location_ranking.csv'
        },
        {
            icon: '🗺️',
            title: 'Hotspot Map Data',
            desc: 'Optimized coordinates and attributes for each zone for map rendering and GIS integration.',
            file: 'hotspot_map_data.csv'
        },
        {
            icon: '📋',
            title: 'Summary Report',
            desc: 'High-level analytics summary — total violations, zone counts, severity breakdowns, and top hotspot.',
            file: 'hotspot_summary_report.csv'
        },
        {
            icon: '📈',
            title: 'SHAP Summary Plot',
            desc: 'SHAP TreeExplainer visualization showing feature impact direction and magnitude (LightGBM).',
            file: 'shap_summary.png'
        }
    ];

    const grid = document.getElementById('downloads-grid');
    grid.innerHTML = files.map(f => `
        <div class="download-card">
            <div class="download-icon">${f.icon}</div>
            <div class="download-title">${f.title}</div>
            <div class="download-desc">${f.desc}</div>
            <a class="download-btn" href="../dataset/${f.file}" download="${f.file}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                Download ${f.file}
            </a>
        </div>
    `).join('');
}

// ── Table Sorting ──
function enableTableSort() {
    document.querySelectorAll('.data-table th[data-sort]').forEach(th => {
        th.addEventListener('click', () => {
            const table = th.closest('table');
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));
            const colIndex = Array.from(th.parentNode.children).indexOf(th);
            const key = th.dataset.sort;
            const isAsc = th.classList.contains('sort-asc');

            // Reset all
            table.querySelectorAll('th').forEach(t => t.classList.remove('sort-asc', 'sort-desc'));
            th.classList.add(isAsc ? 'sort-desc' : 'sort-asc');

            rows.sort((a, b) => {
                let va = a.children[colIndex]?.textContent?.trim() || '';
                let vb = b.children[colIndex]?.textContent?.trim() || '';
                // Try numeric
                const na = parseFloat(va.replace(/,/g, ''));
                const nb = parseFloat(vb.replace(/,/g, ''));
                if (!isNaN(na) && !isNaN(nb)) {
                    return isAsc ? nb - na : na - nb;
                }
                return isAsc ? vb.localeCompare(va) : va.localeCompare(vb);
            });

            rows.forEach(r => tbody.appendChild(r));
        });
    });
}

// ── Three.js 3D Dynamic Particle Background ──
function init3DBackground() {
    const canvas = document.getElementById('bg-canvas-3d');
    if (!canvas) return;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 1, 1000);
    camera.position.z = 400;

    const renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // Particle geometry
    const particleCount = 1800;
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    const colors = new Float32Array(particleCount * 3);
    const originalY = new Float32Array(particleCount);

    const color1 = new THREE.Color('#00ff87'); // Neon Emerald
    const color2 = new THREE.Color('#ffaa00'); // Neon Gold/Amber
    const color3 = new THREE.Color('#ff3860'); // Neon Crimson/Red

    for (let i = 0; i < particleCount; i++) {
        const x = (Math.random() - 0.5) * 1400;
        const z = (Math.random() - 0.5) * 1000;
        const y = Math.sin(x * 0.004) * Math.cos(z * 0.004) * 70 + (Math.random() - 0.5) * 20;

        positions[i * 3] = x;
        positions[i * 3 + 1] = y;
        positions[i * 3 + 2] = z;
        originalY[i] = y;

        // Traffic density visualization color gradients
        let colorMix;
        const t = Math.random();
        if (t < 0.4) {
            colorMix = color1.clone().lerp(color2, Math.random());
        } else {
            colorMix = color2.clone().lerp(color3, Math.random());
        }

        colors[i * 3] = colorMix.r;
        colors[i * 3 + 1] = colorMix.g;
        colors[i * 3 + 2] = colorMix.b;
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    // Point shape texture creation
    const pCanvas = document.createElement('canvas');
    pCanvas.width = 16;
    pCanvas.height = 16;
    const ctx = pCanvas.getContext('2d');
    const grad = ctx.createRadialGradient(8, 8, 0, 8, 8, 8);
    grad.addColorStop(0, 'rgba(255,255,255,1)');
    grad.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 16, 16);
    const texture = new THREE.CanvasTexture(pCanvas);

    const material = new THREE.PointsMaterial({
        size: 4.0,
        vertexColors: true,
        transparent: true,
        opacity: 0.6,
        map: texture,
        depthWrite: false,
        blending: THREE.AdditiveBlending
    });

    const particleSystem = new THREE.Points(geometry, material);
    scene.add(particleSystem);

    let mouseX = 0, mouseY = 0;
    let targetMouseX = 0, targetMouseY = 0;

    window.addEventListener('mousemove', (e) => {
        targetMouseX = (e.clientX - window.innerWidth / 2) * 0.12;
        targetMouseY = (e.clientY - window.innerHeight / 2) * 0.12;
    });

    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
    });

    let clock = new THREE.Clock();

    function animate() {
        requestAnimationFrame(animate);

        const elapsedTime = clock.getElapsedTime();
        const positionsArr = particleSystem.geometry.attributes.position.array;

        // Wave animation flow
        for (let i = 0; i < particleCount; i++) {
            const x = positionsArr[i * 3];
            const z = positionsArr[i * 3 + 2];
            positionsArr[i * 3 + 1] = originalY[i] + Math.sin(elapsedTime * 0.8 + x * 0.006) * Math.cos(elapsedTime * 0.6 + z * 0.006) * 20;
        }
        particleSystem.geometry.attributes.position.needsUpdate = true;

        // Smooth camera movement follow cursor
        mouseX += (targetMouseX - mouseX) * 0.03;
        mouseY += (targetMouseY - mouseY) * 0.03;

        particleSystem.rotation.y = elapsedTime * 0.015 + mouseX * 0.0006;
        particleSystem.rotation.x = mouseY * 0.0006;

        renderer.render(scene, camera);
    }

    animate();
}

// ── Card 3D Tilt Effect ──
function initCardTilts() {
    if (window.innerWidth < 860) return;

    const cards = document.querySelectorAll('.kpi-card, .download-card');
    cards.forEach(card => {
        card.addEventListener('mousemove', (e) => {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const w = rect.width;
            const h = rect.height;

            const rX = ((y / h) - 0.5) * -10;
            const rY = ((x / w) - 0.5) * 10;

            card.style.transform = `perspective(800px) rotateX(${rX}deg) rotateY(${rY}deg) translateY(-2px)`;
        });

        card.style.transition = 'transform 0.1s ease-out, box-shadow 0.3s ease, border-color 0.3s ease';

        card.addEventListener('mouseleave', () => {
            card.style.transform = '';
        });
    });
}

// ── Boot ──
async function init() {
    init3DBackground();
    initNavigation();
    await loadAllData();

    renderExecutiveSummary();
    renderRankings();
    renderForecast();
    renderExplainability();
    renderErrorAnalysis();
    renderComparison();
    renderDownloads();
    enableTableSort();
    initCardTilts();

    // Hide loader
    const overlay = document.getElementById('loading-overlay');
    overlay.classList.add('hidden');
    setTimeout(() => overlay.remove(), 600);
}

document.addEventListener('DOMContentLoaded', init);
