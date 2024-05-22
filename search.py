import asyncio
import json
import random
from concurrent.futures import ThreadPoolExecutor
import aiohttp
import discord
from bs4 import BeautifulSoup
from datetime import datetime
from SearchManager import SearchManager
from helpers import tprint
from discord.ext import commands
from logger import *
from DatabaseManager import *

load_dotenv()
HEADERS = {
    'authority': 'www.facebook.com',
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,'
              'application/signed-exchange;v=b3;q=0.7',
    'accept-language': 'en-US,en;q=0.9',
    'sec-fetch-mode': 'navigate',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0',
}
search_manager = SearchManager()

executor = ThreadPoolExecutor()


async def async_json_dumps(data):
    logging.debug("🔄 Starting async JSON serialization...")
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, json.dumps, data)
    logging.debug("✅ Completed async JSON serialization", extra={'indent': True})
    return result


class PersistentViewBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned_or("!"), intents=intents)

    async def setup_hook(self) -> None:
        self.add_view(BlockButton())


bot = PersistentViewBot()


class BlockButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.seller_name = ""
        self.blocked = False  # Initialize the state

    @discord.ui.button(label="Block Seller", style=discord.ButtonStyle.danger, custom_id="block_button")
    async def block_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logging.debug("🔲 Block/Unblock button pressed")
        with DatabaseManager() as db:
            # Check if already blocked
            if not self.blocked:
                message = interaction.message
                if message.embeds:
                    self.seller_name = message.embeds[0].fields[3].value
                    logging.info(f"🚫 {self.seller_name} blocked")
                    # Block the seller
                    db.execute_query('INSERT INTO blocked_sellers (name) VALUES (?)', (self.seller_name,))
                    button.label = "Unblock Seller"  # Change the button label
                    button.style = discord.ButtonStyle.success  # Change the button style to green
                    self.blocked = True  # Update the state
                    response_message = f"Blocked {self.seller_name}"
            else:
                message = interaction.message
                if message.embeds:
                    self.seller_name = message.embeds[0].fields[3].value
                    logging.info(f"🔓 {self.seller_name} unblocked")
                    # Unblock the seller
                    db.execute_query('DELETE FROM blocked_sellers WHERE name = ?', (self.seller_name,))
                    button.label = "Block Seller"  # Change the button label back
                    button.style = discord.ButtonStyle.danger  # Change the button style to red
                    self.blocked = False  # Update the state
                    response_message = f"Unblocked {self.seller_name}"

        # Update the message with the new button label and style
        await interaction.response.edit_message(view=self)
        logging.debug("🔲 Button appearance updated")

        # Send a follow-up message with the action confirmation
        await interaction.followup.send(response_message, ephemeral=True)
        logging.debug("📩 Follow-up message sent")


# Define a function to send a message to a Discord channel
async def send_discord_message(channel_id, embed, view):
    def log_message(message, level="info", failed=False):
        """Helper function to handle logging with different levels and indentation."""
        if DEBUG == "DEBUG":
            extra = {'indent': True} if failed else {}
            getattr(logging, level)(f"❌{message}❌" if failed else f"📬{message}📬", extra=extra)
        else:
            getattr(logging, level)(f"❌ {message}" if failed else f"📬 {message}")

    logging.debug(f"📨 Sending message to {channel_id}")
    channel = bot.get_channel(channel_id)

    if channel:
        await channel.send(embed=embed, view=view)  # Send the embed and button
        log_message("Message Sent", "info")
    else:
        log_message("Message Failed", "error", failed=True)


def find_relevant_script(soup):
    logging.debug("🔍 Searching for relevant script...")
    for script in reversed(soup.find_all('script', {'type': 'application/json', 'data-sjs': True})):
        if '"marketplace_listing_category_name":"Rentals"' in script.string:
            logging.debug("rental... skipping")
            return None
        if ('qplTimingsServerJS' not in script.string and
                'null' not in script.string[:40] and
                'creation_time' in script.string):
            logging.debug("📌 Relevant script found", extra={'indent': True})
            return script
    logging.debug("⚠️ No relevant script found", extra={'indent': True})
    return None


def parse_listing_json(json_data):
    logging.debug("📊 Parsing listing JSON...")
    try:
        for entry in json_data['require']:
            if entry[0] == 'ScheduledServerJS':
                listing_info = entry[-1][0]['__bbox']['require'][3][3][1]['__bbox']['result']['data']['viewer'][
                    'marketplace_product_details_page']['target']
                creation_time = listing_info['creation_time']
                date_object = datetime.fromtimestamp(creation_time)
                creation_time = date_object.strftime('%I:%M%p %m/%d/%Y')
                description = f'"{listing_info["redacted_description"]["text"].strip()}"'
                seller_id = json.loads(listing_info['story']['tracking'])['actrs']
                location_coords = [listing_info['location']['latitude'], listing_info['location']['longitude']]
                photo_urls = [photo['image']['uri'] for photo in listing_info['listing_photos']]
                logging.debug("✅ JSON parsing successful", extra={'indent': True})
                return creation_time, description, seller_id, location_coords, photo_urls
    except (KeyError, IndexError, TypeError):
        logging.error("❌ JSON parsing failed: {e}", extra={'indent': True})
        return None


