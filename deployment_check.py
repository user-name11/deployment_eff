# app.py

# ───────────────────────────────────────────────────────────────────────────────
# Imports & setup
# ───────────────────────────────────────────────────────────────────────────────
import streamlit as st
st.set_page_config(
    page_title="🚀 Deployment → First Ride Dashboard",
    layout="wide"
)
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import altair as alt
import pydeck as pdk


# ───────────────────────────────────────────────────────────────────────────────
# Sidebar: Page selection & file uploads
# ───────────────────────────────────────────────────────────────────────────────
page = st.sidebar.selectbox(
    "Select view",
    ["📊 Dashboard", "⏱️ Time to First Ride", "📍 Deployments with No Ride Map" ]
)

dep_file = st.sidebar.file_uploader("1️⃣ Upload deployments CSV from https://bolt.cloud.looker.com/dashboards/12627", type="csv")
rides_file = st.sidebar.file_uploader("2️⃣ Upload rides CSV from https://bolt.cloud.looker.com/looks/3523", type="csv")
geo_file = st.sidebar.file_uploader("3️⃣ Upload deployment zones (GeoJSON)", type=["geojson","json"])


# Only proceed once deployment zones (GeoJSON) and CSVs are provided
if geo_file and dep_file and rides_file:
    # Read and preprocess deployments
    deps = pd.read_csv(dep_file, parse_dates=["Created Time"])
    deps = deps.query("`Action Type` == 'deploy' and `Action State` == 'completed'")
    deps = deps.reset_index(drop=False).rename(columns={"index": "deploy_idx"})

    # Load and buffer zones
    zones = gpd.read_file(geo_file).to_crs(epsg=3857)
    zones["geometry"] = zones.geometry.buffer(50)
    zones = zones.to_crs(epsg=4326)

    # Spatial join deployments to zones
    deps["geometry"] = deps.apply(
        lambda r: Point(r["Charger Lng"], r["Charger Lat"]), axis=1
    )
    deps_gdf = gpd.GeoDataFrame(deps, geometry="geometry", crs="EPSG:4326")
    deps_with_zone = gpd.sjoin(
        deps_gdf, zones[["name","geometry"]], how="left", predicate="within"
    )

    # Read and merge rides
    rides = pd.read_csv(rides_file, parse_dates=["Created Time"]).rename(
        columns={"Created Time": "ride_time"}
    )
    merged = deps_with_zone.merge(
        rides[["Uuid","ride_time","Vehicle Type Scooter or Bike"]],
        on="Uuid", how="left"
    )
    merged = merged[merged["ride_time"] >= merged["Created Time"]]
    first_rides = merged.sort_values("ride_time").groupby(
        "deploy_idx", as_index=False
    ).first()
    first_rides["time_to_first_ride"] = (
        first_rides["ride_time"] - first_rides["Created Time"]
    )

    # Build result table
    result = first_rides[[
        "Uuid","Created Date","Created Time","ride_time","name",
        "Vehicle Type Scooter or Bike","time_to_first_ride"
    ]].rename(columns={
        "Created Date": "Deployment Date",
        "Created Time": "Deployment Time",
        "ride_time": "First Ride Time",
        "name": "Deployment Spot",
        "Vehicle Type Scooter or Bike": "Vehicle Model",
        "time_to_first_ride": "Time to First Ride"
    })
    result["Time to First Ride Hours"] = (
        result["Time to First Ride"].dt.total_seconds().div(3600)
    )
else:
    st.info("Please upload deployments CSV, rides CSV, and deployment zones GeoJSON.")
    st.stop()

# ───────────────────────────────────────────────────────────────────────────
# Page-specific rendering (after data is loaded into `result` and `deps_with_zone`)
# ───────────────────────────────────────────────────────────────────────────
if page == "⏱️ Time to First Ride":
    st.title("⏱️ Time to First Ride per Deployment")
    st.dataframe(result)
    st.download_button(
        "📥 Download CSV", result.to_csv(index=False).encode("utf-8"),
        file_name="time_to_first_ride.csv", mime="text/csv"
    )

elif page == "📍 Deployments with No Ride Map":
    st.title("📍 Deployments with No Ride Map")
    # (Ensure no_ride is defined: use deps_with_zone & first_rides from above)
    ridden_idxs = set(first_rides["deploy_idx"])
    no_ride = deps_with_zone[~deps_with_zone["deploy_idx"].isin(ridden_idxs)]
    no_ride_df = no_ride.rename(columns={"Charger Lat": "lat", "Charger Lng": "lon"})
    point_layer = pdk.Layer(
        "ScatterplotLayer",
        data=no_ride_df,
        get_position=["lon", "lat"],
        get_fill_color=[255, 165, 0, 200],
        get_radius=50,
        pickable=True
    )
    zone_layer = pdk.Layer(
        "GeoJsonLayer",
        data=zones.__geo_interface__,
        get_fill_color=[0, 0, 200, 255],
        get_line_color=[0, 0, 0, 200],
        pickable=False
    )
    midpoint = (no_ride_df["lat"].mean(), no_ride_df["lon"].mean())
    view_state = pdk.ViewState(
        latitude=midpoint[0], longitude=midpoint[1], zoom=11, pitch=0
    )
    deck = pdk.Deck(
        layers=[zone_layer, point_layer],
        initial_view_state=view_state,
        map_style="mapbox://styles/mapbox/light-v9"
    )
    st.pydeck_chart(deck)

