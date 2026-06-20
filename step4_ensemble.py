"""
Step 4 — Ensemble Blending
===========================
Takes the top 2–3 tuned models (from tuning_results.csv) and blends them
via simple average and inverse-MAE-weighted average.

Reads: dataset/zone_daily_features.csv, dataset/tuning_results.csv
Output: dataset/ensemble_results.csv
"""

import ast
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
TUNING_PATH         = os.path.join(DATASET_DIR, "tuning_results.csv")
ENSEMBLE_PATH       = os.path.join(DATASET_DIR, "ensemble_results.csv")

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


def precision_at_k(y_true, y_pred, k=10):
    top_true = set(np.argsort(y_true)[-k:])
    top_pred = set(np.argsort(y_pred)[-k:])
    return len(top_true & top_pred) / k


def daily_precision_at_k(dates, y_true, y_pred, k=10):
    df_tmp = pd.DataFrame({'d': dates, 'yt': y_true, 'yp': y_pred})
    precs = []
    for _, grp in df_tmp.groupby('d'):
        if len(grp) < k or grp['yt'].max() == 0:
            continue
        precs.append(precision_at_k(grp['yt'].values, grp['yp'].values, k))
    return np.mean(precs) if precs else 0.0


def build_model(name, params):
    """Instantiate a model from name and best-params dict."""
    if name == "LightGBM":
        import lightgbm as lgb
        return lgb.LGBMRegressor(**params, random_state=42, n_jobs=-1, verbosity=-1)
    elif name == "XGBoost":
        import xgboost as xgb
        return xgb.XGBRegressor(**params, random_state=42, n_jobs=-1, verbosity=0)
    elif name == "HistGradientBoosting":
        from sklearn.ensemble import HistGradientBoostingRegressor
        return HistGradientBoostingRegressor(**params, random_state=42)
    else:
        raise ValueError(f"Unknown model: {name}")


def main():
    t_global = time.time()
    print("=" * 70)
    print("STEP 4 - ENSEMBLE BLENDING")
    print("=" * 70)

    # ── Load data ────────────────────────────────────────────────────────
    grid = pd.read_csv(DAILY_FEATURES_PATH)
    modeling_df = grid.dropna(subset=[
        TARGET_COL, 'lag_14_count', 'rolling_14d_mean',
        'count_growth_rate_14d', 'days_since_last_violation'
    ]).copy()

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

    X_train = train_df[FEATURE_COLS].values
    y_train = train_df[TARGET_COL].values
    X_val   = val_df[FEATURE_COLS].values
    y_val   = val_df[TARGET_COL].values
    X_test  = test_df[FEATURE_COLS].values
    y_test  = test_df[TARGET_COL].values

    # ── Load tuning results ──────────────────────────────────────────────
    tuning_df = pd.read_csv(TUNING_PATH)
    print(f"\nLoaded {len(tuning_df)} tuned models from {TUNING_PATH}")

    # ── Retrain each tuned model ─────────────────────────────────────────
    model_preds_val  = {}
    model_preds_test = {}
    model_val_maes   = {}

    for _, row in tuning_df.iterrows():
        name   = row['model_name']
        params = ast.literal_eval(row['best_params'])
        print(f"  Retraining tuned {name} ...")

        model = build_model(name, params)
        model.fit(X_train, y_train)

        val_pred  = np.clip(model.predict(X_val), 0, None)
        test_pred = np.clip(model.predict(X_test), 0, None)

        model_preds_val[name]  = val_pred
        model_preds_test[name] = test_pred
        model_val_maes[name]   = mean_absolute_error(y_val, val_pred)

    names = list(model_preds_val.keys())
    print(f"\n  Models in ensemble: {names}")

    # ── Build ensembles ──────────────────────────────────────────────────
    results = []

    # Individual tuned models (for comparison)
    for nm in names:
        vp = model_preds_val[nm]
        tp = model_preds_test[nm]
        v_mae  = mean_absolute_error(y_val, vp)
        v_rmse = np.sqrt(mean_squared_error(y_val, vp))
        v_p10  = daily_precision_at_k(val_df['created_date_ist'].values, y_val, vp)
        t_mae  = mean_absolute_error(y_test, tp)
        t_rmse = np.sqrt(mean_squared_error(y_test, tp))
        t_p10  = daily_precision_at_k(test_df['created_date_ist'].values, y_test, tp)
        results.append({
            'model_name': f"Tuned {nm}", 'val_mae': round(v_mae,4), 'val_rmse': round(v_rmse,4),
            'val_p10': round(v_p10,4), 'test_mae': round(t_mae,4), 'test_rmse': round(t_rmse,4),
            'test_p10': round(t_p10,4)
        })

    # Simple average
    val_avg  = np.mean([model_preds_val[n] for n in names], axis=0)
    test_avg = np.mean([model_preds_test[n] for n in names], axis=0)

    v_mae  = mean_absolute_error(y_val, val_avg)
    v_rmse = np.sqrt(mean_squared_error(y_val, val_avg))
    v_p10  = daily_precision_at_k(val_df['created_date_ist'].values, y_val, val_avg)
    t_mae  = mean_absolute_error(y_test, test_avg)
    t_rmse = np.sqrt(mean_squared_error(y_test, test_avg))
    t_p10  = daily_precision_at_k(test_df['created_date_ist'].values, y_test, test_avg)
    results.append({
        'model_name': 'Ensemble (Simple Avg)', 'val_mae': round(v_mae,4), 'val_rmse': round(v_rmse,4),
        'val_p10': round(v_p10,4), 'test_mae': round(t_mae,4), 'test_rmse': round(t_rmse,4),
        'test_p10': round(t_p10,4)
    })

    # Weighted average (weights ∝ 1/val_mae)
    weights = np.array([1.0 / model_val_maes[n] for n in names])
    weights = weights / weights.sum()
    print(f"\n  Weighted ensemble weights: {dict(zip(names, weights.round(4)))}")

    val_wavg  = sum(w * model_preds_val[n] for w, n in zip(weights, names))
    test_wavg = sum(w * model_preds_test[n] for w, n in zip(weights, names))

    v_mae  = mean_absolute_error(y_val, val_wavg)
    v_rmse = np.sqrt(mean_squared_error(y_val, val_wavg))
    v_p10  = daily_precision_at_k(val_df['created_date_ist'].values, y_val, val_wavg)
    t_mae  = mean_absolute_error(y_test, test_wavg)
    t_rmse = np.sqrt(mean_squared_error(y_test, test_wavg))
    t_p10  = daily_precision_at_k(test_df['created_date_ist'].values, y_test, test_wavg)
    results.append({
        'model_name': 'Ensemble (Weighted Avg)', 'val_mae': round(v_mae,4), 'val_rmse': round(v_rmse,4),
        'val_p10': round(v_p10,4), 'test_mae': round(t_mae,4), 'test_rmse': round(t_rmse,4),
        'test_p10': round(t_p10,4)
    })

    # ── Save & Print ─────────────────────────────────────────────────────
    res_df = pd.DataFrame(results).sort_values('val_p10', ascending=False).reset_index(drop=True)
    res_df.to_csv(ENSEMBLE_PATH, index=False)

    print("\n" + "=" * 70)
    print("ENSEMBLE COMPARISON  (sorted by Validation Daily Precision@10)")
    print("=" * 70)
    print(res_df.to_string(index=False))
    print(f"\nSaved to: {ENSEMBLE_PATH}")
    print(f"Total time: {time.time() - t_global:.1f}s")


if __name__ == "__main__":
    main()