def check_db(listing_id):
    logging.debug("🔎 Searching listing in DB...")
    with DatabaseManager() as db:
        db.execute_query("SELECT listing_id FROM listings WHERE listing_id = ?", (listing_id,))
        result = db.fetch_one()
        logging.debug(f"{'🗃️ Old Listing:🚫 Skipping 🚫' if result else '🆕 New Listing:🟢 Proceeding 🟢'}",
                      extra={'indent': True})
        return result is not None


class MarketplaceListing:
    def __init__(self, listing_data, query):
        self.listing_query = query
        self.listing_id = listing_data.get('id', '')
        primary_photo = listing_data.get('primary_listing_photo', {}).get('image', {})
        self.image_url = primary_photo.get('uri', '')
        self.price = listing_data.get('listing_price', {}).get('formatted_amount', '')
        location = listing_data.get('location', {}).get('reverse_geocode', {})
        self.location_city = location.get('city', '')
        self.location_state = location.get('state', '')
        seller = listing_data.get('marketplace_listing_seller', {})
        self.seller_name = seller.get('name', '')
        self.title = listing_data.get('marketplace_listing_title', '')
        self.post_url = f'https://www.facebook.com/marketplace/item/{self.listing_id}'
        self.creation_date = ''
        self.description = ''
        self.seller_url = ''
        self.gps_maps = []
        self.photo_urls = []

    async def get_listing_info(self):
        logging.debug(f"📤 Requesting listing info...")
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://www.facebook.com/marketplace/item/{self.listing_id}',
                                   headers=HEADERS) as response:
                logging.debug(f"✉️ Received response status: {response.status}",
                              extra={'indent': True})
                response_content = await response.read()
                soup = BeautifulSoup(response_content, 'html.parser')
                script_tag = find_relevant_script(soup)
                if script_tag:
                    json_data = json.loads(script_tag.string)
                    listing_info = parse_listing_json(json_data)
                    if listing_info:
                        logging.debug("🔄 Retrieving listing info")
                        str_photo_urls = await async_json_dumps(listing_info[4])
                        self.creation_date = listing_info[0]
                        self.description = listing_info[1]
                        self.seller_url = f'https://www.facebook.com/marketplace/profile/{listing_info[2]}/'
                        self.gps_maps = (f'https://www.google.com/maps/dir/39.7810794,-104.752027/'
                                         f'{listing_info[3][0]},{listing_info[3][-1]}')
                        self.photo_urls = str_photo_urls
                        logging.info("✅ Received listing info")
                    else:
                        logging.warning(f"⚠️ Listing info not found")
                else:
                    logging.warning(f"⚠️ Script tag not found")
                    return -1

    async def notify_discord(self, channel_id):
        logging.debug("🔔 Alerting discord")
        # Create an embed instance
        embed = discord.Embed(title=f"'{self.title}'", description=self.description, color=0x00ff00)
        embed.add_field(name="Query", value=self.listing_query, inline=False)
        embed.add_field(name="Price", value=self.price, inline=True)
        embed.add_field(name="Location", value=f"{self.location_city}, {self.location_state}", inline=True)
        embed.add_field(name="Seller", value=self.seller_name, inline=True)
        embed.add_field(name="Post URL", value=self.post_url, inline=False)
        embed.add_field(name="Seller URL", value=self.seller_url, inline=False)
        embed.add_field(name="Maps", value=self.gps_maps, inline=False)

        # Define the format for the input time and date
        time_format = "%I:%M%p %m/%d/%Y"
        input_time = datetime.strptime(self.creation_date, time_format)
        current_time = datetime.now()
        time_difference = current_time - input_time
        _minutes_ago = round(time_difference.total_seconds() / 60)

        embed.set_footer(text=self.creation_date + f" - {_minutes_ago} minutes ago")  # Optional footer text
        embed.set_image(url=self.image_url)
        view = BlockButton()

        # Assuming send_discord_message is properly handling rate limits
        try:
            await send_discord_message(channel_id, embed, view)
            logging.debug(f"📢 Alert successfully sent to Discord channel ID: {channel_id}")
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = e.retry_after  # The library should provide retry_after
                logging.warning(
                    f"⏳ Rate limited by Discord. Retrying after {retry_after:.2f} seconds")
                await asyncio.sleep(retry_after)
                await send_discord_message(channel_id, embed, view)  # Attempt to send again
            else:
                raise  # Re-raise the exception if it's not a rate limit issue

    async def save_to_db(self, channel_id):
        logging.debug(f"📝 Saving listing {self.listing_id} to database")
        with DatabaseManager() as db:
            db.execute_query('''CREATE TABLE IF NOT EXISTS listings
                         (listing_id TEXT PRIMARY KEY, title TEXT, image_url TEXT, price TEXT, 
                          location_city TEXT, location_state TEXT, seller_name TEXT, 
                          post_url TEXT, creation_date TEXT, description TEXT, 
                          seller_url TEXT, gps_maps TEXT, photo_urls TEXT)''')
            db.execute_query('''INSERT OR REPLACE INTO listings
                         (listing_id, title, image_url, price, location_city, location_state, 
                          seller_name, post_url, creation_date, description, seller_url, gps_maps, photo_urls)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                             (self.listing_id, self.title, self.image_url, self.price,
                              self.location_city, self.location_state, self.seller_name,
                              self.post_url, self.creation_date, self.description,
                              self.seller_url, self.gps_maps, self.photo_urls))
        logging.debug(f"💾Saved💾")
        await self.notify_discord(channel_id)

    def print_listing(self):
        logging.debug("🖨️ Printing listing info...")
        tprint(f"Title: {self.title}")
        tprint(f"ID: {self.listing_id}")
        tprint(f"Image URL: {self.image_url}")
        tprint(f"Price: {self.price}")
        tprint(f"City: {self.location_city}")
        tprint(f"State: {self.location_state}")
        tprint(f"Seller Name: {self.seller_name}")
        tprint(f"Post URL: {self.post_url}")
        tprint(f"Creation Date: {self.creation_date}")
        tprint(f"Description: {self.description}")
        tprint(f"Seller URL: {self.seller_url}")
        tprint(f"Google Maps: {self.gps_maps}")
        tprint(f"Photo URLs: {json.dumps(self.photo_urls)}")
        logging.info("🖨️ Printed listing info")


async def search_marketplace(query, max_price, channel_id):
    start = time.time()
    listings_added = 0
    logging.info(f"🔎 Searching for \033[1;3m{query}...")
    params = {
        'daysSinceListed': '1',
        'deliveryMethod': 'local_pick_up',
        'sortBy': 'creation_time_descend',
        'query': query,
        'exact': 'true',
        'radius': '41',  # change to 90 later
        'maxPrice': max_price
    }
    async with aiohttp.ClientSession() as session:
        async with session.get('https://www.facebook.com/marketplace/denver/search', headers=HEADERS,
                               params=params) as response:
            response_text = await response.text()
            soup = BeautifulSoup(response_text, 'html.parser')
            logging.info(f"⚙️ Search params: {params}.",
                         extra={'indent': True})
            logging.info(f"🔗 Search url: {response.url}",
                         extra={'indent': True})
            logging.info(f"📶 Search response status: {response.status}",
                         extra={'indent': True})

    script_tags = soup.find_all('script', {'type': 'application/json', 'data-sjs': True})
    logging.debug("📊 Parsing search JSON...")
    for script in script_tags:
        results = parse_search_json(script)
        if results:
            for listing_data in results:
                if 'node' in listing_data:
                    if 'listing' in listing_data['node']:
                        listing_data = listing_data['node']['listing']
                        listing = MarketplaceListing(listing_data, query)
                        blocked_sellers = []
                        skipped_keywords = []
                        skipped_cities = ['Colorado Springs', "Monument", "Fort Collins", "Peyton", "Pueblo", "Greeley"]
                        special_words = ["free", "today"]  # Queries to skip when they appear next to skipped keywords
                        searches = search_manager.get_all_searches()

                        with DatabaseManager() as db:
                            # Retrieve banned sellers
                            db.execute_query('SELECT name FROM blocked_sellers')
                            rows = db.fetch_all()
                            blocked_sellers.extend([row[0] for row in rows])

                            # Retrieve skipped keywords
                            db.execute_query('SELECT keyword FROM blacklisted_keywords')
                            rows = db.fetch_all()
                            skipped_keywords.extend(row[0] for row in rows)

                        logging.debug(f"📌 Found listing ({listing.listing_id:>16}): ")
                        if listing.seller_name in blocked_sellers:
                            logging.debug(f"Seller blocked: {listing.seller_name}...🚫Skipped🚫", extra={'indent': True})
                            continue
                            # Your existing condition, modified to use the special_words list
                        elif any(keyword.lower() in (listing.title + " " + listing.description).lower() for keyword in
                                 skipped_keywords) and not any(
                                keyword.lower() in listing.description.lower() for keyword in searches if
                                keyword.lower() not in special_words):
                            logging.debug("Listing contains blacklisted keywords...🚫Skipped🚫", extra={'indent': True})
                            continue
                        elif listing.location_city in skipped_cities:
                            logging.debug("Listing is too far...🚫Skipped🚫", extra={'indent': True})
                            continue
                        else:
                            if not check_db(listing.listing_id):
                                logging.info(f"🆕 Created MarketplaceListing for \033[1m{listing.title}\033[0m")
                                if await listing.get_listing_info() == -1:
                                    logging.warning("rental... skipping")
                                    continue
                                # listing.print_listing()
                                await listing.save_to_db(channel_id)
                                listings_added += 1
                                logging.info("✅ Added new listing to DB")
                    else:
                        logging.info(f"🚫 No search results found")
                    if listings_added == 0:
                        logging.info("❌ No new listings added")
                    else:
                        logging.info(f"➕ {listings_added} listings added")
                    stop = time.time()
                    logging.info(f"❇️ Search completed in {stop - start:.2f} seconds ❇️")
                    return listings_added


def parse_search_json(script):
    try:
        json_data = json.loads(script.string)
        json_data = json_data['require'][0]
        if "ScheduledServerJS" in json_data[0]:
            json_data = json_data[-1][0]['__bbox']['require'][0][-1]
            if 'MarketplaceSearchContent' in json_data[0]:
                logging.debug("✅ Parsing search JSON successful", extra={'indent': True})
                return json_data[-1]['__bbox']['result']['data']['marketplace_search']['feed_units']['edges']
    except json.JSONDecodeError:
        logging.error("❌ JSON decoding failed", extra={'indent': True})
        pass
    return None


# The background task for searching the marketplace
async def background_search_marketplace():
    await bot.wait_until_ready()
    while not bot.is_closed():
        current_time = datetime.now()
        if 0 <= current_time.hour < 7:
            # Calculate how many seconds to wait until 7 AM
            wait_time = ((7 - current_time.hour) * 3600) - (current_time.minute * 60) - current_time.second
            logging.info(f"🌙 It's currently {current_time.strftime('%H:%M:%S')}. Sleeping until 7 AM.")
            await asyncio.sleep(wait_time)
            continue  # Skip the rest of the loop and check again after waiting
        logging.debug("👟 Running background search...")

        command = search_manager.get_next_search()
        if command is not None:
            query = command[1]
            max_price = command[2]
            channel_id = command[3]
            channel_name = bot.get_channel(channel_id)
            logging.debug(
                f"📝 Received search command: Query='{query}', Max Price={max_price}, Channel={channel_name}")
            listings_added = await search_marketplace(query, max_price, channel_id)
            if not listings_added:
                listings_added = 0
            base_interval = .25
            max_interval = 2
            search_manager.search_interval = round(
                random.uniform(base_interval, min(base_interval + (listings_added * 0.75), max_interval)), 2)
            logging.info(f"💤 Sleeping for {search_manager.search_interval} minutes at"
                         f" {datetime.now().strftime('%H:%M:%S')}...")
            await asyncio.sleep(search_manager.search_interval * 60)
            logging.info(f"☀️ Waking at {datetime.now().strftime('%H:%M:%S')}")


@bot.command(name='search')
async def search_command(ctx, *, params: str = None):
    logging.debug(f"⚙️ Processing search command")
    if not params or ',' not in params:
        # Send an error message showing the correct command format
        await ctx.send("Incorrect format. Please use the command like this: `!search <query>, <price>`\n"
                       "Example: `!search vise, 30`", ephemeral=True)
        logging.warning("🚨 [SEARCH COMMAND] Incorrect format received")
    query, price = params.split(',', 1)
    query = query.strip()
    price = price.strip()
    channel_id = ctx.channel.id
    # Assuming search_manager is an instance of some class managing search operations
    search_manager.add_search(query, price, channel_id)
    await ctx.send(f"Search for '{query}' added")
    logging.info(f"➕ Search for '{query}' added")


@bot.command(name='remove')
async def remove_command(ctx, *, query: str = None):
    logging.debug(f"⚙️ Processing remove command")
    if not query:
        # Send an error message showing the correct command format
        await ctx.send("Incorrect format. Please use the command like this: `!remove <query>`\n"
                       "Example: `!search vise`", ephemeral=True)
        logging.warning("🚨 [REMOVE COMMAND] Incorrect format received")

    channel_id = ctx.channel.id
    search_manager.delete_search(query, channel_id)
    await ctx.send(f"Search for '{query}' removed")
    logging.info(f"➖ Search for '{query}' removed")


@bot.event
async def on_ready():
    logging.info(f"🤖 {bot.user} connected!")
    await bot.loop.create_task(background_search_marketplace())


bot.run(os.getenv('TOKEN'))
