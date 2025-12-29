#!/usr/bin/env python3
"""
Scrape members from an X/Twitter list and add their following networks.
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


class ListMemberScraper:
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

        logger.info("Entering username...")
        username_input = await self.page.wait_for_selector('input[autocomplete="username"]', timeout=10000)
        await username_input.fill(X_USERNAME)
        await self.page.wait_for_timeout(1000)

        next_button = await self.page.wait_for_selector('text=Next', timeout=5000)
        await next_button.click()
        await self.page.wait_for_timeout(2000)

        # Check for email verification
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

        logger.info("Entering password...")
        password_input = await self.page.wait_for_selector('input[type="password"]', timeout=10000)
        await password_input.fill(X_PASSWORD)
        await self.page.wait_for_timeout(1000)

        login_button = await self.page.wait_for_selector('text=Log in', timeout=5000)
        await login_button.click()

        logger.info("Waiting for login to complete...")
        await self.page.wait_for_selector('a[href="/home"]', timeout=30000)
        logger.info("Login successful!")

    async def fetch_list_members(self, list_id):
        """Fetch all members from a list."""
        logger.info(f"Fetching members from list {list_id}...")

        await self.page.goto(f'https://x.com/i/lists/{list_id}/members')
        await self.page.wait_for_timeout(3000)

        # Wait for the modal/dialog with list members
        try:
            # Wait for the modal container with members
            await self.page.wait_for_selector('[aria-labelledby]', timeout=5000)
            await self.page.wait_for_selector('[data-testid="UserCell"]', timeout=5000)
            logger.info("Modal with list members loaded")
        except:
            logger.warning("Could not load list members modal")
            return []

        # Find ALL scrollable containers inside the modal
        scrollable_divs = await self.page.evaluate('''
            () => {
                const allDivs = Array.from(document.querySelectorAll('div'));
                const scrollables = allDivs.filter(div => {
                    const style = window.getComputedStyle(div);
                    return (style.overflowY === 'scroll' || style.overflowY === 'auto') && div.scrollHeight > div.clientHeight;
                });
                return scrollables.map((div, idx) => ({
                    index: idx,
                    scrollHeight: div.scrollHeight,
                    clientHeight: div.clientHeight,
                    hasUserCells: div.querySelector('[data-testid="UserCell"]') !== null
                }));
            }
        ''')

        logger.info(f"Found {len(scrollable_divs)} scrollable containers")
        for div_info in scrollable_divs:
            logger.info(f"  Scrollable {div_info['index']}: scrollHeight={div_info['scrollHeight']}, clientHeight={div_info['clientHeight']}, hasUserCells={div_info['hasUserCells']}")

        members = []
        seen_users = set()

        last_count = 0
        no_new_users_count = 0
        max_no_new = 10
        max_scrolls = 200

        scroll_count = 0
        while scroll_count < max_scrolls:
            user_cells = await self.page.query_selector_all('[data-testid="UserCell"]')

            for cell in user_cells:
                try:
                    user_link = await cell.query_selector('a[role="link"][href^="/"]')
                    if not user_link:
                        continue

                    href = await user_link.get_attribute('href')
                    if not href or href == '/' or '/status/' in href:
                        continue

                    username = href.strip('/')

                    if not username or '/' in username:
                        continue

                    if username not in seen_users:
                        display_name = ''
                        name_element = await cell.query_selector('[dir="ltr"] > span > span')
                        if name_element:
                            display_name = await name_element.inner_text()

                        members.append({
                            'username': username,
                            'display_name': display_name
                        })
                        seen_users.add(username)

                except Exception as e:
                    logger.debug(f"Error extracting user: {e}")

            current_count = len(members)

            if current_count == last_count:
                no_new_users_count += 1
                if no_new_users_count >= max_no_new:
                    logger.info(f"No new members found after {scroll_count} scrolls, stopping at {current_count}")
                    break
            else:
                no_new_users_count = 0

            last_count = current_count
            scroll_count += 1

            # Log progress every 10 scrolls
            if scroll_count % 10 == 0:
                logger.info(f"Scroll {scroll_count}: Found {current_count} members so far...")

            # Scroll ALL scrollable divs that contain UserCells
            await self.page.evaluate('''
                () => {
                    const allDivs = Array.from(document.querySelectorAll('div'));
                    const scrollables = allDivs.filter(div => {
                        const style = window.getComputedStyle(div);
                        return (style.overflowY === 'scroll' || style.overflowY === 'auto') && div.scrollHeight > div.clientHeight;
                    });
                    scrollables.forEach(div => {
                        if (div.querySelector('[data-testid="UserCell"]')) {
                            div.scrollTop = div.scrollHeight;
                        }
                    });
                }
            ''')

            await self.page.wait_for_timeout(1500)

        logger.info(f"Extracted {len(members)} list members")
        return members

    async def fetch_user_following(self, username, max_following=500):
        """Fetch who a user follows."""
        logger.info(f"Fetching following for @{username}...")

        await self.page.goto(f'https://x.com/{username}/following')
        await self.page.wait_for_timeout(3000)

        try:
            await self.page.wait_for_selector('[data-testid="UserCell"]', timeout=5000)
        except:
            logger.warning(f"Could not load following for @{username}")
            return []

        following_list = []
        seen_users = set()

        last_count = 0
        no_new_users_count = 0
        max_no_new = 3

        while len(following_list) < max_following:
            user_cells = await self.page.query_selector_all('[data-testid="UserCell"]')

            for cell in user_cells:
                if len(following_list) >= max_following:
                    break

                try:
                    user_link = await cell.query_selector('a[role="link"][href^="/"]')
                    if not user_link:
                        continue

                    href = await user_link.get_attribute('href')
                    if not href or href == '/' or '/status/' in href:
                        continue

                    followed_username = href.strip('/')

                    if not followed_username or '/' in followed_username:
                        continue

                    if followed_username not in seen_users:
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
                    logger.debug(f"Error extracting user: {e}")

            current_count = len(following_list)

            if current_count == last_count:
                no_new_users_count += 1
                if no_new_users_count >= max_no_new:
                    logger.info(f"No new users for @{username}, stopping at {current_count}")
                    break
            else:
                no_new_users_count = 0

            last_count = current_count

            await self.page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await self.page.wait_for_timeout(2000)

        logger.info(f"Extracted {len(following_list)} following for @{username}")
        return following_list

    async def close(self):
        """Close browser."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()


