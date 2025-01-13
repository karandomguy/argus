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

class OrganizationDataFetcher:
    def __init__(self, db_path='political_orgs.db'):
        self.db_path = db_path
        self.setup_database()
        self.news_api = NewsApiClient(api_key=NEWS_API_KEY)
        self.groq_client = Groq(api_key=GROQ_API_KEY)
        self.console = Console()
        
    def setup_database(self):
        """Create the necessary database tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            description TEXT,
            founded_date TEXT,
            headquarters TEXT,
            ideology TEXT,
            last_updated TIMESTAMP
        )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER,
            name TEXT,
            role TEXT,
            bio TEXT,
            start_date TEXT,
            end_date TEXT,
            last_updated TIMESTAMP,
            FOREIGN KEY (org_id) REFERENCES organizations (id),
            UNIQUE(org_id, name, role)
        )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER,
            title TEXT,
            content TEXT,
            source TEXT,
            published_date TIMESTAMP,
            url TEXT,
            FOREIGN KEY (org_id) REFERENCES organizations (id)
        )
        ''')

        conn.commit()
        conn.close()

    def fetch_search_results(self, org_name, num_results=5):
        """Fetch search results from multiple sources."""
        google_results = self._fetch_google_results(org_name, num_results)
        
        specific_sites = [
            f"site:eci.gov.in {org_name}",
            f"site:adrindia.org {org_name}",
            f"site:myneta.info {org_name}",
            f"site:prsindia.org {org_name}",
            f"site:elections.in {org_name}"
        ]

        all_results = google_results
        for site_query in specific_sites:
            results = self._fetch_google_results(site_query, 2)
            all_results.extend(results)
            
        return all_results

    def _fetch_google_results(self, query, num_results=5):
        """Helper method to fetch Google search results."""
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
        """Extract and clean content from a URL."""
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
            
            for content in content_priorities:
                if content:
                    main_content = content
                    break
            
            if not main_content:
                main_content = soup.body if soup.body else soup
            
            text_blocks = []
            for paragraph in main_content.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                text = paragraph.get_text(strip=True)
                if text and len(text) > 20:  # Ignore very short fragments
                    text_blocks.append(text)
            
            return '\n\n'.join(text_blocks)
        except Exception as e:
            self.console.print(f"[red]Error extracting content from {url}: {str(e)}[/red]")
            return ""

    def chunk_content(self, content, max_chars=4000):
        """Split content into manageable chunks."""
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

    def analyze_org_with_groq(self, org_name, content):
        """Analyze organization content using Groq API with content chunking."""
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
          ]
        }}

        Analyze the following content about {org_name} and fill in these fields with only factual info found in the text:
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
            
            merged_result = self.merge_analysis_results(all_results)
            return merged_result
            
        except Exception as e:
            self.console.print(f"[red]Error with Groq API: {str(e)}[/red]")
            return None

    def merge_analysis_results(self, results):
        """Merge results from multiple content chunks."""
        if not results:
            return None
            
        merged = {
            "description": "",
            "founded_date": None,
            "headquarters": None,
            "ideology": None,
            "members": []
        }
        
        seen_members = set()
        
        for result in results:
            if result.get('description') and len(result['description']) > len(merged['description']):
                merged['description'] = result['description']
            
            if not merged['founded_date'] and result.get('founded_date'):
                merged['founded_date'] = result['founded_date']
            if not merged['headquarters'] and result.get('headquarters'):
                merged['headquarters'] = result['headquarters']
            if not merged['ideology'] and result.get('ideology'):
                merged['ideology'] = result['ideology']
            
            for member in result.get('members', []):
                member_key = f"{member['name']}:{member.get('role', '')}"
                if member_key not in seen_members:
                    seen_members.add(member_key)
                    merged['members'].append(member)
        
        return merged

    def fetch_news_data(self, org_name):
        """Fetch recent news articles about the organization."""
        try:
            from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            news = self.news_api.get_everything(
                q=org_name,
                from_param=from_date,
                language='en',
                sort_by='relevancy'
            )
            return news.get('articles', [])
        except Exception as e:
            self.console.print(f"[red]Error fetching news: {str(e)}[/red]")
            return []

    def print_organization_info(self, org_name, org_data, news_articles):
        """Display formatted organization information."""
        self.console.print("\n")
        self.console.print(Panel(f"[bold blue]{org_name}[/bold blue]", expand=False))
        
        if org_data.get('description'):
            self.console.print("\n[bold]Description:[/bold]")
            self.console.print(org_data['description'])
        
        details_table = Table(show_header=False)
        details_table.add_column("Field", style="bold")
        details_table.add_column("Value")
        
        if org_data.get('founded_date'):
            details_table.add_row("Founded", org_data['founded_date'])
        if org_data.get('headquarters'):
            details_table.add_row("Headquarters", org_data['headquarters'])
        if org_data.get('ideology'):
            details_table.add_row("Ideology", org_data['ideology'])
            
        self.console.print("\n[bold]Organization Details:[/bold]")
        self.console.print(details_table)
        
        if org_data.get('members'):
            self.console.print("\n[bold]Leadership & Key Members:[/bold]")
            members_table = Table(show_header=True, header_style="bold magenta")
            members_table.add_column("Name")
            members_table.add_column("Role")
            members_table.add_column("Status")
            members_table.add_column("Bio", width=50)
            
            for member in org_data['members']:
                status = "Current" if member.get('is_current', True) else "Former"
                if member.get('start_date') and member.get('end_date'):
                    status += f" ({member['start_date']} - {member['end_date']})"
                elif member.get('start_date'):
                    status += f" (Since {member['start_date']})"
                
                members_table.add_row(
                    member.get('name', 'N/A'),
                    member.get('role', 'N/A'),
                    status,
                    member.get('bio', 'N/A')
                )
            self.console.print(members_table)
        
        if news_articles:
            self.console.print("\n[bold]Recent News & Updates:[/bold]")
            news_table = Table(show_header=True, header_style="bold cyan")
            news_table.add_column("Date")
            news_table.add_column("Title", width=50)
            news_table.add_column("Source")
            
            for article in news_articles[:5]:
                date = datetime.strptime(article['publishedAt'], '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d')
                news_table.add_row(
                    date,
                    article['title'],
                    article.get('source', {}).get('name', 'Unknown')
                )
            self.console.print(news_table)

    def store_organization_data(self, org_name, org_data, news_articles):
        """Store organization data in the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # ------------------------------------------------------------------
            # 1) INSERT or UPDATE the organization row FIRST
            # ------------------------------------------------------------------
            # ADDED THIS:
            cursor.execute('''
            INSERT INTO organizations
            (name, description, founded_date, headquarters, ideology, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description=excluded.description,
                founded_date=excluded.founded_date,
                headquarters=excluded.headquarters,
                ideology=excluded.ideology,
                last_updated=excluded.last_updated
            ''', (
                org_name,
                org_data.get('description'),
                org_data.get('founded_date'),
                org_data.get('headquarters'),
                org_data.get('ideology'),
                datetime.now()
            ))
            
            org_id = cursor.lastrowid
            if org_id == 0:
                # Means an update occurred, so fetch the existing org_id
                cursor.execute('SELECT id FROM organizations WHERE name=?', (org_name,))
                existing = cursor.fetchone()
                org_id = existing[0] if existing else None

            # ------------------------------------------------------------------
            # 2) Then insert or update members referencing that org_id
            # ------------------------------------------------------------------
            for member in org_data.get('members', []):
                cursor.execute('''
                INSERT INTO members
                (org_id, name, role, bio, start_date, end_date, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id, name, role) DO UPDATE SET
                    bio=excluded.bio,
                    start_date=excluded.start_date,
                    end_date=excluded.end_date,
                    last_updated=excluded.last_updated
                ''', (
                    org_id,
                    member['name'],
                    member.get('role'),
                    member.get('bio'),
                    member.get('start_date'),
                    member.get('end_date'),
                    datetime.now()
                ))

            # ------------------------------------------------------------------
            # 3) Insert news articles referencing that same org_id
            # ------------------------------------------------------------------
            for article in news_articles:
                cursor.execute('''
                INSERT INTO news_articles
                (org_id, title, content, source, published_date, url)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    org_id,
                    article['title'],
                    article.get('description'),
                    article.get('source', {}).get('name'),
                    article.get('publishedAt'),
                    article['url']
                ))

            conn.commit()

        except Exception as e:
            self.console.print(f"[red]Error storing data: {str(e)}[/red]")
            conn.rollback()
        finally:
            conn.close()

    def process_organization(self, org_name):
        """Main processing method with improved error handling."""
        with self.console.status(f"[bold green]Processing {org_name}...[/bold green]") as status:
            try:
                status.update(f"[bold green]Fetching information about {org_name}...[/bold green]")
                search_results = self.fetch_search_results(org_name, num_results=5)
                if not search_results:
                    self.console.print("[red]No search results found[/red]")
                    return
                
                status.update("[bold green]Analyzing content from sources...[/bold green]")
                combined_content = ""
                for result in search_results[:5]:
                    content = self.extract_content_from_url(result['link'])
                    if content:
                        combined_content += f"\n\nSource: {result['link']}\n{content[:5000]}"
                
                status.update("[bold green]Processing data with Groq API...[/bold green]")
                org_data = self.analyze_org_with_groq(org_name, combined_content)
                if not org_data:
                    self.console.print("[red]Failed to analyze organization data[/red]")
                    return
                
                status.update("[bold green]Gathering recent news...[/bold green]")
                news_articles = self.fetch_news_data(org_name)
                
                status.update("[bold green]Saving information...[/bold green]")
                # NOTE: This now actually inserts into organizations first, 
                # then members, then news
                self.store_organization_data(org_name, org_data, news_articles)
                
                # Finally, display results
                self.print_organization_info(org_name, org_data, news_articles)
                
            except Exception as e:
                self.console.print(f"[red]Error processing organization: {str(e)}[/red]")
                raise

def main():
    """Main execution function with error handling and user interface."""
    console = Console()
    fetcher = OrganizationDataFetcher()
    
    console.print("[bold blue]Political Organization Information Analyzer[/bold blue]")
    console.print("Enter an organization name to analyze, or 'quit' to exit.\n")
    
    while True:
        try:
            org_name = console.input("[bold green]Enter organization name:[/bold green] ")
            if org_name.lower() == 'quit':
                console.print("[yellow]Exiting program...[/yellow]")
                break
            
            if not org_name.strip():
                console.print("[red]Please enter a valid organization name.[/red]")
                continue
                
            fetcher.process_organization(org_name.strip())
            
            console.print("\n[bold]Would you like to analyze another organization?[/bold]")
            console.print("(Enter a new organization name or 'quit' to exit)\n")
            
        except KeyboardInterrupt:
            console.print("\n[yellow]Program interrupted by user. Exiting...[/yellow]")
            break
        except Exception as e:
            console.print(f"[red]An unexpected error occurred: {str(e)}[/red]")
            console.print("[yellow]You can try another organization or enter 'quit' to exit.[/yellow]\n")

if __name__ == "__main__":
    main()
