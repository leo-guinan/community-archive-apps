import streamlit as st
from streamlit_tags import st_tags
from streamlit.runtime.scriptrunner import get_script_run_ctx, add_script_run_ctx

import pandas as pd
import numpy as np
from dotenv import load_dotenv
import os
import plotly.graph_objects as go
from supabase import create_client, Client
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date
import plotly.express as px
import contextvars
import logging
import time

load_dotenv(".env")
st.set_page_config(layout="wide")

# Add this near the top of the file
logging.basicConfig(level=logging.INFO)

url: str = "https://fabxmporizzqflnftavs.supabase.co"
key: str = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZhYnhtcG9yaXp6cWZsbmZ0YXZzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3MjIyNDQ5MTIsImV4cCI6MjAzNzgyMDkxMn0.UIEJiUNkLsW28tBHmG-RQDW-I5JNlJLt62CSk9D_qG8"
)


# Add this function to measure execution time
def timeit(func):
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        end_time = time.time()
        duration = end_time - start_time
        st.write(f"{func.__name__} took {duration:.2f} seconds")
        return result
    return wrapper


@st.cache_data
def fetch_tweets_cached(search_query, start_date, end_date, limit=500):
    logging.info(f"Executing fetch_tweets_cached for query: {search_query}")
    ctx = _streamlit_thread_context.get(None)
    if ctx:
        add_script_run_ctx(ctx)
    
    supabase = create_client(url, key)
    result = supabase.rpc(
        "search_tweets",
        {
            "search_query": search_query.replace(" ", "+"),
            "since_date": start_date.isoformat(),
            "until_date": end_date.isoformat(),
            "limit_": limit,
        },
    ).execute()
    df = pd.DataFrame(result.data)
    df['search_word'] = search_query  # Add this line to track which word matched
    return df

@timeit
async def fetch_tweets(search_words, start_date, end_date, limit=500):
    logging.info(f"Executing fetch_tweets for words: {search_words}")
    tasks = [
        asyncio.to_thread(fetch_tweets_cached, word, start_date, end_date, limit)
        for word in search_words
    ]
    results = await asyncio.gather(*tasks)
    return pd.concat(results, ignore_index=True)



_streamlit_thread_context = contextvars.ContextVar("streamlit_thread_context")
@st.cache_data
def fetch_word_occurrences_cached(word, start_date, end_date, user_ids):
    logging.info(f"Executing fetch_word_occurrences for word: {word}")
    ctx = _streamlit_thread_context.get(None)
    if ctx:
        add_script_run_ctx(ctx)
    
    supabase = create_client(url, key)
    result = supabase.rpc(
        "word_occurrences",
        {
            "search_word": word,
        },
    ).execute()
    
    filtered_data = [
        item for item in result.data 
        if start_date <= datetime.strptime(item['month'], '%Y-%m').date() <= end_date
    ]
    
    return {word: filtered_data}

@timeit
async def fetch_word_occurrences(search_words, start_date, end_date, user_ids):
    logging.info(f"Executing fetch_word_occurrences for words: {search_words}")
    tasks = [
        asyncio.to_thread(fetch_word_occurrences_cached, word, start_date, end_date, user_ids)
        for word in search_words
    ]
    results = await asyncio.gather(*tasks)
    return {k: v for d in results for k, v in d.items()}


@st.cache_data
def fetch_monthly_tweet_counts():
    logging.info("Executing fetch_monthly_tweet_counts")
    supabase = create_client(url, key)
    result = supabase.rpc('get_monthly_tweet_counts').execute()
    df = pd.DataFrame(result.data)
    df['month'] = pd.to_datetime(df['month'], utc=True)
    return df


def plot_word_occurrences(word_occurrences_dict, monthly_tweet_counts, normalize):
    logging.info("Executing plot_word_occurrences")
    df_list = []
    for word, result in word_occurrences_dict.items():
        if result:  # Check if result not empty
            df = pd.DataFrame(result)
            df['month'] = pd.to_datetime(df['month'], utc=True)
            df['word'] = word
            df_list.append(df)
    
    if not df_list:  # If no data, return empty figure
        return go.Figure()
    
    df = pd.concat(df_list)
    df = df.merge(monthly_tweet_counts, on='month', how='left')
    
    if normalize:
        df['normalized_count'] = df['word_count'] / df['tweet_count'] * 1000
        y_col = 'normalized_count'
        y_title = 'Occurrences per 1000 tweets'
    else:
        y_col = 'word_count'
        y_title = 'Word Count'

    fig = px.line(df, x='month', y=y_col, color='word', title='Word Occurrences Over Time')
    fig.update_layout(xaxis_title='Month', yaxis_title=y_title)
    fig.update_traces(mode='lines+markers')  # Add markers for selection
    return fig


@st.cache_data
def fetch_users():
    logging.info("Executing fetch_users")
    supabase = create_client(url, key)
    result = supabase.table("account").select("account_id", "username").execute()
    return result.data


st.title("Trends in the Community Archive")

# st.sidebar.header("Search Settings")
default_words = ["ingroup", "postrat", "tpot"]



