# 🚦 Gridlock — AI-Powered Parking Enforcement Intelligence System

> **Flipkart Gridlock Hackathon 2.0 — Round 2**  
> **Team Fantastic 4** | Problem Statement 1: Parking-Induced Congestion

---

## 🎯 Problem Statement

**Poor Visibility on Parking-Induced Congestion** — On-street illegal parking and spillover parking near commercial areas, metro stations, and events choke carriageways and intersections in Bengaluru. Enforcement is patrol-based and reactive, with no heatmap of parking violations vs. congestion impact.

**Our Solution:** An AI-driven parking intelligence system that:
1. **Detects** illegal parking hotspots using DBSCAN geospatial clustering (539 zones identified)
2. **Predicts** next-day violation risk using an Optuna-tuned ensemble of LightGBM + XGBoost + HistGBT
3. **Quantifies** congestion impact with a composite Congestion Impact Score
4. **Recommends** targeted enforcement deployment with officer allocation and time windows

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        RAW DATA (298,450 violations)                │
│                  Bengaluru Traffic Police CCTV Records               │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  STEP 1-2: Feature Engineering (50+ features)                       │
│  • Parking congestion score    • Time buckets (peak/off-peak)       │
│  • Vehicle classification      • Geospatial binning                 │
│  • Violation type encoding     • Junction proximity                 │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  STEP 3: DBSCAN Hotspot Detection (Haversine metric, 100m radius)   │
│  → 539 geo-clusters (zones) with severity scoring & banding         │
│  → Zone-level: hotspot_score (0-100), severity band, trend          │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  STEP 4: Predictive Risk Engine                                      │
│  ├─ Zone-Day Cartesian Grid (539 zones × 150 days)                  │
│  ├─ Lag features (1/3/7/14-day), rolling windows, growth rates      │
│  ├─ Model Benchmark (10 families × 2 target variants)               │
│  ├─ Optuna Tuning (50 trials × 3 models, P@10 objective)           │
│  ├─ Weighted Ensemble (inverse-MAE blending)                        │
│  └─ SHAP Explainability (TreeExplainer)                             │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  DASHBOARD: Interactive Intelligence Console                         │
│  • Executive Summary with Congestion Impact Quantification          │
│  • Leaflet.js Map with risk-colored hotspot markers                 │
│  • Forecast & Deploy with Dynamic Resource Allocation               │
│  • SHAP Explainability with interactive feature importance          │
│  • Three.js 3D particle background                                   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Key Results

| Metric | Value |
|--------|-------|
| Total Violations Processed | 298,450 |
| Hotspot Zones Detected | 539 (54 Very High, 108 High) |
| Daily Precision@10 (P@10) | 68.7% |
| Models Benchmarked | 10 families × 2 target variants |
| Feature Count | 50+ engineered features |
| Anti-leakage | Chronological 75/12.5/12.5% split |

---

## 🛠️ Tech Stack

| Layer | Technologies |
|-------|-------------|
| **ML Pipeline** | Python, scikit-learn, LightGBM, XGBoost, CatBoost, Optuna, SHAP |
| **Data Processing** | pandas, NumPy, DBSCAN (Haversine metric) |
| **Dashboard** | HTML5, CSS3, JavaScript (vanilla) |
| **Visualization** | Leaflet.js, Chart.js, Three.js |
| **Data Loading** | PapaParse (CSV parsing in browser) |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.9+ 
- Modern web browser (Chrome/Firefox/Edge)

### Setup

```bash
# 1. Clone the repository
git clone <repo-url>
cd Flipkart-Gridlock

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Run the ML pipeline (optional — pre-computed outputs are included)
python step3_hotspot_detection.py    # ~5 min — generates zone data
python step4_risk_prediction.py      # ~3 min — generates daily features
python step4_model_benchmark.py      # ~10 min — benchmarks 10 models
python step4_optuna_tuning.py        # ~15 min — tunes top 3 models
python step4_ensemble.py             # ~2 min — blends tuned models
python step4_final_export.py         # ~3 min — exports final predictions

# 4. Open the dashboard
# Simply open dashboard/index.html in your browser
# Or use a local server:
cd dashboard
python -m http.server 8000
# Then visit http://localhost:8000
```

---

## 📁 Project Structure

```
Flipkart-Gridlock/
├── README.md                           # This file
├── requirements.txt                    # Python dependencies
├── ML flipkart.txt                     # Strategy & planning notes
│
├── step3_hotspot_detection.py          # DBSCAN clustering & zone scoring
├── step4_risk_prediction.py            # Zone-day features & baseline model
├── step4_model_benchmark.py            # 10-model family benchmark
├── step4_optuna_tuning.py              # Optuna hyperparameter tuning
├── step4_ensemble.py                   # Weighted ensemble blending
├── step4_final_export.py               # Final predictions, SHAP, error analysis
│
├── dataset/
│   ├── ps1_enhanced_step1_step2.csv    # Raw feature-engineered data (298K rows)
│   ├── hotspot_zones.csv               # 539 detected zones with scores
│   ├── hotspot_map_data.csv            # Zone centroids for map rendering
│   ├── hotspot_summary_report.csv      # High-level summary metrics
│   ├── location_ranking.csv            # Per-location violation rankings
│   ├── zone_daily_features.csv         # Zone × Day modeling dataset
│   ├── deployment_recommendations.csv  # Final enforcement recommendations
│   ├── prediction_error_analysis.csv   # Per-zone actual vs predicted
│   ├── feature_importance.csv          # Cross-model feature importances
│   ├── shap_summary.png               # SHAP beeswarm plot
│   └── step4_predictions.csv           # Model evaluation metrics
│
└── dashboard/
    ├── index.html                      # Dashboard entry point
    ├── style.css                       # Premium dark theme styles
    └── app.js                          # All dashboard logic & rendering
```

---

## 👥 Team Fantastic 4

| Name | Role |
|------|------|
| Team Member 1 | ML Pipeline & Feature Engineering |
| Team Member 2 | Dashboard Development & UI/UX |
| Team Member 3 | Data Analysis & Visualization |
| Team Member 4 | Research & Documentation |

---

## 📜 License

This project was built for the Flipkart Gridlock Hackathon 2.0 (Round 2).
