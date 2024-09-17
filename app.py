from flask import Flask, render_template, request, redirect, url_for
from flask_caching import Cache
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import os
from telethon import TelegramClient
from datetime import datetime, timedelta,timezone

app = Flask(__name__)
cache = Cache(app, config={'CACHE_TYPE': 'simple'})

API_KEY = 'Add yours'
YOUTUBE_API_URL = 'https://www.googleapis.com/youtube/v3/playlistItems'
PLAYLIST_API_URL = 'https://www.googleapis.com/youtube/v3/playlists'
WATCHED_VIDEOS_FILE = 'watched_videos.txt'
PLAYLISTS_FILE = 'playlists.txt'
LISTENED_EPISODES_FILE = 'listened_episodes.txt'

# Helper function to fetch videos from a YouTube playlist
async def fetch_videos_from_playlist(session, playlist_id):
    params = {
        'part': 'snippet',
        'playlistId': playlist_id,
        'maxResults': 50,
        'key': API_KEY
    }
    async with session.get(YOUTUBE_API_URL, params=params) as response:
        if response.status != 200:
            print(f"Failed to fetch data for playlist {playlist_id}: {response.status}")
            return []
        data = await response.json()
        return data.get('items', [])

# Helper function to fetch playlist title from YouTube
async def fetch_playlist_title(session, playlist_id):
    params = {
        'part': 'snippet',
        'id': playlist_id,
        'key': API_KEY,
    }
    async with session.get(PLAYLIST_API_URL, params=params) as response:
        if response.status == 200:
            data = await response.json()
            if data['items']:
                return {
                    'id': data['items'][0]['id'],
                    'title': data['items'][0]['snippet']['title'],
                    'channel_title': data['items'][0]['snippet']['channelTitle']
                }
    return None

def filter_videos_by_date(videos, days=5):
    recent_videos = []
    cutoff_date = datetime.now() - timedelta(days=days)
    for video in videos:
        publish_date = datetime.strptime(video['snippet']['publishedAt'], "%Y-%m-%dT%H:%M:%SZ")
        if publish_date >= cutoff_date:
            recent_videos.append({
                'videoId': video['snippet']['resourceId']['videoId'],
                'title': video['snippet']['title'],
                'url': f"https://www.youtube.com/watch?v={video['snippet']['resourceId']['videoId']}",
                'publishedAt': publish_date
            })
    return recent_videos

def load_watched_videos():
    if os.path.exists(WATCHED_VIDEOS_FILE):
        with open(WATCHED_VIDEOS_FILE, 'r') as file:
            return {line.strip() for line in file}
    return set()

def save_watched_videos(video_ids):
    with open(WATCHED_VIDEOS_FILE, 'a') as file:
        for video_id in video_ids:
            file.write(f"{video_id}\n")

def filter_unseen_videos(videos):
    watched_videos = load_watched_videos()
    return [video for video in videos if video['videoId'] not in watched_videos]

async def load_playlists(session):
    playlists = []
    if os.path.exists(PLAYLISTS_FILE):
        with open(PLAYLISTS_FILE, 'r') as file:
            playlist_ids = [line.strip() for line in file]
        tasks = [fetch_playlist_title(session, playlist_id) for playlist_id in playlist_ids]
        playlist_details = await asyncio.gather(*tasks)
        playlists = [detail for detail in playlist_details if detail]
    return playlists

def add_playlist(playlist_id):
    with open(PLAYLISTS_FILE, 'a') as file:
        file.write(f"{playlist_id}\n")

# Helper function to scrape AIR content
async def scrape_air_content(url, title_filter):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                print(f"Failed to fetch data from {url}: {response.status}")
                return []
            content = await response.text()
            soup = BeautifulSoup(content, "html.parser")
            episodes = []
            table = soup.find('table', class_='table')
            if not table:
                print("Table not found")
                return []
            rows = table.find_all('tr')[1:]
            for row in rows:
                cols = row.find_all('td')
                if len(cols) < 4:
                    continue
                title = cols[0].text.strip()
                date_str = cols[1].text.strip()
                time_str = cols[2].text.strip()
                audio_src = cols[3].find('audio').find('source')['src'] if cols[3].find('audio') else None
                try:
                    date = datetime.strptime(f"{date_str} {time_str}", '%d %b %Y %H:%M')
                except ValueError:
                    continue
                if title in title_filter:
                    episodes.append({
                        'title': title,
                        'date': date,
                        'audio_link': audio_src
                    })
            return episodes

async def scrape_air_spotlight():
    return await scrape_air_content("https://www.newsonair.gov.in/listen-broadcast-category/daily-broadcast/", ["Spotlight"])

async def scrape_air_insight():
    return await scrape_air_content("https://www.newsonair.gov.in/listen-broadcast-category/weekly-broadcast/", ["Insight", "Insights"])

async def scrape_air_economy():
    return await scrape_air_content("https://www.newsonair.gov.in/listen-broadcast-category/weekly-broadcast/", ["Money Talk"])

def filter_recent_episodes(episodes, days=3):
    cutoff_date = datetime.now() - timedelta(days=days)
    return [episode for episode in episodes if episode['date'] >= cutoff_date]

def load_listened_episodes():
    if os.path.exists(LISTENED_EPISODES_FILE):
        with open(LISTENED_EPISODES_FILE, 'r') as file:
            return {line.strip() for line in file}
    return set()

def save_listened_episodes(episode_links):
    with open(LISTENED_EPISODES_FILE, 'a') as file:
        for link in episode_links:
            file.write(f"{link}\n")

