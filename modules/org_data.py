import sqlite3
import requests
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from groq import Groq
from bs4 import BeautifulSoup
from newsapi import NewsApiClient
import json
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
import re
import time

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")

class PartyDataFetcher:
    def __init__(self, db_path='political_parties.db'):
        self.db_path = db_path
        self.setup_database()
        self.news_api = NewsApiClient(api_key=NEWS_API_KEY)
        self.groq_client = Groq(api_key=GROQ_API_KEY)
        self.console = Console()

    def setup_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create "political_parties" table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS political_parties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            description TEXT,
            founded_date TEXT,
            headquarters TEXT,
            ideology TEXT,
            party_symbol TEXT,
            eci_status TEXT,
            alliance_name TEXT,
            last_updated TIMESTAMP
        )
        ''')

        # Create "party_leaders" table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS party_leaders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            party_id INTEGER,
            name TEXT,
            role TEXT,
            bio TEXT,
            start_date TEXT,
            end_date TEXT,
            last_updated TIMESTAMP,
            FOREIGN KEY (party_id) REFERENCES political_parties (id),
            UNIQUE(party_id, name, role)
        )
        ''')

        # Create "news_articles" table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            party_id INTEGER,
            title TEXT,
            content TEXT,
            source TEXT,
            published_date TIMESTAMP,
            url TEXT,
            FOREIGN KEY (party_id) REFERENCES political_parties (id)
        )
        ''')

        # Optional: Create a unique index on (party_id, url) for news_articles to avoid duplicates
        cursor.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_news_articles_party_id_url 
        ON news_articles (party_id, url)
        ''')

        conn.commit()
        conn.close()

    def fetch_search_results(self, party_name, num_results=10):
        google_results = self._fetch_google_results(party_name, num_results)
        specific_sites = [
            f"site:wikipedia.org {party_name}",
            f"site:eci.gov.in {party_name}",
            f"site:adrindia.org {party_name}",
            f"site:myneta.info {party_name}",
        ]
        all_results = google_results
        for site_query in specific_sites:
            results = self._fetch_google_results(site_query, 2)
            all_results.extend(results)
        return all_results

    def _fetch_google_results(self, query, num_results=5):
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            'key': GOOGLE_API_KEY,
            'cx': GOOGLE_CSE_ID,
            'q': query,
            'num': num_results
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json().get('items', [])
        except Exception as e:
            self.console.print(f"[red]Error fetching Google results: {str(e)}[/red]")
            return []

    def extract_content_from_url(self, url):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                              'AppleWebKit/537.36 (KHTML, like Gecko) '
                              'Chrome/111.0.0.0 Safari/537.36',
                'Accept': '*/*'
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                element.decompose()
            main_content = None
            content_priorities = [
                soup.find('main'),
                soup.find('article'),
                soup.find('div', {'class': re.compile(r'content|main|article', re.I)}),
                soup.find('div', {'id': re.compile(r'content|main|article', re.I)})
            ]
            for c in content_priorities:
                if c:
                    main_content = c
                    break
            if not main_content:
                main_content = soup.body if soup.body else soup
            text_blocks = []
            for paragraph in main_content.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                text = paragraph.get_text(strip=True)
                if text and len(text) > 20:
                    text_blocks.append(text)
            return '\n\n'.join(text_blocks)
        except Exception as e:
            self.console.print(f"[red]Error extracting content from {url}: {str(e)}[/red]")
            return ""

    def chunk_content(self, content, max_chars=4000):
        paragraphs = content.split('\n\n')
        chunks = []
        current_chunk = ""
        for paragraph in paragraphs:
            if len(current_chunk) + len(paragraph) < max_chars:
                current_chunk += paragraph + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = paragraph + "\n\n"
        if current_chunk:
            chunks.append(current_chunk)
        return chunks

    def normalize_role(self, role_str):
        if not role_str:
            return ""
        role_str = role_str.lower()
        return re.sub(r'\.', '', role_str).strip()

    def analyze_party_with_groq(self, party_name, content):
        """
        Feeds content chunks to GROQ for extracting structured data (including members).
        """
        chunks = self.chunk_content(content)
        all_results = []
        base_prompt = f"""
You are a strict JSON generator.
IMPORTANT: Return ONLY valid JSON and nothing else.
The JSON must have the following structure:

{{
  "description": "string",
  "founded_date": "string or null",
  "headquarters": "string or null",
  "ideology": "string or null",
  "members": [
    {{
      "name": "string",
      "role": "string",
      "bio": "string",
      "start_date": "string or null",
      "end_date": "string or null",
      "is_current": boolean
    }}
  ],
  "party_symbol": "string or null",
  "eci_status": "string or null",
  "alliance_name": "string or null"
}}

Your goal:
1. Identify as many party members/leaders as possible (MP, MLA, office bearers, etc.).
2. For each member, include role, bio, and any dates.
3. Use null if unknown.

Analyze the content about the party "{party_name}":
"""
        try:
            for i, chunk in enumerate(chunks):
                chunk_prompt = f"{base_prompt}\n\nContent Part {i+1}/{len(chunks)}:\n{chunk}"
                response = self.groq_client.chat.completions.create(
                    model="llama-3.2-3b-preview",
                    messages=[{"role": "user", "content": chunk_prompt}],
                    temperature=0.0,
                    max_tokens=2000
                )
                try:
                    result = json.loads(response.choices[0].message.content)
                    all_results.append(result)
                except json.JSONDecodeError:
                    self.console.print(f"[yellow]Warning: Could not parse JSON from chunk {i+1}[/yellow]")
                time.sleep(1)
            return self.merge_analysis_results(all_results)
        except Exception as e:
            self.console.print(f"[red]Error with Groq API: {str(e)}[/red]")
            return None

    def merge_analysis_results(self, results):
        """
        Merges multiple JSON results returned by GROQ into one final structured dict.
        """
        if not results:
            return None
        merged = {
            "description": "",
            "founded_date": None,
            "headquarters": None,
            "ideology": None,
            "members": [],
            "party_symbol": None,
            "eci_status": None,
            "alliance_name": None
        }
        seen_members = set()
        for r in results:
            # Merge the longest 'description' text
            if r.get('description') and len(r['description']) > len(merged['description']):
                merged['description'] = r['description']

            # Merge only if the field in 'merged' is not yet set
            for fld in ['founded_date', 'headquarters', 'ideology', 'party_symbol', 'eci_status', 'alliance_name']:
                if not merged[fld] and r.get(fld):
                    merged[fld] = r[fld]

            # Merge unique members
            for m in r.get('members', []):
                name = m.get('name', '').strip()
                role_norm = self.normalize_role(m.get('role'))
                key = f"{name.lower()}:{role_norm}"
                if name and key not in seen_members:
                    seen_members.add(key)
                    merged['members'].append(m)
        return merged

    def fetch_news_data(self, party_name):
        """
        Fetches the recent news articles about 'party_name' from the News API,
        but limits the number returned via 'page_size'.
        """
        try:
            from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            news = self.news_api.get_everything(
                q=party_name,
                from_param=from_date,
                language='en',
                sort_by='relevancy',
                page_size=5
            )
            return news.get('articles', [])
        except Exception as e:
            self.console.print(f"[red]Error fetching news: {str(e)}[/red]")
            return []


    def print_party_info(self, party_name, party_data, news_articles):
        self.console.print("\n")
        self.console.print(Panel(f"[bold blue]{party_name}[/bold blue]", expand=False))
        if party_data.get('description'):
            self.console.print("\n[bold]Description:[/bold]")
            self.console.print(party_data['description'])

        details_table = Table(show_header=False)
        details_table.add_column("Field", style="bold")
        details_table.add_column("Value")
        if party_data.get('founded_date'):
            details_table.add_row("Founded", party_data['founded_date'])
        if party_data.get('headquarters'):
            details_table.add_row("Headquarters", party_data['headquarters'])
        if party_data.get('ideology'):
            details_table.add_row("Ideology", party_data['ideology'])
        if party_data.get('party_symbol'):
            details_table.add_row("Party Symbol", party_data['party_symbol'])
        if party_data.get('eci_status'):
            details_table.add_row("ECI Status", party_data['eci_status'])
        if party_data.get('alliance_name'):
            details_table.add_row("Alliance", party_data['alliance_name'])

        self.console.print("\n[bold]Party Details:[/bold]")
        self.console.print(details_table)

        if party_data.get('members'):
            self.console.print("\n[bold]Leadership & Key Members:[/bold]")
            mt = Table(show_header=True, header_style="bold magenta")
            mt.add_column("Name")
            mt.add_column("Role")
            mt.add_column("Status")
            mt.add_column("Bio", width=50)
            for member in party_data['members']:
                status = "Current" if member.get('is_current', True) else "Former"
                sd = member.get('start_date')
                ed = member.get('end_date')
                if sd and ed:
                    status += f" ({sd} - {ed})"
                elif sd:
                    status += f" (Since {sd})"
                mt.add_row(
                    member.get('name', 'N/A'),
                    member.get('role', 'N/A'),
                    status,
                    member.get('bio', 'N/A')
                )
            self.console.print(mt)

        if news_articles:
            self.console.print("\n[bold]Recent News & Updates:[/bold]")
            nt = Table(show_header=True, header_style="bold cyan")
            nt.add_column("Date")
            nt.add_column("Title", width=50)
            nt.add_column("Source")
            for article in news_articles[:5]:
                pub_date_raw = article.get('publishedAt')
                try:
                    d_obj = datetime.strptime(pub_date_raw, '%Y-%m-%dT%H:%M:%SZ')
                    d_str = d_obj.strftime('%Y-%m-%d')
                except:
                    d_str = pub_date_raw or 'Unknown'
                nt.add_row(
                    d_str,
                    article.get('title', 'N/A'),
                    article.get('source', {}).get('name', 'Unknown')
                )
            self.console.print(nt)

    def store_party_data(self, party_name, party_data, news_articles):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            # Insert or update party info
            cursor.execute('''
            INSERT INTO political_parties
            (name, description, founded_date, headquarters, ideology, party_symbol, eci_status, alliance_name, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description=excluded.description,
                founded_date=excluded.founded_date,
                headquarters=excluded.headquarters,
                ideology=excluded.ideology,
                party_symbol=excluded.party_symbol,
                eci_status=excluded.eci_status,
                alliance_name=excluded.alliance_name,
                last_updated=excluded.last_updated
            ''', (
                party_name,
                party_data.get('description'),
                party_data.get('founded_date'),
                party_data.get('headquarters'),
                party_data.get('ideology'),
                party_data.get('party_symbol'),
                party_data.get('eci_status'),
                party_data.get('alliance_name'),
                datetime.now()
            ))
            party_id = cursor.lastrowid

            # If we did an UPDATE instead of INSERT, get the existing ID
            if party_id == 0:
                cursor.execute('SELECT id FROM political_parties WHERE name=?', (party_name,))
                existing = cursor.fetchone()
                party_id = existing[0] if existing else None

            # Store leaders — with a simple check if they actually belong to the party
            for member in party_data.get('members', []):
                # Naive check: skip if the party name isn’t found in the role/bio
                combined_text = (member.get('role','') + member.get('bio','')).lower()
                if party_name.lower() not in combined_text:
                    continue

                cursor.execute('''
                INSERT INTO party_leaders
                (party_id, name, role, bio, start_date, end_date, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(party_id, name, role) DO UPDATE SET
                    bio=excluded.bio,
                    start_date=excluded.start_date,
                    end_date=excluded.end_date,
                    last_updated=excluded.last_updated
                ''', (
                    party_id,
                    member.get('name',''),
                    member.get('role',''),
                    member.get('bio',''),
                    member.get('start_date'),
                    member.get('end_date'),
                    datetime.now()
                ))

            # Store news — avoiding duplicates by using the unique index on (party_id, url)
            for article in news_articles:
                cursor.execute('''
                INSERT INTO news_articles
                (party_id, title, content, source, published_date, url)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(party_id, url) DO UPDATE SET
                    title=excluded.title,
                    content=excluded.content,
                    source=excluded.source,
                    published_date=excluded.published_date
                ''', (
                    party_id,
                    article.get('title'),
                    article.get('description'),
                    article.get('source', {}).get('name'),
                    article.get('publishedAt'),
                    article.get('url')
                ))

            conn.commit()
        except Exception as e:
            self.console.print(f"[red]Error storing data: {str(e)}[/red]")
            conn.rollback()
        finally:
            conn.close()

    def process_party(self, party_name):
        """
        Main workflow for processing the party:
          1. Fetch relevant search results, parse them into text.
          2. Fetch news articles & parse text from them too.
          3. Combine all text content into one big string.
          4. Send to GROQ for analysis.
          5. Store & display the results.
        """
        with self.console.status(f"[bold green]Processing {party_name}...[/bold green]"):
            try:
                # 1) Fetch Google results & parse content
                search_results = self.fetch_search_results(party_name, num_results=10)
                combined_content = ""
                if not search_results:
                    self.console.print("[red]No search results found[/red]")

                # Extract text from each top link
                for result in search_results[:10]:
                    link = result.get('link', '')
                    if link:
                        c = self.extract_content_from_url(link)
                        if c:
                            combined_content += f"\n\nSource: {link}\n{c[:5000]}"

                # 2) Fetch news articles
                news_articles = self.fetch_news_data(party_name)

                # Option A: Directly parse the 'description'/'content' from NewsAPI responses
                # Option B: Actually fetch each news article's URL (like with google) & parse it fully
                # Here, we'll do Option A for brevity:
                news_text = ""
                for art in news_articles:
                    # Combine any textual fields you want. 
                    # The 'content' field often might be truncated, so check which fields are available.
                    if art.get('title'):
                        news_text += f"Title: {art['title']}\n"
                    if art.get('description'):
                        news_text += f"{art['description']}\n\n"
                    # If 'content' is available, add it too
                    if art.get('content'):
                        news_text += f"{art['content']}\n\n"

                # Now append that news text to the combined_content
                combined_content += f"\n\n[News Articles]\n{news_text}"

                # If there's nothing at all in combined_content, skip
                if not combined_content.strip():
                    self.console.print(f"[yellow]No content extracted for {party_name}[/yellow]")
                    return

                # 3) Analyze via GROQ
                party_data = self.analyze_party_with_groq(party_name, combined_content)
                if not party_data:
                    self.console.print("[red]Failed to analyze party data[/red]")
                    return

                # 4) Store & print results
                self.store_party_data(party_name, party_data, news_articles)
                self.print_party_info(party_name, party_data, news_articles)

            except Exception as e:
                self.console.print(f"[red]Error processing party: {str(e)}[/red]")
                raise

def main():
    console = Console()
    fetcher = PartyDataFetcher()
    console.print("[bold blue]Indian Political Party Information Analyzer[/bold blue]")
    console.print("Enter a party name to analyze, or 'quit' to exit.\n")

    while True:
        try:
            party_name = console.input("[bold green]Enter political party name:[/bold green] ")
            if party_name.lower() == 'quit':
                console.print("[yellow]Exiting program...[/yellow]")
                break
            if not party_name.strip():
                console.print("[red]Please enter a valid party name.[/red]")
                continue
            fetcher.process_party(party_name.strip())
            console.print("\n[bold]Would you like to analyze another party?[/bold]")
            console.print("(Enter a new party name or 'quit' to exit)\n")
        except KeyboardInterrupt:
            console.print("\n[yellow]Program interrupted by user. Exiting...[/yellow]")
            break
        except Exception as e:
            console.print(f"[red]An unexpected error occurred: {str(e)}[/red]")
            console.print("[yellow]You can try another party or enter 'quit' to exit.[/yellow]\n")

if __name__ == "__main__":
    main()