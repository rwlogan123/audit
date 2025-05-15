
import streamlit as st
import requests
import base64
import pandas as pd
from email.message import EmailMessage
import smtplib
import re

# --- CONFIG ---
def get_headers(api_user, api_pass):
    credentials = f"{api_user}:{api_pass}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    return {
        "Content-Type": "application/json",
        "Authorization": f"Basic {encoded_credentials}"
    }

def is_valid_email(email):
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return bool(re.match(pattern, email))

# --- API AUTH ---
try:
    api_user = st.secrets["DATAFORSEO_USER"]
    api_pass = st.secrets["DATAFORSEO_PASS"]
    HEADERS = get_headers(api_user, api_pass)
except Exception as e:
    st.error("Missing or invalid credentials in Streamlit secrets.")
    st.stop()

# --- SESSION STATE INIT ---
if "results" not in st.session_state:
    st.session_state["results"] = None
if "summary" not in st.session_state:
    st.session_state["summary"] = None

# --- STREAMLIT UI ---
st.title("Local Business SERP Audit")

with st.form("search_form"):
    keyword = st.text_input("Keyword (e.g., plumber)", value="plumber", help="Main service term customers might search for")
    city = st.text_input("City", value="Los Angeles", help="Primary service area or business location")
    state = st.text_input("State", value="CA", help="Two-letter state abbreviation")
    email = st.text_input("Email to send report (optional)", help="We'll send your CSV report to this address if entered")
    submit = st.form_submit_button("Run Audit")

@st.cache_data(ttl=3600)
def fetch_audit_results(variations, city, state):
    batched_data = [
        {"keyword": q, "location_name": f"{city}, {state}, United States", "limit": 5}
        for q in variations
    ]
    try:
        response = requests.post(
            "https://api.dataforseo.com/v3/business_data/business_listings/search/live",
            headers=HEADERS,
            json={"data": batched_data},
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"API request failed: {e}")
        return None

def format_results(tasks, variations):
    results = []
    for i, task in enumerate(tasks):
        task_result = task.get("result", [{}])
        items = task_result[0].get("items", []) if task_result else []
        for item in items:
            results.append({
                "Query": variations[i],
                "Business Name": item.get("title"),
                "Address": item.get("address_info", {}).get("address"),
                "Phone": item.get("phone_number"),
                "Website": item.get("site_links", {}).get("site_link"),
                "Rating": item.get("rating"),
                "Total Reviews": item.get("reviews_count")
            })
    return results

if submit:
    if not keyword or not city or not state:
        st.warning("Please fill in keyword, city, and state.")
    elif email and not is_valid_email(email):
        st.warning("Please enter a valid email address.")
    else:
        with st.spinner("Running audit and analyzing SERP results..."):
            variations = [
                keyword,
                f"{keyword} near me",
                f"{keyword} {city}",
                f"{keyword} {state}",
                f"{keyword} {city} {state}"
            ]

            response_json = fetch_audit_results(variations, city, state)
            if response_json and response_json.get("tasks"):
                tasks = response_json["tasks"]
                results = format_results(tasks, variations)

                if results:
                    df = pd.DataFrame(results)
                    df['Rating'] = pd.to_numeric(df['Rating'], errors='coerce')
                    st.session_state["results"] = df
                    st.session_state["summary"] = {
                        "queries": len(variations),
                        "matches": len(df)
                    }

                    st.subheader("📊 Audit Summary")
                    st.markdown(f"- **Total Queries Run**: {len(variations)}")
                    st.markdown(f"- **Total Businesses Found**: {len(df)}")

                    st.subheader("🔍 Audit Results")
                    st.dataframe(df)

                    # Top-Rated Businesses Chart
                    top_rated = df.sort_values(by='Rating', ascending=False).head(5)
                    if not top_rated.empty:
                        st.subheader("📈 Top Rated Businesses")
                        chart_data = pd.DataFrame({
                            'Business': top_rated['Business Name'],
                            'Rating': top_rated['Rating']
                        })
                        st.bar_chart(chart_data.set_index('Business'))

                    # --- Sidebar Filters ---
                    with st.sidebar:
                        st.header("Filter Results")
                        min_rating = st.slider("Minimum Rating", 1.0, 5.0, 3.0, 0.1)
                        has_website = st.checkbox("Only businesses with a website", value=False)

                    filtered_df = df[df['Rating'] >= min_rating]
                    if has_website:
                        filtered_df = filtered_df[filtered_df['Website'].notna() & (filtered_df['Website'] != '')]

                    st.subheader("📂 Filtered Results")
                    st.dataframe(filtered_df)

                    # Download filtered results
                    csv_bytes = filtered_df.to_csv(index=False).encode()
                    st.download_button(
                        "⬇️ Download Filtered CSV",
                        data=csv_bytes,
                        file_name="filtered_serp_audit.csv",
                        mime="text/csv"
                    )

                    # Email section
                    if email:
                        try:
                            msg = EmailMessage()
                            msg["Subject"] = "Your SERP Audit Report"
                            msg["From"] = api_user
                            msg["To"] = email
                            msg.set_content("Attached is your audit report.")

                            msg.add_attachment(csv_bytes, maintype="application", subtype="csv", filename="filtered_serp_audit.csv")

                            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                                smtp.login(api_user, api_pass)
                                smtp.send_message(msg)

                            st.success(f"Report sent to {email}")
                        except Exception as e:
                            st.error(f"Failed to send email: {e}")
                else:
                    st.warning("No businesses found for these search terms.")
            else:
                st.error("No response or invalid data received from API.")

# --- Display Last Results if Available ---
if st.session_state["results"] is not None:
    st.markdown("---")
    st.markdown("### 🔁 Last Audit Snapshot")
    st.markdown(f"- **Queries**: {st.session_state['summary']['queries']}")
    st.markdown(f"- **Businesses Found**: {st.session_state['summary']['matches']}")
    st.dataframe(st.session_state["results"])
