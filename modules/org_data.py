import sqlite3
import requests
from bs4 import BeautifulSoup
import wikipedia
from newsapi import NewsApiClient
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import re
import nltk
from nltk.tokenize import sent_tokenize
import spacy
load_dotenv()
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

class OrganizationDataFetcher:
    def __init__(self, db_path='political_orgs.db'):
        self.db_path = db_path
        self.setup_database()
        self.news_api = NewsApiClient(api_key=NEWS_API_KEY)
        
        # Initialize NLP tools
        try:
            self.nlp = spacy.load('en_core_web_sm')
        except OSError:
            # Download the model if it's not installed
            os.system('python -m spacy download en_core_web_sm')
            self.nlp = spacy.load('en_core_web_sm')
        
        # Download required NLTK data
        try:
            nltk.data.find('tokenizers/punkt')
        except LookupError:
            nltk.download('punkt')

    def setup_database(self):
        """Create the necessary database tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create organizations table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            description TEXT,
            founded_date TEXT,
            last_updated TIMESTAMP
        )
        ''')

        # Create members table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER,
            name TEXT,
            role TEXT,
            bio TEXT,
            last_updated TIMESTAMP,
            FOREIGN KEY (org_id) REFERENCES organizations (id)
        )
        ''')

        # Create news_articles table
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

    def fetch_wikipedia_data(self, org_name):
        """Fetch organization data from Wikipedia."""
        try:
            # Search Wikipedia
            page = wikipedia.page(org_name)
            return {
                'description': page.summary,
                'content': page.content,
                'url': page.url
            }
        except wikipedia.exceptions.PageError:
            return None
        except wikipedia.exceptions.DisambiguationError as e:
            # Take the first suggestion if disambiguation occurs
            try:
                page = wikipedia.page(e.options[0])
                return {
                    'description': page.summary,
                    'content': page.content,
                    'url': page.url
                }
            except:
                return None

    def fetch_news_data(self, org_name):
        """Fetch recent news articles about the organization."""
        try:
            # Fetch news from the last 30 days
            from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            news = self.news_api.get_everything(
                q=org_name,
                from_param=from_date,
                language='en',
                sort_by='relevancy'
            )
            return news.get('articles', [])
        except Exception as e:
            print(f"Error fetching news: {str(e)}")
            return []

    def extract_members(self, wiki_content):
        """
        Extract member information from Wikipedia content using multiple techniques:
        1. Section-based extraction
        2. Named Entity Recognition
        3. Pattern matching for roles and positions
        """
        members = []
        seen_names = set()  # Avoid duplicates

        def clean_text(text):
            """Clean and normalize text for processing"""
            # Remove references [1], [2], etc.
            text = re.sub(r'\[\d+\]', '', text)
            # Remove special characters but keep periods and commas
            text = re.sub(r'[^\w\s.,]', ' ', text)
            return text

        def extract_name_and_role(sentence):
            """Extract name and role from a sentence using NLP and patterns"""
            doc = self.nlp(sentence)
            
            # Common political and organizational roles
            roles = (r'(president|chairman|leader|secretary|minister|director|'
                    r'CEO|founder|vice[\-\s]president|treasurer|spokesperson|'
                    r'chief|head|coordinator)')
            
            # Patterns for role identification (using raw strings)
            role_patterns = [
                fr"(?P<name>[\w\s]+)\s+(?:is|was|serves\s+as|served\s+as)\s+(?:the\s+)?(?P<role>{roles})",
                fr"(?P<role>{roles})\s+(?P<name>[\w\s]+)",
                fr"(?P<name>[\w\s]+),\s+(?:the\s+)?(?P<role>{roles})"
            ]

            # Check for pattern matches
            for pattern in role_patterns:
                matches = re.finditer(pattern, sentence, re.IGNORECASE)
                for match in matches:
                    name = match.group('name').strip()
                    role = match.group('role').strip()
                    
                    # Verify name using NER
                    name_doc = self.nlp(name)
                    if any(ent.label_ == 'PERSON' for ent in name_doc.ents):
                        return name, role.title()
            
            # Fallback to NER for names without clear role patterns
            for ent in doc.ents:
                if ent.label_ == 'PERSON':
                    # Look for role keywords near the person mention
                    role_match = re.search(roles, sentence, re.IGNORECASE)
                    if role_match:
                        return ent.text, role_match.group(1).title()
            
            return None, None

        # Split content into sections
        sections = wiki_content.split('\n==')
        relevant_sections = ['leadership', 'members', 'structure', 'organization', 'personnel', 'key people']

        def process_section(section_text):
            """Process a section of text to extract member information"""
            cleaned_text = clean_text(section_text)
            sentences = sent_tokenize(cleaned_text)
            
            for sentence in sentences:
                if len(sentence.split()) < 5:  # Skip very short sentences
                    continue
                    
                name, role = extract_name_and_role(sentence)
                if name and name not in seen_names:
                    seen_names.add(name)
                    members.append({
                        'name': name,
                        'role': role,
                        'bio': sentence.strip()
                    })

        # First process the introduction (usually contains key members)
        intro_section = sections[0]
        process_section(intro_section)

        # Then process other relevant sections
        for section in sections[1:]:
            section_title = section.split('\n')[0].lower()
            if any(keyword in section_title for keyword in relevant_sections):
                process_section(section)

        # Post-process the extracted members
        processed_members = []
        for member in members:
            if member['role']:  # Only include members with identified roles
                # Clean up the data
                processed_member = {
                    'name': re.sub(r'\s+', ' ', member['name']).strip(),  # Remove extra spaces
                    'role': member['role'].replace('The ', '').strip(),
                    'bio': member['bio'][:500] if len(member['bio']) > 500 else member['bio']  # Limit bio length
                }
                
                # Remove common titles from names (using raw strings)
                name = processed_member['name']
                for title in ['Dr.', 'Mr.', 'Mrs.', 'Ms.', 'Prof.', 'Sir', 'Dame']:
                    name = re.sub(fr'^{title}\s+', '', name)
                processed_member['name'] = name
                
                processed_members.append(processed_member)

        return processed_members

    def store_organization_data(self, org_name, wiki_data, news_articles, members):
        """Store all collected data in the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Insert organization
            cursor.execute('''
            INSERT OR REPLACE INTO organizations (name, description, last_updated)
            VALUES (?, ?, ?)
            ''', (org_name, wiki_data['description'] if wiki_data else None, datetime.now()))
            
            org_id = cursor.lastrowid

            # Insert members
            for member in members:
                cursor.execute('''
                INSERT INTO members (org_id, name, role, bio, last_updated)
                VALUES (?, ?, ?, ?, ?)
                ''', (org_id, member['name'], member.get('role'), member.get('bio'), datetime.now()))

            # Insert news articles
            for article in news_articles:
                cursor.execute('''
                INSERT INTO news_articles (org_id, title, content, source, published_date, url)
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
            print(f"Error storing data: {str(e)}")
            conn.rollback()
        finally:
            conn.close()

    def process_organization(self, org_name):
        """Main method to process an organization."""
        print(f"Processing organization: {org_name}")
        
        # Fetch Wikipedia data
        wiki_data = self.fetch_wikipedia_data(org_name)
        if wiki_data:
            print("Successfully fetched Wikipedia data")
            members = self.extract_members(wiki_data['content'])
        else:
            print("No Wikipedia data found")
            members = []

        # Fetch news articles
        news_articles = self.fetch_news_data(org_name)
        print(f"Found {len(news_articles)} news articles")

        # Store all data
        self.store_organization_data(org_name, wiki_data, news_articles, members)
        print("Data storage complete")

def main():
    fetcher = OrganizationDataFetcher()
    
    while True:
        org_name = input("\nEnter organization name (or 'quit' to exit): ")
        if org_name.lower() == 'quit':
            break
            
        try:
            fetcher.process_organization(org_name)
        except Exception as e:
            print(f"Error processing organization: {str(e)}")
        
        print("\nProcessing complete. Would you like to search for another organization?")

if __name__ == "__main__":
    main()