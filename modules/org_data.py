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
        Extracts {name, role} from the text, but ensures 'name' is cleaned up
        using spaCy's PERSON-labeled entity(ies). If multiple names or sub-entities
        appear, we pick the largest or first that spaCy finds.
        """
        members = []
        seen_names = {}

        def clean_text(text):
            """Remove reference markers [1], [2], etc. and unwanted punctuation."""
            text = re.sub(r'\[\d+\]', '', text)         # remove references like [1]
            text = re.sub(r'[^\w\s.,:\-\(\)]', ' ', text) # keep basic punctuation
            text = re.sub(r'\s+', ' ', text).strip()
            return text

        def store_member(name, role, snippet):
            """
            Add a member to `seen_names` dict so we can avoid duplicates
            and keep track of multiple roles/snippets.
            """
            if name not in seen_names:
                seen_names[name] = {
                    'roles': set(),
                    'snippets': []
                }
            seen_names[name]['roles'].add(role)
            seen_names[name]['snippets'].append(snippet)

        def extract_clean_name_and_role(sentence):
            """
            1. Locate approximate (name, role) match with regex.
            2. Run the 'name_candidate' through spaCy NER to get
            the actual PERSON-labeled sub-portion if it exists.
            3. Return a tuple (final_name, final_role).
            """
            doc = self.nlp(sentence)

            # Typical roles in politics/orgs
            roles_regex = (
                r'(president|chairman|chairperson|leader|secretary|'
                r'prime minister|chief minister|director|ceo|founder|'
                r'vice[\-\s]?president|treasurer|spokesperson|chief|head|coordinator)'
            )

            patterns = [
                # e.g. "X is the President"
                fr"(?P<name>[\w\s]+)\s+(?:is|was|became|serves\s+as|served\s+as)\s+(?:the\s+)?(?P<role>{roles_regex})",
                # e.g. "President X"
                fr"(?P<role>{roles_regex})\s+(?P<name>[\w\s]+)",
                # e.g. "X, the President"
                fr"(?P<name>[\w\s]+),\s+(?:the\s+)?(?P<role>{roles_regex})"
            ]

            for pat in patterns:
                for match in re.finditer(pat, sentence, flags=re.IGNORECASE):
                    # The raw chunk from the pattern
                    raw_name = match.group('name').strip()
                    raw_role = match.group('role').strip().title()

                    # Pass raw_name to spaCy to find PERSON-labeled sub-entities
                    candidate_doc = self.nlp(raw_name)
                    # Collect all PERSON entities within that chunk
                    person_ents = [ent for ent in candidate_doc.ents if ent.label_ == 'PERSON']

                    # If spaCy found no PERSON entity, skip
                    if not person_ents:
                        continue

                    # Otherwise, pick the "best" entity. For instance:
                    #   - You could pick the largest entity by length,
                    #   - Or just pick the first if you trust the ordering.
                    chosen_ent = max(person_ents, key=lambda e: len(e.text))

                    # Clean up the chosen entity's text
                    final_name = chosen_ent.text.strip()

                    # Optionally remove things like "Mr." or "Dr." if you want:
                    final_name = re.sub(
                        r'^(Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.|Shri\.|Smt\.)\s+', '', final_name, flags=re.IGNORECASE
                    ).strip()

                    return final_name, raw_role

            # Optional fallback: If no pattern matched, but we see a PERSON in the sentence + a known role:
            # (Be mindful that this can produce more false positives.)
            for ent in doc.ents:
                if ent.label_ == 'PERSON':
                    role_match = re.search(roles_regex, sentence, re.IGNORECASE)
                    if role_match:
                        final_role = role_match.group(1).title()
                        final_name = re.sub(
                            r'^(Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.|Shri\.|Smt\.)\s+', '', ent.text, flags=re.IGNORECASE
                        ).strip()
                        return final_name, final_role

            return None, None

        # ---- MAIN LOGIC ----
        wiki_content = clean_text(wiki_content)
        sentences = nltk.sent_tokenize(wiki_content)

        for sent in sentences:
            # if sentence is too short, skip
            if len(sent.split()) < 5:
                continue
            name_role = extract_clean_name_and_role(sent)
            if name_role and all(name_role):
                final_name, final_role = name_role
                # store snippet as a fallback bio if needed
                store_member(final_name, final_role, sent)

        # Convert from seen_names to a final list
        final_members = []
        for person_name, data in seen_names.items():
            # Combine all roles
            combined_roles = ", ".join(sorted(data['roles']))
            # Take the first snippet if you like (or merge them)
            sample_snippet = data['snippets'][0]
            if len(sample_snippet) > 500:
                sample_snippet = sample_snippet[:500] + "..."

            final_members.append({
                'name': person_name,
                'role': combined_roles,
                'bio': sample_snippet
            })

        return final_members


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