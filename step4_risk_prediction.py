import os
import re
import time
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

# Paths — resolved relative to this script's location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
INPUT_PATH = os.path.join(DATASET_DIR, "ps1_enhanced_step1_step2.csv")
ZONES_PATH = os.path.join(DATASET_DIR, "hotspot_zones.csv")
DAILY_FEATURES_PATH = os.path.join(DATASET_DIR, "zone_daily_features.csv")
PREDICTIONS_PATH = os.path.join(DATASET_DIR, "step4_predictions.csv")
RECOMMENDATIONS_PATH = os.path.join(DATASET_DIR, "deployment_recommendations.csv")

def main():
    t_start = time.time()
    print("=================================================================")
    print("STEP 4: PREDICTIVE CONGESTION RISK & ENFORCEMENT RECOMMENDATION")
    print("=================================================================")
    
    # -------------------------------------------------------------
    # 1. Load Data
    # -------------------------------------------------------------
    print(f"Loading raw dataset from: {INPUT_PATH} ...")
    if not os.path.exists(INPUT_PATH):
        raise FileNotFoundError(f"Input file not found: {INPUT_PATH}")
    df = pd.read_csv(INPUT_PATH)
    print(f"Successfully loaded {len(df):,} records in {time.time() - t_start:.2f} seconds.")
    
    # -------------------------------------------------------------
    # 2. Re-assign DBSCAN Zones (Matching Step 3 Haversine)
    # -------------------------------------------------------------
    print("\n--- Mapping records to DBSCAN clusters (Haversine) ---")
    t0 = time.time()
    
    # Group by unique coordinates to speed up clustering
    coord_groups = df.groupby(['latitude', 'longitude']).size().reset_index(name='record_count')
    coords_rad = np.radians(coord_groups[['latitude', 'longitude']].values)
    
    earth_radius_m = 6371000.0
    eps_m = 100
    eps_rad = eps_m / earth_radius_m
    min_samples = 10
    
    db = DBSCAN(eps=eps_rad, min_samples=min_samples, metric='haversine', algorithm='ball_tree', n_jobs=-1)
    labels = db.fit_predict(coords_rad, sample_weight=coord_groups['record_count'].values)
    coord_groups['dbscan_label'] = labels
    
    df = df.merge(coord_groups[['latitude', 'longitude', 'dbscan_label']], on=['latitude', 'longitude'], how='left')
    
    cluster_counts = df[df['dbscan_label'] != -1].groupby('dbscan_label').size().reset_index(name='count')
    cluster_counts = cluster_counts.sort_values(by='count', ascending=False).reset_index(drop=True)
    
    label_to_zone_id = {row['dbscan_label']: f"ZONE_{i+1:03d}" for i, row in cluster_counts.iterrows()}
    label_to_zone_id[-1] = "ZONE_NOISE"
    df['zone_id'] = df['dbscan_label'].map(label_to_zone_id)
    
    # Filter out noise for zone-day aggregation
    df_zones = df[df['zone_id'] != "ZONE_NOISE"].copy()
    print(f"Mapped {len(df_zones):,} records to {len(cluster_counts)} zones in {time.time() - t0:.2f} seconds.")
    
    # -------------------------------------------------------------
    # 3. Construct Zone-Day Grid
    # -------------------------------------------------------------
    print("\n--- Phase 4.1: Building Zone-Day Grid ---")
    zones = sorted(df_zones['zone_id'].unique())
    dates = sorted(df['created_date_ist'].unique())
    
    # Generate complete Cartesian product of zones x dates to capture zero-violation days
    grid = pd.MultiIndex.from_product([zones, dates], names=['zone_id', 'created_date_ist']).to_frame().reset_index(drop=True)
    
    # Aggregate daily metrics from row-level data
    daily_agg = df_zones.groupby(['zone_id', 'created_date_ist']).agg(
        daily_violation_count=('id', 'count'),
        daily_parking_violation_count=('parking_related_violation_count', 'sum'),
        daily_peak_hour_count=('is_peak_hour', 'sum')
    ).reset_index()
    
    # Merge and fill NaNs with 0
    grid = grid.merge(daily_agg, on=['zone_id', 'created_date_ist'], how='left')
    grid['daily_violation_count'] = grid['daily_violation_count'].fillna(0).astype(int)
    grid['daily_parking_violation_count'] = grid['daily_parking_violation_count'].fillna(0).astype(int)
    grid['daily_peak_hour_count'] = grid['daily_peak_hour_count'].fillna(0).astype(int)
    
    # Sort chronologically for lag computations
    grid = grid.sort_values(by=['zone_id', 'created_date_ist']).reset_index(drop=True)
    print(f"Zone-Day grid constructed with {len(grid):,} records ({len(zones)} zones x {len(dates)} days).")
    
    # -------------------------------------------------------------
    # 4. Feature Engineering
    # -------------------------------------------------------------
    print("\n--- Phase 4.2: Feature Engineering ---")
    t0 = time.time()
    
    grid['date_dt'] = pd.to_datetime(grid['created_date_ist'])
    
    # Prevent leakage: shift daily counts by 1 day. Features at day T can only see T-1 and earlier.
    grid['prev_day_count'] = grid.groupby('zone_id')['daily_violation_count'].shift(1)
    grid['prev_day_parking'] = grid.groupby('zone_id')['daily_parking_violation_count'].shift(1)
    grid['prev_day_peak'] = grid.groupby('zone_id')['daily_peak_hour_count'].shift(1)
    
    # Lag features
    grid['lag_1_count'] = grid['prev_day_count']
    grid['lag_3_count'] = grid.groupby('zone_id')['daily_violation_count'].shift(3)
    grid['lag_7_count'] = grid.groupby('zone_id')['daily_violation_count'].shift(7)
    grid['lag_14_count'] = grid.groupby('zone_id')['daily_violation_count'].shift(14)
    
    grid['lag_1_parking_count'] = grid['prev_day_parking']
    grid['lag_1_peak_hour_count'] = grid['prev_day_peak']
    
    # Rolling features (applied on shifted values to avoid leakage)
    grid['rolling_7d_sum'] = grid.groupby('zone_id')['prev_day_count'].transform(lambda x: x.rolling(7).sum())
    grid['rolling_7d_mean'] = grid.groupby('zone_id')['prev_day_count'].transform(lambda x: x.rolling(7).mean())
    grid['rolling_14d_sum'] = grid.groupby('zone_id')['prev_day_count'].transform(lambda x: x.rolling(14).sum())
    grid['rolling_14d_mean'] = grid.groupby('zone_id')['prev_day_count'].transform(lambda x: x.rolling(14).mean())
    
    grid['rolling_7d_parking_sum'] = grid.groupby('zone_id')['prev_day_parking'].transform(lambda x: x.rolling(7).sum())
    grid['rolling_7d_peak_hour_sum'] = grid.groupby('zone_id')['prev_day_peak'].transform(lambda x: x.rolling(7).sum())
    
    # Trend feature: days_since_last_violation
    def calc_days_since_last(counts):
        n = len(counts)
        days_since = np.zeros(n)
        last_idx = -9999
        for i in range(n):
            if i > 0 and counts.iloc[i-1] > 0:
                last_idx = i - 1
            if last_idx == -9999:
                days_since[i] = 90  # Default to 90 days for no prior violations
            else:
                days_since[i] = i - last_idx
        return pd.Series(days_since, index=counts.index)
        
    grid['days_since_last_violation'] = grid.groupby('zone_id')['daily_violation_count'].transform(calc_days_since_last)
    
    # Trend features: growth rates
    prev_rolling_7d = grid.groupby('zone_id')['rolling_7d_mean'].shift(7)
    grid['count_growth_rate_7d'] = (grid['rolling_7d_mean'] - prev_rolling_7d) / (prev_rolling_7d + 1e-5)
    
    prev_rolling_14d = grid.groupby('zone_id')['rolling_14d_mean'].shift(14)
    grid['count_growth_rate_14d'] = (grid['rolling_14d_mean'] - prev_rolling_14d) / (prev_rolling_14d + 1e-5)
    
    # Daily temporal features of prediction day T
    grid['day_of_week'] = grid['date_dt'].dt.dayofweek
    grid['is_weekend'] = grid['day_of_week'].isin([5, 6]).astype(int)
    grid['month'] = grid['date_dt'].dt.month
    grid['week_of_month'] = (grid['date_dt'].dt.day - 1) // 7 + 1
    grid['is_peak_season'] = grid['month'].isin([11, 12, 1]).astype(int)
    
    # Merge Static Zone Features from Step 3
    if not os.path.exists(ZONES_PATH):
        raise FileNotFoundError(f"Step 3 hotspot zones file not found: {ZONES_PATH}. Run Step 3 pipeline first.")
    
    static_df = pd.read_csv(ZONES_PATH)[[
        'zone_id', 'zone_name', 'centroid_lat', 'centroid_lon', 'lat_std', 'lon_std',
        'violation_density', 'unique_violation_types', 'unique_vehicle_classes',
        'unique_locations', 'unique_junctions', 'recurring_hotspot_flag',
        'month_over_month_trend', 'peak_share', 'hotspot_band', 'top_police_station',
        'top_junction', 'top_location', 'dominant_time_bucket'
    ]]
    grid = grid.merge(static_df, on='zone_id', how='left')
    
    # Map hotspot_band to numeric category
    band_map = {'Very High': 4, 'High': 3, 'Medium': 2, 'Low': 1}
    grid['hotspot_band_num'] = grid['hotspot_band'].map(band_map).fillna(1).astype(int)
    
    # Target: next-day violation count (shifted by -1)
    grid['next_day_violation_count'] = grid.groupby('zone_id')['daily_violation_count'].shift(-1)
    
    # Export full engineered table (retains the final prediction day where next_day_violation_count is NaN)
    export_df = grid.drop(columns=['date_dt'])
    export_df.to_csv(DAILY_FEATURES_PATH, index=False)
    print(f"Saved complete daily features table to: {DAILY_FEATURES_PATH} (Shape: {export_df.shape})")
    
    # Prepare modeling dataset by dropping lag boundaries & target NaN row (last day)
    modeling_df = grid.dropna(subset=[
        'next_day_violation_count', 'lag_14_count', 'rolling_14d_mean', 
        'count_growth_rate_14d', 'days_since_last_violation'
    ]).copy()
    print(f"Modeling dataset prepared with {len(modeling_df):,} rows in {time.time() - t0:.2f} seconds.")
    
    # -------------------------------------------------------------
    # 5. Time-Based Train/Val/Test Split
    # -------------------------------------------------------------
    print("\n--- Phase 4.3: Splitting Data Chronologically ---")
    unique_dates = sorted(modeling_df['created_date_ist'].unique())
    n_dates = len(unique_dates)
    train_cutoff = int(n_dates * 0.75)
    val_cutoff = int(n_dates * 0.875)
    
    train_dates = unique_dates[:train_cutoff]
    val_dates = unique_dates[train_cutoff:val_cutoff]
    test_dates = unique_dates[val_cutoff:]
    
    train_df = modeling_df[modeling_df['created_date_ist'].isin(train_dates)].copy()
    val_df = modeling_df[modeling_df['created_date_ist'].isin(val_dates)].copy()
    test_df = modeling_df[modeling_df['created_date_ist'].isin(test_dates)].copy()
    
    print(f"  Train Set: {len(train_df):,} rows ({len(train_dates)} dates: {train_dates[0]} to {train_dates[-1]})")
    print(f"  Val Set:   {len(val_df):,} rows ({len(val_dates)} dates: {val_dates[0]} to {val_dates[-1]})")
    print(f"  Test Set:  {len(test_df):,} rows ({len(test_dates)} dates: {test_dates[0]} to {test_dates[-1]})")
    
    # -------------------------------------------------------------
    # 6. Model Training & Evaluation
    # -------------------------------------------------------------
    feature_cols = [
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
    target_col = 'next_day_violation_count'
    
    X_train, y_train = train_df[feature_cols], train_df[target_col]
    X_val, y_val = val_df[feature_cols], val_df[target_col]
    X_test, y_test = test_df[feature_cols], test_df[target_col]
    
    # Evaluation metrics helper
    def evaluate_predictions(y_true, y_pred):
        mae = mean_absolute_error(y_true, y_pred)
        rmse = np.sqrt(mean_squared_error(y_true, y_pred))
        return mae, rmse

    # Precision@K helper
    def compute_precision_at_k(y_true, y_pred, k=10):
        top_true_idx = set(np.argsort(y_true)[-k:])
        top_pred_idx = set(np.argsort(y_pred)[-k:])
        overlap = len(top_true_idx.intersection(top_pred_idx))
        return overlap / k

    # Daily mean Precision@K helper
    def compute_daily_precision_at_k(df_subset, pred_col, target_col, k=10):
        precisions = []
        grouped = df_subset.groupby('created_date_ist')
        for date, group in grouped:
            if len(group) < k:
                continue
            y_t = group[target_col].values
            y_p = group[pred_col].values
            if y_t.max() == 0:
                continue
            prec = compute_precision_at_k(y_t, y_p, k)
            precisions.append(prec)
        return np.mean(precisions) if precisions else 0.0

    # Phase 4.4: Evaluate Baseline Model (Persistence: tomorrow = yesterday)
    val_df['baseline_pred'] = val_df['lag_1_count']
    test_df['baseline_pred'] = test_df['lag_1_count']
    
    val_mae_base, val_rmse_base = evaluate_predictions(y_val, val_df['baseline_pred'])
    val_p10_base = compute_daily_precision_at_k(val_df, 'baseline_pred', target_col, k=10)
    
    test_mae_base, test_rmse_base = evaluate_predictions(y_test, test_df['baseline_pred'])
    test_p10_base = compute_daily_precision_at_k(test_df, 'baseline_pred', target_col, k=10)
    
    print("\n--- Phase 4.4: Evaluating Baseline Model (Persistence) ---")
    print(f"  Validation -> MAE: {val_mae_base:.3f}, RMSE: {val_rmse_base:.3f}, Daily Precision@10: {val_p10_base*100:.1f}%")
    print(f"  Test Set   -> MAE: {test_mae_base:.3f}, RMSE: {test_rmse_base:.3f}, Daily Precision@10: {test_p10_base*100:.1f}%")
    
    # Phase 4.5: Train RandomForest Regressor
    print("\n--- Phase 4.5: Training RandomForest Regressor ---")
    rf = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    rf.fit(X_train, y_train)
    
    val_df['rf_pred'] = rf.predict(X_val)
    test_df['rf_pred'] = rf.predict(X_test)
    
    val_mae_rf, val_rmse_rf = evaluate_predictions(y_val, val_df['rf_pred'])
    val_p10_rf = compute_daily_precision_at_k(val_df, 'rf_pred', target_col, k=10)
    
    test_mae_rf, test_rmse_rf = evaluate_predictions(y_test, test_df['rf_pred'])
    test_p10_rf = compute_daily_precision_at_k(test_df, 'rf_pred', target_col, k=10)
    
    print(f"  Validation -> MAE: {val_mae_rf:.3f}, RMSE: {val_rmse_rf:.3f}, Daily Precision@10: {val_p10_rf*100:.1f}%")
    print(f"  Test Set   -> MAE: {test_mae_rf:.3f}, RMSE: {test_rmse_rf:.3f}, Daily Precision@10: {test_p10_rf*100:.1f}%")
    
    # Phase 4.5: Train HistGradientBoosting Regressor (Final Model)
    print("\nTraining HistGradientBoosting Regressor (Final Model)...")
    hgb = HistGradientBoostingRegressor(random_state=42)
    hgb.fit(X_train, y_train)
    
    val_df['hgb_pred'] = hgb.predict(X_val)
    test_df['hgb_pred'] = hgb.predict(X_test)
    
    val_mae_hgb, val_rmse_hgb = evaluate_predictions(y_val, val_df['hgb_pred'])
    val_p10_hgb = compute_daily_precision_at_k(val_df, 'hgb_pred', target_col, k=10)
    
    test_mae_hgb, test_rmse_hgb = evaluate_predictions(y_test, test_df['hgb_pred'])
    test_p10_hgb = compute_daily_precision_at_k(test_df, 'hgb_pred', target_col, k=10)
    
    print(f"  Validation -> MAE: {val_mae_hgb:.3f}, RMSE: {val_rmse_hgb:.3f}, Daily Precision@10: {val_p10_hgb*100:.1f}%")
    print(f"  Test Set   -> MAE: {test_mae_hgb:.3f}, RMSE: {test_rmse_hgb:.3f}, Daily Precision@10: {test_p10_hgb*100:.1f}%")
    
    # Export model performance metrics
    eval_records = [
        {
            'split': 'Validation',
            'baseline_mae': val_mae_base, 'baseline_rmse': val_rmse_base, 'baseline_p10': val_p10_base,
            'rf_mae': val_mae_rf, 'rf_rmse': val_rmse_rf, 'rf_p10': val_p10_rf,
            'hgb_mae': val_mae_hgb, 'hgb_rmse': val_rmse_hgb, 'hgb_p10': val_p10_hgb
        },
        {
            'split': 'Test',
            'baseline_mae': test_mae_base, 'baseline_rmse': test_rmse_base, 'baseline_p10': test_p10_base,
            'rf_mae': test_mae_rf, 'rf_rmse': test_rmse_rf, 'rf_p10': test_p10_rf,
            'hgb_mae': test_mae_hgb, 'hgb_rmse': test_rmse_hgb, 'hgb_p10': test_p10_hgb
        }
    ]
    eval_df = pd.DataFrame(eval_records)
    eval_df.to_csv(PREDICTIONS_PATH, index=False)
    print(f"\nSaved model evaluation metrics to: {PREDICTIONS_PATH}")
    
    # -------------------------------------------------------------
    # 7. Phase 4.6: Enforcement Recommendation Engine
    # -------------------------------------------------------------
    print("\n--- Phase 4.6: Generating Recommendations for 2024-04-09 ---")
    
    # Extract features for the final date (2024-04-08) to forecast deployment for 2024-04-09
    final_day = grid[grid['created_date_ist'] == '2024-04-08'].copy()
    
    # Predict next day violations
    final_day['pred_violations'] = hgb.predict(final_day[feature_cols])
    final_day['pred_violations'] = np.clip(final_day['pred_violations'], 0, None).round(2)
    
    # Compute percentile-based risk score (0-100)
    final_day['predicted_pct'] = final_day['pred_violations'].rank(pct=True)
    final_day['predicted_risk_score'] = (final_day['predicted_pct'] * 100).round(1)
    
    # Assign default risk band based on predicted percentile
    def get_risk_band(pct):
        if pct >= 0.90:
            return 'Very High'
        elif pct >= 0.70:
            return 'High'
        elif pct >= 0.40:
            return 'Medium'
        else:
            return 'Low'
            
    final_day['predicted_risk_band'] = final_day['predicted_pct'].apply(get_risk_band)
    
    # Apply Upgrade Rules
    # Check if forecast is rising (predicted violations > count today)
    is_rising = final_day['pred_violations'] > final_day['lag_1_count']
    
    # Rule 1: Upgrade to 'Very High' if Step 3 band is 'Very High' and forecast is rising
    vh_upgrade = (final_day['hotspot_band'] == 'Very High') & is_rising
    final_day.loc[vh_upgrade, 'predicted_risk_band'] = 'Very High'
    final_day.loc[vh_upgrade, 'predicted_risk_score'] = final_day.loc[vh_upgrade, 'predicted_risk_score'].clip(lower=90.0)
    
    # Rule 2: Upgrade to at least 'High' if Step 3 band is 'High' and forecast is rising
    h_upgrade = (final_day['hotspot_band'] == 'High') & is_rising & final_day['predicted_risk_band'].isin(['Medium', 'Low'])
    final_day.loc[h_upgrade, 'predicted_risk_band'] = 'High'
    final_day.loc[h_upgrade, 'predicted_risk_score'] = final_day.loc[h_upgrade, 'predicted_risk_score'].clip(lower=70.0)
    
    # Define deployment actions and manpower mappings
    action_map = {
        'Very High': 'Deploy Towing Vehicle + 3 Officers + Barricade Support',
        'High': 'Deploy 2 Officers + Active Patrol Monitoring',
        'Medium': 'Deploy 1 Officer / Mobile Patrol (Warning & Monitoring)',
        'Low': 'No Dedicated Deployment'
    }
    
    manpower_map = {
        'Very High': 3,
        'High': 2,
        'Medium': 1,
        'Low': 0
    }
    
    final_day['recommended_action'] = final_day['predicted_risk_band'].map(action_map)
    final_day['manpower_estimate'] = final_day['predicted_risk_band'].map(manpower_map)
    
    # Watch windows mapped from Step 3 dominant time bucket
    time_window_map = {
        'morning_peak': '08:00 AM - 11:00 AM (Morning Peak Focus)',
        'evening_peak': '05:00 PM - 08:00 PM (Evening Peak Focus)',
        'midday': '11:00 AM - 05:00 PM (Midday Traffic Focus)',
        'night': '08:00 PM - 08:00 AM (Night Monitoring Focus)'
    }
    final_day['time_window_to_watch'] = final_day['dominant_time_bucket'].map(time_window_map).fillna('08:00 AM - 08:00 PM')
    
    # Construct deployment recommendations table
    recs_df = final_day[[
        'zone_id', 'zone_name', 'top_police_station', 'top_junction', 'top_location',
        'pred_violations', 'predicted_risk_score', 'predicted_risk_band',
        'recommended_action', 'manpower_estimate', 'time_window_to_watch'
    ]].copy()
    
    recs_df.rename(columns={'pred_violations': 'predicted_next_day_violations'}, inplace=True)
    recs_df = recs_df.sort_values(by='predicted_risk_score', ascending=False).reset_index(drop=True)
    
    recs_df.to_csv(RECOMMENDATIONS_PATH, index=False)
    print(f"Saved Final Deployment Recommendations to: {RECOMMENDATIONS_PATH} (Shape: {recs_df.shape})")
    
    # -------------------------------------------------------------
    # 8. Diagnostics & Print Top 10
    # -------------------------------------------------------------
    print("\nTOP 10 RECOMMENDED ENFORCEMENT ZONES FOR TOMORROW (2024-04-09):")
    print(recs_df[['zone_id', 'zone_name', 'predicted_next_day_violations', 'predicted_risk_score', 'predicted_risk_band', 'manpower_estimate']].head(10).to_string(index=False))
    
    print("\n=================================================================")
    print("All tasks in Step 4 completed successfully!")
    print(f"Total pipeline execution time: {time.time() - t_start:.2f} seconds.")
    print("=================================================================")

if __name__ == "__main__":
    main()
