# 🚦 Gridlock — AI-Powered Parking Enforcement Intelligence System

> **Flipkart Gridlock Hackathon 2.0 — Round 2**
> **Team Fantastic 4** | Problem Statement 1: Parking-Induced Congestion

[![Live Dashboard](https://img.shields.io/badge/Dashboard-Live-brightgreen?style=for-the-badge&logo=googlechrome)](http://localhost:8000/dashboard/index.html)
[![Python](https://img.shields.io/badge/Python-3.9+-blue?style=for-the-badge&logo=python)](https://www.python.org/)
[![LightGBM](https://img.shields.io/badge/LightGBM-Ensemble-orange?style=for-the-badge)](https://lightgbm.readthedocs.io/)
[![License](https://img.shields.io/badge/License-Hackathon-purple?style=for-the-badge)](#license)

---

## 🎯 Problem Statement

**Poor Visibility on Parking-Induced Congestion** — On-street illegal parking and spillover parking near commercial areas, metro stations, and events choke carriageways and intersections in Bengaluru. Traffic enforcement is patrol-based and reactive, with no data-driven heatmap of parking violations vs. congestion impact.

### Our Solution

An end-to-end AI-driven parking intelligence system that:

1. 🗺️ **Detects** illegal parking hotspots using DBSCAN geospatial clustering → **539 zones identified**
2. 📈 **Predicts** next-day violation risk using an Optuna-tuned ensemble of LightGBM + XGBoost + HistGBT
3. 🚦 **Quantifies** congestion impact with a composite Congestion Impact Score (CIS)
4. 🚔 **Recommends** targeted enforcement deployment with officer counts, tow vehicle allocation, and watch windows
5. 📊 **Explains** every prediction via an interactive dashboard with SHAP analysis and dynamic AI insights

---

## 🏗️ System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                  RAW DATA (298,450 violations)                       │
│            Bengaluru Traffic Police CCTV Records                     │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  STEP 1–2: Feature Engineering (50+ features)                        │
│  • Parking congestion score    • Time buckets (peak/off-peak)        │
│  • Vehicle classification      • Geospatial binning                  │
│  • Violation type encoding     • Junction proximity weights          │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  STEP 3: DBSCAN Hotspot Detection (Haversine, ε=100m, min=40)        │
│  → 539 geo-clusters with hotspot_score (0–100) & severity bands      │
│  → Very High / High / Medium / Low enforcement tiers                 │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  STEP 4: Predictive Risk Engine                                       │
│  ├─ Zone–Day Cartesian Grid (539 zones × 150 days)                   │
│  ├─ Lag features (1/3/7/14-day), rolling windows, growth rates       │
│  ├─ Model Benchmark (10 families × 2 target variants)                │
│  ├─ Optuna Tuning (50 trials × 3 models, P@10 objective)             │
│  ├─ Weighted Ensemble (inverse-MAE blending of top 3 models)         │
│  └─ SHAP Explainability (TreeExplainer — feature impact analysis)    │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  DASHBOARD: Interactive Intelligence Console                          │
│  • Executive Summary + Congestion Impact Quantification (CIS)        │
│  • Leaflet.js Multi-Theme Hotspot Map (4 tile styles)                │
│  • Temporal Violation Hotspot Grid (7×24 heat matrix)                │
│  • Forecast & Deploy with Dynamic Resource Allocation Simulator      │
│  • SHAP Explainability with interactive feature inspector            │
│  • Dynamic AI Explain buttons on every chart and map                 │
│  • Three.js 3D particle background                                    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Key Results

| Metric | Value |
|--------|-------|
| Total Violations Processed | **298,450** |
| Hotspot Zones Detected | **539** (54 Very High · 108 High) |
| Daily Precision@10 (Val) | **68.7%** |
| Daily Precision@10 (Test) | **59.4%** |
| Baseline P@10 | 56.0% → AI uplift: **+12.7 pp** |
| Test MAE | **~2.49** violations per zone |
| Models Benchmarked | 10 families × 2 target variants |
| Optuna Trials | 50 trials × 3 models |
| Feature Count | **50+ engineered features** |
| Train/Val/Test Split | Chronological **75 / 12.5 / 12.5 %** |

---

## ✨ Dashboard Features

### 🗺️ Hotspot Map
- **4 tile themes**: Google Maps (default), CartoDB Positron (light), CartoDB Dark Matter (dark), OpenStreetMap
- Circle markers sized by violation count, coloured by risk band
- Popups with **opaque dark background** — clearly readable on all themes
- Filter by risk band, police station, and time bucket

### 📅 Temporal Violation Hotspot Grid
- 7-day × 24-hour heat matrix aggregated from 298K+ violations
- Colour scale: green (low risk) → amber → red (very high risk)
- Hover tooltips show exact violation counts; **Monday row shows tooltips below** the cell (overflow-safe)

### 💡 Dynamic AI Explain Buttons
Every chart and the map has an **Explain** button that opens a data-driven modal with:
- Key insight numbers computed from actual loaded data
- Narrative explanation of what the chart shows and why it matters
- Actionable enforcement recommendations
- Available for: Severity Distribution, Hotspot Map, Temporal Heatmap, Feature Importance, Per-Model Breakdown, Actual vs Predicted, Error Distribution, Validation & Test Performance charts

### 🚔 Dynamic Officer Allocation Simulator
- Adjust total officers and tow vehicles via sliders
- Greedy resource-dispatch algorithm allocates resources to highest-risk zones first
- Compare AI-Guided vs. Historical vs. Random Patrol coverage in real time

### 🧠 SHAP Explainability
- Interactive SHAP summary plot with clickable hotspot annotations
- Per-model feature importance grouped bar chart
- Cross-model average importance for top 15 features

---

## 🛠️ Tech Stack

| Layer | Technologies |
|-------|-------------|
| **ML Pipeline** | Python 3.9+, scikit-learn, LightGBM, XGBoost, HistGradientBoosting, CatBoost, Optuna, SHAP |
| **Data Processing** | pandas, NumPy, DBSCAN (Haversine metric), Haversine distance |
| **Dashboard** | HTML5, Vanilla CSS3, JavaScript (ES6+) |
| **Visualization** | Leaflet.js (maps), Chart.js 4 (charts), Three.js (3D background) |
| **Data Loading** | PapaParse (browser-side CSV parsing) |
| **Fonts** | Outfit, Space Grotesk, JetBrains Mono (Google Fonts) |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- Modern browser (Chrome / Firefox / Edge)

### 1 — Clone & Install

```bash
git clone https://github.com/mahek-desai/Fantastic-4.git
cd Fantastic-4

pip install -r requirements.txt
```

### 2 — Run the Dashboard (pre-computed outputs included)

```bash
# From the project root:
python -m http.server 8000

# Then open in your browser:
# http://localhost:8000/dashboard/index.html
```

> All 10 CSV datasets and the SHAP plot are pre-generated in `dataset/`. The dashboard loads entirely in-browser — no backend required.

### 3 — Re-run the ML Pipeline (optional, ~35 min total)

```bash
python step3_hotspot_detection.py     # DBSCAN clustering → zone data  (~5 min)
python step4_risk_prediction.py       # Zone-day features & baseline    (~3 min)
python step4_model_benchmark.py       # 10-model benchmark              (~10 min)
python step4_optuna_tuning.py         # Optuna hyperparameter tuning    (~15 min)
python step4_ensemble.py              # Weighted ensemble blending       (~2 min)
python step4_final_export.py          # Final predictions, SHAP, errors (~3 min)
```

---

## 📁 Project Structure

```
Fantastic-4/
├── README.md                           # This file
├── requirements.txt                    # Python dependencies
├── walkthrough.md                      # Detailed change log & walkthrough
│
├── step3_hotspot_detection.py          # DBSCAN clustering & zone scoring
├── step4_risk_prediction.py            # Zone-day features & baseline model
├── step4_model_benchmark.py            # 10-model family benchmark
├── step4_optuna_tuning.py              # Optuna hyperparameter tuning
├── step4_ensemble.py                   # Weighted ensemble blending
├── step4_final_export.py               # Final predictions, SHAP, error analysis
├── generate_temporal_heatmap.py        # Temporal heatmap CSV generator
│
├── dataset/
│   ├── ps1_enhanced_step1_step2.csv    # Feature-engineered data (298K rows)
│   ├── hotspot_zones.csv               # 539 detected zones with scores
│   ├── hotspot_map_data.csv            # Zone centroids for map rendering
│   ├── hotspot_summary_report.csv      # High-level summary metrics
│   ├── location_ranking.csv            # Per-location violation rankings
│   ├── temporal_heatmap.csv            # Hour×Day violation counts
│   ├── zone_daily_features.csv         # Zone × Day modeling dataset
│   ├── deployment_recommendations.csv  # Final enforcement recommendations
│   ├── prediction_error_analysis.csv   # Per-zone actual vs predicted
│   ├── feature_importance.csv          # Cross-model feature importances
│   ├── model_leaderboard.csv           # Benchmark results for all models
│   ├── step4_predictions.csv           # Ensemble predictions
│   └── shap_summary.png               # SHAP beeswarm plot
│
└── dashboard/
    ├── index.html                      # Dashboard entry point (1,200+ lines)
    ├── style.css                       # Premium dark theme (2,400+ lines CSS)
    ├── app.js                          # All dashboard logic (2,235+ lines JS)
    └── images/                         # Team member photos
        ├── anand_nakum.png
        ├── shrey_panwala.png
        ├── gracy_christian.png
        └── mahek_desai.png
```

---

## 👥 Team Fantastic 4

| Name | Role | GitHub | LinkedIn |
|------|------|--------|----------|
| **Anand Nakum** | Team Lead · ML Architect · Senior ML Engineer | [anandnakum-11](https://github.com/anandnakum-11) | [anand-nakum](https://www.linkedin.com/in/anand-nakum/) |
| **Shrey Panwala** | Feature Engineering · Data Pipeline | [Shrey-Panwala](https://github.com/Shrey-Panwala) | [shrey-panwala](https://www.linkedin.com/in/shrey-panwala-95507a286/) |
| **Gracy Christian** | Frontend Engineer · UI/UX Designer | [Gracy1475](https://github.com/Gracy1475) | [gracy-christian](https://www.linkedin.com/in/gracy-christian) |
| **Mahek Desai** | Data Scientist · Ensemble Model Engineer | [mahek-desai](https://github.com/mahek-desai) | [mahek-desai](https://www.linkedin.com/in/mahek-desai-639857333/) |

---

## 📜 License

This project was built for the **Flipkart Gridlock Hackathon 2.0 (Round 2)**.
All code and outputs are property of **Team Fantastic 4**.

---

<p align="center">
  Built with ❤️ by <strong>Team Fantastic 4</strong> · Bengaluru, India 🇮🇳
</p>
