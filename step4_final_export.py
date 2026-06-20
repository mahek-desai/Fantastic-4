"""
Step 4 — Final Export
======================
Uses the best model/ensemble from the tuning + ensemble phase to regenerate:
  1. dataset/step4_predictions.csv  (updated evaluation metrics)
  2. dataset/deployment_recommendations.csv  (updated forecasts for 2024-04-09)

Also prints a side-by-side comparison of old vs new top-10 deployment zones.

Reads: dataset/zone_daily_features.csv, dataset/tuning_results.csv,
       dataset/ensemble_results.csv, dataset/hotspot_zones.csv
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
DAILY_FEATURES_PATH   = os.path.join(DATASET_DIR, "zone_daily_features.csv")
TUNING_PATH           = os.path.join(DATASET_DIR, "tuning_results.csv")
ENSEMBLE_PATH         = os.path.join(DATASET_DIR, "ensemble_results.csv")
ZONES_PATH            = os.path.join(DATASET_DIR, "hotspot_zones.csv")
PREDICTIONS_PATH      = os.path.join(DATASET_DIR, "step4_predictions.csv")
RECOMMENDATIONS_PATH  = os.path.join(DATASET_DIR, "deployment_recommendations.csv")
OLD_RECOMMENDATIONS   = None  # We'll load the existing file before overwriting

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
    print("STEP 4 - FINAL EXPORT  (Best Model -> Deployment Recommendations)")
    print("=" * 70)

    # ── Load old recommendations for comparison ──────────────────────────
    try:
        old_recs = pd.read_csv(RECOMMENDATIONS_PATH)
        print(f"Loaded existing recommendations ({len(old_recs)} rows) for comparison.")
    except FileNotFoundError:
        old_recs = None

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

    # ── Determine best approach (ensemble or single model) ───────────────
    ensemble_df = pd.read_csv(ENSEMBLE_PATH)
    tuning_df   = pd.read_csv(TUNING_PATH)

    best_row = ensemble_df.sort_values('val_p10', ascending=False).iloc[0]
    best_name = best_row['model_name']
    print(f"\n  Best approach: {best_name}  (Val P@10 = {best_row['val_p10']*100:.1f}%)")

    is_ensemble = 'Ensemble' in best_name

    # ── Retrain all tuned models (needed for both ensemble and single) ───
    tuned_models = {}
    tuned_val_maes = {}
    for _, row in tuning_df.iterrows():
        name   = row['model_name']
        params = ast.literal_eval(row['best_params'])
        model  = build_model(name, params)
        model.fit(X_train, y_train)
        tuned_models[name] = model
        tuned_val_maes[name] = mean_absolute_error(y_val, np.clip(model.predict(X_val), 0, None))
    
    names = list(tuned_models.keys())

    # ── Produce final val/test predictions ───────────────────────────────
    if is_ensemble and 'Weighted' in best_name:
        weights = np.array([1.0 / tuned_val_maes[n] for n in names])
        weights /= weights.sum()
        val_pred  = sum(w * np.clip(tuned_models[n].predict(X_val), 0, None) for w, n in zip(weights, names))
        test_pred = sum(w * np.clip(tuned_models[n].predict(X_test), 0, None) for w, n in zip(weights, names))
    elif is_ensemble:
        val_pred  = np.mean([np.clip(tuned_models[n].predict(X_val), 0, None) for n in names], axis=0)
        test_pred = np.mean([np.clip(tuned_models[n].predict(X_test), 0, None) for n in names], axis=0)
    else:
        # Single best tuned model
        single_name = best_name.replace("Tuned ", "")
        best_model  = tuned_models[single_name]
        val_pred    = np.clip(best_model.predict(X_val), 0, None)
        test_pred   = np.clip(best_model.predict(X_test), 0, None)

    # ── Compute final metrics ────────────────────────────────────────────
    v_mae  = mean_absolute_error(y_val, val_pred)
    v_rmse = np.sqrt(mean_squared_error(y_val, val_pred))
    v_p10  = daily_precision_at_k(val_df['created_date_ist'].values, y_val, val_pred)
    t_mae  = mean_absolute_error(y_test, test_pred)
    t_rmse = np.sqrt(mean_squared_error(y_test, test_pred))
    t_p10  = daily_precision_at_k(test_df['created_date_ist'].values, y_test, test_pred)

    print(f"\n  Final Model Performance:")
    print(f"    Val  -> MAE={v_mae:.3f}  RMSE={v_rmse:.3f}  P@10={v_p10*100:.1f}%")
    print(f"    Test -> MAE={t_mae:.3f}  RMSE={t_rmse:.3f}  P@10={t_p10*100:.1f}%")

    # ── Save predictions metrics ─────────────────────────────────────────
    pred_df = pd.DataFrame([{
        'best_model': best_name,
        'val_mae': round(v_mae,4), 'val_rmse': round(v_rmse,4), 'val_p10': round(v_p10,4),
        'test_mae': round(t_mae,4), 'test_rmse': round(t_rmse,4), 'test_p10': round(t_p10,4),
    }])
    pred_df.to_csv(PREDICTIONS_PATH, index=False)
    print(f"\n  Saved updated predictions to: {PREDICTIONS_PATH}")

    # ── Generate deployment recommendations for 2024-04-09 ───────────────
    print("\n--- Generating Deployment Recommendations for 2024-04-09 ---")

    final_day = grid[grid['created_date_ist'] == '2024-04-08'].copy()
    if len(final_day) == 0:
        print("  WARNING: No data for 2024-04-08 - cannot generate deployment recommendations.")
        return

    X_final = final_day[FEATURE_COLS].values

    if is_ensemble and 'Weighted' in best_name:
        final_pred = sum(w * np.clip(tuned_models[n].predict(X_final), 0, None) for w, n in zip(weights, names))
    elif is_ensemble:
        final_pred = np.mean([np.clip(tuned_models[n].predict(X_final), 0, None) for n in names], axis=0)
    else:
        final_pred = np.clip(tuned_models[single_name].predict(X_final), 0, None)

    final_day['pred_violations'] = np.round(final_pred, 2)
    final_day['predicted_pct'] = final_day['pred_violations'].rank(pct=True)
    final_day['predicted_risk_score'] = (final_day['predicted_pct'] * 100).round(1)

    def get_risk_band(pct):
        if pct >= 0.90: return 'Very High'
        elif pct >= 0.70: return 'High'
        elif pct >= 0.40: return 'Medium'
        else: return 'Low'

    final_day['predicted_risk_band'] = final_day['predicted_pct'].apply(get_risk_band)

    # Upgrade rules
    is_rising = final_day['pred_violations'] > final_day['lag_1_count']
    vh_upgrade = (final_day['hotspot_band'] == 'Very High') & is_rising
    final_day.loc[vh_upgrade, 'predicted_risk_band'] = 'Very High'
    final_day.loc[vh_upgrade, 'predicted_risk_score'] = final_day.loc[vh_upgrade, 'predicted_risk_score'].clip(lower=90.0)
    h_upgrade = (final_day['hotspot_band'] == 'High') & is_rising & final_day['predicted_risk_band'].isin(['Medium', 'Low'])
    final_day.loc[h_upgrade, 'predicted_risk_band'] = 'High'
    final_day.loc[h_upgrade, 'predicted_risk_score'] = final_day.loc[h_upgrade, 'predicted_risk_score'].clip(lower=70.0)

    action_map = {
        'Very High': 'Deploy Towing Vehicle + 3 Officers + Barricade Support',
        'High':      'Deploy 2 Officers + Active Patrol Monitoring',
        'Medium':    'Deploy 1 Officer / Mobile Patrol (Warning & Monitoring)',
        'Low':       'No Dedicated Deployment'
    }
    manpower_map = {'Very High': 3, 'High': 2, 'Medium': 1, 'Low': 0}
    time_window_map = {
        'morning_peak': '08:00 AM - 11:00 AM (Morning Peak Focus)',
        'evening_peak': '05:00 PM - 08:00 PM (Evening Peak Focus)',
        'midday':       '11:00 AM - 05:00 PM (Midday Traffic Focus)',
        'night':        '08:00 PM - 08:00 AM (Night Monitoring Focus)'
    }

    final_day['recommended_action'] = final_day['predicted_risk_band'].map(action_map)
    final_day['manpower_estimate'] = final_day['predicted_risk_band'].map(manpower_map)
    final_day['time_window_to_watch'] = final_day['dominant_time_bucket'].map(time_window_map).fillna('08:00 AM - 08:00 PM')

    recs_df = final_day[[
        'zone_id', 'zone_name', 'top_police_station', 'top_junction', 'top_location',
        'pred_violations', 'predicted_risk_score', 'predicted_risk_band',
        'recommended_action', 'manpower_estimate', 'time_window_to_watch'
    ]].copy()
    recs_df.rename(columns={'pred_violations': 'predicted_next_day_violations'}, inplace=True)
    recs_df = recs_df.sort_values('predicted_risk_score', ascending=False).reset_index(drop=True)
    recs_df.to_csv(RECOMMENDATIONS_PATH, index=False)
    print(f"  Saved to: {RECOMMENDATIONS_PATH} ({len(recs_df)} zones)")

    # ── 1. Feature Importance extraction & CSV export ─────────────────────
    print("\n--- Phase 4.6: Feature Importance Extraction ---")
    importances = {}
    
    # Extract from LightGBM if available
    if "LightGBM" in tuned_models:
        importances["LightGBM"] = tuned_models["LightGBM"].feature_importances_
        # Normalize to sum to 1.0
        importances["LightGBM"] = importances["LightGBM"] / importances["LightGBM"].sum()
        
    # Extract from XGBoost if available
    if "XGBoost" in tuned_models:
        importances["XGBoost"] = tuned_models["XGBoost"].feature_importances_
        importances["XGBoost"] = importances["XGBoost"] / importances["XGBoost"].sum()
        
    # RandomForest Regressor (Train standard RF to get feature importance)
    from sklearn.ensemble import RandomForestRegressor
    print("  Training standard RandomForestRegressor for feature importances...")
    rf_temp = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    rf_temp.fit(X_train, y_train)
    importances["Random Forest"] = rf_temp.feature_importances_
    importances["Random Forest"] = importances["Random Forest"] / importances["Random Forest"].sum()
    
    # Save Feature Importance to CSV
    feat_imp_df = pd.DataFrame({'Feature': FEATURE_COLS})
    for m_name, imp_vals in importances.items():
        feat_imp_df[m_name] = imp_vals
        
    feat_imp_df['Average'] = feat_imp_df[list(importances.keys())].mean(axis=1)
    feat_imp_df = feat_imp_df.sort_values('Average', ascending=False).reset_index(drop=True)
    
    FEAT_IMP_PATH = os.path.join(DATASET_DIR, "feature_importance.csv")
    feat_imp_df.to_csv(FEAT_IMP_PATH, index=False)
    print(f"  Saved Feature Importances to: {FEAT_IMP_PATH}")
    print("\nTop 5 Most Important Features (Across Models):")
    print(feat_imp_df[['Feature', 'Average']].head(5).to_string(index=False))

    # ── 2. SHAP Explainability ─────────────────────────────────────────────
    try:
        import shap
        import matplotlib.pyplot as plt
        print("\n--- Phase 4.7: Running SHAP TreeExplainer on LightGBM ---")
        
        explain_model_name = "LightGBM" if "LightGBM" in tuned_models else ("XGBoost" if "XGBoost" in tuned_models else None)
        if explain_model_name:
            explainer = shap.TreeExplainer(tuned_models[explain_model_name])
            
            # Use 500 random training samples for explanation speed
            rng = np.random.default_rng(42)
            shap_sample_idx = rng.choice(len(X_train), size=min(500, len(X_train)), replace=False)
            shap_sample_X = X_train[shap_sample_idx]
            
            shap_values = explainer(shap_sample_X)
            
            plt.figure(figsize=(10, 6))
            shap.summary_plot(shap_values, shap_sample_X, feature_names=FEATURE_COLS, show=False)
            plt.title(f"SHAP Summary Plot ({explain_model_name})", fontsize=14)
            plt.tight_layout()
            
            SHAP_PLOT_PATH = os.path.join(DATASET_DIR, "shap_summary.png")
            plt.savefig(SHAP_PLOT_PATH, dpi=150)
            plt.close()
            print(f"  Saved SHAP Summary Plot to: {SHAP_PLOT_PATH}")
        else:
            print("  No suitable model (LightGBM/XGBoost) found for SHAP.")
    except Exception as e:
        print(f"  SHAP explainability skipped or failed: {e}")

    # ── 3. Error Analysis ──────────────────────────────────────────────────
    print("\n--- Phase 4.8: Running Error Analysis ---")
    test_df_analysis = test_df.copy()
    test_df_analysis['predicted'] = test_pred
    
    # Aggregate test-set actuals & predictions per zone
    error_analysis = test_df_analysis.groupby(['zone_id', 'zone_name']).agg(
        actual=('next_day_violation_count', 'mean'),
        predicted=('predicted', 'mean')
    ).reset_index()
    
    error_analysis['error'] = error_analysis['predicted'] - error_analysis['actual']
    error_analysis['absolute_error'] = np.abs(error_analysis['error'])
    
    # Save error analysis CSV
    ERROR_ANALYSIS_PATH = os.path.join(DATASET_DIR, "prediction_error_analysis.csv")
    error_analysis[['zone_id', 'actual', 'predicted', 'error', 'absolute_error']].to_csv(ERROR_ANALYSIS_PATH, index=False)
    print(f"  Saved Error Analysis to: {ERROR_ANALYSIS_PATH}")
    
    # Sort by absolute error to find best/worst predicted zones
    sorted_err = error_analysis.sort_values('absolute_error')
    
    print("\nTop 5 Best Predicted Zones (Lowest Absolute Error):")
    print(sorted_err[['zone_id', 'zone_name', 'actual', 'predicted', 'absolute_error']].head(5).to_string(index=False))
    
    print("\nTop 5 Worst Predicted Zones (Highest Absolute Error):")
    print(sorted_err[['zone_id', 'zone_name', 'actual', 'predicted', 'absolute_error']].tail(5).to_string(index=False))

    # ── Side-by-side comparison ──────────────────────────────────────────
    print("\n" + "=" * 70)
    print("NEW TOP 10 DEPLOYMENT RECOMMENDATIONS (2024-04-09)")
    print("=" * 70)
    print(recs_df[['zone_id', 'zone_name', 'predicted_next_day_violations',
                   'predicted_risk_score', 'predicted_risk_band', 'manpower_estimate']].head(10).to_string(index=False))

    if old_recs is not None:
        print("\n" + "=" * 70)
        print("OLD TOP 10 (Before Enhancement)")
        print("=" * 70)
        print(old_recs[['zone_id', 'zone_name', 'predicted_next_day_violations',
                        'predicted_risk_score', 'predicted_risk_band', 'manpower_estimate']].head(10).to_string(index=False))

    print(f"\nTotal export time: {time.time() - t_global:.1f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
