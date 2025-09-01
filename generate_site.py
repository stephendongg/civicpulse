# generate_site.py
import pandas as pd
from datetime import datetime
import sys
import os

def load_data(csv_path):
    """Load and validate CSV data"""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    
    df = pd.read_csv(csv_path)
    required_columns = ['title', 'link', 'published', 'source', 'cin_label', 'cin_confidence']
    
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")
    
    df['published'] = pd.to_datetime(df['published'])
    return df

def get_category_config():
    """Define category mappings"""
    return {
        'risks_emergencies': 'Emergencies & Risks',
        'civics_governance': 'Civic Information',
        'politics_elections': 'Political Information',
        'transportation': 'Transportation',
        'health_welfare': 'Health & Welfare',
        'education': 'Education',
        'economy_housing_jobs': 'Economic Opportunities',
        'other': 'Other News'
    }

def generate_html_content(df, location="New York NY"):
    """Generate HTML content from DataFrame"""
    categories = get_category_config()
    last_updated = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
    
    html_parts = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '    <meta charset="UTF-8">',
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f'    <title>CivicPulse - {location}</title>',
        '    <link rel="stylesheet" href="style.css">',
        '</head>',
        '<body>',
        '    <div class="container">',
        f'        <header>',
        f'            <h1>CivicPulse - {location}</h1>',
        f'            <p class="last-updated">Last updated: {last_updated}</p>',
        f'        </header>',
        '        <main>'
    ]
    
    # Add content by category
    for category_id, category_name in categories.items():
        articles = df[df['cin_label'] == category_id].sort_values('published', ascending=False)
        
        if len(articles) > 0:
            html_parts.extend([
                f'            <section class="category">',
                f'                <h2>{category_name}</h2>'
            ])
            
            for _, article in articles.head(10).iterrows():
                published_date = article['published'].strftime('%Y-%m-%d %H:%M')
                confidence_class = get_confidence_class(article['cin_confidence'])
                
                html_parts.extend([
                    '                <article class="news-item">',
                    f'                    <h3><a href="{article["link"]}" target="_blank" rel="noopener">{article["title"]}</a></h3>',
                    f'                    <div class="meta">',
                    f'                        <span class="source">{article["source"]}</span>',
                    f'                        <span class="date">{published_date}</span>',
                    f'                        <span class="confidence {confidence_class}">Confidence: {article["cin_confidence"]:.1f}</span>',
                    f'                    </div>',
                    '                </article>'
                ])
            
            html_parts.append('            </section>')
    
    html_parts.extend([
        '        </main>',
        '    </div>',
        '</body>',
        '</html>'
    ])
    
    return '\n'.join(html_parts)

def get_confidence_class(confidence):
    """Return CSS class based on confidence level"""
    if confidence >= 0.8:
        return 'high'
    elif confidence >= 0.6:
        return 'medium'
    else:
        return 'low'

def generate_css():
    """Generate CSS file content"""
    return """/* CivicPulse Styles */
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    line-height: 1.6;
    color: #333;
    background-color: #f8f9fa;
}

.container {
    max-width: 1000px;
    margin: 0 auto;
    padding: 20px;
    background: white;
    min-height: 100vh;
}

header {
    border-bottom: 2px solid #e9ecef;
    margin-bottom: 2rem;
    padding-bottom: 1rem;
}

h1 {
    color: #212529;
    font-size: 2rem;
    margin-bottom: 0.5rem;
}

.last-updated {
    color: #6c757d;
    font-size: 0.9rem;
}

.category {
    margin-bottom: 3rem;
}

.category h2 {
    color: #495057;
    font-size: 1.5rem;
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid #dee2e6;
}

.news-item {
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid #f1f3f4;
}

.news-item:last-child {
    border-bottom: none;
}

.news-item h3 {
    margin-bottom: 0.5rem;
}

.news-item h3 a {
    color: #212529;
    text-decoration: none;
}

.news-item h3 a:hover {
    color: #0d6efd;
    text-decoration: underline;
}

.meta {
    display: flex;
    gap: 1rem;
    font-size: 0.875rem;
    color: #6c757d;
}

.confidence {
    padding: 0.2rem 0.5rem;
    border-radius: 0.25rem;
    font-size: 0.75rem;
    font-weight: 500;
}

.confidence.high {
    background-color: #d1e7dd;
    color: #0f5132;
}

.confidence.medium {
    background-color: #fff3cd;
    color: #664d03;
}

.confidence.low {
    background-color: #f8d7da;
    color: #842029;
}

@media (max-width: 768px) {
    .container {
        padding: 1rem;
    }
    
    h1 {
        font-size: 1.5rem;
    }
    
    .meta {
        flex-direction: column;
        gap: 0.25rem;
    }
}"""

def main():
    """Main execution function"""
    try:
        # Load data
        csv_file = 'local_news_labeled_New_York_NY.csv'
        df = load_data(csv_file)
        
        # Generate files
        html_content = generate_html_content(df)
        css_content = generate_css()
        
        # Write files
        with open('index.html', 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        with open('style.css', 'w', encoding='utf-8') as f:
            f.write(css_content)
        
        print("✅ Site generated successfully!")
        print("📁 Files created: index.html, style.css")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()