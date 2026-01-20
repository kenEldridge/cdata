"""Static site generator for cdata frontend."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from cdata.config import get_settings
from cdata.core.index import get_index_manager, DatasetEntry

# Shared styles
STYLES = '''
:root {
    --bg: #0d1117;
    --bg-secondary: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --success: #3fb950;
    --warning: #d29922;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
    max-width: 1400px;
    margin: 0 auto;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
header {
    margin-bottom: 2rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border);
}
h1 {
    font-size: 1.5rem;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
h1 span { color: var(--accent); }
h2 {
    font-size: 1.1rem;
    font-weight: 600;
    margin: 1.5rem 0 0.75rem 0;
    color: var(--text-muted);
}
.meta {
    color: var(--text-muted);
    font-size: 0.875rem;
    margin-top: 0.5rem;
}
.breadcrumb {
    font-size: 0.875rem;
    margin-bottom: 0.5rem;
}
.breadcrumb a { color: var(--text-muted); }
.stats {
    display: flex;
    gap: 1.5rem;
    margin: 1.5rem 0;
    flex-wrap: wrap;
}
.stat {
    background: var(--bg-secondary);
    padding: 1rem 1.5rem;
    border-radius: 6px;
    border: 1px solid var(--border);
}
.stat-value {
    font-size: 1.5rem;
    font-weight: 600;
    color: var(--accent);
}
.stat-label {
    color: var(--text-muted);
    font-size: 0.875rem;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 0.5rem;
    background: var(--bg-secondary);
    border-radius: 6px;
    overflow: hidden;
}
th, td {
    padding: 0.75rem 1rem;
    text-align: left;
    border-bottom: 1px solid var(--border);
}
th {
    background: var(--bg);
    font-weight: 600;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
}
tr:hover { background: rgba(88, 166, 255, 0.05); }
tr:last-child td { border-bottom: none; }
.name { color: var(--accent); font-weight: 500; }
.number { font-family: monospace; }
.truncate {
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.columns-list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 0.5rem;
}
.column-badge {
    background: var(--bg);
    border: 1px solid var(--border);
    padding: 0.25rem 0.75rem;
    border-radius: 9999px;
    font-size: 0.8rem;
    font-family: monospace;
}
.badge {
    display: inline-block;
    padding: 0.125rem 0.5rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 500;
}
.badge-raw { background: rgba(63, 185, 80, 0.2); color: var(--success); }
.badge-processed { background: rgba(210, 153, 34, 0.2); color: var(--warning); }
.empty {
    text-align: center;
    padding: 3rem;
    color: var(--text-muted);
}
.card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 1rem;
    margin-top: 0.5rem;
}
.preview-note {
    color: var(--text-muted);
    font-size: 0.8rem;
    margin-top: 0.5rem;
}
footer {
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
    color: var(--text-muted);
    font-size: 0.875rem;
}
@media (max-width: 768px) {
    body { padding: 1rem; }
    .stats { flex-direction: column; gap: 1rem; }
    table { font-size: 0.8rem; }
    th, td { padding: 0.5rem; }
    .truncate { max-width: 120px; }
}
'''

INDEX_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>cdata - Data Index</title>
    <style>{{styles}}</style>
</head>
<body>
    <header>
        <h1><span>cdata</span> Data Index</h1>
        <p class="meta">Generated: {{generated_at}}</p>
    </header>

    <div class="stats">
        <div class="stat">
            <div class="stat-value">{{total_datasets}}</div>
            <div class="stat-label">Datasets</div>
        </div>
        <div class="stat">
            <div class="stat-value">{{total_records}}</div>
            <div class="stat-label">Total Records</div>
        </div>
        <div class="stat">
            <div class="stat-value">{{total_size}}</div>
            <div class="stat-label">Total Size</div>
        </div>
    </div>

    {{content}}

    <footer>
        <p>cdata v0.1.0</p>
    </footer>
</body>
</html>
'''

DETAIL_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{name}} - cdata</title>
    <style>{{styles}}</style>
</head>
<body>
    <header>
        <p class="breadcrumb"><a href="index.html">cdata</a> / {{name}}</p>
        <h1><span>{{name}}</span></h1>
        {{#description}}<p class="meta">{{description}}</p>{{/description}}
    </header>

    <div class="stats">
        <div class="stat">
            <div class="stat-value">{{record_count}}</div>
            <div class="stat-label">Records</div>
        </div>
        <div class="stat">
            <div class="stat-value">{{file_size}}</div>
            <div class="stat-label">File Size</div>
        </div>
        <div class="stat">
            <div class="stat-value">{{column_count}}</div>
            <div class="stat-label">Columns</div>
        </div>
        <div class="stat">
            <div class="stat-value">{{fetch_count}}</div>
            <div class="stat-label">Fetches</div>
        </div>
    </div>

    <div class="card">
        <p><strong>Source:</strong> {{source_id}}</p>
        <p><strong>Location:</strong> <span class="badge {{badge_class}}">{{location}}</span></p>
        <p><strong>First Fetched:</strong> {{first_fetched}}</p>
        <p><strong>Last Updated:</strong> {{last_updated}}</p>
    </div>

    <h2>Columns</h2>
    <div class="columns-list">
        {{columns_html}}
    </div>

    <h2>Data Preview</h2>
    {{preview_html}}
    <p class="preview-note">Showing first {{preview_rows}} of {{record_count}} rows</p>

    <footer>
        <p><a href="index.html">&larr; Back to index</a></p>
    </footer>
</body>
</html>
'''


def format_size(bytes: int) -> str:
    """Format bytes as human readable size."""
    if bytes < 1024:
        return f"{bytes} B"
    elif bytes < 1024 * 1024:
        return f"{bytes / 1024:.1f} KB"
    elif bytes < 1024 * 1024 * 1024:
        return f"{bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes / (1024 * 1024 * 1024):.1f} GB"


def format_number(n: int) -> str:
    """Format number with commas."""
    return f"{n:,}"


def escape_html(s: str) -> str:
    """Escape HTML special characters."""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def get_data_preview(entry: DatasetEntry, max_rows: int = 20) -> tuple[pd.DataFrame, int]:
    """Get a preview of the dataset."""
    try:
        file_path = Path(entry.file_path)
        if file_path.exists() and file_path.suffix == ".parquet":
            df = pd.read_parquet(file_path)
            return df.head(max_rows), min(max_rows, len(df))
    except Exception:
        pass
    return pd.DataFrame(), 0


def generate_preview_table(df: pd.DataFrame) -> str:
    """Generate HTML table for data preview."""
    if df.empty:
        return '<div class="empty">No preview available</div>'

    # Limit columns displayed
    display_cols = list(df.columns)[:12]

    header = "<tr>" + "".join(f"<th>{escape_html(col)}</th>" for col in display_cols) + "</tr>"

    rows = []
    for _, row in df.iterrows():
        cells = []
        for col in display_cols:
            val = row[col]
            val_str = str(val) if pd.notna(val) else ""
            # Truncate long values
            if len(val_str) > 50:
                val_str = val_str[:47] + "..."
            cells.append(f'<td class="truncate" title="{escape_html(str(val))}">{escape_html(val_str)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")

    return f'''<table>
        <thead>{header}</thead>
        <tbody>{"".join(rows)}</tbody>
    </table>'''


def generate_dataset_page(entry: DatasetEntry, output_dir: Path) -> Path:
    """Generate a detail page for a dataset."""
    df, preview_rows = get_data_preview(entry)

    badge_class = "badge-raw" if entry.location == "raw" else "badge-processed"

    columns_html = "".join(
        f'<span class="column-badge">{escape_html(col)}</span>'
        for col in entry.columns
    )

    preview_html = generate_preview_table(df)

    html = DETAIL_TEMPLATE
    html = html.replace("{{styles}}", STYLES)
    html = html.replace("{{name}}", escape_html(entry.name))
    html = html.replace("{{description}}", escape_html(entry.description or ""))
    html = html.replace("{{#description}}", "" if entry.description else "<!--")
    html = html.replace("{{/description}}", "" if entry.description else "-->")
    html = html.replace("{{record_count}}", format_number(entry.record_count))
    html = html.replace("{{file_size}}", format_size(entry.file_size_bytes))
    html = html.replace("{{column_count}}", str(len(entry.columns)))
    html = html.replace("{{fetch_count}}", str(entry.fetch_count))
    html = html.replace("{{source_id}}", escape_html(entry.source_id))
    html = html.replace("{{location}}", entry.location)
    html = html.replace("{{badge_class}}", badge_class)
    html = html.replace("{{first_fetched}}", entry.first_fetched.strftime("%Y-%m-%d %H:%M"))
    html = html.replace("{{last_updated}}", entry.last_updated.strftime("%Y-%m-%d %H:%M"))
    html = html.replace("{{columns_html}}", columns_html)
    html = html.replace("{{preview_html}}", preview_html)
    html = html.replace("{{preview_rows}}", str(preview_rows))

    # Sanitize filename
    safe_name = entry.name.replace("/", "_").replace("\\", "_")
    page_path = output_dir / f"{safe_name}.html"
    page_path.write_text(html)

    return page_path


def generate_static_site(output_dir: Optional[Path] = None) -> Path:
    """Generate a static HTML site from the data index.

    Args:
        output_dir: Directory to write the site to. Defaults to data/site.

    Returns:
        Path to the generated index.html
    """
    settings = get_settings()
    output_dir = output_dir or settings.data_dir / "site"
    output_dir.mkdir(parents=True, exist_ok=True)

    index_manager = get_index_manager()
    datasets = index_manager.list_datasets()

    # Calculate stats
    total_records = sum(d.record_count for d in datasets)
    total_size = sum(d.file_size_bytes for d in datasets)

    # Generate individual dataset pages
    for entry in datasets:
        generate_dataset_page(entry, output_dir)

    # Generate table content for index
    if datasets:
        rows = []
        for d in datasets:
            badge_class = "badge-raw" if d.location == "raw" else "badge-processed"
            safe_name = d.name.replace("/", "_").replace("\\", "_")
            rows.append(f'''
            <tr>
                <td class="name"><a href="{safe_name}.html">{escape_html(d.name)}</a></td>
                <td><span class="badge {badge_class}">{d.location}</span></td>
                <td>{escape_html(d.source_id)}</td>
                <td class="number">{format_number(d.record_count)}</td>
                <td class="number">{format_size(d.file_size_bytes)}</td>
                <td>{d.last_updated.strftime("%Y-%m-%d %H:%M")}</td>
                <td class="number">{d.fetch_count}</td>
            </tr>''')

        content = f'''
        <table>
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Location</th>
                    <th>Source</th>
                    <th>Records</th>
                    <th>Size</th>
                    <th>Last Updated</th>
                    <th>Fetches</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>'''
    else:
        content = '<div class="empty">No datasets found. Run <code>cdata data rebuild-index</code> to build the index.</div>'

    # Render index template
    html = INDEX_TEMPLATE
    html = html.replace("{{styles}}", STYLES)
    html = html.replace("{{generated_at}}", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    html = html.replace("{{total_datasets}}", str(len(datasets)))
    html = html.replace("{{total_records}}", format_number(total_records))
    html = html.replace("{{total_size}}", format_size(total_size))
    html = html.replace("{{content}}", content)

    # Write index
    index_path = output_dir / "index.html"
    index_path.write_text(html)

    # Also copy the index.json for API-like access
    index_json = index_manager.index
    (output_dir / "index.json").write_text(
        json.dumps(index_json.model_dump(mode="json"), indent=2, default=str)
    )

    return index_path
