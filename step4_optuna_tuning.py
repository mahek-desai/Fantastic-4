"""
Step 4 — Optuna Hyperparameter Tuning
======================================
Tunes the top 3 boosting models (LightGBM, XGBoost, HistGradientBoosting)
using Optuna with TimeSeriesSplit on the training set.

Reads: dataset/zone_daily_features.csv, dataset/model_leaderboard.csv
Output: dataset/tuning_results.csv
"""

import os
import time
import warnings
import numpy as np
import pandas as pd
import optuna
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="lightgbm")
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ── Paths — resolved relative to this script's location ──────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
DAILY_FEATURES_PATH = os.path.join(DATASET_DIR, "zone_daily_features.csv")
LEADERBOARD_PATH    = os.path.join(DATASET_DIR, "model_leaderboard.csv")
TUNING_PATH         = os.path.join(DATASET_DIR, "tuning_results.csv")

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
N_TRIALS = 50


# ── Evaluation helpers ───────────────────────────────────────────────────────
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


# ── Objective factories ──────────────────────────────────────────────────────
def make_lgbm_objective(X, y, dates, tscv):
    import lightgbm as lgb

    def objective(trial):
        params = {
            'n_estimators':      trial.suggest_int('n_estimators', 100, 600),
            'learning_rate':     trial.suggest_float('learning_rate', 0.01, 0.2, log=True),
            'num_leaves':        trial.suggest_int('num_leaves', 15, 127),
            'max_depth':         trial.suggest_int('max_depth', 3, 12),
            'min_child_samples': trial.suggest_int('min_child_samples', 5, 50),
            'subsample':         trial.suggest_float('subsample', 0.5, 1.0),
            'colsample_bytree':  trial.suggest_float('colsample_bytree', 0.5, 1.0),
            'reg_alpha':         trial.suggest_float('reg_alpha', 1e-8, 10.0, log=True),
            'reg_lambda':        trial.suggest_float('reg_lambda', 1e-8, 10.0, log=True),
            'random_state': 42, 'n_jobs': -1, 'verbosity': -1
        }
        scores = []
        for tr_idx, va_idx in tscv.split(X):
            model = lgb.LGBMRegressor(**params)
            model.fit(X[tr_idx], y[tr_idx])
            pred = np.clip(model.predict(X[va_idx]), 0, None)
            scores.append(daily_precision_at_k(dates[va_idx], y[va_idx], pred))
        return np.mean(scores)
    return objective


def make_xgb_objective(X, y, dates, tscv):
    import xgboost as xgb

    def objective(trial):
        params = {
            'n_estimators':     trial.suggest_int('n_estimators', 100, 600),
            'learning_rate':    trial.suggest_float('learning_rate', 0.01, 0.2, log=True),
            'max_depth':        trial.suggest_int('max_depth', 3, 12),
            'min_child_weight': trial.suggest_int('min_child_weight', 1, 30),
            'subsample':        trial.suggest_float('subsample', 0.5, 1.0),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.5, 1.0),
            'reg_alpha':        trial.suggest_float('reg_alpha', 1e-8, 10.0, log=True),
            'reg_lambda':       trial.suggest_float('reg_lambda', 1e-8, 10.0, log=True),
            'random_state': 42, 'n_jobs': -1, 'verbosity': 0
        }
        scores = []
        for tr_idx, va_idx in tscv.split(X):
            model = xgb.XGBRegressor(**params)
            model.fit(X[tr_idx], y[tr_idx])
            pred = np.clip(model.predict(X[va_idx]), 0, None)
            scores.append(daily_precision_at_k(dates[va_idx], y[va_idx], pred))
        return np.mean(scores)
    return objective


