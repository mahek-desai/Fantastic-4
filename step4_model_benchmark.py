"""
Step 4 — Model Benchmark
=========================
Trains and evaluates 10 model families (each with raw & log1p target variants)
on the FROZEN zone-day dataset and chronological split from Step 4.

Output: dataset/model_leaderboard.csv
"""

import os
import time
import warnings
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="lightgbm")

# ── Paths — resolved relative to this script's location ──────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
DAILY_FEATURES_PATH = os.path.join(DATASET_DIR, "zone_daily_features.csv")
LEADERBOARD_PATH    = os.path.join(DATASET_DIR, "model_leaderboard.csv")

# ── Frozen feature list (identical to step4_risk_prediction.py) ──────────────
FEATURE_COLS = [
    'centroid_lat', 'centroid_lon', 'lat_std', 'lon_std', 'violation_density',
    'unique_violation_types', 'unique_vehicle_classes', 'unique_locations', 'unique_junctions',
    'recurring_hotspot_flag', 'month_over_month_trend', 'peak_share', 'hotspot_band_num',
    'day_of_week', 'is_weekend', 'month', 'week_of_month', 'is_peak_season',
    'lag_1_count', 'lag_3_count', 'lag_7_count', 'lag_14_count',
    'rolling_7d_sum', 'rolling_7d_mean', 'rolling_14d_sum', 'rolling_14d_mean',
    'lag_1_parking_count', 'rolling_7d_parking_sum',
    'lag_1_peak_hour_count', 'rolling_7d_peak_hour_sum',
    'days_since_last_violation', 'count_growth_rate_7d', 'count_growth_rate_14d'
]
TARGET_COL = 'next_day_violation_count'


# ── Evaluation helpers ───────────────────────────────────────────────────────
def evaluate(y_true, y_pred):
    mae  = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    return mae, rmse


def precision_at_k(y_true, y_pred, k=10):
    top_true = set(np.argsort(y_true)[-k:])
    top_pred = set(np.argsort(y_pred)[-k:])
    return len(top_true & top_pred) / k


