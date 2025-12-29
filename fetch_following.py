#!/usr/bin/env python3
"""
Simple DOM-based scraper for X/Twitter following list using Playwright.
Scrapes directly from the visible page elements instead of intercepting API calls.
"""

import asyncio
import logging
import pandas as pd
import re
from pathlib import Path
from playwright.async_api import async_playwright
from tqdm import tqdm
import time

from config import (
    X_USERNAME, X_EMAIL, X_PASSWORD,
    MY_FOLLOWING_CSV, DATA_DIR,
    logger
)


class SimpleXScraper:
    def __init__(self):
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None

    async def start(self, headless=False):
        """Start browser."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=headless,
            args=['--disable-blink-features=AutomationControlled']
        )

        # Create context with realistic viewport
        self.context = await self.browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        self.page = await self.context.new_page()

    async def login(self):
        """Login to X/Twitter."""
        logger.info("Navigating to X.com...")
        await self.page.goto('https://x.com/login')
        await self.page.wait_for_timeout(2000)

        # Enter username
        logger.info("Entering username...")
        username_input = await self.page.wait_for_selector('input[autocomplete="username"]', timeout=10000)
        await username_input.fill(X_USERNAME)
        await self.page.wait_for_timeout(1000)

        # Click next
        next_button = await self.page.wait_for_selector('text=Next', timeout=5000)
        await next_button.click()
        await self.page.wait_for_timeout(2000)

        # Check if email verification is needed
        try:
            email_input = await self.page.wait_for_selector('input[autocomplete="email"]', timeout=3000)
            if email_input:
                logger.info("Email verification required...")
                await email_input.fill(X_EMAIL)
                await self.page.wait_for_timeout(1000)
                next_button = await self.page.wait_for_selector('text=Next', timeout=5000)
                await next_button.click()
                await self.page.wait_for_timeout(2000)
        except:
            pass

        # Enter password
        logger.info("Entering password...")
        password_input = await self.page.wait_for_selector('input[type="password"]', timeout=10000)
        await password_input.fill(X_PASSWORD)
        await self.page.wait_for_timeout(1000)

        # Click login
        login_button = await self.page.wait_for_selector('text=Log in', timeout=5000)
        await login_button.click()

        # Wait for login to complete
        logger.info("Waiting for login to complete...")
        await self.page.wait_for_selector('a[href="/home"]', timeout=30000)
        logger.info("Login successful!")

    async def fetch_following(self):
        """Fetch list of users I follow by scraping the DOM."""
        logger.info(f"Navigating to following page for @{X_USERNAME}...")

        # Navigate to following page
        await self.page.goto(f'https://x.com/{X_USERNAME}/following')
        await self.page.wait_for_timeout(3000)

        # Wait for user cells to load
        await self.page.wait_for_selector('[data-testid="UserCell"]', timeout=10000)

        following_list = []
        seen_users = set()

        # Scroll and extract users
        logger.info("Scrolling to load all following...")
        last_count = 0
        no_new_users_count = 0
        max_no_new = 3  # Stop after 3 scrolls with no new users

        while True:
            # Get all user cells currently visible
            user_cells = await self.page.query_selector_all('[data-testid="UserCell"]')

            for cell in user_cells:
                try:
                    # Extract user info from the cell
                    user_data = await self.extract_user_from_cell(cell)

                    if user_data and user_data['username'] and user_data['username'] not in seen_users:
                        following_list.append(user_data)
                        seen_users.add(user_data['username'])
                        logger.debug(f"Found user: @{user_data['username']}")
                except Exception as e:
                    logger.debug(f"Error extracting user from cell: {e}")

            current_count = len(following_list)
            logger.info(f"Extracted {current_count} unique users so far...")

            # Check if we got new users
            if current_count == last_count:
                no_new_users_count += 1
                if no_new_users_count >= max_no_new:
                    logger.info("No new users found after multiple scrolls, stopping...")
                    break
            else:
                no_new_users_count = 0

            last_count = current_count

            # Scroll down
            await self.page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await self.page.wait_for_timeout(2000)

        logger.info(f"Extracted {len(following_list)} unique users total")
        return following_list

    async def extract_user_from_cell(self, cell):
        """Extract user data from a UserCell element."""
        try:
            # Get the link to the user profile
            user_link = await cell.query_selector('a[role="link"][href^="/"]')
            if not user_link:
                return None

            href = await user_link.get_attribute('href')
            if not href or href == '/' or '/status/' in href:
                return None

            username = href.strip('/')

            # Skip if it's not a valid username
            if not username or '/' in username:
                return None

            # Get display name
            display_name = ''
            name_element = await cell.query_selector('[dir="ltr"] > span > span')
            if name_element:
                display_name = await name_element.inner_text()

            # Get bio/description
            bio = ''
            bio_element = await cell.query_selector('[data-testid="UserDescription"]')
            if bio_element:
                bio = await bio_element.inner_text()

            # Get follower count (usually in format "X.XK followers" or "X followers")
            followers_count = 0
            followers_text_elements = await cell.query_selector_all('span')
            for elem in followers_text_elements:
                text = await elem.inner_text()
                if 'follower' in text.lower():
                    # Extract number from text like "34.2K followers"
                    match = re.search(r'([\d,.]+)([KMB]?)\s*follower', text, re.IGNORECASE)
                    if match:
                        num = float(match.group(1).replace(',', ''))
                        multiplier = {'K': 1000, 'M': 1000000, 'B': 1000000000}.get(match.group(2).upper(), 1)
                        followers_count = int(num * multiplier)
                        break

            # Check for verified badge
            verified = False
            blue_verified = False
            verified_badge = await cell.query_selector('[aria-label*="Verified"]')
            if verified_badge:
                aria_label = await verified_badge.get_attribute('aria-label')
                if aria_label:
                    if 'blue' in aria_label.lower() or 'subscribed' in aria_label.lower():
                        blue_verified = True
                    else:
                        verified = True

            return {
                'username': username,
                'display_name': display_name,
                'user_id': '',  # Would need API call to get this
                'bio': bio,
                'location': '',  # Not shown in following list
                'followers_count': followers_count,
                'following_count': 0,  # Not shown in following list
                'tweet_count': 0,  # Not shown in following list
                'verified': verified,
                'blue_verified': blue_verified,
                'profile_url': f"https://x.com/{username}",
                'profile_image': '',  # Would need to extract
                'created_at': ''  # Not shown in following list
            }

        except Exception as e:
            logger.debug(f"Error extracting user data: {e}")
            return None

    async def close(self):
        """Close browser."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()


