import os
import re
import time
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

# Paths — resolved relative to this script's location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
INPUT_PATH = os.path.join(DATASET_DIR, "ps1_enhanced_step1_step2.csv")
OUTPUT_DIR = DATASET_DIR
ZONES_PATH = os.path.join(OUTPUT_DIR, "hotspot_zones.csv")
RANKING_PATH = os.path.join(OUTPUT_DIR, "location_ranking.csv")
MAP_DATA_PATH = os.path.join(OUTPUT_DIR, "hotspot_map_data.csv")
SUMMARY_PATH = os.path.join(OUTPUT_DIR, "hotspot_summary_report.csv")

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Computes the great-circle distance between two points in meters 
    using the Haversine formula.
    """
    R = 6371000.0  # Earth radius in meters
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return R * c

def main():
    print("=================================================================")
    print("STEP 3: HOTSPOT DETECTION AND LOCATION-LEVEL AGGREGATION")
    print("=================================================================")
    
    # -------------------------------------------------------------
    # 0. Load Dataset
    # -------------------------------------------------------------
    t_start = time.time()
    print(f"Loading dataset from: {INPUT_PATH} ...")
    if not os.path.exists(INPUT_PATH):
        raise FileNotFoundError(f"Input file not found: {INPUT_PATH}")
    
    df = pd.read_csv(INPUT_PATH)
    print(f"Successfully loaded {len(df):,} records in {time.time() - t_start:.2f} seconds.")
    
    # -------------------------------------------------------------
    # 1. Spatial Clustering (DBSCAN on Unique Coordinates using Haversine)
    # -------------------------------------------------------------
    print("\n--- Phase 1: Spatial Clustering (DBSCAN with Haversine) ---")
    t0 = time.time()
    
    # Group by unique coordinates to speed up clustering
    coord_groups = df.groupby(['latitude', 'longitude']).size().reset_index(name='record_count')
    print(f"Found {len(coord_groups):,} unique lat/lon coordinate points.")
    
    # Convert unique coordinates to radians for DBSCAN's haversine metric
    # Note: sklearn's haversine expects coordinates as [latitude, longitude] in radians
    coords_rad = np.radians(coord_groups[['latitude', 'longitude']].values)
    
    # Run DBSCAN (Epsilon = 100 meters, Min Samples = 10 violations)
    # Epsilon in radians = distance_in_meters / Earth_radius_in_meters
    earth_radius_m = 6371000.0
    eps_m = 100
    eps_rad = eps_m / earth_radius_m
    min_samples = 10
    print(f"Fitting DBSCAN with eps={eps_m} meters ({eps_rad:.8f} radians), min_samples={min_samples} violations (haversine metric)...")
    
    db = DBSCAN(eps=eps_rad, min_samples=min_samples, metric='haversine', algorithm='ball_tree', n_jobs=-1)
    labels = db.fit_predict(coords_rad, sample_weight=coord_groups['record_count'].values)
    
    coord_groups['dbscan_label'] = labels
    
    # Map back labels to the main dataset
    df = df.merge(coord_groups[['latitude', 'longitude', 'dbscan_label']], on=['latitude', 'longitude'], how='left')
    
    # Check cluster counts and sort clusters by size
    cluster_counts = df[df['dbscan_label'] != -1].groupby('dbscan_label').size().reset_index(name='count')
    cluster_counts = cluster_counts.sort_values(by='count', ascending=False).reset_index(drop=True)
    
    n_clusters = len(cluster_counts)
    n_noise = (df['dbscan_label'] == -1).sum()
    print(f"DBSCAN clustering complete in {time.time() - t0:.2f} seconds.")
    print(f"Detected {n_clusters} distinct clusters.")
    print(f"Noise points: {n_noise:,} ({n_noise/len(df)*100:.2f}% of total violations).")
    
    # Map raw labels to formatted zone_id sorted by total violation counts
    label_to_zone_id = {row['dbscan_label']: f"ZONE_{i+1:03d}" for i, row in cluster_counts.iterrows()}
    label_to_zone_id[-1] = "ZONE_NOISE"
    
    df['zone_id'] = df['dbscan_label'].map(label_to_zone_id)
    
    # -------------------------------------------------------------
    # 2. Recency Weights Calculation
    # -------------------------------------------------------------
    print("\n--- Calculating Recency Weights ---")
    # Exponential decay with 30 days half-life: lambda = ln(2)/30 = 0.0231
    max_days = df['days_since_start'].max()
    df['recency_weight'] = np.exp(-0.0231 * (max_days - df['days_since_start']))
    print(f"Max days_since_start: {max_days:.2f}. Recency decay applied (30-day half-life).")
    
    # -------------------------------------------------------------
    # 3. Zone-level Aggregation (DBSCAN Clusters)
    # -------------------------------------------------------------
    print("\n--- Phase 2 & 3: Zone-level Aggregations & Scoring ---")
    t0 = time.time()
    
    # Filter out noise for zone-level aggregation table
    df_zones_only = df[df['zone_id'] != "ZONE_NOISE"]
    
    # Aggregate helper functions
    def get_mode_or_fallback(series, fallback="Unknown"):
        modes = series.mode()
        if not modes.empty:
            return str(modes.iloc[0])
        return fallback

    def get_mode_excluding(series, exclude_val, fallback="Unknown"):
        filtered = series[series != exclude_val]
        if not filtered.empty:
            modes = filtered.mode()
            if not modes.empty:
                return str(modes.iloc[0])
        return fallback

    # We will build a list of dictionaries, one per zone_id
    zone_records = []
    
    grouped = df_zones_only.groupby('zone_id')
    for zone_id, group in grouped:
        # Geographic coordinates bounds and spread
        centroid_lat = group['latitude'].mean()
        centroid_lon = group['longitude'].mean()
        lat_std = group['latitude'].std() if len(group) > 1 else 0.0
        lon_std = group['longitude'].std() if len(group) > 1 else 0.0
        
        # Area in sq meters (using bounding box via haversine)
        min_z_lat, max_z_lat = group['latitude'].min(), group['latitude'].max()
        min_z_lon, max_z_lon = group['longitude'].min(), group['longitude'].max()
        width_m = haversine_distance(centroid_lat, min_z_lon, centroid_lat, max_z_lon)
        height_m = haversine_distance(min_z_lat, centroid_lon, max_z_lat, centroid_lon)
        area_m2 = max(width_m * height_m, 100.0) # minimum 100 sq meters cap
        
        # Volume metrics
        total_violations = len(group)
        parking_related_violations = group['parking_related_violation_count'].sum()
        non_parking_violations = group['non_parking_violation_count'].sum()
        violation_density = total_violations / area_m2
        
        # Temporal metrics
        peak_hour_violations = group['is_peak_hour'].sum()
        morning_peak_violations = group['is_morning_peak'].sum()
        evening_peak_violations = group['is_evening_peak'].sum()
        weekend_violations = group['is_weekend'].sum()
        weekday_violations = (1 - group['is_weekend']).sum()
        night_violations = (group['time_bucket'] == 'night').sum()
        
        # Diversity metrics
        unique_violation_types = group['primary_violation'].nunique()
        unique_vehicle_classes = group['vehicle_class'].nunique()
        unique_locations = group['location_clean'].nunique()
        unique_junctions = group['junction_name_clean'].nunique()
        
        # Recency Weight Sum
        recency_weight_sum = group['recency_weight'].sum()
        
        # Administrative summary
        top_police_station = get_mode_or_fallback(group['police_station_clean'], "Unknown Station")
        top_junction = get_mode_excluding(group['junction_name_clean'], "No Junction", "No Junction")
        top_location = get_mode_or_fallback(group['location_clean'], "Unknown Street")
        top_loc_seg = get_mode_or_fallback(group['location_first_segment'], "Unknown Street")
        
        # Time-pattern summaries
        dominant_hour = int(group['created_hour_ist'].mode().iloc[0]) if not group['created_hour_ist'].mode().empty else 12
        dominant_time_bucket = get_mode_or_fallback(group['time_bucket'], "midday")
        dominant_day_name = get_mode_or_fallback(group['created_day_name'], "Monday")
        peak_share = peak_hour_violations / total_violations if total_violations > 0 else 0.0
        
        # Persistence metrics (Monthly counts)
        # Standardize months
        months_lower = group['created_month_name'].str.lower()
        violations_nov = (months_lower == 'november').sum()
        violations_dec = (months_lower == 'december').sum()
        violations_jan = (months_lower == 'january').sum()
        violations_feb = (months_lower == 'february').sum()
        violations_mar = (months_lower == 'march').sum()
        violations_apr = (months_lower == 'april').sum()
        
        # MoM trend calculation
        # Monthly counts sequence: Nov, Dec, Jan, Feb, Mar, Apr
        monthly_counts = np.array([violations_nov, violations_dec, violations_jan, violations_feb, violations_mar, violations_apr])
        x_months = np.array([1, 2, 3, 4, 5, 6])
        slope, _ = np.polyfit(x_months, monthly_counts, 1)
        # Normalize the slope to make it a growth rate relative to average monthly violations
        avg_monthly = total_violations / 6.0
        month_over_month_trend = slope / avg_monthly if avg_monthly > 0 else 0.0
        
        # Recurring hotspot flag (active in at least 3 months AND total violations >= 15)
        active_months = sum([1 for count in monthly_counts if count > 0])
        recurring_hotspot_flag = 1 if (active_months >= 3 and total_violations >= 15) else 0
        
        # Build human-readable zone name
        # Clean junction name BTP prefix
        cleaned_junction = top_junction
        if top_junction != "No Junction":
            cleaned_junction = re.sub(r'^BTP\d+\s*-\s*', '', top_junction)
            cleaned_junction = re.sub(r'\s+Junction$', '', cleaned_junction)
        
        if top_junction != "No Junction":
            if top_loc_seg.lower() in cleaned_junction.lower():
                zone_name = f"{cleaned_junction} / {top_police_station} Zone"
            else:
                zone_name = f"{top_loc_seg} / {cleaned_junction} Zone"
        else:
            zone_name = f"{top_loc_seg} / {top_police_station} Zone"
            
        record = {
            'zone_id': zone_id,
            'zone_name': zone_name,
            'centroid_lat': centroid_lat,
            'centroid_lon': centroid_lon,
            'lat_std': lat_std,
            'lon_std': lon_std,
            'total_violations': total_violations,
            'parking_related_violations': parking_related_violations,
            'non_parking_violations': non_parking_violations,
            'violation_density': violation_density,
            'peak_hour_violations': peak_hour_violations,
            'morning_peak_violations': morning_peak_violations,
            'evening_peak_violations': evening_peak_violations,
            'weekend_violations': weekend_violations,
            'weekday_violations': weekday_violations,
            'night_violations': night_violations,
            'unique_violation_types': unique_violation_types,
            'unique_vehicle_classes': unique_vehicle_classes,
            'unique_locations': unique_locations,
            'unique_junctions': unique_junctions,
            'recency_weight_sum': recency_weight_sum,
            'top_police_station': top_police_station,
            'top_junction': top_junction,
            'top_location': top_location,
            'dominant_hour': dominant_hour,
            'dominant_time_bucket': dominant_time_bucket,
            'dominant_day_name': dominant_day_name,
            'peak_share': peak_share,
            'violations_nov': violations_nov,
            'violations_dec': violations_dec,
            'violations_jan': violations_jan,
            'violations_feb': violations_feb,
            'violations_mar': violations_mar,
            'violations_apr': violations_apr,
            'month_over_month_trend': month_over_month_trend,
            'recurring_hotspot_flag': recurring_hotspot_flag
        }
        zone_records.append(record)
        
    zones_df = pd.DataFrame(zone_records)
    
    # -------------------------------------------------------------
    # 4. Hotspot Score & Banding (DBSCAN Clusters)
    # -------------------------------------------------------------
    # Helper to log-transform and min-max normalize a column
    def normalize_col_log(col):
        log_col = np.log1p(col)
        c_min, c_max = log_col.min(), log_col.max()
        if c_max == c_min:
            return np.zeros_like(log_col)
        return (log_col - c_min) / (c_max - c_min)
        
    zones_df['norm_total'] = normalize_col_log(zones_df['total_violations'])
    zones_df['norm_parking'] = normalize_col_log(zones_df['parking_related_violations'])
    zones_df['norm_peak'] = normalize_col_log(zones_df['peak_hour_violations'])
    zones_df['norm_recency'] = normalize_col_log(zones_df['recency_weight_sum'])
    zones_df['norm_diversity'] = normalize_col_log(zones_df['unique_locations']) # location diversity
    
    # Compute score out of 100
    zones_df['hotspot_score'] = (
        0.35 * zones_df['norm_total'] +
        0.25 * zones_df['norm_parking'] +
        0.20 * zones_df['norm_peak'] +
        0.10 * zones_df['norm_recency'] +
        0.10 * zones_df['norm_diversity']
    ) * 100
    
    # Round metrics for readability
    zones_df['hotspot_score'] = zones_df['hotspot_score'].round(2)
    zones_df['violation_density'] = zones_df['violation_density'].round(6)
    zones_df['month_over_month_trend'] = zones_df['month_over_month_trend'].round(4)
    zones_df['peak_share'] = zones_df['peak_share'].round(4)
    
    # Sort zones by hotspot score
    zones_df = zones_df.sort_values(by='hotspot_score', ascending=False).reset_index(drop=True)
    
    # Assign severity bands based on score ranking
    # top 10% = Very High, next 20% = High, next 30% = Medium, rest = Low
    n_zones = len(zones_df)
    
    def get_band(idx):
        percentile = idx / n_zones
        if percentile <= 0.10:
            return "Very High"
        elif percentile <= 0.30:
            return "High"
        elif percentile <= 0.60:
            return "Medium"
        else:
            return "Low"
            
    zones_df['hotspot_band'] = [get_band(i) for i in range(len(zones_df))]
    
    # Drop intermediate normalization columns
    norm_cols = ['norm_total', 'norm_parking', 'norm_peak', 'norm_recency', 'norm_diversity']
    zones_df = zones_df.drop(columns=norm_cols)
    
    print(f"Computed hotspot scores and bands for {len(zones_df)} zones in {time.time() - t0:.2f} seconds.")
    print("Severity band distribution:")
    print(zones_df['hotspot_band'].value_counts())
    
    # -------------------------------------------------------------
    # 5. Entity-Level Rankings (Police Stations, Junctions, Streets)
    # -------------------------------------------------------------
    print("\n--- Phase 4: Constructing Entity-Level Rankings ---")
    t0 = time.time()
    
    # Helper function to compute rankings for a group
    def create_entity_ranking(groupby_col, entity_type_name, name_cleaner_fn=None):
        grouped = df.groupby(groupby_col)
        entity_records = []
        for name, group in grouped:
            if pd.isnull(name) or str(name).strip() == "" or str(name).lower() in ['unknown', 'no junction']:
                continue
                
            total_violations = len(group)
            parking_related_violations = group['parking_related_violation_count'].sum()
            peak_hour_violations = group['is_peak_hour'].sum()
            recency_weight_sum = group['recency_weight'].sum()
            location_diversity = group['location_clean'].nunique()
            
            clean_name = name_cleaner_fn(name) if name_cleaner_fn else name
            
            entity_records.append({
                'entity_type': entity_type_name,
                'entity_name': clean_name,
                'total_violations': total_violations,
                'parking_related_violations': parking_related_violations,
                'peak_hour_violations': peak_hour_violations,
                'recency_weight_sum': recency_weight_sum,
                'location_diversity': location_diversity
            })
            
        ent_df = pd.DataFrame(entity_records)
        if ent_df.empty:
            return ent_df
            
        # Normalize and Score using Log scaling
        ent_df['norm_total'] = normalize_col_log(ent_df['total_violations'])
        ent_df['norm_parking'] = normalize_col_log(ent_df['parking_related_violations'])
        ent_df['norm_peak'] = normalize_col_log(ent_df['peak_hour_violations'])
        ent_df['norm_recency'] = normalize_col_log(ent_df['recency_weight_sum'])
        ent_df['norm_diversity'] = normalize_col_log(ent_df['location_diversity'])
        
        ent_df['hotspot_score'] = (
            0.35 * ent_df['norm_total'] +
            0.25 * ent_df['norm_parking'] +
            0.20 * ent_df['norm_peak'] +
            0.10 * ent_df['norm_recency'] +
            0.10 * ent_df['norm_diversity']
        ) * 100
        
        ent_df['hotspot_score'] = ent_df['hotspot_score'].round(2)
        ent_df = ent_df.sort_values(by='hotspot_score', ascending=False).reset_index(drop=True)
        ent_df['entity_rank'] = ent_df.index + 1
        
        # Drop norm columns
        ent_df = ent_df.drop(columns=['norm_total', 'norm_parking', 'norm_peak', 'norm_recency', 'norm_diversity'])
        return ent_df

    def clean_junc_name(name):
        c_name = re.sub(r'^BTP\d+\s*-\s*', '', str(name))
        return re.sub(r'\s+Junction$', '', c_name)

    print("Ranking Police Stations...")
    ps_ranking = create_entity_ranking('police_station_clean', 'Police Station')
    print("Ranking Junctions...")
    junc_ranking = create_entity_ranking('junction_name_clean', 'Junction', name_cleaner_fn=clean_junc_name)
    print("Ranking Streets...")
    street_ranking = create_entity_ranking('location_first_segment', 'Street/Location')
    
    # Combine rankings
    combined_rankings = pd.concat([ps_ranking, junc_ranking, street_ranking], ignore_index=True)
    
    # Sort combined rankings by hotspot score descending to build a true leaderboard
    combined_rankings = combined_rankings.sort_values(by='hotspot_score', ascending=False).reset_index(drop=True)
    combined_rankings['global_rank'] = combined_rankings.index + 1
    
    # Re-order columns for presentation
    ranking_cols = [
        'global_rank', 'entity_rank', 'entity_type', 'entity_name', 'hotspot_score',
        'total_violations', 'parking_related_violations', 'peak_hour_violations',
        'recency_weight_sum', 'location_diversity'
    ]
    combined_rankings = combined_rankings[ranking_cols]
    print(f"Combined ranking list contains {len(combined_rankings)} entities in {time.time() - t0:.2f} seconds.")
    
    # -------------------------------------------------------------
    # 6. Fallback Comparison Model: Aggregation by geo_cell_3
    # -------------------------------------------------------------
    print("\n--- Fallback Grid Analysis (geo_cell_3) ---")
    grid_groups = df.groupby('geo_cell_3').size().reset_index(name='count')
    grid_groups = grid_groups.sort_values(by='count', ascending=False).reset_index(drop=True)
    print(f"Rounded Grid (geo_cell_3) contains {len(grid_groups)} cells.")
    print("Top 5 grid cells:")
    print(grid_groups.head(5))
    
    # -------------------------------------------------------------
    # 7. Write Deliverables to Disk
    # -------------------------------------------------------------
    print("\n--- Exporting Deliverables ---")
    
    # Deliverable 1: hotspot_zones.csv
    # Re-order columns for clean presentation
    primary_cols = [
        'zone_id', 'zone_name', 'centroid_lat', 'centroid_lon', 'lat_std', 'lon_std',
        'total_violations', 'parking_related_violations', 'non_parking_violations', 'violation_density',
        'hotspot_score', 'hotspot_band', 'top_police_station', 'top_junction', 'top_location'
    ]
    rest_cols = [c for c in zones_df.columns if c not in primary_cols]
    zones_df = zones_df[primary_cols + rest_cols]
    zones_df.to_csv(ZONES_PATH, index=False)
    print(f"1. Saved Hotspot Zones table to: {ZONES_PATH} (Shape: {zones_df.shape})")
    
    # Deliverable 2: location_ranking.csv
    combined_rankings.to_csv(RANKING_PATH, index=False)
    print(f"2. Saved Combined Location Rankings to: {RANKING_PATH} (Shape: {combined_rankings.shape})")
    
    # Deliverable 3: hotspot_map_data.csv
    map_cols = [
        'zone_id', 'zone_name', 'centroid_lat', 'centroid_lon', 'total_violations', 
        'parking_related_violations', 'hotspot_score', 'hotspot_band', 'top_police_station', 
        'top_location', 'dominant_time_bucket', 'dominant_hour', 'peak_share'
    ]
    map_df = zones_df[map_cols].copy()
    map_df.rename(columns={'centroid_lat': 'latitude', 'centroid_lon': 'longitude'}, inplace=True)
    map_df.to_csv(MAP_DATA_PATH, index=False)
    print(f"3. Saved Map-Ready Hotspot Layer to: {MAP_DATA_PATH} (Shape: {map_df.shape})")
    
    # Deliverable 4: hotspot_summary_report.csv
    summary_stats = [
        {"metric_name": "Total Violations Processed", "metric_value": len(df)},
        {"metric_name": "Clustered Violations (in Zones)", "metric_value": len(df_zones_only)},
        {"metric_name": "Noise Violations (outside Zones)", "metric_value": n_noise},
        {"metric_name": "Noise Violations Percentage", "metric_value": f"{n_noise/len(df)*100:.2f}%"},
        {"metric_name": "Total Geo Clusters (Zones) Detected", "metric_value": n_clusters},
        {"metric_name": "Very High Severity Zones", "metric_value": (zones_df['hotspot_band'] == "Very High").sum()},
        {"metric_name": "High Severity Zones", "metric_value": (zones_df['hotspot_band'] == "High").sum()},
        {"metric_name": "Medium Severity Zones", "metric_value": (zones_df['hotspot_band'] == "Medium").sum()},
        {"metric_name": "Low Severity Zones", "metric_value": (zones_df['hotspot_band'] == "Low").sum()},
        {"metric_name": "Most Common Police Station in Hotspots", "metric_value": get_mode_or_fallback(df_zones_only['police_station_clean'])},
        {"metric_name": "Peak Hour Violations Share in Hotspots", "metric_value": f"{df_zones_only['is_peak_hour'].mean()*100:.2f}%"},
        {"metric_name": "Top Hotspot Zone ID", "metric_value": zones_df.iloc[0]['zone_id']},
        {"metric_name": "Top Hotspot Zone Name", "metric_value": zones_df.iloc[0]['zone_name']},
        {"metric_name": "Top Hotspot Zone Score", "metric_value": zones_df.iloc[0]['hotspot_score']}
    ]
    summary_df = pd.DataFrame(summary_stats)
    summary_df.to_csv(SUMMARY_PATH, index=False)
    print(f"4. Saved Hotspot Summary Report to: {SUMMARY_PATH} (Shape: {summary_df.shape})")
    
    # -------------------------------------------------------------
    # 8. Data Validation
    # -------------------------------------------------------------
    print("\n--- Phase 5: Verification and Diagnostics ---")
    
    # 1. Total row check
    total_in_output = len(df_zones_only) + n_noise
    assert total_in_output == len(df), f"Row count mismatch! Output sum: {total_in_output}, expected: {len(df)}"
    print(f"OK: Verification Passed: Total row counts match exactly (sum of clusters + noise = {total_in_output:,}).")
    
    # 2. Score bounds check
    min_score, max_score = zones_df['hotspot_score'].min(), zones_df['hotspot_score'].max()
    assert 0 <= min_score <= 100 and 0 <= max_score <= 100, f"Score bounds invalid: min={min_score}, max={max_score}"
    print(f"OK: Verification Passed: Hotspot scores are bounded in [0, 100] (Range: {min_score:.2f} - {max_score:.2f}).")
    
    # 3. Top 10 Hotspots display
    print("\nTOP 10 CONGESTION HOTSPOTS (BTP PRIORITIES):")
    print(zones_df[['zone_id', 'zone_name', 'total_violations', 'hotspot_score', 'hotspot_band', 'top_police_station']].head(10).to_string(index=False))
    
    print("\nAll tasks in Step 3 completed successfully!")
    print(f"Total pipeline execution time: {time.time() - t_start:.2f} seconds.")
    print("=================================================================")

if __name__ == "__main__":
    main()
