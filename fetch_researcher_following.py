#!/usr/bin/env python3
"""
Fetch who each researcher follows.
Creates a mapping of researcher -> people they follow.
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
    DATA_DIR, FOLLOWING_DIR,
    logger
)


class ResearcherFollowingScraper:
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

    async def fetch_user_following(self, username, max_following=500):
        """Fetch who a specific user follows."""
        logger.info(f"Fetching following list for @{username}...")

        # Navigate to following page
        await self.page.goto(f'https://x.com/{username}/following')
        await self.page.wait_for_timeout(3000)

        # Check if the page loaded correctly
        try:
            await self.page.wait_for_selector('[data-testid="UserCell"]', timeout=5000)
        except:
            logger.warning(f"Could not load following for @{username} (private or suspended?)")
            return []

        following_list = []
        seen_users = set()

        # Scroll and extract users
        last_count = 0
        no_new_users_count = 0
        max_no_new = 3

        while len(following_list) < max_following:
            # Get all user cells currently visible
            user_cells = await self.page.query_selector_all('[data-testid="UserCell"]')

            for cell in user_cells:
                if len(following_list) >= max_following:
                    break

                try:
                    # Extract username from the cell
                    user_link = await cell.query_selector('a[role="link"][href^="/"]')
                    if not user_link:
                        continue

                    href = await user_link.get_attribute('href')
                    if not href or href == '/' or '/status/' in href:
                        continue

                    followed_username = href.strip('/')

                    # Skip if it's not a valid username
                    if not followed_username or '/' in followed_username:
                        continue

                    if followed_username not in seen_users:
                        # Get display name
                        display_name = ''
                        name_element = await cell.query_selector('[dir="ltr"] > span > span')
                        if name_element:
                            display_name = await name_element.inner_text()

                        following_list.append({
                            'username': followed_username,
                            'display_name': display_name
                        })
                        seen_users.add(followed_username)

                except Exception as e:
                    logger.debug(f"Error extracting user from cell: {e}")

            current_count = len(following_list)

            # Check if we got new users
            if current_count == last_count:
                no_new_users_count += 1
                if no_new_users_count >= max_no_new:
                    logger.info(f"No new users found for @{username}, stopping at {current_count}")
                    break
            else:
                no_new_users_count = 0

            last_count = current_count

            # Scroll down
            await self.page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await self.page.wait_for_timeout(2000)

        logger.info(f"Extracted {len(following_list)} users for @{username}")
        return following_list

    async def close(self):
        """Close browser."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()


async def main():
    """Main execution function."""
    # Read researcher list
    researchers_file = DATA_DIR / 'researchers.txt'
    if not researchers_file.exists():
        logger.error(f"{researchers_file} not found!")
        return

    with open(researchers_file, 'r') as f:
        researchers = [line.strip() for line in f.readlines() if line.strip()]

    logger.info(f"Found {len(researchers)} researchers to process")

    # Initialize scraper
    scraper = ResearcherFollowingScraper()

    try:
        # Start browser
        logger.info("Starting browser...")
        await scraper.start(headless=False)

        # Login
        await scraper.login()

        # Store all following relationships
        all_relationships = []

        # Process each researcher
        for i, researcher in enumerate(researchers, 1):
            print(f"\n{'='*50}")
            print(f"Processing researcher {i}/{len(researchers)}: @{researcher}")
            print('='*50)

            # Check if we already have data for this researcher
            output_file = FOLLOWING_DIR / f"{researcher}_following.csv"
            if output_file.exists():
                logger.info(f"Loading existing data for @{researcher}")
                df = pd.read_csv(output_file)
                for _, row in df.iterrows():
                    all_relationships.append({
                        'researcher': researcher,
                        'follows': row['username'],
                        'follows_display_name': row.get('display_name', '')
                    })
            else:
                # Fetch who this researcher follows
                following = await scraper.fetch_user_following(researcher)

                if following:
                    # Save individual file
                    df = pd.DataFrame(following)
                    df.to_csv(output_file, index=False)
                    logger.info(f"Saved {len(following)} following for @{researcher} to {output_file}")

                    # Add to relationships
                    for person in following:
                        all_relationships.append({
                            'researcher': researcher,
                            'follows': person['username'],
                            'follows_display_name': person.get('display_name', '')
                        })

                # Add delay between users to avoid rate limiting
                if i < len(researchers):
                    logger.info(f"Waiting 3 seconds before next user...")
                    await asyncio.sleep(3)

        # Save combined relationships CSV
        if all_relationships:
            relationships_df = pd.DataFrame(all_relationships)
            output_path = DATA_DIR / 'researcher_following_network.csv'
            relationships_df.to_csv(output_path, index=False)
            logger.info(f"\nSaved {len(relationships_df)} relationships to {output_path}")

            # Calculate and show top followed accounts
            follow_counts = relationships_df['follows'].value_counts()
            print("\n" + "="*50)
            print("TOP 20 MOST FOLLOWED ACCOUNTS BY RESEARCHERS")
            print("="*50)
            for username, count in follow_counts.head(20).items():
                percentage = (count / len(researchers)) * 100
                print(f"{count:3d} researchers ({percentage:5.1f}%) follow @{username}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)

    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())