async def main():
    """Main execution function."""
    scraper = SimpleXScraper()

    try:
        # Start browser (headless=False to see what's happening)
        logger.info("Starting browser...")
        await scraper.start(headless=False)

        # Login
        await scraper.login()

        # Fetch following
        following_list = await scraper.fetch_following()

        if following_list:
            # Convert to DataFrame
            df = pd.DataFrame(following_list)

            # Sort by followers count (descending)
            df = df.sort_values('followers_count', ascending=False)

            # Add selection column
            df.insert(0, 'fetch_followers', False)

            # Save to CSV
            df.to_csv(MY_FOLLOWING_CSV, index=False)
            logger.info(f"Saved {len(df)} users to {MY_FOLLOWING_CSV}")

            # Display summary
            print("\n" + "="*50)
            print("SUMMARY STATISTICS")
            print("="*50)
            print(f"Total users you follow: {len(df)}")
            print(f"Verified users: {df['verified'].sum()}")
            print(f"Blue verified users: {df['blue_verified'].sum()}")
            print(f"\nTop 10 most followed users:")
            print("-"*50)

            for idx, row in df.head(10).iterrows():
                print(f"{row['display_name']} (@{row['username']})")
                print(f"  Followers: {row['followers_count']:,}")
                if row['bio']:
                    print(f"  Bio: {row['bio'][:100]}..." if len(row['bio']) > 100 else f"  Bio: {row['bio']}")
                print()

            print("\n" + "="*50)
            print(f"Data saved to: {MY_FOLLOWING_CSV}")
            print("Edit the 'fetch_followers' column to select users")
            print("="*50)
        else:
            logger.error("No following data collected")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)

    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())