def make_hgb_objective(X, y, dates, tscv):
    from sklearn.ensemble import HistGradientBoostingRegressor

    def objective(trial):
        params = {
            'max_iter':          trial.suggest_int('max_iter', 100, 600),
            'learning_rate':     trial.suggest_float('learning_rate', 0.01, 0.2, log=True),
            'max_depth':         trial.suggest_int('max_depth', 3, 12),
            'min_samples_leaf':  trial.suggest_int('min_samples_leaf', 5, 50),
            'max_leaf_nodes':    trial.suggest_int('max_leaf_nodes', 15, 127),
            'l2_regularization': trial.suggest_float('l2_regularization', 1e-8, 10.0, log=True),
            'max_bins':          trial.suggest_int('max_bins', 64, 255),
            'random_state': 42
        }
        scores = []
        for tr_idx, va_idx in tscv.split(X):
            model = HistGradientBoostingRegressor(**params)
            model.fit(X[tr_idx], y[tr_idx])
            pred = np.clip(model.predict(X[va_idx]), 0, None)
            scores.append(daily_precision_at_k(dates[va_idx], y[va_idx], pred))
        return np.mean(scores)
    return objective


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    t_global = time.time()
    print("=" * 70)
    print("STEP 4 - OPTUNA HYPERPARAMETER TUNING  (50 trials each)")
    print("=" * 70)

    # Load data
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
    dates_train = train_df['created_date_ist'].values

    X_val  = val_df[FEATURE_COLS].values
    y_val  = val_df[TARGET_COL].values
    X_test = test_df[FEATURE_COLS].values
    y_test = test_df[TARGET_COL].values

    tscv = TimeSeriesSplit(n_splits=3)

    # Models to tune
    tune_jobs = [
        ("LightGBM",              make_lgbm_objective),
        ("XGBoost",               make_xgb_objective),
        ("HistGradientBoosting",  make_hgb_objective),
    ]

    tuning_results = []

    for model_name, objective_factory in tune_jobs:
        print(f"\n{'-'*60}")
        print(f"  Tuning {model_name}  ({N_TRIALS} trials) ...")
        print(f"{'-'*60}")

        obj = objective_factory(X_train, y_train, dates_train, tscv)

        study = optuna.create_study(direction='maximize',
                                    study_name=model_name,
                                    sampler=optuna.samplers.TPESampler(seed=42))
        study.optimize(obj, n_trials=N_TRIALS, show_progress_bar=False)

        best = study.best_trial
        print(f"  Best CV P@10: {best.value*100:.2f}%")
        print(f"  Best params:  {best.params}")

        # Retrain best model on full training set, evaluate on val & test
        bp = best.params
        if model_name == "LightGBM":
            import lightgbm as lgb
            final_model = lgb.LGBMRegressor(**bp, random_state=42, n_jobs=-1, verbosity=-1)
        elif model_name == "XGBoost":
            import xgboost as xgb
            final_model = xgb.XGBRegressor(**bp, random_state=42, n_jobs=-1, verbosity=0)
        else:
            from sklearn.ensemble import HistGradientBoostingRegressor
            final_model = HistGradientBoostingRegressor(**bp, random_state=42)

        t0 = time.time()
        final_model.fit(X_train, y_train)
        train_time = time.time() - t0

        val_pred  = np.clip(final_model.predict(X_val), 0, None)
        test_pred = np.clip(final_model.predict(X_test), 0, None)

        val_mae  = mean_absolute_error(y_val, val_pred)
        val_rmse = np.sqrt(mean_squared_error(y_val, val_pred))
        val_df['_pred'] = val_pred
        val_p10 = daily_precision_at_k(val_df['created_date_ist'].values, y_val, val_pred)

        test_mae  = mean_absolute_error(y_test, test_pred)
        test_rmse = np.sqrt(mean_squared_error(y_test, test_pred))
        test_df['_pred'] = test_pred
        test_p10 = daily_precision_at_k(test_df['created_date_ist'].values, y_test, test_pred)

        print(f"  Val  -> MAE={val_mae:.3f}  RMSE={val_rmse:.3f}  P@10={val_p10*100:.1f}%")
        print(f"  Test -> MAE={test_mae:.3f}  RMSE={test_rmse:.3f}  P@10={test_p10*100:.1f}%")

        tuning_results.append({
            'model_name':   model_name,
            'best_cv_p10':  round(best.value, 4),
            'best_params':  str(best.params),
            'val_mae':      round(val_mae, 4),
            'val_rmse':     round(val_rmse, 4),
            'val_p10':      round(val_p10, 4),
            'test_mae':     round(test_mae, 4),
            'test_rmse':    round(test_rmse, 4),
            'test_p10':     round(test_p10, 4),
            'train_time_s': round(train_time, 3),
        })

    results_df = pd.DataFrame(tuning_results)
    results_df.to_csv(TUNING_PATH, index=False)
    print(f"\nSaved tuning results to: {TUNING_PATH}")
    print(f"Total tuning time: {time.time() - t_global:.1f}s")


if __name__ == "__main__":
    main()