def daily_precision_at_k(df, pred_col, target_col, k=10):
    precs = []
    for _, grp in df.groupby('created_date_ist'):
        if len(grp) < k:
            continue
        yt = grp[target_col].values
        yp = grp[pred_col].values
        if yt.max() == 0:
            continue
        precs.append(precision_at_k(yt, yp, k))
    return np.mean(precs) if precs else 0.0


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    t_global = time.time()
    print("=" * 70)
    print("STEP 4 - MODEL BENCHMARK (10 Models x 2 Target Variants)")
    print("=" * 70)

    # ── 1. Load frozen dataset ───────────────────────────────────────────
    print("\nLoading frozen zone-day features ...")
    grid = pd.read_csv(DAILY_FEATURES_PATH)

    # Re-derive modeling subset (drop rows where lags / target are NaN)
    modeling_df = grid.dropna(subset=[
        TARGET_COL, 'lag_14_count', 'rolling_14d_mean',
        'count_growth_rate_14d', 'days_since_last_violation'
    ]).copy()
    print(f"  Modeling rows: {len(modeling_df):,}")

    # ── 2. Frozen chronological split ────────────────────────────────────
    unique_dates = sorted(modeling_df['created_date_ist'].unique())
    n = len(unique_dates)
    train_cut = int(n * 0.75)
    val_cut   = int(n * 0.875)

    train_dates = unique_dates[:train_cut]
    val_dates   = unique_dates[train_cut:val_cut]
    test_dates  = unique_dates[val_cut:]

    train_df = modeling_df[modeling_df['created_date_ist'].isin(train_dates)].copy()
    val_df   = modeling_df[modeling_df['created_date_ist'].isin(val_dates)].copy()
    test_df  = modeling_df[modeling_df['created_date_ist'].isin(test_dates)].copy()

    print(f"  Train: {len(train_df):,} rows  ({train_dates[0]} -> {train_dates[-1]})")
    print(f"  Val:   {len(val_df):,} rows  ({val_dates[0]} -> {val_dates[-1]})")
    print(f"  Test:  {len(test_df):,} rows  ({test_dates[0]} -> {test_dates[-1]})")

    X_train = train_df[FEATURE_COLS].values
    y_train = train_df[TARGET_COL].values
    X_val   = val_df[FEATURE_COLS].values
    y_val   = val_df[TARGET_COL].values
    X_test  = test_df[FEATURE_COLS].values
    y_test  = test_df[TARGET_COL].values

    # ── 3. Build model registry ──────────────────────────────────────────
    from sklearn.ensemble import (
        RandomForestRegressor, ExtraTreesRegressor,
        HistGradientBoostingRegressor
    )
    from sklearn.linear_model import PoissonRegressor, TweedieRegressor
    import lightgbm as lgb
    import xgboost as xgb
    from catboost import CatBoostRegressor

    models = [
        ("Persistence (lag_1)",       None),              # special
        ("Rolling 7d Mean",           None),              # special
        ("Poisson Regressor",         PoissonRegressor(alpha=0.1, max_iter=500)),
        ("Tweedie (p=1.5)",           TweedieRegressor(power=1.5, alpha=0.1, max_iter=500)),
        ("ExtraTrees",                ExtraTreesRegressor(n_estimators=200, random_state=42, n_jobs=-1)),
        ("RandomForest",              RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=-1)),
        ("HistGradientBoosting",      HistGradientBoostingRegressor(max_iter=300, random_state=42)),
        ("LightGBM",                  lgb.LGBMRegressor(n_estimators=300, learning_rate=0.05,
                                                         num_leaves=63, random_state=42,
                                                         n_jobs=-1, verbosity=-1)),
        ("XGBoost",                   xgb.XGBRegressor(n_estimators=300, learning_rate=0.05,
                                                        max_depth=7, random_state=42,
                                                        n_jobs=-1, verbosity=0)),
        ("CatBoost",                  CatBoostRegressor(iterations=300, learning_rate=0.05,
                                                         depth=7, random_seed=42,
                                                         verbose=0)),
    ]

    # ── 4. Train & evaluate each model ───────────────────────────────────
    results = []
    
    from sklearn.preprocessing import MinMaxScaler
    scaler = MinMaxScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    X_test_scaled = scaler.transform(X_test)

    for name, model in models:
        for variant in ["raw", "log1p"]:
            # GLM models don't need log1p target transformation
            if name in ("Poisson Regressor", "Tweedie (p=1.5)") and variant == "log1p":
                continue
                
            print(f"\n  > {name}  [{variant}] ...", end="  ", flush=True)

            # Prepare targets
            if variant == "log1p":
                y_tr = np.log1p(y_train)
            else:
                y_tr = y_train

            # ── Baselines (no fitting) ──────────────────────────────
            if name == "Persistence (lag_1)":
                val_pred  = val_df['lag_1_count'].values.copy()
                test_pred = test_df['lag_1_count'].values.copy()
                t_train, t_infer = 0.0, 0.0

            elif name == "Rolling 7d Mean":
                val_pred  = val_df['rolling_7d_mean'].values.copy()
                test_pred = test_df['rolling_7d_mean'].values.copy()
                t_train, t_infer = 0.0, 0.0

            # ── GLM models need scaled non-negative input ──────────────────
            elif name in ("Poisson Regressor", "Tweedie (p=1.5)"):
                t0 = time.time()
                model.fit(X_train_scaled, y_tr)
                t_train = time.time() - t0

                t0 = time.time()
                val_pred  = model.predict(X_val_scaled)
                test_pred = model.predict(X_test_scaled)
                t_infer = time.time() - t0

            # ── Standard ML models ──────────────────────────────────
            else:
                t0 = time.time()
                model.fit(X_train, y_tr)
                t_train = time.time() - t0

                t0 = time.time()
                val_pred  = model.predict(X_val)
                test_pred = model.predict(X_test)
                t_infer = time.time() - t0

            # ── Inverse-transform for log1p variant ─────────────────
            if variant == "log1p" and name not in ("Persistence (lag_1)", "Rolling 7d Mean"):
                val_pred  = np.expm1(val_pred)
                test_pred = np.expm1(test_pred)

            # Clip negative predictions
            val_pred  = np.clip(val_pred, 0, None)
            test_pred = np.clip(test_pred, 0, None)

            # ── Evaluate ────────────────────────────────────────────
            v_mae, v_rmse = evaluate(y_val, val_pred)
            t_mae, t_rmse = evaluate(y_test, test_pred)

            # Daily Precision@10
            val_df['_pred'] = val_pred
            test_df['_pred'] = test_pred
            v_p10 = daily_precision_at_k(val_df, '_pred', TARGET_COL, k=10)
            t_p10 = daily_precision_at_k(test_df, '_pred', TARGET_COL, k=10)

            print(f"Val MAE={v_mae:.3f}  RMSE={v_rmse:.3f}  P@10={v_p10*100:.1f}%  |  "
                  f"Test MAE={t_mae:.3f}  RMSE={t_rmse:.3f}  P@10={t_p10*100:.1f}%  "
                  f"[train={t_train:.2f}s  infer={t_infer:.3f}s]")

            results.append({
                'model_name':       name,
                'variant':          variant,
                'val_mae':          round(v_mae, 4),
                'val_rmse':         round(v_rmse, 4),
                'val_p10':          round(v_p10, 4),
                'test_mae':         round(t_mae, 4),
                'test_rmse':        round(t_rmse, 4),
                'test_p10':         round(t_p10, 4),
                'train_time_s':     round(t_train, 3),
                'inference_time_s': round(t_infer, 4),
            })

    # ── 5. Build and save leaderboard ────────────────────────────────────
    lb = pd.DataFrame(results)
    lb = lb.sort_values('val_p10', ascending=False).reset_index(drop=True)
    lb.to_csv(LEADERBOARD_PATH, index=False)

    print("\n" + "=" * 70)
    print("MODEL LEADERBOARD  (sorted by Validation Daily Precision@10)")
    print("=" * 70)
    print(lb.to_string(index=False))
    print(f"\nSaved to: {LEADERBOARD_PATH}")
    print(f"Total benchmark time: {time.time() - t_global:.1f}s")


if __name__ == "__main__":
    main()