def filter_unheard_episodes(episodes):
    listened_episodes = load_listened_episodes()
    return [episode for episode in episodes if episode['audio_link'] not in listened_episodes]


# Scrape PIB content
async def scrape_pib():
    url = "https://pib.gov.in/ViewBackgrounder.aspx?MenuId=51"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                print(f"Failed to fetch PIB data: {response.status}")
                return {}
            content = await response.text()
            soup = BeautifulSoup(content, "html.parser")
            
            today = datetime.today()
            one_month_ago = today - timedelta(days=30)

            # Dictionary to hold ministry and respective backgrounders
            pib_data = {}
            
            # Iterate through each ministry section
            for ministry_section in soup.find_all('li'):
                # Get the ministry name from the <h3> tag
                ministry_name_tag = ministry_section.find('h3')
                if ministry_name_tag:
                    ministry_name = ministry_name_tag.get_text(strip=True)
                    backgrounders = []
                    
                    # Get all backgrounder links under this ministry
                    for link in ministry_section.find_all('a'):
                        href = link.get('href')
                        title = link.text.strip()
                        date_span = link.find_next('span', class_='publishdatesmall')
                        
                        if href and date_span:
                            # Extract date
                            date_text = date_span.text.replace('Posted on:', '').strip()
                            try:
                                post_date = datetime.strptime(date_text, '%d %b %Y')
                            except ValueError:
                                continue
                            
                            # Check if the post is within the last month
                            if post_date >= one_month_ago:
                                full_link = f"https://pib.gov.in{href}"
                                backgrounders.append({
                                    'title': title,
                                    'url': full_link,
                                    'date': date_text
                                })
                    
                    # If there are any backgrounders for this ministry, add them
                    if backgrounders:
                        pib_data[ministry_name] = backgrounders
            
            return pib_data


# Flask routes
@app.route('/')
@cache.cached(timeout=300)
async def index():
    async with aiohttp.ClientSession() as session:
        playlists = await load_playlists(session)
        playlist_data = []
        for playlist in playlists:
            videos = await fetch_videos_from_playlist(session, playlist['id'])
            recent_videos = filter_videos_by_date(videos, days=5)
            unseen_videos = filter_unseen_videos(recent_videos)
            playlist_data.append({
                'id': playlist['id'],
                'title': playlist['title'],
                'unseen_count': len(unseen_videos),
                'channel': playlist['channel_title']
            })
            playlist_data.sort(key=lambda x: x['unseen_count'], reverse=True)

        spotlight_episodes, insight_episodes, economy_episodes,pib_backgrounders = await asyncio.gather(
            scrape_air_spotlight(),
            scrape_air_insight(),
            scrape_air_economy(),
            scrape_pib()
        )

        spotlight_unheard = filter_unheard_episodes(filter_recent_episodes(spotlight_episodes, days=5))
        insight_unheard = filter_unheard_episodes(filter_recent_episodes(insight_episodes, days=5))
        economy_unheard = filter_unheard_episodes(filter_recent_episodes(economy_episodes, days=5))

    return render_template('index.html', playlists=playlist_data, 
                           spotlight_unheard_count=len(spotlight_unheard), 
                           insight_unheard_count=len(insight_unheard),
                           economy_unheard_count=len(economy_unheard),
                           pib_backgrounders=pib_backgrounders)

@app.route('/unseen_videos/<playlist_id>')
async def unseen_videos(playlist_id):
    async with aiohttp.ClientSession() as session:
        videos = await fetch_videos_from_playlist(session, playlist_id)
        recent_videos = filter_videos_by_date(videos, days=5)
        unseen_videos = filter_unseen_videos(recent_videos)
    return render_template('unseen_videos.html', videos=unseen_videos, playlist_id=playlist_id)

@app.route('/pib')
async def pibscrap():
	pib= await scrape_pib()
	return render_template('pib.html',pib_backgrounders=pib)


@app.route('/mark_watched', methods=['POST'])
def mark_watched():
    video_ids = request.form.getlist('video_ids')
    save_watched_videos(video_ids)
    return redirect(url_for('index'))

@app.route('/add_playlist', methods=['GET', 'POST'])
def add_playlist_route():
    if request.method == 'POST':
        playlist_id = request.form['playlist_id']
        add_playlist(playlist_id)
        return redirect(url_for('index'))
    return render_template('add_playlist.html')

@app.route('/spotlight')
async def spotlight():
    episodes = await scrape_air_spotlight()
    recent_episodes = filter_recent_episodes(episodes, days=5)
    unheard_episodes = filter_unheard_episodes(recent_episodes)
    return render_template('spotlight.html', episodes=unheard_episodes)

@app.route('/Insight')
async def insight():
    episodes = await scrape_air_insight()
    recent_episodes = filter_recent_episodes(episodes, days=5)
    unheard_episodes = filter_unheard_episodes(recent_episodes)
    return render_template('spotlight.html', episodes=unheard_episodes)

@app.route('/aireconomy')
async def aireconomy():
    episodes = await scrape_air_economy()
    recent_episodes = filter_recent_episodes(episodes, days=5)
    unheard_episodes = filter_unheard_episodes(recent_episodes)
    return render_template('spotlight.html', episodes=unheard_episodes)

@app.route('/mark_listened', methods=['POST'])
def mark_listened():
    episode_links = request.form.getlist('episode_links')
    save_listened_episodes(episode_links)
    return redirect(url_for('spotlight'))

if __name__ == '__main__':
    app.run(debug=True)
