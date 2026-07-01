"""Convert news digest markdown output to styled HTML email."""

import re
import sys
from pathlib import Path


_SPACER_ROW = '<tr><td style="height: 16px; line-height: 16px; font-size: 1px;" height="16">&nbsp;</td></tr>'


def _convert_to_html(md_text: str) -> str:
    lines = md_text.split("\n")
    parts: list[str] = []
    in_article = False
    needs_spacer = False

    for line in lines:
        stripline = line.strip()

        # Skip header decoration lines
        if stripline.startswith("=") or stripline.startswith("World News Digest"):
            continue

        # Region heading: # 🌎 North America
        if stripline.startswith("# "):
            if needs_spacer:
                parts.append(_SPACER_ROW)
            needs_spacer = True
            parts.append(f'<tr><td class="region-header">{stripline[2:]}</td></tr>')
            continue

        # Article item: 1. **[Title](url)** or 1. **[Title](SourceName)**
        m = re.match(r"\d+\.\s+\*\*\[(.+?)\]\((.+?)\)\*\*", stripline)
        if m:
            if in_article:
                parts.append("</table></td></tr>")
            if needs_spacer:
                parts.append(_SPACER_ROW)
            needs_spacer = True
            title, url_or_source = m.group(1), m.group(2)
            if url_or_source.startswith("http"):
                title_html = f'<a href="{url_or_source}">{title}</a>'
            else:
                title_html = f"{title} <span class=\"source\">({url_or_source})</span>"
            parts.append(
                f'<tr><td class="article-card">'
                f'<table cellpadding="0" cellspacing="0" class="article-table">'
                f'<tr><td class="article-title">{title_html}</td></tr>'
            )
            in_article = True
            continue

        # Sub-bullet:    - **label**: text
        m = re.match(r"\s*-\s+\*\*(.+?)\*\*:\s*(.*)", stripline)
        if m:
            label, text = m.group(1), m.group(2)
            css_class = "article-summary" if "요약" in label else "article-significance"
            parts.append(
                f'<tr><td class="{css_class}">'
                f"<strong>{label}:</strong> {text}</td></tr>"
            )
            continue

        # Error / empty
        if stripline and "[!" in stripline:
            if in_article:
                parts.append("</table></td></tr>")
                in_article = False
            parts.append(f'<tr><td class="error">{stripline}</td></tr>')
            continue

        if not stripline and in_article:
            parts.append("</table></td></tr>")
            in_article = False

    if in_article:
        parts.append("</table></td></tr>")

    return "\n".join(parts)


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{
    margin: 0; padding: 0;
    background-color: #f4f4f6;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
      'Helvetica Neue', Arial, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    color: #1a1a2e;
  }}
  .wrapper {{
    max-width: 960px;
    margin: 0 auto;
    padding: 16px 8px;
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
  }}
  .header {{
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    padding: 28px 24px;
    text-align: center;
    border-radius: 12px 12px 0 0;
  }}
  .header h1 {{
    margin: 0;
    font-size: 22px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 0.5px;
  }}
  .header .sub {{
    margin: 6px 0 0;
    font-size: 13px;
    color: #a0aec0;
  }}
  .content {{
    background: #ffffff;
    padding: 0 20px;
    border-radius: 0 0 12px 12px;
  }}
  .region-header {{
    padding: 28px 0 8px;
    font-size: 20px;
    font-weight: 700;
    color: #1a1a2e;
    border-bottom: 2px solid #e2e8f0;
  }}
  .region-header:first-of-type {{
    padding-top: 8px;
  }}
  .article-card {{
    padding: 0;
  }}
  .article-table {{
    margin: 12px 0 12px;
    padding: 16px;
    background: #f8fafc;
    border-radius: 8px;
    border-left: 4px solid #3b82f6;
  }}
  .article-title {{
    font-size: 16px;
    font-weight: 600;
    padding-bottom: 6px;
  }}
  .article-title a {{
    color: #1a56db;
    text-decoration: none;
  }}
  .article-title a:hover {{
    text-decoration: underline;
  }}
  .source {{
    font-size: 12px;
    color: #64748b;
    font-weight: 400;
  }}
  .article-summary {{
    font-size: 14px;
    color: #334155;
    padding: 4px 0;
    line-height: 1.7;
  }}
  .article-significance {{
    font-size: 13px;
    color: #64748b;
    padding: 4px 0 0;
  }}
  .error {{
    padding: 12px 16px;
    margin: 8px 0;
    background: #fef2f2;
    border-radius: 8px;
    border-left: 4px solid #ef4444;
    color: #991b1b;
    font-size: 13px;
  }}
  .footer {{
    padding: 20px;
    text-align: center;
    font-size: 12px;
    color: #94a3b8;
  }}
  .footer a {{
    color: #64748b;
  }}
  @media only screen and (max-width: 480px) {{
    .wrapper {{ padding: 8px 4px; }}
    .header h1 {{ font-size: 18px; }}
    .content {{ padding: 0 12px; }}
  }}
</style>
</head>
<body>
<div class="wrapper">
  <table cellpadding="0" cellspacing="0">
    <tr><td class="header">
      <h1>🌐 World News Digest</h1>
      <p class="sub">{date} &middot; 7 regions &middot; AI-summarized</p>
    </td></tr>
    <tr><td class="content">
      <table cellpadding="0" cellspacing="0">
{body}
      </table>
    </td></tr>
    <tr><td class="footer">
      <p><a href="{url}">View in browser</a></p>
    </td></tr>
  </table>
</div>
</body>
</html>"""


def render(md_path: str, html_path: str, run_url: str = "", date_str: str = "") -> None:
    md_text = Path(md_path).read_text(encoding="utf-8")
    body_html = _convert_to_html(md_text)

    if not date_str:
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")

    html = _HTML_TEMPLATE.format(body=body_html, date=date_str, url=run_url)

    # CSS 인라인화: Naver Mail 등 <style>을 제거하는 클라이언트 대응
    try:
        from premailer import transform
        html = transform(html)
    except ImportError:
        pass

    Path(html_path).write_text(html, encoding="utf-8")
    print(f"HTML email saved to {html_path}")


if __name__ == "__main__":
    md_path = sys.argv[1] if len(sys.argv) > 1 else "news_digest.md"
    html_path = sys.argv[2] if len(sys.argv) > 2 else "news_digest.html"
    run_url = sys.argv[3] if len(sys.argv) > 3 else ""
    date_str = sys.argv[4] if len(sys.argv) > 4 else ""
    render(md_path, html_path, run_url, date_str)
