import os
from groq import Groq
from dotenv import load_dotenv
from typing import List, Dict
import json
from modules.search import search_and_extract  # Using the enhanced search function from previous code

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
class ReportGenerator:
    def __init__(self):
        self.client = Groq(api_key=GROQ_API_KEY)
        self.model = "llama-3.2-3b-preview"
        
    def _create_report_prompt(self, topic: str, research_data: List[Dict]) -> str:
        """
        Creates a structured prompt for the LLM to generate the report.
        """
        prompt = f"""
Based on the following research data about "{topic}", create a detailed, well-structured report.
Include a summary, key points, and analysis of the information. Organize the content in a clear,
professional format. Use the provided source materials but write in your own words.

Research Data:
"""
        
        for item in research_data:
            prompt += f"\nSource: {item['title']}\nURL: {item['link']}\n"
            prompt += f"Content Summary: {item['extracted_content'][:500]}...\n"
            
        prompt += """
Please structure the report with the following sections:
1. Executive Summary
2. Key Findings
3. Detailed Analysis
4. Conclusions
5. References

Ensure the report is factual, well-organized, and maintains a professional tone.
"""
        return prompt

    def _generate_with_llm(self, prompt: str) -> str:
        """
        Generates report content using the Groq API.
        """
        try:
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert report writer who creates clear, 
                        well-structured, and comprehensive reports. Focus on accuracy,
                        clarity, and professional presentation. Include citations when
                        referencing source material."""
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model=self.model,
            )
            return chat_completion.choices[0].message.content
        except Exception as e:
            return f"Error generating report: {str(e)}"

    def _format_report(self, content: str, references: List[Dict]) -> str:
        """
        Formats the final report with proper structure and references.
        """
        # Add formatting and structure to the raw LLM output
        formatted_report = content.strip()
        
        # Add references section if not already included by the LLM
        if "References" not in formatted_report:
            formatted_report += "\n\nReferences:\n"
            for ref in references:
                formatted_report += f"- {ref['title']}: {ref['link']}\n"
        
        return formatted_report

    def generate_detailed_report(self, topic: str, max_results: int = 3) -> Dict:
        """
        Generates a comprehensive report on the given topic.
        
        Args:
            topic: The topic to research and create a report about
            max_results: Maximum number of search results to include
            
        Returns:
            Dictionary containing the report and metadata
        """
        # Get enhanced search results
        search_results = search_and_extract(topic, max_results=max_results)
        
        if not search_results:
            return {
                "success": False,
                "report": f"No results found for '{topic}'.",
                "metadata": {
                    "sources": 0,
                    "topic": topic
                }
            }

        # Create the LLM prompt
        prompt = self._create_report_prompt(topic, search_results)
        
        # Generate report content
        report_content = self._generate_with_llm(prompt)
        
        # Format the final report
        final_report = self._format_report(
            report_content,
            [{"title": r["title"], "link": r["link"]} for r in search_results]
        )
        
        # Generate metadata
        metadata = {
            "topic": topic,
            "sources": len(search_results),
            "source_domains": list(set(r["domain"] for r in search_results)),
            "total_content_length": sum(r["metadata"]["length"] for r in search_results 
                                      if "metadata" in r and "length" in r["metadata"])
        }
        
        return {
            "success": True,
            "report": final_report,
            "metadata": metadata
        }

def save_report(report_data: Dict, output_file: str = "report.txt"):
    """
    Saves the generated report to a file.
    """
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            # Write report metadata
            f.write(f"Report Topic: {report_data['metadata']['topic']}\n")
            f.write(f"Sources Used: {report_data['metadata']['sources']}\n")
            f.write(f"Generated on: {os.path.basename(output_file)}\n")
            f.write("\n" + "="*50 + "\n\n")
            
            # Write main report content
            f.write(report_data['report'])
            
        return True
    except Exception as e:
        print(f"Error saving report: {e}")
        return False

# Example usage
if __name__ == "__main__":
    generator = ReportGenerator()
    topic = "python language"
    
    # Generate report
    report_data = generator.generate_detailed_report(topic)
    
    if report_data["success"]:
        # Save report to file
        if save_report(report_data, f"{topic.replace(' ', '_').lower()}_report.txt"):
            print(f"Report generated and saved successfully!")
            print("\nReport Preview:")
            print("="*50)
            print(report_data["report"][:500] + "...")
        else:
            print("Error saving report.")
    else:
        print("Error generating report:", report_data["report"])