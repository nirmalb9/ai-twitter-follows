#!/usr/bin/env python3
"""
Fetch who each operator follows.
Creates a mapping of operator -> people they follow.
"""

import asyncio
import logging
import pandas as pd
from pathlib import Path
from playwright.async_api import async_playwright

from config import (
    X_USERNAME, X_EMAIL, X_PASSWORD,
    DATA_DIR, FOLLOWING_DIR,
    logger
)


class OperatorFollowingScraper:
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

    async def fetch_user_following(self, username, max_following=500):
        """Fetch who a specific user follows."""
        logger.info(f"Fetching following list for @{username}...")

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
                    logger.info(f"No new users found for @{username}, stopping at {current_count}")
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
    """Main execution function."""
    operators_file = DATA_DIR / 'operators.txt'
    if not operators_file.exists():
        logger.error(f"{operators_file} not found!")
        return

    with open(operators_file, 'r') as f:
        operators = [line.strip() for line in f.readlines() if line.strip()]

    logger.info(f"Found {len(operators)} operators to process")

    scraper = OperatorFollowingScraper()

    try:
        logger.info("Starting browser...")
        await scraper.start(headless=False)

        await scraper.login()

        all_relationships = []

        for i, operator in enumerate(operators, 1):
            print(f"\n{'='*50}")
            print(f"Processing operator {i}/{len(operators)}: @{operator}")
            print('='*50)

            # Check if we already have data for this operator
            output_file = FOLLOWING_DIR / f"{operator}_following.csv"
            if output_file.exists():
                logger.info(f"Loading existing data for @{operator}")
                df = pd.read_csv(output_file)
                for _, row in df.iterrows():
                    all_relationships.append({
                        'operator': operator,
                        'follows': row['username'],
                        'follows_display_name': row.get('display_name', '')
                    })
            else:
                following = await scraper.fetch_user_following(operator)

                if following:
                    df = pd.DataFrame(following)
                    df.to_csv(output_file, index=False)
                    logger.info(f"Saved {len(following)} following for @{operator} to {output_file}")

                    for person in following:
                        all_relationships.append({
                            'operator': operator,
                            'follows': person['username'],
                            'follows_display_name': person.get('display_name', '')
                        })

                if i < len(operators):
                    logger.info(f"Waiting 3 seconds...")
                    await asyncio.sleep(3)

        if all_relationships:
            relationships_df = pd.DataFrame(all_relationships)
            output_path = DATA_DIR / 'operator_following_network.csv'
            relationships_df.to_csv(output_path, index=False)
            logger.info(f"\nSaved {len(relationships_df)} relationships to {output_path}")

            follow_counts = relationships_df['follows'].value_counts()
            print("\n" + "="*50)
            print("TOP 20 MOST FOLLOWED ACCOUNTS BY OPERATORS")
            print("="*50)
            for username, count in follow_counts.head(20).items():
                percentage = (count / len(operators)) * 100
                print(f"{count:3d} operators ({percentage:5.1f}%) follow @{username}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)

    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