elif page == "📊 Dashboard":
    st.header("Deployment → First Ride Dashboard")
    st.write("")
    st.markdown("---")

    # ────────── KPIs (full dataset) ──────────
    total_deps = len(deps_with_zone)
    no_ride_count = total_deps - len(result)
    avg_ttf_hours = result["Time to First Ride Hours"].mean()
    k1, k2, k3 = st.columns(3)
    k1.metric("Total Deployments", total_deps)
    k2.metric("Deployments with No Ride", no_ride_count)
    k3.metric("Avg Time to First Ride (h)", f"{avg_ttf_hours:.2f}")

    st.markdown("---")

    # ────────── Date Range Filter via Two Calendars ──────────
    # Determine available date range from deployment timestamps
    min_date = deps_with_zone["Created Time"].dt.date.min()
    max_date = deps_with_zone["Created Time"].dt.date.max()

    # Two calendar pickers: start date and end date
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input(
            "Start date",
            value=min_date,
            min_value=min_date,
            max_value=max_date
        )
    with col2:
        end_date = st.date_input(
            "End date",
            value=max_date,
            min_value=min_date,
            max_value=max_date
        )

    # Validate date order
    if start_date > end_date:
        st.error("❌ Start date must be before or equal to end date.")
        st.stop()

    # Filter deployments and results within selected range for charts
    deps_filtered = deps_with_zone[
        (deps_with_zone["Created Time"].dt.date >= start_date) &
        (deps_with_zone["Created Time"].dt.date <= end_date)
    ]
    result_filtered = result[
        (result["Deployment Time"].dt.date >= start_date) &
        (result["Deployment Time"].dt.date <= end_date)
    ]

    st.markdown("---")

    # ────────── Charts using filtered data ──────────
    # Histogram with data labels
    hist_chart = alt.Chart(result_filtered).mark_bar().encode(
        x=alt.X(
            "Time to First Ride Hours:Q",
            bin=alt.Bin(step=5),
            title="Time to First Ride (h)",
            axis=alt.Axis(tickMinStep=5)
        ),
        y=alt.Y("count()", title="Number of Vehicles"),
        color=alt.value("#34BB78")
    ).properties(
        title="Distribution of Time to First Ride"
    )
    hist_text = hist_chart.mark_text(
        dy=-5,
        color="black",
        align="center"
    ).encode(
        text=alt.Text("count():Q")
    )
    st.altair_chart((hist_chart + hist_text), use_container_width=True)

    model_df = result_filtered.groupby("Vehicle Model")["Time to First Ride Hours"].mean() \
        .reset_index().rename(columns={"Time to First Ride Hours":"AvgTime"})
    model_df = model_df.sort_values("AvgTime")
    # Bar chart with data labels for Vehicle Model
    model_chart = alt.Chart(model_df).mark_bar().encode(
        x=alt.X("Vehicle Model:N", sort=model_df["Vehicle Model"].tolist()),
        y=alt.Y("AvgTime:Q", title="Avg Time to First Ride (h)"),
        color=alt.value("#34BB78")
    ).properties(
        title="Average Time to First Ride by Vehicle Model"
    )
    model_text = model_chart.mark_text(
        dy=-5,  # shift text above the bar
        color="black",
        align="center"
    ).encode(
        text=alt.Text("AvgTime:Q", format=".2f")
    )
    st.altair_chart((model_chart + model_text), use_container_width=True)

    # Compute average time per deployment spot
    spot_avg = result_filtered.groupby("Deployment Spot")["Time to First Ride Hours"] \
        .mean().reset_index().rename(columns={"Time to First Ride Hours": "AvgTime"})
    # Compute count of deployments per spot (from filtered deployments only)
    spot_count = deps_filtered.groupby("name").size().reset_index(name="Count")
    spot_count = spot_count.rename(columns={"name": "Deployment Spot", "Count": "Total Deployments"})
    # Merge average time and counts
    spot_df = spot_avg.merge(spot_count, on="Deployment Spot", how="left")
    # Sort by average time descending
    spot_df = spot_df.sort_values("AvgTime", ascending=False)
    # Compute thresholds for color scale
    min_time = spot_df["AvgTime"].min()
    median_time = spot_df["AvgTime"].median()
    max_time = spot_df["AvgTime"].max()
    # Bar chart for Deployment Spot (no data labels)
    spot_chart = alt.Chart(spot_df).mark_bar().encode(
        x=alt.X("Deployment Spot:N", sort=spot_df["Deployment Spot"].tolist(), title="Deployment Spot"),
        y=alt.Y("AvgTime:Q", title="Avg Time to First Ride (h)"),
        color=alt.Color(
            "AvgTime:Q",
            scale=alt.Scale(
                domain=[min_time, median_time, max_time],
                range=["green", "orange", "red"]
            ),
            legend=None
        )
    ).properties(
        title="Average Time to First Ride by Deployment Spot"
    )
    st.altair_chart(spot_chart, use_container_width=True)
    # Table view of Deployment Spot metrics
    display_spot = spot_df.rename(columns={
        "AvgTime": "Avg Time to First Ride (h)"
    })
    st.subheader("📋 Deployment Spot Statistics Table")
    st.dataframe(display_spot)
    csv_spot = display_spot.to_csv(index=False).encode("utf-8")
    st.download_button(
        "📥 Download Deployment Spot Table",
        data=csv_spot,
        file_name="deployment_spot_stats.csv",
        mime="text/csv"
    )
else:
    st.info("Please select a view from the sidebar.")