async def main():
    """Main execution."""
    LIST_ID = "2005747855567511884"

    # Load existing network data
    network_file = DATA_DIR / 'researcher_following_network.csv'
    if network_file.exists():
        existing_network = pd.read_csv(network_file)
        already_scraped = set(existing_network['researcher'].unique())
        logger.info(f"Found {len(already_scraped)} already scraped users")
    else:
        existing_network = pd.DataFrame()
        already_scraped = set()
        logger.info("No existing network data found")

    # Initialize scraper
    scraper = ListMemberScraper()

    try:
        logger.info("Starting browser...")
        await scraper.start(headless=False)

        await scraper.login()

        # Fetch list members
        members = await scraper.fetch_list_members(LIST_ID)

        if not members:
            logger.error("No members found!")
            return

        logger.info(f"Found {len(members)} members in the list")

        # Filter for new members
        member_usernames = [m['username'] for m in members]
        new_members = [m for m in members if m['username'] not in already_scraped]

        logger.info(f"New members to scrape: {len(new_members)}")

        if len(new_members) == 0:
            logger.info("All members already scraped!")
            return

        # Store all new relationships
        new_relationships = []

        # Process each new member
        for i, member in enumerate(new_members, 1):
            username = member['username']
            print(f"\n{'='*50}")
            print(f"Processing {i}/{len(new_members)}: @{username}")
            print('='*50)

            # Check if individual file exists
            output_file = FOLLOWING_DIR / f"{username}_following.csv"
            if output_file.exists():
                logger.info(f"Loading existing data for @{username}")
                df = pd.read_csv(output_file)
                for _, row in df.iterrows():
                    new_relationships.append({
                        'researcher': username,
                        'follows': row['username'],
                        'follows_display_name': row.get('display_name', '')
                    })
            else:
                # Fetch following
                following = await scraper.fetch_user_following(username)

                if following:
                    # Save individual file
                    df = pd.DataFrame(following)
                    df.to_csv(output_file, index=False)
                    logger.info(f"Saved {len(following)} following to {output_file}")

                    # Add to relationships
                    for person in following:
                        new_relationships.append({
                            'researcher': username,
                            'follows': person['username'],
                            'follows_display_name': person.get('display_name', '')
                        })

                # Delay between users
                if i < len(new_members):
                    logger.info("Waiting 3 seconds...")
                    await asyncio.sleep(3)

        # Append new relationships to existing network
        if new_relationships:
            new_df = pd.DataFrame(new_relationships)

            if not existing_network.empty:
                combined_network = pd.concat([existing_network, new_df], ignore_index=True)
            else:
                combined_network = new_df

            # Remove duplicates
            combined_network = combined_network.drop_duplicates()

            # Save combined network
            combined_network.to_csv(network_file, index=False)
            logger.info(f"\n✅ Saved {len(combined_network)} total relationships to {network_file}")
            logger.info(f"   Added {len(new_relationships)} new relationships")

            # Show stats
            follow_counts = combined_network['follows'].value_counts()
            print("\n" + "="*50)
            print("TOP 20 MOST FOLLOWED ACCOUNTS (UPDATED)")
            print("="*50)
            for username, count in follow_counts.head(20).items():
                total_users = combined_network['researcher'].nunique()
                percentage = (count / total_users) * 100
                print(f"{count:3d} users ({percentage:5.1f}%) follow @{username}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)

    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())