import re
import os
import asyncio
from jinja2 import Template
from quart import Quart, render_template
from telethon import TelegramClient
from datetime import datetime, timedelta, timezone
import aiosqlite
from collections import defaultdict

app = Quart(__name__)

# API credentials (get these from my.telegram.org)
api_id = 'add yours'
api_hash = 'Add yours'

# List of channel usernames to monitor
channels = ['iasecprelims','EMERGINGINDIANS','TeamKJS','iasecmainsconference','essaysiasec','choicompiles','upscessay_mains_data_examples','UPSCMains_Testseries','insightsIAStips','proxygyan',
            'UPSC_notes_insta']  # Add more channels as needed

# Database file
DB_FILE = 'telegram_files.db'
# Custom filter to truncate words
def truncatewords(s, num_words):
    words = s.split()
    if len(words) > num_words:
        return ' '.join(words[:num_words]) + '...'
    return s

# Register the filter with Jinja
app.jinja_env.filters['truncatewords'] = truncatewords

# Initialize the Telegram client
client = TelegramClient('session_name', api_id, api_hash)

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS seen_messages (
                message_id TEXT PRIMARY KEY
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS file_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT,
                channel_title TEXT,
                message_time TIMESTAMP,
                file_name TEXT,
                file_size INTEGER,
                media_type TEXT,
                caption TEXT
            )
        ''')
        await db.commit()

async def is_message_seen(message_id):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute('SELECT 1 FROM seen_messages WHERE message_id = ?', (str(message_id),))
        result = await cursor.fetchone()
        return result is not None

async def save_seen_message(message_id):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('INSERT OR IGNORE INTO seen_messages (message_id) VALUES (?)', (str(message_id),))
        await db.commit()

async def save_file_message(channel, channel_title,message_time, file_name, file_size, media_type, caption):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''
            INSERT INTO file_messages (channel,channel_title, message_time, file_name, file_size, media_type, caption)
            VALUES (?, ?,?, ?, ?, ?, ?)
        ''', (channel,channel_title, message_time, file_name, file_size, media_type, caption))
        await db.commit()

# Function to convert URLs in captions to clickable links
def make_links_clickable(caption):
    # Regex pattern to find URLs (http:// or https:
    url_pattern = re.compile(r'(https?://[^\s]+)')
    
    # Replace URLs with HTML anchor tags that open in a new tab
    return url_pattern.sub(r'<a href="\1" target="_blank">\1</a>', caption)

async def fetch_recent_file_messages(channel_username):
    three_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    entity = await client.get_entity(channel_username)
    channel_title=entity.title
    async for message in client.iter_messages(entity, limit=100):
        if message.date < three_days_ago:
            break
        if message.media and not await is_message_seen(message.id):
            await save_seen_message(message.id)
            caption = message.message if message.message else "No caption"
            caption = make_links_clickable(caption)  # Convert URLs to clickable links
            await save_file_message(
                channel_username,
                channel_title,
                message.date.isoformat(),
                message.file.name if message.file else 'Unknown file',
                message.file.size if message.file else 0,
                type(message.media).__name__,
                caption  # Store the caption with clickable links
            )

async def fetch_all_channels():
    tasks = [fetch_recent_file_messages(channel) for channel in channels]
    await asyncio.gather(*tasks)

@app.before_serving
async def before_serving():
    await init_db()
    await client.start()

@app.after_serving
async def after_serving():
    await client.disconnect()

@app.route('/')
async def index():
    await fetch_all_channels()
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT * FROM file_messages
            ORDER BY channel, message_time DESC
        ''')
        file_messages = await cursor.fetchall()
    
    # Group messages by channel
    grouped_messages = defaultdict(list)
    for message in file_messages:
        grouped_messages[message['channel_title']].append(dict(message))
    
    return await render_template('indext.html', grouped_messages=grouped_messages)

if __name__ == '__main__':
    app.run()
