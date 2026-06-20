"""
Generate Temporal Heatmap Data
===============================
Aggregates the raw violation dataset into a Day-of-Week × Hour-of-Day matrix
for the dashboard's temporal heatmap visualization.

Output: dataset/temporal_heatmap.csv
"""

import os
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
INPUT_PATH = os.path.join(DATASET_DIR, "ps1_enhanced_step1_step2.csv")
OUTPUT_PATH = os.path.join(DATASET_DIR, "temporal_heatmap.csv")

def main():
    print("Loading dataset...")
    df = pd.read_csv(INPUT_PATH, usecols=['created_hour_ist', 'created_day_name', 'created_day_of_week'])
    
    print(f"  {len(df):,} records loaded.")
    
    # Aggregate: count violations per (day_of_week, hour) cell
    heatmap = df.groupby(['created_day_of_week', 'created_day_name', 'created_hour_ist']).size().reset_index(name='violation_count')
    
    # Ensure all 7×24 = 168 cells exist (fill missing with 0)
    day_order = [
        (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'), 
        (3, 'Thursday'), (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday')
    ]
    
    all_cells = []
    for dow, dname in day_order:
        for hour in range(24):
            all_cells.append({'created_day_of_week': dow, 'created_day_name': dname, 'created_hour_ist': hour})
    
    full_grid = pd.DataFrame(all_cells)
    heatmap = full_grid.merge(heatmap, on=['created_day_of_week', 'created_day_name', 'created_hour_ist'], how='left')
    heatmap['violation_count'] = heatmap['violation_count'].fillna(0).astype(int)
    
    # Sort by day_of_week, then hour
    heatmap = heatmap.sort_values(['created_day_of_week', 'created_hour_ist']).reset_index(drop=True)
    
    # Rename columns for clarity
    heatmap = heatmap.rename(columns={
        'created_day_of_week': 'day_of_week',
        'created_day_name': 'day_name',
        'created_hour_ist': 'hour',
    })
    
    heatmap.to_csv(OUTPUT_PATH, index=False)
    print(f"  Saved temporal heatmap ({len(heatmap)} cells) to: {OUTPUT_PATH}")
    
    # Print preview
    pivot = heatmap.pivot(index='day_name', columns='hour', values='violation_count')
    pivot = pivot.reindex(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])
    print("\nHeatmap Preview (violations per day × hour):")
    print(pivot.to_string())

if __name__ == "__main__":
    main()