async def main():
    logging.info("Executing main function")
    if not st.session_state.get("supabase"):
        st.session_state.supabase = create_client(url, key)
    
    _streamlit_thread_context.set(get_script_run_ctx())
    
    col1, col2 = st.columns(2)
    
    with col1:
        form = st.form("search_form")
        search_words = st_tags(
            label="",
            text="Enter search words",
            value=default_words,
            suggestions=["meditation", "mindfulness", "retreat"],
            maxtags=10,
            key="1",
        )

        start_date = form.date_input("Start Date", value=date(2020, 1, 1))
        end_date = form.date_input("End Date", value=date.today())

        users = fetch_users()
        user_options = {user["username"]: user["account_id"] for user in users}
        selected_users = form.multiselect("Select Users", options=list(user_options.keys()))
        user_ids = [user_options[user] for user in selected_users]
        normalize = form.checkbox('Normalize by monthly tweet count')
        submit_button = form.form_submit_button(label='Search')

    # Check if query parameters have changed
    query_changed = (
        submit_button
        or "prev_search_words" not in st.session_state
        or "prev_start_date" not in st.session_state
        or "prev_end_date" not in st.session_state
        or "prev_user_ids" not in st.session_state
        or search_words != st.session_state.get("prev_search_words")
        or start_date != st.session_state.get("prev_start_date")
        or end_date != st.session_state.get("prev_end_date")
        or user_ids != st.session_state.get("prev_user_ids")
    )

    if query_changed or "tweets_df" not in st.session_state:
        if search_words:
            with st.spinner("Fetching data..."):
                tweets_task = asyncio.create_task(fetch_tweets(search_words, start_date, end_date))
                word_occurrences_task = asyncio.create_task(fetch_word_occurrences(search_words, start_date, end_date, user_ids))
                
                st.session_state.tweets_df = await tweets_task
                st.session_state.word_occurrences_dict = await word_occurrences_task
                st.session_state.monthly_tweet_counts = fetch_monthly_tweet_counts()

                # Update previous query parameters
                st.session_state.prev_search_words = search_words
                st.session_state.prev_start_date = start_date
                st.session_state.prev_end_date = end_date
                st.session_state.prev_user_ids = user_ids

    if "tweets_df" in st.session_state:
        tweets_df = st.session_state.tweets_df
        word_occurrences_dict = st.session_state.word_occurrences_dict
        monthly_tweet_counts = st.session_state.monthly_tweet_counts

        with col1:
            st.subheader("Word Occurrences Over Time")
            fig = plot_word_occurrences(
                word_occurrences_dict, monthly_tweet_counts, normalize
            )
            selection = st.plotly_chart(fig, use_container_width=True, key="word_occurrences", on_select="rerun")
            logging.info(f"Selected points: {selection}")

        with col2:
            st.subheader("Related Tweets")
            tweet_container = st.container()
            tweet_container.markdown(
                """
                <style>
                [data-testid="stVerticalBlock"] > [style*="flex-direction: column;"] > [data-testid="stVerticalBlock"] {
                    height: 80vh;
                    overflow-y: auto;
                }
                .tweet-container {
                    display: flex;
                    align-items: flex-start;
                    margin-bottom: 20px;
                }
                .tweet-avatar {
                    width: 48px;
                    height: 48px;
                    border-radius: 50%;
                    margin-right: 10px;
                }
                .tweet-content {
                    flex: 1;
                }
                </style>
                """,
                unsafe_allow_html=True
            )
            with tweet_container:
                tabs = st.tabs(search_words)
                for word, tab in zip(search_words, tabs):
                    with tab:
                        word_tweets = tweets_df[tweets_df['search_word'] == word]
                        
                        # Filter tweets based on selection
                        if selection and selection['selection']['points']:
                            selected_dates = [pd.to_datetime(point['x']) for point in selection['selection']['points']]
                            word_tweets.loc[:, 'created_at'] = pd.to_datetime(word_tweets['created_at'])
                            word_tweets = word_tweets[pd.to_datetime(word_tweets['created_at']).dt.to_period('M').isin([date.to_period('M') for date in selected_dates])]
                        
                        if word_tweets.empty:
                            st.write(f"No tweets found for '{word}'")
                        else:
                            for _, tweet in word_tweets.iterrows():
                                tweet_url = f"https://twitter.com/i/web/status/{tweet['tweet_id']}"
                                highlighted_text = tweet['full_text'].replace(word, f"<b>{word}</b>")
                                st.markdown(
                                    f"""
                                    <div class="tweet-container">
                                        <img src="{tweet['avatar_media_url']}" class="tweet-avatar" alt="Avatar">
                                        <div class="tweet-content">
                                            <b>@{tweet['username']}</b> - <a href="{tweet_url}" target="_blank" style="color: inherit; text-decoration: none;">{tweet['created_at']}</a>
                                            <br>
                                            {highlighted_text}
                                    </div>
                                    """,
                                    unsafe_allow_html=True
                                )
                                st.markdown("---")
                

if __name__ == "__main__":
    asyncio.run(main())