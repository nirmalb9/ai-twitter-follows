"""Configuration management for Twitter network analysis."""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# X/Twitter Credentials
X_USERNAME = os.getenv('X_USERNAME')
X_EMAIL = os.getenv('X_EMAIL')
X_PASSWORD = os.getenv('X_PASSWORD')
X_2FA_CODE = os.getenv('X_2FA_CODE', '')

# Validate credentials
assert X_USERNAME, "X_USERNAME not set in .env file"
assert X_EMAIL, "X_EMAIL not set in .env file"
assert X_PASSWORD, "X_PASSWORD not set in .env file"

# Data directories
DATA_DIR = Path('data')
DATA_DIR.mkdir(exist_ok=True)

FOLLOWERS_DIR = DATA_DIR / 'followers'
FOLLOWERS_DIR.mkdir(exist_ok=True)

FOLLOWING_DIR = DATA_DIR / 'following'
FOLLOWING_DIR.mkdir(exist_ok=True)

TWEETS_DIR = DATA_DIR / 'tweets'
TWEETS_DIR.mkdir(exist_ok=True)

# Output files
MY_FOLLOWING_CSV = DATA_DIR / 'my_following.csv'
SELECTED_USERS_FILE = DATA_DIR / 'selected_users.txt'

# Scraping parameters
MAX_FOLLOWING_PER_USER = 5000  # Limit to avoid rate limits
MAX_FOLLOWERS_PER_USER = 5000  # Limit to avoid rate limits
TWEETS_PER_USER = 20
BATCH_SIZE = 200  # Users to fetch at once

# Rate limiting
DELAY_BETWEEN_USERS = 2  # Seconds between user fetches
DELAY_BETWEEN_BATCHES = 5  # Seconds between batch fetches

# Cookie file for session persistence
COOKIES_FILE = 'cookies.json'