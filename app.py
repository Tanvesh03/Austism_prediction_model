import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from booking_scraper import BookingScraper
import json
import io

st.set_page_config(
    page_title="Booking.com Scraper",
    page_icon="🏨",
    layout="wide",
)

st.title("🏨 Booking.com Hotel Scraper")
st.caption("Search and explore hotel listings scraped from Booking.com.")

# ── Sidebar controls ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Search Parameters")

    destination = st.text_input("Destination", placeholder="e.g. Paris, France")

    tomorrow = datetime.today() + timedelta(days=1)
    default_out = tomorrow + timedelta(days=2)

    checkin = st.date_input("Check-in Date", value=tomorrow, min_value=datetime.today())
    checkout = st.date_input("Check-out Date", value=default_out, min_value=checkin)

    adults = st.number_input("Adults", min_value=1, max_value=10, value=2)
    max_pages = st.slider("Max Pages to Scrape", min_value=1, max_value=5, value=2)

    run = st.button("🔍 Search Hotels", use_container_width=True, type="primary")

# ── Session state ─────────────────────────────────────────────────────────────
if "hotels_df" not in st.session_state:
    st.session_state.hotels_df = None
if "raw_hotels" not in st.session_state:
    st.session_state.raw_hotels = None

# ── Scrape ────────────────────────────────────────────────────────────────────
if run:
    if not destination.strip():
        st.sidebar.error("Please enter a destination.")
    elif checkout <= checkin:
        st.sidebar.error("Check-out must be after check-in.")
    else:
        with st.spinner(f"Scraping Booking.com for **{destination}**…"):
            scraper = BookingScraper(delay_range=(1, 3))
            hotels = scraper.scrape(
                destination=destination,
                checkin=checkin.strftime("%Y-%m-%d"),
                checkout=checkout.strftime("%Y-%m-%d"),
                adults=int(adults),
                max_pages=int(max_pages),
            )

        if not hotels:
            st.warning(
                "No results returned. Booking.com may be blocking the request. "
                "Try again or consider using a headless browser."
            )
            st.session_state.hotels_df = None
            st.session_state.raw_hotels = None
        else:
            df = pd.DataFrame([{
                "Name": h.name,
                "Location": h.location,
                "Price / Night": pd.to_numeric(h.price_per_night, errors="coerce"),
                "Currency": h.currency,
                "Rating": pd.to_numeric(h.rating, errors="coerce"),
                "Reviews": h.review_count,
                "Review Label": h.review_label,
                "Check-in": h.checkin_date,
                "Check-out": h.checkout_date,
                "URL": h.url,
            } for h in hotels])

            st.session_state.hotels_df = df
            st.session_state.raw_hotels = hotels
            st.success(f"Found **{len(hotels)}** hotel(s).")

# ── Results ───────────────────────────────────────────────────────────────────
df = st.session_state.hotels_df

if df is not None and not df.empty:

    # KPI row
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Hotels Found", len(df))
    col2.metric("Avg Price / Night",
                f"${df['Price / Night'].mean():.0f}" if df['Price / Night'].notna().any() else "N/A")
    col3.metric("Avg Rating",
                f"{df['Rating'].mean():.1f}" if df['Rating'].notna().any() else "N/A")
    col4.metric("Cheapest",
                f"${df['Price / Night'].min():.0f}" if df['Price / Night'].notna().any() else "N/A")

    st.divider()

    # ── Filters ───────────────────────────────────────────────────────────────
    with st.expander("Filters", expanded=True):
        fc1, fc2 = st.columns(2)
        price_vals = df["Price / Night"].dropna()
        if not price_vals.empty:
            p_min, p_max = float(price_vals.min()), float(price_vals.max())
            price_range = fc1.slider(
                "Price range ($/night)",
                min_value=p_min, max_value=p_max if p_max > p_min else p_min + 1,
                value=(p_min, p_max),
            )
        else:
            price_range = None

        rating_vals = df["Rating"].dropna()
        if not rating_vals.empty:
            r_min, r_max = float(rating_vals.min()), float(rating_vals.max())
            rating_filter = fc2.slider(
                "Minimum rating",
                min_value=r_min, max_value=r_max if r_max > r_min else r_min + 0.1,
                value=r_min, step=0.1,
            )
        else:
            rating_filter = None

    filtered = df.copy()
    if price_range is not None:
        filtered = filtered[
            filtered["Price / Night"].isna() |
            filtered["Price / Night"].between(*price_range)
        ]
    if rating_filter is not None:
        filtered = filtered[
            filtered["Rating"].isna() |
            (filtered["Rating"] >= rating_filter)
        ]

    st.subheader(f"Results ({len(filtered)} hotels)")

    # Clickable table
    display_df = filtered.drop(columns=["URL"]).reset_index(drop=True)
    st.dataframe(display_df, use_container_width=True, height=400)

    st.divider()

    # ── Charts ────────────────────────────────────────────────────────────────
    ch1, ch2 = st.columns(2)

    with ch1:
        st.subheader("Price Distribution")
        price_data = filtered["Price / Night"].dropna()
        if not price_data.empty:
            fig = px.histogram(
                filtered, x="Price / Night", nbins=20,
                labels={"Price / Night": "Price per Night ($)"},
                color_discrete_sequence=["#0068c9"],
            )
            fig.update_layout(showlegend=False, margin=dict(t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No price data available.")

    with ch2:
        st.subheader("Rating vs Price")
        scatter_data = filtered.dropna(subset=["Price / Night", "Rating"])
        if not scatter_data.empty:
            fig2 = px.scatter(
                scatter_data,
                x="Price / Night", y="Rating",
                hover_name="Name",
                color="Rating",
                color_continuous_scale="Blues",
                labels={"Price / Night": "Price per Night ($)"},
            )
            fig2.update_layout(margin=dict(t=20, b=20))
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Not enough data for scatter plot.")

    st.divider()

    # ── Downloads ─────────────────────────────────────────────────────────────
    st.subheader("Download Results")
    dl1, dl2 = st.columns(2)

    csv_buf = io.StringIO()
    filtered.to_csv(csv_buf, index=False)
    dl1.download_button(
        label="⬇️ Download CSV",
        data=csv_buf.getvalue(),
        file_name="booking_results.csv",
        mime="text/csv",
        use_container_width=True,
    )

    json_data = filtered.to_json(orient="records", indent=2)
    dl2.download_button(
        label="⬇️ Download JSON",
        data=json_data,
        file_name="booking_results.json",
        mime="application/json",
        use_container_width=True,
    )

else:
    st.info("Enter a destination in the sidebar and click **Search Hotels** to get started.")
